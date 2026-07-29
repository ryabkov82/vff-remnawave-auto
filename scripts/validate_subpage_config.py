#!/usr/bin/env python3
"""Validate Remnawave Subscription Page v7 JSON configuration."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_ROOT_KEYS = (
    "locales",
    "version",
    "uiConfig",
    "platforms",
    "svgLibrary",
    "baseSettings",
    "baseTranslations",
    "brandingSettings",
)

REQUIRED_PLATFORMS = (
    "ios",
    "android",
    "windows",
    "macos",
    "linux",
    "appleTV",
    "androidTV",
)

ALLOWED_BUTTON_TYPES = {"external", "subscriptionLink", "copyButton"}

ALLOWED_PLACEHOLDERS = {
    "{{SUBSCRIPTION_LINK}}",
    "{{USERNAME}}",
    "{{HAPP_CRYPT3_LINK}}",
    "{{HAPP_CRYPT4_LINK}}",
}

LEGACY_KEYS = {
    "isFeatured",
    "urlScheme",
    "isNeedBase64Encoding",
    "installationStep",
    "addSubscriptionStep",
    "connectAndUseStep",
    "additionalAfterAddSubscriptionStep",
    "buttonLink",
    "buttonText",
}

FORBIDDEN_LOCALES = {"zh", "fa", "fr"}

IOS_ORDER = ["OneXray", "Shadowrocket", "Happ", "v2RayTun", "Streisand"]

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "roles/remnawave_subscription_page_config/files/base.json"
)

PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class ValidationError(Exception):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def check_locales_object(obj: dict[str, Any], path: str) -> None:
    keys = set(obj.keys())
    if keys & FORBIDDEN_LOCALES:
        fail(f"{path}: forbidden locales present: {sorted(keys & FORBIDDEN_LOCALES)}")
    if not keys <= {"en", "ru"}:
        extra = keys - {"en", "ru"}
        fail(f"{path}: unexpected locale keys: {sorted(extra)}")
    if "en" not in obj or "ru" not in obj:
        fail(f"{path}: must contain both en and ru")


def walk_localized(value: Any, path: str) -> None:
    if isinstance(value, dict):
        if value and all(isinstance(v, str) for v in value.values()):
            if "en" in value or "ru" in value or any(k in FORBIDDEN_LOCALES for k in value):
                check_locales_object(value, path)
                return
        for key, item in value.items():
            walk_localized(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk_localized(item, f"{path}[{index}]")


def walk_legacy_keys(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in LEGACY_KEYS:
                fail(f"{path}: legacy key '{key}' is not allowed")
            walk_legacy_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk_legacy_keys(item, f"{path}[{index}]")


def check_placeholders_in_string(text: str, path: str) -> None:
    for match in PLACEHOLDER_PATTERN.finditer(text):
        token = match.group(0)
        if token not in ALLOWED_PLACEHOLDERS:
            fail(f"{path}: disallowed placeholder {token}")


def walk_placeholders(value: Any, path: str) -> None:
    if isinstance(value, str):
        check_placeholders_in_string(value, path)
    elif isinstance(value, dict):
        for key, item in value.items():
            walk_placeholders(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk_placeholders(item, f"{path}[{index}]")


def collect_svg_icon_keys(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "svgIconKey" and isinstance(item, str):
                found.add(item)
            collect_svg_icon_keys(item, found)
    elif isinstance(value, list):
        for item in value:
            collect_svg_icon_keys(item, found)


def validate_platform(platform_name: str, platform: Any, svg_library: set[str]) -> list[Any]:
    path = f"platforms.{platform_name}"
    if isinstance(platform, list):
        fail(f"{path} must be an object with displayName, svgIconKey and apps")
    if not isinstance(platform, dict):
        fail(f"{path} must be an object with displayName, svgIconKey and apps")

    if "displayName" not in platform:
        fail(f"{path}.displayName: required")
    display_name = platform["displayName"]
    if not isinstance(display_name, dict):
        fail(f"{path}.displayName must be an object")
    check_locales_object(display_name, f"{path}.displayName")
    if not str(display_name.get("en", "")).strip():
        fail(f"{path}.displayName.en must be non-empty")
    if not str(display_name.get("ru", "")).strip():
        fail(f"{path}.displayName.ru must be non-empty")

    if "svgIconKey" not in platform:
        fail(f"{path}.svgIconKey: required")
    svg_icon_key = platform["svgIconKey"]
    if not isinstance(svg_icon_key, str) or not svg_icon_key.strip():
        fail(f"{path}.svgIconKey must be a non-empty string")
    if svg_icon_key not in svg_library:
        fail(f"{path}.svgIconKey unknown value: {svg_icon_key!r}")

    if "apps" not in platform:
        fail(f"{path}.apps: required")
    apps = platform["apps"]
    if not isinstance(apps, list):
        fail(f"{path}.apps must be an array")

    return apps


def validate_config(data: dict[str, Any]) -> None:
    missing_root = [key for key in REQUIRED_ROOT_KEYS if key not in data]
    if missing_root:
        fail(f"missing root keys: {missing_root}")

    if data.get("version") != "1":
        fail(f"version must be '1', got {data.get('version')!r}")

    if data.get("locales") != ["en", "ru"]:
        fail(f"locales must be ['en', 'ru'], got {data.get('locales')!r}")

    platforms = data["platforms"]
    missing_platforms = [p for p in REQUIRED_PLATFORMS if p not in platforms]
    if missing_platforms:
        fail(f"platforms missing: {missing_platforms}")

    walk_localized(data.get("baseTranslations", {}), "baseTranslations")
    walk_legacy_keys(data, "root")

    svg_library = set(data["svgLibrary"].keys())
    used_icons: set[str] = set()
    collect_svg_icon_keys(data["platforms"], used_icons)
    unknown_icons = sorted(used_icons - svg_library)
    if unknown_icons:
        fail(f"unknown svgIconKey values: {unknown_icons}")

    for platform_name in REQUIRED_PLATFORMS:
        apps = validate_platform(platform_name, platforms[platform_name], svg_library)
        names = [app.get("name") for app in apps]
        if len(names) != len(set(names)):
            fail(f"platforms.{platform_name}: duplicate app.name values")

        for app_index, app in enumerate(apps):
            app_path = f"platforms.{platform_name}.apps[{app_index}]"
            for block_index, block in enumerate(app.get("blocks", [])):
                block_path = f"{app_path}.blocks[{block_index}]"
                for button_index, button in enumerate(block.get("buttons", [])):
                    button_path = f"{block_path}.buttons[{button_index}]"
                    button_type = button.get("type")
                    if button_type not in ALLOWED_BUTTON_TYPES:
                        fail(f"{button_path}: invalid button.type {button_type!r}")

    walk_placeholders(data["platforms"], "platforms")

    ios_apps = platforms["ios"]["apps"]
    ios_names = [app["name"] for app in ios_apps]
    if ios_names[: len(IOS_ORDER)] != IOS_ORDER:
        fail(
            f"iOS app order must start with {IOS_ORDER}, got prefix {ios_names[: len(IOS_ORDER)]}"
        )
    if len(set(ios_names)) != len(ios_names):
        fail(f"iOS duplicate app.name values: {ios_names}")

    ios_by_name = {app["name"]: app for app in ios_apps}

    if not ios_by_name["OneXray"].get("featured"):
        fail("OneXray featured must be true")
    onexray_blob = json.dumps(ios_by_name["OneXray"], ensure_ascii=False)
    if "onexray://" in onexray_blob.lower():
        fail("OneXray must not contain onexray:// links")
    onexray_buttons = [
        btn
        for block in ios_by_name["OneXray"]["blocks"]
        for btn in block.get("buttons", [])
    ]
    if not any(
        btn.get("type") == "copyButton" and btn.get("link") == "{{SUBSCRIPTION_LINK}}"
        for btn in onexray_buttons
    ):
        fail("OneXray must contain copyButton with {{SUBSCRIPTION_LINK}}")

    if not ios_by_name["Shadowrocket"].get("featured"):
        fail("Shadowrocket featured must be true")
    if ios_by_name["Happ"].get("featured"):
        fail("Happ featured must be false")
    if ios_by_name["v2RayTun"].get("featured"):
        fail("v2RayTun featured must be false")

    for platform_name in REQUIRED_PLATFORMS:
        apps = platforms[platform_name]["apps"]
        if not isinstance(apps, list):
            fail(f"platforms.{platform_name}.apps must be an array")
        for app_index, app in enumerate(apps):
            if not app.get("name"):
                fail(f"platforms.{platform_name}.apps[{app_index}].name is required")
            if not app.get("blocks"):
                fail(f"platforms.{platform_name}.apps[{app_index}] must contain blocks")


def main(argv: list[str]) -> int:
    if len(argv) == 1:
        config_path = DEFAULT_CONFIG_PATH
    elif len(argv) == 2:
        config_path = Path(argv[1])
    else:
        print(
            f"Usage: {Path(argv[0]).name} [<config.json>]",
            file=sys.stderr,
        )
        print(
            f"Default: {DEFAULT_CONFIG_PATH}",
            file=sys.stderr,
        )
        return 2
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        validate_config(data)
    except ValidationError as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"JSON ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
