#!/usr/bin/env python3
"""Static checks for production subscription cutover/rollback HTTPS health tasks."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CUTOVER_TASKS = REPO_ROOT / "roles/remnawave_subscription_page/tasks/cutover.yml"
ROLLBACK_TASKS = REPO_ROOT / "roles/remnawave_subscription_page/tasks/rollback.yml"
NGINX_TEMPLATE = REPO_ROOT / "roles/remnawave_subscription_page/templates/nginx-subscription.conf.j2"
FILTER_PLUGIN = REPO_ROOT / "roles/remnawave_subscription_page/filter_plugins"

sys.path.insert(0, str(FILTER_PLUGIN))
from remnawave_subscription_upstream import (  # noqa: E402
    _uri_health_diagnostics,
    _uri_transport_error_category,
)

PUBLIC_URI_TASK_NAMES = (
    "Preflight new subscription page public HTTPS from controller",
    "Preflight production subscription public HTTPS TLS from controller",
    "Verify production HTTPS subscription page after cutover",
    "Verify production HTTPS subscription page when cutover already applied",
    "Verify production HTTPS subscription page after rollback",
)

SANITIZED_DIAG_KEYS = (
    "stage",
    "execution_node",
    "http_status",
    "content_type",
    "content_length",
    "contains_branding",
    "expected_target",
    "reported_target",
    "target_matches",
    "transport_error",
    "error_category",
)


def _split_tasks(content: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^[ \t]*- name:", content)
    tasks: list[tuple[str, str]] = []
    for part in parts[1:]:
        name, _, body = part.partition("\n")
        tasks.append((name.strip(), body))
    return tasks


def _task_by_name(content: str, name: str) -> str:
    matches = [(task_name, body) for task_name, body in _split_tasks(content) if task_name == name]
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one task named {name!r}, found {len(matches)}")
    return matches[0][1]


def _task_blocks(content: str) -> list[str]:
    return [body for _, body in _split_tasks(content)]


class RemnawaveSubscriptionCutoverHealthchecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cutover = CUTOVER_TASKS.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK_TASKS.read_text(encoding="utf-8")
        cls.template = NGINX_TEMPLATE.read_text(encoding="utf-8")

    def test_production_template_adds_subscription_target_header(self) -> None:
        self.assertIn(
            'add_header X-VFF-Subscription-Target "{{ remnawave_subscription_effective_upstream_target }}" always;',
            self.template,
        )
        header_block = self.template.split("add_header X-VFF-Subscription-Target", maxsplit=1)[1][:200]
        self.assertNotIn("remnawave_subscription_upstream_target", header_block)

    def test_production_template_header_uses_always(self) -> None:
        self.assertIn("X-VFF-Subscription-Target", self.template)
        self.assertRegex(self.template, r'add_header X-VFF-Subscription-Target .* always;')

    def test_cutover_health_check_does_not_require_onexray(self) -> None:
        for task_name in (
            "Verify production HTTPS subscription page after cutover",
            "Verify production HTTPS subscription page when cutover already applied",
        ):
            body = _task_by_name(self.cutover, task_name)
            self.assertNotIn("OneXray", body, task_name)

    def test_cutover_health_check_requires_target_next_header(self) -> None:
        for task_name in (
            "Verify production HTTPS subscription page after cutover",
            "Verify production HTTPS subscription page when cutover already applied",
        ):
            body = _task_by_name(self.cutover, task_name)
            self.assertIn("x_vff_subscription_target", body, task_name)
            self.assertIn("== 'next'", body, task_name)

    def test_public_next_preflight_does_not_require_onexray(self) -> None:
        body = _task_by_name(
            self.cutover,
            "Preflight new subscription page public HTTPS from controller",
        )
        self.assertNotIn("OneXray", body)

    def test_public_next_preflight_requires_branding(self) -> None:
        body = _task_by_name(
            self.cutover,
            "Preflight new subscription page public HTTPS from controller",
        )
        self.assertIn("VPN for friends", body)
        self.assertIn("delegate_to: localhost", body)

    def test_explicit_rollback_renders_legacy_template(self) -> None:
        self.assertIn("Render production subscription vhost with legacy upstream", self.rollback)
        self.assertIn("render_production_subscription_vhost.yml", self.rollback)
        self.assertNotIn("Restore production subscription vhost from stable legacy backup", self.rollback)

    def test_rollback_marker_check_requires_legacy_upstream(self) -> None:
        body = _task_by_name(
            self.rollback,
            "Assert production subscription vhost contains legacy upstream marker after rollback",
        )
        self.assertIn("remnawave_subscription_legacy_upstream_marker", body)
        self.assertIn("remnawave_subscription_next_upstream_marker not in", body)

    def test_rollback_public_health_check_requires_target_legacy(self) -> None:
        body = _task_by_name(
            self.rollback,
            "Verify production HTTPS subscription page after rollback",
        )
        self.assertIn("x_vff_subscription_target", body)
        self.assertIn("== 'legacy'", body)
        self.assertIn("delegate_to: localhost", body)

    def test_public_uri_tasks_use_proxy_and_cert_validation(self) -> None:
        for task_name in PUBLIC_URI_TASK_NAMES:
            content = self.cutover if task_name != PUBLIC_URI_TASK_NAMES[-1] else self.rollback
            body = _task_by_name(content, task_name)
            self.assertIn("use_proxy: false", body, task_name)
            self.assertIn("validate_certs: true", body, task_name)

    def test_body_checks_use_return_content_true(self) -> None:
        for task_name in (
            "Preflight new subscription page public HTTPS from controller",
            "Verify production HTTPS subscription page after cutover",
            "Verify production HTTPS subscription page when cutover already applied",
        ):
            body = _task_by_name(self.cutover, task_name)
            self.assertIn("return_content: true", body, task_name)

    def test_diagnostics_negative_status_is_transport_error(self) -> None:
        diag = _uri_health_diagnostics({"status": -1, "msg": "Connection failure"})
        self.assertTrue(diag["transport_error"])
        self.assertEqual(diag["http_status"], -1)
        self.assertNotEqual(diag["error_category"], "http")

    def test_diagnostics_missing_status_is_transport_error(self) -> None:
        diag = _uri_health_diagnostics({"msg": "Connection refused", "failed": True})
        self.assertTrue(diag["transport_error"])
        self.assertIsNone(diag["http_status"])
        self.assertNotEqual(diag.get("error_category"), "http")

    def test_diagnostics_http_error_status(self) -> None:
        diag = _uri_health_diagnostics({"status": 502, "content": "", "content_type": "text/html"})
        self.assertFalse(diag["transport_error"])
        self.assertEqual(diag["http_status"], 502)
        self.assertEqual(diag["error_category"], "http")

    def test_diagnostics_success_has_no_error_category(self) -> None:
        diag = _uri_health_diagnostics({"status": 200, "content": "VPN for friends"})
        self.assertFalse(diag["transport_error"])
        self.assertEqual(diag["http_status"], 200)
        self.assertIsNone(diag["error_category"])

    def test_cutover_and_rollback_do_not_use_subscription_domain(self) -> None:
        self.assertNotIn("remnawave_subscription_domain", self.cutover)
        self.assertNotIn("remnawave_subscription_domain", self.rollback)

    def test_production_uri_tasks_use_sub_public_domain(self) -> None:
        for task_name in (
            "Verify production HTTPS subscription page after cutover",
            "Verify production HTTPS subscription page when cutover already applied",
            "Verify production HTTPS subscription page after rollback",
        ):
            content = self.cutover if task_name != "Verify production HTTPS subscription page after rollback" else self.rollback
            body = _task_by_name(content, task_name)
            self.assertIn("remnawave_sub_public_domain", body, task_name)
            self.assertNotIn("remnawave_subscription_domain", body, task_name)
            self.assertNotIn("remnawave_subscription_next_public_domain", body, task_name)

    def test_sub_next_preflight_uses_next_public_domain(self) -> None:
        body = _task_by_name(
            self.cutover,
            "Preflight new subscription page public HTTPS from controller",
        )
        self.assertIn("remnawave_subscription_next_public_domain", body)
        self.assertNotIn("remnawave_sub_public_domain", body.split("url:", maxsplit=1)[1].split("method:", maxsplit=1)[0])

    def test_diagnostics_preserve_actual_non_200_status(self) -> None:
        diag = _uri_health_diagnostics({"status": 502, "content": "", "content_type": "text/html"}, expected_target="next")
        self.assertEqual(diag["http_status"], 502)
        self.assertEqual(diag["error_category"], "http")
        self.assertFalse(diag["transport_error"])

    def test_diagnostics_include_target_fields(self) -> None:
        diag = _uri_health_diagnostics(
            {
                "status": 200,
                "content": "VPN for friends",
                "content_type": "text/html",
                "x_vff_subscription_target": "next",
            },
            expected_target="next",
        )
        self.assertNotIn("contains_onexray", diag)
        self.assertEqual(diag["expected_target"], "next")
        self.assertEqual(diag["reported_target"], "next")
        self.assertTrue(diag["target_matches"])
        self.assertTrue(diag["contains_branding"])

    def test_diagnostics_classify_transport_errors_without_raw_msg(self) -> None:
        self.assertEqual(_uri_transport_error_category("Failed to resolve host name"), "dns")
        diag = _uri_health_diagnostics({"msg": "Connection refused", "failed": True})
        self.assertIsNone(diag["http_status"])
        self.assertTrue(diag["transport_error"])
        self.assertEqual(diag["error_category"], "connection")
        self.assertNotIn("msg", diag)

    def test_sanitized_diagnostics_present_and_safe(self) -> None:
        rescue_part = self.cutover.split("  rescue:", maxsplit=1)[1]
        self.assertIn("remnawave_subscription_uri_health_diagnostics", rescue_part)
        for key in SANITIZED_DIAG_KEYS:
            self.assertIn(key, str(_uri_health_diagnostics({"status": 200, "content": ""}, expected_target="next")))

        debug_part = rescue_part.split(
            "Report sanitized production cutover health check diagnostics",
            maxsplit=1,
        )[1]
        debug_block = debug_part.split("- name:", maxsplit=1)[0]
        self.assertIn("remnawave_subscription_cutover_health_diagnostics", debug_block)
        self.assertNotIn("_sub_cutover_prod_health.content", debug_block)
        self.assertNotIn(".msg", debug_block)
        self.assertNotIn("contains_onexray", debug_block)

    def test_no_localhost_4443_health_check(self) -> None:
        combined = self.cutover + self.rollback
        self.assertNotIn("127.0.0.1:4443", combined)
        self.assertNotIn("localhost:4443", combined)

    def test_rescue_still_restores_timestamp_backup(self) -> None:
        rescue_part = self.cutover.split("  rescue:", maxsplit=1)[1]
        diagnostic_pos = rescue_part.index("Build sanitized production cutover health check diagnostics")
        restore_pos = rescue_part.index("Restore production subscription vhost from timestamp backup")
        self.assertLess(diagnostic_pos, restore_pos)
        self.assertIn("_sub_cutover_timestamp_backup.dest", rescue_part)

    def test_production_tls_preflight_before_cutover_mutation(self) -> None:
        preflight_pos = self.cutover.index(
            "Preflight production subscription public HTTPS TLS from controller",
        )
        mutation_pos = self.cutover.index("Perform production subscription page cutover")
        self.assertLess(preflight_pos, mutation_pos)
        preflight_block = self.cutover.split(
            "Validate public production subscription TLS from controller before cutover mutation",
            maxsplit=1,
        )[1].split("Validate production subscription TLS before cutover mutation", maxsplit=1)[0]
        self.assertIn("validate_certs: true", preflight_block)
        self.assertIn("use_proxy: false", preflight_block)
        self.assertIn("status_code: 200", preflight_block)
        self.assertNotIn("x_vff_subscription_target", preflight_block.lower())


if __name__ == "__main__":
    unittest.main()
