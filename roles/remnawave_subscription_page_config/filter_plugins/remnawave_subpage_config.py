"""Ansible filters for Remnawave Subscription Page config canonicalization."""

from __future__ import annotations

import copy
from typing import Any


def _is_localized_object(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if not all(isinstance(item, str) for item in value.values()):
        return False
    return any(len(key) == 2 for key in value)


def _clean_localized_texts(value: Any, locales: list[str]) -> Any:
    if isinstance(value, list):
        return [_clean_localized_texts(item, locales) for item in value]
    if isinstance(value, dict):
        if _is_localized_object(value):
            cleaned: dict[str, str] = {}
            for locale in locales:
                if locale not in value:
                    continue
                raw = value[locale]
                if not isinstance(raw, str):
                    continue
                stripped = raw.strip()
                if stripped:
                    cleaned[locale] = stripped
            return cleaned
        return {key: _clean_localized_texts(item, locales) for key, item in value.items()}
    return value


def _canonicalize_config(config: Any) -> Any:
    if not isinstance(config, dict):
        return copy.deepcopy(config)

    result = copy.deepcopy(config)
    locales = result.get("locales")
    if not isinstance(locales, list):
        locales = []

    if "platforms" in result:
        result["platforms"] = _clean_localized_texts(result["platforms"], locales)
    if "baseTranslations" in result:
        result["baseTranslations"] = _clean_localized_texts(result["baseTranslations"], locales)
    return result


def _collect_diff_paths(
    left: Any,
    right: Any,
    path: str = "",
    *,
    limit: int = 30,
) -> list[str]:
    paths: list[str] = []

    def append(path_value: str) -> None:
        if len(paths) < limit:
            paths.append(path_value)

    if type(left) is not type(right):
        append(path or ".")
        return paths

    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left or key not in right:
                append(child_path)
            else:
                nested = _collect_diff_paths(left[key], right[key], child_path, limit=limit - len(paths))
                paths.extend(nested)
            if len(paths) >= limit:
                break
        return paths[:limit]

    if isinstance(left, list):
        if len(left) != len(right):
            append(path or ".")
            return paths
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            nested = _collect_diff_paths(
                left_item,
                right_item,
                f"{path}[{index}]",
                limit=limit - len(paths),
            )
            paths.extend(nested)
            if len(paths) >= limit:
                break
        return paths[:limit]

    if left != right:
        append(path or ".")
    return paths[:limit]


class FilterModule:
    """Ansible filter plugin for Remnawave Subscription Page config."""

    def filters(self) -> dict[str, Any]:
        return {
            "remnawave_subpage_config_canonicalize": self.canonicalize,
            "remnawave_subpage_config_diff_paths": self.diff_paths,
        }

    def canonicalize(self, config: Any) -> Any:
        return _canonicalize_config(config)

    def diff_paths(self, left: Any, right: Any) -> list[str]:
        left_canonical = _canonicalize_config(left)
        right_canonical = _canonicalize_config(right)
        return _collect_diff_paths(left_canonical, right_canonical)
