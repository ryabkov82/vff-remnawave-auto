"""Ansible filters for remnawave_register_node inbound tag lists."""

from __future__ import annotations

from typing import Any


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def effective_inbound_tags(
    base_tags: Any,
    extra_tags: Any = None,
    legacy_tag: Any = "",
) -> list[str]:
    """base (or legacy single tag) + extra, unique, order preserved."""
    base = _as_str_list(base_tags)
    if not base:
        base = _as_str_list(legacy_tag)
    extra = _as_str_list(extra_tags)
    result: list[str] = []
    seen: set[str] = set()
    for tag in base + extra:
        if tag in seen:
            continue
        result.append(tag)
        seen.add(tag)
    return result


def reconcile_active_inbounds(
    current: Any,
    desired: Any,
    mode: str = "merge",
) -> dict[str, Any]:
    """Mirror register_node merge|replace over UUID (or tag stand-in) lists."""
    current_list = _as_str_list(current)
    desired_list = effective_inbound_tags(desired, extra_tags=[])
    if (mode or "merge") == "replace":
        members = list(desired_list)
    else:
        members = effective_inbound_tags(current_list, extra_tags=desired_list)
    return {
        "members": members,
        "changed": sorted(members) != sorted(current_list),
    }


class FilterModule:
    """Ansible filter plugin for node inbound tag composition."""

    def filters(self) -> dict[str, Any]:
        return {
            "remnawave_effective_inbound_tags": effective_inbound_tags,
            "remnawave_reconcile_active_inbounds": reconcile_active_inbounds,
        }
