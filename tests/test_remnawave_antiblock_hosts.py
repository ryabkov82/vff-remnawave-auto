#!/usr/bin/env python3
"""Stage 6A regression tests for Remnawave AntiBlock Hosts (current API)."""

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
PLAY_RAW = PLAY.read_text(encoding="utf-8")
FILTER_PLUGIN = (
    ROLE / "filter_plugins/remnawave_antiblock_hosts.py"
).read_text(encoding="utf-8")

OWNER = "VFF:ANTIBLOCK"
MANAGED = "VFF:MANAGED"
PROFILE = "a281fe1b-d9b6-4874-b34a-2832481cc60f"
INBOUND = "d7340374-7968-4240-9528-8c617af963ee"
NODE = "f5477129-378e-4c0d-830c-b3ed3ce58a7a"
OTHER_INBOUND = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_PROFILE = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

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
        "ingress_ips": [
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
            "desired=5 matched=5 create=0 update=5 adopt=5 delete=0 ambiguous=0",
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
        self.assertNotIn("method: DELETE", ROLE_TASKS)
        self.assertNotIn("method: delete", ROLE_TASKS.lower())
        self.assertIn("antiblock_cdn_hosts_prune", ROLE_TASKS)
        self.assertIn("not (antiblock_cdn_hosts_prune | bool)", ROLE_TASKS)
        with self.assertRaises(ValueError):
            abh.plan_antiblock_hosts(_desired(), [], owner_tag=OWNER, prune=True)

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

    def test_desired_addresses_hostname_then_ingress_ips(self) -> None:
        desired = _desired()
        self.assertEqual(
            [item["address"] for item in desired],
            [
                "cdn-lab.digitalstreamers.xyz",
                "188.72.111.7",
                "188.72.111.19",
                "188.72.111.35",
                "188.72.103.4",
            ],
        )
        self.assertTrue(all(item["port"] == 443 for item in desired))
        self.assertTrue(all(item["sni"] == "cdn-lab.digitalstreamers.xyz" for item in desired))

    def test_makefile_documents_hosts_tag_and_plan_override(self) -> None:
        node = MAKEFILE[MAKEFILE.find("antiblock-cdn-node:") : MAKEFILE.find("antiblock-cdn-node-plan:")]
        self.assertIn("TAGS=antiblock_cdn_hosts", node)
        self.assertIn("antiblock_cdn_hosts_allow_writes=false", node)
        self.assertNotIn("remnawave_add_host", node)

    def test_second_plan_after_adopt_is_noop(self) -> None:
        adopted = _de_fra_2_existing(tags=[OWNER])
        plan = abh.plan_antiblock_hosts(_desired(), adopted, owner_tag=OWNER, allow_writes=True)
        self.assertEqual(plan["update"], 0)
        self.assertEqual(plan["adopt"], 0)
        self.assertEqual(plan["writes"], [])
        self.assertEqual(
            plan["summary"],
            "desired=5 matched=5 create=0 update=0 adopt=0 delete=0 ambiguous=0",
        )

    def test_empty_tags_are_not_owned(self) -> None:
        self.assertFalse(abh.is_antiblock_owned({"tags": []}, OWNER))
        self.assertFalse(abh.is_antiblock_owned({"tag": OWNER}, OWNER))


DICT_METHOD_KEYS = ("items", "keys", "values", "get", "update", "copy")
_DOT_PLAN_METHOD = re.compile(
    r"_abh_(?:plan|verify)\.(" + "|".join(DICT_METHOD_KEYS) + r")\b"
)


class JinjaDictKeyCollisionTests(unittest.TestCase):
    def test_role_uses_bracket_notation_for_dict_method_keys(self) -> None:
        hits = _DOT_PLAN_METHOD.findall(ROLE_TASKS)
        self.assertEqual(hits, [], msg=f"Jinja dict-method collisions: {hits}")
        self.assertIn("_abh_plan['items']", ROLE_TASKS)
        self.assertNotIn("_abh_plan.items", ROLE_TASKS)

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
