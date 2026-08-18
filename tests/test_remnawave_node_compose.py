#!/usr/bin/env python3
"""Render tests for remnawave_node docker-compose extra volumes."""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml
from jinja2 import Environment, FileSystemLoader

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles/remnawave_node"
COMPOSE_TASKS = (ROLE / "tasks/compose.yml").read_text(encoding="utf-8")
SMOKE_NODE = (REPO / "roles/smoke_tests/tasks/node.yml").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
UPGRADE_NODES = (REPO / "roles/remnawave_upgrade/tasks/upgrade_nodes.yml").read_text(
    encoding="utf-8"
)
NODES_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/nodes.yml").read_text(encoding="utf-8")
)
CDN_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/antiblock_cdn_nodes.yml").read_text(encoding="utf-8")
)
HOSTS_INI = (REPO / "inventory/hosts.ini").read_text(encoding="utf-8")
ANTIBLOCK_INBOUND = yaml.safe_load(
    (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(encoding="utf-8")
)
LETSENCRYPT_VOLUME = "/etc/letsencrypt:/etc/letsencrypt:ro"
HOST_LOG_VOLUME = "/var/log/remnanode:/var/log/remnanode"


def _basename(value: str) -> str:
    return Path(str(value)).name


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in {"1", "true", "yes", "on"}


def _render(**overrides) -> str:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), autoescape=False)
    env.filters["basename"] = _basename
    env.filters["bool"] = _bool
    ctx = {
        "remnawave_node_container_name": "remnanode",
        "remnawave_node_image": "remnawave/node:3.2.2",
        "remnawave_node_network_mode": "host",
        "remnawave_node_restart_policy": "always",
        "remnawave_node_cap_net_admin": True,
        "remnawave_node_plugins_enabled": True,
        "remnawave_node_enable_host_logs": True,
        "remnawave_node_log_dir": "/var/log/remnanode",
        "remnawave_node_geo_files": [],
        "remnawave_node_extra_volumes": [],
        "remnawave_node_dir": "/opt/remnanode",
    }
    ctx.update(overrides)
    return env.get_template("docker-compose.yml.j2").render(**ctx)


def _volume_lines(rendered: str) -> list[str]:
    parsed = yaml.safe_load(rendered)
    service = parsed["services"]["remnanode"]
    return list(service.get("volumes") or [])


class RemnawaveNodeComposeTests(unittest.TestCase):
    def test_defaults_keep_extra_volumes_empty(self) -> None:
        self.assertEqual(DEFAULTS["remnawave_node_extra_volumes"], [])
        self.assertTrue(DEFAULTS["remnawave_node_enable_host_logs"])
        self.assertEqual(DEFAULTS["remnawave_node_geo_files"], [])

    def test_ordinary_node_has_host_logs_without_letsencrypt(self) -> None:
        rendered = _render()
        volumes = _volume_lines(rendered)
        self.assertEqual(volumes, [HOST_LOG_VOLUME])
        self.assertNotIn("/etc/letsencrypt", rendered)
        self.assertIn("network_mode: host", rendered)
        self.assertIn("NET_ADMIN", rendered)
        self.assertIn("env_file:", rendered)
        self.assertIn("- .env", rendered)

    def test_cdn_node_keeps_host_logs_and_letsencrypt(self) -> None:
        rendered = _render(remnawave_node_extra_volumes=[LETSENCRYPT_VOLUME])
        volumes = _volume_lines(rendered)
        self.assertEqual(volumes, [HOST_LOG_VOLUME, LETSENCRYPT_VOLUME])

    def test_extra_volumes_render_when_logs_and_geo_are_empty(self) -> None:
        rendered = _render(
            remnawave_node_enable_host_logs=False,
            remnawave_node_geo_files=[],
            remnawave_node_extra_volumes=[LETSENCRYPT_VOLUME],
        )
        volumes = _volume_lines(rendered)
        self.assertEqual(volumes, [LETSENCRYPT_VOLUME])
        self.assertIn("volumes:", rendered)
        self.assertNotIn(HOST_LOG_VOLUME, volumes)

    def test_no_volumes_key_when_everything_empty(self) -> None:
        rendered = _render(
            remnawave_node_enable_host_logs=False,
            remnawave_node_geo_files=[],
            remnawave_node_extra_volumes=[],
        )
        parsed = yaml.safe_load(rendered)
        self.assertNotIn("volumes", parsed["services"]["remnanode"])
        self.assertIn("NET_ADMIN", rendered)
        self.assertIn("env_file:", rendered)

    def test_geo_mounts_still_render_with_extra_volumes(self) -> None:
        rendered = _render(
            remnawave_node_geo_files=[
                {"src": "files/geo-zapret.dat", "dest_name": "geo-zapret.dat"}
            ],
            remnawave_node_extra_volumes=[LETSENCRYPT_VOLUME],
        )
        volumes = _volume_lines(rendered)
        self.assertIn(HOST_LOG_VOLUME, volumes)
        self.assertIn(
            "/opt/remnanode/geo-zapret.dat:/usr/local/share/xray/geo-zapret.dat",
            volumes,
        )
        self.assertIn(LETSENCRYPT_VOLUME, volumes)


class AntiblockCdnVolumeWiringTests(unittest.TestCase):
    def test_cdn_group_sets_letsencrypt_for_all_cdn_nodes(self) -> None:
        self.assertEqual(CDN_VARS["remnawave_node_extra_volumes"], [LETSENCRYPT_VOLUME])
        role_files = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (REPO / "roles/remnawave_node").rglob("*")
            if path.is_file()
        )
        self.assertNotIn("de-fra-2", role_files)
        self.assertNotIn("certbot", role_files)

    def test_ordinary_nodes_group_does_not_mount_letsencrypt(self) -> None:
        self.assertNotIn("remnawave_node_extra_volumes", NODES_VARS)
        self.assertNotIn("/etc/letsencrypt", (REPO / "inventory/group_vars/nodes.yml").read_text(encoding="utf-8"))

    def test_cdn_group_is_additive_and_not_hostname_special_cased(self) -> None:
        self.assertIn("[antiblock_cdn_nodes]", HOSTS_INI)
        cdn_members = HOSTS_INI.split("[antiblock_cdn_nodes]", 1)[1].split("[", 1)[0]
        self.assertIn("de-fra-2", cdn_members)
        nodes = HOSTS_INI.split("[nodes]", 1)[1].split("[", 1)[0]
        self.assertIn("ru-spb-2", nodes)
        self.assertNotIn("ru-spb-2", cdn_members)

    def test_upgrade_reuses_remnawave_node_without_clearing_extra_volumes(self) -> None:
        self.assertIn("name: remnawave_node", UPGRADE_NODES)
        self.assertIn("remnawave_node_write_env: false", UPGRADE_NODES)
        self.assertNotIn("remnawave_node_extra_volumes", UPGRADE_NODES)
        self.assertNotIn("remnawave_node_compose_raw", UPGRADE_NODES)

    def test_inbound_cert_paths_stay_on_host_letsencrypt(self) -> None:
        inbound = ANTIBLOCK_INBOUND["antiblock_cdn_inbound"]
        certs = inbound["streamSettings"]["tlsSettings"]["certificates"][0]
        self.assertEqual(
            certs["certificateFile"],
            "/etc/letsencrypt/live/digitalstreamers.xyz/fullchain.pem",
        )
        self.assertEqual(
            certs["keyFile"],
            "/etc/letsencrypt/live/digitalstreamers.xyz/privkey.pem",
        )


class RemnawaveNodeSmokeStateTests(unittest.TestCase):
    def test_compose_smoke_uses_inspect_state_not_docker_ps(self) -> None:
        self.assertIn("json .State", COMPOSE_TASKS)
        self.assertIn("_rw_node_container_state.Running", COMPOSE_TASKS)
        self.assertIn("_rw_node_container_state.Status == 'running'", COMPOSE_TASKS)
        self.assertIn(
            "not (_rw_node_container_state.Restarting | default(false) | bool)",
            COMPOSE_TASKS,
        )
        self.assertNotIn("docker ps --format", COMPOSE_TASKS)

    def test_smoke_node_uses_inspect_state_not_docker_ps(self) -> None:
        self.assertIn("json .State", SMOKE_NODE)
        self.assertIn("_smoke_node_state.Running", SMOKE_NODE)
        self.assertIn("_smoke_node_state.Status == 'running'", SMOKE_NODE)
        self.assertIn(
            "not (_smoke_node_state.Restarting | default(false) | bool)",
            SMOKE_NODE,
        )
        self.assertNotIn("docker ps --format", SMOKE_NODE)

    def test_restarting_is_not_treated_as_running(self) -> None:
        for source in (COMPOSE_TASKS, SMOKE_NODE):
            self.assertIn(".Restarting", source)
            self.assertIn(".Status == 'running'", source)
            self.assertIn(".Running", source)


if __name__ == "__main__":
    unittest.main()
