#!/usr/bin/env python3
"""Tests for extra static HAProxy SNI routes and AntiBlock origin DNS wiring."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "roles/remnawave_node_haproxy/filter_plugins"))

from haproxy_extra_sni import (  # noqa: E402
    extra_sni_backend_line,
    extra_sni_backends,
    prepare_extra_sni_routes,
    relative_dns_record_name,
)

ROLE = REPO / "roles/remnawave_node_haproxy"
TASKS = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
HANDLERS = (ROLE / "handlers/main.yml").read_text(encoding="utf-8")
TEMPLATE = ROLE / "templates/haproxy_node.cfg.j2"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
PLAY = REPO / "playbooks/antiblock_cdn.yml"
NODES_PLAY = (REPO / "playbooks/nodes.yml").read_text(encoding="utf-8")
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
HOSTS_INI = (REPO / "inventory/hosts.ini").read_text(encoding="utf-8")
GROUP_CDN = yaml.safe_load(
    (REPO / "inventory/group_vars/antiblock_cdn_nodes.yml").read_text(encoding="utf-8")
)
HOST_DE_FRA_2 = yaml.safe_load(
    (REPO / "inventory/host_vars/de-fra-2/antiblock_cdn.yml").read_text(encoding="utf-8")
)
ANTIBLOCK_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(encoding="utf-8")
)
CF_DNS_TASKS = (REPO / "roles/cf_dns/tasks/main.yml").read_text(encoding="utf-8")

ORIGIN_ROUTE = {
    "name": "xhttp_cdn",
    "sni": "origin-cdn.digitalstreamers.xyz",
    "backend_host": "127.0.0.1",
    "backend_port": 8447,
    "backend_name": "be_xhttp_8447",
    "server_name": "xhttp_local",
    "send_proxy_v2": False,
    "check": True,
    "timeout_connect": "5s",
    "timeout_server": "5m",
}


def _include_tasks(play: dict, role_name: str | None = None) -> list[dict]:
    out: list[dict] = []
    for task in play.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        include = task.get("ansible.builtin.include_role") or task.get("include_role")
        if not isinstance(include, dict):
            continue
        if role_name is None or include.get("name") == role_name:
            out.append(task)
    return out


def _plays(path: Path = PLAY) -> list[dict]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return loaded
    return [loaded]


def _role_names(play: dict) -> list[str]:
    names: list[str] = []
    for item in play.get("roles") or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            names.append(str(item.get("role") or item.get("name")))
    for task in play.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        include = task.get("ansible.builtin.include_role") or task.get("include_role")
        if isinstance(include, dict) and include.get("name"):
            names.append(str(include["name"]))
        elif isinstance(include, str):
            names.append(include)
    return names


def _makefile_block(target: str) -> str:
    marker = f"{target}:"
    start = MAKEFILE.find(marker)
    if start < 0:
        raise AssertionError(f"missing make target {target}")
    rest = MAKEFILE[start:]
    nxt = rest.find("\n\n")
    return rest if nxt < 0 else rest[:nxt]


def _group_members(section: str) -> list[str]:
    members: list[str] = []
    in_section = False
    for line in HOSTS_INI.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1] == section
            continue
        if in_section and stripped and not stripped.startswith("#"):
            members.append(stripped.split()[0])
    return members


def _unique(seq):
    return list(dict.fromkeys(list(seq)))


def _backend_stanza(rendered: str, name: str) -> str:
    marker = f"\nbackend {name}"
    start = rendered.find(marker)
    if start < 0:
        if rendered.startswith(f"backend {name}"):
            rest = rendered
        else:
            raise AssertionError(f"missing {marker!r} in rendered config")
    else:
        rest = rendered[start + 1 :]
    nxt = rest.find("\nbackend ")
    if nxt >= 0:
        rest = rest[:nxt]
    listen = rest.find("\nlisten ")
    if listen >= 0:
        rest = rest[:listen]
    return rest


def _directive_lines(stanza: str) -> list[str]:
    return [line.strip() for line in stanza.splitlines() if line.strip()]


def _render(**kwargs) -> str:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), autoescape=False)
    env.filters["unique"] = _unique
    env.filters["haproxy_extra_sni_backends"] = extra_sni_backends
    env.filters["haproxy_extra_sni_backend_line"] = extra_sni_backend_line
    ctx = {
        "_sni_port_map": {},
        "_haproxy_extra_sni_routes": [],
        "nginx_https_bind": "127.0.0.1:4443",
    }
    ctx.update(kwargs)
    return env.get_template("haproxy_node.cfg.j2").render(**ctx)


class ExtraSniValidationTests(unittest.TestCase):
    def test_empty_routes_are_ok(self) -> None:
        result = prepare_extra_sni_routes([], {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["routes"], [])

    def test_empty_sni_rejected(self) -> None:
        result = prepare_extra_sni_routes(
            [{"name": "xhttp_cdn", "sni": "", "backend_port": 8447}],
            {},
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("SNI is required" in err for err in result["errors"]))

    def test_invalid_port_rejected(self) -> None:
        result = prepare_extra_sni_routes(
            [{"name": "xhttp_cdn", "sni": "origin.example", "backend_port": 0}],
            {},
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("invalid backend_port" in err for err in result["errors"]))

    def test_duplicate_identical_route_is_noop(self) -> None:
        result = prepare_extra_sni_routes([ORIGIN_ROUTE, dict(ORIGIN_ROUTE)], {})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["routes"]), 1)

    def test_same_sni_different_backend_is_collision(self) -> None:
        other = dict(ORIGIN_ROUTE)
        other["backend_port"] = 9443
        result = prepare_extra_sni_routes([ORIGIN_ROUTE, other], {})
        self.assertFalse(result["ok"])
        self.assertTrue(any("multiple extra backends" in err for err in result["errors"]))

    def test_collision_with_dynamic_sni_map(self) -> None:
        result = prepare_extra_sni_routes(
            [ORIGIN_ROUTE],
            {"origin-cdn.digitalstreamers.xyz": 443},
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("dynamic Remnawave Host SNI map" in err for err in result["errors"]))
        self.assertEqual(result["routes"], [])

    def test_send_proxy_line(self) -> None:
        prepared = prepare_extra_sni_routes([ORIGIN_ROUTE], {})["routes"][0]
        line = extra_sni_backend_line(prepared)
        self.assertEqual(line, "server xhttp_local 127.0.0.1:8447 check")
        self.assertNotIn("send-proxy-v2", line)
        enabled = dict(prepared)
        enabled["send_proxy_v2"] = True
        self.assertIn("send-proxy-v2", extra_sni_backend_line(enabled))
        self.assertTrue(line.startswith("server "))
        self.assertIn("check", line)


class HaproxyTemplateTests(unittest.TestCase):
    def test_origin_sni_renders_backend_8447_without_proxy(self) -> None:
        prepared = prepare_extra_sni_routes(
            [ORIGIN_ROUTE],
            {"edge-fra-02.digitalstreamers.xyz": 8443},
        )
        self.assertTrue(prepared["ok"])
        rendered = _render(
            _sni_port_map={"edge-fra-02.digitalstreamers.xyz": 8443},
            _haproxy_extra_sni_routes=prepared["routes"],
        )
        self.assertIn("acl SNI_XHTTP_CDN req.ssl_sni -i origin-cdn.digitalstreamers.xyz", rendered)
        self.assertIn("use_backend be_xhttp_8447 if SNI_XHTTP_CDN", rendered)
        self.assertIn("backend be_xhttp_8447", rendered)
        self.assertIn("timeout connect 5s", rendered)
        self.assertIn("timeout server 5m", rendered)
        self.assertIn("server xhttp_local 127.0.0.1:8447 check", rendered)
        origin_backend = _backend_stanza(rendered, "be_xhttp_8447")
        self.assertNotIn("send-proxy-v2", origin_backend)
        xray_backend = _backend_stanza(rendered, "be_xray_8443")
        self.assertIn("send-proxy-v2", xray_backend)

    def test_extra_backend_timeouts_render_as_separate_lines(self) -> None:
        prepared = prepare_extra_sni_routes([ORIGIN_ROUTE], {})["routes"]
        rendered = _render(_haproxy_extra_sni_routes=prepared)
        stanza = _backend_stanza(rendered, "be_xhttp_8447")
        lines = _directive_lines(stanza)
        self.assertEqual(
            lines,
            [
                "backend be_xhttp_8447",
                "mode tcp",
                "timeout connect 5s",
                "timeout server 5m",
                "server xhttp_local 127.0.0.1:8447 check",
            ],
        )
        self.assertNotIn("send-proxy-v2", stanza)
        self.assertFalse(
            any(
                "timeout" in line and line.strip().startswith("mode ")
                for line in stanza.splitlines()
            ),
            stanza,
        )
        extra_block = TEMPLATE.read_text(encoding="utf-8").split(
            "haproxy_extra_sni_backends"
        )[1]
        self.assertNotIn("{%-", extra_block)

    def test_extra_backend_without_timeouts_stays_valid(self) -> None:
        route = dict(ORIGIN_ROUTE)
        route["timeout_connect"] = ""
        route["timeout_server"] = ""
        prepared = prepare_extra_sni_routes([route], {})["routes"]
        rendered = _render(_haproxy_extra_sni_routes=prepared)
        stanza = _backend_stanza(rendered, "be_xhttp_8447")
        lines = _directive_lines(stanza)
        self.assertEqual(
            lines,
            [
                "backend be_xhttp_8447",
                "mode tcp",
                "server xhttp_local 127.0.0.1:8447 check",
            ],
        )
        self.assertFalse(any(line.startswith("timeout ") for line in lines))
        self.assertNotIn("send-proxy-v2", stanza)

    def test_send_proxy_present_only_when_true(self) -> None:
        route = dict(ORIGIN_ROUTE)
        route["send_proxy_v2"] = True
        prepared = prepare_extra_sni_routes([route], {})["routes"]
        rendered = _render(_haproxy_extra_sni_routes=prepared)
        origin_backend = rendered.split("\nbackend be_xhttp_8447", 1)[1].split("listen stats", 1)[0]
        self.assertIn("send-proxy-v2", origin_backend)

    def test_empty_extra_routes_keep_dynamic_only(self) -> None:
        rendered = _render(_sni_port_map={"edge.example": 8443})
        self.assertNotIn("SNI_XHTTP_CDN", rendered)
        self.assertNotIn("be_xhttp_8447", rendered)
        self.assertIn("be_xray_8443", rendered)

    def test_validate_before_handler_and_reload_semantics(self) -> None:
        self.assertIn('validate: "{{ haproxy_validate_cmd }}"', TASKS)
        self.assertIn("/usr/sbin/haproxy -c -f %s", str(DEFAULTS["haproxy_validate_cmd"]))
        self.assertIn("notify: Reload HAProxy", TASKS)
        self.assertLess(TASKS.find("Fail if extra SNI routes"), TASKS.find("Render haproxy.cfg"))
        self.assertLess(TASKS.find("validate:"), TASKS.find("notify: Reload HAProxy"))
        self.assertIn("state: reloaded", HANDLERS)
        self.assertNotIn("state: restarted", HANDLERS)
        self.assertIn("Restart HAProxy", HANDLERS)
        self.assertEqual(DEFAULTS["haproxy_node_extra_sni_routes"], [])


class OriginDnsTests(unittest.TestCase):
    def test_origin_record_uses_relative_name_and_node_ip_semantics(self) -> None:
        zone = ANTIBLOCK_VARS["antiblock_cdn_certificate"]["dns_zone"]
        origin = HOST_DE_FRA_2["antiblock_cdn_node"]["origin_hostname"]
        self.assertEqual(relative_dns_record_name(origin, zone), "origin-cdn")
        records = GROUP_CDN["antiblock_cdn_origin_dns_records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "A")
        self.assertFalse(records[0]["proxied"])
        self.assertTrue(records[0]["solo"])
        self.assertNotIn("2.26.25.230", yaml.dump(GROUP_CDN))
        self.assertNotIn("2.26.25.230", yaml.dump(HOST_DE_FRA_2))
        self.assertIn("ansible_host", CF_DNS_TASKS)
        self.assertIn("cf_dns_target_ip_resolved", CF_DNS_TASKS)

    def test_unrelated_records_not_deleted(self) -> None:
        play = _plays()[1]
        cf_role = next(
            task
            for task in _include_tasks(play, "cf_dns")
            if "origin A" in str(task.get("name"))
        )
        origin = GROUP_CDN["antiblock_cdn_origin_dns_records"][0]
        self.assertTrue(origin["solo"])
        self.assertEqual(origin["type"], "A")
        self.assertEqual(cf_role["vars"]["cf_dns_state"], "present")
        self.assertEqual(
            cf_role["vars"]["cf_dns_records"],
            "{{ antiblock_cdn_origin_dns_records }}",
        )
        self.assertNotIn("cf_dns_solo_default", cf_role.get("vars") or {})
        self.assertIn("item.solo", CF_DNS_TASKS)
        self.assertIn("loop: \"{{ cf_dns_records | default(cf_dns_records_default) }}\"", CF_DNS_TASKS)
        self.assertNotIn("state: absent", CF_DNS_TASKS)
        self.assertIn("type: \"{{ item.type | default('A') }}\"", CF_DNS_TASKS)
        self.assertNotIn("list_records", CF_DNS_TASKS)
        self.assertNotIn("origin-cdn", yaml.dump(yaml.safe_load(
            (REPO / "inventory/host_vars/de-fra-2/main.yml").read_text(encoding="utf-8")
        ).get("cf_dns_records")))
        # solo=true only removes other records of the same name+type.
        # Origin reconciliation is a single A; other names (www, edge-fra-02, …)
        # and other types at origin-cdn (CNAME/TXT/AAAA) are not in the loop.
        self.assertEqual(
            [item["type"] for item in GROUP_CDN["antiblock_cdn_origin_dns_records"]],
            ["A"],
        )
        node_names = [
            item["name"]
            for item in yaml.safe_load(
                (REPO / "inventory/host_vars/de-fra-2/main.yml").read_text(encoding="utf-8")
            )["cf_dns_records"]
        ]
        origin_relative = relative_dns_record_name(
            HOST_DE_FRA_2["antiblock_cdn_node"]["origin_hostname"],
            ANTIBLOCK_VARS["antiblock_cdn_certificate"]["dns_zone"],
        )
        self.assertNotIn(origin_relative, node_names)

    def test_nodes_dns_and_antiblock_origin_are_separate_lists(self) -> None:
        self.assertNotIn("cf_dns_records", GROUP_CDN)
        self.assertNotIn("cf_dns_records_default", GROUP_CDN)
        host = yaml.safe_load(
            (REPO / "inventory/host_vars/de-fra-2/main.yml").read_text(encoding="utf-8")
        )
        node_names = [item["name"] for item in host["cf_dns_records"]]
        self.assertEqual(
            node_names,
            [
                "www",
                "site",
                "edge-fra-02",
                "stream-fra-02",
                "cache-fra-02",
                "segment-fra-02",
                "api-fra-02",
            ],
        )
        self.assertNotIn("origin-cdn", node_names)
        nodes_cf = next(
            item
            for item in _plays(REPO / "playbooks/nodes.yml")[0]["roles"]
            if isinstance(item, dict) and item.get("role") == "cf_dns"
        )
        self.assertNotIn("cf_dns_records", nodes_cf.get("vars") or {})
        antiblock_cf = next(
            task
            for task in _include_tasks(_plays()[1], "cf_dns")
            if "origin A" in str(task.get("name"))
        )
        self.assertEqual(
            antiblock_cf["vars"]["cf_dns_records"],
            "{{ antiblock_cdn_origin_dns_records }}",
        )

    def test_origin_ready_wait_before_haproxy(self) -> None:
        play = _plays()[1]
        tasks = play.get("tasks") or []
        wait = next(
            task for task in tasks if "Wait until origin inbound is listening" in str(task.get("name"))
        )
        self.assertEqual(wait["ansible.builtin.wait_for"]["host"], "127.0.0.1")
        self.assertEqual(
            wait["ansible.builtin.wait_for"]["port"],
            "{{ antiblock_cdn_inbound_port | int }}",
        )
        self.assertEqual(wait["ansible.builtin.wait_for"]["state"], "started")
        self.assertIn("antiblock_cdn_origin_listen_timeout", wait["ansible.builtin.wait_for"]["timeout"])
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_origin_listen_timeout"], 90)
        register_tasks = (REPO / "roles/remnawave_register_node/tasks/main.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("wait_for", register_tasks)
        names = [str(task.get("name")) for task in tasks]
        self.assertLess(
            names.index("AntiBlock CDN | Wait until origin inbound is listening"),
            names.index("AntiBlock CDN | Ensure HAProxy origin SNI route"),
        )


class ArchitectureTests(unittest.TestCase):
    def test_de_fra_2_keeps_legacy_hostnames(self) -> None:
        node = HOST_DE_FRA_2["antiblock_cdn_node"]
        self.assertEqual(node["public_hostname"], "cdn-lab.digitalstreamers.xyz")
        self.assertEqual(node["origin_hostname"], "origin-cdn.digitalstreamers.xyz")
        self.assertEqual(
            node["origin_group_name"],
            "common-origin-cdn-digitalstreamers-xyz",
        )
        derived = GROUP_CDN["antiblock_cdn_node"]
        self.assertEqual(
            derived["public_hostname"],
            "{{ inventory_hostname }}.cdn.digitalstreamers.xyz",
        )
        self.assertEqual(
            derived["origin_hostname"],
            "origin-{{ inventory_hostname }}.digitalstreamers.xyz",
        )
        self.assertIn("de-fra-2", _group_members("antiblock_cdn_nodes"))
        self.assertNotIn("de-fra-3", _group_members("antiblock_cdn_nodes"))

    def test_backend_port_comes_from_inbound_port(self) -> None:
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_inbound_port"], 8447)
        extra = GROUP_CDN["haproxy_node_extra_sni_routes"][0]
        self.assertEqual(extra["backend_port"], "{{ antiblock_cdn_inbound_port | int }}")
        self.assertEqual(extra["backend_name"], "be_xhttp_{{ antiblock_cdn_inbound_port }}")
        self.assertFalse(extra["send_proxy_v2"])
        self.assertNotIn("8447", yaml.dump(GROUP_CDN["haproxy_node_extra_sni_routes"]))

    def test_generic_nodes_playbook_does_not_wire_antiblock(self) -> None:
        self.assertNotIn("antiblock_cdn", NODES_PLAY)
        self.assertNotIn("haproxy_node_extra_sni_routes", NODES_PLAY)
        self.assertNotIn("origin-cdn", NODES_PLAY)
        self.assertNotIn("antiblock_cdn_origin_dns_records", NODES_PLAY)
        self.assertEqual(DEFAULTS["haproxy_node_extra_sni_routes"], [])

    def test_antiblock_playbook_wires_per_node_cdn_without_add_host(self) -> None:
        plays = _plays()
        self.assertEqual(plays[0]["hosts"], "panel")
        self.assertEqual(plays[1]["hosts"], "antiblock_cdn_nodes")
        self.assertEqual(
            _role_names(plays[1]),
            [
                "remnawave_register_node",
                "cf_dns",
                "remnawave_node_haproxy",
                "yandex_cdn",
                "cf_dns",
                "remnawave_antiblock_hosts",
            ],
        )
        raw = PLAY.read_text(encoding="utf-8")
        self.assertNotIn("remnawave_add_host", raw)
        self.assertNotIn("requestNew", raw)
        self.assertIn("delegate_to: localhost", raw)

    def test_makefile_single_node_limit_includes_panel(self) -> None:
        block = _makefile_block("antiblock-cdn-node")
        self.assertIn("HOST is required", block)
        self.assertIn("antiblock_cdn_nodes", block)
        self.assertIn("--limit panel:$(HOST)", block)
        self.assertNotIn("LIMIT_FLAG", block)
        inbounds = _makefile_block("inbounds")
        nodes = _makefile_block("nodes")
        self.assertIn("PLAY_INBOUNDS", inbounds)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", inbounds)
        self.assertIn("PLAY_NODES", nodes)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", nodes)


if __name__ == "__main__":
    unittest.main()
