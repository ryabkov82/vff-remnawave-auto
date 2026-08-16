#!/usr/bin/env python3
"""Remnawave AntiBlock Host plan / adopt / create helpers (current Host API).

Current Remnawave Host contract (not 2.7.4):
  ownership field: tags[]  (never singular tag)
  xHTTP params:    xhttpExtraParams  (never xHttpExtraParams / XHttpExtraParams)
  PATCH /api/hosts is partial: uuid required, other fields optional
  POST  /api/hosts creates
  allowInsecure is not part of the current Create/Update Host schema

Stage 6A/6B.1 never DELETEs. Ownership is VFF:ANTIBLOCK, not VFF:MANAGED.
Stage 6B.1 classifies stale owned Hosts; prune=true is still rejected.
"""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any

OWNER_TAG_DEFAULT = "VFF:ANTIBLOCK"
MANAGED_TAG_DEFAULT = "VFF:MANAGED"

LEGACY_PAYLOAD_KEYS = ("tag", "xHttpExtraParams", "XHttpExtraParams", "allowInsecure")

TRANSPORT_FIELDS = (
    "path",
    "sni",
    "host",
    "alpn",
    "fingerprint",
    "securityLayer",
    "isDisabled",
    "isHidden",
    "overrideSniFromAddress",
    "keepSniBlank",
    "shuffleHost",
    "mihomoX25519",
    "xhttpExtraParams",
    "nodes",
    "inbound",
)

BOOL_FIELDS = {
    "isDisabled",
    "isHidden",
    "overrideSniFromAddress",
    "keepSniBlank",
    "shuffleHost",
    "mihomoX25519",
}

CREATE_FIELDS = (
    "inbound",
    "remark",
    "address",
    "port",
    "path",
    "sni",
    "host",
    "alpn",
    "fingerprint",
    "securityLayer",
    "xhttpExtraParams",
    "tags",
    "isDisabled",
    "isHidden",
    "overrideSniFromAddress",
    "keepSniBlank",
    "shuffleHost",
    "mihomoX25519",
    "nodes",
)

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def normalize_host_tags(host: dict[str, Any] | None) -> list[str]:
    """Return Host.tags as a list. Current API only: never fall back to tag."""
    if not host:
        return []
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


def merge_owner_tags(existing_tags: Any, owner_tag: str) -> list[str]:
    """existing_tags + [owner_tag], unique, existing order preserved."""
    out: list[str] = []
    seen: set[str] = set()
    for item in _as_list(existing_tags):
        if item is None:
            continue
        text = str(item)
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    owner = str(owner_tag or "")
    if owner and owner not in seen:
        out.append(owner)
    return out


def is_antiblock_owned(host: dict[str, Any] | None, owner_tag: str = OWNER_TAG_DEFAULT) -> bool:
    """True only when owner_tag is in tags[]. VFF:MANAGED is never ownership."""
    return str(owner_tag) in normalize_host_tags(host)


def normalize_node_uuids(nodes: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _as_list(nodes):
        uuid = None
        if isinstance(item, str) and item:
            uuid = item
        elif isinstance(item, dict):
            uuid = item.get("nodeUuid") or item.get("uuid") or item.get("node_uuid")
        if not uuid:
            continue
        text = str(uuid)
        if text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def inbound_uuids(host: dict[str, Any] | None) -> tuple[str, str]:
    if not host:
        return "", ""
    inbound = host.get("inbound") or {}
    if not isinstance(inbound, dict):
        inbound = {}
    return (
        str(
            inbound.get("configProfileUuid")
            or host.get("configProfileUuid")
            or ""
        ),
        str(
            inbound.get("configProfileInboundUuid")
            or host.get("configProfileInboundUuid")
            or ""
        ),
    )


def identity_key(host: dict[str, Any] | None) -> tuple[str, int, str, str]:
    """Safe identity: address + port + profile UUID + inbound UUID."""
    if not host:
        return "", 0, "", ""
    profile_uuid, inbound_uuid = inbound_uuids(host)
    return (
        str(host.get("address") or ""),
        int(host.get("port") or 0),
        profile_uuid,
        inbound_uuid,
    )


def address_port_key(host: dict[str, Any] | None) -> tuple[str, int]:
    if not host:
        return "", 0
    return str(host.get("address") or ""), int(host.get("port") or 0)


def _coerce_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _is_number_str(value: str) -> bool:
    return bool(_NUMBER_RE.match(value.strip()))


def semantic_equal(left: Any, right: Any) -> bool:
    """Exact semantic equality for Host transport, including xhttpExtraParams."""
    left = _coerce_json(left)
    right = _coerce_json(right)
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(semantic_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(semantic_equal(item_l, item_r) for item_l, item_r in zip(left, right))
    if isinstance(left, bool) and isinstance(right, bool):
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, (int, float)) and isinstance(right, str) and _is_number_str(right):
        return float(left) == float(right)
    if isinstance(right, (int, float)) and isinstance(left, str) and _is_number_str(left):
        return float(left) == float(right)
    return left == right


def xhttp_params_equal(left: Any, right: Any) -> bool:
    return semantic_equal(left, right)


def assert_current_api_payload(payload: dict[str, Any], *, kind: str = "payload") -> None:
    """Refuse legacy Host API fields on any write body."""
    if not isinstance(payload, dict):
        raise ValueError(f"{kind} must be an object")
    for key in LEGACY_PAYLOAD_KEYS:
        if key in payload:
            raise ValueError(f"{kind} must not contain legacy field {key!r}")
    dumped = json.dumps(payload, ensure_ascii=False)
    for key in LEGACY_PAYLOAD_KEYS:
        if f'"{key}"' in dumped:
            raise ValueError(f"{kind} must not contain legacy field {key!r}")
    if "tags" in payload and not isinstance(payload.get("tags"), list):
        raise ValueError(f"{kind} tags must be an array")
    if "xhttpExtraParams" in payload:
        params = payload.get("xhttpExtraParams")
        if params is not None and not isinstance(params, dict):
            raise ValueError(f"{kind} xhttpExtraParams must be an object")
        if isinstance(params, dict) and "uplinkHTTPMethod" in params:
            if params.get("uplinkHTTPMethod") != "GET":
                raise ValueError(
                    f"{kind} xhttpExtraParams.uplinkHTTPMethod must be 'GET' "
                    f"(got {params.get('uplinkHTTPMethod')!r})"
                )


def _bool_or_default(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _transport_value(host: dict[str, Any], field: str) -> Any:
    if field == "nodes":
        return normalize_node_uuids(host.get("nodes"))
    if field == "inbound":
        profile_uuid, inbound_uuid = inbound_uuids(host)
        return {
            "configProfileUuid": profile_uuid,
            "configProfileInboundUuid": inbound_uuid,
        }
    if field == "xhttpExtraParams":
        return _coerce_json(host.get("xhttpExtraParams"))
    if field in BOOL_FIELDS:
        return _bool_or_default(host.get(field), False)
    if field == "port":
        return int(host.get("port") or 0)
    return host.get(field)


def transport_drift_fields(existing: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    drifted: list[str] = []
    for field in TRANSPORT_FIELDS:
        if not semantic_equal(_transport_value(existing, field), _transport_value(desired, field)):
            drifted.append(field)
    return drifted


def select_identity_candidates(
    existing: list[dict[str, Any]],
    desired: dict[str, Any],
) -> list[dict[str, Any]]:
    key = identity_key(desired)
    return [host for host in existing if identity_key(host) == key]


def select_address_port_candidates(
    existing: list[dict[str, Any]],
    desired: dict[str, Any],
) -> list[dict[str, Any]]:
    key = address_port_key(desired)
    return [host for host in existing if address_port_key(host) == key]


def validate_trusted_ingress_ips(value: Any) -> list[str]:
    """Fail-fast check for the curated IPv4 pool. No DNS, order preserved."""
    if isinstance(value, (str, bytes)) or value is None:
        raise ValueError("antiblock_cdn_trusted_ingress_ips must be a list")
    if not isinstance(value, (list, tuple)):
        # ansible-lint JinjaRule may pass a non-list mock; do not crash the linter.
        return []
    if len(value) == 0:
        raise ValueError("antiblock_cdn_trusted_ingress_ips must not be empty")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item is None:
            raise ValueError("antiblock_cdn_trusted_ingress_ips contains an empty value")
        text = str(item).strip()
        try:
            parsed = ipaddress.IPv4Address(text)
        except (ipaddress.AddressValueError, ValueError) as exc:
            raise ValueError(
                f"antiblock_cdn_trusted_ingress_ips must contain only IPv4 addresses: {text!r}"
            ) from exc
        ip = str(parsed)
        if ip in seen:
            raise ValueError(f"antiblock_cdn_trusted_ingress_ips has duplicate IP: {ip}")
        out.append(ip)
        seen.add(ip)
    return out


def desired_remark(inventory_hostname: str, address: str, public_hostname: str, index: int) -> str:
    """Deterministic remark for future Hosts. Adoption never renames existing ones."""
    host = str(inventory_hostname or "").strip() or str(public_hostname or "").strip() or address
    if index <= 0:
        return f"{host} (xHTTP, CDN)"
    return f"{host} (xHTTP, CDN) {index + 1}"


def build_desired_antiblock_hosts(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Build desired Hosts from public hostname + static ingress IPs."""
    public_hostname = str(ctx.get("public_hostname") or "").strip()
    if not public_hostname:
        raise ValueError("public_hostname is required")
    if "ingress_ips" in ctx:
        raise ValueError("ingress_ips is not supported; use trusted_ingress_ips")
    ingress_ips = validate_trusted_ingress_ips(ctx.get("trusted_ingress_ips"))
    addresses: list[str] = []
    seen: set[str] = set()
    for address in [public_hostname, *ingress_ips]:
        if address in seen:
            continue
        addresses.append(address)
        seen.add(address)

    owner_tag = str(ctx.get("owner_tag") or OWNER_TAG_DEFAULT)
    node_uuid = str(ctx.get("node_uuid") or "")
    profile_uuid = str(ctx.get("profile_uuid") or "")
    inbound_uuid = str(ctx.get("inbound_uuid") or "")
    inventory_hostname = str(ctx.get("inventory_hostname") or "")
    xhttp = ctx.get("xhttp_extra_params") or ctx.get("xhttpExtraParams") or {}
    if not isinstance(xhttp, dict):
        raise ValueError("xhttp_extra_params must be an object")

    desired: list[dict[str, Any]] = []
    for index, address in enumerate(addresses):
        item = {
            "remark": desired_remark(inventory_hostname, address, public_hostname, index),
            "address": address,
            "port": int(ctx.get("port") or 443),
            "path": str(ctx.get("path") or ""),
            "sni": str(ctx.get("sni") or public_hostname),
            "host": str(ctx.get("host") or public_hostname),
            "alpn": str(ctx.get("alpn") or "h2,http/1.1"),
            "fingerprint": str(ctx.get("fingerprint") or "firefox"),
            "securityLayer": str(ctx.get("security_layer") or ctx.get("securityLayer") or "TLS"),
            "xhttpExtraParams": xhttp,
            "tags": [owner_tag],
            "isDisabled": _bool_or_default(ctx.get("is_disabled", ctx.get("isDisabled")), False),
            "isHidden": _bool_or_default(ctx.get("is_hidden", ctx.get("isHidden")), False),
            "overrideSniFromAddress": _bool_or_default(
                ctx.get("override_sni_from_address", ctx.get("overrideSniFromAddress")),
                False,
            ),
            "keepSniBlank": _bool_or_default(ctx.get("keep_sni_blank", ctx.get("keepSniBlank")), False),
            "shuffleHost": _bool_or_default(ctx.get("shuffle_host", ctx.get("shuffleHost")), False),
            "mihomoX25519": _bool_or_default(ctx.get("mihomo_x25519", ctx.get("mihomoX25519")), False),
            "nodes": [node_uuid] if node_uuid else [],
            "inbound": {
                "configProfileUuid": profile_uuid,
                "configProfileInboundUuid": inbound_uuid,
            },
        }
        desired.append(item)
    return desired


def build_create_payload(desired: dict[str, Any], *, owner_tag: str = OWNER_TAG_DEFAULT) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in CREATE_FIELDS:
        if field == "tags":
            payload["tags"] = merge_owner_tags([], owner_tag)
            continue
        if field == "xhttpExtraParams":
            payload["xhttpExtraParams"] = desired.get("xhttpExtraParams") or {}
            continue
        if field == "nodes":
            payload["nodes"] = normalize_node_uuids(desired.get("nodes"))
            continue
        if field == "inbound":
            profile_uuid, inbound_uuid = inbound_uuids(desired)
            payload["inbound"] = {
                "configProfileUuid": profile_uuid,
                "configProfileInboundUuid": inbound_uuid,
            }
            continue
        if field in BOOL_FIELDS:
            payload[field] = _bool_or_default(desired.get(field), False)
            continue
        if field == "port":
            payload["port"] = int(desired.get("port") or 443)
            continue
        payload[field] = desired.get(field)
    assert_current_api_payload(payload, kind="create")
    return payload


def build_partial_patch(
    existing: dict[str, Any],
    desired: dict[str, Any],
    drift_fields: list[str],
    *,
    owner_tag: str = OWNER_TAG_DEFAULT,
) -> dict[str, Any]:
    uuid = str(existing.get("uuid") or "")
    if not uuid:
        raise ValueError("existing host missing uuid")
    body: dict[str, Any] = {"uuid": uuid}
    for field in drift_fields:
        if field == "tags":
            body["tags"] = merge_owner_tags(normalize_host_tags(existing), owner_tag)
        elif field == "inbound":
            profile_uuid, inbound_uuid = inbound_uuids(desired)
            body["inbound"] = {
                "configProfileUuid": profile_uuid,
                "configProfileInboundUuid": inbound_uuid,
            }
        elif field == "nodes":
            body["nodes"] = normalize_node_uuids(desired.get("nodes"))
        elif field == "xhttpExtraParams":
            body["xhttpExtraParams"] = desired.get("xhttpExtraParams") or {}
        elif field in BOOL_FIELDS:
            body[field] = _bool_or_default(desired.get(field), False)
        elif field == "port":
            body["port"] = int(desired.get("port") or 443)
        else:
            body[field] = desired.get(field)
    assert_current_api_payload(body, kind="patch")
    return body


def is_ipv4_address(value: Any) -> bool:
    try:
        ipaddress.IPv4Address(str(value or "").strip())
    except (ipaddress.AddressValueError, ValueError):
        return False
    return True


def host_in_antiblock_scope(
    host: dict[str, Any],
    *,
    owner_tag: str,
    node_uuid: str,
    profile_uuid: str,
    inbound_uuid: str,
) -> bool:
    """True when Host is owned and bound to this node + AntiBlock inbound."""
    if not (node_uuid and profile_uuid and inbound_uuid):
        return False
    if not is_antiblock_owned(host, owner_tag):
        return False
    profile, inbound = inbound_uuids(host)
    if profile != profile_uuid or inbound != inbound_uuid:
        return False
    return node_uuid in normalize_node_uuids(host.get("nodes"))


def classify_prune_eligibility(
    host: dict[str, Any],
    *,
    owner_tag: str,
    node_uuid: str,
    public_hostname: str,
) -> tuple[bool, str | None]:
    """Conservative future-prune eligibility. Never implies a DELETE write."""
    uuid = str(host.get("uuid") or "").strip()
    if not uuid:
        return False, "missing_uuid"
    address = str(host.get("address") or "").strip()
    if public_hostname and address == str(public_hostname).strip():
        return False, "public_hostname"
    if not is_ipv4_address(address):
        return False, "non_ipv4_address"
    if normalize_host_tags(host) != [owner_tag]:
        return False, "extra_tags"
    if normalize_node_uuids(host.get("nodes")) != [node_uuid]:
        return False, "multiple_nodes"
    return True, None


def classify_stale_hosts(
    existing: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    *,
    owner_tag: str,
    node_uuid: str,
    profile_uuid: str,
    inbound_uuid: str,
    public_hostname: str,
) -> list[dict[str, Any]]:
    """Stale VFF:ANTIBLOCK Hosts for the current node/inbound only. No DELETE."""
    desired_identities = {identity_key(item) for item in desired}
    stale_items: list[dict[str, Any]] = []
    for host in existing:
        if not host_in_antiblock_scope(
            host,
            owner_tag=owner_tag,
            node_uuid=node_uuid,
            profile_uuid=profile_uuid,
            inbound_uuid=inbound_uuid,
        ):
            continue
        key = identity_key(host)
        if key in desired_identities:
            continue
        eligible, reason = classify_prune_eligibility(
            host,
            owner_tag=owner_tag,
            node_uuid=node_uuid,
            public_hostname=public_hostname,
        )
        stale_items.append(
            {
                "uuid": str(host.get("uuid") or "") or None,
                "address": host.get("address"),
                "port": int(host.get("port") or 0),
                "identity": _format_identity(key),
                "tags": normalize_host_tags(host),
                "nodes": normalize_node_uuids(host.get("nodes")),
                "prune_eligible": eligible,
                "block_reason": reason,
            }
        )
    return stale_items


def _format_identity(key: tuple[str, int, str, str]) -> str:
    address, port, profile_uuid, inbound_uuid = key
    return (
        f"address={address} port={port} "
        f"configProfileUuid={profile_uuid} configProfileInboundUuid={inbound_uuid}"
    )


def plan_antiblock_hosts(
    desired: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    owner_tag: str = OWNER_TAG_DEFAULT,
    allow_writes: bool = False,
    prune: bool = False,
    node_uuid: str = "",
    profile_uuid: str = "",
    inbound_uuid: str = "",
    public_hostname: str = "",
) -> dict[str, Any]:
    """Plan adopt / create / managed reconcile. Classify stale Hosts. Never DELETE."""
    if prune:
        raise ValueError("antiblock_cdn_hosts_prune is not supported in Stage 6B.1")

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    writes: list[dict[str, Any]] = []
    matched = 0
    create = 0
    update = 0
    adopt = 0
    ambiguous = 0

    for desired_host in desired:
        key = identity_key(desired_host)
        candidates = select_identity_candidates(existing, desired_host)
        row: dict[str, Any] = {
            "address": desired_host.get("address"),
            "port": desired_host.get("port"),
            "identity": _format_identity(key),
            "action": "missing",
            "uuid": None,
            "existing_remark": None,
            "desired_remark": desired_host.get("remark"),
            "owned": False,
            "drift_fields": [],
            "candidate_uuids": [str(item.get("uuid") or "") for item in candidates],
        }

        if len(candidates) > 1:
            ambiguous += 1
            row["action"] = "ambiguous"
            errors.append(
                "Ambiguous Host match for "
                f"{row['identity']} candidate_uuids={row['candidate_uuids']}. "
                "Refusing to pick first or create."
            )
            items.append(row)
            continue

        if len(candidates) == 0:
            create += 1
            row["action"] = "create"
            row["drift_fields"] = ["*"]
            if allow_writes:
                writes.append(
                    {
                        "method": "POST",
                        "path": "/api/hosts",
                        "body": build_create_payload(desired_host, owner_tag=owner_tag),
                        "drift_fields": ["*"],
                        "action": "create",
                    }
                )
            items.append(row)
            continue

        existing_host = candidates[0]
        matched += 1
        owned = is_antiblock_owned(existing_host, owner_tag)
        existing_tags = normalize_host_tags(existing_host)
        desired_tags = merge_owner_tags(existing_tags, owner_tag)
        tags_drift = existing_tags != desired_tags
        transport_drift = transport_drift_fields(existing_host, desired_host)

        row["uuid"] = str(existing_host.get("uuid") or "")
        row["existing_remark"] = existing_host.get("remark")
        row["owned"] = owned
        row["existing_tags"] = existing_tags
        row["desired_tags"] = desired_tags

        if not owned:
            if transport_drift:
                row["action"] = "unmanaged_transport_drift"
                row["drift_fields"] = transport_drift
                errors.append(
                    "Unmanaged Host uuid="
                    f"{row['uuid']} {row['identity']} transport drift={transport_drift}. "
                    "Refusing to mutate unmanaged production Host."
                )
                items.append(row)
                continue
            if not tags_drift:
                row["action"] = "noop"
                items.append(row)
                continue
            row["action"] = "adopt"
            row["drift_fields"] = ["tags"]
            adopt += 1
            update += 1
            if allow_writes:
                writes.append(
                    {
                        "method": "PATCH",
                        "path": "/api/hosts",
                        "body": {
                            "uuid": row["uuid"],
                            "tags": desired_tags,
                        },
                        "drift_fields": ["tags"],
                        "action": "adopt",
                    }
                )
            items.append(row)
            continue

        drift_fields = list(transport_drift)
        if tags_drift:
            drift_fields.append("tags")
        if not drift_fields:
            row["action"] = "noop"
            items.append(row)
            continue

        row["action"] = "update"
        row["drift_fields"] = drift_fields
        update += 1
        if allow_writes:
            writes.append(
                {
                    "method": "PATCH",
                    "path": "/api/hosts",
                    "body": build_partial_patch(
                        existing_host,
                        desired_host,
                        drift_fields,
                        owner_tag=owner_tag,
                    ),
                    "drift_fields": drift_fields,
                    "action": "update",
                }
            )
        items.append(row)

    for write in writes:
        if str(write.get("method") or "").upper() == "DELETE":
            raise ValueError("AntiBlock Host plan must never emit DELETE")
        assert_current_api_payload(write["body"], kind=write["action"])

    stale_items = classify_stale_hosts(
        existing,
        desired,
        owner_tag=owner_tag,
        node_uuid=str(node_uuid or ""),
        profile_uuid=str(profile_uuid or ""),
        inbound_uuid=str(inbound_uuid or ""),
        public_hostname=str(public_hostname or ""),
    )
    prune_eligible = sum(1 for row in stale_items if row.get("prune_eligible"))
    prune_blocked = len(stale_items) - prune_eligible

    ok = not errors
    summary = (
        f"desired={len(desired)} matched={matched} create={create} "
        f"update={update} adopt={adopt} stale={len(stale_items)} "
        f"prune_eligible={prune_eligible} prune_blocked={prune_blocked} "
        f"delete=0 ambiguous={ambiguous}"
    )
    safe_writes = writes if (allow_writes and ok) else []
    if any(str(item.get("method") or "").upper() == "DELETE" for item in safe_writes):
        raise ValueError("AntiBlock Host plan must never emit DELETE")
    return {
        "ok": ok,
        "error": "; ".join(errors) if errors else None,
        "errors": errors,
        "summary": summary,
        "desired": len(desired),
        "matched": matched,
        "create": create,
        "update": update,
        "adopt": adopt,
        "stale": len(stale_items),
        "prune_eligible": prune_eligible,
        "prune_blocked": prune_blocked,
        "delete": 0,
        "ambiguous": ambiguous,
        "items": items,
        "stale_items": stale_items,
        "writes": safe_writes,
        "allow_writes": bool(allow_writes),
        "prune": False,
    }


def verify_antiblock_hosts(
    desired: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    owner_tag: str = OWNER_TAG_DEFAULT,
    expected_uuids: list[str] | None = None,
) -> dict[str, Any]:
    """Re-GET assertions: one Host per identity, owner tag, transport, UUIDs."""
    errors: list[str] = []
    seen_uuids: list[str] = []

    for desired_host in desired:
        candidates = select_identity_candidates(existing, desired_host)
        key = identity_key(desired_host)
        label = _format_identity(key)
        if len(candidates) != 1:
            errors.append(
                f"expected exactly one Host for {label}, found {len(candidates)} "
                f"uuids={[c.get('uuid') for c in candidates]}"
            )
            continue
        host = candidates[0]
        uuid = str(host.get("uuid") or "")
        seen_uuids.append(uuid)
        if not is_antiblock_owned(host, owner_tag):
            errors.append(f"owner tag {owner_tag!r} missing on uuid={uuid}")
        drift = transport_drift_fields(host, desired_host)
        if drift:
            errors.append(f"transport drift after write uuid={uuid} fields={drift}")
        if not xhttp_params_equal(host.get("xhttpExtraParams"), desired_host.get("xhttpExtraParams")):
            errors.append(f"xhttpExtraParams mismatch uuid={uuid}")
        if normalize_node_uuids(host.get("nodes")) != normalize_node_uuids(desired_host.get("nodes")):
            errors.append(f"nodes mismatch uuid={uuid}")
        if inbound_uuids(host) != inbound_uuids(desired_host):
            errors.append(f"inbound/profile mismatch uuid={uuid}")

    if expected_uuids is not None:
        if seen_uuids != list(expected_uuids):
            errors.append(
                f"UUID preservation failed: expected={list(expected_uuids)} got={seen_uuids}"
            )

    return {
        "ok": not errors,
        "errors": errors,
        "uuids": seen_uuids,
    }


def plan_from_filter(
    existing: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = opts or {}
    return plan_antiblock_hosts(
        desired,
        existing,
        owner_tag=str(options.get("owner_tag") or OWNER_TAG_DEFAULT),
        allow_writes=bool(options.get("allow_writes", False)),
        prune=bool(options.get("prune", False)),
        node_uuid=str(options.get("node_uuid") or ""),
        profile_uuid=str(options.get("profile_uuid") or ""),
        inbound_uuid=str(options.get("inbound_uuid") or ""),
        public_hostname=str(options.get("public_hostname") or ""),
    )


def verify_from_filter(
    existing: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = opts or {}
    expected = options.get("expected_uuids")
    return verify_antiblock_hosts(
        desired,
        existing,
        owner_tag=str(options.get("owner_tag") or OWNER_TAG_DEFAULT),
        expected_uuids=list(expected) if expected is not None else None,
    )
