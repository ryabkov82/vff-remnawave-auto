#!/usr/bin/env python3
"""Unit tests for Remnawave Host match / rename / audit helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO / "scripts"))

import remnawave_hosts_lib as lib  # noqa: E402

ROLE = REPO / "roles/remnawave_add_host"
AUDIT_ROLE = REPO / "roles/remnawave_hosts_audit"
ENSURE = (ROLE / "tasks/ensure_host.yml").read_text(encoding="utf-8")
PRUNE = (ROLE / "tasks/prune.yml").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
AUDIT_TASKS = (AUDIT_ROLE / "tasks/main.yml").read_text(encoding="utf-8")
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")


_UNSET = object()


def _host(
    *,
    uuid: str,
    remark: str,
    address: str = "edge.example.com",
    port: int = 443,
    profile: str = "prof-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    inbound: str = "inbd-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    tags: object = _UNSET,
    tag: object = _UNSET,
    nodes: list[str] | None = None,
    path: str = "",
    isDisabled: bool = False,
) -> dict:
    data = {
        "uuid": uuid,
        "remark": remark,
        "address": address,
        "port": port,
        "path": path,
        "inbound": {
            "configProfileUuid": profile,
            "configProfileInboundUuid": inbound,
        },
        "serverDescription": "keep-me",
        "sni": "sni.example.com",
        "isHidden": False,
        "isDisabled": isDisabled,
        "viewPosition": 10,
        "nodes": nodes or ["node-1111-1111-1111-111111111111"],
        "fingerprint": "chrome",
        "securityLayer": "DEFAULT",
    }
    if tags is not _UNSET:
        data["tags"] = tags
    elif tag is _UNSET:
        data["tags"] = ["VFF:MANAGED"]
    if tag is not _UNSET:
        data["tag"] = tag
    return data


REALITY_INBOUND = "inbd-reality-0000-0000-000000000001"
XHTTP_INBOUND = "inbd-xhttp-0000-0000-000000000002"
PROFILE = "prof-0000-0000-0000-000000000001"


class MatchModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = [
            _host(
                uuid="11111111-1111-1111-1111-111111111111",
                remark="🇩🇪 1 vpn-for-friends",
                address="edge.example.com",
                inbound=REALITY_INBOUND,
                profile=PROFILE,
            ),
            _host(
                uuid="22222222-2222-2222-2222-222222222222",
                remark="🇩🇪 1 vpn-for-friends (xHTTP)",
                address="edge.example.com",
                inbound=XHTTP_INBOUND,
                profile=PROFILE,
                path="/api/v1/sync/",
            ),
        ]

    def test_remark_exact_match_idempotent(self) -> None:
        c = lib.select_candidates(
            self.existing,
            match_by="remark",
            remark="🇩🇪 1 vpn-for-friends",
            address="edge.example.com",
            port=443,
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["uuid"], "11111111-1111-1111-1111-111111111111")
        # Same remark -> no rename payload change needed.
        self.assertEqual(c[0]["remark"], "🇩🇪 1 vpn-for-friends")

    def test_endpoint_inbound_finds_one(self) -> None:
        c = lib.select_candidates(
            self.existing,
            match_by="endpoint_inbound",
            remark="ignored",
            address="edge.example.com",
            port=443,
            profile_uuid=PROFILE,
            inbound_uuid=REALITY_INBOUND,
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["uuid"], "11111111-1111-1111-1111-111111111111")

    def test_address_port_legacy_risk_two_matches(self) -> None:
        c = lib.select_candidates(
            self.existing,
            match_by="address_port",
            remark="",
            address="edge.example.com",
            port=443,
        )
        self.assertEqual(len(c), 2)
        first = lib.legacy_address_port_first(
            self.existing, address="edge.example.com", port=443
        )
        self.assertIsNotNone(first)
        # Legacy first silently picks Reality and ignores xHTTP twin.
        self.assertEqual(first["uuid"], "11111111-1111-1111-1111-111111111111")

    def test_endpoint_inbound_distinguishes_reality_and_xhttp(self) -> None:
        reality = lib.select_candidates(
            self.existing,
            match_by="endpoint_inbound",
            remark="",
            address="edge.example.com",
            port=443,
            profile_uuid=PROFILE,
            inbound_uuid=REALITY_INBOUND,
        )
        xhttp = lib.select_candidates(
            self.existing,
            match_by="endpoint_inbound",
            remark="",
            address="edge.example.com",
            port=443,
            profile_uuid=PROFILE,
            inbound_uuid=XHTTP_INBOUND,
        )
        self.assertEqual(len(reality), 1)
        self.assertEqual(len(xhttp), 1)
        self.assertNotEqual(reality[0]["uuid"], xhttp[0]["uuid"])

    def test_endpoint_inbound_two_full_matches_is_ambiguous(self) -> None:
        dup = self.existing + [
            _host(
                uuid="33333333-3333-3333-3333-333333333333",
                remark="dup",
                address="edge.example.com",
                inbound=REALITY_INBOUND,
                profile=PROFILE,
            )
        ]
        c = lib.select_candidates(
            dup,
            match_by="endpoint_inbound",
            remark="",
            address="edge.example.com",
            port=443,
            profile_uuid=PROFILE,
            inbound_uuid=REALITY_INBOUND,
        )
        self.assertEqual(len(c), 2)
        # Role must fail and not create — covered structurally below.


class RenamePayloadTests(unittest.TestCase):
    def test_rename_disabled_keeps_remark(self) -> None:
        self.assertFalse(DEFAULTS["rw_host_set_remark_if_exists"])

    def test_payload_changes_only_remark(self) -> None:
        existing = _host(
            uuid="11111111-1111-1111-1111-111111111111",
            remark="old",
            isDisabled=False,
        )
        payload = lib.build_remark_update_payload(existing, "🇩🇪 Germany 1")
        self.assertEqual(
            payload,
            {
                "uuid": existing["uuid"],
                "remark": "🇩🇪 Germany 1",
                "isDisabled": False,
            },
        )
        # Ensure we did not copy other fields into the PATCH body.
        for forbidden in (
            "address",
            "port",
            "inbound",
            "nodes",
            "sni",
            "tag",
            "tags",
            "allowInsecure",
            "serverDescription",
            "isHidden",
            "viewPosition",
            "path",
            "fingerprint",
        ):
            self.assertNotIn(forbidden, payload)

    def test_payload_preserves_disabled_host(self) -> None:
        existing = _host(
            uuid="11111111-1111-1111-1111-111111111111",
            remark="old",
            isDisabled=True,
        )
        payload = lib.build_remark_update_payload(existing, "🇩🇪 Germany 1")
        self.assertEqual(
            payload,
            {
                "uuid": existing["uuid"],
                "remark": "🇩🇪 Germany 1",
                "isDisabled": True,
            },
        )

    def test_payload_missing_isDisabled_raises(self) -> None:
        existing = _host(
            uuid="11111111-1111-1111-1111-111111111111",
            remark="old",
        )
        del existing["isDisabled"]
        with self.assertRaises(ValueError):
            lib.build_remark_update_payload(existing, "🇩🇪 Germany 1")

    def test_assert_rename_response_ok(self) -> None:
        lib.assert_rename_response(
            {"uuid": "11111111-1111-1111-1111-111111111111", "remark": "new"},
            expected_uuid="11111111-1111-1111-1111-111111111111",
            expected_remark="new",
        )

    def test_assert_rename_response_uuid_changed(self) -> None:
        with self.assertRaises(AssertionError):
            lib.assert_rename_response(
                {"uuid": "99999999-9999-9999-9999-999999999999", "remark": "new"},
                expected_uuid="11111111-1111-1111-1111-111111111111",
                expected_remark="new",
            )

    def test_empty_remark_rejected(self) -> None:
        with self.assertRaises(ValueError):
            lib.build_remark_update_payload(
                _host(uuid="11111111-1111-1111-1111-111111111111", remark="x"),
                "  ",
            )


class UnmanagedGuardTests(unittest.TestCase):
    def test_defaults_disallow_unmanaged(self) -> None:
        self.assertFalse(DEFAULTS["rw_host_allow_unmanaged_update"])

    def test_match_marks_unmanaged(self) -> None:
        api = [
            _host(
                uuid="11111111-1111-1111-1111-111111111111",
                remark="old brand",
                tags=["OTHER"],
                inbound=REALITY_INBOUND,
                profile=PROFILE,
            )
        ]
        desired = [
            {
                "inventory_host": "de-fra-1",
                "remark": "🇩🇪 Germany 1",
                "address": "edge.example.com",
                "port": 443,
                "inbound_tag": "VLESS TCP REALITY (DS)",
            }
        ]
        inbound_by_tag = {
            "VLESS TCP REALITY (DS)": {
                "inbound_uuid": REALITY_INBOUND,
                "profile_uuid": PROFILE,
            }
        }
        matches, _ = lib.match_inventory_to_api(
            desired, api, inbound_by_tag=inbound_by_tag
        )
        self.assertEqual(matches[0]["status"], "unmanaged_match")
        self.assertTrue(matches[0].get("rename_blocked"))


class AuditOnlyGetTests(unittest.TestCase):
    def test_audit_tasks_only_get(self) -> None:
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            self.assertNotRegex(
                AUDIT_TASKS,
                rf"method:\s*{method}\b",
                msg=f"audit role must not use {method}",
            )
        self.assertIn("method: GET", AUDIT_TASKS)
        self.assertIn("no_log: true", AUDIT_TASKS)

    def test_reports_reject_authorization(self) -> None:
        report = lib.build_audit_report(
            api_hosts=[
                _host(
                    uuid="11111111-1111-1111-1111-111111111111",
                    remark="🇩🇪 1 vpn-for-friends",
                    inbound=REALITY_INBOUND,
                    profile=PROFILE,
                )
            ],
            nodes=[{"uuid": "node-1111-1111-1111-111111111111", "name": "de-fra-1"}],
            inbounds=[
                {
                    "uuid": REALITY_INBOUND,
                    "tag": "VLESS TCP REALITY (DS)",
                    "profileUuid": PROFILE,
                }
            ],
            desired=[],
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = lib.write_reports(report, Path(tmp))
            for path in (json_path, md_path):
                text = path.read_text(encoding="utf-8")
                lib.assert_no_secrets(text)
                self.assertNotIn("Bearer ", text)
                self.assertNotIn("Authorization", text)


class RoleStructureTests(unittest.TestCase):
    def _create_payload_block(self) -> str:
        marker = "- name: Build create payload"
        start = ENSURE.find(marker)
        self.assertGreaterEqual(start, 0, "missing task: Build create payload")
        rest = ENSURE[start:]
        nxt = rest.find("\n- name: Create host if missing")
        return rest if nxt < 0 else rest[:nxt]

    def test_defaults_modes_and_flags(self) -> None:
        self.assertEqual(DEFAULTS["rw_host_match_by"], "remark")
        self.assertFalse(DEFAULTS["rw_host_set_remark_if_exists"])
        self.assertFalse(DEFAULTS["rw_host_allow_unmanaged_update"])
        self.assertTrue(DEFAULTS["rw_host_update_api_confirmed"])
        self.assertEqual(DEFAULTS["rw_host_update_api_method"], "PATCH")
        self.assertEqual(DEFAULTS["rw_host_update_api_path"], "/hosts")

    def test_ensure_host_has_endpoint_inbound_and_rename(self) -> None:
        self.assertIn("endpoint_inbound", ENSURE)
        self.assertIn("Ambiguous Host match", ENSURE)
        self.assertIn("PATCH /api/hosts (remark only)", ENSURE)
        self.assertIn("rw_host_set_remark_if_exists", ENSURE)
        self.assertIn("rw_host_allow_unmanaged_update", ENSURE)
        self.assertIn("ansible_check_mode", ENSURE)
        self.assertIn("planned_rename", ENSURE)
        self.assertIn("Refusing create/delete fallback", ENSURE)
        self.assertIn("Refresh _rw_hosts_existing after rename", ENSURE)
        self.assertIn("_rw_remark_rename_planned", ENSURE)
        self.assertIn("_rw_remark_rename_performed", ENSURE)
        self.assertIn("remark_rename_planned", ENSURE)
        self.assertIn("Mark remark rename as performed", ENSURE)
        self.assertIn(
            "changed_when: (_rw_remark_patch.status | default(0) | int) == 200",
            ENSURE,
        )
        create = self._create_payload_block()
        self.assertIn("tags:", create)
        self.assertIn('- "{{ rw_host_managed_tag }}"', create)
        self.assertNotIn("\n      tag:", create)
        self.assertNotIn("allowInsecure", create)
        self.assertNotIn("allowInsecure", ENSURE)

    def _block_between(self, start_name: str, end_name: str) -> str:
        start = ENSURE.find(f"- name: {start_name}")
        self.assertGreaterEqual(start, 0, f"missing task: {start_name}")
        end = ENSURE.find(f"- name: {end_name}", start + 1)
        self.assertGreater(end, start, f"missing following task: {end_name}")
        return ENSURE[start:end]

    def test_no_legacy_bulk_host_endpoints(self) -> None:
        self.assertNotIn("/hosts/bulk/set-inbound", ENSURE)
        self.assertNotIn("/hosts/bulk/set-port", ENSURE)
        self.assertNotIn("/hosts/bulk/set-inbound", PRUNE)
        self.assertNotIn("/hosts/bulk/set-port", PRUNE)
        self.assertNotIn("/hosts/bulk/update", ENSURE)
        self.assertNotIn("/hosts/bulk/update", PRUNE)

    def test_inbound_patch_preserves_isDisabled(self) -> None:
        block = self._block_between(
            "Reconcile inbound on existing host (PATCH /api/hosts)",
            "Optionally set port on existing host (PATCH /api/hosts)",
        )
        self.assertIn("rw_host_set_inbound_if_exists", block)
        self.assertIn("_rw_inbound_differs", block)
        self.assertIn("uuid:", block)
        self.assertIn("isDisabled:", block)
        self.assertIn("_rw_existing.isDisabled", block)
        self.assertIn("inbound:", block)
        self.assertIn("configProfileUuid:", block)
        self.assertIn("configProfileInboundUuid:", block)
        self.assertIn("PATCH /api/hosts (inbound)", block)
        self.assertNotIn("uuids:", block)
        self.assertNotIn("bulk/set-inbound", block)

    def test_port_patch_preserves_isDisabled(self) -> None:
        block = self._block_between(
            "Optionally set port on existing host (PATCH /api/hosts)",
            "Guard rename requires confirmed API contract",
        )
        self.assertIn("rw_host_set_port_if_exists", block)
        self.assertIn("_rw_port_differs", block)
        self.assertIn("uuid:", block)
        self.assertIn("isDisabled:", block)
        self.assertIn("_rw_existing.isDisabled", block)
        self.assertIn("port:", block)
        self.assertIn("PATCH /api/hosts (port)", block)
        self.assertNotIn("uuids:", block)
        self.assertNotIn("bulk/set-port", block)

    def test_remark_patch_preserves_isDisabled(self) -> None:
        block = self._block_between(
            '"PATCH /api/hosts (remark only)"',
            "Output result",
        )
        self.assertIn("uuid:", block)
        self.assertIn("remark:", block)
        self.assertIn("isDisabled:", block)
        self.assertIn("_rw_existing.isDisabled", block)
        self.assertNotIn("inbound:", block)
        self.assertNotIn("tags:", block)

    def test_isDisabled_assert_runs_before_any_host_patch(self) -> None:
        assert_pos = ENSURE.find("Assert existing Host.isDisabled is defined before PATCH")
        inbound_pos = ENSURE.find("PATCH /api/hosts (inbound)")
        port_pos = ENSURE.find("PATCH /api/hosts (port)")
        remark_pos = ENSURE.find('"PATCH /api/hosts (remark only)"')
        self.assertGreater(assert_pos, 0)
        self.assertGreater(inbound_pos, assert_pos)
        self.assertGreater(port_pos, assert_pos)
        self.assertGreater(remark_pos, assert_pos)
        self.assertIn("_rw_existing.isDisabled is defined", ENSURE)

    def test_host_delete_expects_204(self) -> None:
        delete = self._block_between("Delete host", "Clear existing after delete")
        self.assertIn("method: DELETE", delete)
        self.assertIn("status_code: [204]", delete)
        self.assertNotIn("status_code: [200]", delete)
        self.assertNotIn("status_code: [200, 204]", delete)
        prune_delete = PRUNE[
            PRUNE.find("Prune (DELETE) managed hosts bound to current node") :
        ]
        self.assertIn("method: DELETE", prune_delete)
        self.assertIn("status_code: [204]", prune_delete)
        self.assertNotIn("status_code: [200]", prune_delete)


class RemarkRenameReportingTests(unittest.TestCase):
    """Structural guarantees for planned/performed rename reporting."""

    def _task_block(self, name: str) -> str:
        marker = f"- name: {name}"
        start = ENSURE.find(marker)
        self.assertGreaterEqual(start, 0, f"missing task: {name}")
        rest = ENSURE[start + len(marker) :]
        nxt = rest.find("\n- name:")
        return rest if nxt < 0 else rest[:nxt]

    def test_check_mode_sets_planned_not_performed(self) -> None:
        mark = self._task_block("Mark remark rename as planned (check mode)")
        self.assertIn("ansible_check_mode", mark)
        self.assertIn("_rw_remark_rename_planned: true", mark)
        self.assertNotIn("_rw_remark_rename_performed: true", mark)

        plan = self._task_block("Plan remark rename (check mode only)")
        self.assertIn("ansible_check_mode", plan)
        self.assertIn("changed_when: true", plan)
        self.assertNotIn("method: PATCH", plan)
        self.assertNotIn("uri:", plan)

        out = self._task_block("Output result")
        self.assertIn(
            'remark_rename_planned: "{{ _rw_remark_rename_planned | bool }}"',
            out,
        )
        self.assertIn(
            'remark_renamed: "{{ _rw_remark_rename_performed | bool }}"',
            out,
        )
        # Must not report renamed=true solely from check-mode diff.
        self.assertNotIn("ansible_check_mode", out)

    def test_apply_patch_marks_changed_and_performed(self) -> None:
        patch = self._task_block('"PATCH /api/hosts (remark only)"')
        self.assertIn("not ansible_check_mode", patch)
        self.assertIn("Update Host remark via confirmed PATCH contract", patch)
        self.assertIn(
            "changed_when: (_rw_remark_patch.status | default(0) | int) == 200",
            patch,
        )
        # performed is set after response validation, before local refresh.
        performed_pos = patch.find("Mark remark rename as performed")
        refresh_pos = patch.find("Refresh local existing Host remark after rename")
        self.assertGreater(performed_pos, 0)
        self.assertGreater(refresh_pos, performed_pos)
        performed = patch[performed_pos:refresh_pos]
        self.assertIn("_rw_remark_rename_performed: true", performed)
        self.assertNotIn("_rw_remark_rename_planned: true", performed)

    def test_idempotent_repeat_leaves_flags_false(self) -> None:
        reset = self._task_block('"Ensure host | Reset per-item working facts"')
        self.assertIn("_rw_remark_rename_planned: false", reset)
        self.assertIn("_rw_remark_rename_performed: false", reset)
        # PATCH block only runs when remark differs; idempotent path skips it.
        patch = self._task_block('"PATCH /api/hosts (remark only)"')
        self.assertIn("_rw_remark_differs | bool", patch)

    def test_api_error_does_not_set_performed(self) -> None:
        patch = self._task_block('"PATCH /api/hosts (remark only)"')
        fail_pos = patch.find("Fail on remark update API error")
        performed_pos = patch.find("Mark remark rename as performed")
        self.assertGreater(fail_pos, 0)
        self.assertGreater(performed_pos, fail_pos)
        # On non-200 the fail task runs and performed task is never reached.
        fail_block = patch[fail_pos:performed_pos]
        self.assertIn("!= 200", fail_block)
        self.assertNotIn("_rw_remark_rename_performed: true", fail_block)

    def test_prune_still_managed_only(self) -> None:
        self.assertIn("rw_host_managed_tag", PRUNE)
        self.assertIn("rw_host_managed_tag in tags", PRUNE)
        self.assertIn("endpoint_inbound", PRUNE)
        self.assertNotIn("rw_host_allow_unmanaged_update", PRUNE)
        self.assertNotIn("selectattr('tag'", PRUNE)

    def test_makefile_hosts_audit(self) -> None:
        self.assertIn("hosts-audit:", MAKEFILE)
        self.assertIn("PLAY_AUDIT_HOSTS", MAKEFILE)
        self.assertIn("hosts-plan:", MAKEFILE)

    def test_second_run_idempotent_when_remark_matches(self) -> None:
        existing = _host(
            uuid="11111111-1111-1111-1111-111111111111",
            remark="🇩🇪 Germany 1",
            inbound=REALITY_INBOUND,
            profile=PROFILE,
        )
        c = lib.select_candidates(
            [existing],
            match_by="endpoint_inbound",
            remark="🇩🇪 Germany 1",
            address="edge.example.com",
            port=443,
            profile_uuid=PROFILE,
            inbound_uuid=REALITY_INBOUND,
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["remark"], "🇩🇪 Germany 1")
        # No PATCH needed when remarks already match.
        self.assertFalse(c[0]["remark"] != "🇩🇪 Germany 1")


class CollisionAnalysisTests(unittest.TestCase):
    def test_address_port_collision_reality_xhttp(self) -> None:
        report = lib.build_audit_report(
            api_hosts=[
                _host(
                    uuid="11111111-1111-1111-1111-111111111111",
                    remark="R",
                    inbound=REALITY_INBOUND,
                    profile=PROFILE,
                ),
                _host(
                    uuid="22222222-2222-2222-2222-222222222222",
                    remark="X (xHTTP)",
                    inbound=XHTTP_INBOUND,
                    profile=PROFILE,
                    path="/api/v1/sync/",
                ),
            ],
            inbounds=[
                {
                    "uuid": REALITY_INBOUND,
                    "tag": "VLESS TCP REALITY (DS)",
                    "profileUuid": PROFILE,
                },
                {
                    "uuid": XHTTP_INBOUND,
                    "tag": "VLESS xHTTP (behind nginx)",
                    "profileUuid": PROFILE,
                },
            ],
        )
        self.assertFalse(report.address_port_safe)
        self.assertIn("B_address_port", report.colliding_keys)
        self.assertIn("D_address_port_profile_inbound", report.unique_keys)
        self.assertEqual(report.minimal_unique_key, "A_remark")
        # When remarks unique but address_port collides, endpoint_inbound is also unique.
        self.assertEqual(len(report.collisions["D_address_port_profile_inbound"]), 0)
        groups = report.collisions["B_address_port"]
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["xhttp_related"])


class ManagedTagsTests(unittest.TestCase):
    """Host.tags membership: managed marker need not be the only tag."""

    def test_normalize_and_is_managed_fixtures(self) -> None:
        cases = [
            ({"tags": ["VFF:MANAGED"]}, True, ["VFF:MANAGED"]),
            ({"tags": ["OTHER", "VFF:MANAGED"]}, True, ["OTHER", "VFF:MANAGED"]),
            ({"tags": []}, False, []),
            ({"tags": None}, False, []),
            ({}, False, []),
            ({"tags": ["OTHER"]}, False, ["OTHER"]),
            ({"tag": "VFF:MANAGED"}, True, ["VFF:MANAGED"]),
        ]
        for host, expected_managed, expected_tags in cases:
            with self.subTest(host=host):
                self.assertEqual(lib.normalize_host_tags(host), expected_tags)
                self.assertEqual(lib.is_managed_host(host), expected_managed)

    def test_multi_tags_preserved_in_enrich_and_report(self) -> None:
        host = _host(
            uuid="11111111-1111-1111-1111-111111111111",
            remark="multi",
            tags=["OTHER", "VFF:MANAGED"],
            inbound=REALITY_INBOUND,
            profile=PROFILE,
        )
        enriched = lib.enrich_host(
            host,
            nodes_by_uuid={},
            inbound_by_uuid={},
        )
        self.assertEqual(enriched["tags"], ["OTHER", "VFF:MANAGED"])
        self.assertTrue(enriched["managed"])
        report = lib.build_audit_report(api_hosts=[host])
        self.assertEqual(report.hosts[0]["tags"], ["OTHER", "VFF:MANAGED"])
        self.assertEqual(report.unmanaged, [])
        md = lib.render_markdown(report)
        self.assertIn("OTHER,VFF:MANAGED", md)

    def test_empty_and_foreign_tags_are_unmanaged_in_match(self) -> None:
        inbound_by_tag = {
            "VLESS TCP REALITY (DS)": {
                "inbound_uuid": REALITY_INBOUND,
                "profile_uuid": PROFILE,
            }
        }
        desired = [
            {
                "inventory_host": "de-fra-1",
                "remark": "🇩🇪 Germany 1",
                "address": "edge.example.com",
                "port": 443,
                "inbound_tag": "VLESS TCP REALITY (DS)",
            }
        ]
        for api_host in (
            _host(
                uuid="11111111-1111-1111-1111-111111111111",
                remark="old brand",
                tags=[],
                inbound=REALITY_INBOUND,
                profile=PROFILE,
            ),
            _host(
                uuid="11111111-1111-1111-1111-111111111111",
                remark="old brand",
                tags=None,
                inbound=REALITY_INBOUND,
                profile=PROFILE,
            ),
            {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "remark": "old brand",
                "address": "edge.example.com",
                "port": 443,
                "inbound": {
                    "configProfileUuid": PROFILE,
                    "configProfileInboundUuid": REALITY_INBOUND,
                },
            },
        ):
            with self.subTest(tags=api_host.get("tags", "__missing__")):
                matches, _ = lib.match_inventory_to_api(
                    desired, [api_host], inbound_by_tag=inbound_by_tag
                )
                self.assertEqual(matches[0]["status"], "unmanaged_match")

    def test_legacy_singular_tag_is_managed_in_match(self) -> None:
        api = [
            _host(
                uuid="11111111-1111-1111-1111-111111111111",
                remark="🇩🇪 Germany 1",
                tag="VFF:MANAGED",
                inbound=REALITY_INBOUND,
                profile=PROFILE,
            )
        ]
        desired = [
            {
                "inventory_host": "de-fra-1",
                "remark": "🇩🇪 Germany 1",
                "address": "edge.example.com",
                "port": 443,
                "inbound_tag": "VLESS TCP REALITY (DS)",
            }
        ]
        inbound_by_tag = {
            "VLESS TCP REALITY (DS)": {
                "inbound_uuid": REALITY_INBOUND,
                "profile_uuid": PROFILE,
            }
        }
        matches, _ = lib.match_inventory_to_api(
            desired, api, inbound_by_tag=inbound_by_tag
        )
        self.assertEqual(matches[0]["status"], "exact")
        self.assertEqual(matches[0]["tags"], ["VFF:MANAGED"])


class UnknownMatchModeTests(unittest.TestCase):
    def test_unknown_match_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            lib.select_candidates(
                [],
                match_by="nope",
                remark="x",
                address="a",
                port=443,
            )


if __name__ == "__main__":
    unittest.main()
