#!/usr/bin/env python3
"""Unit and structural tests for global Yandex CM wildcard bootstrap."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import yandex_certificate_manager as ycm  # noqa: E402

FIXTURES = REPO / "tests/fixtures/yandex_cm"
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
BOOTSTRAP = REPO / "playbooks/antiblock_cdn_bootstrap.yml"
ANTIBLOCK_PLAY = REPO / "playbooks/antiblock_cdn.yml"
INBOUNDS_PLAY = REPO / "playbooks/inbounds.yml"
NODES_PLAY = REPO / "playbooks/nodes.yml"
ANTIBLOCK_VARS_PATH = REPO / "inventory/group_vars/all/antiblock_cdn.yml"
ANTIBLOCK_VARS = yaml.safe_load(ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8"))
ROLE_TASKS = (REPO / "roles/yandex_certificate_manager/tasks/main.yml").read_text(
    encoding="utf-8"
)
ROLE_DEFAULTS = yaml.safe_load(
    (REPO / "roles/yandex_certificate_manager/defaults/main.yml").read_text(
        encoding="utf-8"
    )
)
CF_DNS_TASKS = (REPO / "roles/cf_dns/tasks/main.yml").read_text(encoding="utf-8")
VAULT_ALL = (REPO / "inventory/group_vars/all/vault.yml").read_text(encoding="utf-8")
COMMITTED_VARS = [
    ANTIBLOCK_VARS_PATH,
    REPO / "inventory/group_vars/all/main.yml",
    REPO / "roles/yandex_certificate_manager/defaults/main.yml",
    BOOTSTRAP,
]
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
NAME = "antiblock-cdn-wildcard"
DOMAINS = ["*.cdn.digitalstreamers.xyz"]
ZONE = "digitalstreamers.xyz"
CDN_ACME = "_acme-challenge.cdn.digitalstreamers.xyz"
APEX_ACME = "_acme-challenge.digitalstreamers.xyz"
CF_RELATIVE_ACME = "_acme-challenge.cdn"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plays(path: Path) -> list[dict]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return []
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


class DesiredStateTests(unittest.TestCase):
    def test_wildcard_certificate_vars(self) -> None:
        cert = ANTIBLOCK_VARS["antiblock_cdn_certificate"]
        self.assertEqual(cert["name"], NAME)
        self.assertEqual(cert["domains"], DOMAINS)
        self.assertEqual(cert["challenge"], "dns")
        self.assertEqual(cert["dns_zone"], ZONE)
        folder_id = str(ANTIBLOCK_VARS["antiblock_cdn_yc_folder_id"] or "")
        self.assertIsNone(UUID_RE.search(folder_id))
        desired = ycm.load_desired_from_vars(ANTIBLOCK_VARS)
        self.assertEqual(desired["name"], NAME)
        self.assertEqual(desired["domains"], DOMAINS)
        self.assertEqual(desired["challenge"], "DNS")

    def test_certificate_uuid_not_inventoried(self) -> None:
        raw = ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8")
        self.assertIsNone(UUID_RE.search(raw))
        self.assertNotIn("certificate_id", raw.lower())
        folder_id = str(ANTIBLOCK_VARS["antiblock_cdn_yc_folder_id"] or "")
        self.assertIsNone(UUID_RE.search(folder_id))
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIsNone(UUID_RE.search(bootstrap))
        self.assertIn("antiblock_cdn_certificate.name", bootstrap)

    def test_secrets_not_in_committed_vars(self) -> None:
        self.assertTrue(VAULT_ALL.startswith("$ANSIBLE_VAULT"))
        joined = "\n".join(path.read_text(encoding="utf-8") for path in COMMITTED_VARS)
        self.assertNotIn("BEGIN PRIVATE KEY", joined)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", joined)
        self.assertNotIn("iamToken", joined)
        self.assertNotIn("y0_A", joined)
        self.assertNotIn("AQVN", joined)
        self.assertIn("vault_yandex_cloud_sa_authorized_key", joined)
        self.assertIn(
            "vault_yandex_cloud_sa_authorized_key | default('')",
            BOOTSTRAP.read_text(encoding="utf-8"),
        )
        self.assertNotRegex(
            joined,
            r"vault_yandex_cloud_sa_authorized_key:\s+['\"]?(?:\{|-----)",
        )
        self.assertNotIn(
            'vault_cf_dns_api_token: "',
            ANTIBLOCK_VARS_PATH.read_text(encoding="utf-8"),
        )


class ReconcileLogicTests(unittest.TestCase):
    def test_absent_plans_create_without_write(self) -> None:
        plan = ycm.plan_reconcile(None, name=NAME, domains=DOMAINS)
        self.assertEqual(plan["action"], "request")
        with mock.patch.object(ycm, "list_certificates", return_value=[]):
            with mock.patch.object(ycm, "request_managed_certificate") as req:
                result = ycm.reconcile(
                    token="t",
                    folder_id="folder",
                    name=NAME,
                    domains=DOMAINS,
                    dns_zone=ZONE,
                    allow_writes=False,
                )
        req.assert_not_called()
        self.assertEqual(result["action"], "request")
        self.assertFalse(result["requested"])
        self.assertEqual(result["status_class"], "absent")
        self.assertEqual(result["dns_records"], [])

    def test_existing_by_name_does_not_create_duplicate(self) -> None:
        existing = _load_fixture("issued_empty_challenges.json")
        plan = ycm.plan_reconcile(existing, name=NAME, domains=DOMAINS)
        self.assertEqual(plan["action"], "none")
        with mock.patch.object(ycm, "list_certificates", return_value=[existing]):
            with mock.patch.object(ycm, "request_managed_certificate") as req:
                with mock.patch.object(ycm, "get_certificate_full", return_value=existing):
                    result = ycm.reconcile(
                        token="t",
                        folder_id="folder",
                        name=NAME,
                        domains=DOMAINS,
                        dns_zone=ZONE,
                        allow_writes=True,
                    )
        req.assert_not_called()
        self.assertFalse(result["requested"])
        self.assertEqual(result["status_class"], "issued")
        self.assertEqual(result["dns_source"], "canonical_renewal")
        self.assertEqual(len(result["dns_records"]), 1)
        record = result["dns_records"][0]
        self.assertEqual(record["name"], CF_RELATIVE_ACME)
        self.assertEqual(record["type"], "CNAME")
        self.assertEqual(
            record["value"],
            f"{existing['id']}.{ycm.RENEWAL_CNAME_TARGET_SUFFIX}",
        )
        self.assertFalse(record["proxied"])
        self.assertTrue(record["solo"])

    def test_validating_does_not_create_second_certificate(self) -> None:
        existing = _load_fixture("validating_cname.json")
        plan = ycm.plan_reconcile(existing, name=NAME, domains=DOMAINS)
        self.assertEqual(plan["action"], "none")
        self.assertEqual(ycm.classify_status(existing["status"]), "pending")
        self.assertIn("PROCESSING", ycm.extract_challenge_statuses(existing))
        with mock.patch.object(ycm, "list_certificates", return_value=[existing]):
            with mock.patch.object(ycm, "request_managed_certificate") as req:
                result = ycm.reconcile(
                    token="t",
                    folder_id="folder",
                    name=NAME,
                    domains=DOMAINS,
                    dns_zone=ZONE,
                    allow_writes=True,
                )
        req.assert_not_called()
        self.assertFalse(result["requested"])
        self.assertEqual(result["status_class"], "pending")
        self.assertEqual(result["dns_source"], "challenge")
        self.assertEqual(result["dns_records"][0]["type"], "CNAME")
        self.assertEqual(
            result["dns_records"][0]["value"],
            "example-challenge.cm.yandexcloud.net",
        )
        self.assertNotEqual(
            result["dns_records"][0]["value"],
            f"{existing['id']}.{ycm.RENEWAL_CNAME_TARGET_SUFFIX}",
        )
        self.assertFalse(result["dns_records"][0]["proxied"])

    def test_invalid_fails_plan(self) -> None:
        existing = _load_fixture("invalid.json")
        plan = ycm.plan_reconcile(existing, name=NAME, domains=DOMAINS)
        self.assertEqual(plan["action"], "fail")
        with mock.patch.object(ycm, "list_certificates", return_value=[existing]):
            with self.assertRaises(RuntimeError):
                ycm.reconcile(
                    token="t",
                    folder_id="folder",
                    name=NAME,
                    domains=DOMAINS,
                    dns_zone=ZONE,
                    allow_writes=True,
                )


class ChallengeTests(unittest.TestCase):
    def test_challenge_taken_from_yandex_payload(self) -> None:
        cert = _load_fixture("validating_cname.json")
        extracted = ycm.extract_dns_challenges(cert)
        self.assertEqual(
            extracted,
            [
                {
                    "name": CDN_ACME,
                    "type": "CNAME",
                    "value": "example-challenge.cm.yandexcloud.net.",
                }
            ],
        )
        records = ycm.challenges_to_cf_dns_records(extracted, ZONE)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], CF_RELATIVE_ACME)
        self.assertEqual(records[0]["type"], "CNAME")
        self.assertEqual(records[0]["value"], "example-challenge.cm.yandexcloud.net")
        self.assertFalse(records[0]["proxied"])
        self.assertTrue(records[0]["solo"])
        invented = "_acme-challenge." + DOMAINS[0].lstrip("*.")
        self.assertEqual(extracted[0]["name"], cert["challenges"][0]["dnsChallenge"]["name"])
        self.assertNotEqual(extracted[0]["value"], invented)

    def test_cname_and_txt_not_created_together(self) -> None:
        cert = _load_fixture("cname_and_txt.json")
        records = ycm.challenges_to_cf_dns_records(
            ycm.extract_dns_challenges(cert), ZONE
        )
        types = {item["type"] for item in records}
        self.assertEqual(types, {"CNAME"})
        self.assertNotIn("TXT", types)

    def test_issued_reconciles_canonical_renewal_cname(self) -> None:
        cert = _load_fixture("issued_empty_challenges.json")
        selected, source = ycm.select_dns_challenges(cert, DOMAINS)
        self.assertEqual(source, "canonical_renewal")
        self.assertEqual(
            selected,
            [
                {
                    "name": CDN_ACME,
                    "type": "CNAME",
                    "value": f"{cert['id']}.{ycm.RENEWAL_CNAME_TARGET_SUFFIX}.",
                }
            ],
        )
        records = ycm.challenges_to_cf_dns_records(selected, ZONE)
        self.assertEqual(records[0]["name"], CF_RELATIVE_ACME)
        self.assertEqual(records[0]["type"], "CNAME")
        self.assertFalse(records[0]["proxied"])
        self.assertTrue(records[0]["solo"])
        self.assertNotIn("TXT", {item["type"] for item in records})

    def test_issued_with_live_cname_keeps_yandex_value(self) -> None:
        cert = _load_fixture("issued_with_cname.json")
        selected, source = ycm.select_dns_challenges(cert, DOMAINS)
        self.assertEqual(source, "challenge")
        self.assertEqual(selected[0]["value"], "example-challenge.cm.yandexcloud.net.")

    def test_issued_keeps_cname_no_delete(self) -> None:
        empty = ycm.challenges_to_cf_dns_records(
            ycm.extract_dns_challenges(_load_fixture("issued_empty_challenges.json")),
            ZONE,
        )
        self.assertEqual(empty, [])
        still = ycm.challenges_to_cf_dns_records(
            ycm.extract_dns_challenges(_load_fixture("issued_with_cname.json")),
            ZONE,
        )
        self.assertEqual(still[0]["type"], "CNAME")
        self.assertFalse(still[0]["proxied"])
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertNotIn("cf_dns_state: absent", bootstrap)
        self.assertNotIn("cf_dns_state: absent", ROLE_TASKS)
        self.assertIn("cf_dns_state: present", bootstrap)
        self.assertIn("yandex_cm_cf_dns_records | default([]) | length) > 0", bootstrap)
        self.assertNotIn("community.general.cloudflare_dns", ROLE_TASKS)
        self.assertIn("canonical_renewal", (REPO / "scripts/yandex_certificate_manager.py").read_text(encoding="utf-8"))
        self.assertIn("cm.yandexcloud.net", (REPO / "scripts/yandex_certificate_manager.py").read_text(encoding="utf-8"))

    def test_issued_txt_only_switches_to_canonical_cname(self) -> None:
        cert = {
            "id": "fpq-runtime-cert-id",
            "name": NAME,
            "type": "MANAGED",
            "domains": DOMAINS,
            "status": "ISSUED",
            "challenges": [
                {
                    "status": "VALID",
                    "dnsChallenge": {
                        "name": CDN_ACME,
                        "type": "TXT",
                        "value": "leftover-txt-must-not-be-created",
                    },
                }
            ],
        }
        selected, source = ycm.select_dns_challenges(cert, DOMAINS)
        self.assertEqual(source, "canonical_renewal")
        self.assertEqual(selected[0]["type"], "CNAME")
        self.assertEqual(
            selected[0]["value"],
            f"fpq-runtime-cert-id.{ycm.RENEWAL_CNAME_TARGET_SUFFIX}.",
        )
        records = ycm.challenges_to_cf_dns_records(selected, ZONE)
        self.assertEqual({item["type"] for item in records}, {"CNAME"})

    def test_renewing_without_challenges_uses_canonical_cname(self) -> None:
        cert = {
            "id": "fpq-runtime-cert-id",
            "name": NAME,
            "status": "RENEWING",
            "challenges": [],
        }
        selected, source = ycm.select_dns_challenges(cert, DOMAINS)
        self.assertEqual(source, "canonical_renewal")
        self.assertEqual(selected[0]["name"], CDN_ACME)
        self.assertEqual(selected[0]["type"], "CNAME")

    def test_http_challenge_ignored(self) -> None:
        cert = _load_fixture("issued_with_cname.json")
        extracted = ycm.extract_dns_challenges(cert)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["type"], "CNAME")
        self.assertNotIn("should-not-be-used", json.dumps(extracted))


class AcmeNamespaceCollisionTests(unittest.TestCase):
    """Certbot owns apex _acme-challenge.digitalstreamers.xyz TXT. Do not CNAME it."""

    AUTOMATION_PATHS = [
        REPO / "inventory/group_vars/all/antiblock_cdn.yml",
        REPO / "inventory/group_vars/antiblock_cdn_nodes.yml",
        REPO / "inventory/host_vars/de-fra-2/antiblock_cdn.yml",
        REPO / "playbooks/antiblock_cdn.yml",
        REPO / "playbooks/antiblock_cdn_bootstrap.yml",
        REPO / "playbooks/antiblock_cdn_yandex.yml",
        REPO / "scripts/yandex_cdn.py",
        REPO / "roles/yandex_cdn/defaults/main.yml",
        REPO / "roles/yandex_cdn/tasks/main.yml",
        REPO / "roles/yandex_certificate_manager/defaults/main.yml",
        REPO / "roles/yandex_certificate_manager/tasks/main.yml",
    ]

    def test_shared_wildcard_is_cdn_subdomain(self) -> None:
        cert = ANTIBLOCK_VARS["antiblock_cdn_certificate"]
        self.assertEqual(cert["domains"], ["*.cdn.digitalstreamers.xyz"])
        self.assertEqual(cert["dns_zone"], ZONE)
        self.assertNotIn("*.digitalstreamers.xyz", cert["domains"])
        self.assertNotIn("digitalstreamers.xyz", cert["domains"])

    def test_canonical_challenge_is_cdn_acme_not_apex(self) -> None:
        self.assertEqual(
            ycm.acme_challenge_fqdn("*.cdn.digitalstreamers.xyz"),
            CDN_ACME,
        )
        canonical = ycm.canonical_renewal_challenges("fpq-runtime-cert-id", DOMAINS)
        self.assertEqual([item["name"] for item in canonical], [CDN_ACME])
        self.assertNotIn(APEX_ACME, [item["name"] for item in canonical])
        records = ycm.challenges_to_cf_dns_records(canonical, ZONE)
        self.assertEqual(records[0]["name"], CF_RELATIVE_ACME)
        self.assertNotEqual(records[0]["name"], "_acme-challenge")
        self.assertEqual(records[0]["type"], "CNAME")
        self.assertFalse(records[0]["proxied"])
        self.assertTrue(records[0]["solo"])

    def test_automation_never_emits_apex_acme_challenge(self) -> None:
        desired = ycm.load_desired_from_vars(ANTIBLOCK_VARS)
        emitted = ycm.canonical_renewal_challenges("fpq-id", desired["domains"])
        emitted += ycm.challenges_to_cf_dns_records(emitted, desired["dns_zone"])
        blob = json.dumps(emitted)
        self.assertNotIn(APEX_ACME, blob)
        self.assertNotIn('"_acme-challenge"', blob)
        for path in self.AUTOMATION_PATHS:
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn(
                APEX_ACME,
                raw,
                msg=f"{path} must not create/change {APEX_ACME}",
            )
        for fixture in (FIXTURES).glob("*.json"):
            raw = fixture.read_text(encoding="utf-8")
            self.assertNotIn(APEX_ACME, raw, msg=str(fixture))

    def test_apex_leftover_txt_does_not_become_apex_cname(self) -> None:
        cert = {
            "id": "fpq-runtime-cert-id",
            "name": NAME,
            "status": "ISSUED",
            "challenges": [
                {
                    "status": "VALID",
                    "dnsChallenge": {
                        "name": APEX_ACME,
                        "type": "TXT",
                        "value": "certbot-owned-must-not-become-yandex-cname",
                    },
                }
            ],
        }
        selected, source = ycm.select_dns_challenges(cert, DOMAINS)
        self.assertEqual(source, "canonical_renewal")
        self.assertEqual([item["name"] for item in selected], [CDN_ACME])
        records = ycm.challenges_to_cf_dns_records(selected, ZONE)
        names = [item["name"] for item in records]
        self.assertEqual(names, [CF_RELATIVE_ACME])
        self.assertNotIn("_acme-challenge", names)

    def test_de_fra_2_keeps_legacy_public_and_origin_namespace(self) -> None:
        host = yaml.safe_load(
            (REPO / "inventory/host_vars/de-fra-2/antiblock_cdn.yml").read_text(
                encoding="utf-8"
            )
        )["antiblock_cdn_node"]
        group = yaml.safe_load(
            (REPO / "inventory/group_vars/antiblock_cdn_nodes.yml").read_text(
                encoding="utf-8"
            )
        )["antiblock_cdn_node"]
        self.assertEqual(host["public_hostname"], "cdn-lab.digitalstreamers.xyz")
        self.assertEqual(host["origin_hostname"], "origin-cdn.digitalstreamers.xyz")
        self.assertEqual(host["certificate_mode"], "legacy_existing")
        self.assertEqual(
            group["public_hostname"],
            "{{ inventory_hostname }}.cdn.digitalstreamers.xyz",
        )
        self.assertEqual(
            group["origin_hostname"],
            "origin-{{ inventory_hostname }}.digitalstreamers.xyz",
        )
        self.assertTrue(group["origin_hostname"].endswith(".digitalstreamers.xyz"))
        self.assertNotIn(".cdn.digitalstreamers.xyz", group["origin_hostname"])
        self.assertNotIn("cdn-{{ inventory_hostname }}", group["public_hostname"])


class PlaybookAndMakefileTests(unittest.TestCase):
    def test_bootstrap_is_global_only(self) -> None:
        raw = BOOTSTRAP.read_text(encoding="utf-8")
        plays = _plays(BOOTSTRAP)
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["hosts"], "panel")
        self.assertEqual(plays[0]["connection"], "local")
        roles = [item["role"] for item in plays[0]["roles"]]
        self.assertEqual(roles, ["yandex_certificate_manager", "cf_dns"])
        self.assertIn("community.general.cloudflare_dns", CF_DNS_TASKS)
        self.assertNotIn("community.general.cloudflare_dns", ROLE_TASKS)
        self.assertNotIn("api.cloudflare.com", ROLE_TASKS.lower())
        self.assertNotIn("api.cloudflare.com", raw.lower())
        for forbidden in (
            "origin_group",
            "remnawave_add_host",
            "remnawave_node_haproxy",
            "haproxy_tls_sni",
            "remnawave_register_node",
            "remnawave_inbounds",
        ):
            self.assertNotIn(forbidden, raw.lower())

    def test_per_node_playbook_does_not_issue_certificate(self) -> None:
        raw = ANTIBLOCK_PLAY.read_text(encoding="utf-8")
        self.assertNotIn("yandex_certificate_manager", raw)
        self.assertNotIn("requestNew", raw)
        roles = []
        for play in _plays(ANTIBLOCK_PLAY):
            for item in play.get("roles") or []:
                roles.append(item["role"] if isinstance(item, dict) else item)
        self.assertNotIn("yandex_certificate_manager", roles)

    def test_generic_make_inbounds_nodes_unchanged(self) -> None:
        inbounds = _makefile_block("inbounds")
        nodes = _makefile_block("nodes")
        antiblock = _makefile_block("antiblock-cdn")
        self.assertIn("PLAY_INBOUNDS", inbounds)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN_BOOTSTRAP", inbounds)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN", inbounds)
        self.assertIn("PLAY_NODES", nodes)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN_BOOTSTRAP", nodes)
        self.assertNotIn("yandex_certificate_manager", INBOUNDS_PLAY.read_text(encoding="utf-8"))
        self.assertNotIn("yandex_certificate_manager", NODES_PLAY.read_text(encoding="utf-8"))
        self.assertIn("PLAY_ANTIBLOCK_CDN)", antiblock)
        self.assertNotIn("PLAY_ANTIBLOCK_CDN_BOOTSTRAP", antiblock)

    def test_bootstrap_plan_is_not_check_mode(self) -> None:
        plan = _makefile_block("antiblock-cdn-bootstrap-plan")
        apply_ = _makefile_block("antiblock-cdn-bootstrap")
        plan_cmds = [
            ln
            for ln in plan.splitlines()
            if "$(ANSIBLE)" in ln or "$(BIN)/python" in ln
        ]
        self.assertTrue(any("--syntax-check" in ln for ln in plan_cmds))
        self.assertFalse(
            any(re.search(r"(^|\s)--check(\s|$)", ln) for ln in plan_cmds)
        )
        self.assertIn("print-desired", plan)
        self.assertNotIn("--allow-writes", plan)
        apply_cmds = [ln for ln in apply_.splitlines() if "$(ANSIBLE)" in ln]
        self.assertTrue(any("PLAY_ANTIBLOCK_CDN_BOOTSTRAP" in ln for ln in apply_cmds))
        self.assertFalse(any("--syntax-check" in ln for ln in apply_cmds))

    def test_role_defaults_are_safe(self) -> None:
        self.assertFalse(ROLE_DEFAULTS["yandex_cm_allow_writes"])
        self.assertEqual(ROLE_DEFAULTS["yandex_cm_sa_authorized_key"], "")
        self.assertEqual(ROLE_DEFAULTS["yandex_cm_iam_token"], "")
        self.assertIn("view=FULL", (REPO / "scripts/yandex_certificate_manager.py").read_text(encoding="utf-8"))
        self.assertIn("challengeType", (REPO / "scripts/yandex_certificate_manager.py").read_text(encoding="utf-8"))
        bootstrap_vars = _plays(BOOTSTRAP)[0]["roles"][0]["vars"]
        self.assertTrue(bootstrap_vars["yandex_cm_allow_writes"])
        self.assertEqual(bootstrap_vars["yandex_cm_challenge_type"], "DNS")


if __name__ == "__main__":
    unittest.main()
