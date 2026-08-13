#!/usr/bin/env python3
"""Unit tests for per-node Yandex CDN Origin Group + Resource reconcile."""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import yandex_cdn as ycdn  # noqa: E402
import yandex_certificate_manager as ycm  # noqa: E402
import yandex_cloud_common as yc  # noqa: E402

FIXTURES = REPO / "tests/fixtures/yandex_cdn"
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
PLAY = REPO / "playbooks/antiblock_cdn.yml"
PLAN_PLAY = REPO / "playbooks/antiblock_cdn_yandex.yml"
BOOTSTRAP = REPO / "playbooks/antiblock_cdn_bootstrap.yml"
GROUP_CDN = yaml.safe_load(
    (REPO / "inventory/group_vars/antiblock_cdn_nodes.yml").read_text(encoding="utf-8")
)
HOST_DE_FRA_2 = yaml.safe_load(
    (REPO / "inventory/host_vars/de-fra-2/antiblock_cdn.yml").read_text(encoding="utf-8")
)
ANTIBLOCK_VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/all/antiblock_cdn.yml").read_text(encoding="utf-8")
)
ROLE_DEFAULTS = yaml.safe_load(
    (REPO / "roles/yandex_cdn/defaults/main.yml").read_text(encoding="utf-8")
)
ROLE_TASKS = (REPO / "roles/yandex_cdn/tasks/main.yml").read_text(encoding="utf-8")
DOCS = (REPO / "docs/antiblock_cdn.md").read_text(encoding="utf-8")
HOSTS_INI = (REPO / "inventory/hosts.ini").read_text(encoding="utf-8")

PUBLIC = "cdn-lab.digitalstreamers.xyz"
ORIGIN = "origin-cdn.digitalstreamers.xyz"
GROUP_NAME = "common-origin-cdn-digitalstreamers-xyz"
ZONE = "digitalstreamers.xyz"
WILDCARD = "antiblock-cdn-wildcard"
FORBIDDEN_IDS = (
    "7883994692362412293",
    "bc8rzaiaqqkilvbp4fhu",
)
ISSUED_CERT = {
    "id": "fpq-wildcard-runtime",
    "name": WILDCARD,
    "type": "MANAGED",
    "domains": ["*.digitalstreamers.xyz"],
    "status": "ISSUED",
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plays(path: Path = PLAY) -> list[dict]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return loaded
    return [loaded]


def _makefile_block(target: str) -> str:
    marker = f"{target}:"
    start = MAKEFILE.find(marker)
    if start < 0:
        raise AssertionError(f"missing make target {target}")
    rest = MAKEFILE[start:]
    nxt = rest.find("\n\n")
    return rest if nxt < 0 else rest[:nxt]


def _includes(play: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for task in play.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        include = task.get("ansible.builtin.include_role") or task.get("include_role")
        if isinstance(include, dict) and include.get("name"):
            out.append((str(include["name"]), task))
    return out


def _desired(**overrides: object) -> dict:
    data = {
        "name": GROUP_NAME,
        "origin_hostname": ORIGIN,
        "use_next": True,
        "public_hostname": PUBLIC,
        "legacy": True,
    }
    data.update(overrides)
    return data


class OriginGroupPlanTests(unittest.TestCase):
    def test_a_absent_plans_create(self) -> None:
        plan = ycdn.plan_origin_group(None, **_desired())
        self.assertEqual(plan["action"], "create")

    def test_b_matching_group_is_noop(self) -> None:
        plan = ycdn.plan_origin_group(_load("origin_group_ok.json"), **_desired())
        self.assertEqual(plan["action"], "none")

    def test_c_source_drift_plans_update(self) -> None:
        group = _load("origin_group_ok.json")
        group["origins"][0]["source"] = "origin-old.digitalstreamers.xyz"
        plan = ycdn.plan_origin_group(group, **_desired(legacy=False))
        self.assertEqual(plan["action"], "update")
        self.assertIn("origins", plan["drift"])

    def test_d_extra_origin_on_new_node_plans_update(self) -> None:
        group = _load("origin_group_ok.json")
        group["name"] = "antiblock-de-fra-3"
        group["origins"].append(
            {"source": "origin-extra.example", "enabled": True, "backup": True}
        )
        group["resourcesMetadata"] = []
        plan = ycdn.plan_origin_group(
            group,
            **_desired(
                name="antiblock-de-fra-3",
                origin_hostname="origin-de-fra-3.digitalstreamers.xyz",
                use_next=False,
                public_hostname="cdn-de-fra-3.digitalstreamers.xyz",
                legacy=False,
            ),
        )
        self.assertEqual(plan["action"], "update")
        self.assertIn("origins", plan["drift"])

    def test_e_duplicate_group_names_fail(self) -> None:
        groups = [_load("origin_group_ok.json"), _load("origin_group_ok.json")]
        with self.assertRaisesRegex(RuntimeError, "Duplicate origin group"):
            ycdn.find_unique_by_name(groups, GROUP_NAME, kind="origin group")

    def test_f_legacy_unexpected_origins_or_resources_fail(self) -> None:
        extra = _load("origin_group_ok.json")
        extra["origins"].append({"source": "other.example", "enabled": True, "backup": False})
        with self.assertRaisesRegex(RuntimeError, "refusing destructive"):
            ycdn.plan_origin_group(extra, **_desired())
        unrelated = _load("origin_group_ok.json")
        unrelated["resourcesMetadata"].append(
            {"id": "other", "cname": "cdn-someone-else.digitalstreamers.xyz"}
        )
        with self.assertRaisesRegex(RuntimeError, "multiple CDN"):
            ycdn.plan_origin_group(unrelated, **_desired())
        wrong = _load("origin_group_ok.json")
        wrong["resourcesMetadata"][0]["cname"] = "unrelated.example"
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            ycdn.plan_origin_group(wrong, **_desired())


class ResourcePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ok = _load("resource_ok.json")
        self.kwargs = {
            "public_hostname": PUBLIC,
            "origin_group_id": "og-fixture-1",
            "origin_hostname": ORIGIN,
            "certificate_id": "fpq-wildcard-runtime",
            "manage_cert": False,
        }

    def test_g_absent_cname_plans_create(self) -> None:
        plan = ycdn.plan_resource(None, **self.kwargs)
        self.assertEqual(plan["action"], "create")

    def test_h_exact_production_options_noop(self) -> None:
        plan = ycdn.plan_resource(self.ok, **self.kwargs)
        self.assertEqual(plan["action"], "none")

    def test_i_origin_group_id_drift_patches(self) -> None:
        plan = ycdn.plan_resource(self.ok, **{**self.kwargs, "origin_group_id": "og-other"})
        self.assertEqual(plan["action"], "update")
        self.assertIn("origin_group_id", plan["drift"])

    def test_j_origin_protocol_drift_patches(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["originProtocol"] = "HTTP"
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertEqual(plan["action"], "update")
        self.assertIn("origin_protocol", plan["drift"])

    def test_k_host_origin_drift_patches(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["options"]["hostOptions"]["host"]["value"] = "other.example"
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertIn("hostOptions", plan["drift"])

    def test_l_custom_server_name_drift_patches(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["options"]["customServerName"]["value"] = "other.example"
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertIn("customServerName", plan["drift"])

    def test_m_allowed_methods_drift_patches(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["options"]["allowedHttpMethods"]["value"] = ["GET"]
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertIn("allowedHttpMethods", plan["drift"])

    def test_n_query_and_cookie_drift_patches(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["options"]["queryParamsOptions"]["ignoreQueryString"]["value"] = False
        resource["options"]["ignoreCookie"]["value"] = False
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertIn("queryParamsOptions", plan["drift"])
        self.assertIn("ignoreCookie", plan["drift"])

    def test_o_tls_profile_drift_patches(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["tls"]["profile"] = "PROFILE_LATEST"
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertIn("tls", plan["drift"])

    def test_p_provider_cname_from_resource(self) -> None:
        self.assertEqual(
            ycdn.provider_cname_of(self.ok),
            "ab9549976660aa28.topology.gslb.yccdn.ru",
        )

    def test_q_empty_provider_cname_polls(self) -> None:
        empty = copy.deepcopy(self.ok)
        empty["providerCname"] = ""
        filled = copy.deepcopy(self.ok)
        with mock.patch.object(ycdn, "get_resource", side_effect=[empty, filled]) as get:
            with mock.patch.object(ycdn.time, "sleep"):
                got = ycdn.wait_provider_cname("t", "res-fixture-1", timeout=10, poll_interval=0)
        self.assertEqual(ycdn.provider_cname_of(got), filled["providerCname"])
        self.assertEqual(get.call_count, 2)

    def test_r_empty_default_option_objects_do_not_drift(self) -> None:
        resource = copy.deepcopy(self.ok)
        resource["options"]["compressionOptions"] = {}
        resource["options"]["ipAddressAcl"] = {}
        plan = ycdn.plan_resource(resource, **self.kwargs)
        self.assertEqual(plan["action"], "none")

    def test_s_unmanaged_options_preserved_on_merge(self) -> None:
        current = copy.deepcopy(self.ok["options"])
        current["ipAddressAcl"] = {"enabled": True, "policyType": "ALLOW"}
        merged = ycdn.merge_resource_options(
            current, ycdn.desired_managed_options(ORIGIN)
        )
        self.assertEqual(merged["ipAddressAcl"], current["ipAddressAcl"])
        self.assertTrue(merged["hostOptions"]["host"]["enabled"])
        self.assertIn("edgeCacheSettings", merged)


class CertificateLookupTests(unittest.TestCase):
    def test_t_new_nodes_resolve_wildcard_by_name(self) -> None:
        with mock.patch.object(ycm, "list_certificates", return_value=[ISSUED_CERT]):
            found = ycdn.resolve_wildcard_certificate(
                "t",
                folder_id="folder",
                name=WILDCARD,
                domains=["*.digitalstreamers.xyz"],
            )
        self.assertEqual(found["id"], "fpq-wildcard-runtime")
        self.assertEqual(found["status"], "ISSUED")

    def test_u_certificate_not_issued_blocks_resource_create(self) -> None:
        pending = {**ISSUED_CERT, "status": "VALIDATING"}
        with mock.patch.object(ycm, "list_certificates", return_value=[pending]):
            with self.assertRaisesRegex(RuntimeError, "VALIDATING"):
                ycdn.resolve_wildcard_certificate(
                    "t",
                    folder_id="folder",
                    name=WILDCARD,
                    domains=["*.digitalstreamers.xyz"],
                )
        absent_plan = ycdn.plan_resource(
            None,
            public_hostname="cdn-de-fra-3.digitalstreamers.xyz",
            origin_group_id="og-new",
            origin_hostname="origin-de-fra-3.digitalstreamers.xyz",
            certificate_id=None,
            manage_cert=True,
        )
        self.assertEqual(absent_plan["action"], "create")
        with self.assertRaisesRegex(RuntimeError, "certificate id"):
            ycdn.create_resource(
                "t",
                folder_id="folder",
                public_hostname="cdn-de-fra-3.digitalstreamers.xyz",
                origin_group_id="og-new",
                origin_hostname="origin-de-fra-3.digitalstreamers.xyz",
                certificate_id=None,
                manage_cert=True,
                allow_writes=True,
                operation_timeout=1,
                poll_interval=0.1,
            )

    def test_v_de_fra_2_does_not_migrate_legacy_certificate(self) -> None:
        resource = _load("resource_ok.json")
        plan = ycdn.plan_resource(
            resource,
            public_hostname=PUBLIC,
            origin_group_id="og-fixture-1",
            origin_hostname=ORIGIN,
            certificate_id="fpq-wildcard-runtime",
            manage_cert=False,
        )
        self.assertEqual(plan["action"], "none")
        self.assertNotIn("ssl_certificate", plan.get("drift") or [])
        self.assertEqual(HOST_DE_FRA_2["antiblock_cdn_node"]["certificate_mode"], "legacy_existing")
        self.assertFalse(ycdn.manage_certificate("legacy_existing"))
        self.assertTrue(ycdn.manage_certificate("shared_wildcard"))


class DnsAndArchitectureTests(unittest.TestCase):
    def test_w_public_cname_proxied_false_solo_true(self) -> None:
        records = ycdn.public_cname_records(
            PUBLIC, ZONE, "ab9549976660aa28.topology.gslb.yccdn.ru"
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "cdn-lab")
        self.assertEqual(records[0]["type"], "CNAME")
        self.assertFalse(records[0]["proxied"])
        self.assertTrue(records[0]["solo"])

    def test_x_provider_cname_is_cname_target(self) -> None:
        records = ycdn.public_cname_records(
            "cdn-de-fra-3.digitalstreamers.xyz",
            ZONE,
            "provider.topology.gslb.yccdn.ru.",
        )
        self.assertEqual(records[0]["value"], "provider.topology.gslb.yccdn.ru")

    def test_y_origin_a_remains_separate(self) -> None:
        origin = GROUP_CDN["antiblock_cdn_origin_dns_records"][0]
        self.assertEqual(origin["type"], "A")
        self.assertTrue(origin["solo"])
        self.assertNotIn("cf_dns_records", GROUP_CDN)
        self.assertNotIn("antiblock_cdn_public_dns_records", GROUP_CDN)
        play = _plays()[1]
        includes = _includes(play)
        origin_task = next(task for name, task in includes if name == "cf_dns" and "origin A" in task["name"])
        public_task = next(task for name, task in includes if name == "cf_dns" and "public CDN CNAME" in task["name"])
        self.assertEqual(
            origin_task["vars"]["cf_dns_records"],
            "{{ antiblock_cdn_origin_dns_records }}",
        )
        self.assertEqual(
            public_task["vars"]["cf_dns_records"],
            "{{ yandex_cdn_public_dns_records }}",
        )

    def test_z_one_resource_per_node_architecture(self) -> None:
        derived = GROUP_CDN["antiblock_cdn_node"]
        self.assertEqual(derived["origin_group_name"], "antiblock-{{ inventory_hostname }}")
        self.assertFalse(derived["origin_group_use_next"])
        self.assertEqual(derived["certificate_mode"], "shared_wildcard")
        legacy = HOST_DE_FRA_2["antiblock_cdn_node"]
        self.assertEqual(legacy["origin_group_name"], GROUP_NAME)
        self.assertTrue(legacy["origin_group_use_next"])
        self.assertEqual(legacy["certificate_mode"], "legacy_existing")
        raw = PLAY.read_text(encoding="utf-8")
        self.assertNotIn("remnawave_add_host", raw)
        self.assertNotIn("VFF:ANTIBLOCK", raw)
        self.assertNotIn("prune", raw.lower())
        self.assertNotIn("requestNew", raw)
        self.assertNotIn("yandex_certificate_manager", raw)
        for forbidden in FORBIDDEN_IDS:
            self.assertNotIn(forbidden, raw)
            self.assertNotIn(forbidden, yaml.dump(GROUP_CDN))
            self.assertNotIn(forbidden, yaml.dump(HOST_DE_FRA_2))
            self.assertNotIn(forbidden, yaml.dump(ANTIBLOCK_VARS))
        self.assertNotIn("de-fra-3", _group_members())
        self.assertIn("backup': False", str(ycdn.desired_origins("origin.example")))
        self.assertEqual(len(ycdn.desired_origins("origin.example")), 1)


def _group_members() -> list[str]:
    members: list[str] = []
    in_section = False
    for line in HOSTS_INI.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1] == "antiblock_cdn_nodes"
            continue
        if in_section and stripped and not stripped.startswith("#"):
            members.append(stripped.split()[0])
    return members


class ReconcileWriteGuardTests(unittest.TestCase):
    def test_writes_disabled_never_post_or_patch(self) -> None:
        with mock.patch.object(ycdn, "list_origin_groups", return_value=[]):
            with mock.patch.object(ycdn, "list_resources", return_value=[]):
                with mock.patch.object(ycm, "list_certificates", return_value=[ISSUED_CERT]):
                    with mock.patch.object(ycdn, "create_origin_group") as cog:
                        with mock.patch.object(ycdn, "create_resource") as cres:
                            result = ycdn.reconcile(
                                token="t",
                                folder_id="folder",
                                public_hostname="cdn-de-fra-3.digitalstreamers.xyz",
                                origin_hostname="origin-de-fra-3.digitalstreamers.xyz",
                                origin_group_name="antiblock-de-fra-3",
                                origin_group_use_next=False,
                                certificate_mode="shared_wildcard",
                                certificate_name=WILDCARD,
                                certificate_domains=["*.digitalstreamers.xyz"],
                                dns_zone=ZONE,
                                allow_writes=False,
                            )
        cog.assert_not_called()
        cres.assert_not_called()
        self.assertFalse(result["changed"])
        self.assertEqual(result["origin_group"]["action"], "create")
        self.assertEqual(result["resource"]["action"], "create")
        self.assertFalse(ROLE_DEFAULTS["yandex_cdn_allow_writes"])
        with self.assertRaisesRegex(RuntimeError, "allow_writes is false"):
            ycdn._cdn_request("POST", ycdn.ORIGIN_GROUPS_URL, "t", {}, allow_writes=False)
        with self.assertRaisesRegex(RuntimeError, "DELETE is not implemented"):
            ycdn._cdn_request("DELETE", ycdn.RESOURCES_URL + "/x", "t", None, allow_writes=True)

    def test_legacy_stable_state_is_noop_without_writes(self) -> None:
        group = _load("origin_group_ok.json")
        resource = _load("resource_ok.json")
        with mock.patch.object(ycdn, "list_origin_groups", return_value=[group]):
            with mock.patch.object(ycdn, "list_resources", return_value=[resource]):
                with mock.patch.object(ycdn, "update_origin_group") as uog:
                    with mock.patch.object(ycdn, "update_resource") as ures:
                        result = ycdn.reconcile(
                            token="t",
                            folder_id="folder",
                            public_hostname=PUBLIC,
                            origin_hostname=ORIGIN,
                            origin_group_name=GROUP_NAME,
                            origin_group_use_next=True,
                            certificate_mode="legacy_existing",
                            certificate_name=WILDCARD,
                            certificate_domains=["*.digitalstreamers.xyz"],
                            dns_zone=ZONE,
                            allow_writes=True,
                        )
        uog.assert_not_called()
        ures.assert_not_called()
        self.assertFalse(result["changed"])
        self.assertEqual(result["origin_group"]["action"], "none")
        self.assertEqual(result["resource"]["action"], "none")
        self.assertEqual(result["provider_cname"], resource["providerCname"])
        self.assertEqual(result["certificate"]["id"], None)

    def test_shared_auth_is_not_duplicated(self) -> None:
        self.assertIs(ycm.jwt_ps256, yc.jwt_ps256)
        self.assertIs(ycm.iam_token_from_sa_key, yc.iam_token_from_sa_key)
        self.assertIs(ycm.wait_operation, yc.wait_operation)
        source = (REPO / "scripts/yandex_cdn.py").read_text(encoding="utf-8")
        self.assertNotIn("def jwt_ps256", source)
        self.assertIn("yandex_cloud_common", source)
        self.assertIn("yc init is not used", ROLE_TASKS.lower())


class PlaybookMakefileTests(unittest.TestCase):
    def test_apply_order_origin_then_yandex_then_public_cname(self) -> None:
        play = _plays()[1]
        names = [str(task.get("name")) for task in play.get("tasks") or []]
        self.assertLess(
            names.index("AntiBlock CDN | Wait until origin inbound is listening"),
            names.index("AntiBlock CDN | Ensure origin A record"),
        )
        self.assertLess(
            names.index("AntiBlock CDN | Ensure origin A record"),
            names.index("AntiBlock CDN | Ensure HAProxy origin SNI route"),
        )
        self.assertLess(
            names.index("AntiBlock CDN | Ensure HAProxy origin SNI route"),
            names.index("AntiBlock CDN | Ensure Yandex Origin Group and CDN Resource"),
        )
        self.assertLess(
            names.index("AntiBlock CDN | Ensure Yandex Origin Group and CDN Resource"),
            names.index("AntiBlock CDN | Ensure public CDN CNAME"),
        )
        yandex = next(
            task
            for name, task in _includes(play)
            if name == "yandex_cdn"
        )
        self.assertTrue(yandex["ansible.builtin.include_role"]["apply"]["delegate_to"] == "localhost")
        self.assertTrue(yandex["vars"]["yandex_cdn_allow_writes"])
        public = next(
            task
            for name, task in _includes(play)
            if name == "cf_dns" and "public CDN CNAME" in task["name"]
        )
        self.assertEqual(
            public["ansible.builtin.include_role"]["apply"]["delegate_to"],
            "localhost",
        )

    def test_plan_playbook_is_local_read_only(self) -> None:
        plays = _plays(PLAN_PLAY)
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["connection"], "local")
        self.assertEqual(plays[0]["hosts"], "antiblock_cdn_nodes")
        self.assertFalse(plays[0]["roles"][0]["vars"]["yandex_cdn_allow_writes"])
        raw = PLAN_PLAY.read_text(encoding="utf-8")
        self.assertNotIn("remnawave_register_node", raw)
        self.assertNotIn("remnawave_node_haproxy", raw)
        self.assertNotIn("cf_dns", raw)
        node = _makefile_block("antiblock-cdn-node")
        plan = _makefile_block("antiblock-cdn-node-plan")
        self.assertIn("--limit panel:$(HOST)", node)
        self.assertIn("delegate_to localhost", node)
        self.assertIn("HOST is required", plan)
        self.assertIn("antiblock_cdn_nodes", plan)
        self.assertIn("PLAY_ANTIBLOCK_CDN_YANDEX", plan)
        self.assertIn("--limit $(HOST)", plan)
        self.assertTrue(any("--syntax-check" in ln for ln in plan.splitlines()))
        self.assertFalse(any(re.search(r"(^|\s)--check(\s|$)", ln) for ln in plan.splitlines()))
        apply_ = _makefile_block("antiblock-cdn")
        self.assertNotIn("PLAY_ANTIBLOCK_CDN_YANDEX", apply_)

    def test_limit_does_not_use_localhost_play(self) -> None:
        for play in _plays():
            self.assertNotEqual(play.get("hosts"), "localhost")
        self.assertNotEqual(_plays(PLAN_PLAY)[0].get("hosts"), "localhost")

    def test_docs_cover_per_node_cdn(self) -> None:
        self.assertIn("one node = one CDN Resource", DOCS)
        self.assertIn("cdn.editor", DOCS)
        self.assertIn("legacy_existing", DOCS)
        self.assertIn("make antiblock-cdn-node-plan", DOCS)
        self.assertIn("common-origin-cdn-digitalstreamers-xyz", DOCS)


if __name__ == "__main__":
    unittest.main()
