#!/usr/bin/env python3
"""Tests for Subscription Page v7 declarative config file layout."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/remnawave_subscription_page_config"
ROLE_FILES = ROLE / "files"
DESIRED_JSON = ROLE_FILES / "vpn-for-friends.json"
UPSTREAM_JSON = ROLE_FILES / "source/default-7.2.1.json"
LEGACY_CONFIGS_DIR = ROOT / "configs/subscription-page/v7"
DEFAULTS = ROLE / "defaults/main.yml"
TASKS = ROLE / "tasks/main.yml"
BUILD_SCRIPT = ROOT / "scripts/build_vpn_for_friends_subpage_config.py"
VALIDATE_SCRIPT = ROOT / "scripts/validate_subpage_config.py"
MAKEFILE = ROOT / "Makefile"

sys.path.insert(0, str(ROLE / "filter_plugins"))
from remnawave_subpage_config import FilterModule  # noqa: E402


def canonicalize(config: dict) -> dict:
    return FilterModule().canonicalize(config)


class RemnawaveSubpageConfigRoleFilesTest(unittest.TestCase):
    def test_desired_json_inside_role_files(self) -> None:
        self.assertTrue(DESIRED_JSON.is_file())
        self.assertEqual(DESIRED_JSON.parent, ROLE_FILES)

    def test_upstream_source_inside_role_files_source(self) -> None:
        self.assertTrue(UPSTREAM_JSON.is_file())
        self.assertEqual(UPSTREAM_JSON.parent, ROLE_FILES / "source")

    def test_legacy_configs_directory_absent(self) -> None:
        self.assertFalse(LEGACY_CONFIGS_DIR.exists())

    def test_defaults_and_tasks_do_not_reference_legacy_configs_path(self) -> None:
        legacy_pattern = re.compile(r"configs/subscription-page/v7")
        for path in (DEFAULTS, TASKS):
            content = path.read_text(encoding="utf-8")
            self.assertIsNone(
                legacy_pattern.search(content),
                f"{path} still references legacy configs path",
            )

    def test_build_script_default_source_path(self) -> None:
        content = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'ROLE_FILES / "source/default-7.2.1.json"',
            content,
        )
        self.assertNotIn("configs/subscription-page/v7", content)

    def test_build_script_default_output_path(self) -> None:
        content = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'ROLE_FILES / "vpn-for-friends.json"',
            content,
        )
        self.assertIn("DEFAULT_OUTPUT = ROLE_FILES", content)

    def test_validator_default_path(self) -> None:
        content = VALIDATE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("roles/remnawave_subscription_page_config/files/vpn-for-friends.json", content)
        self.assertNotIn("configs/subscription-page/v7", content)

    def test_role_allows_external_override_config_path(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")
        self.assertIn("remnawave_subpage_config_source_file | trim", tasks)
        self.assertIn("remnawave_subpage_config_source_file | default('') | trim | length > 0", tasks)
        self.assertNotIn(
            "remnawave_subpage_config_source_file: >-",
            tasks,
            "input variable must not be overwritten by set_fact",
        )

        defaults = DEFAULTS.read_text(encoding="utf-8")
        self.assertIn('remnawave_subpage_config_source_file: ""', defaults)

    def test_effective_variable_computed_via_role_path(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")
        self.assertIn("remnawave_subpage_config_effective_source_file", tasks)
        self.assertIn("role_path ~ '/files/vpn-for-friends.json'", tasks)
        self.assertIn("Resolve subscription page config effective source file path", tasks)

    def test_external_override_used_in_effective_variable(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")
        self.assertRegex(
            tasks,
            r"remnawave_subpage_config_effective_source_file: >-\s*\n\s*\{\{",
        )
        self.assertIn("remnawave_subpage_config_source_file | trim", tasks)
        self.assertIn("lookup('file', remnawave_subpage_config_effective_source_file)", tasks)
        self.assertNotIn("lookup('file', remnawave_subpage_config_source_file)", tasks)

    def test_runtime_tasks_use_effective_source_file_path(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")
        path_usages = re.findall(
            r"path: \"\{\{ (remnawave_subpage_config_[^}]+) \}\}\"",
            tasks,
        )
        self.assertIn("remnawave_subpage_config_effective_source_file", path_usages)
        self.assertNotIn("remnawave_subpage_config_source_file", path_usages)

    def test_moved_json_content_unchanged_semantically_via_build(self) -> None:
        desired = json.loads(DESIRED_JSON.read_text(encoding="utf-8"))
        desired_canonical = canonicalize(desired)

        with self.subTest("upstream source readable"):
            upstream = json.loads(UPSTREAM_JSON.read_text(encoding="utf-8"))
            self.assertIn("platforms", upstream)

        with self.subTest("build output matches desired canonical JSON"):
            generated = Path("/tmp/vpn-for-friends.generated.json")
            subprocess.run(
                [
                    sys.executable,
                    str(BUILD_SCRIPT),
                    "--output",
                    str(generated),
                ],
                check=True,
                cwd=ROOT,
            )
            built = json.loads(generated.read_text(encoding="utf-8"))
            self.assertEqual(canonicalize(built), desired_canonical)

    def test_makefile_uses_role_files_path(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertNotIn("configs/subscription-page/v7", makefile)
        block = makefile.split("sub-next-config-check:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("validate_subpage_config.py", block)
        self.assertNotIn("configs/subscription-page", block)


if __name__ == "__main__":
    unittest.main()
