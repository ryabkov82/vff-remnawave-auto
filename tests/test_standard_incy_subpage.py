#!/usr/bin/env python3
"""INCY as the recommended Standard Subscription Page client."""

from __future__ import annotations

import json
import re
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
BUILD = SCRIPTS / "build_subpage_config.py"

sys.path.insert(0, str(SCRIPTS))
from subpage_branding import assert_only_brand_diffs, deep_merge  # noqa: E402

INCY_IMPORT = "incy://import/{{SUBSCRIPTION_LINK}}"
ANDROID_ORDER = ["INCY", "Happ", "v2RayTun", "Hiddify", "Clash Meta", "FlClashX", "v2rayNG"]
IOS_ORDER = ["INCY", "OneXray", "Shadowrocket", "Happ", "v2RayTun", "Streisand", "Stash"]
WINDOWS_ORDER = [
    "INCY",
    "Happ",
    "v2RayTun",
    "Hiddify",
    "Clash Verge",
    "FlClashX",
    "Koala Clash",
    "Prizrak-Box",
]
INCY_PLATFORMS = ("android", "ios", "windows")
OTHER_PLATFORMS = ("macos", "linux", "appleTV", "androidTV")
PREMIUM_MARKERS = ("incy://crypt1/", "{{INCY_CRYPT1_LINK}}")
PROTECTED_INCY_PATH = re.compile(r"(?<!/app)/incy/")
INCY_INSTALL = {
    "android": (
        "https://play.google.com/store/apps/details?id=llc.itdev.incy",
        "https://github.com/INCY-DEV/incy-platforms/releases/latest/download/Incy.apk",
    ),
    "ios": ("https://apps.apple.com/ru/app/incy/id6756943388",),
    "windows": (
        "https://github.com/INCY-DEV/incy-platforms/releases/latest/download/incy-windows-setup.exe",
    ),
}
HAPP_ANDROID_INSTALL = (
    "https://play.google.com/store/apps/details?id=com.happproxy",
    "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk",
)
HAPP_IMPORT = "happ://add/{{SUBSCRIPTION_LINK}}"
VFF_HAPP_REDIRECT = (
    "https://vff.portalbase.link/redirect.html?url=happ://add/{{SUBSCRIPTION_LINK}}"
)
FC_HAPP_REDIRECT = (
    "https://fc.portalbase.link/redirect.html?url=happ://add/{{SUBSCRIPTION_LINK}}"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_button_links(app: dict) -> list[str]:
    links: list[str] = []
    for block in app.get("blocks", []):
        for button in block.get("buttons", []):
            link = button.get("link")
            if isinstance(link, str) and link:
                links.append(link)
    return links


def collect_typed_links(app: dict, button_type: str) -> list[str]:
    links: list[str] = []
    for block in app.get("blocks", []):
        for button in block.get("buttons", []):
            if button.get("type") == button_type and isinstance(button.get("link"), str):
                links.append(button["link"])
    return links


class StandardIncySubpageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vff = deep_merge(load(BASE), load(VFF_PATCH))
        cls.fc = deep_merge(load(BASE), load(FC_PATCH))
        cls.configs = {"vff": cls.vff, "fc": cls.fc}

    def test_incy_is_first_featured_app(self) -> None:
        for brand, config in self.configs.items():
            for platform in INCY_PLATFORMS:
                app = config["platforms"][platform]["apps"][0]
                self.assertEqual(app["name"], "INCY", f"{brand}/{platform}")
                self.assertTrue(app["featured"], f"{brand}/{platform}")

    def test_incy_import_is_official_raw_subscription_link(self) -> None:
        for brand, config in self.configs.items():
            for platform in INCY_PLATFORMS:
                imports = collect_typed_links(
                    config["platforms"][platform]["apps"][0],
                    "subscriptionLink",
                )
                self.assertEqual(imports, [INCY_IMPORT], f"{brand}/{platform}")

    def test_incy_official_install_urls(self) -> None:
        for brand, config in self.configs.items():
            for platform, expected in INCY_INSTALL.items():
                links = collect_typed_links(
                    config["platforms"][platform]["apps"][0],
                    "external",
                )
                self.assertEqual(tuple(links), expected, f"{brand}/{platform}")

    def test_resulting_app_order(self) -> None:
        expected = {
            "android": ANDROID_ORDER,
            "ios": IOS_ORDER,
            "windows": WINDOWS_ORDER,
        }
        for brand, config in self.configs.items():
            for platform, names in expected.items():
                actual = [app["name"] for app in config["platforms"][platform]["apps"]]
                self.assertEqual(actual, names, f"{brand}/{platform}")

    def test_incy_not_added_to_other_platforms(self) -> None:
        for brand, config in self.configs.items():
            for platform in OTHER_PLATFORMS:
                names = [app["name"] for app in config["platforms"][platform]["apps"]]
                self.assertNotIn("INCY", names, f"{brand}/{platform}")

    def test_android_happ_stays_at_index_one(self) -> None:
        for brand, config in self.configs.items():
            happ = config["platforms"]["android"]["apps"][1]
            self.assertEqual(happ["name"], "Happ", brand)
            links = collect_button_links(happ)
            for expected in HAPP_ANDROID_INSTALL:
                self.assertIn(expected, links, brand)
            self.assertIn(HAPP_IMPORT, collect_typed_links(happ, "subscriptionLink"))

    def test_ios_happ_stays_after_incy_prepend(self) -> None:
        for brand, config in self.configs.items():
            happ = config["platforms"]["ios"]["apps"][3]
            self.assertEqual(happ["name"], "Happ", brand)
            self.assertFalse(happ.get("featured"), brand)
            self.assertEqual(collect_typed_links(happ, "subscriptionLink"), [HAPP_IMPORT])
            self.assertEqual(happ["svgIconKey"], "Happ")

    def test_windows_happ_is_index_one_with_brand_redirect(self) -> None:
        self.assertEqual(self.vff["platforms"]["windows"]["apps"][1]["name"], "Happ")
        self.assertEqual(self.fc["platforms"]["windows"]["apps"][1]["name"], "Happ")
        vff_link = self.vff["platforms"]["windows"]["apps"][1]["blocks"][1]["buttons"][0]["link"]
        fc_link = self.fc["platforms"]["windows"]["apps"][1]["blocks"][1]["buttons"][0]["link"]
        self.assertEqual(vff_link, VFF_HAPP_REDIRECT)
        self.assertEqual(fc_link, FC_HAPP_REDIRECT)
        windows_incy_vff = collect_typed_links(
            self.vff["platforms"]["windows"]["apps"][0],
            "subscriptionLink",
        )
        windows_incy_fc = collect_typed_links(
            self.fc["platforms"]["windows"]["apps"][0],
            "subscriptionLink",
        )
        self.assertEqual(windows_incy_vff, [INCY_IMPORT])
        self.assertEqual(windows_incy_fc, [INCY_IMPORT])
        self.assertNotIn("redirect.html", json.dumps(windows_incy_vff))
        self.assertNotIn("redirect.html", json.dumps(windows_incy_fc))

    def test_standard_has_no_premium_protection_markers(self) -> None:
        for brand, config in self.configs.items():
            blob = json.dumps(config, ensure_ascii=False)
            for marker in PREMIUM_MARKERS:
                self.assertNotIn(marker, blob, f"{brand} contains {marker}")
            self.assertIsNone(
                PROTECTED_INCY_PATH.search(blob),
                f"{brand} contains protected /incy/ path",
            )

    def test_hide_get_link_button_remains_false(self) -> None:
        for brand, config in self.configs.items():
            self.assertIs(config["baseSettings"]["hideGetLinkButton"], False, brand)

    def test_brand_diff_allowlist_clean(self) -> None:
        unexpected = assert_only_brand_diffs(self.vff, self.fc)
        self.assertEqual(unexpected, [])

    def test_cli_build_both_brands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for brand in ("vff", "fc"):
                out = Path(tmp) / f"{brand}.json"
                completed = subprocess.run(
                    [sys.executable, str(BUILD), "--brand", brand, "--output", str(out)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                built = load(out)
                self.assertEqual(built["platforms"]["android"]["apps"][0]["name"], "INCY")
                self.assertEqual(built["platforms"]["ios"]["apps"][0]["name"], "INCY")
                self.assertEqual(built["platforms"]["windows"]["apps"][0]["name"], "INCY")
                self.assertEqual(built["platforms"]["windows"]["apps"][1]["name"], "Happ")


if __name__ == "__main__":
    unittest.main()
