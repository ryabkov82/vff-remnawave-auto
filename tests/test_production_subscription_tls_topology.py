#!/usr/bin/env python3
"""Static topology checks for production subscription TLS/SNI routing."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION_VARS = REPO_ROOT / "inventory/group_vars/subscription/main.yml"
PANEL_VARS = REPO_ROOT / "inventory/group_vars/panel/main.yml"
HAPROXY_TEMPLATE = REPO_ROOT / "roles/haproxy_tls_sni/templates/haproxy.cfg.j2"
HAPROXY_TASKS = REPO_ROOT / "roles/haproxy_tls_sni/tasks/main.yml"
SUB_NEXT_TEMPLATE = REPO_ROOT / "roles/remnawave_subscription_page_next/templates/nginx-sub-next.conf.j2"
PROD_TEMPLATE = REPO_ROOT / "roles/remnawave_subscription_page/templates/nginx-subscription.conf.j2"
CUTOVER = REPO_ROOT / "roles/remnawave_subscription_page/tasks/cutover.yml"
ROLLBACK = REPO_ROOT / "roles/remnawave_subscription_page/tasks/rollback.yml"


def _rollback_apply_block(content: str) -> str:
    marker = "- name: Perform explicit production subscription rollback apply"
    start = content.index(marker)
    rescue = content.index("  rescue:", start)
    return content[start:rescue]


def _cutover_mutation_block(content: str) -> str:
    marker = "- name: Perform production subscription page cutover"
    start = content.index(marker)
    rescue = content.index("  rescue:", start)
    return content[start:rescue]


class ProductionSubscriptionTlsTopologyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subscription_vars = SUBSCRIPTION_VARS.read_text(encoding="utf-8")
        cls.panel_vars = PANEL_VARS.read_text(encoding="utf-8")
        cls.haproxy_template = HAPROXY_TEMPLATE.read_text(encoding="utf-8")
        cls.haproxy_tasks = HAPROXY_TASKS.read_text(encoding="utf-8")
        cls.sub_next_template = SUB_NEXT_TEMPLATE.read_text(encoding="utf-8")
        cls.prod_template = PROD_TEMPLATE.read_text(encoding="utf-8")
        cls.cutover = CUTOVER.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK.read_text(encoding="utf-8")

    def test_subscription_inventory_uses_public_nginx_https_port_443(self) -> None:
        self.assertRegex(
            self.subscription_vars,
            r"remnawave_nginx_external_https_port:\s*443\b",
        )

    def test_panel_inventory_keeps_haproxy_backend_nginx_port_4443(self) -> None:
        self.assertRegex(
            self.panel_vars,
            r'remnawave_nginx_external_https_port:\s*"4443"|remnawave_nginx_external_https_port:\s*4443\b',
        )

    def test_production_template_uses_external_https_port_variable(self) -> None:
        self.assertIn("remnawave_nginx_external_https_port", self.prod_template)
        self.assertNotRegex(self.prod_template, r"listen\s+0\.0\.0\.0:4443\b")

    def test_sub_next_template_keeps_public_443_listener(self) -> None:
        self.assertRegex(self.sub_next_template, r"listen\s+443\s+ssl")
        self.assertIn("remnawave_sub_next_domain", self.sub_next_template)

    def test_haproxy_excludes_production_sub_when_subscription_group_exists(self) -> None:
        self.assertIn("remnawave_group_subscription not in groups", self.haproxy_template)
        self.assertIn("remnawave_sub_public_domain", self.haproxy_template)

    def test_haproxy_panel_sni_routes_to_nginx_backend_before_default(self) -> None:
        panel_pos = self.haproxy_template.index("use_backend be_panel if SNI_PANEL")
        default_pos = self.haproxy_template.index("default_backend be_node_nginx")
        self.assertLess(panel_pos, default_pos)
        self.assertIn("backend be_panel", self.haproxy_template)
        self.assertIn("haproxy_nginx_port", self.haproxy_template)

    def test_haproxy_candidate_runs_config_check_before_install(self) -> None:
        self.assertIn('validate: "haproxy -c -f %s"', self.haproxy_tasks)

    def test_cutover_production_tls_preflight_runs_before_mutation(self) -> None:
        preflight_pos = self.cutover.index(
            "Preflight production subscription public HTTPS TLS from controller",
        )
        mutation_pos = self.cutover.index("Perform production subscription page cutover")
        self.assertLess(preflight_pos, mutation_pos)

    def test_cutover_production_tls_preflight_uses_controller_tls_validation(self) -> None:
        block = self.cutover.split(
            "Validate public production subscription TLS from controller before cutover mutation",
            maxsplit=1,
        )[1].split("Validate production subscription TLS before cutover mutation", maxsplit=1)[0]
        self.assertIn("delegate_to: localhost", block)
        self.assertIn("become: false", block)
        self.assertIn("validate_certs: true", block)
        self.assertIn("use_proxy: false", block)
        self.assertIn("status_code: 200", block)
        self.assertIn("remnawave_sub_public_domain", block)
        self.assertNotIn("x_vff_subscription_target", block.lower())

    def test_rollback_render_uses_include_tasks_inside_block(self) -> None:
        block = _rollback_apply_block(self.rollback)
        self.assertIn("include_tasks: render_production_subscription_vhost.yml", block)
        self.assertNotIn("import_tasks: render_production_subscription_vhost.yml", block)

    def test_rollback_health_check_is_inside_protected_block(self) -> None:
        block = _rollback_apply_block(self.rollback)
        self.assertIn("Verify production HTTPS subscription page after rollback", block)
        self.assertIn("Assert production subscription vhost contains legacy upstream marker", block)

    def test_rollback_rescue_restores_timestamp_backup_with_diagnostics(self) -> None:
        rescue = self.rollback.split("  rescue:", maxsplit=1)[1]
        diag_pos = rescue.index("Build sanitized production rollback health check diagnostics")
        restore_pos = rescue.index("Restore production subscription vhost from rollback timestamp backup")
        fail_pos = rescue.index("Fail after automatic production subscription rollback recovery")
        self.assertLess(diag_pos, restore_pos)
        self.assertLess(restore_pos, fail_pos)
        self.assertIn("remnawave_subscription_uri_health_diagnostics", rescue)
        self.assertIn("_sub_rollback_timestamp_backup.dest", rescue)
        self.assertIn("Probe production subscription public HTTPS transport after rollback rescue", rescue)

    def test_rollback_block_structure_allows_rescue_on_health_failure(self) -> None:
        block = _rollback_apply_block(self.rollback)
        health_pos = block.index("Verify production HTTPS subscription page after rollback")
        self.assertNotIn("import_tasks: render_production_subscription_vhost.yml", block)
        self.assertLess(
            block.index("include_tasks: render_production_subscription_vhost.yml"),
            health_pos,
        )

    def test_cutover_mutation_uses_include_tasks_for_render(self) -> None:
        block = _cutover_mutation_block(self.cutover)
        self.assertIn("include_tasks: render_production_subscription_vhost.yml", block)
        self.assertNotIn("import_tasks: render_production_subscription_vhost.yml", block)


if __name__ == "__main__":
    unittest.main()
