#!/usr/bin/env python3
"""Structural tests for Remnawave 3.2.3 read-only API scope preflight."""

from __future__ import annotations

import re
from pathlib import Path
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles/remnawave_api_preflight"
TASKS = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
CHECK = (ROLE / "tasks/check_one.yml").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
PLAY = (REPO / "playbooks/remnawave_api_preflight.yml").read_text(encoding="utf-8")
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
DOCS = (REPO / "docs/remnawave_upgrade.md").read_text(encoding="utf-8")
UPGRADE_PRE = (REPO / "roles/remnawave_upgrade/tasks/preflight.yml").read_text(encoding="utf-8")
UPGRADE_VER = (REPO / "roles/remnawave_upgrade/tasks/verify.yml").read_text(encoding="utf-8")

REQUIRED_SCOPES = [
    "hosts:*",
    "nodes:*",
    "config-profiles:*",
    "internal-squads:*",
    "external-squads:*",
    "subscription-page-configs:*",
    "system:read",
    "keygen:get",
]

REQUIRED_GETS = [
    "/hosts",
    "/nodes",
    "/config-profiles/inbounds",
    "/internal-squads",
    "/external-squads",
    "/subscription-page-configs",
    "/system/health",
]


class PreflightReadOnlyTests(unittest.TestCase):
    def test_role_and_playbook_are_get_only(self) -> None:
        for src, label in ((TASKS, "main"), (CHECK, "check_one"), (PLAY, "playbook")):
            for method in ("POST", "PATCH", "PUT", "DELETE"):
                self.assertNotRegex(
                    src,
                    rf"method:\s*{method}\b",
                    msg=f"{label} must not use {method}",
                )
        self.assertIn("method: GET", CHECK)

    def test_representative_gets_and_scopes(self) -> None:
        for path in REQUIRED_GETS:
            self.assertIn(path, TASKS)
        for scope in REQUIRED_SCOPES:
            self.assertIn(scope, TASKS)
            self.assertIn(scope, DEFAULTS["rw_api_preflight_required_scopes"])

    def test_401_and_403_are_distinct(self) -> None:
        self.assertIn("401: invalid/expired API token", CHECK)
        self.assertIn(
            "403: token authenticated but required Remnawave 3.2.3 scope is missing",
            CHECK,
        )
        self.assertIn("404: contract/base URL mismatch", CHECK)
        self.assertIn("endpoint-specific preflight failure", CHECK)
        self.assertIn("failed_when: false", CHECK)

    def test_authorization_uses_no_log(self) -> None:
        self.assertIn("Authorization:", CHECK)
        self.assertIn("no_log: true", CHECK)
        self.assertIn("no_log: true", TASKS)
        self.assertNotIn("vault_remnawave_panel_api_token", CHECK)
        self.assertNotIn("Bearer {{ remnawave_panel_api_token }}", TASKS)

    def _check_rows(self) -> list[tuple[str, str, str]]:
        return re.findall(
            r"- path: (/[^\n]+)\n\s+token_var: (\S+)\n\s+scope: (\S+)",
            TASKS,
        )

    def test_subpage_token_default_is_empty_unlike_inherited_tokens(self) -> None:
        self.assertEqual(DEFAULTS["remnawave_subpage_config_api_token"], "")
        self.assertIn(
            "remnawave_panel_api_token",
            DEFAULTS["remnawave_external_squads_api_token"],
        )
        self.assertIn(
            "remnawave_panel_api_token",
            DEFAULTS["remnawave_inbounds_cache_api_token"],
        )

    def test_separate_token_variables(self) -> None:
        self.assertIn("token_var: remnawave_panel_api_token", TASKS)
        self.assertIn("token_var: remnawave_external_squads_api_token", TASKS)
        self.assertIn("token_var: remnawave_subpage_config_api_token", TASKS)
        self.assertIn("token_var: remnawave_inbounds_cache_api_token", TASKS)
        self.assertIn("lookup('vars', item.token_var)", CHECK)
        self.assertIn("token_variable={{ item.token_var }}", CHECK)
        self.assertIn("expected_scope={{ item.scope }}", CHECK)

    def test_external_squads_token_covers_both_gets(self) -> None:
        rows = self._check_rows()
        squad_paths = {path for path, token, _scope in rows if token == "remnawave_external_squads_api_token"}
        self.assertEqual(
            squad_paths,
            {"/external-squads", "/subscription-page-configs"},
        )
        squad_scopes = {
            scope
            for path, token, scope in rows
            if token == "remnawave_external_squads_api_token"
        }
        self.assertEqual(squad_scopes, {"external-squads:*", "subscription-page-configs:*"})
        subpage_only = {
            path
            for path, token, _scope in rows
            if token == "remnawave_subpage_config_api_token"
        }
        self.assertEqual(subpage_only, {"/subscription-page-configs"})

    def test_inbounds_cache_token_checks_config_profiles_inbounds(self) -> None:
        rows = self._check_rows()
        cache = [
            (path, scope)
            for path, token, scope in rows
            if token == "remnawave_inbounds_cache_api_token"
        ]
        self.assertEqual(cache, [("/config-profiles/inbounds", "config-profiles:*")])
        panel_inbounds = [
            (path, token)
            for path, token, _scope in rows
            if path == "/config-profiles/inbounds"
        ]
        self.assertIn(("/config-profiles/inbounds", "remnawave_panel_api_token"), panel_inbounds)
        self.assertIn(
            ("/config-profiles/inbounds", "remnawave_inbounds_cache_api_token"),
            panel_inbounds,
        )

    def test_failure_names_endpoint_token_var_and_scope(self) -> None:
        self.assertIn("endpoint=GET {{ item.path }}", CHECK)
        self.assertIn("token_variable={{ item.token_var }}", CHECK)
        self.assertIn("expected_scope={{ item.scope }}", CHECK)

    def test_checklist_is_required_and_explains_write_gap(self) -> None:
        self.assertIn("REQUIRED MANUAL CHECKLIST", TASKS)
        self.assertIn("does NOT prove write", TASKS)
        self.assertIn("resource:*", TASKS)
        self.assertIn("physical_token_union", TASKS)
        for scope in REQUIRED_SCOPES:
            self.assertIn(scope, DOCS)
        for token_var in (
            "remnawave_panel_api_token",
            "remnawave_inbounds_cache_api_token",
            "remnawave_external_squads_api_token",
            "remnawave_subpage_config_api_token",
        ):
            self.assertIn(token_var, DOCS)
            self.assertIn(token_var, TASKS)
        self.assertIn("объединение scopes", DOCS)

    def test_make_target_calls_playbook(self) -> None:
        self.assertIn("PLAY_API_PREFLIGHT ?= playbooks/remnawave_api_preflight.yml", MAKEFILE)
        self.assertIn("remnawave-api-preflight:", MAKEFILE)
        self.assertIn("$(PLAY_API_PREFLIGHT)", MAKEFILE)
        self.assertIn("role: remnawave_api_preflight", PLAY)
        self.assertIn("hosts: panel", PLAY)

    def test_upgrade_preflight_is_not_scope_preflight(self) -> None:
        self.assertIn("cannot prove Remnawave 3.2.3 API scopes", UPGRADE_PRE)
        self.assertIn("make remnawave-api-preflight", UPGRADE_PRE)
        self.assertIn("NOT the 3.2.3 token-scope preflight", UPGRADE_VER)
        self.assertIn("DO NOT run new vff-remnawave-auto mutations", DOCS)
        self.assertIn("make remnawave-api-preflight", DOCS)

    def test_keygen_scope_is_checklist_only_never_probed(self) -> None:
        self.assertIn("keygen:get", DEFAULTS["rw_api_preflight_required_scopes"])
        self.assertIn("keygen:get", TASKS)
        self.assertIn("GET /api/keygen intentionally is NOT probed", TASKS)
        self.assertIn("generates a new node certificate / SECRET_KEY", TASKS)
        self.assertIn("must be verified manually", TASKS)
        rows = self._check_rows()
        probed_paths = [path for path, _token, _scope in rows]
        self.assertNotIn("/keygen", probed_paths)
        self.assertNotIn("/api/keygen", probed_paths)
        self.assertNotRegex(TASKS, r"path:\s*/(?:api/)?keygen\b")
        self.assertTrue(all("keygen" not in path for path in probed_paths))

    def test_delegate_localhost_run_once(self) -> None:
        self.assertIn("delegate_to: localhost", TASKS)
        self.assertIn("run_once: true", TASKS)
        self.assertIn("delegate_to: localhost", CHECK)


if __name__ == "__main__":
    unittest.main()
