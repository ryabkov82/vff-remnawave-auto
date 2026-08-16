#!/usr/bin/env python3
"""Remnawave Host audit / match helpers (read-only analysis, no API calls).

API contract (Remnawave backend 3.2.3):
  GET  /api/hosts  — Host.tags: string[] (managed = marker in tags, not exclusive)
  PATCH /api/hosts  — UpdateHost is partial, but isDisabled has schema default false.
  Therefore every local PATCH helper must send the current Host.isDisabled.
  Omitted fields (nodes/inbound/tags/sni/etc.) stay unchanged; omitted isDisabled does not.
  No bulk remark endpoint exists.

  Write-path is 3.2.3 only (create uses tags: [managed_tag]).
  Read-side: normalize_host_tags() also accepts legacy 2.7.4 Host.tag when tags is absent.
  Report field ``tags`` is canonical; ``tag`` is a compatibility field (legacy
  singular value if present, otherwise the first normalized tag).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANAGED_TAG_DEFAULT = "VFF:MANAGED"
XHTTP_RE = re.compile(r"xhttp", re.IGNORECASE)
VFF_REMARK_RE = re.compile(r"vpn-for-friends", re.IGNORECASE)

# Forbidden substrings in audit artefacts (token / auth leakage).
SECRET_MARKERS = (
    "authorization",
    "bearer ",
    "api_token",
    "vault_remnawave_panel_api_token",
)


@dataclass
class CollisionGroup:
    key: str
    uuids: list[str]
    remarks: list[str]
    xhttp_related: bool = False


@dataclass
class AuditReport:
    hosts: list[dict[str, Any]] = field(default_factory=list)
    collisions: dict[str, list[CollisionGroup]] = field(default_factory=dict)
    unique_keys: list[str] = field(default_factory=list)
    colliding_keys: list[str] = field(default_factory=list)
    minimal_unique_key: str | None = None
    address_port_safe: bool = False
    inventory_matches: list[dict[str, Any]] = field(default_factory=list)
    api_only: list[dict[str, Any]] = field(default_factory=list)
    rename_required: list[dict[str, Any]] = field(default_factory=list)
    unmanaged: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_host_tags(host: dict[str, Any] | None) -> list[str]:
    """Return Host.tags as a list of non-empty strings (order preserved).

    Remnawave 3.2.3: missing / null / [] / non-list → [].
    Cheap 2.7.4 read compatibility: if ``tags`` is absent and singular ``tag``
    is a non-empty string, return [tag]. If ``tags`` is present, do not fall
    back to ``tag``.
    """
    if not host:
        return []
    if "tags" in host:
        tags = host.get("tags")
        if not isinstance(tags, list):
            return []
        out: list[str] = []
        for item in tags:
            if item is None:
                continue
            text = str(item)
            if text:
                out.append(text)
        return out
    tag = host.get("tag")
    if tag is None or tag == "":
        return []
    return [str(tag)]


def is_managed_host(
    host: dict[str, Any] | None,
    managed_tag: str = MANAGED_TAG_DEFAULT,
) -> bool:
    """True when ``managed_tag`` is present in normalized Host.tags."""
    return managed_tag in normalize_host_tags(host)


def _compat_host_tag(host: dict[str, Any], tags: list[str]) -> str | None:
    """Compatibility singular tag: legacy Host.tag if set, else first tags[] item."""
    if "tag" in host:
        raw = host.get("tag")
        if raw is not None and raw != "":
            return str(raw)
    return tags[0] if tags else None


def _format_tags(tags: list[str] | None) -> str:
    return ",".join(tags or [])


def normalize_node_uuids(nodes: Any) -> list[str]:
    """Normalize Host.nodes to a sorted list of node UUID strings."""
    out: list[str] = []
    for item in _as_list(nodes):
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            uuid = item.get("nodeUuid") or item.get("uuid") or item.get("node_uuid")
            if uuid:
                out.append(str(uuid))
    return sorted(set(out))


def inbound_uuids(host: dict[str, Any]) -> tuple[str, str]:
    inbound = host.get("inbound") or {}
    return (
        str(inbound.get("configProfileUuid") or ""),
        str(inbound.get("configProfileInboundUuid") or ""),
    )


def host_keys(host: dict[str, Any]) -> dict[str, str]:
    address = str(host.get("address") or "")
    port = int(host.get("port") or 0)
    profile_uuid, inbound_uuid = inbound_uuids(host)
    nodes = normalize_node_uuids(host.get("nodes"))
    nodes_key = ",".join(nodes)
    return {
        "A_remark": str(host.get("remark") or ""),
        "B_address_port": f"{address}|{port}",
        "C_address_port_inbound": f"{address}|{port}|{inbound_uuid}",
        "D_address_port_profile_inbound": f"{address}|{port}|{profile_uuid}|{inbound_uuid}",
        "E_endpoint_inbound_nodes": (
            f"{address}|{port}|{profile_uuid}|{inbound_uuid}|{nodes_key}"
        ),
    }


def is_xhttp_host(host: dict[str, Any], inbound_tag: str | None = None) -> bool:
    remark = str(host.get("remark") or "")
    path = str(host.get("path") or "")
    tag = inbound_tag or ""
    if XHTTP_RE.search(remark) or XHTTP_RE.search(tag) or XHTTP_RE.search(path):
        return True
    if path and path not in ("", "/"):
        # Non-empty path often indicates xHTTP; still require tag/remark when possible.
        if "xhttp" in path.lower() or "/api/" in path.lower():
            return True
    return False


def resolve_inbound_tag(
    host: dict[str, Any],
    inbound_by_uuid: dict[str, dict[str, Any]],
) -> str:
    _, inbound_uuid = inbound_uuids(host)
    if not inbound_uuid:
        return ""
    info = inbound_by_uuid.get(inbound_uuid) or {}
    return str(info.get("tag") or "")


def enrich_host(
    host: dict[str, Any],
    *,
    nodes_by_uuid: dict[str, str],
    inbound_by_uuid: dict[str, dict[str, Any]],
    managed_tag: str = MANAGED_TAG_DEFAULT,
) -> dict[str, Any]:
    profile_uuid, inbound_uuid = inbound_uuids(host)
    node_uuids = normalize_node_uuids(host.get("nodes"))
    node_names = [nodes_by_uuid.get(u, "") for u in node_uuids]
    inbound_tag = resolve_inbound_tag(host, inbound_by_uuid)
    tags = normalize_host_tags(host)
    managed = managed_tag in tags
    remark = str(host.get("remark") or "")
    return {
        "uuid": host.get("uuid"),
        "remark": remark,
        "address": host.get("address"),
        "port": host.get("port"),
        "inbound_configProfileUuid": profile_uuid or None,
        "inbound_configProfileInboundUuid": inbound_uuid or None,
        "inbound_tag": inbound_tag or None,
        "nodes": node_uuids,
        "node_names": [n for n in node_names if n],
        "tags": tags,
        "tag": _compat_host_tag(host, tags),
        "serverDescription": host.get("serverDescription"),
        "isHidden": host.get("isHidden"),
        "managed": managed,
        "managed_status": "managed" if managed else "unmanaged",
        "remark_contains_vpn_for_friends": bool(VFF_REMARK_RE.search(remark)),
        "is_xhttp": is_xhttp_host(host, inbound_tag),
        "keys": host_keys(host),
    }


def find_collisions(hosts: list[dict[str, Any]]) -> dict[str, list[CollisionGroup]]:
    """hosts must already be enriched (with keys)."""
    result: dict[str, list[CollisionGroup]] = {}
    key_names = [
        "A_remark",
        "B_address_port",
        "C_address_port_inbound",
        "D_address_port_profile_inbound",
        "E_endpoint_inbound_nodes",
    ]
    for key_name in key_names:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for h in hosts:
            buckets[h["keys"][key_name]].append(h)
        groups: list[CollisionGroup] = []
        for key, items in sorted(buckets.items(), key=lambda kv: kv[0]):
            if not key or key in ("|0|||", "|0||"):
                # Skip empty degenerate keys unless multiple empties collide.
                if len(items) < 2:
                    continue
            if len(items) > 1:
                groups.append(
                    CollisionGroup(
                        key=key,
                        uuids=[str(i["uuid"]) for i in items],
                        remarks=[str(i["remark"]) for i in items],
                        xhttp_related=any(bool(i.get("is_xhttp")) for i in items)
                        and any(not bool(i.get("is_xhttp")) for i in items),
                    )
                )
        result[key_name] = groups
    return result


def pick_minimal_unique_key(collisions: dict[str, list[CollisionGroup]]) -> tuple[str | None, bool]:
    """Return (minimal unique key name, address_port_safe)."""
    order = [
        "A_remark",
        "B_address_port",
        "C_address_port_inbound",
        "D_address_port_profile_inbound",
        "E_endpoint_inbound_nodes",
    ]
    address_port_safe = len(collisions.get("B_address_port") or []) == 0
    for name in order:
        if len(collisions.get(name) or []) == 0:
            return name, address_port_safe
    return None, address_port_safe


def select_candidates(
    existing: list[dict[str, Any]],
    *,
    match_by: str,
    remark: str,
    address: str,
    port: int,
    profile_uuid: str = "",
    inbound_uuid: str = "",
) -> list[dict[str, Any]]:
    """Select Host candidates. Never returns 'first' without caller counting."""
    if match_by == "remark":
        return [h for h in existing if str(h.get("remark") or "") == remark]
    if match_by == "address_port":
        return [
            h
            for h in existing
            if str(h.get("address") or "") == address and int(h.get("port") or 0) == int(port)
        ]
    if match_by == "endpoint_inbound":
        out = []
        for h in existing:
            if str(h.get("address") or "") != address:
                continue
            if int(h.get("port") or 0) != int(port):
                continue
            p, i = inbound_uuids(h)
            if p != profile_uuid or i != inbound_uuid:
                continue
            out.append(h)
        return out
    raise ValueError(f"unknown match_by: {match_by}")


def legacy_address_port_first(
    existing: list[dict[str, Any]],
    *,
    address: str,
    port: int,
) -> dict[str, Any] | None:
    """Legacy address_port behaviour: first match, ignores inbound collisions."""
    candidates = select_candidates(
        existing, match_by="address_port", remark="", address=address, port=port
    )
    return candidates[0] if candidates else None


def build_remark_update_payload(existing: dict[str, Any], new_remark: str) -> dict[str, Any]:
    """Safe 3.2.3 remark PATCH: uuid + remark + current isDisabled.

    UpdateHost is partial, but isDisabled defaults to false in the 3.2.3 schema.
    This helper is safe only because it copies the existing Host.isDisabled.
    Missing isDisabled is an error: defaulting to false would re-enable a
    disabled Host.
    """
    uuid = existing.get("uuid")
    if not uuid:
        raise ValueError("existing host missing uuid")
    if not (new_remark or "").strip():
        raise ValueError("desired remark is empty")
    if "isDisabled" not in existing:
        raise ValueError("existing host missing isDisabled")
    return {
        "uuid": str(uuid),
        "remark": new_remark,
        "isDisabled": bool(existing["isDisabled"]),
    }


def assert_rename_response(
    response_host: dict[str, Any],
    *,
    expected_uuid: str,
    expected_remark: str,
) -> None:
    got_uuid = str(response_host.get("uuid") or "")
    got_remark = str(response_host.get("remark") or "")
    if got_uuid != expected_uuid:
        raise AssertionError(f"UUID changed after update: {expected_uuid} -> {got_uuid}")
    if got_remark != expected_remark:
        raise AssertionError(
            f"remark not updated: expected={expected_remark!r} got={got_remark!r}"
        )


def match_inventory_to_api(
    desired: list[dict[str, Any]],
    api_hosts: list[dict[str, Any]],
    *,
    inbound_by_tag: dict[str, dict[str, Any]],
    managed_tag: str = MANAGED_TAG_DEFAULT,
    match_by: str = "endpoint_inbound",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (inventory_matches, api_only enriched summaries)."""
    claimed: set[str] = set()
    matches: list[dict[str, Any]] = []

    for item in desired:
        inv_host = item.get("inventory_host")
        remark = str(item.get("remark") or "")
        address = str(item.get("address") or "")
        port = int(item.get("port") or 443)
        inbound_tag = str(item.get("inbound_tag") or "")
        mapping = inbound_by_tag.get(inbound_tag) or {}
        profile_uuid = str(
            item.get("profile_uuid")
            or mapping.get("profile_uuid")
            or mapping.get("configProfileUuid")
            or ""
        )
        inbound_uuid = str(
            item.get("inbound_uuid")
            or mapping.get("inbound_uuid")
            or mapping.get("configProfileInboundUuid")
            or ""
        )

        row: dict[str, Any] = {
            "inventory_host": inv_host,
            "desired_remark": remark,
            "address": address,
            "port": port,
            "inbound_tag": inbound_tag,
            "api_uuid": None,
            "api_remark": None,
            "tags": [],
            "managed_tag": None,
            "match_by": match_by,
            "status": "missing",
        }

        try:
            candidates = select_candidates(
                api_hosts,
                match_by=match_by,
                remark=remark,
                address=address,
                port=port,
                profile_uuid=profile_uuid,
                inbound_uuid=inbound_uuid,
            )
        except ValueError:
            row["status"] = "ambiguous"
            row["error"] = f"unknown match_by={match_by}"
            matches.append(row)
            continue

        if len(candidates) == 0 and match_by != "remark":
            # Fallback: try exact remark for visibility.
            by_remark = select_candidates(
                api_hosts,
                match_by="remark",
                remark=remark,
                address=address,
                port=port,
            )
            if len(by_remark) == 1:
                candidates = by_remark
                row["match_by"] = "remark"
            elif len(by_remark) > 1:
                row["status"] = "ambiguous"
                row["candidate_uuids"] = [c.get("uuid") for c in by_remark]
                matches.append(row)
                continue

        if len(candidates) == 0:
            row["status"] = "missing"
            matches.append(row)
            continue

        if len(candidates) > 1:
            row["status"] = "ambiguous"
            row["candidate_uuids"] = [c.get("uuid") for c in candidates]
            matches.append(row)
            continue

        host = candidates[0]
        uuid = str(host.get("uuid"))
        claimed.add(uuid)
        api_remark = str(host.get("remark") or "")
        tags = normalize_host_tags(host)
        row["api_uuid"] = uuid
        row["api_remark"] = api_remark
        row["tags"] = tags
        # Compatibility: previously this field stored the singular Host.tag.
        row["managed_tag"] = _format_tags(tags) or None

        if managed_tag not in tags:
            row["status"] = "unmanaged_match"
            if api_remark != remark:
                row["rename_blocked"] = True
        elif api_remark == remark:
            row["status"] = "exact"
        else:
            row["status"] = "rename_required"

        matches.append(row)

    api_only: list[dict[str, Any]] = []
    for host in api_hosts:
        uuid = str(host.get("uuid"))
        if uuid in claimed:
            continue
        tags = normalize_host_tags(host)
        api_only.append(
            {
                "uuid": uuid,
                "remark": host.get("remark"),
                "address": host.get("address"),
                "port": host.get("port"),
                "tags": tags,
                "tag": _compat_host_tag(host, tags),
                "status": "api_only",
            }
        )

    return matches, api_only


def build_nodes_map(nodes: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in nodes:
        uuid = n.get("uuid")
        name = n.get("name")
        if uuid:
            out[str(uuid)] = str(name or "")
    return out


def build_inbound_by_uuid(inbounds: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in inbounds:
        uuid = item.get("uuid")
        if not uuid:
            continue
        out[str(uuid)] = {
            "tag": item.get("tag"),
            "profileUuid": item.get("profileUuid") or item.get("profile_uuid"),
            "uuid": uuid,
        }
    return out


def build_inbound_by_tag(inbounds: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in inbounds:
        tag = item.get("tag")
        if not tag:
            continue
        out[str(tag)] = {
            "inbound_uuid": str(item.get("uuid") or ""),
            "profile_uuid": str(item.get("profileUuid") or item.get("profile_uuid") or ""),
            "tag": str(tag),
        }
    return out


def build_audit_report(
    *,
    api_hosts: list[dict[str, Any]],
    nodes: list[dict[str, Any]] | None = None,
    inbounds: list[dict[str, Any]] | None = None,
    desired: list[dict[str, Any]] | None = None,
    managed_tag: str = MANAGED_TAG_DEFAULT,
    match_by: str = "endpoint_inbound",
) -> AuditReport:
    nodes = nodes or []
    inbounds = inbounds or []
    desired = desired or []
    nodes_by_uuid = build_nodes_map(nodes)
    inbound_by_uuid = build_inbound_by_uuid(inbounds)
    inbound_by_tag = build_inbound_by_tag(inbounds)

    enriched = [
        enrich_host(
            h,
            nodes_by_uuid=nodes_by_uuid,
            inbound_by_uuid=inbound_by_uuid,
            managed_tag=managed_tag,
        )
        for h in api_hosts
    ]
    collisions = find_collisions(enriched)
    unique = [k for k, groups in collisions.items() if len(groups) == 0]
    colliding = [k for k, groups in collisions.items() if len(groups) > 0]
    minimal, address_port_safe = pick_minimal_unique_key(collisions)

    matches, api_only = match_inventory_to_api(
        desired,
        api_hosts,
        inbound_by_tag=inbound_by_tag,
        managed_tag=managed_tag,
        match_by=match_by,
    )
    rename_required = [m for m in matches if m.get("status") == "rename_required"]
    unmanaged = [h for h in enriched if not h.get("managed")]

    return AuditReport(
        hosts=enriched,
        collisions={
            k: [
                {
                    "key": g.key,
                    "uuids": g.uuids,
                    "remarks": g.remarks,
                    "xhttp_related": g.xhttp_related,
                }
                for g in groups
            ]
            for k, groups in collisions.items()
        },
        unique_keys=unique,
        colliding_keys=colliding,
        minimal_unique_key=minimal,
        address_port_safe=address_port_safe,
        inventory_matches=matches,
        api_only=api_only,
        rename_required=rename_required,
        unmanaged=unmanaged,
        meta={
            "host_count": len(enriched),
            "managed_tag": managed_tag,
            "match_by": match_by,
            "api_update_contract": {
                "method": "PATCH",
                "path": "/api/hosts",
                "required": ["uuid"],
                "partial_remark_supported": True,
                "bulk_remark_endpoint": False,
                "confirmed_for": "Remnawave backend 3.2.3 UpdateHostCommand",
                "isDisabled_must_be_preserved": True,
            },
        },
    )


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    return {
        "meta": report.meta,
        "hosts": report.hosts,
        "collisions": report.collisions,
        "unique_keys": report.unique_keys,
        "colliding_keys": report.colliding_keys,
        "minimal_unique_key": report.minimal_unique_key,
        "address_port_safe": report.address_port_safe,
        "inventory_matches": report.inventory_matches,
        "api_only": report.api_only,
        "rename_required": report.rename_required,
        "unmanaged": [
            {
                "uuid": h.get("uuid"),
                "remark": h.get("remark"),
                "address": h.get("address"),
                "port": h.get("port"),
                "tags": h.get("tags"),
                "tag": h.get("tag"),
            }
            for h in report.unmanaged
        ],
    }


def render_markdown(report: AuditReport) -> str:
    lines: list[str] = []
    lines.append("# Remnawave Hosts Audit")
    lines.append("")
    lines.append(f"- Host count: **{report.meta.get('host_count', len(report.hosts))}**")
    lines.append(f"- Minimal unique key: `{report.minimal_unique_key}`")
    lines.append(f"- address_port safe: `{report.address_port_safe}`")
    lines.append(f"- Unique keys: {', '.join(f'`{k}`' for k in report.unique_keys) or '(none)'}")
    lines.append(
        f"- Colliding keys: {', '.join(f'`{k}`' for k in report.colliding_keys) or '(none)'}"
    )
    contract = (report.meta or {}).get("api_update_contract") or {}
    lines.append("")
    lines.append("## API update contract")
    lines.append("")
    lines.append(
        f"- `{contract.get('method')} {contract.get('path')}` "
        f"(required: {contract.get('required')})"
    )
    lines.append(
        f"- Partial remark PATCH supported: `{contract.get('partial_remark_supported')}`"
    )
    lines.append(f"- Bulk remark endpoint: `{contract.get('bulk_remark_endpoint')}`")
    lines.append(f"- Confirmed for: {contract.get('confirmed_for')}")
    lines.append("")
    lines.append("## Hosts")
    lines.append("")
    lines.append(
        "| uuid | remark | address | port | inbound_tag | nodes | tags | managed | xHTTP | vff |"
    )
    lines.append("|---|---|---|---:|---|---|---|---|---|---|")
    for h in report.hosts:
        nodes = ",".join(h.get("node_names") or h.get("nodes") or []) or "-"
        lines.append(
            "| {uuid} | {remark} | {address} | {port} | {itag} | {nodes} | {tags} | {managed} | {xhttp} | {vff} |".format(
                uuid=h.get("uuid"),
                remark=(h.get("remark") or "").replace("|", "\\|"),
                address=h.get("address"),
                port=h.get("port"),
                itag=(h.get("inbound_tag") or "-").replace("|", "\\|"),
                nodes=nodes.replace("|", "\\|"),
                tags=_format_tags(h.get("tags")) or "-",
                managed=h.get("managed_status"),
                xhttp="yes" if h.get("is_xhttp") else "no",
                vff="yes" if h.get("remark_contains_vpn_for_friends") else "no",
            )
        )

    lines.append("")
    lines.append("## Collisions")
    lines.append("")
    for key_name, groups in report.collisions.items():
        lines.append(f"### `{key_name}`")
        if not groups:
            lines.append("")
            lines.append("_unique_")
            lines.append("")
            continue
        lines.append("")
        lines.append("| key | uuids | remarks | Reality/xHTTP mix |")
        lines.append("|---|---|---|---|")
        for g in groups:
            lines.append(
                "| `{key}` | {uuids} | {remarks} | {mix} |".format(
                    key=g["key"].replace("|", "\\|"),
                    uuids=", ".join(g["uuids"]),
                    remarks="; ".join((r or "").replace("|", "\\|") for r in g["remarks"]),
                    mix="yes" if g.get("xhttp_related") else "no",
                )
            )
        lines.append("")

    lines.append("## Inventory ↔ API")
    lines.append("")
    lines.append(
        "| inventory | desired remark | address | port | inbound_tag | api uuid | api remark | tags | match | status |"
    )
    lines.append("|---|---|---|---:|---|---|---|---|---|---|")
    for m in report.inventory_matches:
        lines.append(
            "| {inv} | {desired} | {address} | {port} | {itag} | {uuid} | {api_remark} | {tags} | {match} | {status} |".format(
                inv=m.get("inventory_host"),
                desired=(m.get("desired_remark") or "").replace("|", "\\|"),
                address=m.get("address"),
                port=m.get("port"),
                itag=(m.get("inbound_tag") or "-").replace("|", "\\|"),
                uuid=m.get("api_uuid") or "-",
                api_remark=(m.get("api_remark") or "-").replace("|", "\\|"),
                tags=_format_tags(m.get("tags")) or m.get("managed_tag") or "-",
                match=m.get("match_by"),
                status=m.get("status"),
            )
        )

    if report.api_only:
        lines.append("")
        lines.append("## API-only Hosts")
        lines.append("")
        lines.append("| uuid | remark | address | port | tags |")
        lines.append("|---|---|---|---:|---|")
        for h in report.api_only:
            lines.append(
                f"| {h.get('uuid')} | {(h.get('remark') or '').replace('|', '\\|')} | "
                f"{h.get('address')} | {h.get('port')} | "
                f"{_format_tags(h.get('tags')) or h.get('tag') or '-'} |"
            )

    lines.append("")
    lines.append("## rename_required")
    lines.append("")
    if not report.rename_required:
        lines.append("_none_")
    else:
        for m in report.rename_required:
            lines.append(
                f"- `{m.get('api_uuid')}`: {m.get('api_remark')!r} → {m.get('desired_remark')!r} "
                f"({m.get('inventory_host')} {m.get('address')}:{m.get('port')})"
            )

    lines.append("")
    lines.append("## unmanaged")
    lines.append("")
    if not report.unmanaged:
        lines.append("_none_")
    else:
        for h in report.unmanaged:
            lines.append(
                f"- `{h.get('uuid')}` remark={h.get('remark')!r} "
                f"tags={h.get('tags')!r} {h.get('address')}:{h.get('port')}"
            )

    lines.append("")
    return "\n".join(lines)


def assert_no_secrets(text: str) -> None:
    lowered = text.lower()
    for marker in SECRET_MARKERS:
        if marker in lowered:
            raise AssertionError(f"secret marker found in report: {marker}")


def write_reports(report: AuditReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = report_to_dict(report)
    json_path = out_dir / "remnawave-hosts-audit.json"
    md_path = out_dir / "remnawave-hosts-audit.md"
    json_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    md_text = render_markdown(report)
    assert_no_secrets(json_text)
    assert_no_secrets(md_text)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build Remnawave hosts audit reports")
    parser.add_argument("--hosts-json", required=True, help="API GET /hosts response JSON file")
    parser.add_argument("--nodes-json", default="", help="API GET /nodes response JSON file")
    parser.add_argument(
        "--inbounds-json", default="", help="API GET config-profiles/inbounds JSON file"
    )
    parser.add_argument("--desired-json", default="", help="Desired inventory hosts JSON file")
    parser.add_argument("--out-dir", default="build", help="Output directory")
    parser.add_argument("--managed-tag", default=MANAGED_TAG_DEFAULT)
    parser.add_argument("--match-by", default="endpoint_inbound")
    args = parser.parse_args(argv)

    def load_list(path: str, *keys: str) -> list[dict[str, Any]]:
        if not path:
            return []
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            if "response" in raw:
                resp = raw["response"]
                if isinstance(resp, list):
                    return resp
                if isinstance(resp, dict):
                    for k in keys:
                        if k in resp and isinstance(resp[k], list):
                            return resp[k]
            for k in keys:
                if k in raw and isinstance(raw[k], list):
                    return raw[k]
        raise ValueError(f"cannot parse list from {path}")

    hosts = load_list(args.hosts_json, "hosts")
    nodes = load_list(args.nodes_json, "nodes")
    inbounds = load_list(args.inbounds_json, "inbounds")
    desired = load_list(args.desired_json, "desired")

    report = build_audit_report(
        api_hosts=hosts,
        nodes=nodes,
        inbounds=inbounds,
        desired=desired,
        managed_tag=args.managed_tag,
        match_by=args.match_by,
    )
    json_path, md_path = write_reports(report, Path(args.out_dir))
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"hosts={len(report.hosts)} address_port_safe={report.address_port_safe}")
    print(f"minimal_unique_key={report.minimal_unique_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
