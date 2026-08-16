#!/usr/bin/env python3
"""Structural tests for Remnawave 3.2.3 ACTIVE API contracts (step 5).

Official source: remnawave/backend tag 3.2.3
libs/contract/commands + NestJS controllers (HttpStatus.CREATED / OK).
"""

from __future__ import annotations

import re
from pathlib import Path
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
INBOUNDS = REPO / "roles/remnawave_inbounds"
INBOUNDS_MAIN = (INBOUNDS / "tasks/main.yml").read_text(encoding="utf-8")
RECONCILE = (INBOUNDS / "tasks/reconcile_squads.yml").read_text(encoding="utf-8")
RECONCILE_ONE = (INBOUNDS / "tasks/reconcile_one_squad.yml").read_text(encoding="utf-8")
CACHE = (REPO / "roles/remnawave_inbounds_cache/tasks/main.yml").read_text(encoding="utf-8")
REALITY = (REPO / "roles/remnawave_reality_servernames/tasks/main.yml").read_text(
    encoding="utf-8"
)
ES_MAIN = (REPO / "roles/remnawave_external_squads/tasks/main.yml").read_text(
    encoding="utf-8"
)
ES_ONE = (REPO / "roles/remnawave_external_squads/tasks/manage_one.yml").read_text(
    encoding="utf-8"
)
SPC_MAIN = (
    REPO / "roles/remnawave_subscription_page_config/tasks/main.yml"
).read_text(encoding="utf-8")
SPC_ONE = (
    REPO / "roles/remnawave_subscription_page_config/tasks/manage_one.yml"
).read_text(encoding="utf-8")
SPC_DEFAULTS = (
    REPO / "roles/remnawave_subscription_page_config/defaults/main.yml"
).read_text(encoding="utf-8")
ANTIBLOCK_PLAY = (REPO / "playbooks/antiblock_cdn.yml").read_text(encoding="utf-8")
ANTIBLOCK_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(encoding="utf-8")
)
ANTIBLOCK_RAW = (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(
    encoding="utf-8"
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


class ConfigProfileContractTests(unittest.TestCase):
    def test_get_list_uses_response_config_profiles(self) -> None:
        block = _task_block(INBOUNDS_MAIN, "Get config profiles")
        self.assertIn("/config-profiles", block)
        self.assertIn("method: GET", block)
        self.assertIn("status_code: 200", block)
        extract = _task_block(INBOUNDS_MAIN, "Extract config profile list from API response")
        self.assertIn("response.configProfiles", extract)

    def test_get_by_uuid_uses_response_config_and_inbounds(self) -> None:
        get_full = _task_block(INBOUNDS_MAIN, "Get full profile by uuid (with config)")
        self.assertIn("/config-profiles/{{ target_uuid }}", get_full)
        self.assertIn("method: GET", get_full)
        self.assertIn("status_code: 200", get_full)
        self.assertIn("response.config", INBOUNDS_MAIN)
        self.assertIn("response.inbounds", INBOUNDS_MAIN)

    def test_patch_sends_uuid_and_config_and_expects_200(self) -> None:
        patch = _task_block(INBOUNDS_MAIN, "PATCH config profile with merged config")
        self.assertIn("method: PATCH", patch)
        self.assertIn("uuid:", patch)
        self.assertIn("config:", patch)
        self.assertIn("status_code: [200, 409]", patch)
        retry = _task_block(INBOUNDS_MAIN, "Retry PATCH with auto-prefixed tags")
        self.assertIn("status_code: 200", retry)
        self.assertIn("uuid:", retry)
        self.assertIn("config:", retry)

    def test_deliberate_409_tag_collision_branch_preserved(self) -> None:
        self.assertIn("Handle global tag conflict (409) with auto-prefix", INBOUNDS_MAIN)
        self.assertIn("Fail on global inbound tag collision (409)", INBOUNDS_MAIN)
        self.assertIn("_ri.tag_collision_mode == 'fail'", INBOUNDS_MAIN)
        self.assertIn("_ri.tag_collision_mode == 'auto_prefix'", INBOUNDS_MAIN)

    def test_inbounds_cache_and_reality_get_inbounds_list(self) -> None:
        self.assertIn("/config-profiles/inbounds", CACHE)
        self.assertIn("response.inbounds", CACHE)
        self.assertIn("status_code: [200]", CACHE)
        self.assertIn("/config-profiles/inbounds", REALITY)
        self.assertIn("response.inbounds", REALITY)
        reality_patch = _task_block(REALITY, "Reality | PATCH /config-profiles")
        self.assertIn("uuid:", reality_patch)
        self.assertIn("config:", reality_patch)
        self.assertIn("status_code: [200]", reality_patch)


class InternalSquadContractTests(unittest.TestCase):
    def test_patch_sends_uuid_and_inbounds_and_expects_200(self) -> None:
        additive = _task_block(INBOUNDS_MAIN, "PATCH internal squad with merged inbounds")
        self.assertIn("/internal-squads", additive)
        self.assertIn("method: PATCH", additive)
        self.assertIn("status_code: 200", additive)
        self.assertIn("uuid:", additive)
        self.assertIn("inbounds:", additive)

        reconcile = _task_block(
            RECONCILE_ONE,
            "PATCH Internal Squad inbound membership on drift ({{ _ri_squad_name }})",
        )
        self.assertIn("/internal-squads", reconcile)
        self.assertIn("method: PATCH", reconcile)
        self.assertIn("status_code: 200", reconcile)
        self.assertIn("uuid:", reconcile)
        self.assertIn('inbounds: "{{ _ri_squad_reconciled.members }}"', reconcile)
        self.assertIn("when: _ri_squad_reconciled.needs_patch | bool", reconcile)

    def test_get_list_uses_response_internal_squads(self) -> None:
        get_list = _task_block(INBOUNDS_MAIN, "Get internal squads")
        self.assertIn("method: GET", get_list)
        self.assertIn("status_code: 200", get_list)
        self.assertIn("response.internalSquads", INBOUNDS_MAIN)

    def test_unrelated_members_preserved_by_reconcile_filter(self) -> None:
        self.assertIn("remnawave_reconcile_squad_members", RECONCILE_ONE)
        self.assertIn("remnawave_squad_inbound_uuids", RECONCILE_ONE)


class ExternalSquadContractTests(unittest.TestCase):
    def test_get_list_uses_response_external_squads(self) -> None:
        get_list = _task_block(ES_MAIN, "List External Squads from Remnawave API")
        self.assertIn("/api/external-squads", get_list)
        self.assertIn("method: GET", get_list)
        self.assertIn("status_code: 200", get_list)
        self.assertIn("response.externalSquads", ES_MAIN)

    def test_create_expects_only_201(self) -> None:
        create = _task_block(ES_ONE, "Create missing External Squad via Remnawave API")
        self.assertIn("method: POST", create)
        self.assertIn("name:", create)
        self.assertIn("status_code: [201]", create)
        self.assertNotIn("status_code: [200, 201]", create)
        self.assertIn("changed_when: _es_create_result.status | default(0) == 201", create)
        assert_block = _task_block(ES_ONE, "Fail with sanitized External Squad create error")
        self.assertIn("== 201", assert_block)
        self.assertNotIn("[200, 201]", assert_block)

    def test_update_expects_200(self) -> None:
        update = _task_block(ES_ONE, "Update External Squad via Remnawave API")
        self.assertIn("method: PATCH", update)
        self.assertIn("status_code: 200", update)
        self.assertIn("changed_when: _es_update_result.status | default(0) == 200", update)


class SubpageConfigContractTests(unittest.TestCase):
    def test_get_list_uses_response_configs(self) -> None:
        get_list = _task_block(SPC_MAIN, "List Subscription Page configs from Remnawave API")
        self.assertIn("/api/subscription-page-configs", get_list)
        self.assertIn("method: GET", get_list)
        self.assertIn("status_code: 200", get_list)
        self.assertIn("response.configs", SPC_MAIN)

    def test_create_expects_only_201(self) -> None:
        create = _task_block(SPC_ONE, "Create missing Subpage Config via Remnawave API")
        self.assertIn("method: POST", create)
        self.assertIn("name:", create)
        self.assertIn("status_code: [201]", create)
        self.assertNotIn("status_code: [200, 201]", create)
        self.assertIn("changed_when: _spc_create_result.status | default(0) == 201", create)
        assert_block = _task_block(SPC_ONE, "Fail with sanitized Subpage Config create error")
        self.assertIn("== 201", assert_block)
        self.assertNotIn("[200, 201]", assert_block)
        capture = _task_block(SPC_ONE, "Capture UUID from Subpage Config create response")
        self.assertIn("response.uuid", capture)
        self.assertIn("response.name", capture)
        self.assertIn("response.config", capture)

    def test_get_and_patch_use_response_config_and_expect_200(self) -> None:
        get_one = _task_block(SPC_ONE, "Get current Subpage Config body from Remnawave API")
        self.assertIn("method: GET", get_one)
        self.assertIn("status_code: 200", get_one)
        parse = _task_block(SPC_ONE, "Parse current Subpage Config body")
        self.assertIn("response.config", parse)
        update = _task_block(SPC_ONE, "Update Subpage Config via Remnawave API")
        self.assertIn("method: PATCH", update)
        self.assertIn("status_code: 200", update)
        self.assertIn("'uuid': _spc_uuid", update)
        self.assertIn("'config': _spc_desired", update)
        self.assertIn("changed_when: _spc_update_result.status | default(0) == 200", update)

    def test_active_comment_is_not_legacy_274(self) -> None:
        self.assertNotIn("API 2.7.4", SPC_DEFAULTS)
        self.assertIn("API 3.2.3", SPC_DEFAULTS)


class AntiblockInvariantTests(unittest.TestCase):
    def test_inbound_tag_comes_from_variable(self) -> None:
        self.assertEqual(
            ANTIBLOCK_VARS["antiblock_cdn_inbound_tag"],
            "VLESS xHTTP packet-up test",
        )
        self.assertIn("inbound_tag: \"{{ antiblock_cdn_inbound_tag }}\"", ANTIBLOCK_PLAY)
        self.assertIn("\"{{ antiblock_cdn_inbound }}\"", ANTIBLOCK_PLAY)
        inbound = ANTIBLOCK_VARS["antiblock_cdn_inbound"]
        self.assertEqual(inbound["tag"], "{{ antiblock_cdn_inbound_tag }}")

    def test_membership_requires_antiblock_squad_and_forbids_default(self) -> None:
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_internal_squad"], "AntiBlock-Squad")
        self.assertEqual(
            ANTIBLOCK_VARS["antiblock_cdn_forbidden_internal_squads"],
            ["Default-Squad"],
        )
        self.assertIn("present_in:", ANTIBLOCK_PLAY)
        self.assertIn("\"{{ antiblock_cdn_internal_squad }}\"", ANTIBLOCK_PLAY)
        self.assertIn("absent_from: \"{{ antiblock_cdn_forbidden_internal_squads }}\"", ANTIBLOCK_PLAY)
        self.assertNotIn("Default-Squad", ANTIBLOCK_PLAY.split("present_in:")[1].split("absent_from:")[0])

    def test_no_hardcoded_inbound_uuid_and_tag_is_stable(self) -> None:
        self.assertIsNone(UUID_RE.search(ANTIBLOCK_RAW))
        self.assertIsNone(UUID_RE.search(ANTIBLOCK_PLAY))
        self.assertIn("resolve the inbound by tag", ANTIBLOCK_RAW)
        self.assertIn("UUID is resolved by tag; it is not hardcoded", RECONCILE)

    def test_xhttp_raw_inbound_keeps_xhttp_settings_not_host_field(self) -> None:
        inbound = ANTIBLOCK_VARS["antiblock_cdn_inbound"]
        xhttp = inbound["streamSettings"]["xhttpSettings"]
        self.assertEqual(inbound["streamSettings"]["network"], "xhttp")
        self.assertEqual(xhttp["mode"], "packet-up")
        self.assertEqual(xhttp["path"], "{{ antiblock_cdn_path }}")
        self.assertEqual(
            ANTIBLOCK_VARS["antiblock_cdn_path"],
            "/static/main/video/segment.ts/m0ce971085771",
        )
        self.assertEqual(inbound["listen"], "127.0.0.1")
        self.assertEqual(inbound["port"], "{{ antiblock_cdn_inbound_port | int }}")
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_inbound_port"], 8447)
        inbound_text = ANTIBLOCK_RAW.split("antiblock_cdn_inbound:")[1].split(
            "antiblock_cdn_certificate:"
        )[0]
        self.assertIn("xhttpSettings:", inbound_text)
        self.assertNotIn("xhttpExtraParams", inbound_text)
        self.assertNotIn("xHttpExtraParams", inbound_text)
        self.assertNotIn("XHttpExtraParams", inbound_text)
        self.assertIn("antiblock_cdn_host_xhttp_extra_params", ANTIBLOCK_VARS)
        self.assertEqual(
            ANTIBLOCK_VARS["antiblock_cdn_host_xhttp_extra_params"]["uplinkHTTPMethod"],
            "GET",
        )
        self.assertNotIn("xHttpExtraParams", yaml.dump(ANTIBLOCK_VARS))
        self.assertNotIn("XHttpExtraParams", yaml.dump(ANTIBLOCK_VARS))


if __name__ == "__main__":
    unittest.main()
