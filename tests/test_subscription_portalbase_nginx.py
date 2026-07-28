#!/usr/bin/env python3
"""Structural checks for dedicated sub.portalbase.link Nginx reverse proxy."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles/remnawave_subscription_page_next"
TEMPLATE = ROLE / "templates/nginx-sub-portalbase.conf.j2"
TASKS = ROLE / "tasks/nginx_portalbase.yml"
DEFAULTS = ROLE / "defaults/main.yml"
HANDLERS = ROLE / "handlers/main.yml"
PLAYBOOK = REPO_ROOT / "playbooks/subscription.yml"
MAKEFILE = REPO_ROOT / "Makefile"
INVENTORY = REPO_ROOT / "inventory/group_vars/subscription/main.yml"

FORBIDDEN_PATTERNS = (
    "remnawave_sub_next_aliases",
    "remnawave_sub_portalbase_aliases",
    "sub.vpn-for-friends.com",
    "sub-next.vpn-for-friends.com",
    "SUB_PUBLIC_DOMAIN",
    "remnawave_subscription_upstream_target",
)


class SubscriptionPortalbaseNginxTest(unittest.TestCase):
    def test_template_exists_and_targets_portalbase_domain(self) -> None:
        self.assertTrue(TEMPLATE.is_file())
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{{ remnawave_sub_portalbase_domain }}", content)
        self.assertIn("remnawave-subscription-page-portalbase", content)
        self.assertIn("proxy_set_header X-Forwarded-Proto https", content)
        self.assertIn("proxy_set_header Host $host", content)
        self.assertNotIn("remnawave-subscription-page-next", content)

    def test_template_has_http_bootstrap_and_https_block(self) -> None:
        content = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("listen 80", content)
        self.assertIn("/.well-known/acme-challenge/", content)
        self.assertIn("remnawave_sub_portalbase_ssl_ready", content)
        self.assertIn("listen 443 ssl", content)
        self.assertIn("{{ remnawave_sub_portalbase_ssl_fullchain }}", content)

    def test_tasks_issue_cert_only_when_missing(self) -> None:
        content = TASKS.read_text(encoding="utf-8")
        self.assertIn("remnawave_sub_portalbase_certificate_was_missing", content)
        self.assertIn("certbot certonly", content)
        self.assertIn("--webroot", content)
        self.assertIn("-d {{ remnawave_sub_portalbase_domain }}", content)
        self.assertIn("Apply subscription portalbase HTTP bootstrap before certificate issuance", content)
        self.assertIn("Render subscription portalbase HTTPS Nginx vhost after certificate issuance", content)

    def test_tasks_healthcheck_url(self) -> None:
        content = TASKS.read_text(encoding="utf-8")
        self.assertIn(
            "https://{{ remnawave_sub_portalbase_domain }}/{{ remnawave_sub_portalbase_healthcheck_short_uuid }}",
            content,
        )

    def test_handlers_run_nginx_t_before_reload(self) -> None:
        content = HANDLERS.read_text(encoding="utf-8")
        self.assertIn("Reload subscription portalbase Nginx", content)
        self.assertIn("nginx -t", content)

    def test_defaults_are_fixed_domain_not_alias_list(self) -> None:
        content = DEFAULTS.read_text(encoding="utf-8")
        self.assertIn('remnawave_sub_portalbase_domain: "sub.portalbase.link"', content)
        self.assertIn("remnawave_sub_portalbase_upstream_port: 3011", content)
        self.assertIn('remnawave_sub_portalbase_healthcheck_short_uuid: "VZLHkrKwsj0Qs82e"', content)
        for pattern in ("remnawave_sub_next_aliases", "remnawave_sub_portalbase_aliases"):
            self.assertNotIn(pattern, content)

    def test_playbook_and_makefile_wire_dedicated_tag(self) -> None:
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertIn("Deploy subscription portalbase Nginx reverse proxy", playbook)
        self.assertIn("tasks_from: nginx_portalbase", playbook)
        self.assertIn("sub_portalbase", playbook)
        self.assertIn("sub-portalbase:", makefile)
        self.assertIn("--tags sub_portalbase", makefile)

    def test_inventory_enables_portalbase_without_touching_production_domains(self) -> None:
        content = INVENTORY.read_text(encoding="utf-8")
        self.assertIn("remnawave_sub_portalbase_nginx_enabled: true", content)
        self.assertIn('remnawave_sub_portalbase_domain: "sub.portalbase.link"', content)
        self.assertIn('remnawave_sub_public_domain: sub.vpn-for-friends.com', content)
        self.assertIn('remnawave_sub_next_domain: "sub-next.vpn-for-friends.com"', content)

    def test_portalbase_files_do_not_reference_forbidden_concepts(self) -> None:
        for path in (TEMPLATE, TASKS):
            content = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_PATTERNS:
                self.assertNotIn(pattern, content, f"{path} contains {pattern}")


if __name__ == "__main__":
    unittest.main()
