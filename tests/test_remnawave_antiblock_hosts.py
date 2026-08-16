#!/usr/bin/env python3
"""Stage 6A/6B regression tests for Remnawave AntiBlock Hosts (current API)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import remnawave_antiblock_hosts as abh  # noqa: E402

ROLE = REPO / "roles/remnawave_antiblock_hosts"
ADD_HOST = REPO / "roles/remnawave_add_host"
PLAY = REPO / "playbooks/antiblock_cdn.yml"
NODES_PLAY = REPO / "playbooks/nodes.yml"
ANTIBLOCK_VARS_PATH = REPO / "inventory/group_vars/all/antiblock_cdn.yml"
GROUP_CDN_NODES = REPO / "inventory/group_vars/antiblock_cdn_nodes.yml"
HOST_DE_FRA_2 = REPO / "inventory/host_vars/de-fra-2/antiblock_cdn.yml"
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
ROLE_TASKS = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
ROLE_DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
ADD_HOST_DEFAULTS = yaml.safe_load((ADD_HOST / "defaults/main.yml").read_text(encoding="utf-8"))
ADD_HOST_MAIN = (ADD_HOST / "tasks/main.yml").read_text(encoding="utf-8")
ADD_HOST_ENSURE = (ADD_HOST / "tasks/ensure_host.yml").read_text(encoding="utf-8")
ANTIBLOCK_VARS = yaml.safe_load(ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8"))
GROUP_CDN = yaml.safe_load(GROUP_CDN_NODES.read_text(encoding="utf-8"))
HOST_DE_FRA_2_VARS = yaml.safe_load(HOST_DE_FRA_2.read_text(encoding="utf-8"))
PLAY_RAW = PLAY.read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts/remnawave_antiblock_hosts.py").read_text(encoding="utf-8")
TRUSTED_POOL = [
    "188.72.111.7",
    "188.72.111.19",
    "188.72.111.35",
    "188.72.103.4",
]
FILTER_PLUGIN = (
    ROLE / "filter_plugins/remnawave_antiblock_hosts.py"
).read_text(encoding="utf-8")

OWNER = "VFF:ANTIBLOCK"
MANAGED = "VFF:MANAGED"
PROFILE = "a281fe1b-d9b6-4874-b34a-2832481cc60f"
INBOUND = "d7340374-7968-4240-9528-8c617af963ee"
NODE = "f5477129-378e-4c0d-830c-b3ed3ce58a7a"
OTHER_NODE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OTHER_INBOUND = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_PROFILE = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PUBLIC_HOSTNAME = "cdn-lab.digitalstreamers.xyz"
REMOVED_IP = "188.72.111.35"

DE_FRA_2_HOSTS = (
    {
        "uuid": "1d3d1b98-59b7-4667-b124-2b219b284b25",
        "remark": "🇩🇪 Germany 2 (xHTTP, CDN)",
        "address": "cdn-lab.digitalstreamers.xyz",
    },
    {
        "uuid": "4cd6140d-ea43-4931-a449-1119dfc3688e",
        "remark": "🇩🇪 Germany 2 (xHTTP, CDN) 2",
        "address": "188.72.111.7",
    },
    {
        "uuid": "be7b8c8b-4f54-4aa2-91bc-c413f9b54921",
        "remark": "🇩🇪 Germany 2 (xHTTP, CDN) 3",
        "address": "188.72.111.19",
    },
    {
        "uuid": "3ab3244d-2bb4-40bf-87ab-9edea5b1c268",
        "remark": "🇩🇪 Germany 2 (xHTTP, CDN) 4",
        "address": "188.72.111.35",
    },
    {
        "uuid": "210e2349-9566-4617-aaf0-4c70ff7edeb2",
        "remark": "🇩🇪 Germany 2 (xHTTP, CDN) 5",
        "address": "188.72.103.4",
    },
)
DE_FRA_2_UUIDS = [item["uuid"] for item in DE_FRA_2_HOSTS]
INVENTORY_FORBIDDEN_UUIDS = DE_FRA_2_UUIDS + [PROFILE, INBOUND, NODE]
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
XHTTP = ANTIBLOCK_VARS["antiblock_cdn_host_xhttp_extra_params"]


def _ctx(**overrides: object) -> dict:
    data = {
        "public_hostname": "cdn-lab.digitalstreamers.xyz",
        "trusted_ingress_ips": [
            "188.72.111.7",
            "188.72.111.19",
            "188.72.111.35",
            "188.72.103.4",
        ],
        "port": 443,
        "path": "/static/main/video/segment.ts/m0ce971085771",
        "sni": "cdn-lab.digitalstreamers.xyz",
        "host": "cdn-lab.digitalstreamers.xyz",
        "alpn": "h2,http/1.1",
        "fingerprint": "firefox",
        "security_layer": "TLS",
        "xhttp_extra_params": XHTTP,
        "owner_tag": OWNER,
        "node_uuid": NODE,
        "profile_uuid": PROFILE,
        "inbound_uuid": INBOUND,
        "inventory_hostname": "de-fra-2",
    }
    data.update(overrides)
    return data


def _desired(**overrides: object) -> list[dict]:
    return abh.build_desired_antiblock_hosts(_ctx(**overrides))


def _scope(**overrides: object) -> dict:
    data = {
        "owner_tag": OWNER,
        "node_uuid": NODE,
        "profile_uuid": PROFILE,
        "inbound_uuid": INBOUND,
        "public_hostname": PUBLIC_HOSTNAME,
    }
    data.update(overrides)
    return data


def _plan(existing: list[dict], desired: list[dict] | None = None, **opts: object):
    kwargs = _scope()
    kwargs.update(opts)
    return abh.plan_antiblock_hosts(desired if desired is not None else _desired(), existing, **kwargs)


def _assert_no_delete(plan: dict) -> None:
    self = unittest.TestCase()
    self.assertEqual(plan["delete"], 0)
    for write in plan.get("writes") or []:
        self.assertNotEqual(str(write.get("method") or "").upper(), "DELETE")
        self.assertIn(str(write.get("method") or "").upper(), {"POST", "PATCH", ""})


def _existing_host(spec: dict, **overrides: object) -> dict:
    host = {
        "uuid": spec["uuid"],
        "remark": spec["remark"],
        "address": spec["address"],
        "port": 443,
        "path": "/static/main/video/segment.ts/m0ce971085771",
        "sni": "cdn-lab.digitalstreamers.xyz",
        "host": "cdn-lab.digitalstreamers.xyz",
        "alpn": "h2,http/1.1",
        "fingerprint": "firefox",
        "securityLayer": "TLS",
        "xhttpExtraParams": dict(XHTTP),
        "tags": [],
        "isDisabled": False,
        "isHidden": False,
        "overrideSniFromAddress": False,
        "keepSniBlank": False,
        "shuffleHost": False,
        "mihomoX25519": False,
        "nodes": [NODE],
        "inbound": {
            "configProfileUuid": PROFILE,
            "configProfileInboundUuid": INBOUND,
        },
    }
    host.update(overrides)
    return host


def _de_fra_2_existing(**overrides: object) -> list[dict]:
    return [_existing_host(spec, **overrides) for spec in DE_FRA_2_HOSTS]


def _include(play: dict, role_name: str) -> dict:
    for task in play.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        include = task.get("ansible.builtin.include_role") or task.get("include_role") or {}
        if include.get("name") == role_name and "Hosts" in str(task.get("name")):
            return task
    raise AssertionError(f"missing include_role {role_name}")


class CurrentApiFieldTests(unittest.TestCase):
    def test_01_tags_never_singular_tag(self) -> None:
        payload = abh.build_create_payload(_desired()[0], owner_tag=OWNER)
        self.assertIn("tags", payload)
        self.assertIsInstance(payload["tags"], list)
        self.assertNotIn("tag", payload)
        self.assertEqual(payload["tags"], [OWNER])

    def test_02_xhttp_extra_params_current_casing(self) -> None:
        payload = abh.build_create_payload(_desired()[0], owner_tag=OWNER)
        self.assertIn("xhttpExtraParams", payload)
        self.assertNotIn("xHttpExtraParams", payload)
        self.assertNotIn("XHttpExtraParams", payload)
        for path in (ROLE / "tasks/main.yml", ROLE / "defaults/main.yml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            dumped = yaml.dump(data)
            self.assertNotIn("xHttpExtraParams", dumped)
            self.assertNotIn("XHttpExtraParams", dumped)
        vars_dump = yaml.dump(ANTIBLOCK_VARS)
        self.assertIn("xhttpExtraParams", ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("xHttpExtraParams:", vars_dump)
        self.assertNotIn("XHttpExtraParams:", vars_dump)

    def test_03_exact_uplink_http_method(self) -> None:
        self.assertEqual(XHTTP["uplinkHTTPMethod"], "GET")
        payload = abh.build_create_payload(_desired()[0], owner_tag=OWNER)
        self.assertEqual(payload["xhttpExtraParams"]["uplinkHTTPMethod"], "GET")
        with self.assertRaises(ValueError):
            abh.assert_current_api_payload(
                {"uuid": "x", "xhttpExtraParams": {"uplinkHTTPMethod": "POST"}}
            )


class TagMergeTests(unittest.TestCase):
    def test_04_empty_tags_become_owner(self) -> None:
        self.assertEqual(abh.merge_owner_tags([], OWNER), [OWNER])
        plan = abh.plan_antiblock_hosts(_desired(), _de_fra_2_existing(), owner_tag=OWNER)
        self.assertEqual(plan["adopt"], 5)
        for item in plan["items"]:
            self.assertEqual(item["drift_fields"], ["tags"])
            self.assertEqual(item["desired_tags"], [OWNER])

    def test_05_existing_foo_keeps_foo_and_appends_owner(self) -> None:
        self.assertEqual(abh.merge_owner_tags(["FOO"], OWNER), ["FOO", OWNER])
        existing = [_existing_host(DE_FRA_2_HOSTS[0], tags=["FOO"])]
        plan = abh.plan_antiblock_hosts([_desired()[0]], existing, owner_tag=OWNER)
        self.assertEqual(plan["items"][0]["desired_tags"], ["FOO", OWNER])
        self.assertEqual(plan["items"][0]["action"], "adopt")

    def test_06_owner_already_present_no_tag_drift(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        plan = abh.plan_antiblock_hosts(_desired(), existing, owner_tag=OWNER)
        self.assertEqual(plan["update"], 0)
        self.assertEqual(plan["adopt"], 0)
        for item in plan["items"]:
            self.assertEqual(item["action"], "noop")
            self.assertEqual(item["drift_fields"], [])

    def test_07_preserve_tag_order_and_unrelated(self) -> None:
        self.assertEqual(
            abh.merge_owner_tags(["Z", "FOO", OWNER, "BAR"], OWNER),
            ["Z", "FOO", OWNER, "BAR"],
        )
        existing = [_existing_host(DE_FRA_2_HOSTS[0], tags=["Z", "FOO", OWNER, "BAR"])]
        plan = abh.plan_antiblock_hosts([_desired()[0]], existing, owner_tag=OWNER)
        self.assertEqual(plan["items"][0]["action"], "noop")
        self.assertEqual(plan["items"][0]["desired_tags"], ["Z", "FOO", OWNER, "BAR"])


class MatchIdentityTests(unittest.TestCase):
    def test_08_safe_endpoint_inbound_matching(self) -> None:
        desired = _desired()
        existing = _de_fra_2_existing()
        for want, got in zip(desired, existing):
            cands = abh.select_identity_candidates(existing, want)
            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0]["uuid"], got["uuid"])

    def test_09_no_address_port_only_adoption(self) -> None:
        desired = [_desired()[0]]
        decoy = _existing_host(
            DE_FRA_2_HOSTS[0],
            uuid="99999999-9999-4999-8999-999999999999",
            inbound={
                "configProfileUuid": OTHER_PROFILE,
                "configProfileInboundUuid": OTHER_INBOUND,
            },
        )
        existing = [decoy]
        self.assertEqual(len(abh.select_address_port_candidates(existing, desired[0])), 1)
        self.assertEqual(abh.select_identity_candidates(existing, desired[0]), [])
        plan = abh.plan_antiblock_hosts(desired, existing, owner_tag=OWNER)
        self.assertEqual(plan["create"], 1)
        self.assertEqual(plan["matched"], 0)
        self.assertIsNone(plan["items"][0]["uuid"])

    def test_10_ambiguous_match_fails(self) -> None:
        desired = [_desired()[0]]
        existing = [
            _existing_host(DE_FRA_2_HOSTS[0]),
            _existing_host(DE_FRA_2_HOSTS[0], uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ]
        plan = abh.plan_antiblock_hosts(desired, existing, owner_tag=OWNER, allow_writes=True)
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["ambiguous"], 1)
        self.assertEqual(plan["writes"], [])
        self.assertIn("Ambiguous", plan["error"] or "")
        self.assertIn("Refusing to pick first or create", plan["error"] or "")
        self.assertEqual(plan["create"], 0)
        self.assertEqual(plan["writes"], [])


class AdoptionSafetyTests(unittest.TestCase):
    def test_11_unmanaged_exact_transport_tags_only(self) -> None:
        plan = abh.plan_antiblock_hosts(
            _desired(),
            _de_fra_2_existing(),
            owner_tag=OWNER,
            allow_writes=True,
        )
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["adopt"], 5)
        self.assertEqual(len(plan["writes"]), 5)
        for write, spec in zip(plan["writes"], DE_FRA_2_HOSTS):
            self.assertEqual(write["method"], "PATCH")
            self.assertEqual(write["path"], "/api/hosts")
            self.assertEqual(write["body"], {"uuid": spec["uuid"], "tags": [OWNER]})
            self.assertEqual(set(write["body"]), {"uuid", "tags"})
            for forbidden in (
                "remark",
                "address",
                "path",
                "sni",
                "host",
                "alpn",
                "securityLayer",
                "xhttpExtraParams",
                "nodes",
                "inbound",
            ):
                self.assertNotIn(forbidden, write["body"])

    def test_12_unmanaged_transport_drift_fails_no_patch(self) -> None:
        existing = _de_fra_2_existing()
        existing[0]["path"] = "/other"
        plan = abh.plan_antiblock_hosts(
            _desired(),
            existing,
            owner_tag=OWNER,
            allow_writes=True,
        )
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["writes"], [])
        self.assertEqual(plan["items"][0]["action"], "unmanaged_transport_drift")
        self.assertIn("path", plan["items"][0]["drift_fields"])
        self.assertIn("Refusing to mutate unmanaged", plan["error"] or "")

    def test_13_managed_transport_drift_partial_patch(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[0]["path"] = "/old"
        existing[0]["fingerprint"] = "chrome"
        plan = abh.plan_antiblock_hosts(
            [_desired()[0]],
            [existing[0]],
            owner_tag=OWNER,
            allow_writes=True,
        )
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["adopt"], 0)
        self.assertEqual(plan["update"], 1)
        write = plan["writes"][0]
        self.assertEqual(write["method"], "PATCH")
        self.assertEqual(set(write["body"]), {"uuid", "path", "fingerprint"})
        self.assertEqual(write["body"]["path"], _desired()[0]["path"])
        self.assertEqual(write["drift_fields"], ["path", "fingerprint"])
        self.assertNotIn("remark", write["body"])
        self.assertNotIn("xhttpExtraParams", write["body"])


class DeFra2FixtureTests(unittest.TestCase):
    def test_14_fixture_matched_five_no_create_delete(self) -> None:
        plan = abh.plan_antiblock_hosts(_desired(), _de_fra_2_existing(), owner_tag=OWNER)
        self.assertEqual(plan["desired"], 5)
        self.assertEqual(plan["matched"], 5)
        self.assertEqual(plan["create"], 0)
        self.assertEqual(plan["delete"], 0)
        self.assertEqual(plan["ambiguous"], 0)
        self.assertEqual(plan["adopt"], 5)
        self.assertEqual(plan["update"], 5)
        self.assertEqual(
            plan["summary"],
            "desired=5 matched=5 create=0 update=5 adopt=5 stale=0 "
            "prune_eligible=0 prune_blocked=0 delete=0 ambiguous=0",
        )
        for item in plan["items"]:
            self.assertEqual(item["drift_fields"], ["tags"])
            self.assertEqual(item["existing_remark"], next(
                spec["remark"] for spec in DE_FRA_2_HOSTS if spec["uuid"] == item["uuid"]
            ))

    def test_15_exact_five_uuid_preservation(self) -> None:
        existing = _de_fra_2_existing()
        plan = abh.plan_antiblock_hosts(_desired(), existing, owner_tag=OWNER)
        self.assertEqual([item["uuid"] for item in plan["items"]], DE_FRA_2_UUIDS)
        adopted = [{**host, "tags": [OWNER]} for host in existing]
        verify = abh.verify_antiblock_hosts(
            _desired(),
            adopted,
            owner_tag=OWNER,
            expected_uuids=DE_FRA_2_UUIDS,
        )
        self.assertTrue(verify["ok"], verify["errors"])
        self.assertEqual(verify["uuids"], DE_FRA_2_UUIDS)


class CreateAndEqualityTests(unittest.TestCase):
    def test_16_create_payload_current_api(self) -> None:
        payload = abh.build_create_payload(_desired()[0], owner_tag=OWNER)
        for field in abh.CREATE_FIELDS:
            self.assertIn(field, payload)
        for legacy in abh.LEGACY_PAYLOAD_KEYS:
            self.assertNotIn(legacy, payload)
        self.assertEqual(payload["tags"], [OWNER])
        self.assertEqual(payload["nodes"], [NODE])
        self.assertEqual(
            payload["inbound"],
            {"configProfileUuid": PROFILE, "configProfileInboundUuid": INBOUND},
        )
        plan = abh.plan_antiblock_hosts(_desired(), [], owner_tag=OWNER, allow_writes=True)
        self.assertEqual(plan["create"], 5)
        self.assertEqual(plan["matched"], 0)
        self.assertEqual(len(plan["writes"]), 5)
        for write in plan["writes"]:
            self.assertEqual(write["method"], "POST")
            self.assertEqual(write["path"], "/api/hosts")
            abh.assert_current_api_payload(write["body"], kind="create")

    def test_17_xhttp_semantic_equality(self) -> None:
        left = dict(XHTTP)
        right = dict(XHTTP)
        right["scMinPostsIntervalMs"] = 30
        right["scMaxBufferedPosts"] = 100
        self.assertTrue(abh.xhttp_params_equal(left, right))
        self.assertTrue(abh.xhttp_params_equal(left, json_dumps := __import__("json").dumps(left)))
        drifted = dict(XHTTP)
        drifted["uplinkHTTPMethod"] = "POST"
        self.assertFalse(abh.xhttp_params_equal(left, drifted))
        existing = _de_fra_2_existing()
        existing[0]["xhttpExtraParams"] = {"scMinPostsIntervalMs": 30, **{
            k: v for k, v in XHTTP.items() if k != "scMinPostsIntervalMs"
        }}
        plan = abh.plan_antiblock_hosts([_desired()[0]], [existing[0]], owner_tag=OWNER)
        self.assertEqual(plan["items"][0]["action"], "adopt")


class PlanPruneOwnershipTests(unittest.TestCase):
    def test_18_plan_mode_zero_writes(self) -> None:
        plan = abh.plan_antiblock_hosts(
            _desired(),
            _de_fra_2_existing(),
            owner_tag=OWNER,
            allow_writes=False,
        )
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["adopt"], 5)
        self.assertEqual(plan["writes"], [])
        self.assertFalse(plan["allow_writes"])

    def test_19_prune_false_no_delete(self) -> None:
        plan = abh.plan_antiblock_hosts(_desired(), _de_fra_2_existing(), owner_tag=OWNER)
        self.assertEqual(plan["delete"], 0)
        self.assertFalse(plan["prune"])
        self.assertEqual(plan["delete_items"], [])
        self.assertIn("antiblock_cdn_hosts_prune", ROLE_TASKS)
        zero = abh.plan_antiblock_hosts(
            _desired(),
            _de_fra_2_existing(tags=[OWNER]),
            owner_tag=OWNER,
            prune=True,
        )
        self.assertTrue(zero["prune"])
        self.assertEqual(zero["delete"], 0)
        self.assertEqual(zero["delete_items"], [])

    def test_20_vff_managed_is_never_antiblock_ownership(self) -> None:
        host = _existing_host(DE_FRA_2_HOSTS[0], tags=[MANAGED])
        self.assertFalse(abh.is_antiblock_owned(host, OWNER))
        self.assertTrue(abh.is_antiblock_owned({**host, "tags": [MANAGED, OWNER]}, OWNER))
        plan = abh.plan_antiblock_hosts([_desired()[0]], [host], owner_tag=OWNER, allow_writes=True)
        self.assertEqual(plan["items"][0]["action"], "adopt")
        self.assertEqual(plan["writes"][0]["body"]["tags"], [MANAGED, OWNER])
        self.assertEqual(ROLE_DEFAULTS["antiblock_cdn_host_owner_tag"], OWNER)
        self.assertNotEqual(ROLE_DEFAULTS["antiblock_cdn_host_owner_tag"], MANAGED)
        self.assertEqual(ADD_HOST_DEFAULTS["rw_host_managed_tag"], MANAGED)


class OrdinaryAddHostUnchangedTests(unittest.TestCase):
    def test_21_ordinary_add_host_and_make_nodes_unchanged(self) -> None:
        nodes = NODES_PLAY.read_text(encoding="utf-8")
        self.assertIn("remnawave_add_host", nodes)
        self.assertNotIn("remnawave_antiblock_hosts", nodes)
        self.assertNotIn("antiblock_cdn_hosts", nodes)
        self.assertNotIn("VFF:ANTIBLOCK", ADD_HOST_MAIN)
        self.assertNotIn("VFF:ANTIBLOCK", ADD_HOST_ENSURE)
        self.assertIn("rw_host_managed_tag", ADD_HOST_ENSURE)
        self.assertIn("allowInsecure", ADD_HOST_MAIN)
        self.assertEqual(ADD_HOST_DEFAULTS["rw_host_tag"], "PROD")
        nodes_make = MAKEFILE[MAKEFILE.find("nodes:") : MAKEFILE.find("hosts-audit:")]
        self.assertNotIn("antiblock_cdn_hosts", nodes_make)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", nodes_make)


class IncludeRoleTagsTests(unittest.TestCase):
    def test_22_include_role_apply_tags_propagation(self) -> None:
        plays = yaml.safe_load(PLAY_RAW)
        hosts_task = _include(plays[1], "remnawave_antiblock_hosts")
        apply_tags = hosts_task["ansible.builtin.include_role"]["apply"]["tags"]
        self.assertEqual(
            apply_tags,
            ["antiblock_cdn", "antiblock_cdn_nodes", "antiblock_cdn_hosts"],
        )
        self.assertIn("antiblock_cdn_hosts", hosts_task["tags"])
        self.assertIn("apply:", ROLE_TASKS)
        self.assertIn("name: remnawave_inbounds_cache", ROLE_TASKS)
        cache_block = ROLE_TASKS.split("Ensure inbound cache")[1].split("Resolve inbound")[0]
        self.assertIn("antiblock_cdn_hosts", cache_block)
        self.assertIn("antiblock_cdn_nodes", cache_block)
        self.assertIn("apply:", cache_block)
        for task in plays[1].get("tasks") or []:
            name = str(task.get("name"))
            tags = task.get("tags") or []
            include = task.get("ansible.builtin.include_role") or {}
            apply = (include.get("apply") or {}).get("tags") or []
            if "Hosts" in name:
                continue
            self.assertNotIn("antiblock_cdn_hosts", tags, name)
            self.assertNotIn("antiblock_cdn_hosts", apply, name)


class InventoryAndRoleContractTests(unittest.TestCase):
    def test_inventory_has_no_hardcoded_uuids(self) -> None:
        for path in (ANTIBLOCK_VARS_PATH, GROUP_CDN_NODES, HOST_DE_FRA_2, PLAY, ROLE / "defaults/main.yml"):
            raw = path.read_text(encoding="utf-8")
            for uuid in INVENTORY_FORBIDDEN_UUIDS:
                self.assertNotIn(uuid, raw, path)
            self.assertIsNone(UUID_RE.search(raw), path)

    def test_shared_xhttp_object_not_copied_per_host(self) -> None:
        raw = ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8")
        self.assertEqual(raw.count("uplinkHTTPMethod"), 1)
        self.assertEqual(raw.count("antiblock_cdn_host_xhttp_extra_params"), 1)
        self.assertFalse(ROLE_DEFAULTS["antiblock_cdn_hosts_allow_writes"])
        self.assertFalse(ROLE_DEFAULTS["antiblock_cdn_hosts_prune"])
        self.assertFalse(ANTIBLOCK_VARS["antiblock_cdn_hosts_allow_writes"])
        self.assertFalse(ANTIBLOCK_VARS["antiblock_cdn_hosts_prune"])
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_host_owner_tag"], OWNER)

    def test_desired_addresses_hostname_then_trusted_pool(self) -> None:
        desired = _desired()
        self.assertEqual(
            [item["address"] for item in desired],
            ["cdn-lab.digitalstreamers.xyz", *TRUSTED_POOL],
        )
        self.assertTrue(all(item["port"] == 443 for item in desired))
        self.assertTrue(all(item["sni"] == "cdn-lab.digitalstreamers.xyz" for item in desired))

    def test_makefile_documents_hosts_tag_and_plan_override(self) -> None:
        node = MAKEFILE[MAKEFILE.find("antiblock-cdn-node:") : MAKEFILE.find("antiblock-cdn-node-plan:")]
        self.assertIn("TAGS=antiblock_cdn_hosts", node)
        self.assertIn("antiblock_cdn_hosts_allow_writes=false", node)
        self.assertIn("antiblock_cdn_hosts_prune=true", node)
        self.assertNotIn("remnawave_add_host", node)

    def test_second_plan_after_adopt_is_noop(self) -> None:
        adopted = _de_fra_2_existing(tags=[OWNER])
        plan = abh.plan_antiblock_hosts(_desired(), adopted, owner_tag=OWNER, allow_writes=True)
        self.assertEqual(plan["update"], 0)
        self.assertEqual(plan["adopt"], 0)
        self.assertEqual(plan["writes"], [])
        self.assertEqual(
            plan["summary"],
            "desired=5 matched=5 create=0 update=0 adopt=0 stale=0 "
            "prune_eligible=0 prune_blocked=0 delete=0 ambiguous=0",
        )

    def test_empty_tags_are_not_owned(self) -> None:
        self.assertFalse(abh.is_antiblock_owned({"tags": []}, OWNER))
        self.assertFalse(abh.is_antiblock_owned({"tag": OWNER}, OWNER))


def _repo_files_containing(needle: str) -> list[str]:
    skip_dirs = {".git", ".venv", ".ansible", "__pycache__", "node_modules"}
    suffixes = {".yml", ".yaml", ".py", ".md", ".j2"}
    hits: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix not in suffixes and path.name != "Makefile":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle in text:
            hits.append(str(path.relative_to(REPO)))
    return hits


class TrustedIngressPoolTests(unittest.TestCase):
    def test_01_global_source_of_truth_name(self) -> None:
        self.assertEqual(ANTIBLOCK_VARS["antiblock_cdn_trusted_ingress_ips"], TRUSTED_POOL)
        self.assertNotIn("antiblock_cdn_ingress_ips", ANTIBLOCK_VARS)
        self.assertIn("antiblock_cdn_trusted_ingress_ips", ROLE_TASKS)
        self.assertIn("trusted_ingress_ips", ROLE_TASKS)
        self.assertIn("remnawave_antiblock_trusted_ingress_ips", ROLE_TASKS)

    def test_02_old_ingress_ips_name_unused(self) -> None:
        leftovers = [
            path
            for path in _repo_files_containing("antiblock_cdn_ingress_ips")
            if path != "tests/test_remnawave_antiblock_hosts.py"
        ]
        self.assertEqual(leftovers, [])
        self.assertNotIn("antiblock_cdn_ingress_ips", ROLE_TASKS)
        with self.assertRaises(ValueError) as ctx:
            _desired(ingress_ips=TRUSTED_POOL)
        self.assertIn("trusted_ingress_ips", str(ctx.exception))

    def test_03_de_fra_2_desired_addresses_exact(self) -> None:
        self.assertEqual(
            HOST_DE_FRA_2_VARS["antiblock_cdn_node"]["public_hostname"],
            "cdn-lab.digitalstreamers.xyz",
        )
        self.assertNotIn("antiblock_cdn_trusted_ingress_ips", HOST_DE_FRA_2_VARS)
        self.assertEqual(
            [item["address"] for item in _desired()],
            [
                "cdn-lab.digitalstreamers.xyz",
                "188.72.111.7",
                "188.72.111.19",
                "188.72.111.35",
                "188.72.103.4",
            ],
        )

    def test_04_generic_node_uses_derived_hostname_and_central_pool(self) -> None:
        self.assertEqual(
            GROUP_CDN["antiblock_cdn_node"]["public_hostname"],
            "{{ inventory_hostname }}.cdn.digitalstreamers.xyz",
        )
        self.assertNotIn("antiblock_cdn_trusted_ingress_ips", GROUP_CDN)
        desired = _desired(
            public_hostname="de-fra-3.cdn.digitalstreamers.xyz",
            sni="de-fra-3.cdn.digitalstreamers.xyz",
            host="de-fra-3.cdn.digitalstreamers.xyz",
            inventory_hostname="de-fra-3",
            trusted_ingress_ips=ANTIBLOCK_VARS["antiblock_cdn_trusted_ingress_ips"],
        )
        self.assertEqual(
            [item["address"] for item in desired],
            ["de-fra-3.cdn.digitalstreamers.xyz", *TRUSTED_POOL],
        )

    def test_05_duplicate_ip_fails(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            abh.validate_trusted_ingress_ips(["188.72.111.7", "188.72.111.7"])
        self.assertIn("duplicate", str(ctx.exception))
        with self.assertRaises(ValueError):
            _desired(trusted_ingress_ips=["188.72.111.7", "188.72.111.19", "188.72.111.7"])

    def test_06_invalid_ipv4_fails(self) -> None:
        for bad in ("cdn-lab.digitalstreamers.xyz", "188.72.111", "2001:db8::1", "not-an-ip"):
            with self.assertRaises(ValueError, msg=bad):
                abh.validate_trusted_ingress_ips([bad])

    def test_07_empty_pool_fails(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            abh.validate_trusted_ingress_ips([])
        self.assertIn("empty", str(ctx.exception))
        with self.assertRaises(ValueError):
            abh.validate_trusted_ingress_ips(None)
        with self.assertRaises(ValueError):
            _desired(trusted_ingress_ips=[])

    def test_08_order_preserved(self) -> None:
        self.assertEqual(
            abh.validate_trusted_ingress_ips(list(TRUSTED_POOL)),
            TRUSTED_POOL,
        )
        desired = _desired(trusted_ingress_ips=TRUSTED_POOL)
        self.assertEqual([item["address"] for item in desired][1:], TRUSTED_POOL)

    def test_09_no_providercname_or_dns_discovery(self) -> None:
        for blob in (ROLE_TASKS, SCRIPT, FILTER_PLUGIN):
            self.assertNotIn("providerCname", blob)
            self.assertNotIn("provider_cname", blob)
            self.assertNotIn("getaddrinfo", blob)
            self.assertNotIn("gethostbyname", blob)
            self.assertNotIn("dns.resolver", blob)
        self.assertIn("curated", ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8").lower())

    def test_10_prune_remains_disabled(self) -> None:
        self.assertFalse(ANTIBLOCK_VARS["antiblock_cdn_hosts_prune"])
        self.assertFalse(ROLE_DEFAULTS["antiblock_cdn_hosts_prune"])
        self.assertNotIn("antiblock_cdn_hosts_allow_delete", ROLE_TASKS)
        adopted = _de_fra_2_existing(tags=[OWNER])
        plan = abh.plan_antiblock_hosts(_desired(), adopted, owner_tag=OWNER)
        self.assertEqual(plan["delete"], 0)
        self.assertEqual(plan["update"], 0)
        self.assertEqual(
            plan["summary"],
            "desired=5 matched=5 create=0 update=0 adopt=0 stale=0 "
            "prune_eligible=0 prune_blocked=0 delete=0 ambiguous=0",
        )


class StalePrunePlanTests(unittest.TestCase):
    def test_01_de_fra_2_stale_zero(self) -> None:
        plan = _plan(_de_fra_2_existing(tags=[OWNER]))
        self.assertEqual(plan["desired"], 5)
        self.assertEqual(plan["matched"], 5)
        self.assertEqual(plan["stale"], 0)
        self.assertEqual(plan["prune_eligible"], 0)
        self.assertEqual(plan["prune_blocked"], 0)
        self.assertEqual(plan["stale_items"], [])
        _assert_no_delete(plan)
        self.assertIn("stale=0", plan["summary"])

    def test_02_removed_trusted_ip_is_prune_eligible_no_delete(self) -> None:
        pool = [ip for ip in TRUSTED_POOL if ip != REMOVED_IP]
        desired = _desired(trusted_ingress_ips=pool)
        existing = _de_fra_2_existing(tags=[OWNER])
        plan = _plan(existing, desired)
        self.assertEqual(plan["desired"], 4)
        self.assertEqual(plan["matched"], 4)
        self.assertEqual(plan["create"], 0)
        self.assertEqual(plan["update"], 0)
        self.assertEqual(plan["adopt"], 0)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_eligible"], 1)
        self.assertEqual(plan["prune_blocked"], 0)
        _assert_no_delete(plan)
        self.assertEqual(plan["writes"], [])
        stale = plan["stale_items"][0]
        self.assertEqual(stale["address"], REMOVED_IP)
        self.assertTrue(stale["prune_eligible"])
        self.assertIsNone(stale["block_reason"])

        written = _plan(existing, desired, allow_writes=True)
        self.assertEqual(written["stale"], 1)
        self.assertEqual(written["prune_eligible"], 1)
        _assert_no_delete(written)
        self.assertEqual(written["writes"], [])

    def test_03_empty_tags_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = []
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 0)

    def test_04_vff_managed_only_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = [MANAGED]
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 0)
        self.assertFalse(abh.is_antiblock_owned(existing[3], OWNER))

    def test_05_antiblock_plus_managed_is_blocked(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = [OWNER, MANAGED]
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_eligible"], 0)
        self.assertEqual(plan["prune_blocked"], 1)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "extra_tags")
        _assert_no_delete(plan)

    def test_06_extra_foo_tag_is_blocked(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = [OWNER, "FOO"]
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_blocked"], 1)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "extra_tags")

    def test_07_other_node_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["nodes"] = [OTHER_NODE]
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 0)

    def test_08_current_plus_other_node_blocked(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["nodes"] = [NODE, OTHER_NODE]
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_eligible"], 0)
        self.assertEqual(plan["prune_blocked"], 1)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "multiple_nodes")
        _assert_no_delete(plan)

    def test_09_different_inbound_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["inbound"] = {
            "configProfileUuid": PROFILE,
            "configProfileInboundUuid": OTHER_INBOUND,
        }
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 0)

    def test_10_different_profile_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["inbound"] = {
            "configProfileUuid": OTHER_PROFILE,
            "configProfileInboundUuid": INBOUND,
        }
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 0)

    def test_11_public_hostname_never_eligible(self) -> None:
        desired = _desired(trusted_ingress_ips=TRUSTED_POOL)
        existing = _de_fra_2_existing(tags=[OWNER])
        # Drop hostname from desired while leaving the owned hostname Host.
        desired = [item for item in desired if item["address"] != PUBLIC_HOSTNAME]
        plan = _plan(existing, desired)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["stale_items"][0]["address"], PUBLIC_HOSTNAME)
        self.assertFalse(plan["stale_items"][0]["prune_eligible"])
        self.assertEqual(plan["stale_items"][0]["block_reason"], "public_hostname")
        _assert_no_delete(plan)

    def test_12_non_ipv4_never_eligible(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "edge-extra.digitalstreamers.xyz"
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 1)
        self.assertFalse(plan["stale_items"][0]["prune_eligible"])
        self.assertEqual(plan["stale_items"][0]["block_reason"], "non_ipv4_address")

    def test_13_missing_uuid_blocked(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["uuid"] = ""
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "missing_uuid")
        self.assertFalse(plan["stale_items"][0]["prune_eligible"])

    def test_14_safe_identity_not_address_port_only(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        decoy = _existing_host(
            {"uuid": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "remark": "decoy", "address": REMOVED_IP},
            tags=[OWNER],
            inbound={
                "configProfileUuid": PROFILE,
                "configProfileInboundUuid": OTHER_INBOUND,
            },
        )
        existing.append(decoy)
        pool = [ip for ip in TRUSTED_POOL if ip != REMOVED_IP]
        plan = _plan(existing, _desired(trusted_ingress_ips=pool))
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["stale_items"][0]["address"], REMOVED_IP)
        self.assertEqual(plan["stale_items"][0]["uuid"], DE_FRA_2_HOSTS[3]["uuid"])

    def test_15_wrong_port_is_stale_identity_no_delete(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["port"] = 8443
        plan = _plan(existing, _desired(), allow_writes=True)
        self.assertEqual(plan["desired"], 5)
        self.assertEqual(plan["matched"], 4)
        self.assertEqual(plan["create"], 1)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["stale_items"][0]["address"], REMOVED_IP)
        self.assertEqual(plan["stale_items"][0]["port"], 8443)
        self.assertTrue(plan["stale_items"][0]["prune_eligible"])
        _assert_no_delete(plan)
        self.assertEqual([write["method"] for write in plan["writes"]], ["POST"])

    def test_16_vff_managed_never_prune_ownership(self) -> None:
        existing = _de_fra_2_existing(tags=[MANAGED])
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired())
        self.assertEqual(plan["stale"], 0)
        self.assertEqual(ROLE_DEFAULTS["antiblock_cdn_host_owner_tag"], OWNER)
        self.assertEqual(ADD_HOST_DEFAULTS["rw_host_managed_tag"], MANAGED)

    def test_17_writes_collection_never_contains_delete(self) -> None:
        self.assertIn("writes must never include DELETE", SCRIPT)
        self.assertIn("Refuse any DELETE write", ROLE_TASKS)
        self.assertIn("selectattr('method', 'equalto', 'DELETE')", ROLE_TASKS)
        pool = [ip for ip in TRUSTED_POOL if ip != REMOVED_IP]
        plan = _plan(
            _de_fra_2_existing(tags=[OWNER]),
            _desired(trusted_ingress_ips=pool),
            allow_writes=True,
            prune=True,
        )
        self.assertEqual(plan["delete"], 1)
        self.assertTrue(all(write["method"] in {"POST", "PATCH"} for write in plan["writes"]))
        self.assertEqual(plan["writes"], [])

    def test_18_allow_writes_true_still_no_delete(self) -> None:
        pool = [ip for ip in TRUSTED_POOL if ip != REMOVED_IP]
        plan = _plan(
            _de_fra_2_existing(tags=[OWNER]),
            _desired(trusted_ingress_ips=pool),
            allow_writes=True,
        )
        self.assertEqual(plan["prune_eligible"], 1)
        _assert_no_delete(plan)
        self.assertTrue(all(write["method"] in {"POST", "PATCH"} for write in plan["writes"]))

    def test_19_stage_6a_create_adopt_update_unchanged(self) -> None:
        adopt = _plan(_de_fra_2_existing(), allow_writes=True)
        self.assertEqual(adopt["adopt"], 5)
        self.assertEqual(adopt["create"], 0)
        self.assertEqual([write["method"] for write in adopt["writes"]], ["PATCH"] * 5)
        create = _plan([], allow_writes=True)
        self.assertEqual(create["create"], 5)
        self.assertEqual([write["method"] for write in create["writes"]], ["POST"] * 5)
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[0]["path"] = "/old"
        update = _plan([existing[0]], [_desired()[0]], allow_writes=True)
        self.assertEqual(update["update"], 1)
        self.assertEqual(update["writes"][0]["method"], "PATCH")
        _assert_no_delete(adopt)
        _assert_no_delete(create)
        _assert_no_delete(update)

    def test_20_ordinary_add_host_untouched(self) -> None:
        self.assertNotIn("VFF:ANTIBLOCK", ADD_HOST_MAIN)
        self.assertNotIn("stale_items", ADD_HOST_MAIN)
        self.assertNotIn("antiblock_cdn_hosts", NODES_PLAY.read_text(encoding="utf-8"))


NEW_IP = "198.51.100.20"


def _removed_ip_desired() -> list[dict]:
    return _desired(trusted_ingress_ips=[ip for ip in TRUSTED_POOL if ip != REMOVED_IP])


def _replaced_ip_desired() -> list[dict]:
    pool = [NEW_IP if ip == REMOVED_IP else ip for ip in TRUSTED_POOL]
    return _desired(trusted_ingress_ips=pool)


def _task_block(source: str, name: str) -> str:
    marker = f"- name: {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing task: {name}")
    rest = source[start:]
    nxt = rest.find("\n- name:", len(marker))
    return rest if nxt < 0 else rest[:nxt]


class ApplyFailure(Exception):
    """Simulator stop before or during DELETE."""


def _apply_writes(hosts: list[dict], writes: list[dict]) -> list[dict]:
    result = [dict(host) for host in hosts]
    for write in writes:
        method = str(write.get("method") or "").upper()
        body = dict(write.get("body") or {})
        if method == "DELETE":
            raise AssertionError("writes must not contain DELETE")
        if method == "POST":
            created = dict(body)
            created.setdefault("uuid", f"created-{created.get('address')}")
            result.append(created)
            continue
        if method == "PATCH":
            uuid = body.get("uuid")
            for host in result:
                if host.get("uuid") == uuid:
                    host.update({key: value for key, value in body.items() if key != "uuid"})
    return result


def _simulate_run(
    existing: list[dict],
    desired: list[dict],
    *,
    allow_writes: bool,
    prune: bool,
    fail_writes: bool = False,
    fail_verify: bool = False,
    fail_delete_at: int | None = None,
) -> dict:
    hosts = [dict(item) for item in existing]
    plan = _plan(hosts, desired, allow_writes=allow_writes, prune=prune)
    mutations: list[dict] = []
    deleted: list[str] = []
    verified_before_delete = False
    failed = None

    if allow_writes and plan["writes"]:
        if fail_writes:
            return {
                "plan": plan,
                "hosts": hosts,
                "mutations": mutations,
                "deleted": deleted,
                "verified_before_delete": False,
                "failed": "writes",
                "final_plan": None,
                "final_verify": None,
                "deleted_verify": None,
            }
        hosts = _apply_writes(hosts, plan["writes"])
        mutations.extend(
            {
                "method": write["method"],
                "path": write.get("path"),
                "address": (write.get("body") or {}).get("address"),
            }
            for write in plan["writes"]
        )

    need_verify = bool(allow_writes and (plan["writes"] or (prune and plan["delete_items"])))
    if need_verify:
        verify = abh.verify_antiblock_hosts(desired, hosts, owner_tag=OWNER)
        verified_before_delete = True
        if fail_verify or not verify["ok"]:
            return {
                "plan": plan,
                "hosts": hosts,
                "mutations": mutations,
                "deleted": deleted,
                "verified_before_delete": True,
                "failed": "verify",
                "final_plan": None,
                "final_verify": verify,
                "deleted_verify": None,
            }

    if allow_writes and prune and plan["delete_items"]:
        if not verified_before_delete:
            raise ApplyFailure("DELETE without desired verify")
        for index, item in enumerate(plan["delete_items"]):
            if fail_delete_at is not None and index >= fail_delete_at:
                failed = "delete"
                break
            abh.assert_delete_item_invariants(
                item,
                owner_tag=OWNER,
                node_uuid=NODE,
                public_hostname=PUBLIC_HOSTNAME,
            )
            hosts = [host for host in hosts if str(host.get("uuid") or "") != item["uuid"]]
            deleted.append(item["uuid"])
            mutations.append(
                {
                    "method": "DELETE",
                    "path": item["path"],
                    "uuid": item["uuid"],
                    "address": item["address"],
                }
            )

    final_verify = abh.verify_antiblock_hosts(desired, hosts, owner_tag=OWNER)
    deleted_verify = abh.verify_deleted_uuids_absent(hosts, plan["delete_items"] if failed != "delete" else [
        item for item in plan["delete_items"] if item["uuid"] in deleted
    ])
    final_plan = _plan(hosts, desired, allow_writes=False, prune=prune)
    return {
        "plan": plan,
        "hosts": hosts,
        "mutations": mutations,
        "deleted": deleted,
        "verified_before_delete": verified_before_delete,
        "failed": failed,
        "final_plan": final_plan,
        "final_verify": final_verify,
        "deleted_verify": deleted_verify,
    }


class GuardedDeleteTests(unittest.TestCase):
    def test_01_prune_false_delete_zero(self) -> None:
        plan = _plan(_de_fra_2_existing(tags=[OWNER]), _removed_ip_desired(), prune=False)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_eligible"], 1)
        self.assertEqual(plan["delete"], 0)
        self.assertEqual(plan["delete_items"], [])
        self.assertFalse(plan["prune"])

    def test_02_prune_true_eligible_delete_one(self) -> None:
        plan = _plan(_de_fra_2_existing(tags=[OWNER]), _removed_ip_desired(), prune=True)
        self.assertEqual(plan["desired"], 4)
        self.assertEqual(plan["matched"], 4)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_eligible"], 1)
        self.assertEqual(plan["prune_blocked"], 0)
        self.assertEqual(plan["delete"], 1)
        self.assertEqual([item["address"] for item in plan["delete_items"]], [REMOVED_IP])
        self.assertEqual(plan["delete_items"][0]["uuid"], DE_FRA_2_HOSTS[3]["uuid"])

    def test_03_prune_true_allow_writes_false_no_mutation(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        desired = _removed_ip_desired()
        plan = _plan(existing, desired, allow_writes=False, prune=True)
        self.assertEqual(plan["delete"], 1)
        self.assertEqual(plan["writes"], [])
        self.assertEqual(
            plan["summary"],
            "desired=4 matched=4 create=0 update=0 adopt=0 stale=1 "
            "prune_eligible=1 prune_blocked=0 delete=1 ambiguous=0",
        )
        result = _simulate_run(existing, desired, allow_writes=False, prune=True)
        self.assertEqual(result["mutations"], [])
        self.assertEqual(result["deleted"], [])
        self.assertFalse(result["verified_before_delete"])

    def test_04_prune_true_allow_writes_true_deletes_uuid(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        desired = _removed_ip_desired()
        result = _simulate_run(existing, desired, allow_writes=True, prune=True)
        old_uuid = DE_FRA_2_HOSTS[3]["uuid"]
        self.assertEqual(result["plan"]["delete"], 1)
        self.assertEqual(result["deleted"], [old_uuid])
        self.assertEqual(
            [item for item in result["mutations"] if item["method"] == "DELETE"],
            [{"method": "DELETE", "path": f"/api/hosts/{old_uuid}", "uuid": old_uuid, "address": REMOVED_IP}],
        )
        self.assertTrue(result["final_verify"]["ok"])
        self.assertTrue(result["deleted_verify"]["ok"])
        self.assertEqual(result["final_plan"]["prune_eligible"], 0)

    def test_05_exact_delete_endpoint_and_status(self) -> None:
        block = _task_block(ROLE_TASKS, "AntiBlock Hosts | Delete stale Host")
        self.assertIn("url: \"{{ remnawave_panel_api_base }}/hosts/{{ item.uuid }}\"", block)
        self.assertIn("method: DELETE", block)
        self.assertIn("status_code: [204]", block)
        self.assertNotIn("body:", block)
        self.assertNotIn("bulk/delete", block)
        self.assertIn("loop: \"{{ _abh_plan['delete_items'] }}\"", block)
        self.assertIn("delete {{ item.address }} {{ item.uuid }}", block)
        self.assertIn("changed_when: true", block)

    def test_06_delete_by_uuid_only(self) -> None:
        plan = _plan(_de_fra_2_existing(tags=[OWNER]), _removed_ip_desired(), prune=True)
        item = plan["delete_items"][0]
        self.assertEqual(item["path"], f"/api/hosts/{item['uuid']}")
        self.assertNotIn(item["address"], item["path"])
        self.assertNotIn("remark", item["path"])
        delete = _task_block(ROLE_TASKS, "AntiBlock Hosts | Delete stale Host")
        self.assertIn("/hosts/{{ item.uuid }}", delete)
        self.assertNotIn("/hosts/{{ item.address }}", delete)
        self.assertNotIn("bulk/delete", ROLE_TASKS)

    def test_07_public_hostname_never_deleted(self) -> None:
        desired = [item for item in _desired() if item["address"] != PUBLIC_HOSTNAME]
        plan = _plan(_de_fra_2_existing(tags=[OWNER]), desired, allow_writes=True, prune=True)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_blocked"], 1)
        self.assertEqual(plan["delete"], 0)
        self.assertEqual(plan["delete_items"], [])

    def test_08_extra_tag_never_deleted(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = [OWNER, "FOO"]
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired(), allow_writes=True, prune=True)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_blocked"], 1)
        self.assertEqual(plan["delete_items"], [])

    def test_09_managed_combination_never_deleted(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = [OWNER, MANAGED]
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired(), allow_writes=True, prune=True)
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["delete_items"], [])

    def test_10_multi_node_never_deleted(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["nodes"] = [NODE, OTHER_NODE]
        plan = _plan(existing, _desired(), allow_writes=True, prune=True)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "multiple_nodes")
        self.assertEqual(plan["delete_items"], [])

    def test_11_other_node_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["nodes"] = [OTHER_NODE]
        plan = _plan(existing, _desired(), prune=True)
        self.assertEqual(plan["stale"], 0)
        self.assertEqual(plan["delete"], 0)

    def test_12_other_profile_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["inbound"] = {
            "configProfileUuid": OTHER_PROFILE,
            "configProfileInboundUuid": INBOUND,
        }
        plan = _plan(existing, _desired(), prune=True)
        self.assertEqual(plan["stale"], 0)
        self.assertEqual(plan["delete"], 0)

    def test_13_other_inbound_ignored(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["inbound"] = {
            "configProfileUuid": PROFILE,
            "configProfileInboundUuid": OTHER_INBOUND,
        }
        plan = _plan(existing, _desired(), prune=True)
        self.assertEqual(plan["stale"], 0)
        self.assertEqual(plan["delete"], 0)

    def test_14_non_ipv4_never_deleted(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "edge-extra.digitalstreamers.xyz"
        plan = _plan(existing, _desired(), allow_writes=True, prune=True)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "non_ipv4_address")
        self.assertEqual(plan["delete_items"], [])

    def test_15_missing_uuid_never_deleted(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["address"] = "198.51.100.10"
        existing[3]["uuid"] = ""
        plan = _plan(existing, _desired(), allow_writes=True, prune=True)
        self.assertEqual(plan["stale_items"][0]["block_reason"], "missing_uuid")
        self.assertEqual(plan["delete_items"], [])

    def test_16_prune_blocked_never_in_delete_items(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[3]["tags"] = [OWNER, "FOO"]
        existing[3]["address"] = "198.51.100.10"
        plan = _plan(existing, _desired(), prune=True)
        self.assertTrue(all(item["prune_eligible"] for item in plan["delete_items"]))
        self.assertTrue(all(not item["prune_eligible"] for item in plan["stale_items"]))
        self.assertEqual(plan["delete_items"], [])

    def test_17_create_succeeds_before_stale_delete(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        desired = _replaced_ip_desired()
        result = _simulate_run(existing, desired, allow_writes=True, prune=True)
        methods = [item["method"] for item in result["mutations"]]
        self.assertEqual(methods, ["POST", "DELETE"])
        self.assertEqual(result["mutations"][0]["address"], NEW_IP)
        self.assertEqual(result["mutations"][1]["address"], REMOVED_IP)
        self.assertTrue(result["verified_before_delete"])
        self.assertIn(NEW_IP, [host["address"] for host in result["hosts"]])
        self.assertNotIn(REMOVED_IP, [host["address"] for host in result["hosts"]])

    def test_18_patch_succeeds_before_stale_delete(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[0]["path"] = "/old"
        desired = _removed_ip_desired()
        result = _simulate_run(existing, desired, allow_writes=True, prune=True)
        methods = [item["method"] for item in result["mutations"]]
        self.assertEqual(methods, ["PATCH", "DELETE"])
        self.assertTrue(result["verified_before_delete"])
        self.assertTrue(result["final_verify"]["ok"])

    def test_19_write_failure_prevents_delete(self) -> None:
        result = _simulate_run(
            _de_fra_2_existing(tags=[OWNER]),
            _replaced_ip_desired(),
            allow_writes=True,
            prune=True,
            fail_writes=True,
        )
        self.assertEqual(result["failed"], "writes")
        self.assertEqual(result["deleted"], [])
        self.assertFalse(any(item["method"] == "DELETE" for item in result["mutations"]))

    def test_20_desired_verify_failure_prevents_delete(self) -> None:
        result = _simulate_run(
            _de_fra_2_existing(tags=[OWNER]),
            _removed_ip_desired(),
            allow_writes=True,
            prune=True,
            fail_verify=True,
        )
        self.assertEqual(result["failed"], "verify")
        self.assertTrue(result["verified_before_delete"])
        self.assertEqual(result["deleted"], [])

    def test_21_prune_only_still_verifies_desired_before_delete(self) -> None:
        result = _simulate_run(
            _de_fra_2_existing(tags=[OWNER]),
            _removed_ip_desired(),
            allow_writes=True,
            prune=True,
        )
        self.assertEqual(result["plan"]["writes"], [])
        self.assertTrue(result["verified_before_delete"])
        self.assertEqual(result["deleted"], [DE_FRA_2_HOSTS[3]["uuid"]])
        verify_pos = ROLE_TASKS.find("AntiBlock Hosts | Assert desired Hosts verified")
        delete_pos = ROLE_TASKS.find("AntiBlock Hosts | Delete stale Host")
        self.assertGreater(verify_pos, 0)
        self.assertGreater(delete_pos, verify_pos)
        self.assertIn("_abh_desired_verify is defined", ROLE_TASKS)
        self.assertIn("_abh_desired_verify.ok | bool", ROLE_TASKS)
        self.assertIn("Reuse initial GET for prune-only desired verify", ROLE_TASKS)

    def test_22_post_delete_get_uuid_absent(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        desired = _removed_ip_desired()
        result = _simulate_run(existing, desired, allow_writes=True, prune=True)
        old_uuid = DE_FRA_2_HOSTS[3]["uuid"]
        self.assertNotIn(old_uuid, [host.get("uuid") for host in result["hosts"]])
        self.assertTrue(result["deleted_verify"]["ok"])
        self.assertIn("remnawave_antiblock_hosts_verify_deleted", ROLE_TASKS)
        self.assertIn("Re-GET /api/hosts after delete", ROLE_TASKS)

    def test_23_post_delete_desired_verify_passes(self) -> None:
        result = _simulate_run(
            _de_fra_2_existing(tags=[OWNER]),
            _removed_ip_desired(),
            allow_writes=True,
            prune=True,
        )
        self.assertTrue(result["final_verify"]["ok"])
        self.assertIn("remnawave_antiblock_hosts_verify", _task_block(ROLE_TASKS, "AntiBlock Hosts | Verify after delete"))

    def test_24_post_delete_classification_prune_eligible_zero(self) -> None:
        result = _simulate_run(
            _de_fra_2_existing(tags=[OWNER]),
            _removed_ip_desired(),
            allow_writes=True,
            prune=True,
        )
        self.assertEqual(result["final_plan"]["stale"], 0)
        self.assertEqual(result["final_plan"]["prune_eligible"], 0)
        self.assertIn("(_abh_final_plan.prune_eligible | int) == 0", ROLE_TASKS)

    def test_25_blocked_stale_may_remain(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        existing.append(
            _existing_host(
                {"uuid": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", "remark": "blocked", "address": "198.51.100.10"},
                tags=[OWNER, "FOO"],
            )
        )
        result = _simulate_run(existing, _removed_ip_desired(), allow_writes=True, prune=True)
        self.assertEqual(result["plan"]["stale"], 2)
        self.assertEqual(result["plan"]["prune_eligible"], 1)
        self.assertEqual(result["plan"]["prune_blocked"], 1)
        self.assertEqual(result["plan"]["delete"], 1)
        self.assertEqual(result["final_plan"]["stale"], 1)
        self.assertEqual(result["final_plan"]["prune_eligible"], 0)
        self.assertEqual(result["final_plan"]["prune_blocked"], 1)
        self.assertIn("198.51.100.10", [host["address"] for host in result["hosts"]])
        self.assertNotIn("stale == 0", ROLE_TASKS)
        self.assertNotIn("stale | int) == 0", ROLE_TASKS)

    def test_26_partial_delete_is_rerunnable(self) -> None:
        existing = _de_fra_2_existing(tags=[OWNER])
        extra = _existing_host(
            {"uuid": "ffffffff-ffff-4fff-8fff-ffffffffffff", "remark": "extra", "address": "198.51.100.11"},
            tags=[OWNER],
        )
        existing.append(extra)
        desired = _removed_ip_desired()
        first = _simulate_run(existing, desired, allow_writes=True, prune=True, fail_delete_at=1)
        self.assertEqual(first["failed"], "delete")
        self.assertEqual(len(first["deleted"]), 1)
        self.assertEqual(first["final_plan"]["prune_eligible"], 1)
        second = _simulate_run(first["hosts"], desired, allow_writes=True, prune=True)
        self.assertIsNone(second["failed"])
        self.assertEqual(len(second["deleted"]), 1)
        self.assertEqual(second["final_plan"]["prune_eligible"], 0)
        self.assertTrue(second["final_verify"]["ok"])

    def test_27_de_fra_2_fixture_zero_drift(self) -> None:
        plan = _plan(_de_fra_2_existing(tags=[OWNER]), prune=True, allow_writes=True)
        self.assertEqual(plan["desired"], 5)
        self.assertEqual(plan["matched"], 5)
        self.assertEqual(plan["create"], 0)
        self.assertEqual(plan["update"], 0)
        self.assertEqual(plan["adopt"], 0)
        self.assertEqual(plan["stale"], 0)
        self.assertEqual(plan["prune_eligible"], 0)
        self.assertEqual(plan["prune_blocked"], 0)
        self.assertEqual(plan["delete"], 0)
        self.assertEqual(plan["ambiguous"], 0)
        self.assertEqual(plan["writes"], [])
        self.assertEqual(
            plan["summary"],
            "desired=5 matched=5 create=0 update=0 adopt=0 stale=0 "
            "prune_eligible=0 prune_blocked=0 delete=0 ambiguous=0",
        )

    def test_28_stage_6a_create_adopt_update_remain(self) -> None:
        adopt = _plan(_de_fra_2_existing(), allow_writes=True)
        self.assertEqual(adopt["adopt"], 5)
        create = _plan([], allow_writes=True)
        self.assertEqual(create["create"], 5)
        existing = _de_fra_2_existing(tags=[OWNER])
        existing[0]["path"] = "/old"
        update = _plan([existing[0]], [_desired()[0]], allow_writes=True)
        self.assertEqual(update["writes"][0]["method"], "PATCH")
        _assert_no_delete(adopt)
        _assert_no_delete(create)
        _assert_no_delete(update)

    def test_29_stage_6b1_classification_unchanged(self) -> None:
        plan = _plan(_de_fra_2_existing(tags=[OWNER]), _removed_ip_desired())
        self.assertEqual(plan["stale"], 1)
        self.assertEqual(plan["prune_eligible"], 1)
        self.assertEqual(plan["delete"], 0)
        blocked = _de_fra_2_existing(tags=[OWNER])
        blocked[3]["tags"] = [OWNER, "FOO"]
        blocked[3]["address"] = "198.51.100.10"
        blocked_plan = _plan(blocked, _desired(), prune=True)
        self.assertEqual(blocked_plan["prune_blocked"], 1)
        self.assertEqual(blocked_plan["delete"], 0)

    def test_30_no_third_allow_delete_variable(self) -> None:
        for blob in (ROLE_TASKS, SCRIPT, FILTER_PLUGIN, PLAY_RAW, MAKEFILE):
            self.assertNotIn("antiblock_cdn_hosts_allow_delete", blob)
            self.assertNotIn("allow_delete:", blob)
        self.assertIn("antiblock_cdn_hosts_allow_writes", ROLE_TASKS)
        self.assertIn("antiblock_cdn_hosts_prune", ROLE_TASKS)
        self.assertNotIn("antiblock_cdn_hosts_prune: true", PLAY_RAW)

    def test_31_ordinary_add_host_unchanged(self) -> None:
        self.assertNotIn("VFF:ANTIBLOCK", ADD_HOST_MAIN)
        self.assertNotIn("delete_items", ADD_HOST_MAIN)
        self.assertNotIn("antiblock_cdn_hosts_prune", ADD_HOST_MAIN)

    def test_32_ordinary_make_nodes_unchanged(self) -> None:
        nodes = NODES_PLAY.read_text(encoding="utf-8")
        self.assertIn("remnawave_add_host", nodes)
        self.assertNotIn("remnawave_antiblock_hosts", nodes)
        nodes_make = MAKEFILE[MAKEFILE.find("nodes:") : MAKEFILE.find("hosts-audit:")]
        self.assertNotIn("antiblock_cdn_hosts", nodes_make)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", nodes_make)

    def test_33_invariants_reject_unsafe_delete_item(self) -> None:
        with self.assertRaises(ValueError):
            abh.assert_delete_item_invariants(
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "address": PUBLIC_HOSTNAME,
                    "prune_eligible": True,
                    "tags": [OWNER],
                    "nodes": [NODE],
                },
                owner_tag=OWNER,
                node_uuid=NODE,
                public_hostname=PUBLIC_HOSTNAME,
            )
        with self.assertRaises(ValueError):
            abh.assert_delete_item_invariants(
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "address": REMOVED_IP,
                    "prune_eligible": False,
                    "tags": [OWNER],
                    "nodes": [NODE],
                },
                owner_tag=OWNER,
                node_uuid=NODE,
                public_hostname=PUBLIC_HOSTNAME,
            )

    def test_34_same_run_replacement_order(self) -> None:
        result = _simulate_run(
            _de_fra_2_existing(tags=[OWNER]),
            _replaced_ip_desired(),
            allow_writes=True,
            prune=True,
        )
        self.assertEqual([item["method"] for item in result["mutations"]], ["POST", "DELETE"])
        self.assertTrue(result["verified_before_delete"])
        self.assertTrue(result["final_verify"]["ok"])
        self.assertTrue(result["deleted_verify"]["ok"])
        self.assertEqual(result["final_plan"]["prune_eligible"], 0)
        self.assertIn(NEW_IP, [host["address"] for host in result["hosts"]])
        self.assertNotIn(DE_FRA_2_HOSTS[3]["uuid"], [host.get("uuid") for host in result["hosts"]])


DICT_METHOD_KEYS = ("items", "keys", "values", "get", "update", "copy")
_DOT_PLAN_METHOD = re.compile(
    r"_abh_(?:plan|verify)\.(" + "|".join(DICT_METHOD_KEYS) + r")\b"
)


class JinjaDictKeyCollisionTests(unittest.TestCase):
    def test_role_uses_bracket_notation_for_dict_method_keys(self) -> None:
        hits = _DOT_PLAN_METHOD.findall(ROLE_TASKS)
        self.assertEqual(hits, [], msg=f"Jinja dict-method collisions: {hits}")
        self.assertIn("_abh_plan['items']", ROLE_TASKS)
        self.assertIn("_abh_plan['stale_items']", ROLE_TASKS)
        self.assertIn("_abh_plan['delete_items']", ROLE_TASKS)
        self.assertNotIn("_abh_plan.items", ROLE_TASKS)
        self.assertNotIn("_abh_plan.stale_items", ROLE_TASKS)
        self.assertNotIn("_abh_plan.delete_items", ROLE_TASKS)

    def test_plan_summary_renders_items_key_not_dict_method(self) -> None:
        env = Environment()
        plan = {"items": [{"drift_fields": ["tags"]}]}
        dotted = "{{ _abh_plan.items | map(attribute='drift_fields') | list }}"
        with self.assertRaises(TypeError) as ctx:
            env.from_string(dotted).render(_abh_plan=plan)
        self.assertIn("not iterable", str(ctx.exception).lower())

        bracket = "{{ _abh_plan['items'] | map(attribute='drift_fields') | list }}"
        rendered = env.from_string(bracket).render(_abh_plan=plan)
        self.assertEqual(rendered, "[['tags']]")

        role_summary = (
            "{{ _abh_plan['items'] | map(attribute='drift_fields') | list }}"
        )
        self.assertIn(role_summary, ROLE_TASKS)
        self.assertEqual(
            env.from_string(role_summary).render(_abh_plan=plan),
            env.from_string(bracket).render(_abh_plan=plan),
        )


if __name__ == "__main__":
    unittest.main()
