"""Ansible filters for extra static HAProxy SNI routes on Remnawave nodes."""

from __future__ import annotations

import re
from typing import Any

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def relative_dns_record_name(fqdn: Any, zone: Any) -> str:
    """Return Cloudflare record name relative to zone (origin-cdn.example.com → origin-cdn)."""
    name = str(fqdn or "").strip().rstrip(".")
    zone_name = str(zone or "").strip().rstrip(".")
    if not name:
        return name
    if not zone_name:
        return name
    lower_name, lower_zone = name.lower(), zone_name.lower()
    if lower_name == lower_zone:
        return "@"
    suffix = "." + lower_zone
    if lower_name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def _acl_suffix(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def _backend_identity(route: dict[str, Any]) -> tuple[str, int, bool]:
    return (
        str(route["backend_host"]).strip().lower(),
        int(route["backend_port"]),
        bool(route["send_proxy_v2"]),
    )


def prepare_extra_sni_routes(
    routes: Any,
    dynamic_sni_port_map: Any = None,
) -> dict[str, Any]:
    """Normalize extra SNI routes and fail on collisions before haproxy.cfg render."""
    errors: list[str] = []
    prepared: list[dict[str, Any]] = []
    seen_sni: dict[str, tuple[str, int, bool]] = {}
    dynamic: dict[str, int] = {}
    if isinstance(dynamic_sni_port_map, dict):
        for key, value in dynamic_sni_port_map.items():
            sni = str(key or "").strip().rstrip(".").lower()
            if not sni:
                continue
            try:
                dynamic[sni] = int(value)
            except (TypeError, ValueError):
                errors.append(f"dynamic SNI map has non-integer port for {key!r}")

    raw_list = routes or []
    if not isinstance(raw_list, list):
        return {
            "ok": False,
            "routes": [],
            "errors": ["haproxy_node_extra_sni_routes must be a list"],
        }

    for index, raw in enumerate(raw_list):
        label = f"haproxy_node_extra_sni_routes[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{label} must be a mapping")
            continue
        name = str(raw.get("name") or "").strip()
        sni = str(raw.get("sni") or "").strip().rstrip(".")
        host = str(raw.get("backend_host") or "127.0.0.1").strip()
        try:
            port = int(raw.get("backend_port"))
        except (TypeError, ValueError):
            port = 0
        if not name:
            errors.append(f"{label}: name is required")
            continue
        if not _NAME_RE.match(name):
            errors.append(f"{label}: invalid name {name!r}")
            continue
        if not sni:
            errors.append(f"{label}: SNI is required")
            continue
        if not host:
            errors.append(f"{label}: backend_host is required")
            continue
        if port < 1 or port > 65535:
            errors.append(f"{label}: invalid backend_port {raw.get('backend_port')!r}")
            continue

        send_proxy = bool(raw.get("send_proxy_v2", False))
        check = bool(raw.get("check", True))
        timeout_connect = str(raw.get("timeout_connect") or "").strip()
        timeout_server = str(raw.get("timeout_server") or "").strip()
        backend_name = str(raw.get("backend_name") or f"be_{name}").strip()
        server_name = str(raw.get("server_name") or f"extra_{name}").strip()
        route = {
            "name": name,
            "sni": sni,
            "acl_suffix": _acl_suffix(name),
            "backend_name": backend_name,
            "server_name": server_name,
            "backend_host": host,
            "backend_port": port,
            "send_proxy_v2": send_proxy,
            "check": check,
            "timeout_connect": timeout_connect,
            "timeout_server": timeout_server,
        }
        sni_key = sni.lower()
        identity = _backend_identity(route)
        if sni_key in seen_sni:
            if seen_sni[sni_key] == identity:
                continue
            errors.append(
                f"SNI {sni!r} is mapped to multiple extra backends; refusing to render"
            )
            continue
        if sni_key in dynamic:
            errors.append(
                f"SNI {sni!r} already exists in the dynamic Remnawave Host SNI map "
                f"(port {dynamic[sni_key]}); extra static route would collide"
            )
            continue
        seen_sni[sni_key] = identity
        prepared.append(route)

    return {
        "ok": not errors,
        "routes": prepared if not errors else [],
        "errors": errors,
    }


def extra_sni_backends(routes: Any) -> list[dict[str, Any]]:
    """Deduplicate extra routes by backend_name for HAProxy backend stanzas."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for route in routes or []:
        if not isinstance(route, dict):
            continue
        name = str(route.get("backend_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(route)
    return out


def extra_sni_backend_line(route: dict[str, Any]) -> str:
    """Render the HAProxy server line for an extra route (for tests and docs)."""
    parts = [
        "server",
        str(route["server_name"]),
        f"{route['backend_host']}:{route['backend_port']}",
    ]
    if route.get("check"):
        parts.append("check")
    if route.get("send_proxy_v2"):
        parts.append("send-proxy-v2")
    return " ".join(parts)


class FilterModule:
    """Ansible filter plugin for extra HAProxy SNI routes."""

    def filters(self) -> dict[str, Any]:
        return {
            "haproxy_prepare_extra_sni_routes": prepare_extra_sni_routes,
            "haproxy_extra_sni_backends": extra_sni_backends,
            "haproxy_extra_sni_backend_line": extra_sni_backend_line,
            "cf_dns_relative_name": relative_dns_record_name,
        }
