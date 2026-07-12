#!/usr/bin/env python3
"""Static checks for production subscription TLS and render safety."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "roles/remnawave_subscription_page/templates/nginx-subscription.conf.j2"
CUTOVER = REPO_ROOT / "roles/remnawave_subscription_page/tasks/cutover.yml"
ROLLBACK = REPO_ROOT / "roles/remnawave_subscription_page/tasks/rollback.yml"
VALIDATE_TLS = REPO_ROOT / "roles/remnawave_subscription_page/tasks/validate_production_subscription_tls.yml"
RENDER = REPO_ROOT / "roles/remnawave_subscription_page/tasks/render_production_subscription_vhost.yml"
ASSERT_RENDER = REPO_ROOT / "roles/remnawave_subscription_page/tasks/assert_rendered_production_subscription_vhost.yml"


class ProductionSubscriptionTlsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = TEMPLATE.read_text(encoding="utf-8")
        cls.cutover = CUTOVER.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK.read_text(encoding="utf-8")
        cls.validate_tls = VALIDATE_TLS.read_text(encoding="utf-8")
        cls.render = RENDER.read_text(encoding="utf-8")
        cls.assert_render = ASSERT_RENDER.read_text(encoding="utf-8")

    def test_template_uses_production_certificate_variables(self) -> None:
        self.assertIn("remnawave_subscription_prod_ssl_fullchain", self.template)
        self.assertIn("remnawave_subscription_prod_ssl_privkey", self.template)
        self.assertNotIn("remnawave_sub_next_ssl_fullchain", self.template)
        self.assertNotIn("remnawave_sub_next_ssl_privkey", self.template)
        self.assertNotIn("remnawave_nginx_ssl_fullchain", self.template)

    def test_certificate_paths_follow_production_domain(self) -> None:
        self.assertIn(
            'remnawave_subscription_prod_ssl_fullchain: "/etc/letsencrypt/live/{{ remnawave_sub_public_domain }}/fullchain.pem"',
            (REPO_ROOT / "roles/remnawave_subscription_page/defaults/main.yml").read_text(encoding="utf-8"),
        )

    def test_openssl_checkhost_runs_before_render(self) -> None:
        self.assertIn("openssl x509", self.validate_tls)
        self.assertIn("-checkhost {{ remnawave_sub_public_domain }}", self.validate_tls)
        validate_pos = self.render.index("validate_production_subscription_tls.yml")
        template_pos = self.render.index("Render production subscription vhost candidate")
        self.assertLess(validate_pos, template_pos)

    def test_render_pipeline_asserts_candidate_before_install(self) -> None:
        assert_pos = self.render.index("assert_rendered_production_subscription_vhost.yml")
        install_pos = self.render.index("Install validated production subscription vhost")
        self.assertLess(assert_pos, install_pos)
        self.assertIn("remnawave_subscription_prod_ssl_fullchain", self.assert_render)
        self.assertIn("remnawave_subscription_effective_upstream_target", self.assert_render)

    def test_rollback_rescue_restores_timestamp_backup(self) -> None:
        rescue_part = self.rollback.split("  rescue:", maxsplit=1)[1]
        self.assertIn("Restore production subscription vhost from rollback timestamp backup", rescue_part)
        self.assertIn("_sub_rollback_timestamp_backup.dest", rescue_part)
        self.assertIn("Fail after automatic production subscription rollback recovery", rescue_part)
        self.assertIn("Build sanitized production rollback health check diagnostics", rescue_part)
        self.assertIn("include_tasks: render_production_subscription_vhost.yml", self.rollback)
        self.assertNotIn("import_tasks: render_production_subscription_vhost.yml", self.rollback)

    def test_cutover_rescue_still_restores_timestamp_backup(self) -> None:
        rescue_part = self.cutover.split("  rescue:", maxsplit=1)[1]
        self.assertIn("Restore production subscription vhost from timestamp backup", rescue_part)
        self.assertIn("_sub_cutover_timestamp_backup.dest", rescue_part)

    def test_cutover_uses_shared_render_pipeline(self) -> None:
        self.assertIn("render_production_subscription_vhost.yml", self.cutover)
        self.assertNotIn("dest: \"{{ remnawave_nginx_sites_dir }}/{{ remnawave_nginx_subscription_site }}\"", self.cutover.split("Perform production subscription page cutover", 1)[1].split("  rescue:", 1)[0])

    def test_duplicate_ssl_conflict_check_exists(self) -> None:
        self.assertIn("Detect conflicting production subscription HTTPS server blocks", self.validate_tls)


if __name__ == "__main__":
    unittest.main()
