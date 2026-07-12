#!/usr/bin/env python3
"""Tests for production subscription upstream Ansible filters."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "roles/remnawave_subscription_page/filter_plugins"
    ),
)

from remnawave_subscription_upstream import (  # noqa: E402
    FilterModule,
    _cutover_plan,
    _detect_vhost_upstream,
    _resolve_preserve_target,
)


LEGACY_MARKER = "server 127.0.0.1:3010;"
NEXT_MARKER = "server 127.0.0.1:3011;"
REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_TEMPLATE = REPO_ROOT / "roles/remnawave_subscription_page/templates/nginx-subscription.conf.j2"
PLAY_SUBSCRIPTION = REPO_ROOT / "playbooks/subscription.yml"


class RemnawaveSubscriptionUpstreamFiltersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.filters = FilterModule()
        self.state = self.filters.vhost_upstream_state
        self.effective = self.filters.effective_upstream
        self.plan = self.filters.cutover_plan
        self.preserve = self.filters.resolve_preserve_target
        self.template = NGINX_TEMPLATE.read_text(encoding="utf-8")
        self.play_subscription = PLAY_SUBSCRIPTION.read_text(encoding="utf-8")

    def test_legacy_vhost_state(self) -> None:
        content = f"upstream remnawave-subscription-page {{\n    {LEGACY_MARKER}\n}}\n"
        result = self.state(content, LEGACY_MARKER, NEXT_MARKER)
        self.assertTrue(result["current_is_legacy"])
        self.assertFalse(result["current_is_next"])
        self.assertTrue(result["known"])

    def test_next_vhost_state(self) -> None:
        content = f"upstream remnawave-subscription-page {{\n    {NEXT_MARKER}\n}}\n"
        result = self.state(content, LEGACY_MARKER, NEXT_MARKER)
        self.assertFalse(result["current_is_legacy"])
        self.assertTrue(result["current_is_next"])
        self.assertTrue(result["known"])

    def test_unknown_vhost_state(self) -> None:
        content = "upstream remnawave-subscription-page { server 127.0.0.1:9999; }\n"
        result = self.state(content, LEGACY_MARKER, NEXT_MARKER)
        self.assertFalse(result["current_is_legacy"])
        self.assertFalse(result["current_is_next"])
        self.assertFalse(result["known"])

    def test_ambiguous_vhost_state(self) -> None:
        content = f"{LEGACY_MARKER}\n{NEXT_MARKER}\n"
        result = self.state(content, LEGACY_MARKER, NEXT_MARKER)
        self.assertFalse(result["current_is_legacy"])
        self.assertFalse(result["current_is_next"])
        self.assertFalse(result["known"])

    def test_effective_upstream_legacy_selector(self) -> None:
        result = self.effective("legacy", "127.0.0.1", 3010, "http", "127.0.0.1", 3011, "http")
        self.assertEqual(result["target"], "legacy")
        self.assertEqual(result["port"], 3010)

    def test_effective_upstream_next_selector(self) -> None:
        result = self.effective("next", "127.0.0.1", 3010, "http", "127.0.0.1", 3011, "http")
        self.assertEqual(result["target"], "next")
        self.assertEqual(result["port"], 3011)

    def test_effective_upstream_invalid_selector(self) -> None:
        with self.assertRaises(ValueError):
            self.effective("invalid", "127.0.0.1", 3010, "http", "127.0.0.1", 3011, "http")
        with self.assertRaises(ValueError):
            self.effective("preserve", "127.0.0.1", 3010, "http", "127.0.0.1", 3011, "http")

    def test_preserve_existing_legacy_resolves_to_legacy(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"upstream x {{\n    {LEGACY_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        self.assertEqual(self.preserve(upstream_state, True), "legacy")
        effective = self.effective(self.preserve(upstream_state, True), "127.0.0.1", 3010, "http", "127.0.0.1", 3011, "http")
        self.assertEqual(effective["port"], 3010)

    def test_preserve_existing_next_resolves_to_next(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"upstream x {{\n    {NEXT_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        self.assertEqual(self.preserve(upstream_state, True), "next")
        effective = self.effective(self.preserve(upstream_state, True), "127.0.0.1", 3010, "http", "127.0.0.1", 3011, "http")
        self.assertEqual(effective["port"], 3011)

    def test_preserve_missing_vhost_bootstraps_legacy(self) -> None:
        self.assertEqual(_resolve_preserve_target({}, False), "legacy")
        unknown_state = _detect_vhost_upstream("upstream x { server 127.0.0.1:9999; }\n", LEGACY_MARKER, NEXT_MARKER)
        self.assertEqual(self.preserve(unknown_state, False), "legacy")

    def test_preserve_unknown_existing_vhost_fails(self) -> None:
        upstream_state = _detect_vhost_upstream(
            "upstream x { server 127.0.0.1:9999; }\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        with self.assertRaisesRegex(ValueError, "unknown or ambiguous upstream"):
            self.preserve(upstream_state, True)

    def test_preserve_ambiguous_existing_vhost_fails(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"{LEGACY_MARKER}\n{NEXT_MARKER}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        with self.assertRaisesRegex(ValueError, "unknown or ambiguous upstream"):
            self.preserve(upstream_state, True)

    def test_template_header_uses_effective_target(self) -> None:
        self.assertIn(
            'add_header X-VFF-Subscription-Target "{{ remnawave_subscription_effective_upstream_target }}" always;',
            self.template,
        )
        self.assertNotIn('add_header X-VFF-Subscription-Target "{{ remnawave_subscription_upstream_target }}" always;', self.template)

    def test_subscription_playbook_does_not_force_legacy_or_next(self) -> None:
        deploy_play = self.play_subscription.split(
            "- name: Manage Subscription Page staging and production target",
            maxsplit=1,
        )[0]
        self.assertNotIn("remnawave_subscription_upstream_target:", deploy_play)

    def test_cutover_playbook_sets_next(self) -> None:
        self.assertIn("remnawave_subscription_upstream_target: next", self.play_subscription)

    def test_rollback_playbook_sets_legacy(self) -> None:
        self.assertIn("remnawave_subscription_upstream_target: legacy", self.play_subscription)

    def test_stable_backup_allowed_only_for_legacy_content(self) -> None:
        legacy = self.state(
            f"upstream x {{\n    {LEGACY_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        nxt = self.state(
            f"upstream x {{\n    {NEXT_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        self.assertTrue(legacy["current_is_legacy"])
        self.assertTrue(nxt["current_is_next"])
        self.assertFalse(nxt["current_is_legacy"])

    def test_plan_legacy_without_stable_backup(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"upstream x {{\n    {LEGACY_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        plan = _cutover_plan(upstream_state, False, False, True)
        self.assertEqual(plan["current_target"], "legacy")
        self.assertTrue(plan["cutover_needed"])
        self.assertTrue(plan["stable_legacy_backup_would_be_created"])
        self.assertTrue(plan["timestamp_backup_would_be_created"])
        self.assertTrue(plan["nginx_reload_would_be_required"])
        self.assertTrue(plan["production_healthcheck_would_run"])

    def test_plan_legacy_with_stable_backup(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"upstream x {{\n    {LEGACY_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        plan = _cutover_plan(upstream_state, False, True, True)
        self.assertTrue(plan["cutover_needed"])
        self.assertFalse(plan["stable_legacy_backup_would_be_created"])
        self.assertTrue(plan["timestamp_backup_would_be_created"])
        self.assertTrue(plan["nginx_reload_would_be_required"])

    def test_plan_next_with_stable_backup(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"upstream x {{\n    {NEXT_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        plan = _cutover_plan(upstream_state, True, True, True)
        self.assertEqual(plan["current_target"], "next")
        self.assertFalse(plan["cutover_needed"])
        self.assertFalse(plan["stable_legacy_backup_would_be_created"])
        self.assertFalse(plan["timestamp_backup_would_be_created"])
        self.assertFalse(plan["nginx_reload_would_be_required"])
        self.assertTrue(plan["production_healthcheck_would_run"])

    def test_plan_next_without_stable_backup_is_unsafe_for_backup_creation(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"upstream x {{\n    {NEXT_MARKER}\n}}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        plan = _cutover_plan(upstream_state, True, False, True)
        self.assertFalse(plan["cutover_needed"])
        self.assertFalse(plan["stable_legacy_backup_would_be_created"])

    def test_plan_unknown_state(self) -> None:
        upstream_state = _detect_vhost_upstream(
            "upstream x { server 127.0.0.1:9999; }\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        plan = _cutover_plan(upstream_state, False, False, True)
        self.assertEqual(plan["current_target"], "unknown")
        self.assertTrue(plan["cutover_needed"])
        self.assertFalse(plan["stable_legacy_backup_would_be_created"])

    def test_plan_ambiguous_state(self) -> None:
        upstream_state = _detect_vhost_upstream(
            f"{LEGACY_MARKER}\n{NEXT_MARKER}\n",
            LEGACY_MARKER,
            NEXT_MARKER,
        )
        plan = _cutover_plan(upstream_state, False, False, True)
        self.assertEqual(plan["current_target"], "ambiguous")
        self.assertFalse(plan["stable_legacy_backup_would_be_created"])


if __name__ == "__main__":
    unittest.main()
