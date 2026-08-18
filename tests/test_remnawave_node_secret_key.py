#!/usr/bin/env python3
"""Structural tests for remnawave_node SECRET_KEY auto-resolve."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles/remnawave_node"
MAIN = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
SECRET = (ROLE / "tasks/secret_key.yml").read_text(encoding="utf-8")
PREPARE = (ROLE / "tasks/prepare.yml").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
UPGRADE_NODES = (REPO / "roles/remnawave_upgrade/tasks/upgrade_nodes.yml").read_text(
    encoding="utf-8"
)
README = (REPO / "README.md").read_text(encoding="utf-8")
NODE_DOCS = (REPO / "docs/remnawave_node.md").read_text(encoding="utf-8")
EXAMPLE = (REPO / "inventory/host_vars/de-fra-1/main.example.yml").read_text(
    encoding="utf-8"
)
REGISTER = (REPO / "roles/remnawave_register_node/tasks/main.yml").read_text(
    encoding="utf-8"
)
PREFLIGHT_TASKS = (REPO / "roles/remnawave_api_preflight/tasks/main.yml").read_text(
    encoding="utf-8"
)
PREFLIGHT_DEFAULTS = yaml.safe_load(
    (REPO / "roles/remnawave_api_preflight/defaults/main.yml").read_text(encoding="utf-8")
)


def _task_index(source: str, name: str) -> int:
    marker = f"- name: {name}"
    pos = source.find(marker)
    if pos < 0:
        raise AssertionError(f"missing task: {name}")
    return pos


def _task_block(source: str, name: str) -> str:
    marker = f"- name: {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing task: {name}")
    rest = source[start:]
    nxt = rest.find("\n- name:", len(marker))
    return rest if nxt < 0 else rest[:nxt]


class SecretKeyImportOrderTests(unittest.TestCase):
    def test_secret_key_imported_before_prepare(self) -> None:
        self.assertIn("import_tasks: secret_key.yml", MAIN)
        self.assertIn("import_tasks: prepare.yml", MAIN)
        self.assertLess(
            MAIN.find("import_tasks: secret_key.yml"),
            MAIN.find("import_tasks: prepare.yml"),
        )
        self.assertIn("Remnawave Node | Resolve SECRET_KEY", MAIN)
        self.assertIn("Remnawave Node | Prepare host", MAIN)


class SecretKeyPrecedenceTests(unittest.TestCase):
    def test_explicit_key_skips_env_and_api(self) -> None:
        detect = _task_block(SECRET, "Remnawave Node | Detect explicit SECRET_KEY")
        self.assertIn("remnawave_secret_key | default('') | trim | length", detect)
        self.assertIn("_rw_node_has_secret_key", detect)
        self.assertIn("_rw_node_preserve_existing_env: false", detect)
        for name in (
            "Remnawave Node | Stat existing .env for SECRET_KEY",
            "Remnawave Node | Read existing .env SECRET_KEY",
            "Remnawave Node | GET /api/keygen",
        ):
            block = _task_block(SECRET, name)
            self.assertIn("not (_rw_node_has_secret_key | bool)", block)

    def test_existing_env_used_before_api(self) -> None:
        self.assertLess(
            _task_index(SECRET, "Remnawave Node | Read existing .env SECRET_KEY"),
            _task_index(SECRET, "Remnawave Node | GET /api/keygen"),
        )
        self.assertLess(
            _task_index(SECRET, "Remnawave Node | Use SECRET_KEY from existing .env"),
            _task_index(SECRET, "Remnawave Node | GET /api/keygen"),
        )
        slurp = _task_block(SECRET, "Remnawave Node | Read existing .env SECRET_KEY")
        self.assertIn("ansible.builtin.slurp:", slurp)
        self.assertIn("remnawave_node_secret_key_env_path", slurp)
        parse = _task_block(SECRET, "Remnawave Node | Parse SECRET_KEY from existing .env")
        self.assertIn("SECRET_KEY=", parse)
        self.assertIn("b64decode", parse)
        self.assertIn("regex_replace('^SECRET_KEY=', '')", parse)
        self.assertNotIn("regex_search('(?m)^SECRET_KEY=([^", parse)

    def test_second_run_does_not_call_keygen_when_env_has_key(self) -> None:
        use_env = _task_block(SECRET, "Remnawave Node | Use SECRET_KEY from existing .env")
        self.assertIn("_rw_node_has_secret_key: true", use_env)
        self.assertIn("_rw_node_preserve_existing_env: true", use_env)
        keygen = _task_block(SECRET, "Remnawave Node | GET /api/keygen")
        self.assertIn("not (_rw_node_has_secret_key | bool)", keygen)
        self.assertIn("remnawave_node_secret_key_auto | bool", keygen)
        self.assertIn("remnawave_node_write_env | bool", keygen)


def _role_parse_expression() -> str:
    block = yaml.safe_load(
        _task_block(SECRET, "Remnawave Node | Parse SECRET_KEY from existing .env")
    )
    task = block[0] if isinstance(block, list) else block
    expr = (task.get("ansible.builtin.set_fact") or task.get("set_fact") or {})[
        "_rw_node_env_secret"
    ]
    if not isinstance(expr, str) or "{{" not in expr:
        raise AssertionError("parse task is not a Jinja expression")
    return expr


def _parse_env_secret(env_text: str):
    loader = DataLoader()
    templar = Templar(loader=loader)
    templar.available_variables = {
        "_rw_node_env_slurp": {
            "content": base64.b64encode(env_text.encode("utf-8")).decode("ascii"),
        }
    }
    return templar.template(_role_parse_expression(), fail_on_undefined=True)


class SecretKeyEnvParseFilterTests(unittest.TestCase):
    """Evaluate the role Jinja with real Ansible regex_search / regex_replace."""

    def test_env_secret_is_parsed_as_string(self) -> None:
        secret = _parse_env_secret("NODE_PORT=2222\nSECRET_KEY=abc123\n")
        self.assertEqual(secret, "abc123")
        self.assertIsInstance(secret, str)

    def test_quoted_env_secret_is_unquoted(self) -> None:
        self.assertEqual(_parse_env_secret('SECRET_KEY="abc123"\n'), "abc123")

    def test_missing_secret_key_is_empty_and_does_not_raise(self) -> None:
        secret = _parse_env_secret("NODE_PORT=2222\n")
        self.assertEqual(secret, "")
        keygen = _task_block(SECRET, "Remnawave Node | GET /api/keygen")
        use_env = _task_block(SECRET, "Remnawave Node | Use SECRET_KEY from existing .env")
        self.assertIn("(_rw_node_env_secret | default('') | length) > 0", use_env)
        self.assertIn("not (_rw_node_has_secret_key | bool)", keygen)

    def test_capture_group_regex_search_returns_list_not_string(self) -> None:
        loader = DataLoader()
        templar = Templar(loader=loader)
        captured = templar.template(
            "{{ 'SECRET_KEY=abc123' | regex_search('(?m)^SECRET_KEY=([^\\r\\n]+)', '\\1') }}",
            fail_on_undefined=True,
        )
        self.assertEqual(captured, ["abc123"])
        self.assertIsInstance(captured, list)
        broken = templar.template(
            "{{ 'SECRET_KEY=abc123' | regex_search('(?m)^SECRET_KEY=([^\\r\\n]+)', '\\1') | default('', true) | trim }}",
            fail_on_undefined=True,
        )
        self.assertNotEqual(broken, "abc123")


class SecretKeyApiContractTests(unittest.TestCase):
    def test_keygen_endpoint_method_and_response_field(self) -> None:
        keygen = _task_block(SECRET, "Remnawave Node | GET /api/keygen")
        self.assertIn("remnawave_node_secret_key_api_path", keygen)
        self.assertEqual(DEFAULTS["remnawave_node_secret_key_api_path"], "/api/keygen")
        self.assertIn("method: GET", keygen)
        self.assertIn("Authorization: \"Bearer {{ remnawave_panel_api_token }}\"", keygen)
        self.assertIn("Accept: application/json", keygen)
        self.assertIn("delegate_to: localhost", keygen)
        self.assertIn("become: false", keygen)
        self.assertNotRegex(PREFLIGHT_TASKS, r"path:\s*/(?:api/)?keygen\b")
        self.assertIn("keygen:get", PREFLIGHT_DEFAULTS["rw_api_preflight_required_scopes"])

        set_key = _task_block(SECRET, "Remnawave Node | Set remnawave_secret_key from keygen")
        self.assertIn("response.secretKey", set_key)
        self.assertIn("remnawave_secret_key:", set_key)

    def test_keygen_safe_error_does_not_print_response(self) -> None:
        fail = _task_block(SECRET, "Remnawave Node | Fail keygen without leaking response")
        self.assertIn("Remnawave keygen failed (HTTP", fail)
        self.assertIn("keygen:get", fail)
        self.assertNotIn("secretKey", fail)
        self.assertNotIn("_rw_node_keygen.json", fail)
        self.assertNotIn("_rw_node_keygen.content", fail)

    def test_keygen_consumers_ignore_skipped_register(self) -> None:
        for name in (
            "Remnawave Node | Fail keygen without leaking response",
            "Remnawave Node | Assert keygen returned secretKey",
            "Remnawave Node | Set remnawave_secret_key from keygen",
        ):
            block = _task_block(SECRET, name)
            self.assertIn("_rw_node_keygen is defined", block, msg=name)
            self.assertIn("_rw_node_keygen is not skipped", block, msg=name)


class SecretKeyNoLogTests(unittest.TestCase):
    def test_secret_bearing_tasks_have_no_log(self) -> None:
        secret_tasks = (
            "Remnawave Node | Detect explicit SECRET_KEY",
            "Remnawave Node | Read existing .env SECRET_KEY",
            "Remnawave Node | Parse SECRET_KEY from existing .env",
            "Remnawave Node | Use SECRET_KEY from existing .env",
            "Remnawave Node | GET /api/keygen",
            "Remnawave Node | Assert keygen returned secretKey",
            "Remnawave Node | Set remnawave_secret_key from keygen",
            "Remnawave Node | Assert SECRET_KEY is resolved",
        )
        for name in secret_tasks:
            block = _task_block(SECRET, name)
            self.assertIn("no_log: true", block, msg=name)

    def test_write_env_has_no_log(self) -> None:
        write = _task_block(PREPARE, "Write .env if requested")
        self.assertIn("no_log: true", write)
        self.assertIn("remnawave_node_env_content", write)
        self.assertIn("remnawave_node_write_env | bool", write)
        self.assertIn("not (_rw_node_preserve_existing_env | default(false) | bool)", write)
        self.assertNotIn("b64decode", write)
        self.assertNotIn("slurp", write)
        self.assertNotIn("BEGIN ", write)


class SecretKeyCheckModeTests(unittest.TestCase):
    def test_check_mode_does_not_call_keygen(self) -> None:
        refuse = _task_block(SECRET, "Remnawave Node | Refuse keygen in check mode")
        self.assertIn("ansible_check_mode", refuse)
        self.assertIn("SECRET_KEY is absent and cannot be generated in check mode.", refuse)
        keygen = _task_block(SECRET, "Remnawave Node | GET /api/keygen")
        self.assertIn("not ansible_check_mode", keygen)
        self.assertNotIn("check_mode: false", keygen)


class SecretKeySafetyTests(unittest.TestCase):
    def test_does_not_write_inventory_or_vault(self) -> None:
        for needle in (
            "copy:",
            "template:",
            "lineinfile:",
            "blockinfile:",
            "vault.yml",
            "host_vars",
        ):
            self.assertNotIn(needle, SECRET)

    def test_does_not_validate_secret_key_format(self) -> None:
        for needle in (
            "BEGIN CERTIFICATE",
            "BEGIN PRIVATE",
            "is_json",
            "from_json",
            "b64decode | length",
            "validate_secret",
        ):
            self.assertNotIn(needle, SECRET)
            self.assertNotIn(needle, PREPARE)

    def test_defaults_enable_auto_and_keep_write_env_false(self) -> None:
        self.assertTrue(DEFAULTS["remnawave_node_secret_key_auto"])
        self.assertFalse(DEFAULTS["remnawave_node_write_env"])
        self.assertEqual(
            DEFAULTS["remnawave_node_secret_key_env_path"],
            "{{ remnawave_node_dir }}/.env",
        )

    def test_upgrade_still_skips_env_write(self) -> None:
        self.assertIn("remnawave_node_write_env: false", UPGRADE_NODES)
        keygen = _task_block(SECRET, "Remnawave Node | GET /api/keygen")
        self.assertIn("remnawave_node_write_env | bool", keygen)

    def test_register_node_unchanged(self) -> None:
        self.assertNotIn("secret_key.yml", REGISTER)
        self.assertNotIn("/api/keygen", REGISTER)
        self.assertNotIn("remnawave_node_secret_key_auto", REGISTER)

    def test_docs_say_vault_optional_for_new_nodes(self) -> None:
        self.assertIn("больше не", README)
        self.assertIn("обязателен", README)
        self.assertIn("GET /api/keygen", README)
        self.assertIn("приоритет", README)
        self.assertIn("GET /api/keygen", NODE_DOCS)
        self.assertIn("высший приоритет", NODE_DOCS)
        self.assertIn("перезаписывает", NODE_DOCS)
        self.assertIn("не перезаписывает", README)
        self.assertIn("optional for new nodes", EXAMPLE)
        self.assertIn("SECRET_KEY={{ remnawave_secret_key }}", EXAMPLE)


SKIPPED_KEYGEN = {
    "changed": False,
    "skipped": True,
    "skip_reason": "Conditional result was False",
}
HTTP_403_KEYGEN = {"changed": False, "skipped": False, "status": 403}
HTTP_200_KEYGEN = {
    "changed": False,
    "skipped": False,
    "status": 200,
    "json": {"response": {"secretKey": "from-api-key"}},
}


def _task_when(name: str, source: str = SECRET) -> list[str]:
    data = yaml.safe_load(_task_block(source, name))
    task = data[0] if isinstance(data, list) else data
    when = task["when"]
    if isinstance(when, str):
        return [when]
    return list(when)


def _eval_when(when_list: list[str], variables: dict) -> bool:
    loader = DataLoader()
    templar = Templar(loader=loader)
    templar.available_variables = variables
    return all(
        bool(templar.template("{{ (" + cond + ") | bool }}", fail_on_undefined=True))
        for cond in when_list
    )


def _host_task_result(report: dict, name: str) -> dict:
    for play in report.get("plays") or []:
        for task in play.get("tasks") or []:
            full = (task.get("task") or {}).get("name") or ""
            if full != name and not full.endswith(name) and f": {name}" not in full:
                continue
            hosts = task.get("hosts") or {}
            if hosts:
                return next(iter(hosts.values()))
    names = [
        (task.get("task") or {}).get("name")
        for play in report.get("plays") or []
        for task in play.get("tasks") or []
    ]
    raise AssertionError(f"missing task result: {name}; saw={names}")


class _KeygenHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = getattr(self.server, "keygen_status", 200)
        if self.path.rstrip("/") != "/api/keygen":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"message":"forbidden"}'
        if status == 200:
            body = b'{"response":{"secretKey":"from-api-key"}}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        del fmt, args


def _write_env_when() -> list:
    return _task_when("Write .env if requested", PREPARE)


def _run_secret_key_role(
    *,
    env_text: str | None,
    http_status: int | None,
    remnawave_secret_key: str = "",
    env_content: str = "NODE_PORT=2222\nSECRET_KEY={{ remnawave_secret_key }}\n",
    include_write_env: bool = False,
    workdir: Path | None = None,
) -> dict:
    tmp = workdir or Path(tempfile.mkdtemp(prefix="rw-secret-key-"))
    env_path = tmp / ".env"
    if env_text is not None:
        env_path.write_text(env_text, encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _KeygenHandler)
    server.keygen_status = 200 if http_status is None else http_status
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    panel_url = f"http://127.0.0.1:{server.server_address[1]}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(f"{panel_url}/api/keygen", timeout=2).read()
    except urllib.error.HTTPError:
        pass

    playbook = {
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "become": False,
        "vars": {
            "remnawave_secret_key": remnawave_secret_key,
            "remnawave_node_write_env": True,
            "remnawave_node_secret_key_auto": True,
            "remnawave_node_dir": str(tmp),
            "remnawave_node_secret_key_env_path": str(env_path),
            "remnawave_node_env_content": env_content,
            "remnawave_panel_url": panel_url,
            "remnawave_panel_api_token": "test-token",
            "remnawave_node_secret_key_api_path": "/api/keygen",
        },
        "tasks": [
            {
                "name": "run secret_key.yml",
                "ansible.builtin.include_role": {
                    "name": "remnawave_node",
                    "tasks_from": "secret_key.yml",
                },
            }
        ],
    }
    if include_write_env:
        playbook["tasks"].append(
            {
                "name": "Write .env if requested",
                "when": _write_env_when(),
                "ansible.builtin.copy": {
                    "dest": "{{ remnawave_node_dir }}/.env",
                    "content": "{{ remnawave_node_env_content }}",
                    "mode": "0640",
                },
                "no_log": True,
            }
        )
    play_path = tmp / "secret_key_probe.yml"
    cfg_path = tmp / "ansible.cfg"
    play_path.write_text(yaml.safe_dump([playbook], sort_keys=False), encoding="utf-8")
    cfg_path.write_text(
        "\n".join(
            [
                "[defaults]",
                f"roles_path = {REPO / 'roles'}",
                "retry_files_enabled = False",
                "host_key_checking = False",
                "interpreter_python = auto_silent",
                "jinja2_native = True",
                "stdout_callback = json",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(cfg_path)
    env["ANSIBLE_STDOUT_CALLBACK"] = "json"
    env["ANSIBLE_LOAD_CALLBACK_PLUGINS"] = "1"
    env.pop("ANSIBLE_VAULT_PASSWORD_FILE", None)
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    try:
        completed = subprocess.run(
            [
                str(REPO / ".venv/bin/ansible-playbook"),
                "-i",
                "localhost,",
                "-c",
                "local",
                str(play_path),
            ],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    stdout = completed.stdout
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"ansible-playbook json parse failed rc={completed.returncode}\n"
            f"stdout={stdout}\nstderr={completed.stderr}"
        ) from exc
    report["_rc"] = completed.returncode
    report["_stderr"] = completed.stderr
    report["_stdout"] = stdout
    report["_env_path"] = str(env_path)
    report["_workdir"] = str(tmp)
    report["_env_text"] = (
        env_path.read_text(encoding="utf-8") if env_path.exists() else None
    )
    return report


class SecretKeySkippedRegisterTests(unittest.TestCase):
    def test_templar_skipped_register_does_not_look_like_http_failure(self) -> None:
        fail_when = _task_when("Remnawave Node | Fail keygen without leaking response")
        assert_when = _task_when("Remnawave Node | Assert keygen returned secretKey")
        set_when = _task_when("Remnawave Node | Set remnawave_secret_key from keygen")
        skipped_vars = {"_rw_node_keygen": SKIPPED_KEYGEN}
        self.assertFalse(_eval_when(fail_when, skipped_vars))
        self.assertFalse(_eval_when(assert_when, skipped_vars))
        self.assertFalse(_eval_when(set_when, skipped_vars))
        self.assertTrue(_eval_when(fail_when, {"_rw_node_keygen": HTTP_403_KEYGEN}))
        self.assertFalse(_eval_when(assert_when, {"_rw_node_keygen": HTTP_403_KEYGEN}))
        self.assertFalse(_eval_when(set_when, {"_rw_node_keygen": HTTP_403_KEYGEN}))
        self.assertFalse(_eval_when(fail_when, {"_rw_node_keygen": HTTP_200_KEYGEN}))
        self.assertTrue(_eval_when(assert_when, {"_rw_node_keygen": HTTP_200_KEYGEN}))
        self.assertTrue(_eval_when(set_when, {"_rw_node_keygen": HTTP_200_KEYGEN}))

    def test_existing_env_skips_keygen_and_does_not_fail_unknown(self) -> None:
        report = _run_secret_key_role(
            env_text="NODE_PORT=2222\nSECRET_KEY=abc123\n",
            http_status=None,
        )
        self.assertEqual(report["_rc"], 0, msg=report["_stderr"])
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        fail = _host_task_result(report, "Remnawave Node | Fail keygen without leaking response")
        resolved = _host_task_result(report, "Remnawave Node | Assert SECRET_KEY is resolved")
        self.assertTrue(get.get("skipped"))
        self.assertTrue(fail.get("skipped"))
        self.assertFalse(resolved.get("skipped", False))
        self.assertFalse(resolved.get("failed", False))
        self.assertNotIn("HTTP unknown", report["_stdout"])
        self.assertNotIn("HTTP unknown", report["_stderr"])

    def test_keygen_http_error_runs_fail_task(self) -> None:
        report = _run_secret_key_role(env_text=None, http_status=403)
        self.assertNotEqual(report["_rc"], 0)
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        fail = _host_task_result(report, "Remnawave Node | Fail keygen without leaking response")
        self.assertFalse(get.get("skipped", False))
        self.assertFalse(fail.get("skipped", False))
        self.assertTrue(fail.get("failed", False))
        blob = fail.get("msg") or report["_stdout"]
        self.assertIn("HTTP 403", str(blob))
        self.assertNotIn("HTTP unknown", str(blob))

    def test_keygen_http_200_sets_secret(self) -> None:
        report = _run_secret_key_role(env_text=None, http_status=200)
        self.assertEqual(report["_rc"], 0, msg=report["_stderr"])
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        fail = _host_task_result(report, "Remnawave Node | Fail keygen without leaking response")
        verify = _host_task_result(report, "Remnawave Node | Assert keygen returned secretKey")
        set_secret = _host_task_result(report, "Remnawave Node | Set remnawave_secret_key from keygen")
        resolved = _host_task_result(report, "Remnawave Node | Assert SECRET_KEY is resolved")
        self.assertFalse(get.get("skipped", False))
        self.assertTrue(fail.get("skipped"))
        self.assertFalse(verify.get("skipped", False))
        self.assertFalse(set_secret.get("skipped", False))
        self.assertFalse(resolved.get("failed", False))
        self.assertNotIn("HTTP unknown", report["_stdout"])


class SecretKeyPreserveExistingEnvTests(unittest.TestCase):
    def test_templar_write_env_respects_preserve_flag(self) -> None:
        write_when = _write_env_when()
        self.assertFalse(
            _eval_when(
                write_when,
                {
                    "remnawave_node_write_env": True,
                    "_rw_node_preserve_existing_env": True,
                },
            )
        )
        self.assertTrue(
            _eval_when(
                write_when,
                {
                    "remnawave_node_write_env": True,
                    "_rw_node_preserve_existing_env": False,
                },
            )
        )
        self.assertFalse(
            _eval_when(
                write_when,
                {
                    "remnawave_node_write_env": False,
                    "_rw_node_preserve_existing_env": False,
                },
            )
        )

    def test_existing_env_skips_keygen_and_write(self) -> None:
        original = "NODE_PORT=2222\nSECRET_KEY=abc123-keep-me\nOTHER=stay\n"
        report = _run_secret_key_role(
            env_text=original,
            http_status=200,
            env_content="SECRET_KEY=SHOULD-NOT-WRITE\n",
            include_write_env=True,
        )
        self.assertEqual(report["_rc"], 0, msg=report["_stderr"])
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        write = _host_task_result(report, "Write .env if requested")
        self.assertTrue(get.get("skipped"))
        self.assertTrue(write.get("skipped"))
        self.assertEqual(report["_env_text"], original)

    def test_absent_env_runs_keygen_and_write(self) -> None:
        report = _run_secret_key_role(
            env_text=None,
            http_status=200,
            include_write_env=True,
        )
        self.assertEqual(report["_rc"], 0, msg=report["_stderr"])
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        write = _host_task_result(report, "Write .env if requested")
        self.assertFalse(get.get("skipped", False))
        self.assertFalse(write.get("skipped", False))
        self.assertIn("SECRET_KEY=from-api-key", report["_env_text"] or "")

    def test_env_without_secret_runs_keygen_and_write(self) -> None:
        report = _run_secret_key_role(
            env_text="NODE_PORT=2222\n",
            http_status=200,
            include_write_env=True,
        )
        self.assertEqual(report["_rc"], 0, msg=report["_stderr"])
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        write = _host_task_result(report, "Write .env if requested")
        self.assertFalse(get.get("skipped", False))
        self.assertFalse(write.get("skipped", False))
        self.assertIn("SECRET_KEY=from-api-key", report["_env_text"] or "")

    def test_explicit_vault_key_writes_desired_env(self) -> None:
        report = _run_secret_key_role(
            env_text="SECRET_KEY=old-on-disk\n",
            http_status=200,
            remnawave_secret_key="vault-key-value",
            include_write_env=True,
        )
        self.assertEqual(report["_rc"], 0, msg=report["_stderr"])
        get = _host_task_result(report, "Remnawave Node | GET /api/keygen")
        write = _host_task_result(report, "Write .env if requested")
        self.assertTrue(get.get("skipped"))
        self.assertFalse(write.get("skipped", False))
        self.assertIn("SECRET_KEY=vault-key-value", report["_env_text"] or "")

    def test_second_provisioning_does_not_change_existing_env(self) -> None:
        long_key = "k" * 180
        original = f"NODE_PORT=2222\nSECRET_KEY={long_key}\nKEEP=yes\n"
        first = _run_secret_key_role(
            env_text=original,
            http_status=200,
            env_content="SECRET_KEY=truncated-should-not-apply\n",
            include_write_env=True,
        )
        self.assertEqual(first["_rc"], 0, msg=first["_stderr"])
        self.assertEqual(first["_env_text"], original)
        second = _run_secret_key_role(
            env_text=None,
            http_status=200,
            env_content="SECRET_KEY=truncated-should-not-apply\n",
            include_write_env=True,
            workdir=Path(first["_workdir"]),
        )
        self.assertEqual(second["_rc"], 0, msg=second["_stderr"])
        get = _host_task_result(second, "Remnawave Node | GET /api/keygen")
        write = _host_task_result(second, "Write .env if requested")
        self.assertTrue(get.get("skipped"))
        self.assertTrue(write.get("skipped"))
        self.assertEqual(second["_env_text"], original)
        self.assertEqual(len(long_key), 180)


if __name__ == "__main__":
    unittest.main()
