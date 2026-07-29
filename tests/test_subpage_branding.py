#!/usr/bin/env python3
"""Unit tests for Subscription Page branding merge and API plan helpers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ROLE_FILES = ROOT / "roles/remnawave_subscription_page_config/files"
BASE = ROLE_FILES / "base.json"
VFF_PATCH = ROLE_FILES / "brands/vpn-for-friends.patch.json"
FC_PATCH = ROLE_FILES / "brands/friends-connect.patch.json"
GOLDEN = ROOT / "tests/fixtures/vpn-for-friends.golden.json"
BUILD = SCRIPTS / "build_subpage_config.py"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "roles/remnawave_subscription_page_config/filter_plugins"))

from remnawave_subpage_config import FilterModule  # noqa: E402
from subpage_branding import (  # noqa: E402
    ALLOWED_BRAND_DIFF_PATHS,
    assert_only_brand_diffs,
    build_external_squad_patch_body,
    collect_diff_paths,
    configs_equal,
    deep_merge,
    merge_external_squad_subscription_settings,
    plan_external_squad_action,
    plan_subpage_config_action,
    profile_title_needs_update,
    resolve_external_squad_subpage_binding,
    resolve_subpage_uuid_by_name,
    verify_external_squad_patch_response,
)


def canonicalize(config: dict) -> dict:
    return FilterModule().canonicalize(config)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class DeepMergeTests(unittest.TestCase):
    def test_merge_vff_equals_golden_raw_and_canonical(self) -> None:
        built = deep_merge(load(BASE), load(VFF_PATCH))
        golden = load(GOLDEN)
        self.assertTrue(configs_equal(built, golden))
        self.assertTrue(configs_equal(canonicalize(built), canonicalize(golden)))

    def test_merge_fc_only_allowed_brand_paths_differ(self) -> None:
        vff = deep_merge(load(BASE), load(VFF_PATCH))
        fc = deep_merge(load(BASE), load(FC_PATCH))
        unexpected = assert_only_brand_diffs(vff, fc)
        self.assertEqual(unexpected, [])
        self.assertEqual(fc["brandingSettings"]["title"], "Friends Connect")
        self.assertEqual(vff["brandingSettings"]["title"], "VPN for friends")

    def test_vff_and_fc_share_neutral_logo_url(self) -> None:
        vff = deep_merge(load(BASE), load(VFF_PATCH))
        fc = deep_merge(load(BASE), load(FC_PATCH))
        logo = "https://remna.st/img/logo.svg"
        self.assertEqual(vff["brandingSettings"]["logoUrl"], logo)
        self.assertEqual(fc["brandingSettings"]["logoUrl"], logo)
        self.assertNotIn("logoUrl", load(VFF_PATCH)["brandingSettings"])
        self.assertNotIn("logoUrl", load(FC_PATCH)["brandingSettings"])
        self.assertEqual(load(BASE)["brandingSettings"]["logoUrl"], logo)
        unexpected = assert_only_brand_diffs(vff, fc)
        self.assertEqual(unexpected, [])
        self.assertNotIn("$.brandingSettings.logoUrl", collect_diff_paths(vff, fc))

    def test_brand_happ_redirect_links(self) -> None:
        vff = deep_merge(load(BASE), load(VFF_PATCH))
        fc = deep_merge(load(BASE), load(FC_PATCH))
        path = ("platforms", "windows", "apps", 0, "blocks", 1, "buttons", 0, "link")
        vff_link = vff["platforms"]["windows"]["apps"][0]["blocks"][1]["buttons"][0]["link"]
        fc_link = fc["platforms"]["windows"]["apps"][0]["blocks"][1]["buttons"][0]["link"]
        self.assertEqual(
            vff_link,
            "https://vff.portalbase.link/redirect.html?url=happ://add/{{SUBSCRIPTION_LINK}}",
        )
        self.assertEqual(
            fc_link,
            "https://fc.portalbase.link/redirect.html?url=happ://add/{{SUBSCRIPTION_LINK}}",
        )
        self.assertIn("vff.portalbase.link/redirect.html", vff_link)
        self.assertIn("fc.portalbase.link/redirect.html", fc_link)
        self.assertNotIn("vpn-for-friends.com/redirect.html", json.dumps(vff))
        self.assertNotIn("vpn-for-friends.com/redirect.html", json.dumps(fc))
        self.assertFalse(fc_link.startswith("happ://"), path)
        unexpected = assert_only_brand_diffs(vff, fc)
        self.assertEqual(unexpected, [])
        self.assertIn(
            "$.platforms.windows.apps[0].blocks[1].buttons[0].link",
            collect_diff_paths(vff, fc),
        )

    def test_allowed_brand_paths_constant_covers_audit(self) -> None:
        expected = {
            "$.brandingSettings.title",
            "$.brandingSettings.supportUrl",
            "$.baseSettings.metaTitle",
            "$.platforms.windows.apps[0].blocks[1].buttons[0].link",
        }
        self.assertEqual(set(ALLOWED_BRAND_DIFF_PATHS), expected)

    def test_common_structure_preserved(self) -> None:
        vff = deep_merge(load(BASE), load(VFF_PATCH))
        fc = deep_merge(load(BASE), load(FC_PATCH))
        for key in (
            "locales",
            "version",
            "uiConfig",
            "platforms",
            "svgLibrary",
            "baseTranslations",
        ):
            if key == "platforms":
                self.assertEqual(set(vff[key]), set(fc[key]))
                for platform in vff[key]:
                    self.assertEqual(
                        [app["name"] for app in vff[key][platform]["apps"]],
                        [app["name"] for app in fc[key][platform]["apps"]],
                    )
            elif key == "svgLibrary":
                self.assertEqual(set(vff[key]), set(fc[key]))
            else:
                self.assertEqual(vff[key], fc[key], key)

    def test_null_deletes_key(self) -> None:
        merged = deep_merge({"a": 1, "b": 2}, {"b": None})
        self.assertEqual(merged, {"a": 1})

    def test_list_of_dicts_merges_by_index(self) -> None:
        base = {"apps": [{"name": "Happ", "link": "a"}, {"name": "Other", "link": "b"}]}
        patch = {"apps": [{"link": "c"}, {}]}
        merged = deep_merge(base, patch)
        self.assertEqual(merged["apps"][0]["name"], "Happ")
        self.assertEqual(merged["apps"][0]["link"], "c")
        self.assertEqual(merged["apps"][1], {"name": "Other", "link": "b"})


class BuildScriptTests(unittest.TestCase):
    def test_cli_build_vff_and_fc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vff_out = Path(tmp) / "vff.json"
            fc_out = Path(tmp) / "fc.json"
            for brand, out in (("vff", vff_out), ("fc", fc_out)):
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(BUILD),
                        "--brand",
                        brand,
                        "--output",
                        str(out),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(out.is_file())
            self.assertTrue(configs_equal(load(vff_out), load(GOLDEN)))
            unexpected = assert_only_brand_diffs(load(vff_out), load(fc_out))
            self.assertEqual(unexpected, [])

    def test_cli_fails_on_missing_patch(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(BUILD),
                "--base",
                str(BASE),
                "--patch",
                "/tmp/does-not-exist-brand-patch.json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)


class SubpageConfigPlanTests(unittest.TestCase):
    def test_create_when_missing_and_no_duplicate_on_rerun(self) -> None:
        desired = {"version": "1"}
        first = plan_subpage_config_action(
            [],
            name="Friends Connect",
            uuid="",
            desired_config=desired,
            check_mode=False,
        )
        self.assertTrue(first["create"])
        self.assertIn("POST", first["http_methods"])

        existing = [{"uuid": "11111111-1111-1111-1111-111111111111", "name": "Friends Connect", "config": desired}]
        second = plan_subpage_config_action(
            existing,
            name="Friends Connect",
            uuid="",
            desired_config=desired,
            check_mode=False,
        )
        self.assertFalse(second["create"])
        self.assertFalse(second["patch_config"])
        self.assertEqual(second["http_methods"], [])

    def test_check_mode_skips_http_methods(self) -> None:
        plan = plan_subpage_config_action(
            [],
            name="Friends Connect",
            uuid="",
            desired_config={"version": "1"},
            check_mode=True,
        )
        self.assertTrue(plan["create"])
        self.assertEqual(plan["http_methods"], [])

        existing = [
            {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "name": "VPN for friends",
                "config": {"a": 1},
            }
        ]
        update_plan = plan_subpage_config_action(
            existing,
            name="VPN for friends",
            uuid="11111111-1111-1111-1111-111111111111",
            desired_config={"a": 2},
            check_mode=True,
        )
        self.assertTrue(update_plan["patch_config"])
        self.assertEqual(update_plan["http_methods"], [])


class ExternalSquadPlanTests(unittest.TestCase):
    def test_create_when_missing_and_idempotent_rerun(self) -> None:
        first = plan_external_squad_action(
            [],
            name="Friends-Connect",
            desired_subpage_config_uuid="22222222-2222-2222-2222-222222222222",
            check_mode=False,
        )
        self.assertTrue(first["create"])
        self.assertIn("POST", first["http_methods"])

        existing = [
            {
                "uuid": "33333333-3333-3333-3333-333333333333",
                "name": "Friends-Connect",
                "subpageConfigUuid": "22222222-2222-2222-2222-222222222222",
            }
        ]
        second = plan_external_squad_action(
            existing,
            name="Friends-Connect",
            desired_subpage_config_uuid="22222222-2222-2222-2222-222222222222",
            check_mode=False,
        )
        self.assertFalse(second["create"])
        self.assertFalse(second["patch_subpage"])
        self.assertEqual(second["http_methods"], [])

    def test_protected_antiblock_premium_not_managed(self) -> None:
        plan = plan_external_squad_action(
            [{"uuid": "44444444-4444-4444-4444-444444444444", "name": "AntiBlock-Premium"}],
            name="AntiBlock-Premium",
            desired_subpage_config_uuid="22222222-2222-2222-2222-222222222222",
            protected_names=["AntiBlock-Premium"],
            check_mode=False,
        )
        self.assertTrue(plan["skip"])
        self.assertTrue(plan["protected"])
        self.assertEqual(plan["http_methods"], [])
        self.assertIsNotNone(plan["error"])

    def test_unknown_subpage_name_raises(self) -> None:
        with self.assertRaises(LookupError) as ctx:
            resolve_subpage_uuid_by_name(
                [{"uuid": "11111111-1111-1111-1111-111111111111", "name": "VPN for friends"}],
                "Does Not Exist",
            )
        self.assertIn("Unknown Subpage Config name", str(ctx.exception))

    def test_check_mode_no_post_patch(self) -> None:
        plan = plan_external_squad_action(
            [],
            name="VPN-for-Friends",
            desired_subpage_config_uuid="22222222-2222-2222-2222-222222222222",
            check_mode=True,
        )
        self.assertTrue(plan["create"])
        self.assertEqual(plan["http_methods"], [])

    def test_declared_missing_subpage_defers_in_check_mode(self) -> None:
        binding = resolve_external_squad_subpage_binding(
            subpage_name="Friends Connect",
            remote_configs=[
                {
                    "uuid": "f24bc0b1-2386-4473-9bde-9cd7b384641c",
                    "name": "VPN for friends",
                }
            ],
            declared_configs=[
                {"key": "vff", "name": "VPN for friends"},
                {"key": "fc", "name": "Friends Connect"},
            ],
            resolved_map={
                "fc": {
                    "name": "Friends Connect",
                    "uuid": "",
                    "planned_create": True,
                }
            },
            check_mode=True,
        )
        self.assertTrue(binding["ok"])
        self.assertTrue(binding["deferred"])
        self.assertTrue(binding["declared"])
        self.assertEqual(binding["uuid"], "")

        plan = plan_external_squad_action(
            [],
            name="Friends-Connect",
            desired_subpage_config_uuid="",
            check_mode=True,
            subpage_deferred=True,
            subpage_name="Friends Connect",
        )
        self.assertTrue(plan["deferred"])
        self.assertTrue(plan["create"])
        self.assertEqual(plan["http_methods"], [])
        self.assertIn("would be created after Subpage Config 'Friends Connect'", plan["message"])

    def test_undeclared_unknown_subpage_errors_in_check_mode(self) -> None:
        binding = resolve_external_squad_subpage_binding(
            subpage_name="Nonexistent Config",
            remote_configs=[
                {
                    "uuid": "f24bc0b1-2386-4473-9bde-9cd7b384641c",
                    "name": "VPN for friends",
                }
            ],
            declared_configs=[{"key": "vff", "name": "VPN for friends"}],
            resolved_map={},
            check_mode=True,
        )
        self.assertFalse(binding["ok"])
        self.assertFalse(binding["deferred"])
        self.assertIn("Unknown Subpage Config name", binding["error"])

    def test_apply_mode_requires_non_empty_uuid(self) -> None:
        binding = resolve_external_squad_subpage_binding(
            subpage_name="Friends Connect",
            remote_configs=[],
            declared_configs=[{"key": "fc", "name": "Friends Connect"}],
            resolved_map={
                "fc": {"name": "Friends Connect", "uuid": "", "planned_create": True}
            },
            check_mode=False,
        )
        self.assertFalse(binding["ok"])
        self.assertTrue(binding["declared"])

        plan = plan_external_squad_action(
            [],
            name="Friends-Connect",
            desired_subpage_config_uuid="",
            check_mode=False,
            subpage_deferred=False,
            subpage_name="Friends Connect",
        )
        self.assertTrue(plan["skip"])
        self.assertIsNotNone(plan["error"])
        self.assertEqual(plan["http_methods"], [])

    def test_existing_vff_resolves_by_uuid(self) -> None:
        vff_uuid = "f24bc0b1-2386-4473-9bde-9cd7b384641c"
        binding = resolve_external_squad_subpage_binding(
            subpage_name="VPN for friends",
            remote_configs=[{"uuid": vff_uuid, "name": "VPN for friends"}],
            declared_configs=[
                {"key": "vff", "name": "VPN for friends", "uuid": vff_uuid},
            ],
            resolved_map={
                "vff": {
                    "name": "VPN for friends",
                    "uuid": vff_uuid,
                    "planned_create": False,
                }
            },
            check_mode=True,
        )
        self.assertTrue(binding["ok"])
        self.assertFalse(binding["deferred"])
        self.assertEqual(binding["uuid"], vff_uuid)


class ExternalSquadProfileTitleTests(unittest.TestCase):
    VFF_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    FC_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    VFF_SUBPAGE = "f24bc0b1-2386-4473-9bde-9cd7b384641c"
    FC_SUBPAGE = "cccccccc-cccc-cccc-cccc-cccccccccccc"

    def test_merge_sets_brand_profile_titles(self) -> None:
        vff = merge_external_squad_subscription_settings(
            {"supportLink": "https://t.me/support"},
            profile_title="VPN for friends",
        )
        fc = merge_external_squad_subscription_settings(
            None,
            profile_title="Friends Connect",
        )
        self.assertEqual(vff["profileTitle"], "VPN for friends")
        self.assertEqual(fc["profileTitle"], "Friends Connect")
        self.assertEqual(vff["supportLink"], "https://t.me/support")

    def test_merge_preserves_existing_subscription_settings(self) -> None:
        current = {
            "supportLink": "https://t.me/support",
            "profileUpdateInterval": 12,
            "isProfileWebpageUrlEnabled": True,
            "serveJsonAtBaseSubscription": False,
            "isShowCustomRemarks": True,
            "happAnnounce": "hello",
            "happRouting": "route",
            "randomizeHosts": False,
            "profileTitle": "Old Title",
        }
        merged = merge_external_squad_subscription_settings(
            current,
            profile_title="Friends Connect",
        )
        for key, value in current.items():
            if key == "profileTitle":
                continue
            self.assertEqual(merged[key], value, key)
        self.assertEqual(merged["profileTitle"], "Friends Connect")

    def test_null_subscription_settings_treated_as_empty_object(self) -> None:
        merged = merge_external_squad_subscription_settings(
            None,
            profile_title="VPN for friends",
        )
        self.assertEqual(merged, {"profileTitle": "VPN for friends"})
        self.assertTrue(profile_title_needs_update(None, "VPN for friends"))

    def test_matching_profile_title_skips_patch(self) -> None:
        existing = [
            {
                "uuid": self.FC_UUID,
                "name": "Friends-Connect",
                "subpageConfigUuid": self.FC_SUBPAGE,
                "subscriptionSettings": {
                    "profileTitle": "Friends Connect",
                    "supportLink": "https://t.me/support",
                },
            }
        ]
        plan = plan_external_squad_action(
            existing,
            name="Friends-Connect",
            desired_subpage_config_uuid=self.FC_SUBPAGE,
            desired_profile_title="Friends Connect",
            check_mode=False,
        )
        self.assertFalse(plan["patch_subpage"])
        self.assertFalse(plan["patch_profile_title"])
        self.assertEqual(plan["http_methods"], [])

        body = build_external_squad_patch_body(
            uuid=self.FC_UUID,
            desired_subpage_config_uuid=self.FC_SUBPAGE,
            current_subpage_config_uuid=self.FC_SUBPAGE,
            current_subscription_settings=existing[0]["subscriptionSettings"],
            desired_profile_title="Friends Connect",
        )
        self.assertEqual(body, {"uuid": self.FC_UUID})

    def test_profile_title_change_preserves_subpage_uuid_in_patch_body(self) -> None:
        current_settings = {
            "profileTitle": "Old",
            "supportLink": "https://t.me/support",
            "happAnnounce": "keep-me",
        }
        body = build_external_squad_patch_body(
            uuid=self.VFF_UUID,
            desired_subpage_config_uuid=self.VFF_SUBPAGE,
            current_subpage_config_uuid=self.VFF_SUBPAGE,
            current_subscription_settings=current_settings,
            desired_profile_title="VPN for friends",
        )
        self.assertNotIn("subpageConfigUuid", body)
        self.assertEqual(body["uuid"], self.VFF_UUID)
        self.assertEqual(
            body["subscriptionSettings"]["profileTitle"],
            "VPN for friends",
        )
        self.assertEqual(body["subscriptionSettings"]["supportLink"], "https://t.me/support")
        self.assertEqual(body["subscriptionSettings"]["happAnnounce"], "keep-me")
        self.assertIsNotNone(body["subscriptionSettings"])

    def test_verify_keeps_subpage_and_other_settings(self) -> None:
        before = {
            "uuid": self.FC_UUID,
            "name": "Friends-Connect",
            "subpageConfigUuid": self.FC_SUBPAGE,
            "subscriptionSettings": {
                "profileTitle": "Old",
                "supportLink": "https://t.me/support",
                "randomizeHosts": True,
            },
        }
        after = {
            "uuid": self.FC_UUID,
            "name": "Friends-Connect",
            "subpageConfigUuid": self.FC_SUBPAGE,
            "subscriptionSettings": {
                "profileTitle": "Friends Connect",
                "supportLink": "https://t.me/support",
                "randomizeHosts": True,
            },
        }
        errors = verify_external_squad_patch_response(
            before,
            after,
            desired_profile_title="Friends Connect",
            desired_subpage_config_uuid=self.FC_SUBPAGE,
        )
        self.assertEqual(errors, [])

    def test_antiblock_premium_still_protected(self) -> None:
        plan = plan_external_squad_action(
            [{"uuid": self.VFF_UUID, "name": "AntiBlock-Premium"}],
            name="AntiBlock-Premium",
            desired_subpage_config_uuid=self.VFF_SUBPAGE,
            desired_profile_title="Should Not Apply",
            protected_names=["AntiBlock-Premium"],
            check_mode=False,
        )
        self.assertTrue(plan["skip"])
        self.assertEqual(plan["http_methods"], [])

    def test_idempotent_rerun_after_profile_title_applied(self) -> None:
        existing = [
            {
                "uuid": self.VFF_UUID,
                "name": "VPN-for-Friends",
                "subpageConfigUuid": self.VFF_SUBPAGE,
                "subscriptionSettings": {
                    "profileTitle": "VPN for friends",
                    "supportLink": "https://t.me/support",
                },
            }
        ]
        first = plan_external_squad_action(
            existing,
            name="VPN-for-Friends",
            desired_subpage_config_uuid=self.VFF_SUBPAGE,
            desired_profile_title="VPN for friends",
            check_mode=False,
        )
        second = plan_external_squad_action(
            existing,
            name="VPN-for-Friends",
            desired_subpage_config_uuid=self.VFF_SUBPAGE,
            desired_profile_title="VPN for friends",
            check_mode=False,
        )
        self.assertEqual(first["http_methods"], [])
        self.assertEqual(second["http_methods"], [])
        self.assertFalse(first["patch_profile_title"])
        self.assertFalse(second["patch_profile_title"])


if __name__ == "__main__":
    unittest.main()
