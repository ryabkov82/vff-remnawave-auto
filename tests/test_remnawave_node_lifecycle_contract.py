#!/usr/bin/env python3
"""Structural tests for Remnawave 3.2.3 node lifecycle HTTP contracts."""

from __future__ import annotations

from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
DELETE = (REPO / "roles/remnawave_delete_node/tasks/main.yml").read_text(encoding="utf-8")
DISABLE = (REPO / "roles/remnawave_disable_node/tasks/main.yml").read_text(encoding="utf-8")


def _task_block(src: str, name: str) -> str:
    for marker in (f'- name: "{name}"', f"- name: {name}"):
        start = src.find(marker)
        if start >= 0:
            rest = src[start + len(marker) :]
            nxt = rest.find("\n- name:")
            return rest if nxt < 0 else rest[:nxt]
    raise AssertionError(f"missing task: {name}")


class DeleteNodeContractTests(unittest.TestCase):
    def test_host_bulk_delete_expects_204(self) -> None:
        block = _task_block(DELETE, "Bulk delete hosts attached to node")
        self.assertIn("/hosts/bulk/delete", block)
        self.assertIn("method: POST", block)
        self.assertIn("uuids:", block)
        self.assertIn("_host_uuids", block)
        self.assertIn("status_code: [204]", block)
        self.assertNotIn("status_code: [200, 400]", block)
        self.assertNotIn("return_content: true", block)
        self.assertIn("not remnawave_dry_run", block)

    def test_node_delete_expects_204_with_idempotent_404(self) -> None:
        block = _task_block(DELETE, "Delete node")
        self.assertIn("/nodes/{{ _node_obj.uuid }}", block)
        self.assertIn("method: DELETE", block)
        self.assertIn("status_code: [204, 404]", block)
        self.assertNotIn("status_code: [200, 204, 404]", block)
        self.assertNotIn("[200, 204]", block)
        self.assertIn("== 204", block)
        self.assertIn("not remnawave_dry_run", block)
        self.assertNotIn("return_content: true", block)

    def test_delete_role_has_no_legacy_bulk_success_pair(self) -> None:
        self.assertNotIn("status_code: [200, 400]", DELETE)
        self.assertNotIn("status_code: [200, 204, 404]", DELETE)


class DisableNodeContractTests(unittest.TestCase):
    def test_host_bulk_enable_disable_expects_204(self) -> None:
        block = _task_block(DISABLE, "Bulk toggle hosts (enable/disable)")
        self.assertIn("/hosts/bulk/", block)
        self.assertIn("ternary('enable', 'disable')", block)
        self.assertIn("method: POST", block)
        self.assertIn("uuids:", block)
        self.assertIn("_hosts_of_node", block)
        self.assertIn("status_code: [204]", block)
        self.assertNotIn("status_code: [200, 400]", block)
        self.assertNotIn("return_content: true", block)
        self.assertIn("not remnawave_dry_run", block)

    def test_node_action_expects_200(self) -> None:
        block = _task_block(DISABLE, "Toggle node via action endpoint")
        self.assertIn("/nodes/{{ _node_obj.uuid }}/actions/", block)
        self.assertIn("ternary('disable', 'enable')", block)
        self.assertIn("method: POST", block)
        self.assertIn("status_code: [200]", block)
        self.assertNotIn("status_code: [200, 400, 404]", block)
        self.assertNotIn("400", block)
        self.assertNotIn("404", block)
        self.assertIn("not remnawave_dry_run", block)
        self.assertIn("_cur_disabled != _want_disabled", block)

    def test_disable_role_bulk_has_no_legacy_success_pair(self) -> None:
        self.assertNotIn("status_code: [200, 400]", DISABLE)


if __name__ == "__main__":
    unittest.main()
