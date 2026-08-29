#!/usr/bin/env python3
"""Keep Subscription Page HTML healthcheck UUIDs on one dedicated source."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "inventory/group_vars/subscription/main.yml"
SOURCE = "remnawave_subscription_healthcheck_short_uuid"
ALIASES = (
    "remnawave_sub_next_healthcheck_short_uuid",
    "remnawave_subpage_config_healthcheck_short_uuid",
    "remnawave_subscription_prod_healthcheck_short_uuid",
)
STALE_HEALTHCHECK = "VZLHkrKwsj0Qs82e"
REF = "{{ remnawave_subscription_healthcheck_short_uuid }}"


class SubscriptionHealthcheckUuidTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = INVENTORY.read_text(encoding="utf-8")
        cls.inventory = yaml.safe_load(cls.raw)

    def test_single_source_value_is_present(self) -> None:
        value = self.inventory[SOURCE]
        self.assertIsInstance(value, str)
        self.assertGreaterEqual(len(value.strip()), 8)
        self.assertNotEqual(value, STALE_HEALTHCHECK)
        self.assertNotIn("{{", value)

    def test_aliases_point_to_single_source(self) -> None:
        for key in ALIASES:
            self.assertEqual(self.inventory[key], REF, key)

    def test_stale_client_uuid_not_reused(self) -> None:
        self.assertNotIn(STALE_HEALTHCHECK, self.raw)

    def test_inventory_documents_synthetic_subscription(self) -> None:
        self.assertIn("Dedicated synthetic Standard subscription", self.raw)
        self.assertIn("username: monitoring", self.raw)


if __name__ == "__main__":
    unittest.main()
