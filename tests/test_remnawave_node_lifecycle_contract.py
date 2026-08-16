#!/usr/bin/env python3
"""Structural tests for Remnawave 3.2.3 node lifecycle HTTP contracts."""

from __future__ import annotations

from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
DELETE = (REPO / "roles/remnawave_delete_node/tasks/main.yml").read_text(encoding="utf-8")
DISABLE = (REPO / "roles/remnawave_disable_node/tasks/main.yml").read_text(encoding="utf-8")
REGISTER = (REPO / "roles/remnawave_register_node/tasks/main.yml").read_text(
    encoding="utf-8"
)


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


class RegisterNodeContractTests(unittest.TestCase):
    def test_create_accepts_only_201(self) -> None:
        block = _task_block(REGISTER, "Create node if absent")
        self.assertIn("method: POST", block)
        self.assertIn("/api/nodes", block)
        self.assertIn("failed_when: _created.status not in [201]", block)
        self.assertNotIn("[200, 201]", block)

    def test_patch_accepts_only_200(self) -> None:
        block = _task_block(REGISTER, "PATCH node configProfile if changed")
        self.assertIn("method: PATCH", block)
        self.assertIn("/api/nodes", block)
        self.assertIn("failed_when: _patched.status not in [200]", block)
        self.assertIn("activeInbounds:", block)
        self.assertIn("_final_inbound_uuids", block)

    def test_get_parses_response_as_array(self) -> None:
        get_block = _task_block(REGISTER, "List nodes")
        self.assertIn("method: GET", get_block)
        self.assertIn("/api/nodes", get_block)
        self.assertIn("failed_when: _nodes.status not in [200]", get_block)
        pick = _task_block(REGISTER, "Pick existing node by name (if any)")
        self.assertIn("_nodes.json.response", pick)
        self.assertIn("selectattr('name'", pick)

    def test_create_payload_uses_config_profile_inbound_uuids(self) -> None:
        payload = _task_block(REGISTER, "Build payload (typed)")
        self.assertIn("activeConfigProfileUuid:", payload)
        self.assertIn("activeInbounds: \"{{ _desired_inbound_uuids }}\"", payload)
        self.assertIn("_desired_inbound_uuids: \"{{ tmp | from_json }}\"", REGISTER)


if __name__ == "__main__":
    unittest.main()
