#!/usr/bin/env python3
"""Structural tests for haproxy_tls_sni reload fallback and bind postcondition."""

from __future__ import annotations

from pathlib import Path
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles/haproxy_tls_sni"
HANDLERS = (ROLE / "handlers/main.yml").read_text(encoding="utf-8")
TASKS = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")

BIND_CHECK_HOST = (
    "{{ '127.0.0.1' if haproxy_bind_addr == '0.0.0.0' else "
    "('::1' if haproxy_bind_addr == '::' else haproxy_bind_addr) }}"
)


def _bind_check_host(bind_addr: str) -> str:
    loader = DataLoader()
    templar = Templar(loader=loader)
    templar.available_variables = {"haproxy_bind_addr": bind_addr}
    result = templar.template(BIND_CHECK_HOST, fail_on_undefined=True)
    return str(result)


def _task_block(source: str, name: str) -> str:
    marker = f"- name: {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing task: {name}")
    rest = source[start:]
    nxt = rest.find("\n- name:", len(marker))
    return rest if nxt < 0 else rest[:nxt]


class HaproxyReconfigureHandlerTests(unittest.TestCase):
    def test_reload_wait_allows_fallback_via_ignore_errors(self) -> None:
        block = _task_block(HANDLERS, "Wait HAProxy Bind After Reload")
        self.assertIn("register: _hap_bind_after_reload", block)
        self.assertIn("ignore_errors: true", block)
        self.assertNotIn("failed_when: false", block)
        self.assertIn(BIND_CHECK_HOST, block)
        self.assertIn("port: \"{{ haproxy_bind_port }}\"", block)

    def test_fallback_restart_depends_on_reload_wait_failed(self) -> None:
        restart = _task_block(HANDLERS, "Restart HAProxy (Fallback)")
        self.assertIn("when: _hap_bind_after_reload is failed", restart)
        self.assertIn("state: restarted", restart)

    def test_final_wait_after_restart_does_not_suppress_failure(self) -> None:
        block = _task_block(HANDLERS, "Wait HAProxy Bind After Restart")
        self.assertIn("when: _hap_bind_after_reload is failed", block)
        self.assertIn(BIND_CHECK_HOST, block)
        self.assertNotIn("failed_when: false", block)
        self.assertNotIn("ignore_errors", block)
        self.assertIn("timeout: 15", block)

    def test_handler_order_is_reload_wait_fallback_final_wait(self) -> None:
        names = [
            "Reload HAProxy",
            "Wait HAProxy Bind After Reload",
            "Restart HAProxy (Fallback)",
            "Wait HAProxy Bind After Restart",
        ]
        positions = [HANDLERS.find(f"- name: {name}") for name in names]
        self.assertTrue(all(pos >= 0 for pos in positions), positions)
        self.assertEqual(positions, sorted(positions))


class HaproxyBindPostconditionTests(unittest.TestCase):
    def test_unconditional_listener_check_after_flush_handlers(self) -> None:
        self.assertIn("ansible.builtin.meta: flush_handlers", TASKS)
        post = _task_block(TASKS, "Wait HAProxy Bind")
        self.assertGreater(
            TASKS.find("- name: Wait HAProxy Bind"),
            TASKS.find("- name: Flush handlers"),
        )
        self.assertGreater(
            TASKS.find("- name: Flush handlers"),
            TASKS.find("- name: Ensure HAProxy is started"),
        )
        self.assertIn("ansible.builtin.wait_for:", post)
        self.assertIn(BIND_CHECK_HOST, post)
        self.assertIn("port: \"{{ haproxy_bind_port }}\"", post)
        self.assertIn("state: started", post)
        self.assertIn("timeout: 15", post)
        self.assertNotIn("when:", post)
        self.assertNotIn("failed_when: false", post)
        self.assertNotIn("ignore_errors", post)

    def test_wildcard_bind_is_checked_on_loopback(self) -> None:
        self.assertEqual(_bind_check_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(_bind_check_host("::"), "::1")
        self.assertEqual(_bind_check_host("192.0.2.10"), "192.0.2.10")
        self.assertEqual(_bind_check_host("2001:db8::1"), "2001:db8::1")
        self.assertIn("0.0.0.0", BIND_CHECK_HOST)
        self.assertIn("'::'", BIND_CHECK_HOST)
        self.assertIn("127.0.0.1", BIND_CHECK_HOST)
        self.assertIn("'::1'", BIND_CHECK_HOST)
        self.assertNotIn("netstat", HANDLERS)
        self.assertNotIn("ss ", HANDLERS)
        self.assertNotIn("ansible.builtin.shell", HANDLERS)
        self.assertNotIn("ansible.builtin.shell", TASKS)


if __name__ == "__main__":
    unittest.main()
