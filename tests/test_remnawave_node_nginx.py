#!/usr/bin/env python3
"""Structural tests for node nginx xHTTP snippet (access_log off)."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles/remnawave_node_nginx"
TEMPLATE = (ROLE / "templates/ds_server_includes_20-xhttp.conf.j2").read_text(
    encoding="utf-8"
)
TASKS = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
VHOST = (ROLE / "templates/node_https_4443.conf.j2").read_text(encoding="utf-8")


class XhttpSnippetAccessLogTests(unittest.TestCase):
    def test_location_disables_access_log(self) -> None:
        self.assertIn("location {{ nginx_xhttp_location }}", TEMPLATE)
        self.assertIn("access_log off;", TEMPLATE)
        self.assertIn("grpc_pass grpc://{{ nginx_xhttp_upstream }}", TEMPLATE)
        self.assertNotIn("error_log off", TEMPLATE)

    def test_access_log_off_is_inside_location_block(self) -> None:
        start = TEMPLATE.index("location {{ nginx_xhttp_location }} {")
        end = TEMPLATE.rindex("}")
        body = TEMPLATE[start:end]
        self.assertIn("access_log off;", body)
        self.assertLess(body.index("access_log off;"), body.index("grpc_pass"))

    def test_deploy_task_still_uses_xhttp_template(self) -> None:
        self.assertIn("src: ds_server_includes_20-xhttp.conf.j2", TASKS)
        self.assertIn('dest: "{{ nginx_server_includes_dir }}/20-xhttp.conf"', TASKS)
        self.assertIn("notify: nginx restart", TASKS)

    def test_standalone_vhost_unchanged(self) -> None:
        self.assertNotIn("access_log off;", VHOST)
        self.assertIn("listen {{ nginx_https_bind }} ssl http2;", VHOST)


if __name__ == "__main__":
    unittest.main()
