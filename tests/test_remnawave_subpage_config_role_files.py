#!/usr/bin/env python3
"""Tests for Subscription Page v7 declarative config file layout."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/remnawave_subscription_page_config"
ROLE_FILES = ROLE / "files"
BASE_JSON = ROLE_FILES / "base.json"
VFF_PATCH = ROLE_FILES / "brands/vpn-for-friends.patch.json"
FC_PATCH = ROLE_FILES / "brands/friends-connect.patch.json"
GOLDEN_JSON = ROOT / "tests/fixtures/vpn-for-friends.golden.json"
UPSTREAM_JSON = ROLE_FILES / "source/default-7.2.1.json"
LEGACY_CONFIGS_DIR = ROOT / "configs/subscription-page/v7"
DEFAULTS = ROLE / "defaults/main.yml"
TASKS = ROLE / "tasks/main.yml"
MANAGE_ONE = ROLE / "tasks/manage_one.yml"
BUILD_LEGACY_SCRIPT = ROOT / "scripts/build_vpn_for_friends_subpage_config.py"
BUILD_BRAND_SCRIPT = ROOT / "scripts/build_subpage_config.py"
VALIDATE_SCRIPT = ROOT / "scripts/validate_subpage_config.py"
MAKEFILE = ROOT / "Makefile"

sys.path.insert(0, str(ROLE / "filter_plugins"))
sys.path.insert(0, str(ROOT / "scripts"))
from remnawave_subpage_config import FilterModule  # noqa: E402
from subpage_branding import configs_equal, deep_merge  # noqa: E402


def canonicalize(config: dict) -> dict:
    return FilterModule().canonicalize(config)


class RemnawaveSubpageConfigRoleFilesTest(unittest.TestCase):
    def test_base_and_brand_patches_inside_role_files(self) -> None:
        self.assertTrue(BASE_JSON.is_file())
        self.assertTrue(VFF_PATCH.is_file())
        self.assertTrue(FC_PATCH.is_file())
        self.assertEqual(BASE_JSON.parent, ROLE_FILES)
        self.assertFalse((ROLE_FILES / "vpn-for-friends.json").exists())

    def test_upstream_source_inside_role_files_source(self) -> None:
        self.assertTrue(UPSTREAM_JSON.is_file())
        self.assertEqual(UPSTREAM_JSON.parent, ROLE_FILES / "source")

    def test_legacy_configs_directory_absent(self) -> None:
        self.assertFalse(LEGACY_CONFIGS_DIR.exists())

    def test_defaults_and_tasks_do_not_reference_legacy_configs_path(self) -> None:
        legacy_pattern = re.compile(r"configs/subscription-page/v7")
        for path in (DEFAULTS, TASKS, MANAGE_ONE):
            content = path.read_text(encoding="utf-8")
            self.assertIsNone(
                legacy_pattern.search(content),
                f"{path} still references legacy configs path",
            )

    def test_build_legacy_script_default_source_path(self) -> None:
        content = BUILD_LEGACY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'ROLE_FILES / "source/default-7.2.1.json"',
            content,
        )
        self.assertNotIn("configs/subscription-page/v7", content)

    def test_brand_build_script_defaults(self) -> None:
        content = BUILD_BRAND_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("base.json", content)
        self.assertIn("vpn-for-friends.patch.json", content)
        self.assertIn("friends-connect.patch.json", content)

    def test_validator_default_path_is_base(self) -> None:
        content = VALIDATE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("roles/remnawave_subscription_page_config/files/base.json", content)
        self.assertNotIn("configs/subscription-page/v7", content)

    def test_role_supports_multi_config_and_legacy_fallback(self) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        tasks = TASKS.read_text(encoding="utf-8")
        manage = MANAGE_ONE.read_text(encoding="utf-8")
        self.assertIn("remnawave_subpage_configs:", defaults)
        self.assertIn("build_subpage_config.py", defaults)
        self.assertIn("remnawave_subpage_configs_effective", tasks)
        self.assertIn("manage_one.yml", tasks)
        self.assertIn("remnawave_subpage_config_build_script", manage)
        self.assertIn("method: POST", manage)
        self.assertIn("method: PATCH", manage)

    def test_built_vff_matches_golden_canonical(self) -> None:
        golden = json.loads(GOLDEN_JSON.read_text(encoding="utf-8"))
        built = deep_merge(
            json.loads(BASE_JSON.read_text(encoding="utf-8")),
            json.loads(VFF_PATCH.read_text(encoding="utf-8")),
        )
        self.assertTrue(configs_equal(canonicalize(built), canonicalize(golden)))

        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / "vff.json"
            subprocess.run(
                [
                    sys.executable,
                    str(BUILD_BRAND_SCRIPT),
                    "--brand",
                    "vff",
                    "--output",
                    str(generated),
                ],
                check=True,
                cwd=ROOT,
            )
            from_cli = json.loads(generated.read_text(encoding="utf-8"))
            self.assertTrue(configs_equal(canonicalize(from_cli), canonicalize(golden)))

    def test_makefile_validates_both_brands(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertNotIn("configs/subscription-page/v7", makefile)
        block = makefile.split("sub-next-config-check:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("build_subpage_config.py", block)
        self.assertIn("--brand vff", block)
        self.assertIn("--brand fc", block)


if __name__ == "__main__":
    unittest.main()
