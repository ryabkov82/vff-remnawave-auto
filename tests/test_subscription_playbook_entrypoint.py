#!/usr/bin/env python3
"""Structural checks for consolidated Subscription Page playbook entry point."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS_DIR = REPO_ROOT / "playbooks"
PLAY_SUB = PLAYBOOKS_DIR / "subscription.yml"
MAKEFILE = REPO_ROOT / "Makefile"

REMOVED_PLAYBOOKS = (
    "subscription-next.yml",
    "subscription-next-nginx.yml",
    "subscription-next-config.yml",
    "subscription-cutover.yml",
    "subscription-rollback.yml",
)

RUNTIME_TASK_FILES = (
    REPO_ROOT / "roles/remnawave_subscription_page/tasks/cutover.yml",
    REPO_ROOT / "roles/remnawave_subscription_page/tasks/rollback.yml",
    REPO_ROOT / "roles/remnawave_subscription_page/tasks/validate_production_subscription_tls.yml",
)

INLINED_CUTOVER_MARKERS = (
    "Perform production subscription page cutover",
    "Preflight production subscription public HTTPS TLS from controller",
    "Build sanitized production rollback health check diagnostics",
)

SUBSCRIPTION_MAKE_TARGETS = (
    ("sub:", "PLAY_SUB)"),
    ("sub-next:", "PLAY_SUB)"),
    ("sub-next-check:", "PLAY_SUB)"),
    ("sub-next-nginx:", "PLAY_SUB)"),
    ("sub-next-nginx-check:", "PLAY_SUB)"),
    ("sub-portalbase:", "PLAY_SUB)"),
    ("sub-portalbase-check:", "PLAY_SUB)"),
    ("sub-next-config-plan:", "PLAY_SUB)"),
    ("sub-next-config-apply:", "PLAY_SUB)"),
    ("sub-cutover:", "PLAY_SUB)"),
    ("sub-cutover-check:", "PLAY_SUB)"),
    ("sub-rollback:", "PLAY_SUB)"),
    ("sub-rollback-check:", "PLAY_SUB)"),
    ("subpage-config:", "PLAY_SUB)"),
)

TARGET_TAG_EXPECTATIONS = (
    ("sub-next:", "--tags sub_next"),
    ("sub-next-nginx:", "--tags sub_next_nginx"),
    ("sub-portalbase:", "--tags sub_portalbase"),
    ("sub-next-config-plan:", "--tags sub_next_config"),
    ("sub-next-config-apply:", "--tags sub_next_config"),
    ("sub-next-full:", "--tags sub_next_full"),
    ("sub-cutover:", "--tags sub_cutover"),
    ("sub-rollback:", "--tags sub_rollback"),
    ("subpage-config:", "--tags sub_config"),
)

SPECIAL_INCLUDE_OPERATIONS = (
    {
        "marker": "Apply subscription app-config (config-only include)",
        "wrapper_tags": {"never", "sub_config"},
        "apply_tags": {"sub_config"},
    },
    {
        "marker": "Configure production subscription Nginx vhost only",
        "wrapper_tags": {"never", "nginx"},
        "apply_tags": {"nginx"},
        "tasks_from": "nginx.yml",
        "role": "remnawave_subscription_page",
    },
    {
        "marker": "Deploy subscription-next container",
        "wrapper_tags": {"never", "sub_next", "sub_next_full"},
        "apply_tags": {"sub_next", "sub_next_full"},
    },
    {
        "marker": "Deploy subscription-next Nginx reverse proxy",
        "wrapper_tags": {"never", "sub_next_nginx", "sub_next_full"},
        "apply_tags": {"sub_next_nginx", "sub_next_full"},
        "forbidden_wrapper_tags": {"nginx", "subpage_next", "subpage_config", "cutover", "rollback"},
    },
    {
        "marker": "Deploy subscription portalbase Nginx reverse proxy",
        "wrapper_tags": {"never", "sub_portalbase"},
        "apply_tags": {"sub_portalbase"},
        "tasks_from": "nginx_portalbase",
        "role": "remnawave_subscription_page_next",
        "forbidden_wrapper_tags": {
            "nginx",
            "sub_next_nginx",
            "sub_next_full",
            "sub_cutover",
            "sub_rollback",
        },
    },
    {
        "marker": "Manage subscription page config via Remnawave API",
        "wrapper_tags": {"never", "sub_next_config", "sub_next_full"},
        "apply_tags": {"sub_next_config", "sub_next_full"},
    },
    {
        "marker": "Cutover production subscription page upstream",
        "wrapper_tags": {"never", "sub_cutover"},
        "apply_tags": {"sub_cutover"},
    },
    {
        "marker": "Rollback production subscription page upstream",
        "wrapper_tags": {"never", "sub_rollback"},
        "apply_tags": {"sub_rollback"},
    },
)

RUNTIME_TASK_FILES = (
    REPO_ROOT / "roles/remnawave_subscription_page/tasks/cutover.yml",
    REPO_ROOT / "roles/remnawave_subscription_page/tasks/rollback.yml",
)

LEGACY_WRAPPER_TAGS = ("subpage_next", "subpage_config", "cutover", "rollback")


STAGING_PLAY_MARKERS = (
    "Deploy subscription-next container",
    "Deploy subscription-next Nginx reverse proxy",
    "Deploy subscription portalbase Nginx reverse proxy",
    "Manage subscription page config via Remnawave API",
    "Cutover production subscription page upstream",
    "Rollback production subscription page upstream",
)


def _play_blocks(content: str) -> list[str]:
    return re.split(r"(?m)^- name:", content)[1:]


def _staging_play(content: str) -> str:
    return "- name:" + content.split(
        "- name: Manage Subscription Page staging and production target",
        maxsplit=1,
    )[1]


def _task_block(content: str, marker: str) -> str:
    start = content.index(f"- name: {marker}")
    tail = content[start + 1 :]
    match = re.search(r"\n    - name: ", tail)
    end = start + 1 + match.start() if match else len(content)
    return content[start:end]


def _apply_tags(block: str) -> set[str]:
    after_apply = block.split("apply:", maxsplit=1)[1]
    apply_only = after_apply.split("\n      tags:", maxsplit=1)[0]
    return set(re.findall(r"-\s+(\w+)", apply_only))


def _wrapper_tags(block: str) -> set[str]:
    wrapper_part = block.rsplit("\n      tags:", maxsplit=1)[1]
    wrapper_only = wrapper_part.split("\n      vars:", maxsplit=1)[0]
    return set(re.findall(r"-\s+(\w+)", wrapper_only))


class SubscriptionPlaybookEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.play_sub = PLAY_SUB.read_text(encoding="utf-8")
        cls.makefile = MAKEFILE.read_text(encoding="utf-8")

    def test_runtime_task_files_exist_outside_playbook(self) -> None:
        for path in RUNTIME_TASK_FILES:
            self.assertTrue(path.is_file(), str(path))

    def test_playbook_does_not_inline_cutover_rollback_runtime_tasks(self) -> None:
        for marker in INLINED_CUTOVER_MARKERS:
            self.assertNotIn(marker, self.play_sub, marker)

    def test_only_one_subscription_playbook_exists(self) -> None:
        playbooks = sorted(
            path.name for path in PLAYBOOKS_DIR.glob("subscription*.yml")
        )
        self.assertEqual(playbooks, ["subscription.yml"])

    def test_removed_playbooks_are_absent(self) -> None:
        for name in REMOVED_PLAYBOOKS:
            self.assertFalse((PLAYBOOKS_DIR / name).exists(), name)

    def test_play_sub_points_to_subscription_yml(self) -> None:
        self.assertIn("PLAY_SUB ?= playbooks/subscription.yml", self.makefile)

    def test_no_extra_play_sub_variables(self) -> None:
        extra_vars = re.findall(r"^PLAY_SUB_[A-Z0-9_]+", self.makefile, re.M)
        self.assertEqual(extra_vars, [])
        self.assertIn("PLAY_SUB ?= playbooks/subscription.yml", self.makefile)

    def test_subscription_make_targets_use_play_sub(self) -> None:
        for target_marker, playbook_var in SUBSCRIPTION_MAKE_TARGETS:
            block = self.makefile.split(target_marker, maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
            self.assertIn(playbook_var, block, target_marker)

    def test_special_targets_pass_operational_tags(self) -> None:
        for target_marker, tag_flag in TARGET_TAG_EXPECTATIONS:
            block = self.makefile.split(target_marker, maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
            self.assertIn(tag_flag, block, target_marker)

    def test_deploy_role_remains_in_subscription_playbook(self) -> None:
        self.assertIn("remnawave_subscription_deploy", self.play_sub)
        self.assertIn("tags: [subpage]", self.play_sub)

    def test_cutover_uses_include_role_with_next_target(self) -> None:
        self.assertIn("tasks_from: cutover", self.play_sub)
        self.assertIn("remnawave_subscription_upstream_target: next", self.play_sub)
        self.assertIn("include_role:", self.play_sub)
        cutover_block = self.play_sub.split("Cutover production subscription page upstream", 1)[1][:400]
        self.assertNotIn("import_role:", cutover_block)

    def test_rollback_uses_include_role_with_legacy_target(self) -> None:
        self.assertIn("tasks_from: rollback", self.play_sub)
        self.assertIn("remnawave_subscription_upstream_target: legacy", self.play_sub)
        rollback_block = self.play_sub.split("Rollback production subscription page upstream", 1)[1][:400]
        self.assertNotIn("import_role:", rollback_block)

    def test_cutover_and_rollback_have_never_tag(self) -> None:
        for marker, tag in (
            ("Cutover production subscription page upstream", "sub_cutover"),
            ("Rollback production subscription page upstream", "sub_rollback"),
        ):
            block = _task_block(self.play_sub, marker)
            self.assertIn("never", _wrapper_tags(block), marker)
            self.assertIn(tag, _wrapper_tags(block), marker)

    def test_special_include_roles_have_apply_tags(self) -> None:
        for spec in SPECIAL_INCLUDE_OPERATIONS:
            block = _task_block(self.play_sub, spec["marker"])
            self.assertIn("include_role:", block, spec["marker"])
            self.assertNotIn("import_role:", block, spec["marker"])
            wrapper_tags = _wrapper_tags(block)
            apply_tags = _apply_tags(block)
            self.assertIn("never", wrapper_tags, spec["marker"])
            self.assertTrue(spec["wrapper_tags"].issubset(wrapper_tags), spec["marker"])
            self.assertEqual(spec["apply_tags"], apply_tags, spec["marker"])
            for forbidden in spec.get("forbidden_wrapper_tags", ()):
                self.assertNotIn(forbidden, wrapper_tags, spec["marker"])
            if "tasks_from" in spec:
                self.assertIn(f"tasks_from: {spec['tasks_from']}", block, spec["marker"])
            if "role" in spec:
                self.assertIn(f"name: {spec['role']}", block, spec["marker"])

    def test_makefile_documents_sub_tags_nginx(self) -> None:
        sub_block = self.makefile.split("sub: ##", 1)[1].split("\n\n", 1)[0]
        self.assertIn("make sub TAGS=nginx", sub_block)

    def test_production_nginx_wrapper_not_in_staging_play(self) -> None:
        staging = _staging_play(self.play_sub)
        self.assertNotIn("Configure production subscription Nginx vhost only", staging)
        self.assertNotIn("tasks_from: nginx.yml", staging.split("Deploy subscription-next Nginx", 1)[0])

    def test_sub_next_full_present_on_all_next_operations(self) -> None:
        for marker in (
            "Deploy subscription-next container",
            "Deploy subscription-next Nginx reverse proxy",
            "Manage subscription page config via Remnawave API",
        ):
            block = _task_block(self.play_sub, marker)
            self.assertIn("sub_next_full", _wrapper_tags(block), marker)
            self.assertIn("sub_next_full", _apply_tags(block), marker)

    def test_next_nginx_has_no_broad_nginx_tag(self) -> None:
        block = _task_block(self.play_sub, "Deploy subscription-next Nginx reverse proxy")
        self.assertNotIn("nginx", _wrapper_tags(block))
        self.assertNotIn("nginx", _apply_tags(block))

    def test_runtime_cutover_and_rollback_task_files_exist(self) -> None:
        for path in RUNTIME_TASK_FILES:
            self.assertTrue(path.is_file(), str(path))

    def test_playbook_has_no_legacy_wrapper_tags(self) -> None:
        for legacy_tag in LEGACY_WRAPPER_TAGS:
            self.assertNotIn(f"- {legacy_tag}", self.play_sub, legacy_tag)

    def test_make_sub_nginx_tag_does_not_select_next_nginx_wrapper(self) -> None:
        block = _task_block(self.play_sub, "Deploy subscription-next Nginx reverse proxy")
        self.assertNotIn("nginx", _wrapper_tags(block))
        self.assertNotIn("nginx", _apply_tags(block))

    def test_config_plan_and_apply_share_tag_without_extra_vars(self) -> None:
        plan_block = self.makefile.split("sub-next-config-plan:", 1)[1].split("\n\n", 1)[0]
        apply_block = self.makefile.split("sub-next-config-apply:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("--tags sub_next_config", plan_block)
        self.assertIn("--tags sub_next_config", apply_block)
        self.assertIn("--check --diff", plan_block)
        self.assertNotIn("--check --diff", apply_block)
        self.assertNotIn("-e ", plan_block)
        self.assertNotIn("-e ", apply_block)

    def test_playbook_has_exactly_two_plays(self) -> None:
        self.assertEqual(len(_play_blocks(self.play_sub)), 2)

    def test_first_play_hosts_panel_subscription(self) -> None:
        first_play = "- name:" + _play_blocks(self.play_sub)[0]
        self.assertIn("hosts: panel:subscription", first_play)

    def test_second_play_hosts_subscription(self) -> None:
        second_play = _staging_play(self.play_sub)
        self.assertIn("hosts: subscription", second_play)
        self.assertIn("gather_facts: true", second_play)

    def test_staging_play_contains_all_special_include_tasks_in_order(self) -> None:
        staging = _staging_play(self.play_sub)
        positions = [staging.index(marker) for marker in STAGING_PLAY_MARKERS]
        self.assertEqual(positions, sorted(positions))

    def test_simultaneous_cutover_and_rollback_are_forbidden(self) -> None:
        guard = _task_block(
            self.play_sub,
            "Refuse simultaneous production cutover and rollback tag selection",
        )
        self.assertIn("ansible_run_tags", guard)
        self.assertIn("'sub_cutover' in ansible_run_tags", guard)
        self.assertIn("'sub_rollback' in ansible_run_tags", guard)
        self.assertIn("'all' not in ansible_run_tags", guard)
        self.assertIn("sub_cutover", _wrapper_tags(guard))
        self.assertIn("sub_rollback", _wrapper_tags(guard))
        self.assertNotIn("never", _wrapper_tags(guard))

    def test_normal_deploy_playbook_does_not_force_upstream_target(self) -> None:
        deploy_play = self.play_sub.split(
            "- name: Manage Subscription Page staging and production target",
            maxsplit=1,
        )[0]
        self.assertNotIn("remnawave_subscription_upstream_target:", deploy_play)


if __name__ == "__main__":
    unittest.main()
