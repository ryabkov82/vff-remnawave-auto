#!/usr/bin/env python3
"""Yandex Cloud CDN origin-group + resource reconcile (one node = one resource).

Lookup is by stable origin-group name and resource CNAME. IDs are runtime-only
and are never inventoried. Writes (POST/PATCH) require --allow-writes. DELETE
is not implemented.

Auth: the same service-account JWT -> IAM token path as Certificate Manager
(see yandex_cloud_common). Interactive `yc init` is not used.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yandex_certificate_manager as ycm  # noqa: E402
import yandex_cloud_common as yc  # noqa: E402

CDN_API = "https://cdn.api.cloud.yandex.net/cdn/v1"
ORIGIN_GROUPS_URL = f"{CDN_API}/originGroups"
RESOURCES_URL = f"{CDN_API}/resources"

PROVIDER_TYPE = "ourcdn"
ORIGIN_PROTOCOL = "HTTPS"
TLS_PROFILE = "PROFILE_COMPATIBLE"
CERT_MODE_WILDCARD = "shared_wildcard"
CERT_MODE_LEGACY = "legacy_existing"
WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

MANAGED_OPTION_KEYS = (
    "edgeCacheSettings",
    "browserCacheSettings",
    "queryParamsOptions",
    "hostOptions",
    "allowedHttpMethods",
    "customServerName",
    "ignoreCookie",
    "secureKey",
)

# Production de-fra-2 omits options.disableCache. Cache-off is
# edgeCacheSettings.enabled=false and browserCacheSettings.enabled=false.
CACHE_TOGGLE_KEYS = ("edgeCacheSettings", "browserCacheSettings")


def normalize_host(value: Any) -> str:
    return str(value or "").strip().rstrip(".").lower()


def relative_record_name(fqdn: str, zone: str) -> str:
    return ycm.relative_record_name(fqdn, zone)


def empty_option(value: Any) -> bool:
    return value in (None, {}, [], "", False)


def _normalize_host_option(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"host", "value"} and isinstance(item, str):
            out[key] = normalize_host(item) if key == "value" else _normalize_host_option(item)
        elif isinstance(item, dict):
            out[key] = _normalize_host_option(item)
        else:
            out[key] = item
    return out


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {key: _drop_empty(item) for key, item in value.items()}
        cleaned = {key: item for key, item in cleaned.items() if not empty_option(item)}
        return cleaned
    if isinstance(value, list):
        return [_drop_empty(item) for item in value]
    return value


def signing_disabled(secure_key: Any) -> bool:
    if empty_option(secure_key) or not isinstance(secure_key, dict):
        return True
    stype = str(secure_key.get("type") or "").upper()
    enabled = secure_key.get("enabled")
    if stype in {"", "DISABLE_IP_SIGNING"}:
        return True
    return enabled is not True


def _normalize_cache_toggle(value: Any) -> dict[str, Any]:
    """Compare CDN/browser cache only by enabled. Missing/{} means disabled."""
    enabled = False
    if isinstance(value, dict):
        enabled = bool(value.get("enabled"))
    return {"enabled": enabled}


def desired_managed_options(origin_hostname: str) -> dict[str, Any]:
    host = str(origin_hostname).strip().rstrip(".")
    return {
        # Transport/front, not a content cache. Matches working de-fra-2 GET:
        # edge/browser {enabled: false}; disableCache is absent on that resource.
        "edgeCacheSettings": {"enabled": False},
        "browserCacheSettings": {"enabled": False},
        "queryParamsOptions": {
            "ignoreQueryString": {"enabled": True, "value": True},
        },
        "hostOptions": {
            "host": {"enabled": True, "value": host},
        },
        "allowedHttpMethods": {
            "enabled": True,
            "value": ["GET", "HEAD", "OPTIONS"],
        },
        "customServerName": {"enabled": True, "value": host},
        "ignoreCookie": {"enabled": True, "value": True},
        "secureKey": {"enabled": False, "type": "DISABLE_IP_SIGNING"},
    }


def normalize_managed_options(options: dict[str, Any] | None) -> dict[str, Any]:
    raw = options or {}
    out: dict[str, Any] = {}
    for key in MANAGED_OPTION_KEYS:
        value = raw.get(key)
        if key == "secureKey":
            out[key] = {"disabled": signing_disabled(value)}
            continue
        if key in CACHE_TOGGLE_KEYS:
            out[key] = _normalize_cache_toggle(value)
            continue
        if key == "allowedHttpMethods":
            methods = []
            if isinstance(value, dict):
                methods = [str(item).upper() for item in (value.get("value") or [])]
            out[key] = {
                "enabled": bool(value.get("enabled")) if isinstance(value, dict) else False,
                "value": sorted(methods),
            }
            continue
        cleaned = _drop_empty(value) if isinstance(value, dict) else {}
        if key in {"hostOptions", "customServerName"}:
            cleaned = _normalize_host_option(cleaned)
        out[key] = cleaned
    return out


def managed_options_equal(actual: dict[str, Any] | None, desired: dict[str, Any]) -> bool:
    return normalize_managed_options(actual) == normalize_managed_options(desired)


def merge_resource_options(
    current: dict[str, Any] | None, desired_managed: dict[str, Any]
) -> dict[str, Any]:
    """Overlay managed fields onto the current options object.

    Unmanaged keys (compression, ACLs, …) are preserved.
    Empty default objects stay as they are so PATCH is not destructive.
    """
    merged = dict(current or {})
    for key, value in desired_managed.items():
        merged[key] = value
    return merged


def normalize_origin_protocol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.endswith("HTTPS") or text == "HTTPS":
        return "HTTPS"
    if text.endswith("HTTP") or text == "HTTP":
        return "HTTP"
    if "MATCH" in text:
        return "MATCH"
    return text


def normalize_origin(origin: dict[str, Any]) -> dict[str, Any]:
    enabled = origin.get("enabled")
    backup = origin.get("backup")
    return {
        "source": normalize_host(origin.get("source")),
        "enabled": True if enabled is None else bool(enabled),
        "backup": False if backup is None else bool(backup),
    }


def desired_origins(origin_hostname: str) -> list[dict[str, Any]]:
    return [
        {
            "source": str(origin_hostname).strip().rstrip("."),
            "enabled": True,
            "backup": False,
        }
    ]


def origins_equal(actual: list[dict[str, Any]] | None, origin_hostname: str) -> bool:
    have = [normalize_origin(item) for item in (actual or []) if isinstance(item, dict)]
    want = [normalize_origin(item) for item in desired_origins(origin_hostname)]
    return have == want


def resources_metadata(group: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = yc.api_get(group, "resourcesMetadata", "resources_metadata", default=[]) or []
    return [item for item in raw if isinstance(item, dict)]


def find_unique_by_name(
    items: list[dict[str, Any]], name: str, *, kind: str
) -> dict[str, Any] | None:
    want = str(name or "").strip()
    matches = [item for item in items if str(item.get("name") or "") == want]
    if len(matches) > 1:
        ids = [str(item.get("id") or "?") for item in matches]
        raise RuntimeError(
            f"Duplicate {kind} named {want!r}; refusing to pick one. ids={ids}"
        )
    return matches[0] if matches else None


def find_resource_by_cname(
    resources: list[dict[str, Any]], cname: str
) -> dict[str, Any] | None:
    want = normalize_host(cname)
    matches = [
        item for item in resources if normalize_host(item.get("cname")) == want
    ]
    if len(matches) > 1:
        ids = [str(item.get("id") or "?") for item in matches]
        raise RuntimeError(
            f"Duplicate CDN resources with cname {cname!r}; refusing to pick one. ids={ids}"
        )
    return matches[0] if matches else None


def ssl_certificate_id(resource: dict[str, Any] | None) -> str:
    cert = yc.api_get(resource, "sslCertificate", "ssl_certificate", default={}) or {}
    data = yc.api_get(cert, "data", default={}) or {}
    cm = yc.api_get(data, "cm", default={}) or {}
    return str(yc.api_get(cm, "id", default="") or "").strip()


def provider_cname_of(resource: dict[str, Any] | None) -> str:
    return str(
        yc.api_get(resource, "providerCname", "provider_cname", default="") or ""
    ).strip().rstrip(".")


def tls_profile_of(resource: dict[str, Any] | None) -> str:
    tls = yc.api_get(resource, "tls", default={}) or {}
    return str(yc.api_get(tls, "profile", default="") or "").strip().upper()


def origin_group_id_of(resource: dict[str, Any] | None) -> str:
    return str(
        yc.api_get(resource, "originGroupId", "origin_group_id", default="") or ""
    ).strip()


def is_legacy_node(certificate_mode: str) -> bool:
    return str(certificate_mode or "").strip() == CERT_MODE_LEGACY


def manage_certificate(certificate_mode: str) -> bool:
    return str(certificate_mode or "").strip() == CERT_MODE_WILDCARD


def public_cname_records(
    public_hostname: str, zone: str, provider_cname: str
) -> list[dict[str, Any]]:
    target = str(provider_cname or "").strip().rstrip(".")
    if not target:
        return []
    return [
        {
            "name": relative_record_name(public_hostname, zone),
            "type": "CNAME",
            "value": target,
            "proxied": False,
            "solo": True,
        }
    ]


def legacy_origin_group_guard(
    group: dict[str, Any],
    *,
    origin_group_name: str,
    public_hostname: str,
) -> None:
    actual_name = str(group.get("name") or "")
    if actual_name != origin_group_name:
        raise RuntimeError(
            f"Legacy origin group name {actual_name!r} != desired {origin_group_name!r}; "
            "refusing rename/adoption."
        )
    origins = [item for item in (group.get("origins") or []) if isinstance(item, dict)]
    if len(origins) != 1:
        sources = [item.get("source") for item in origins]
        raise RuntimeError(
            f"Legacy origin group {origin_group_name!r} has {len(origins)} origins "
            f"{sources}; refusing destructive single-origin adoption."
        )
    meta = resources_metadata(group)
    if len(meta) > 1:
        cnames = [item.get("cname") for item in meta]
        raise RuntimeError(
            f"Legacy origin group {origin_group_name!r} is attached to multiple CDN "
            f"resources {cnames}; refusing adoption."
        )
    if len(meta) == 1:
        attached = normalize_host(meta[0].get("cname"))
        if attached != normalize_host(public_hostname):
            raise RuntimeError(
                f"Legacy origin group {origin_group_name!r} is attached to unrelated "
                f"resource cname {meta[0].get('cname')!r}; expected {public_hostname!r}."
            )


def unrelated_resource_guard(
    group: dict[str, Any], *, public_hostname: str, origin_group_name: str
) -> None:
    meta = resources_metadata(group)
    unexpected = [
        item
        for item in meta
        if normalize_host(item.get("cname")) != normalize_host(public_hostname)
    ]
    if unexpected:
        cnames = [item.get("cname") for item in unexpected]
        raise RuntimeError(
            f"Origin group {origin_group_name!r} is attached to unrelated CDN "
            f"resources {cnames}; refusing to reuse it."
        )


def plan_origin_group(
    existing: dict[str, Any] | None,
    *,
    name: str,
    origin_hostname: str,
    use_next: bool,
    public_hostname: str,
    legacy: bool,
) -> dict[str, Any]:
    if existing is None:
        return {
            "action": "create",
            "reason": f"origin group {name!r} is absent",
        }
    if legacy:
        legacy_origin_group_guard(
            existing, origin_group_name=name, public_hostname=public_hostname
        )
    else:
        unrelated_resource_guard(
            existing, public_hostname=public_hostname, origin_group_name=name
        )
    drift: list[str] = []
    if bool(existing.get("useNext", existing.get("use_next", True))) != bool(use_next):
        drift.append("use_next")
    if not origins_equal(existing.get("origins"), origin_hostname):
        if legacy and len(existing.get("origins") or []) != 1:
            # Guard already failed; keep for completeness.
            drift.append("origins")
        else:
            drift.append("origins")
    if not drift:
        return {
            "action": "none",
            "reason": f"origin group {name!r} already matches desired state",
        }
    if legacy and "origins" in drift and len(existing.get("origins") or []) != 1:
        raise RuntimeError(
            f"Legacy origin group {name!r} origin set is unexpected; refusing update."
        )
    return {
        "action": "update",
        "reason": f"origin group {name!r} drift: {', '.join(drift)}",
        "drift": drift,
    }


def plan_resource(
    existing: dict[str, Any] | None,
    *,
    public_hostname: str,
    origin_group_id: str,
    origin_hostname: str,
    certificate_id: str | None,
    manage_cert: bool,
) -> dict[str, Any]:
    if existing is None:
        return {
            "action": "create",
            "reason": f"CDN resource cname {public_hostname!r} is absent",
        }
    actual_cname = normalize_host(existing.get("cname"))
    if actual_cname != normalize_host(public_hostname):
        raise RuntimeError(
            f"CDN resource identity mismatch: existing cname {existing.get('cname')!r} "
            f"!= desired {public_hostname!r}. Refusing delete/recreate."
        )
    desired_opts = desired_managed_options(origin_hostname)
    drift: list[str] = []
    if str(origin_group_id_of(existing)) != str(origin_group_id):
        drift.append("origin_group_id")
    if normalize_origin_protocol(
        yc.api_get(existing, "originProtocol", "origin_protocol")
    ) != ORIGIN_PROTOCOL:
        drift.append("origin_protocol")
    active = existing.get("active")
    if active is False:
        drift.append("active")
    if (tls_profile_of(existing) or TLS_PROFILE) != TLS_PROFILE:
        drift.append("tls")
    options = yc.api_get(existing, "options", default={}) or {}
    if not managed_options_equal(options, desired_opts):
        current = normalize_managed_options(options)
        wanted = normalize_managed_options(desired_opts)
        for key in MANAGED_OPTION_KEYS:
            if current.get(key) != wanted.get(key):
                drift.append(key)
    if manage_cert:
        if not certificate_id:
            raise RuntimeError("shared_wildcard certificate id is required to create/update resource")
        if ssl_certificate_id(existing) != str(certificate_id):
            drift.append("ssl_certificate")
    # legacy_existing: never include ssl_certificate in drift
    unique_drift = list(dict.fromkeys(drift))
    if not unique_drift:
        return {
            "action": "none",
            "reason": f"CDN resource {public_hostname!r} already matches managed fields",
        }
    return {
        "action": "update",
        "reason": f"CDN resource {public_hostname!r} drift: {', '.join(unique_drift)}",
        "drift": unique_drift,
    }


def resolve_wildcard_certificate(
    token: str,
    *,
    folder_id: str,
    name: str,
    domains: list[str],
) -> dict[str, Any]:
    certificates = ycm.list_certificates(token, folder_id)
    existing = ycm.find_certificate_by_name(certificates, name)
    if existing is None:
        raise RuntimeError(
            f"Certificate {name!r} is absent. Run make antiblock-cdn-bootstrap"
        )
    if not ycm.domains_match(existing.get("domains"), domains):
        raise RuntimeError(
            f"Certificate {name!r} domains {existing.get('domains')} != desired {domains}"
        )
    status = str(existing.get("status") or "")
    kind = ycm.classify_status(status)
    if kind == "pending":
        raise RuntimeError(
            f"Certificate {name!r} is {status}; waiting until ISSUED. "
            "Do not create a new certificate. Re-run after bootstrap completes."
        )
    if kind != "issued":
        raise RuntimeError(
            f"Certificate {name!r} is {status}. CDN Resource will not be created."
        )
    cert_id = str(existing.get("id") or "").strip()
    if not cert_id:
        raise RuntimeError(f"Certificate {name!r} is ISSUED but has no id")
    return existing


def _cdn_request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None,
    *,
    allow_writes: bool,
) -> dict[str, Any]:
    if method.upper() in WRITE_METHODS:
        if method.upper() == "DELETE":
            raise RuntimeError("Yandex CDN DELETE is not implemented in this stage")
        if not allow_writes:
            raise RuntimeError(
                f"Refusing {method} {url}: yandex_cdn_allow_writes is false"
            )
    return yc.request_json(method, url, token, body)


def list_origin_groups(token: str, folder_id: str) -> list[dict[str, Any]]:
    return _list_pages(token, ORIGIN_GROUPS_URL, folder_id, "originGroups")


def list_resources(token: str, folder_id: str) -> list[dict[str, Any]]:
    return _list_pages(token, RESOURCES_URL, folder_id, "resources")


def _list_pages(
    token: str, url: str, folder_id: str, list_key: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page_token = ""
    while True:
        query = {"folderId": folder_id, "pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        payload = yc.request_json("GET", url + "?" + urllib.parse.urlencode(query), token)
        chunk = payload.get(list_key) or []
        if list_key == "originGroups" and not chunk:
            chunk = payload.get("origin_groups") or []
        if list_key == "resources" and not chunk:
            chunk = payload.get("cdnResources") or []
        out.extend(chunk)
        page_token = str(payload.get("nextPageToken") or payload.get("next_page_token") or "")
        if not page_token:
            break
    return out


def get_origin_group(token: str, folder_id: str, group_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"folderId": folder_id})
    url = f"{ORIGIN_GROUPS_URL}/{urllib.parse.quote(str(group_id))}?{query}"
    return yc.request_json("GET", url, token)


def get_resource(token: str, resource_id: str) -> dict[str, Any]:
    return yc.request_json("GET", f"{RESOURCES_URL}/{urllib.parse.quote(str(resource_id))}", token)


def wait_provider_cname(
    token: str,
    resource_id: str,
    *,
    timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    resource = get_resource(token, resource_id)
    while True:
        if provider_cname_of(resource):
            return resource
        if time.time() >= deadline:
            raise RuntimeError(
                f"CDN resource {resource_id} operation finished but provider_cname is still empty"
            )
        time.sleep(max(float(poll_interval), 0.1))
        resource = get_resource(token, resource_id)


def _origin_payload(origin_hostname: str) -> list[dict[str, Any]]:
    return [
        {
            "source": str(origin_hostname).strip().rstrip("."),
            "enabled": True,
            "backup": False,
        }
    ]


def create_origin_group(
    token: str,
    *,
    folder_id: str,
    name: str,
    origin_hostname: str,
    use_next: bool,
    allow_writes: bool,
    operation_timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    operation = _cdn_request(
        "POST",
        ORIGIN_GROUPS_URL,
        token,
        {
            "folderId": folder_id,
            "name": name,
            "useNext": bool(use_next),
            "origins": _origin_payload(origin_hostname),
            "providerType": PROVIDER_TYPE,
        },
        allow_writes=allow_writes,
    )
    created = yc.wait_operation(
        token, operation, timeout=operation_timeout, poll_interval=poll_interval
    )
    group_id = str(created.get("id") or "")
    if group_id:
        return get_origin_group(token, folder_id, group_id)
    return created


def update_origin_group(
    token: str,
    *,
    folder_id: str,
    group_id: str,
    origin_hostname: str,
    use_next: bool,
    allow_writes: bool,
    operation_timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    operation = _cdn_request(
        "PATCH",
        ORIGIN_GROUPS_URL,
        token,
        {
            "folderId": folder_id,
            "originGroupId": str(group_id),
            "useNext": bool(use_next),
            "origins": _origin_payload(origin_hostname),
        },
        allow_writes=allow_writes,
    )
    yc.wait_operation(
        token, operation, timeout=operation_timeout, poll_interval=poll_interval
    )
    return get_origin_group(token, folder_id, str(group_id))


def create_resource(
    token: str,
    *,
    folder_id: str,
    public_hostname: str,
    origin_group_id: str,
    origin_hostname: str,
    certificate_id: str | None,
    manage_cert: bool,
    allow_writes: bool,
    operation_timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "folderId": folder_id,
        "cname": public_hostname,
        "origin": {"originGroupId": str(origin_group_id)},
        "originProtocol": ORIGIN_PROTOCOL,
        "active": True,
        "options": desired_managed_options(origin_hostname),
        "providerType": PROVIDER_TYPE,
        "tls": {"profile": TLS_PROFILE},
    }
    if manage_cert:
        if not certificate_id:
            raise RuntimeError("shared_wildcard requires an ISSUED certificate id")
        body["sslCertificate"] = {"type": "CM", "data": {"cm": {"id": certificate_id}}}
    operation = _cdn_request(
        "POST", RESOURCES_URL, token, body, allow_writes=allow_writes
    )
    created = yc.wait_operation(
        token, operation, timeout=operation_timeout, poll_interval=poll_interval
    )
    resource_id = str(created.get("id") or "")
    if resource_id:
        return get_resource(token, resource_id)
    return created


def update_resource(
    token: str,
    existing: dict[str, Any],
    *,
    origin_group_id: str,
    origin_hostname: str,
    certificate_id: str | None,
    manage_cert: bool,
    allow_writes: bool,
    operation_timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    resource_id = str(existing.get("id") or "")
    current_options = yc.api_get(existing, "options", default={}) or {}
    body: dict[str, Any] = {
        "originGroupId": str(origin_group_id),
        "originProtocol": ORIGIN_PROTOCOL,
        "active": True,
        "options": merge_resource_options(
            current_options, desired_managed_options(origin_hostname)
        ),
        "tls": {"profile": TLS_PROFILE},
    }
    if manage_cert:
        if not certificate_id:
            raise RuntimeError("shared_wildcard requires an ISSUED certificate id")
        body["sslCertificate"] = {"type": "CM", "data": {"cm": {"id": certificate_id}}}
    operation = _cdn_request(
        "PATCH",
        f"{RESOURCES_URL}/{urllib.parse.quote(resource_id)}",
        token,
        body,
        allow_writes=allow_writes,
    )
    yc.wait_operation(
        token, operation, timeout=operation_timeout, poll_interval=poll_interval
    )
    return get_resource(token, resource_id)


def reconcile(
    *,
    token: str,
    folder_id: str,
    public_hostname: str,
    origin_hostname: str,
    origin_group_name: str,
    origin_group_use_next: bool,
    certificate_mode: str,
    certificate_name: str,
    certificate_domains: list[str],
    dns_zone: str,
    allow_writes: bool,
    operation_timeout: int = 180,
    poll_interval: float = 2,
    provider_cname_timeout: int = 180,
) -> dict[str, Any]:
    if not folder_id:
        raise ValueError("folder_id is required")
    if not public_hostname or not origin_hostname or not origin_group_name:
        raise ValueError("public_hostname, origin_hostname, origin_group_name are required")

    legacy = is_legacy_node(certificate_mode)
    manage_cert = manage_certificate(certificate_mode)
    if certificate_mode not in {CERT_MODE_WILDCARD, CERT_MODE_LEGACY}:
        raise ValueError(
            f"certificate_mode must be {CERT_MODE_WILDCARD!r} or {CERT_MODE_LEGACY!r}"
        )

    certificate: dict[str, Any] | None = None
    certificate_id: str | None = None
    if manage_cert:
        certificate = resolve_wildcard_certificate(
            token,
            folder_id=folder_id,
            name=certificate_name,
            domains=certificate_domains,
        )
        certificate_id = str(certificate.get("id") or "")

    groups = list_origin_groups(token, folder_id)
    existing_group = find_unique_by_name(groups, origin_group_name, kind="origin group")
    group_plan = plan_origin_group(
        existing_group,
        name=origin_group_name,
        origin_hostname=origin_hostname,
        use_next=origin_group_use_next,
        public_hostname=public_hostname,
        legacy=legacy,
    )
    group = existing_group
    group_wrote = False
    if group_plan["action"] == "create":
        if allow_writes:
            group = create_origin_group(
                token,
                folder_id=folder_id,
                name=origin_group_name,
                origin_hostname=origin_hostname,
                use_next=origin_group_use_next,
                allow_writes=True,
                operation_timeout=operation_timeout,
                poll_interval=poll_interval,
            )
            group_wrote = True
    elif group_plan["action"] == "update":
        if allow_writes:
            group = update_origin_group(
                token,
                folder_id=folder_id,
                group_id=str((existing_group or {}).get("id") or ""),
                origin_hostname=origin_hostname,
                use_next=origin_group_use_next,
                allow_writes=True,
                operation_timeout=operation_timeout,
                poll_interval=poll_interval,
            )
            group_wrote = True

    group_id = str((group or {}).get("id") or "")
    resources = list_resources(token, folder_id)
    existing_resource = find_resource_by_cname(resources, public_hostname)
    resource_plan: dict[str, Any]
    if not group_id and group_plan["action"] == "create" and not allow_writes:
        resource_plan = {
            "action": "create",
            "reason": "CDN resource create is blocked until origin group exists",
        }
        resource = None
        resource_wrote = False
    else:
        if not group_id:
            raise RuntimeError(
                f"Origin group {origin_group_name!r} has no id after {group_plan['action']}"
            )
        resource_plan = plan_resource(
            existing_resource,
            public_hostname=public_hostname,
            origin_group_id=group_id,
            origin_hostname=origin_hostname,
            certificate_id=certificate_id,
            manage_cert=manage_cert,
        )
        resource = existing_resource
        resource_wrote = False
        if resource_plan["action"] == "create":
            if allow_writes:
                resource = create_resource(
                    token,
                    folder_id=folder_id,
                    public_hostname=public_hostname,
                    origin_group_id=group_id,
                    origin_hostname=origin_hostname,
                    certificate_id=certificate_id,
                    manage_cert=manage_cert,
                    allow_writes=True,
                    operation_timeout=operation_timeout,
                    poll_interval=poll_interval,
                )
                resource_wrote = True
        elif resource_plan["action"] == "update":
            if allow_writes:
                resource = update_resource(
                    token,
                    existing_resource or {},
                    origin_group_id=group_id,
                    origin_hostname=origin_hostname,
                    certificate_id=certificate_id,
                    manage_cert=manage_cert,
                    allow_writes=True,
                    operation_timeout=operation_timeout,
                    poll_interval=poll_interval,
                )
                resource_wrote = True

    if allow_writes and resource and resource.get("id") and not provider_cname_of(resource):
        resource = wait_provider_cname(
            token,
            str(resource["id"]),
            timeout=provider_cname_timeout,
            poll_interval=poll_interval,
        )
    cname = provider_cname_of(resource)
    if allow_writes and resource_plan["action"] != "none" and not cname and resource:
        raise RuntimeError("CDN resource has empty provider_cname after operation")

    records = public_cname_records(public_hostname, dns_zone, cname)
    changed = bool(group_wrote or resource_wrote)
    return {
        "changed": changed,
        "origin_group": {
            "action": group_plan["action"],
            "id": (group or {}).get("id"),
            "name": origin_group_name,
            "reason": group_plan["reason"],
            "wrote": group_wrote,
            "drift": group_plan.get("drift") or [],
        },
        "resource": {
            "action": resource_plan["action"],
            "id": (resource or {}).get("id"),
            "cname": public_hostname,
            "reason": resource_plan["reason"],
            "wrote": resource_wrote,
            "drift": resource_plan.get("drift") or [],
        },
        "certificate": {
            "mode": certificate_mode,
            "id": certificate_id,
            "name": certificate_name if manage_cert else None,
            "status": (certificate or {}).get("status"),
            "managed": manage_cert,
        },
        "provider_cname": cname or None,
        "public_dns_records": records,
        "reason": (
            f"origin_group={group_plan['action']} resource={resource_plan['action']} "
            f"writes={'on' if allow_writes else 'off'}"
        ),
    }


def _cmd_reconcile(args: argparse.Namespace) -> int:
    token = yc.token_from_cli_args(args)
    result = reconcile(
        token=token,
        folder_id=args.folder_id,
        public_hostname=args.public_hostname,
        origin_hostname=args.origin_hostname,
        origin_group_name=args.origin_group_name,
        origin_group_use_next=args.origin_group_use_next,
        certificate_mode=args.certificate_mode,
        certificate_name=args.certificate_name,
        certificate_domains=args.certificate_domains,
        dns_zone=args.dns_zone,
        allow_writes=args.allow_writes,
        operation_timeout=args.operation_timeout,
        poll_interval=args.poll_interval,
        provider_cname_timeout=args.provider_cname_timeout,
    )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    recon = sub.add_parser("reconcile", help="Lookup/create/update Origin Group + CDN Resource")
    recon.add_argument("--folder-id", required=True)
    recon.add_argument("--public-hostname", required=True)
    recon.add_argument("--origin-hostname", required=True)
    recon.add_argument("--origin-group-name", required=True)
    recon.add_argument("--origin-group-use-next", action="store_true")
    recon.add_argument("--certificate-mode", required=True)
    recon.add_argument("--certificate-name", default="")
    recon.add_argument("--certificate-domains", nargs="*", default=[])
    recon.add_argument("--dns-zone", required=True)
    recon.add_argument("--allow-writes", action="store_true")
    recon.add_argument("--operation-timeout", type=int, default=180)
    recon.add_argument("--poll-interval", type=float, default=2)
    recon.add_argument("--provider-cname-timeout", type=int, default=180)
    yc.add_auth_args(recon)
    recon.set_defaults(func=_cmd_reconcile)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
