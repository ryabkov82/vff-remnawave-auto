#!/usr/bin/env python3
"""Structural checks for subscription-next local HTTP health-check headers."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles/remnawave_subscription_page_next"
TASKS = ROLE / "tasks/main.yml"
DEFAULTS = ROLE / "defaults/main.yml"


def _task_block(content: str, marker: str) -> str:
    start = content.index(f"- name: {marker}")
    tail = content[start + 1 :]
    match = re.search(r"\n- name: ", tail)
    end = start + 1 + match.start() if match else len(content)
    return content[start:end]


class SubscriptionNextHealthcheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = TASKS.read_text(encoding="utf-8")
        cls.defaults = DEFAULTS.read_text(encoding="utf-8")
        cls.block = _task_block(cls.tasks, "HTTP check subscription-next page URL")

    def test_healthcheck_uses_local_bind_and_port(self) -> None:
        self.assertIn("remnawave_sub_next_bind_address", self.block)
        self.assertIn("remnawave_sub_next_external_port", self.block)
        self.assertIn("remnawave_sub_next_healthcheck_short_uuid", self.block)
        self.assertIn("http://{{ remnawave_sub_next_bind_address }}", self.block)
        self.assertNotIn("https://", self.block.split("url:", 1)[1].split("method:", 1)[0])

    def test_defaults_keep_localhost_3011(self) -> None:
        self.assertIn("remnawave_sub_next_bind_address: 127.0.0.1", self.defaults)
        self.assertIn("remnawave_sub_next_external_port: 3011", self.defaults)
        self.assertIn('remnawave_sub_portalbase_domain: "sub.portalbase.link"', self.defaults)

    def test_healthcheck_sends_reverse_proxy_headers(self) -> None:
        self.assertIn('Host: "{{ remnawave_sub_portalbase_domain }}"', self.block)
        self.assertIn('X-Forwarded-Host: "{{ remnawave_sub_portalbase_domain }}"', self.block)
        self.assertIn('X-Forwarded-Proto: "https"', self.block)
        self.assertIn('X-Forwarded-Port: "443"', self.block)
        self.assertIn('X-Real-IP: "127.0.0.1"', self.block)
        self.assertIn('X-Forwarded-For: "127.0.0.1"', self.block)

    def test_healthcheck_keeps_retry_and_check_mode_guards(self) -> None:
        self.assertIn("register: _sub_next_http", self.block)
        self.assertIn("retries: 10", self.block)
        self.assertIn("delay: 3", self.block)
        self.assertIn("until: _sub_next_http.status == 200", self.block)
        self.assertIn("timeout: 10", self.block)
        self.assertIn("status_code: 200", self.block)
        self.assertIn("not ansible_check_mode", self.block)
        self.assertNotIn("failed_when: false", self.block)
        self.assertNotIn("ignore_errors", self.block)


if __name__ == "__main__":
    unittest.main()
