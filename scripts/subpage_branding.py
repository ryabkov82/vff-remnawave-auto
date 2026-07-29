#!/usr/bin/env python3
"""Shared helpers for Subscription Page branding (merge + API plans).

Merge semantics (deterministic deep merge):
- Scalars / non-dict patch values replace the base value.
- Dicts merge recursively by key.
- ``null`` in a patch deletes the key (JSON Merge Patch).
- Lists of dicts merge **by index**: each patch element is deep-merged into
  the corresponding base element; empty ``{}`` is a no-op for that element;
  extra patch elements are appended; if the patch list is shorter, trailing
  base elements are kept.
- Lists that are not lists-of-dicts are replaced wholesale by the patch.

Canonical equality for configs ignores key order (via json.dumps sort_keys
or the Ansible canonicalize filter for Remnawave localized text cleanup).
"""

from __future__ import annotations

import copy
import json
from typing import Any


def deep_merge(base: Any, patch: Any) -> Any:
    """Apply brand patch onto base with the documented merge semantics."""
    if patch is None:
        return None
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    if not isinstance(base, dict):
        return copy.deepcopy(patch)

    result: dict[str, Any] = copy.deepcopy(base)
    for key, patch_value in patch.items():
        if patch_value is None:
            result.pop(key, None)
            continue
        if key not in result:
            result[key] = copy.deepcopy(patch_value)
            continue
        base_value = result[key]
        if isinstance(patch_value, dict) and isinstance(base_value, dict):
            result[key] = deep_merge(base_value, patch_value)
        elif (
            isinstance(patch_value, list)
            and isinstance(base_value, list)
            and _is_list_of_dicts(base_value)
            and _is_list_of_dicts(patch_value)
        ):
            result[key] = _merge_dict_lists_by_index(base_value, patch_value)
        else:
            result[key] = copy.deepcopy(patch_value)
    return result


def _is_list_of_dicts(value: list[Any]) -> bool:
    return all(isinstance(item, dict) for item in value)


def _merge_dict_lists_by_index(base: list[Any], patch: list[Any]) -> list[Any]:
    merged: list[Any] = []
    for index in range(max(len(base), len(patch))):
        if index >= len(patch):
            merged.append(copy.deepcopy(base[index]))
            continue
        if index >= len(base):
            merged.append(copy.deepcopy(patch[index]))
            continue
        merged.append(deep_merge(base[index], patch[index]))
    return merged


def canonical_json(value: Any) -> str:
    """Stable JSON for equality checks (key order independent)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def configs_equal(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def collect_diff_paths(
    left: Any,
    right: Any,
    path: str = "$",
    *,
    limit: int = 50,
) -> list[str]:
    paths: list[str] = []

    def add(item: str) -> None:
        if len(paths) < limit:
            paths.append(item)

    if type(left) is not type(right):
        add(path)
        return paths

    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                add(child)
            else:
                paths.extend(
                    collect_diff_paths(left[key], right[key], child, limit=limit - len(paths))
                )
            if len(paths) >= limit:
                break
        return paths[:limit]

    if isinstance(left, list):
        if len(left) != len(right):
            add(path)
            return paths
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            paths.extend(
                collect_diff_paths(
                    left_item,
                    right_item,
                    f"{path}[{index}]",
                    limit=limit - len(paths),
                )
            )
            if len(paths) >= limit:
                break
        return paths[:limit]

    if left != right:
        add(path)
    return paths[:limit]


# Brand leaf paths expected to differ between VFF and FC (and only these).
ALLOWED_BRAND_DIFF_PATHS = frozenset(
    {
        "$.brandingSettings.title",
        "$.brandingSettings.supportUrl",
        "$.baseSettings.metaTitle",
        "$.platforms.windows.apps[0].blocks[1].buttons[0].link",
    }
)


def assert_only_brand_diffs(left: Any, right: Any) -> list[str]:
    """Return unexpected diff paths (empty means only allowed brand paths differ)."""
    diffs = collect_diff_paths(left, right)
    return [path for path in diffs if path not in ALLOWED_BRAND_DIFF_PATHS]


def find_by_uuid_or_name(
    items: list[dict[str, Any]],
    *,
    uuid: str | None,
    name: str,
    uuid_key: str = "uuid",
    name_key: str = "name",
) -> dict[str, Any] | None:
    uuid_value = (uuid or "").strip()
    if uuid_value:
        for item in items:
            if str(item.get(uuid_key, "")) == uuid_value:
                return item
    for item in items:
        if str(item.get(name_key, "")) == name:
            return item
    return None


def plan_subpage_config_action(
    existing: list[dict[str, Any]],
    *,
    name: str,
    uuid: str | None,
    desired_config: dict[str, Any],
    check_mode: bool,
) -> dict[str, Any]:
    """Plan create/update for one Subpage Config. Never mutates inputs."""
    found = find_by_uuid_or_name(existing, uuid=uuid, name=name)
    plan: dict[str, Any] = {
        "name": name,
        "uuid": (uuid or "").strip() or None,
        "exists": found is not None,
        "create": False,
        "patch_config": False,
        "patch_name": False,
        "http_methods": [],
        "resolved_uuid": None,
        "message": "",
    }
    if found is None:
        plan["create"] = True
        if check_mode:
            plan["message"] = f"Would create Subpage Config {name!r}."
            plan["http_methods"] = []
        else:
            plan["http_methods"] = ["POST", "PATCH"]
            plan["message"] = f"Create Subpage Config {name!r}, then PATCH config."
            plan["patch_config"] = True
        return plan

    plan["resolved_uuid"] = found.get("uuid")
    plan["uuid"] = found.get("uuid")
    current_config = found.get("config")
    if current_config is None:
        plan["patch_config"] = True
    else:
        plan["patch_config"] = not configs_equal(current_config, desired_config)
    if found.get("name") != name:
        plan["patch_name"] = True

    methods: list[str] = []
    if plan["patch_config"] or plan["patch_name"]:
        methods.append("PATCH")
    if check_mode:
        plan["http_methods"] = []
        if plan["patch_config"] or plan["patch_name"]:
            plan["message"] = f"Would update Subpage Config {name!r}."
        else:
            plan["message"] = f"Subpage Config {name!r} is already up to date."
    else:
        plan["http_methods"] = methods
        if methods:
            plan["message"] = f"Update Subpage Config {name!r}."
        else:
            plan["message"] = f"Subpage Config {name!r} is already up to date."
    return plan


def resolve_subpage_uuid_by_name(
    configs: list[dict[str, Any]],
    name: str,
) -> str:
    match = find_by_uuid_or_name(configs, uuid=None, name=name)
    if match is None or not match.get("uuid"):
        raise LookupError(f"Unknown Subpage Config name: {name!r}")
    return str(match["uuid"])


def declared_subpage_config_names(
    declared_configs: list[dict[str, Any]] | None,
) -> set[str]:
    """Exact Subpage Config names from remnawave_subpage_configs."""
    names: set[str] = set()
    for item in declared_configs or []:
        name = str(item.get("name", "")).strip()
        if name:
            names.add(name)
    return names


def resolved_subpage_entry_by_name(
    resolved_map: dict[str, Any] | None,
    name: str,
) -> dict[str, Any] | None:
    """Find a remnawave_subpage_config_resolved entry by exact config name."""
    for entry in (resolved_map or {}).values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name", "")).strip() == name:
            return entry
    return None


def resolve_external_squad_subpage_binding(
    *,
    subpage_name: str,
    remote_configs: list[dict[str, Any]] | None = None,
    declared_configs: list[dict[str, Any]] | None = None,
    resolved_map: dict[str, Any] | None = None,
    uuid_map_override: dict[str, Any] | None = None,
    check_mode: bool = False,
) -> dict[str, Any]:
    """Resolve Subpage Config UUID for External Squad linking.

    Distinguishes:
    - real UUID available now;
    - declaratively planned create (check-mode deferred link);
    - truly unknown name (always an error).

    Never invents a fake UUID.
    """
    name = subpage_name.strip()
    result: dict[str, Any] = {
        "name": name,
        "uuid": "",
        "declared": False,
        "planned_create": False,
        "deferred": False,
        "ok": False,
        "error": None,
        "message": "",
    }

    override = (uuid_map_override or {}).get(name, "")
    if isinstance(override, str) and override.strip():
        result["uuid"] = override.strip()

    if not result["uuid"]:
        resolved_entry = resolved_subpage_entry_by_name(resolved_map, name)
        if resolved_entry is not None:
            result["planned_create"] = bool(resolved_entry.get("planned_create"))
            uuid_value = str(resolved_entry.get("uuid", "")).strip()
            if uuid_value:
                result["uuid"] = uuid_value

    if not result["uuid"]:
        match = find_by_uuid_or_name(list(remote_configs or []), uuid=None, name=name)
        if match is not None and match.get("uuid"):
            result["uuid"] = str(match["uuid"])

    declared_names = declared_subpage_config_names(declared_configs)
    result["declared"] = name in declared_names or result["planned_create"]
    if name in declared_names and not result["uuid"]:
        # Declarative entry without a live UUID implies a planned create in check-mode.
        result["planned_create"] = True

    if result["uuid"]:
        result["ok"] = True
        result["message"] = f"Resolved Subpage Config {name!r} UUID."
        return result

    if check_mode and result["declared"]:
        result["ok"] = True
        result["deferred"] = True
        result["planned_create"] = True
        result["message"] = (
            f"Subpage Config {name!r} is declared and would be created; "
            "External Squad link is deferred until apply."
        )
        return result

    result["error"] = f"Unknown Subpage Config name: {name!r}"
    result["message"] = result["error"]
    return result


def plan_external_squad_action(
    existing: list[dict[str, Any]],
    *,
    name: str,
    desired_subpage_config_uuid: str,
    protected_names: list[str] | None = None,
    check_mode: bool = False,
    subpage_deferred: bool = False,
    subpage_name: str | None = None,
) -> dict[str, Any]:
    """Plan create/update for one External Squad (subpage link only)."""
    protected = set(protected_names or [])
    plan: dict[str, Any] = {
        "name": name,
        "protected": name in protected,
        "create": False,
        "patch_subpage": False,
        "skip": False,
        "deferred": False,
        "http_methods": [],
        "resolved_uuid": None,
        "message": "",
        "error": None,
    }
    if name in protected:
        plan["skip"] = True
        plan["error"] = f"Refusing to manage protected External Squad {name!r}."
        plan["message"] = plan["error"]
        return plan

    display_subpage = (subpage_name or "").strip() or "desired Subpage Config"

    if check_mode and subpage_deferred and not (desired_subpage_config_uuid or "").strip():
        plan["deferred"] = True
        plan["create"] = find_by_uuid_or_name(existing, uuid=None, name=name) is None
        plan["patch_subpage"] = True
        plan["http_methods"] = []
        if plan["create"]:
            plan["message"] = (
                f"External Squad {name!r} is missing and would be created after "
                f"Subpage Config {display_subpage!r} is created, then linked to it via PATCH."
            )
        else:
            plan["message"] = (
                f"External Squad {name!r} would be linked to Subpage Config "
                f"{display_subpage!r} after that config is created."
            )
        return plan

    if not (desired_subpage_config_uuid or "").strip():
        plan["skip"] = True
        plan["error"] = (
            f"Subpage Config UUID is empty for External Squad {name!r}; "
            "apply Subpage Configs first."
        )
        plan["message"] = plan["error"]
        return plan

    found = find_by_uuid_or_name(existing, uuid=None, name=name)
    if found is None:
        plan["create"] = True
        plan["patch_subpage"] = True
        if check_mode:
            plan["http_methods"] = []
            plan["message"] = (
                f"Would create External Squad {name!r} and link Subpage Config."
            )
        else:
            plan["http_methods"] = ["POST", "PATCH"]
            plan["message"] = (
                f"Create External Squad {name!r}, then PATCH subpageConfigUuid."
            )
        return plan

    plan["resolved_uuid"] = found.get("uuid")
    current = found.get("subpageConfigUuid")
    plan["patch_subpage"] = current != desired_subpage_config_uuid
    if check_mode:
        plan["http_methods"] = []
        if plan["patch_subpage"]:
            plan["message"] = (
                f"Would update External Squad {name!r} subpageConfigUuid."
            )
        else:
            plan["message"] = f"External Squad {name!r} is already up to date."
    else:
        plan["http_methods"] = ["PATCH"] if plan["patch_subpage"] else []
        if plan["patch_subpage"]:
            plan["message"] = f"Update External Squad {name!r} subpageConfigUuid."
        else:
            plan["message"] = f"External Squad {name!r} is already up to date."
    return plan
