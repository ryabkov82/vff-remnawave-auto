#!/usr/bin/env python3
"""Structural checks for dedicated sub.portalbase.link Nginx reverse proxy."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles/remnawave_subscription_page_next"
TEMPLATE = ROLE / "templates/nginx-sub-portalbase.conf.j2"
NEXT_TEMPLATE = ROLE / "templates/nginx-sub-next.conf.j2"
PROD_TEMPLATE = (
    REPO_ROOT / "roles/remnawave_subscription_page/templates/nginx-subscription.conf.j2"
)
TASKS = ROLE / "tasks/nginx_portalbase.yml"
DEFAULTS = ROLE / "defaults/main.yml"
HANDLERS = ROLE / "handlers/main.yml"
PLAYBOOK = REPO_ROOT / "playbooks/subscription.yml"
MAKEFILE = REPO_ROOT / "Makefile"
INVENTORY = REPO_ROOT / "inventory/group_vars/subscription/main.yml"
ANSIBLE_PLAYBOOK = REPO_ROOT / ".venv/bin/ansible-playbook"

FORBIDDEN_PATTERNS = (
    "remnawave_sub_next_aliases",
    "remnawave_sub_portalbase_aliases",
    "sub.vpn-for-friends.com",
    "sub-next.vpn-for-friends.com",
    "SUB_PUBLIC_DOMAIN",
    "remnawave_subscription_upstream_target",
)

REGULAR_HTTPS_LOCATION = """    location / {
        proxy_http_version 1.1;
        proxy_redirect off;
        proxy_pass http://remnawave-subscription-page-portalbase;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $host;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }"""

INCY_ASSERT_NAME = "Assert subscription portalbase INCY prefix is valid"

INVALID_INCY_PREFIXES = (
    "",
    "incy/",
    "/incy",
    "/",
    "/.well-known/acme-challenge/",
    "/healthz",
    "/healthz/",
    "/incy/?x/",
    "/incy/#frag/",
    "/incy /",
    " /incy/",
    "/incy/\t",
)


def _task_block(content: str, marker: str) -> str:
    start = content.index(f"- name: {marker}")
    tail = content[start + 1 :]
    match = re.search(r"\n- name: ", tail)
    end = start + 1 + match.start() if match else len(content)
    return content[start:end]


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in {"1", "true", "yes", "on"}


def _render(**overrides) -> str:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), autoescape=False)
    env.filters["bool"] = _bool
    ctx = {
        "remnawave_sub_portalbase_domain": "sub.portalbase.link",
        "remnawave_sub_portalbase_upstream_host": "127.0.0.1",
        "remnawave_sub_portalbase_upstream_port": 3011,
        "remnawave_sub_portalbase_nginx_webroot": "/var/www/letsencrypt",
        "remnawave_sub_portalbase_ssl_ready": True,
        "remnawave_sub_portalbase_ssl_fullchain": (
            "/etc/letsencrypt/live/sub.portalbase.link/fullchain.pem"
        ),
        "remnawave_sub_portalbase_ssl_privkey": (
            "/etc/letsencrypt/live/sub.portalbase.link/privkey.pem"
        ),
        "remnawave_sub_portalbase_incy_enabled": False,
        "remnawave_sub_portalbase_incy_prefix": "/incy/",
    }
    ctx.update(overrides)
    return env.get_template("nginx-sub-portalbase.conf.j2").render(**ctx)


def _incy_assert_task() -> dict:
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    for task in tasks:
        if task.get("name") == INCY_ASSERT_NAME:
            return task
    raise AssertionError(f"missing task: {INCY_ASSERT_NAME}")


def _run_incy_assert(*, enabled: bool, prefix: str) -> subprocess.CompletedProcess[str]:
    playbook = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "vars": {
                "remnawave_sub_portalbase_incy_enabled": enabled,
                "remnawave_sub_portalbase_incy_prefix": prefix,
            },
            "tasks": [_incy_assert_task()],
        }
    ]
    with tempfile.TemporaryDirectory(prefix="incy-assert-") as tmp:
        tmp_path = Path(tmp)
        play_path = tmp_path / "incy_assert.yml"
        cfg_path = tmp_path / "ansible.cfg"
        play_path.write_text(yaml.safe_dump(playbook, sort_keys=False), encoding="utf-8")
        cfg_path.write_text(
            "\n".join(
                [
                    "[defaults]",
                    "retry_files_enabled = False",
                    "host_key_checking = False",
                    "interpreter_python = auto_silent",
                    "stdout_callback = unixy",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["ANSIBLE_CONFIG"] = str(cfg_path)
        env.pop("ANSIBLE_VAULT_PASSWORD_FILE", None)
        return subprocess.run(
            [
                str(ANSIBLE_PLAYBOOK),
                "-i",
                "localhost,",
                "-c",
                "local",
                str(play_path),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


class SubscriptionPortalbaseNginxTest(unittest.TestCase):
    def test_template_exists_and_targets_portalbase_domain(self) -> None:
        self.assertTrue(TEMPLATE.is_file())
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{{ remnawave_sub_portalbase_domain }}", content)
        self.assertIn("remnawave-subscription-page-portalbase", content)
        self.assertIn("proxy_set_header X-Forwarded-Proto https", content)
        self.assertIn("proxy_set_header Host $host", content)
        self.assertNotIn("remnawave-subscription-page-next", content)

    def test_template_has_http_bootstrap_and_https_block(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("listen 80", content)
        self.assertIn("/.well-known/acme-challenge/", content)
        self.assertIn("remnawave_sub_portalbase_ssl_ready", content)
        self.assertIn("listen 443 ssl", content)
        self.assertIn("{{ remnawave_sub_portalbase_ssl_fullchain }}", content)

    def test_tasks_issue_cert_only_when_missing(self) -> None:
        content = TASKS.read_text(encoding="utf-8")
        self.assertIn("remnawave_sub_portalbase_certificate_was_missing", content)
        self.assertIn("certbot certonly", content)
        self.assertIn("--webroot", content)
        self.assertIn("-d {{ remnawave_sub_portalbase_domain }}", content)
        self.assertIn("Apply subscription portalbase HTTP bootstrap before certificate issuance", content)
        self.assertIn("Render subscription portalbase HTTPS Nginx vhost after certificate issuance", content)

    def test_tasks_use_credential_independent_health_checks(self) -> None:
        content = TASKS.read_text(encoding="utf-8")
        self.assertNotIn("remnawave_sub_portalbase_healthcheck_short_uuid", content)
        self.assertNotIn("healthcheck_short_uuid", content)

        upstream = _task_block(content, "Wait for subscription portalbase upstream runtime")
        self.assertIn("remnawave_sub_portalbase_upstream_host", upstream)
        self.assertIn("remnawave_sub_portalbase_upstream_port", upstream)
        self.assertIn("not ansible_check_mode", upstream)

        public = _task_block(
            content,
            "Public HTTPS health check via subscription portalbase /healthz",
        )
        self.assertIn('url: "https://{{ remnawave_sub_portalbase_domain }}/healthz"', public)
        self.assertIn("status_code: 200", public)
        self.assertIn("validate_certs: true", public)
        self.assertIn("return_content: true", public)
        self.assertIn("| trim) == 'ok'", public)
        self.assertIn("not ansible_check_mode", public)
        self.assertNotIn("text/html", public)
        flush_pos = content.index(
            "Apply subscription portalbase HTTPS Nginx configuration after certificate issuance"
        )
        self.assertGreater(content.index("Wait for subscription portalbase upstream runtime"), flush_pos)
        self.assertGreater(
            content.index("Public HTTPS health check via subscription portalbase /healthz"),
            content.index("Wait for subscription portalbase upstream runtime"),
        )

    def test_handlers_run_nginx_t_before_reload(self) -> None:
        content = HANDLERS.read_text(encoding="utf-8")
        self.assertIn("Reload subscription portalbase Nginx", content)
        self.assertIn("nginx -t", content)

    def test_defaults_are_fixed_domain_not_alias_list(self) -> None:
        content = DEFAULTS.read_text(encoding="utf-8")
        defaults = yaml.safe_load(content)
        self.assertIn('remnawave_sub_portalbase_domain: "sub.portalbase.link"', content)
        self.assertIn("remnawave_sub_portalbase_upstream_port: 3011", content)
        self.assertNotIn("remnawave_sub_portalbase_healthcheck_short_uuid", content)
        self.assertNotIn("remnawave_sub_portalbase_healthcheck_short_uuid", defaults)
        self.assertIn("remnawave_sub_next_healthcheck_short_uuid", defaults)
        for pattern in ("remnawave_sub_next_aliases", "remnawave_sub_portalbase_aliases"):
            self.assertNotIn(pattern, content)

    def test_playbook_and_makefile_wire_dedicated_tag(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertIn("Deploy subscription portalbase Nginx reverse proxy", playbook)
        self.assertIn("tasks_from: nginx_portalbase", playbook)
        self.assertIn("sub_portalbase", playbook)
        self.assertIn("sub-portalbase:", makefile)
        self.assertIn("--tags sub_portalbase", makefile)

    def test_inventory_enables_portalbase_without_touching_production_domains(self) -> None:
        content = INVENTORY.read_text(encoding="utf-8")
        inventory = yaml.safe_load(content)
        self.assertIn("remnawave_sub_portalbase_nginx_enabled: true", content)
        self.assertIn('remnawave_sub_portalbase_domain: "sub.portalbase.link"', content)
        self.assertIn("remnawave_sub_public_domain: sub.vpn-for-friends.com", content)
        self.assertIn('remnawave_sub_next_domain: "sub-next.vpn-for-friends.com"', content)
        self.assertNotIn("remnawave_sub_portalbase_healthcheck_short_uuid", content)
        self.assertNotIn("remnawave_sub_portalbase_healthcheck_short_uuid", inventory)
        self.assertEqual(inventory["remnawave_sub_next_healthcheck_short_uuid"], "VZLHkrKwsj0Qs82e")

    def test_portalbase_files_do_not_reference_forbidden_concepts(self) -> None:
        for path in (TEMPLATE, TASKS):
            content = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_PATTERNS:
                self.assertNotIn(pattern, content, f"{path} contains {pattern}")

    def test_defaults_disable_incy_with_explicit_prefix(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
        self.assertIs(defaults["remnawave_sub_portalbase_incy_enabled"], False)
        self.assertEqual(defaults["remnawave_sub_portalbase_incy_prefix"], "/incy/")

    def test_production_inventory_enables_incy_prefix(self) -> None:
        inventory = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
        self.assertIs(inventory["remnawave_sub_portalbase_incy_enabled"], True)
        self.assertEqual(inventory["remnawave_sub_portalbase_incy_prefix"], "/incy/")
        self.assertEqual(inventory["remnawave_sub_public_domain"], "sub.vpn-for-friends.com")
        self.assertEqual(inventory["remnawave_sub_next_domain"], "sub-next.vpn-for-friends.com")
        self.assertEqual(inventory["remnawave_sub_portalbase_upstream_host"], "127.0.0.1")
        self.assertEqual(inventory["remnawave_sub_portalbase_upstream_port"], 3011)

    def test_template_has_conditional_incy_location(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("remnawave_sub_portalbase_incy_enabled | bool", content)
        self.assertIn(
            "location ^~ {{ remnawave_sub_portalbase_incy_prefix }}",
            content,
        )
        self.assertIn(
            "proxy_pass http://remnawave-subscription-page-portalbase/;",
            content,
        )
        self.assertIn('add_header hide-url "1" always;', content)
        self.assertNotIn("/incy-test/", content)

    def test_regular_location_does_not_contain_hide_url(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(REGULAR_HTTPS_LOCATION, content)
        start = content.index(REGULAR_HTTPS_LOCATION)
        regular = content[start : start + len(REGULAR_HTTPS_LOCATION)]
        self.assertNotIn("hide-url", regular)
        self.assertNotIn(
            "proxy_pass http://remnawave-subscription-page-portalbase/;",
            regular,
        )

    def test_hide_url_is_not_server_level(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        https_server = content.split("listen 443 ssl", 1)[1]
        before_incy = https_server.split("remnawave_sub_portalbase_incy_enabled", 1)[0]
        self.assertNotIn("hide-url", before_incy)
        after_regular = https_server.split("location / {", 1)[1]
        self.assertNotIn("hide-url", after_regular)

    def test_http_acme_tls_and_healthz_are_unchanged_relative_to_incy(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        http_server = content.split("listen 80", 1)[1].split("listen 443 ssl", 1)[0]
        self.assertIn("/.well-known/acme-challenge/", http_server)
        self.assertNotIn("hide-url", http_server)
        self.assertNotIn("remnawave_sub_portalbase_incy_prefix", http_server)
        self.assertIn("location = /healthz", content)
        self.assertNotIn("/incy-test/", content)

    def test_incy_is_isolated_from_other_subscription_vhosts(self) -> None:
        for path in (NEXT_TEMPLATE, PROD_TEMPLATE):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("remnawave_sub_portalbase_incy", content, path)
            self.assertNotIn("hide-url", content, path)
            self.assertNotIn("/incy/", content, path)
            self.assertNotIn("/incy-test/", content, path)
            self.assertNotIn("remnawave-subscription-page-portalbase", content, path)

    def test_incy_does_not_change_portalbase_upstream_target(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "server {{ remnawave_sub_portalbase_upstream_host }}:{{ remnawave_sub_portalbase_upstream_port }};",
            content,
        )
        self.assertEqual(content.count("upstream remnawave-subscription-page-portalbase"), 1)
        rendered = _render(remnawave_sub_portalbase_incy_enabled=True)
        self.assertIn("server 127.0.0.1:3011;", rendered)
        self.assertIn("proxy_pass http://remnawave-subscription-page-portalbase;", rendered)
        self.assertIn("proxy_pass http://remnawave-subscription-page-portalbase/;", rendered)

    def test_render_disabled_omits_incy_location(self) -> None:
        rendered = _render(remnawave_sub_portalbase_incy_enabled=False)
        self.assertNotIn("location ^~ /incy/", rendered)
        self.assertNotIn("hide-url", rendered)
        self.assertIn(REGULAR_HTTPS_LOCATION, rendered)
        self.assertNotIn("/incy-test/", rendered)

    def test_render_enabled_adds_incy_location_only(self) -> None:
        rendered = _render(remnawave_sub_portalbase_incy_enabled=True)
        self.assertIn("location ^~ /incy/", rendered)
        self.assertIn("proxy_pass http://remnawave-subscription-page-portalbase/;", rendered)
        self.assertIn('add_header hide-url "1" always;', rendered)
        self.assertEqual(rendered.count("hide-url"), 1)
        self.assertIn(REGULAR_HTTPS_LOCATION, rendered)
        regular_start = rendered.index(REGULAR_HTTPS_LOCATION)
        regular = rendered[regular_start : regular_start + len(REGULAR_HTTPS_LOCATION)]
        self.assertNotIn("hide-url", regular)
        self.assertNotIn("/incy-test/", rendered)

    def test_incy_validation_task_is_fail_fast_and_check_mode_safe(self) -> None:
        content = TASKS.read_text(encoding="utf-8")
        block = _task_block(content, INCY_ASSERT_NAME)
        self.assertIn("ansible.builtin.assert", block)
        self.assertIn("remnawave_sub_portalbase_incy_enabled | bool", block)
        self.assertNotIn("not ansible_check_mode", block)
        for needle in (
            "trim | length > 0",
            "[0] == '/'",
            "[-1] == '/'",
            "!= '/'",
            "/.well-known/acme-challenge/",
            "/healthz",
            "'?' not in remnawave_sub_portalbase_incy_prefix",
            "'#' not in remnawave_sub_portalbase_incy_prefix",
            r"is not search('\s')",
        ):
            self.assertIn(needle, block)
        apt_pos = content.index("Ensure Nginx and certbot packages are installed")
        self.assertLess(content.index(INCY_ASSERT_NAME), apt_pos)


@unittest.skipUnless(ANSIBLE_PLAYBOOK.is_file(), "local ansible-playbook is not available")
class SubscriptionPortalbaseIncyValidationTest(unittest.TestCase):
    def test_valid_prefix_passes(self) -> None:
        result = _run_incy_assert(enabled=True, prefix="/incy/")
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_invalid_prefixes_fail_fast(self) -> None:
        for prefix in INVALID_INCY_PREFIXES:
            with self.subTest(prefix=prefix):
                result = _run_incy_assert(enabled=True, prefix=prefix)
                self.assertNotEqual(
                    result.returncode,
                    0,
                    f"prefix={prefix!r} should fail\nstdout={result.stdout}\nstderr={result.stderr}",
                )

    def test_disabled_feature_skips_invalid_prefix(self) -> None:
        result = _run_incy_assert(enabled=False, prefix="")
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout}\nstderr={result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
