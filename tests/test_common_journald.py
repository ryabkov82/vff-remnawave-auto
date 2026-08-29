#!/usr/bin/env python3
"""Structural tests for persistent journald disk limits in roles/common."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles/common"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
MAIN = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
TASKS = (ROLE / "tasks/journald.yml").read_text(encoding="utf-8")
TEMPLATE = (ROLE / "templates/journald-disk-limits.conf.j2").read_text(encoding="utf-8")
HANDLERS = (ROLE / "handlers/main.yml").read_text(encoding="utf-8")
BOOTSTRAP = (REPO / "playbooks/bootstrap.yml").read_text(encoding="utf-8")
NODES = (REPO / "playbooks/nodes.yml").read_text(encoding="utf-8")
PANEL = (REPO / "playbooks/panel.yml").read_text(encoding="utf-8")


def _task_block(source: str, name: str) -> str:
    marker = f"- name: {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing task: {name}")
    rest = source[start:]
    nxt = rest.find("\n- name:", len(marker))
    return rest if nxt < 0 else rest[:nxt]


class CommonJournaldLimitTests(unittest.TestCase):
    def test_defaults_cap_persistent_journal(self) -> None:
        self.assertTrue(DEFAULTS["common_journald_manage"])
        self.assertEqual(DEFAULTS["common_journald_system_max_use"], "250M")
        self.assertEqual(DEFAULTS["common_journald_system_keep_free"], "1G")
        self.assertEqual(
            DEFAULTS["common_journald_conf_dir"], "/etc/systemd/journald.conf.d"
        )
        self.assertEqual(DEFAULTS["common_journald_dropin"], "99-disk-limits.conf")

    def test_dropin_template_has_only_requested_keys(self) -> None:
        self.assertIn("[Journal]", TEMPLATE)
        self.assertIn("SystemMaxUse={{ common_journald_system_max_use }}", TEMPLATE)
        self.assertIn(
            "SystemKeepFree={{ common_journald_system_keep_free }}", TEMPLATE
        )
        self.assertNotIn("RuntimeMaxUse", TEMPLATE)
        self.assertNotIn("Storage=", TEMPLATE)
        self.assertNotIn("journald.conf", TEMPLATE.split("[Journal]", 1)[1])

    def test_tasks_use_dropin_not_lineinfile(self) -> None:
        deploy = _task_block(TASKS, "Deploy journald persistent size limits")
        self.assertIn("src: journald-disk-limits.conf.j2", deploy)
        self.assertIn(
            'dest: "{{ common_journald_conf_dir }}/{{ common_journald_dropin }}"',
            deploy,
        )
        self.assertIn("notify: Restart systemd-journald", deploy)
        self.assertNotIn("lineinfile", TASKS)
        self.assertNotIn("/etc/systemd/journald.conf\n", TASKS)
        self.assertNotIn("journalctl --vacuum", TASKS)

    def test_handler_restarts_journald(self) -> None:
        self.assertIn("name: systemd-journald", HANDLERS)
        self.assertIn("state: restarted", HANDLERS)
        self.assertIn("Restart systemd-journald", HANDLERS)

    def test_main_imports_journald_idempotently(self) -> None:
        block = _task_block(MAIN, "Include journald persistent size limits")
        self.assertIn("import_tasks: journald.yml", block)
        self.assertIn("when: common_journald_manage | bool", block)
        self.assertIn("tags: [common, journald]", block)

    def test_playbooks_still_include_common(self) -> None:
        self.assertIn("- common", BOOTSTRAP)
        self.assertIn("role: common", NODES)
        self.assertIn("role: common", PANEL)


if __name__ == "__main__":
    unittest.main()
