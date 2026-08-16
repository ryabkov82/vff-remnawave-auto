#!/usr/bin/env python3
"""Structural tests for dedicated AntiBlock CDN orchestration."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PLAY = REPO / "playbooks/antiblock_cdn.yml"
INBOUNDS_PLAY = REPO / "playbooks/inbounds.yml"
NODES_PLAY = REPO / "playbooks/nodes.yml"
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
HOST_VARS_CDN_NODE = REPO / "inventory/host_vars/de-fra-2/main.yml"
GROUP_CDN_NODES = REPO / "inventory/group_vars/antiblock_cdn_nodes.yml"
INBOUNDS_TASKS = (REPO / "roles/remnawave_inbounds/tasks/main.yml").read_text(
    encoding="utf-8"
)
REGISTER_NODE_TASKS = (REPO / "roles/remnawave_register_node/tasks/main.yml").read_text(
    encoding="utf-8"
)
DOCS = (REPO / "docs/antiblock_cdn.md").read_text(encoding="utf-8")
ANTIBLOCK_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(encoding="utf-8")
)

FORBIDDEN_UUIDS = (
    "a281fe1b-d9b6-4874-b34a-2832481cc60f",
    "d7340374-7968-4240-9528-8c617af963ee",
)
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _plays(path: Path = PLAY) -> list[dict]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return []
    if isinstance(loaded, list):
        return loaded
    return [loaded]


def _roles(play: dict) -> list[dict]:
    roles = play.get("roles") or []
    out: list[dict] = []
    for item in roles:
        if isinstance(item, dict):
            out.append(item)
        else:
            out.append({"role": item})
    return out


def _role(play: dict) -> dict:
    roles = _roles(play)
    self = unittest.TestCase()
    self.assertGreaterEqual(len(roles), 1, msg=play.get("name"))
    return roles[0]


def _makefile_block(target: str) -> str:
    marker = f"{target}:"
    start = MAKEFILE.find(marker)
    if start < 0:
        raise AssertionError(f"missing make target {target}")
    rest = MAKEFILE[start:]
    nxt = rest.find("\n\n")
    return rest if nxt < 0 else rest[:nxt]


class AntiblockCdnPlaybookTests(unittest.TestCase):
    def test_two_plays_panel_then_cdn_nodes(self) -> None:
        plays = _plays()
        self.assertEqual(len(plays), 2)
        self.assertEqual(plays[0]["hosts"], "panel")
        self.assertEqual(plays[1]["hosts"], "antiblock_cdn_nodes")
        self.assertEqual(_role(plays[0])["role"], "remnawave_inbounds")
        self.assertEqual(_roles(plays[1])[0]["role"], "remnawave_register_node")

    def test_inbound_passed_by_tag_without_uuid(self) -> None:
        raw = PLAY.read_text(encoding="utf-8")
        vars_ = _role(_plays()[0])["vars"]
        self.assertEqual(vars_["remnawave_inbounds"], ["{{ antiblock_cdn_inbound }}"])
        self.assertEqual(
            vars_["remnawave_inbounds_managed"],
            ["{{ antiblock_cdn_inbound_tag }}"],
        )
        self.assertNotIn("remnawave_profile_uuid", vars_)
        for uuid in FORBIDDEN_UUIDS:
            self.assertNotIn(uuid, raw)
        self.assertIsNone(UUID_RE.search(raw))

    def test_tag_collision_is_strict_fail_via_existing_var(self) -> None:
        vars_ = _role(_plays()[0])["vars"]
        self.assertEqual(
            vars_["remnawave_tag_collision_mode"],
            "{{ antiblock_cdn_tag_collision_mode }}",
        )
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_tag_collision_mode"], "fail")
        self.assertIn("Fail on global inbound tag collision (409)", INBOUNDS_TASKS)
        self.assertIn("_ri.tag_collision_mode == 'fail'", INBOUNDS_TASKS)

    def test_memberships_only_in_dedicated_playbook(self) -> None:
        memberships = _role(_plays()[0])["vars"]["remnawave_inbound_squad_memberships"]
        self.assertEqual(len(memberships), 1)
        item = memberships[0]
        self.assertEqual(item["inbound_tag"], "{{ antiblock_cdn_inbound_tag }}")
        self.assertEqual(item["present_in"], ["{{ antiblock_cdn_internal_squad }}"])
        self.assertNotIn("Default-Squad", item["present_in"])
        self.assertNotIn("{{ antiblock_cdn_forbidden_internal_squads }}", item["present_in"])
        self.assertEqual(
            item["absent_from"],
            "{{ antiblock_cdn_forbidden_internal_squads }}",
        )
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_internal_squad"], "AntiBlock-Squad")
        self.assertEqual(
            ANTIBLOCK_VARS["antiblock_cdn_forbidden_internal_squads"],
            ["Default-Squad"],
        )
        inbounds_play = INBOUNDS_PLAY.read_text(encoding="utf-8")
        self.assertNotIn("remnawave_inbound_squad_memberships", inbounds_play)
        self.assertNotIn("antiblock_cdn_inbound", inbounds_play)

    def test_additive_default_squad_path_disabled_in_dedicated_play(self) -> None:
        vars_ = _role(_plays()[0])["vars"]
        self.assertFalse(vars_["remnawave_register_inbounds_in_squad"])
        self.assertEqual(vars_["remnawave_update_mode"], "replace")

    def test_cdn_nodes_keep_host_replace_and_extra_tag(self) -> None:
        play2 = _plays()[1]
        self.assertNotIn("vars", _role(play2))
        host = yaml.safe_load(HOST_VARS_CDN_NODE.read_text(encoding="utf-8"))
        self.assertEqual(host["remnawave_node_inbounds_mode"], "replace")
        self.assertNotIn(
            "VLESS xHTTP packet-up test",
            host["remnawave_inbound_tags"],
        )
        group = yaml.safe_load(GROUP_CDN_NODES.read_text(encoding="utf-8"))
        self.assertEqual(
            group["remnawave_inbound_tags_extra"],
            ["{{ antiblock_cdn_inbound_tag }}"],
        )

    def test_ordinary_playbooks_unchanged(self) -> None:
        nodes = _plays(NODES_PLAY)[0]
        role_names = []
        for item in nodes.get("roles") or []:
            if isinstance(item, str):
                role_names.append(item)
            elif isinstance(item, dict):
                role_names.append(item.get("role") or item.get("name"))
        self.assertIn("remnawave_register_node", role_names)
        self.assertIn("remnawave_add_host", role_names)
        self.assertIn("remnawave_node_haproxy", role_names)
        nodes_raw = NODES_PLAY.read_text(encoding="utf-8")
        self.assertNotIn("antiblock_cdn", nodes_raw)
        self.assertNotIn("VLESS xHTTP packet-up test", nodes_raw)
        inbounds = _plays(INBOUNDS_PLAY)[0]
        self.assertEqual(inbounds["hosts"], "panel")
        self.assertEqual(inbounds["roles"][0]["role"], "remnawave_inbounds")
        self.assertNotIn("vars", inbounds["roles"][0])

    def test_hosts_adoption_after_public_cname_not_add_host(self) -> None:
        raw = PLAY.read_text(encoding="utf-8")
        self.assertNotIn("remnawave_add_host", raw)
        self.assertNotIn("haproxy_tls_sni", raw)
        roles = [item["role"] for play in _plays() for item in _roles(play)]
        self.assertEqual(roles, ["remnawave_inbounds", "remnawave_register_node"])
        includes = [
            (task.get("ansible.builtin.include_role") or {}).get("name")
            for task in (_plays()[1].get("tasks") or [])
            if isinstance(task, dict)
            and (task.get("ansible.builtin.include_role") or task.get("include_role"))
        ]
        self.assertEqual(
            includes,
            [
                "cf_dns",
                "remnawave_node_haproxy",
                "yandex_cdn",
                "cf_dns",
                "remnawave_antiblock_hosts",
            ],
        )
        hosts = next(
            task
            for task in (_plays()[1].get("tasks") or [])
            if (task.get("ansible.builtin.include_role") or {}).get("name")
            == "remnawave_antiblock_hosts"
        )
        apply_tags = hosts["ansible.builtin.include_role"]["apply"]["tags"]
        self.assertIn("antiblock_cdn_hosts", apply_tags)
        self.assertIn("antiblock_cdn_hosts", hosts.get("tags") or [])
        self.assertTrue(hosts["vars"]["antiblock_cdn_hosts_allow_writes"])
        names = [str(task.get("name")) for task in (_plays()[1].get("tasks") or [])]
        self.assertLess(
            names.index("AntiBlock CDN | Ensure public CDN CNAME"),
            names.index("AntiBlock CDN | Reconcile Remnawave CDN Hosts"),
        )

    def test_other_inbounds_kept_by_current_map_copy(self) -> None:
        self.assertIn("current_map.copy()", INBOUNDS_TASKS)
        self.assertIn(
            "(_curr_inb_uuids + _desired_inbound_uuids) | unique",
            REGISTER_NODE_TASKS,
        )
        self.assertIn(
            "(_final_inbound_uuids | sort) != (_curr_inb_uuids | sort)",
            REGISTER_NODE_TASKS,
        )

    def test_makefile_plan_is_syntax_check_only(self) -> None:
        plan = _makefile_block("antiblock-cdn-plan")
        apply_ = _makefile_block("antiblock-cdn")
        inbounds = _makefile_block("inbounds")
        nodes = _makefile_block("nodes")
        plan_cmds = [ln for ln in plan.splitlines() if "$(ANSIBLE)" in ln]
        apply_cmds = [ln for ln in apply_.splitlines() if "$(ANSIBLE)" in ln]
        self.assertTrue(plan_cmds)
        self.assertTrue(any("--syntax-check" in ln for ln in plan_cmds))
        self.assertFalse(
            any(re.search(r"(^|\s)--check(\s|$)", ln) for ln in plan_cmds)
        )
        self.assertTrue(any("PLAY_ANTIBLOCK_CDN" in ln for ln in apply_cmds))
        self.assertFalse(any("--syntax-check" in ln for ln in apply_cmds))
        self.assertIn("PLAY_INBOUNDS", inbounds)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", inbounds)
        self.assertIn("PLAY_NODES", nodes)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", nodes)

    def test_docs_cover_passive_flag_and_out_of_scope(self) -> None:
        self.assertIn("make antiblock-cdn", DOCS)
        self.assertIn("AntiBlock-Squad", DOCS)
        self.assertIn("Default-Squad", DOCS)
        self.assertIn("Hosts", DOCS)
        self.assertIn("HAProxy", DOCS)
        self.assertIn("antiblock_cdn_enabled", DOCS)
        self.assertIn("remnawave_inbound_tags_extra", DOCS)
        self.assertIn("antiblock_cdn_nodes", DOCS)
        self.assertIn("one node = one CDN Resource", DOCS)


if __name__ == "__main__":
    unittest.main()
