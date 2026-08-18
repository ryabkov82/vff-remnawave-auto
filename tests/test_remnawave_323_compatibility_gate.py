#!/usr/bin/env python3
"""Final ACTIVE-only Remnawave 3.2.3 compatibility gate.

Scans the ACTIVE role set only. Legacy migrate_* roles and docs are excluded.
"""

from __future__ import annotations

import re
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]

ACTIVE_ROLES = (
    "remnawave_register_node",
    "remnawave_add_host",
    "remnawave_delete_node",
    "remnawave_disable_node",
    "remnawave_inbounds",
    "remnawave_inbounds_cache",
    "remnawave_reality_servernames",
    "remnawave_sni_map",
    "remnawave_hosts_audit",
    "remnawave_external_squads",
    "remnawave_subscription_page_config",
    "remnawave_api_preflight",
    "remnawave_upgrade",
)

FORBIDDEN_ENDPOINTS = (
    "/hosts/bulk/set-inbound",
    "/hosts/bulk/set-port",
)

FORBIDDEN_DUAL_CREATE = (
    "status_code: [200, 201]",
    "not in [200, 201]",
    "in [200, 201]",
)


def _active_yml_texts() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ACTIVE_ROLES:
        role_dir = REPO / "roles" / name
        for path in sorted(role_dir.rglob("*.yml")):
            out[str(path.relative_to(REPO))] = path.read_text(encoding="utf-8")
    return out


def _joined(texts: dict[str, str]) -> str:
    return "\n".join(texts.values())


class ActiveCompatibilityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texts = _active_yml_texts()
        cls.all_yml = _joined(cls.texts)

    def test_active_roles_exist(self) -> None:
        for name in ACTIVE_ROLES:
            self.assertTrue(
                (REPO / "roles" / name / "tasks").is_dir(),
                msg=f"missing ACTIVE role {name}",
            )

    def test_active_has_no_removed_host_bulk_endpoints(self) -> None:
        for endpoint in FORBIDDEN_ENDPOINTS:
            self.assertNotIn(endpoint, self.all_yml)

    def test_active_host_request_bodies_omit_allow_insecure(self) -> None:
        ensure = self.texts["roles/remnawave_add_host/tasks/ensure_host.yml"]
        prune = self.texts["roles/remnawave_add_host/tasks/prune.yml"]
        self.assertNotIn("allowInsecure", ensure)
        self.assertNotIn("allowInsecure", prune)
        create = ensure[ensure.find("POST /api/hosts") : ensure.find("Create host if missing") + 400]
        self.assertNotIn("allowInsecure", create)

    def test_active_host_managed_logic_uses_tags_not_singular_tag(self) -> None:
        prune = self.texts["roles/remnawave_add_host/tasks/prune.yml"]
        self.assertIn("rw_host_managed_tag in host.tags", prune)
        self.assertIn("rw_host_managed_tag in tags", prune)
        self.assertIsNone(re.search(r"\bhost\.tag\b", prune))
        self.assertIsNone(re.search(r"\bh\.tag\b", prune))
        ensure = self.texts["roles/remnawave_add_host/tasks/ensure_host.yml"]
        self.assertIn("tags:", ensure)
        self.assertIn("rw_host_managed_tag", ensure)

    def test_active_creates_are_not_dual_200_201(self) -> None:
        register = self.texts["roles/remnawave_register_node/tasks/main.yml"]
        external = self.texts["roles/remnawave_external_squads/tasks/manage_one.yml"]
        subpage = self.texts["roles/remnawave_subscription_page_config/tasks/manage_one.yml"]
        for blob in (register, external, subpage):
            for needle in FORBIDDEN_DUAL_CREATE:
                self.assertNotIn(needle, blob)
        self.assertIn("not in [201]", register)
        self.assertIn("status_code: [201]", external)
        self.assertIn("status_code: [201]", subpage)

    def test_active_contains_required_323_contracts(self) -> None:
        add_host = self.texts["roles/remnawave_add_host/tasks/ensure_host.yml"]
        prune = self.texts["roles/remnawave_add_host/tasks/prune.yml"]
        delete = self.texts["roles/remnawave_delete_node/tasks/main.yml"]
        disable = self.texts["roles/remnawave_disable_node/tasks/main.yml"]
        register = self.texts["roles/remnawave_register_node/tasks/main.yml"]
        preflight = self.texts["roles/remnawave_api_preflight/tasks/main.yml"]

        self.assertIn("tags:", add_host)
        self.assertIn("status_code: [204]", add_host)
        self.assertIn("method: DELETE", add_host)
        self.assertIn("status_code: [204]", prune)
        self.assertIn("/hosts/bulk/delete", delete)
        self.assertIn("status_code: [204]", delete)
        self.assertIn("status_code: [204, 404]", delete)
        self.assertIn("/hosts/bulk/", disable)
        self.assertIn("status_code: [204]", disable)
        self.assertIn("failed_when: _created.status not in [201]", register)
        self.assertIn("role: remnawave_api_preflight", (REPO / "playbooks/remnawave_api_preflight.yml").read_text(encoding="utf-8"))
        self.assertIn("hosts:*", preflight)
        self.assertIn("nodes:*", preflight)
        self.assertIn("config-profiles:*", preflight)
        self.assertIn("internal-squads:*", preflight)
        self.assertIn("external-squads:*", preflight)
        self.assertIn("subscription-page-configs:*", preflight)
        self.assertIn("system:read", preflight)
        self.assertIn("keygen:get", preflight)

    def test_antiblock_squad_invariant_tests_exist(self) -> None:
        antiblock = (REPO / "tests/test_antiblock_cdn_playbook.py").read_text(
            encoding="utf-8"
        )
        contract = (REPO / "tests/test_remnawave_active_api_contract.py").read_text(
            encoding="utf-8"
        )
        membership = (
            REPO / "tests/test_remnawave_inbound_squad_membership.py"
        ).read_text(encoding="utf-8")
        self.assertIn("AntiBlock-Squad", antiblock)
        self.assertIn("Default-Squad", antiblock)
        self.assertIn("antiblock_cdn_inbound_tag", antiblock)
        self.assertIn("present_in", antiblock)
        self.assertIn("absent_from", antiblock)
        self.assertIn("AntiBlock-Squad", contract)
        self.assertIn("Default-Squad", contract)
        self.assertIn("AntiBlock-Squad", membership)
        self.assertIn("Default-Squad", membership)


if __name__ == "__main__":
    unittest.main()
