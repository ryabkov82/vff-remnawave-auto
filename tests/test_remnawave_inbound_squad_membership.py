#!/usr/bin/env python3
"""Unit tests for Remnawave Internal Squad membership reconcile."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "roles/remnawave_inbounds/filter_plugins"))

from remnawave_squad_membership import (  # noqa: E402
    membership_conflicts,
    reconcile_squad_members,
    squad_inbound_uuids,
)

ROLE = REPO / "roles/remnawave_inbounds"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
MAIN_TASKS = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
RECONCILE = (ROLE / "tasks/reconcile_squads.yml").read_text(encoding="utf-8")
RECONCILE_ONE = (ROLE / "tasks/reconcile_one_squad.yml").read_text(encoding="utf-8")
ANTIBLOCK_VARS = REPO / "inventory/group_vars/all/antiblock_cdn.yml"
HOSTS_INI = (REPO / "inventory/hosts.ini").read_text(encoding="utf-8")
PANEL_VARS = (REPO / "inventory/group_vars/panel/main.yml").read_text(encoding="utf-8")
DOCS = (REPO / "docs/remnawave_inbounds.md").read_text(encoding="utf-8")

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-cccc-cccc-cccccccccccc"

FORBIDDEN_UUIDS = (
    "a281fe1b-d9b6-4874-b34a-2832481cc60f",
    "d7340374-7968-4240-9528-8c617af963ee",
)

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _task_block(source: str, name: str) -> str:
    marker = f"- name: {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing task: {name}")
    rest = source[start:]
    nxt = rest.find("\n- name:", len(marker))
    return rest if nxt < 0 else rest[:nxt]


class ReconcileSquadMembersTests(unittest.TestCase):
    def test_a_present_appends_new_uuid(self) -> None:
        result = reconcile_squad_members([A, B], add=[C], remove=[])
        self.assertEqual(result["members"], [A, B, C])
        self.assertTrue(result["changed"])

    def test_b_absent_removes_target_only(self) -> None:
        result = reconcile_squad_members([A, B, C], add=[], remove=[C])
        self.assertEqual(result["members"], [A, B])
        self.assertTrue(result["changed"])

    def test_c_present_already_member_is_unchanged(self) -> None:
        result = reconcile_squad_members([A, B, C], add=[C], remove=[])
        self.assertEqual(result["members"], [A, B, C])
        self.assertFalse(result["changed"])

    def test_d_absent_already_missing_is_unchanged(self) -> None:
        result = reconcile_squad_members([A, B], add=[], remove=[C])
        self.assertEqual(result["members"], [A, B])
        self.assertFalse(result["changed"])

    def test_e_present_and_absent_same_squad_is_conflict(self) -> None:
        conflicts = membership_conflicts(
            [
                {
                    "inbound_tag": "VLESS xHTTP packet-up test",
                    "present_in": ["AntiBlock-Squad", "Default-Squad"],
                    "absent_from": ["Default-Squad"],
                }
            ]
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["inbound_tag"], "VLESS xHTTP packet-up test")
        self.assertEqual(conflicts[0]["squads"], ["Default-Squad"])

    def test_e_conflict_across_split_membership_items(self) -> None:
        conflicts = membership_conflicts(
            [
                {
                    "inbound_tag": "VLESS xHTTP packet-up test",
                    "present_in": ["Default-Squad"],
                    "absent_from": [],
                },
                {
                    "inbound_tag": "VLESS xHTTP packet-up test",
                    "present_in": [],
                    "absent_from": ["Default-Squad"],
                },
            ]
        )
        self.assertEqual(conflicts[0]["squads"], ["Default-Squad"])

    def test_f_removing_c_keeps_unrelated_a_and_b(self) -> None:
        result = reconcile_squad_members([A, B, C], add=[], remove=[C])
        self.assertIn(A, result["members"])
        self.assertIn(B, result["members"])
        self.assertNotIn(C, result["members"])
        self.assertEqual(result["members"], [A, B])

    def test_g_repeat_reconcile_of_correct_state_is_no_change(self) -> None:
        first = reconcile_squad_members([A, B], add=[C], remove=[])
        self.assertEqual(first["members"], [A, B, C])
        second = reconcile_squad_members(first["members"], add=[C], remove=[])
        self.assertEqual(second["members"], [A, B, C])
        self.assertFalse(second["changed"])
        self.assertFalse(second["needs_patch"])

        already_absent = reconcile_squad_members([A, B], add=[], remove=[C])
        self.assertFalse(already_absent["changed"])
        repeat_absent = reconcile_squad_members(
            already_absent["members"], add=[], remove=[C]
        )
        self.assertFalse(repeat_absent["changed"])
        self.assertEqual(repeat_absent["members"], [A, B])

    def test_preserves_current_order_and_appends(self) -> None:
        result = reconcile_squad_members([B, A], add=[C], remove=[])
        self.assertEqual(result["members"], [B, A, C])

    def test_add_and_remove_together_does_not_drop_unrelated(self) -> None:
        result = reconcile_squad_members([A, B, C], add=[C], remove=[B])
        self.assertEqual(result["members"], [A, C])
        self.assertTrue(result["changed"])

    def test_squad_inbound_uuids_from_objects_and_strings(self) -> None:
        self.assertEqual(
            squad_inbound_uuids([{"uuid": A}, {"uuid": B}]),
            [A, B],
        )
        self.assertEqual(squad_inbound_uuids([A, B]), [A, B])
        self.assertEqual(
            squad_inbound_uuids([{"inboundUuid": C}, A]),
            [C, A],
        )


class RoleStructureTests(unittest.TestCase):
    def test_defaults_keep_additive_registration_and_empty_memberships(self) -> None:
        self.assertEqual(DEFAULTS["remnawave_inbound_squad_memberships"], [])
        self.assertTrue(DEFAULTS["remnawave_register_inbounds_in_squad"])
        self.assertEqual(DEFAULTS["remnawave_internal_squad_name"], "Default-Squad")
        self.assertEqual(DEFAULTS["remnawave_tag_collision_mode"], "auto_prefix")

    def test_additive_squad_path_is_unchanged(self) -> None:
        self.assertIn("(_existing_inb_uuids + _desired_inbound_uuids) | unique | list", MAIN_TASKS)
        self.assertIn("remnawave_register_inbounds_in_squad", MAIN_TASKS)
        old_patch = _task_block(MAIN_TASKS, "PATCH internal squad with merged inbounds")
        self.assertIn("when: _ri.register_in_squad", old_patch)
        self.assertNotIn("_ri_squad_reconciled.changed", old_patch)
        self.assertIn("method: PATCH", old_patch)

    def test_new_reconcile_is_opt_in_include(self) -> None:
        include = _task_block(MAIN_TASKS, "Reconcile declarative inbound squad memberships")
        self.assertIn("(_ri.squad_memberships | default([])) | length > 0", include)
        self.assertIn("include_tasks: reconcile_squads.yml", include)
        self.assertNotIn("import_tasks: reconcile_squads.yml", MAIN_TASKS)

    def test_empty_memberships_does_not_run_reconcile_api(self) -> None:
        """Default [] must not include reconcile_squads.yml (no extra GET/PATCH)."""
        self.assertEqual(DEFAULTS["remnawave_inbound_squad_memberships"], [])
        include = _task_block(MAIN_TASKS, "Reconcile declarative inbound squad memberships")
        self.assertIn("when: (_ri.squad_memberships | default([])) | length > 0", include)
        self.assertIn("include_tasks: reconcile_squads.yml", include)

        self.assertIn("method: GET", RECONCILE)
        self.assertIn("method: GET", RECONCILE_ONE)
        self.assertIn("method: PATCH", RECONCILE_ONE)
        self.assertNotIn("method: PATCH", RECONCILE)

        old_patch = _task_block(MAIN_TASKS, "PATCH internal squad with merged inbounds")
        self.assertIn("when: _ri.register_in_squad", old_patch)
        self.assertNotIn("reconcile_squads.yml", old_patch)
        self.assertNotIn("_ri_squad_reconciled", old_patch)
        self.assertIn("(_existing_inb_uuids + _desired_inbound_uuids) | unique | list", MAIN_TASKS)

    def test_patch_task_skips_api_write_when_membership_unchanged(self) -> None:
        patch = _task_block(
            RECONCILE_ONE,
            "PATCH Internal Squad inbound membership on drift ({{ _ri_squad_name }})",
        )
        self.assertIn("when: _ri_squad_reconciled.needs_patch | bool", patch)
        self.assertNotIn("when: _ri_squad_reconciled.changed", patch)
        self.assertIn("method: PATCH", patch)
        self.assertIn("inbounds: \"{{ _ri_squad_reconciled.members }}\"", patch)

        skipped = _task_block(
            RECONCILE_ONE,
            "Squad membership reconcile summary ({{ _ri_squad_name }})",
        )
        self.assertIn("skipping PATCH", skipped)

    def test_reconcile_uses_tested_merge_filter(self) -> None:
        self.assertIn("remnawave_reconcile_squad_members", RECONCILE_ONE)
        self.assertIn("remnawave_squad_inbound_uuids", RECONCILE_ONE)
        self.assertIn("remnawave_squad_membership_conflicts", RECONCILE)

    def test_validation_fails_before_patch(self) -> None:
        conflict_pos = RECONCILE.find("present_in and absent_from overlap")
        missing_tag_pos = RECONCILE.find("membership inbound_tag is not in the profile")
        missing_squad_pos = RECONCILE.find("configured Internal Squad does not exist")
        loop_pos = RECONCILE.find("include_tasks: reconcile_one_squad.yml")
        self.assertGreater(conflict_pos, 0)
        self.assertGreater(missing_tag_pos, conflict_pos)
        self.assertGreater(missing_squad_pos, missing_tag_pos)
        self.assertGreater(loop_pos, missing_squad_pos)
        self.assertIn("Squads are not created automatically", RECONCILE)
        self.assertIn("method: PATCH", RECONCILE_ONE)
        self.assertNotIn("method: POST", RECONCILE)
        self.assertNotIn("method: POST", RECONCILE_ONE)
        self.assertNotIn("method: DELETE", RECONCILE_ONE)


class AntiblockInventoryTests(unittest.TestCase):
    def test_antiblock_cdn_vars_are_declarative_and_have_no_remnawave_uuids(self) -> None:
        raw = ANTIBLOCK_VARS.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        self.assertTrue(data["antiblock_cdn_enabled"])
        self.assertEqual(data["antiblock_cdn_inbound_tag"], "VLESS xHTTP packet-up test")
        self.assertEqual(data["antiblock_cdn_inbound_port"], 8447)
        self.assertEqual(data["antiblock_cdn_internal_squad"], "AntiBlock-Squad")
        self.assertEqual(data["antiblock_cdn_forbidden_internal_squads"], ["Default-Squad"])
        self.assertEqual(data["antiblock_cdn_tag_collision_mode"], "fail")
        self.assertNotIn("remnawave_tag_collision_mode", data)
        inbound = data["antiblock_cdn_inbound"]
        self.assertEqual(inbound["tag"], "{{ antiblock_cdn_inbound_tag }}")
        self.assertEqual(inbound["protocol"], "vless")
        self.assertEqual(inbound["streamSettings"]["xhttpSettings"]["mode"], "packet-up")
        self.assertIn("mlkem768x25519plus.native.600s.1--", inbound["settings"]["decryption"])
        self.assertNotIn("remnawave_inbound_squad_memberships", data)
        for uuid in FORBIDDEN_UUIDS:
            self.assertNotIn(uuid, raw)
        self.assertIsNone(UUID_RE.search(raw))

    def test_generic_inbounds_workflow_does_not_receive_antiblock_memberships(self) -> None:
        """make inbounds must keep production behaviour: role default [] only."""
        playbook = (REPO / "playbooks/inbounds.yml").read_text(encoding="utf-8")
        makefile = (REPO / "Makefile").read_text(encoding="utf-8")
        self.assertNotIn("remnawave_inbound_squad_memberships", playbook)
        self.assertNotIn("remnawave_inbound_squad_memberships", PANEL_VARS)
        self.assertNotIn("remnawave_inbound_squad_memberships", makefile)
        for path in (REPO / "inventory").rglob("*.yml"):
            if path.name.startswith("vault"):
                continue
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                self.assertNotIn(
                    "remnawave_inbound_squad_memberships",
                    loaded,
                    f"{path} must not wire generic squad memberships",
                )
        self.assertIn("PLAY_INBOUNDS", makefile)
        self.assertIn("playbooks/inbounds.yml", makefile)

    def test_origin_group_adds_de_fra_2_without_removing_existing_groups(self) -> None:
        self.assertIn("[antiblock_cdn_origin]", HOSTS_INI)
        origin = HOSTS_INI.split("[antiblock_cdn_origin]", 1)[1].split("[", 1)[0]
        self.assertIn("de-fra-2", origin)
        nodes = HOSTS_INI.split("[nodes]", 1)[1].split("[", 1)[0]
        nodes_1g = HOSTS_INI.split("[nodes_1g]", 1)[1].split("[", 1)[0]
        self.assertIn("de-fra-2", nodes)
        self.assertIn("de-fra-2", nodes_1g)

    def test_production_inbounds_managed_filter_unchanged(self) -> None:
        self.assertIn('remnawave_tag_collision_mode: "auto_prefix"', PANEL_VARS)
        self.assertIn("- \"VLESS TCP REALITY (DS)\"", PANEL_VARS)
        self.assertNotIn("VLESS xHTTP packet-up test", PANEL_VARS)
        self.assertNotIn("antiblock_cdn_inbound", PANEL_VARS)


class DocsTests(unittest.TestCase):
    def test_docs_cover_memberships_and_compat(self) -> None:
        self.assertIn("remnawave_inbound_squad_memberships", DOCS)
        self.assertIn("present_in", DOCS)
        self.assertIn("absent_from", DOCS)
        self.assertIn("AntiBlock-Squad", DOCS)
        self.assertIn("Default-Squad", DOCS)
        self.assertIn("unrelated", DOCS.lower())
        self.assertIn("antiblock_cdn.yml", DOCS)
        self.assertIn("remnawave_register_inbounds_in_squad", DOCS)
        self.assertIn("не** запускают `reconcile_squads.yml`", DOCS)
        self.assertIn("make inbounds", DOCS)


if __name__ == "__main__":
    unittest.main()
