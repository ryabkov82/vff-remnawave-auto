#!/usr/bin/env python3
"""Tests for VPN for Friends platform merge in build script."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_FILES = ROOT / "roles/remnawave_subscription_page_config/files"
DEFAULT_JSON = ROLE_FILES / "source/default-7.2.1.json"
DESIRED_JSON = ROOT / "tests/fixtures/vpn-for-friends.golden.json"
BUILD_SCRIPT = ROOT / "scripts/build_vpn_for_friends_subpage_config.py"
VALIDATE_SCRIPT = ROOT / "scripts/validate_subpage_config.py"

sys.path.insert(0, str(ROOT / "roles/remnawave_subscription_page_config/filter_plugins"))
from remnawave_subpage_config import FilterModule  # noqa: E402

FORBIDDEN_URL_PATTERNS = (
    re.compile(r"example\.com", re.I),
    re.compile(r"localhost", re.I),
    re.compile(r"127\.0\.0\.1", re.I),
    re.compile(r"placeholder", re.I),
)

IOS_CUSTOM_ORDER = ["INCY", "OneXray", "Shadowrocket", "Happ", "v2RayTun", "Streisand", "Stash"]
BRAND_BUILD_SCRIPT = ROOT / "scripts/build_subpage_config.py"


def canonicalize(config: dict) -> dict:
    return FilterModule().canonicalize(config)


def collect_button_links(platforms: dict) -> list[tuple[str, str, str]]:
    links: list[tuple[str, str, str]] = []
    for platform_key, platform in platforms.items():
        for app in platform.get("apps", []):
            app_name = app.get("name", "")
            for block in app.get("blocks", []):
                for button in block.get("buttons", []):
                    link = button.get("link", "")
                    if isinstance(link, str) and link:
                        links.append((platform_key, app_name, link))
    return links


def collect_svg_icon_keys(value, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "svgIconKey" and isinstance(item, str):
                found.add(item)
            collect_svg_icon_keys(item, found)
    elif isinstance(value, list):
        for item in value:
            collect_svg_icon_keys(item, found)


class VpnForFriendsPlatformMergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.default = json.loads(DEFAULT_JSON.read_text(encoding="utf-8"))
        cls.desired = json.loads(DESIRED_JSON.read_text(encoding="utf-8"))
        cls.default_platform_order = list(cls.default["platforms"].keys())
        cls.default_platform_keys = set(cls.default_platform_order)

    def _run_build(self, output: Path) -> dict:
        subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
            check=True,
            cwd=ROOT,
        )
        return json.loads(output.read_text(encoding="utf-8"))

    def test_all_default_platform_ids_present(self) -> None:
        desired_keys = set(self.desired["platforms"].keys())
        self.assertTrue(self.default_platform_keys <= desired_keys)

    def test_platform_ids_unique(self) -> None:
        keys = list(self.desired["platforms"].keys())
        self.assertEqual(len(keys), len(set(keys)))

    def test_default_platform_order_preserved(self) -> None:
        desired_keys = list(self.desired["platforms"].keys())
        default_prefix = [k for k in desired_keys if k in self.default_platform_order]
        self.assertEqual(default_prefix, self.default_platform_order)

    def test_each_platform_has_app_names(self) -> None:
        for platform_key, platform in self.desired["platforms"].items():
            apps = platform.get("apps", [])
            names = [app.get("name") for app in apps]
            self.assertTrue(all(names), f"{platform_key} has unnamed app")
            self.assertEqual(len(names), len(set(names)), f"{platform_key} duplicate apps")

    def test_no_dangling_svg_icon_references(self) -> None:
        library = set(self.desired["svgLibrary"].keys())
        used: set[str] = set()
        collect_svg_icon_keys(self.desired["platforms"], used)
        self.assertFalse(used - library, f"unknown svgIconKey: {sorted(used - library)}")

    def test_visible_platforms_have_at_least_one_app(self) -> None:
        for platform_key, platform in self.desired["platforms"].items():
            apps = platform.get("apps", [])
            self.assertGreater(len(apps), 0, f"{platform_key} has no apps")

    def test_no_forbidden_placeholder_urls(self) -> None:
        for platform_key, app_name, link in collect_button_links(self.desired["platforms"]):
            for pattern in FORBIDDEN_URL_PATTERNS:
                self.assertIsNone(
                    pattern.search(link),
                    f"{platform_key}/{app_name}: forbidden URL {link!r}",
                )

    def test_required_buttons_have_non_empty_links(self) -> None:
        for platform_key, platform in self.desired["platforms"].items():
            for app in platform.get("apps", []):
                for block in app.get("blocks", []):
                    for button in block.get("buttons", []):
                        if button.get("type") in {"external", "subscriptionLink"}:
                            link = button.get("link", "")
                            self.assertTrue(
                                isinstance(link, str) and link.strip(),
                                f"{platform_key}/{app['name']}: empty link",
                            )

    def test_rebuild_is_idempotent(self) -> None:
        first = Path("/tmp/vpn-for-friends.idempotent-1.json")
        second = Path("/tmp/vpn-for-friends.idempotent-2.json")
        built_1 = self._run_build(first)
        built_2 = self._run_build(second)
        self.assertEqual(canonicalize(built_1), canonicalize(built_2))

    def _run_brand_build(self, output: Path) -> dict:
        subprocess.run(
            [sys.executable, str(BRAND_BUILD_SCRIPT), "--brand", "vff", "--output", str(output)],
            check=True,
            cwd=ROOT,
        )
        return json.loads(output.read_text(encoding="utf-8"))

    def test_committed_desired_matches_generator_canonical(self) -> None:
        generated = Path("/tmp/vpn-for-friends.canonical-check.json")
        built = self._run_brand_build(generated)
        self.assertEqual(canonicalize(self.desired), canonicalize(built))

    def test_custom_ios_apps_preserved(self) -> None:
        ios_apps = self.desired["platforms"]["ios"]["apps"]
        ios_names = [app["name"] for app in ios_apps]
        self.assertEqual(ios_names[: len(IOS_CUSTOM_ORDER)], IOS_CUSTOM_ORDER)

    def test_custom_platform_apps_not_replaced_by_default(self) -> None:
        """Custom apps from legacy transform must remain byte-identical after merge."""
        before_path = Path("/tmp/vpn-for-friends.before-merge-baseline.json")
        if not before_path.exists():
            self.skipTest("baseline before-merge file not available")
        before = json.loads(before_path.read_text(encoding="utf-8"))

        for platform_key in ("ios", "android", "windows"):
            before_apps = {app["name"]: app for app in before["platforms"][platform_key]["apps"]}
            after_apps = {app["name"]: app for app in self.desired["platforms"][platform_key]["apps"]}
            for name in before_apps:
                self.assertIn(name, after_apps, f"{platform_key}/{name} removed")
                self.assertEqual(
                    after_apps[name],
                    before_apps[name],
                    f"{platform_key}/{name} replaced by default",
                )

    def test_default_only_apps_added_from_upstream(self) -> None:
        for platform_key in self.default_platform_order:
            default_names = {app["name"] for app in self.default["platforms"][platform_key]["apps"]}
            desired_names = {app["name"] for app in self.desired["platforms"][platform_key]["apps"]}
            missing = default_names - desired_names
            self.assertFalse(
                missing,
                f"{platform_key} still missing default apps: {sorted(missing)}",
            )

    def test_validator_accepts_generated_config(self) -> None:
        output = Path("/tmp/vpn-for-friends.validator-check.json")
        self._run_brand_build(output)
        result = subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
