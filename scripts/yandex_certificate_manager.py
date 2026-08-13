#!/usr/bin/env python3
"""Yandex Certificate Manager helpers (idempotent lookup / challenge parse).

API writes happen only when --allow-writes is set. While VALIDATING, DNS
challenge records are taken from Certificate Manager FULL view and are never
invented locally. After the certificate ID is known, ISSUED/empty-challenge
runs keep reconciling Yandex's documented renewal CNAME
`_acme-challenge.<domain> → <certificate_id>.cm.yandexcloud.net`.

Auth (non-interactive): service-account authorized key JSON -> JWT PS256 ->
IAM token. Interactive `yc init` is not used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yandex_cloud_common as yc  # noqa: E402

CERT_API = "https://certificate-manager.api.cloud.yandex.net/certificate-manager/v1/certificates"
IAM_TOKENS_URL = yc.IAM_TOKENS_URL
IAM_AUD = yc.IAM_AUD
OPS_API = yc.OPS_API
jwt_ps256 = yc.jwt_ps256
iam_token_from_sa_key = yc.iam_token_from_sa_key
_request_json = yc.request_json
wait_operation = yc.wait_operation
NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
RENEWAL_CNAME_TARGET_SUFFIX = "cm.yandexcloud.net"

PENDING_CERT_STATUSES = frozenset({"VALIDATING", "RENEWING"})
FAILED_CERT_STATUSES = frozenset({"INVALID", "RENEWAL_FAILED", "REVOKED"})
SUCCESS_CERT_STATUSES = frozenset({"ISSUED"})


def classify_status(status: str | None) -> str:
    value = (status or "").strip().upper()
    if not value or value in {"ABSENT", "NOT_FOUND"}:
        return "absent"
    if value in SUCCESS_CERT_STATUSES:
        return "issued"
    if value in PENDING_CERT_STATUSES:
        return "pending"
    if value in FAILED_CERT_STATUSES:
        return "failed"
    return "unknown"


def find_certificate_by_name(
    certificates: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    want = (name or "").strip()
    matches = [item for item in certificates if str(item.get("name") or "") == want]
    if len(matches) > 1:
        raise ValueError(
            f"Multiple certificates named {want!r}; refusing to pick one."
        )
    return matches[0] if matches else None


def domains_match(actual: Any, desired: Any) -> bool:
    def _norm(values: Any) -> set[str]:
        return {str(item).strip().lower().rstrip(".") for item in (values or []) if item}

    return _norm(actual) == _norm(desired)


def plan_reconcile(
    existing: dict[str, Any] | None,
    *,
    name: str,
    domains: list[str],
) -> dict[str, Any]:
    """Decide request vs no-op. Never requests a second cert for the same name."""
    if existing is None:
        return {
            "action": "request",
            "reason": f"certificate {name!r} is absent",
            "status": "absent",
        }
    existing_name = str(existing.get("name") or "")
    if existing_name != name:
        raise ValueError(f"Lookup mismatch: existing name {existing_name!r} != {name!r}")
    cert_type = str(existing.get("type") or "").upper()
    if cert_type and cert_type != "MANAGED":
        raise ValueError(
            f"Certificate {name!r} exists with type {cert_type}; expected MANAGED."
        )
    if not domains_match(existing.get("domains"), domains):
        raise ValueError(
            f"Certificate {name!r} exists with domains {existing.get('domains')}, "
            f"desired {domains}. Refusing to create a duplicate."
        )
    status = str(existing.get("status") or "")
    kind = classify_status(status)
    if kind == "failed":
        return {
            "action": "fail",
            "reason": f"certificate {name!r} status={status}",
            "status": status,
        }
    return {
        "action": "none",
        "reason": f"certificate {name!r} already exists (status={status or 'unknown'})",
        "status": status or "unknown",
    }


def _challenge_dns(challenge: dict[str, Any]) -> dict[str, Any] | None:
    dns = challenge.get("dnsChallenge") or challenge.get("dns_challenge")
    if not isinstance(dns, dict):
        return None
    name = str(dns.get("name") or "").strip()
    rtype = str(dns.get("type") or "").strip().upper()
    value = str(dns.get("value") or "").strip()
    if not name or not rtype or not value:
        return None
    return {"name": name, "type": rtype, "value": value}


def extract_dns_challenges(certificate: dict[str, Any] | None) -> list[dict[str, str]]:
    """Return DNS records exactly as Certificate Manager FULL view provided them."""
    if not certificate:
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for challenge in certificate.get("challenges") or []:
        if not isinstance(challenge, dict):
            continue
        dns = _challenge_dns(challenge)
        if dns is None:
            continue
        if dns["type"] not in {"CNAME", "TXT"}:
            raise ValueError(
                f"Unsupported DNS challenge type {dns['type']!r} from Certificate Manager"
            )
        key = (dns["name"], dns["type"], dns["value"])
        if key in seen:
            continue
        seen.add(key)
        out.append(dns)
    return out


def extract_challenge_statuses(certificate: dict[str, Any] | None) -> list[str]:
    if not certificate:
        return []
    out: list[str] = []
    for challenge in certificate.get("challenges") or []:
        if not isinstance(challenge, dict):
            continue
        status = str(challenge.get("status") or "").strip().upper()
        if status:
            out.append(status)
    return out


def relative_record_name(fqdn: str, zone: str) -> str:
    name = fqdn.strip().rstrip(".")
    zone_name = zone.strip().rstrip(".")
    if not name:
        return name
    lower_name, lower_zone = name.lower(), zone_name.lower()
    if lower_name == lower_zone:
        return "@"
    suffix = "." + lower_zone
    if lower_name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def acme_challenge_fqdn(domain: str) -> str:
    """Return `_acme-challenge.<apex>` for a host or wildcard domain."""
    host = domain.strip().lower().rstrip(".")
    if host.startswith("*."):
        host = host[2:]
    if not host:
        raise ValueError("cannot derive _acme-challenge name from empty domain")
    return f"_acme-challenge.{host}"


def canonical_renewal_challenges(
    certificate_id: str, domains: list[str]
) -> list[dict[str, str]]:
    """Yandex auto-renewal CNAME: `_acme-challenge.<domain> → <id>.cm.yandexcloud.net`."""
    cert_id = str(certificate_id or "").strip()
    if not cert_id:
        return []
    value = f"{cert_id}.{RENEWAL_CNAME_TARGET_SUFFIX}."
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for domain in domains or []:
        name = acme_challenge_fqdn(str(domain))
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "type": "CNAME", "value": value})
    return out


def select_dns_challenges(
    certificate: dict[str, Any] | None,
    domains: list[str],
) -> tuple[list[dict[str, str]], str]:
    """Choose Cloudflare records: live FULL-view challenge, else renewal CNAME.

    VALIDATING/RENEWING with returned challenges: use name/type/value as-is.
    ISSUED (or pending with an empty challenge list) and a certificate ID:
    keep the documented renewal CNAME so a deleted `_acme-challenge` is restored.
    TXT is never emitted once a CNAME is selected.
    """
    live = extract_dns_challenges(certificate)
    status_class = classify_status((certificate or {}).get("status"))
    cert_id = str((certificate or {}).get("id") or "").strip()
    if status_class == "pending" and live:
        return live, "challenge"
    live_has_cname = any(item["type"].upper() == "CNAME" for item in live)
    if live_has_cname:
        return live, "challenge"
    if cert_id:
        return canonical_renewal_challenges(cert_id, domains), "canonical_renewal"
    return live, "challenge"


def challenges_to_cf_dns_records(
    challenges: list[dict[str, str]],
    zone: str,
) -> list[dict[str, Any]]:
    """Map Yandex DNS challenges to roles/cf_dns records.

    If any CNAME is present, TXT records are omitted (CNAME cannot coexist
    with other types at the same name). proxied is always false. solo is true
    for CNAME so a leftover TXT at _acme-challenge is replaced.
    """
    if not challenges:
        return []
    types = {item["type"].upper() for item in challenges}
    selected = challenges
    if "CNAME" in types:
        selected = [item for item in challenges if item["type"].upper() == "CNAME"]
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in selected:
        rtype = item["type"].upper()
        record = relative_record_name(item["name"], zone)
        value = item["value"].rstrip(".")
        key = (record.lower(), rtype)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "name": record,
                "type": rtype,
                "value": value,
                "proxied": False,
                "solo": rtype == "CNAME",
            }
        )
    return records


def load_desired_from_vars(data: dict[str, Any]) -> dict[str, Any]:
    cert = data.get("antiblock_cdn_certificate") or {}
    if not isinstance(cert, dict):
        raise ValueError("antiblock_cdn_certificate must be a mapping")
    name = str(cert.get("name") or "").strip()
    domains = [str(item).strip() for item in (cert.get("domains") or []) if item]
    challenge = str(cert.get("challenge") or "dns").strip().lower()
    dns_zone = str(cert.get("dns_zone") or "").strip()
    if not name:
        raise ValueError("antiblock_cdn_certificate.name is required")
    if not NAME_RE.match(name):
        raise ValueError(
            f"certificate name {name!r} must match {NAME_RE.pattern} (Yandex CM)"
        )
    if not domains:
        raise ValueError("antiblock_cdn_certificate.domains is required")
    if challenge != "dns":
        raise ValueError("only DNS challenge is supported for wildcard certificates")
    return {
        "name": name,
        "domains": domains,
        "challenge": "DNS",
        "dns_zone": dns_zone,
        "folder_id": str(data.get("antiblock_cdn_yc_folder_id") or "").strip(),
    }


def list_certificates(token: str, folder_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page_token = ""
    while True:
        query = {"folderId": folder_id, "view": "FULL", "pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        url = CERT_API + "?" + urllib.parse.urlencode(query)
        payload = _request_json("GET", url, token)
        out.extend(payload.get("certificates") or [])
        page_token = str(payload.get("nextPageToken") or payload.get("next_page_token") or "")
        if not page_token:
            break
    return out


def get_certificate_full(token: str, certificate_id: str) -> dict[str, Any]:
    url = f"{CERT_API}/{urllib.parse.quote(certificate_id)}?view=FULL"
    return _request_json("GET", url, token)


def request_managed_certificate(
    token: str,
    *,
    folder_id: str,
    name: str,
    domains: list[str],
) -> dict[str, Any]:
    operation = _request_json(
        "POST",
        f"{CERT_API}/requestNew",
        token,
        {
            "folderId": folder_id,
            "name": name,
            "domains": domains,
            "challengeType": "DNS",
        },
    )
    created = wait_operation(token, operation)
    cert_id = str(created.get("id") or "")
    if cert_id:
        return get_certificate_full(token, cert_id)
    return created


def reconcile(
    *,
    token: str,
    folder_id: str,
    name: str,
    domains: list[str],
    dns_zone: str,
    allow_writes: bool,
) -> dict[str, Any]:
    existing_list = list_certificates(token, folder_id)
    existing = find_certificate_by_name(existing_list, name)
    plan = plan_reconcile(existing, name=name, domains=domains)
    certificate = existing
    requested = False
    if plan["action"] == "fail":
        raise RuntimeError(plan["reason"])
    if plan["action"] == "request":
        if not allow_writes:
            return {
                "action": "request",
                "requested": False,
                "status": "absent",
                "status_class": "absent",
                "challenge_statuses": [],
                "certificate_id": None,
                "dns_source": "none",
                "dns_records": [],
                "reason": plan["reason"] + " (writes disabled)",
            }
        certificate = request_managed_certificate(
            token, folder_id=folder_id, name=name, domains=domains
        )
        requested = True
        plan = plan_reconcile(certificate, name=name, domains=domains)
    if certificate and certificate.get("id") and not (certificate.get("challenges") or []):
        certificate = get_certificate_full(token, str(certificate["id"]))
    status = str((certificate or {}).get("status") or plan.get("status") or "")
    status_class = classify_status(status)
    challenge_statuses = extract_challenge_statuses(certificate)
    if status_class == "failed":
        raise RuntimeError(
            f"Certificate {name!r} is {status}. "
            f"Challenge statuses: {challenge_statuses}. "
            f"DNS challenges: {extract_dns_challenges(certificate)}"
        )
    selected, dns_source = select_dns_challenges(certificate, domains)
    records = challenges_to_cf_dns_records(selected, dns_zone)
    reason = str(plan["reason"])
    if status_class == "pending" and "PROCESSING" in challenge_statuses:
        reason = f"certificate {name!r} is {status}; DNS challenge PROCESSING"
    if dns_source == "canonical_renewal":
        reason = f"{reason}; ensuring renewal CNAME from certificate id"
    return {
        "action": "request" if requested else "none",
        "requested": requested,
        "status": status or "unknown",
        "status_class": status_class,
        "challenge_statuses": challenge_statuses,
        "certificate_id": (certificate or {}).get("id"),
        "dns_source": dns_source,
        "dns_records": records,
        "reason": reason,
    }


_load_sa_key = yc.load_sa_key
_read_text = yc.read_text
_token_from_args = yc.token_from_cli_args


def _cmd_print_desired(args: argparse.Namespace) -> int:
    data = {}
    for path in args.vars_file:
        with open(path, encoding="utf-8") as handle:
            loaded = __import__("yaml").safe_load(handle) or {}
        if isinstance(loaded, dict):
            data.update(loaded)
    desired = load_desired_from_vars(data)
    print("AntiBlock CDN wildcard certificate desired state (no API writes)")
    print(f"  name:      {desired['name']}")
    print(f"  domains:   {', '.join(desired['domains'])}")
    print(f"  challenge: {desired['challenge']}")
    print(f"  dns_zone:  {desired['dns_zone'] or '(unset)'}")
    print(f"  folder_id: {desired['folder_id'] or '(unset — required for apply)'}")
    print("  lookup:    by name (certificate UUID is not inventoried)")
    print("  writes:    none")
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    token = _token_from_args(args)
    result = reconcile(
        token=token,
        folder_id=args.folder_id,
        name=args.name,
        domains=args.domains,
        dns_zone=args.dns_zone,
        allow_writes=args.allow_writes,
    )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    desired = sub.add_parser("print-desired", help="Show inventory desired state (no API)")
    desired.add_argument("--vars-file", action="append", required=True)
    desired.set_defaults(func=_cmd_print_desired)

    recon = sub.add_parser("reconcile", help="Lookup/request certificate")
    recon.add_argument("--folder-id", required=True)
    recon.add_argument("--name", required=True)
    recon.add_argument("--domains", nargs="+", required=True)
    recon.add_argument("--dns-zone", required=True)
    recon.add_argument("--allow-writes", action="store_true")
    recon.add_argument("--sa-key-file", default="")
    recon.add_argument("--iam-token-file", default="")
    recon.add_argument("--sa-key-stdin", action="store_true")
    recon.add_argument("--iam-token-stdin", action="store_true")
    recon.set_defaults(func=_cmd_reconcile)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
