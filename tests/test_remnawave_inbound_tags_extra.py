#!/usr/bin/env python3
"""Tests for remnawave_inbound_tags_extra vs register_node replace/merge."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "roles/remnawave_register_node/filter_plugins"))

from remnawave_node_inbounds import (  # noqa: E402
    effective_inbound_tags,
    reconcile_active_inbounds,
)

A = "A"
B = "B"
C = "C"
D = "D"
ANTIBLOCK_TAG = "VLESS xHTTP packet-up test"

DEFAULTS = yaml.safe_load(
    (REPO / "roles/remnawave_register_node/defaults/main.yml").read_text(
        encoding="utf-8"
    )
)
REGISTER_TASKS = (
    REPO / "roles/remnawave_register_node/tasks/main.yml"
).read_text(encoding="utf-8")
HOST_DE_FRA_2 = yaml.safe_load(
    (REPO / "inventory/host_vars/de-fra-2/main.yml").read_text(encoding="utf-8")
)
GROUP_CDN = yaml.safe_load(
    (REPO / "inventory/group_vars/antiblock_cdn_nodes.yml").read_text(encoding="utf-8")
)
ANTIBLOCK_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(encoding="utf-8")
)
HOSTS_INI = (REPO / "inventory/hosts.ini").read_text(encoding="utf-8")


def _resolve_extra(raw: list) -> list[str]:
    tag = ANTIBLOCK_VARS["antiblock_cdn_inbound_tag"]
    out: list[str] = []
    for item in raw:
        if item == "{{ antiblock_cdn_inbound_tag }}":
            out.append(tag)
        else:
            out.append(str(item))
    return out


class EffectiveTagsAndReplaceTests(unittest.TestCase):
    def test_a_replace_already_has_extra_is_unchanged(self) -> None:
        desired = effective_inbound_tags([A, B], extra_tags=[C])
        result = reconcile_active_inbounds([A, B, C], desired, mode="replace")
        self.assertEqual(desired, [A, B, C])
        self.assertEqual(result["members"], [A, B, C])
        self.assertFalse(result["changed"])

    def test_b_replace_adds_extra_to_base(self) -> None:
        desired = effective_inbound_tags([A, B], extra_tags=[C])
        result = reconcile_active_inbounds([A, B], desired, mode="replace")
        self.assertEqual(result["members"], [A, B, C])
        self.assertTrue(result["changed"])

    def test_c_replace_drops_unrelated_keeps_extra(self) -> None:
        desired = effective_inbound_tags([A, B], extra_tags=[C])
        result = reconcile_active_inbounds([A, B, C, D], desired, mode="replace")
        self.assertEqual(result["members"], [A, B, C])
        self.assertNotIn(D, result["members"])
        self.assertTrue(result["changed"])

    def test_d_empty_extra_preserves_legacy_base_only(self) -> None:
        self.assertEqual(DEFAULTS["remnawave_inbound_tags_extra"], [])
        desired = effective_inbound_tags([A, B], extra_tags=[])
        self.assertEqual(desired, [A, B])
        result = reconcile_active_inbounds([A, B], desired, mode="replace")
        self.assertFalse(result["changed"])
        result_drop = reconcile_active_inbounds([A, B, C], desired, mode="replace")
        self.assertEqual(result_drop["members"], [A, B])
        self.assertNotIn(C, result_drop["members"])

    def test_legacy_single_tag_then_extra(self) -> None:
        self.assertEqual(
            effective_inbound_tags([], extra_tags=[C], legacy_tag=A),
            [A, C],
        )

    def test_role_uses_effective_tags_filter(self) -> None:
        self.assertIn("remnawave_effective_inbound_tags", REGISTER_TASKS)
        self.assertIn("remnawave_inbound_tags_extra", REGISTER_TASKS)
        self.assertIn(
            "(remnawave_node_inbounds_mode | default('merge') == 'replace')",
            REGISTER_TASKS,
        )


class CdnNodeOrdinaryRegisterNodeTests(unittest.TestCase):
    def test_de_fra_2_replace_keeps_antiblock_tag(self) -> None:
        """Ordinary register_node replace on de-fra-2 keeps packet-up inbound."""
        self.assertEqual(HOST_DE_FRA_2["remnawave_node_inbounds_mode"], "replace")
        base = HOST_DE_FRA_2["remnawave_inbound_tags"]
        self.assertNotIn(ANTIBLOCK_TAG, base)
        extra = _resolve_extra(GROUP_CDN["remnawave_inbound_tags_extra"])
        self.assertEqual(extra, [ANTIBLOCK_TAG])
        desired = effective_inbound_tags(base, extra_tags=extra)
        self.assertIn(ANTIBLOCK_TAG, desired)
        for tag in base:
            self.assertIn(tag, desired)

        current_after_antiblock = list(desired)
        result = reconcile_active_inbounds(
            current_after_antiblock, desired, mode="replace"
        )
        self.assertFalse(result["changed"])
        self.assertIn(ANTIBLOCK_TAG, result["members"])

    def test_extra_only_on_cdn_group_not_global_nodes(self) -> None:
        self.assertIn("[antiblock_cdn_nodes]", HOSTS_INI)
        self.assertNotIn("[antiblock_cdn_origin]", HOSTS_INI)
        group = HOSTS_INI.split("[antiblock_cdn_nodes]", 1)[1].split("[", 1)[0]
        self.assertIn("de-fra-2", group)
        self.assertNotIn("nl-ams-2", group)
        self.assertNotIn("de-fra-3", group)

        nodes_vars = yaml.safe_load(
            (REPO / "inventory/group_vars/nodes.yml").read_text(encoding="utf-8")
        )
        all_vars = yaml.safe_load(
            (REPO / "inventory/group_vars/all/main.yml").read_text(encoding="utf-8")
        )
        self.assertNotIn("remnawave_inbound_tags_extra", nodes_vars)
        self.assertNotIn("remnawave_inbound_tags_extra", all_vars)
        antiblock_all = yaml.safe_load(
            (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("remnawave_inbound_tags_extra", antiblock_all)


if __name__ == "__main__":
    unittest.main()
