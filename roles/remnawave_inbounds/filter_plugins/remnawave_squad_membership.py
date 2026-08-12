"""Ansible filters for declarative Remnawave Internal Squad membership.

Pure merge/validation helpers: no API calls. The role uses these so PATCH
runs only when membership actually drifted.
"""

from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_str_list(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _as_list(value):
        if item is None:
            continue
        text = str(item)
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def squad_inbound_uuids(inbounds: Any) -> list[str]:
    """Extract inbound UUIDs from a squad payload (objects or plain strings)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in _as_list(inbounds):
        uuid = None
        if isinstance(item, str):
            uuid = item
        elif isinstance(item, dict):
            uuid = item.get("uuid") or item.get("inboundUuid") or item.get("inbound_uuid")
        if not uuid:
            continue
        text = str(uuid)
        if text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def reconcile_squad_members(
    current: Any,
    add: Any = None,
    remove: Any = None,
) -> dict[str, Any]:
    """Return desired squad members without dropping unrelated UUIDs.

    new_members = (current - remove) + add  (unique, current order preserved,
    new UUIDs appended).
    """
    current_list = [str(item) for item in _as_list(current) if item is not None and str(item)]
    add_list = _as_str_list(add)
    remove_set = set(_as_str_list(remove))

    result: list[str] = []
    seen: set[str] = set()
    for uuid in current_list:
        if uuid in remove_set or uuid in seen:
            continue
        result.append(uuid)
        seen.add(uuid)
    for uuid in add_list:
        if uuid in remove_set or uuid in seen:
            continue
        result.append(uuid)
        seen.add(uuid)

    needs_patch = result != current_list
    return {
        "members": result,
        "changed": needs_patch,
        "needs_patch": needs_patch,
    }


def membership_conflicts(memberships: Any) -> list[dict[str, Any]]:
    """Squads listed in both present_in and absent_from for the same inbound tag."""
    by_tag: dict[str, dict[str, set[str]]] = {}
    for item in _as_list(memberships):
        if not isinstance(item, dict):
            continue
        tag = str(item.get("inbound_tag") or "")
        rec = by_tag.setdefault(tag, {"present": set(), "absent": set()})
        rec["present"].update(_as_str_list(item.get("present_in")))
        rec["absent"].update(_as_str_list(item.get("absent_from")))

    conflicts: list[dict[str, Any]] = []
    for tag, rec in by_tag.items():
        overlap = sorted(rec["present"] & rec["absent"])
        if overlap:
            conflicts.append({"inbound_tag": tag, "squads": overlap})
    return conflicts


class FilterModule:
    """Ansible filter plugin for Internal Squad membership reconcile."""

    def filters(self) -> dict[str, Any]:
        return {
            "remnawave_reconcile_squad_members": reconcile_squad_members,
            "remnawave_squad_membership_conflicts": membership_conflicts,
            "remnawave_squad_inbound_uuids": squad_inbound_uuids,
        }
