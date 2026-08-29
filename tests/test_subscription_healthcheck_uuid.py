#!/usr/bin/env python3
"""Keep Subscription Page HTML healthcheck UUIDs on one vaulted source."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "inventory/group_vars/subscription/main.yml"
SOURCE = "remnawave_subscription_healthcheck_short_uuid"
VAULT = "vault_remnawave_subscription_healthcheck_short_uuid"
ALIASES = (
    "remnawave_sub_next_healthcheck_short_uuid",
    "remnawave_subpage_config_healthcheck_short_uuid",
    "remnawave_subscription_prod_healthcheck_short_uuid",
)
STALE_HEALTHCHECK = "VZLHkrKwsj0Qs82e"
SOURCE_REF = "{{ vault_remnawave_subscription_healthcheck_short_uuid }}"
ALIAS_REF = "{{ remnawave_subscription_healthcheck_short_uuid }}"


class SubscriptionHealthcheckUuidTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = INVENTORY.read_text(encoding="utf-8")
        cls.inventory = yaml.safe_load(cls.raw)

    def test_public_inventory_references_vault(self) -> None:
        self.assertEqual(self.inventory[SOURCE], SOURCE_REF)
        self.assertIn(VAULT, self.raw)
        self.assertIn("Ansible Vault", self.raw)

    def test_aliases_point_to_single_source(self) -> None:
        for key in ALIASES:
            self.assertEqual(self.inventory[key], ALIAS_REF, key)

    def test_stale_client_uuid_not_reused(self) -> None:
        self.assertNotIn(STALE_HEALTHCHECK, self.raw)

    def test_inventory_has_no_literal_healthcheck_uuid(self) -> None:
        value = self.inventory[SOURCE]
        self.assertIn("{{", value)
        self.assertTrue(value.strip().startswith("{{"))
        self.assertTrue(value.strip().endswith("}}"))

    def test_inventory_documents_synthetic_subscription(self) -> None:
        self.assertIn("Dedicated synthetic Standard subscription", self.raw)
        self.assertIn("username: monitoring", self.raw)
        self.assertIn("bearer credential", self.raw)


if __name__ == "__main__":
    unittest.main()
