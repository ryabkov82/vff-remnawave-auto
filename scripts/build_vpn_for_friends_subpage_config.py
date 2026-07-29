#!/usr/bin/env python3
"""Build vpn-for-friends.json from legacy app-config and v7 default template."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_FILES = ROOT / "roles/remnawave_subscription_page_config/files"
LEGACY_PATH = ROOT / "roles/remnawave_subscription_page/files/app-config.json"
DEFAULT_SOURCE = ROLE_FILES / "source/default-7.2.1.json"
DEFAULT_OUTPUT = ROOT / "tests/fixtures/vpn-for-friends.golden.json"

LOCALES = ("en", "ru")

BLOCK_TITLES = {
    "installation": {"en": "App Installation", "ru": "Установка приложения"},
    "add": {"en": "Add Subscription", "ru": "Добавление подписки"},
    "connect": {"en": "Connect and use", "ru": "Подключение и использование"},
}

BLOCK_COLORS = {
    "installation": "violet",
    "add": "cyan",
    "connect": "teal",
}

ICON_BY_APP = {
    "Happ": "Happ",
    "v2RayTun": "vrayTUN",
    "Hiddify": "Hiddify",
    "Clash Meta": "ClashMeta",
    "OneXray": "OneXray",
    "Shadowrocket": "Shadowrocket",
    "Streisand": "Streisand",
    "Clash Verge": "ClashVerge",
}

LEGACY_PLATFORM_MAP = {
    "android": "android",
    "ios": "ios",
    "linux": "linux",
    "macos": "macos",
    "windows": "windows",
    "appleTV": "appleTV",
    "androidTV": "androidTV",
}

HAPP_REFILTER_LINK = (
    "happ://routing/onadd/ewogICAgIk5hbWUiOiAiUmU6ZmlsdGVyIiwKICAgICJHbG9iYWxQcm94eSI6ICJmYWxzZSIsCiAgICAiUmVtb3RlRG5zIjogIjEuMS4xLjEiLAogICAgIkRvbWVzdGljRG5zIjogIjc3Ljg4LjguOCIsCiAgICAiR2VvaXB1cmwiOiAiaHR0cHM6Ly9naXRodWIuY29tLzFhbmRyZXZpY2gvUmUtZmlsdGVyLWxpc3RzL3JlbGVhc2VzL2xhdGVzdC9kb3dubG9hZC9nZW9pcC5kYXQiLAogICAgIkVlb3NpdGV1cmwiOiAiaHR0cHM6Ly9naXRodWIuY29tLzFhbmRyZXZpY2gvUmUtZmlsdGVyLWxpc3RzL3JlbGVhc2VzL2xhdGVzdC9kb3dubG9hZC9nZW9zaXRlLmRhdCIsCiAgICAiRG5zSG9zdHMiOiB7fSwKICAgICJEaXJlY3RTaXRlcyI6IFtdLAogICAgIkRpcmVjdElwIjogWwogICAgICAgICIxMC4wLjAuMC84IiwKICAgICAgICAiMTcyLjE2LjAuMC8xMiIsCiAgICAgICAgIjE5Mi4xNjguMC4wLzE2IiwKICAgICAgICAiMTY5LjI1NC4wLjAvMTYiLAogICAgICAgICIyMjQuMC4wLjAvNCIsCiAgICAgICAgIjI1NS4yNTUuMjU1LjI1NSIKICAgIF0sCiAgICAiUHJveHlTaXRlcyI6IFsKICAgICAgICAiZ2Vvc2l0ZTpyZWZpbHRlciIKICAgIF0sCiAgICAiUHJveHlJcCI6IFsKICAgICAgICAiZ2VvaXA6cmVmaWx0ZXIiCiAgICBdLAogICAgIkJsb2NrU2l0ZXMiOiBbXSwKICAgICJCbG9ja0lwIjogW10sCiAgICAiRG9tYWluU3RyYXRlZ3kiOiAiSVBPbkRlbWFuZCIKfQ=="
)


def filter_loc(value):
    if isinstance(value, dict):
        if set(value.keys()) >= set(LOCALES) or any(k in value for k in LOCALES):
            return {k: value[k] for k in LOCALES if k in value}
        return {k: filter_loc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [filter_loc(item) for item in value]
    return value


def loc_text(en: str, ru: str) -> dict[str, str]:
    return {"en": en, "ru": ru}


def make_block(kind: str, description: dict, buttons: list | None = None, title: dict | None = None) -> dict:
    block = {
        "title": title or BLOCK_TITLES[kind],
        "buttons": buttons or [],
        "svgIconKey": {"installation": "DownloadIcon", "add": "CloudDownload", "connect": "Check"}[kind],
        "description": filter_loc(description),
        "svgIconColor": BLOCK_COLORS[kind],
    }
    return block


def convert_buttons(raw_buttons: list[dict]) -> list[dict]:
    result = []
    for btn in raw_buttons:
        result.append(
            {
                "link": btn["buttonLink"],
                "text": filter_loc(btn["buttonText"]),
                "type": "external",
                "svgIconKey": "ExternalLink",
            }
        )
    return result


def subscription_link_from_scheme(url_scheme: str) -> str | None:
    if not url_scheme:
        return None
    scheme = url_scheme
    if "{{SUBSCRIPTION_LINK}}" in scheme:
        return scheme
    if scheme.endswith("/"):
        return f"{scheme}{{{{SUBSCRIPTION_LINK}}}}"
    if scheme.endswith("="):
        return f"{scheme}{{{{SUBSCRIPTION_LINK}}}}"
    if "redirect.html?url=" in scheme:
        return f"{scheme}{{{{SUBSCRIPTION_LINK}}}}"
    return f"{scheme}{{{{SUBSCRIPTION_LINK}}}}"


def convert_additional(step: dict | None) -> dict | None:
    if not step:
        return None
    buttons = convert_buttons(step.get("buttons") or [])
    block = {
        "title": filter_loc(step["title"]) if step.get("title") else None,
        "description": filter_loc(step.get("description") or {}),
        "buttons": buttons,
        "svgIconKey": "DownloadIcon",
        "svgIconColor": "cyan",
    }
    if block["title"] is None:
        del block["title"]
    return block


def build_onexray_ios(app: dict) -> dict:
    blocks = [
        make_block(
            "installation",
            {
                "en": "Install OneXray from the App Store.",
                "ru": "Установите OneXray из App Store.",
            },
            [
                {
                    "link": "https://apps.apple.com/ru/app/onexray/id6745748773",
                    "text": loc_text("Open in App Store", "Открыть в App Store"),
                    "type": "external",
                    "svgIconKey": "ExternalLink",
                }
            ],
        ),
        make_block(
            "add",
            {
                "en": (
                    "Copy the subscription link, open OneXray, go to Subscriptions, "
                    "tap +, paste the link and add it."
                ),
                "ru": (
                    "Скопируйте ссылку подписки, откройте OneXray, перейдите в раздел "
                    "Subscriptions, нажмите «+», вставьте ссылку и добавьте её."
                ),
            },
            [
                {
                    "link": "{{SUBSCRIPTION_LINK}}",
                    "text": loc_text("Copy subscription link", "Скопировать ссылку подписки"),
                    "type": "copyButton",
                    "svgIconKey": "CloudDownload",
                }
            ],
        ),
        make_block(
            "connect",
            loc_text("Select a server and connect.", "Выберите сервер и подключитесь."),
        ),
    ]
    return {"name": "OneXray", "blocks": blocks, "featured": True, "svgIconKey": "OneXray"}


def build_shadowrocket_ios(app: dict) -> dict:
    blocks = [
        make_block(
            "installation",
            app["installationStep"]["description"],
            convert_buttons(app["installationStep"]["buttons"]),
        ),
        make_block(
            "add",
            {
                "en": (
                    "Click the button below — the app will open and the subscription will be added "
                    "automatically. Verify automatic import on a real iPhone before switching "
                    "production traffic to this flow."
                ),
                "ru": (
                    "Нажмите кнопку ниже — приложение откроется, и подписка добавится автоматически. "
                    "Проверьте автоматический импорт на реальном iPhone до production-переключения."
                ),
            },
            [
                {
                    "link": "shadowrocket://add/{{SUBSCRIPTION_LINK}}#{{USERNAME}}",
                    "text": loc_text("Add Subscription", "Добавить подписку"),
                    "type": "subscriptionLink",
                    "svgIconKey": "Plus",
                },
                {
                    "link": "{{SUBSCRIPTION_LINK}}",
                    "text": loc_text("Copy subscription link", "Скопировать ссылку подписки"),
                    "type": "copyButton",
                    "svgIconKey": "CloudDownload",
                },
            ],
        ),
        make_block("connect", app["connectAndUseStep"]["description"]),
    ]
    return {"name": "Shadowrocket", "blocks": blocks, "featured": True, "svgIconKey": "Shadowrocket"}


def build_happ_ios(app: dict) -> dict:
    blocks = [
        make_block(
            "installation",
            {
                "en": (
                    "Use this option only if Happ is already installed on your device. "
                    "Do not delete or offload the installed app."
                ),
                "ru": (
                    "Используйте этот вариант только если Happ уже установлен на устройстве. "
                    "Не удаляйте и не выгружайте установленное приложение."
                ),
            },
            [],
        ),
        make_block(
            "add",
            app["addSubscriptionStep"]["description"],
            [
                {
                    "link": "happ://add/{{SUBSCRIPTION_LINK}}",
                    "text": loc_text("Add Subscription", "Добавить подписку"),
                    "type": "subscriptionLink",
                    "svgIconKey": "Plus",
                }
            ],
        ),
        make_block("connect", app["connectAndUseStep"]["description"]),
        make_block(
            "add",
            app["additionalAfterAddSubscriptionStep"]["description"],
            [
                {
                    "link": HAPP_REFILTER_LINK,
                    "text": loc_text("Add configuration", "Добавить конфигурацию"),
                    "type": "external",
                    "svgIconKey": "ExternalLink",
                }
            ],
            title=filter_loc(app["additionalAfterAddSubscriptionStep"]["title"]),
        ),
    ]
    return {"name": "Happ", "blocks": blocks, "featured": False, "svgIconKey": "Happ"}


def build_generic_app(app: dict, platform: str, featured_override: bool | None = None) -> dict:
    name = app["name"]
    blocks: list[dict] = []

    if app.get("additionalBeforeAddSubscriptionStep"):
        extra = convert_additional(app["additionalBeforeAddSubscriptionStep"])
        if extra:
            blocks.append(extra)

    if app.get("installationStep"):
        blocks.append(
            make_block(
                "installation",
                app["installationStep"]["description"],
                convert_buttons(app.get("installationStep", {}).get("buttons") or []),
            )
        )

    add_buttons = []
    url_scheme = app.get("urlScheme", "")
    sub_link = subscription_link_from_scheme(url_scheme) if url_scheme else None
    if sub_link:
        add_buttons.append(
            {
                "link": sub_link,
                "text": loc_text("Add Subscription", "Добавить подписку"),
                "type": "subscriptionLink",
                "svgIconKey": "Plus",
            }
        )

    if app.get("addSubscriptionStep"):
        blocks.append(make_block("add", app["addSubscriptionStep"]["description"], add_buttons))

    if app.get("connectAndUseStep"):
        blocks.append(make_block("connect", app["connectAndUseStep"]["description"]))

    if app.get("additionalAfterAddSubscriptionStep"):
        extra = convert_additional(app["additionalAfterAddSubscriptionStep"])
        if extra:
            blocks.append(extra)

    featured = app.get("isFeatured", False)
    if featured_override is not None:
        featured = featured_override

    icon = ICON_BY_APP.get(name, "DownloadIcon")
    return {"name": name, "blocks": blocks, "featured": featured, "svgIconKey": icon}


def transform_app(app: dict, platform: str) -> dict:
    if platform == "ios":
        if app["name"] == "OneXray":
            return build_onexray_ios(app)
        if app["name"] == "Shadowrocket":
            return build_shadowrocket_ios(app)
        if app["name"] == "Happ":
            return build_happ_ios(app)
        if app["name"] == "v2RayTun":
            return build_generic_app(app, platform, featured_override=False)
        if app["name"] == "Streisand":
            return build_generic_app(app, platform, featured_override=False)
    return build_generic_app(app, platform)


def filter_base_translations(raw: dict) -> dict:
    return {key: {loc: raw[key][loc] for loc in LOCALES} for key, raw_val in raw.items() for loc in LOCALES if loc in raw[key]}


def platform_meta_from_default(default_platforms: dict, platform_key: str) -> dict:
    """Extract displayName (en/ru) and svgIconKey from v7 default template."""
    platform = default_platforms[platform_key]
    return {
        "displayName": filter_loc(platform["displayName"]),
        "svgIconKey": platform["svgIconKey"],
    }


def clone_default_app(app: dict) -> dict:
    return filter_loc(deepcopy(app))


def merge_platform_apps(custom_apps: list[dict], default_apps: list[dict]) -> list[dict]:
    """Keep custom apps and order; append default-only apps in default order."""
    custom_names = {app["name"] for app in custom_apps}
    merged = list(custom_apps)
    for app in default_apps:
        if app["name"] not in custom_names:
            merged.append(clone_default_app(app))
    return merged


def merge_platforms(
    custom_platforms: dict[str, dict],
    default_platforms: dict[str, dict],
) -> dict[str, dict]:
    """Merge VPN for Friends platforms with upstream default template."""
    merged: dict[str, dict] = {}
    ordered_keys = list(default_platforms.keys())
    for key in custom_platforms:
        if key not in ordered_keys:
            ordered_keys.append(key)

    for key in ordered_keys:
        custom = custom_platforms.get(key)
        default_plat = default_platforms.get(key)
        if custom and default_plat:
            merged[key] = {
                "displayName": custom["displayName"],
                "svgIconKey": custom.get("svgIconKey", default_plat["svgIconKey"]),
                "apps": merge_platform_apps(custom["apps"], default_plat["apps"]),
            }
        elif custom:
            merged[key] = filter_loc(deepcopy(custom))
        elif default_plat:
            merged[key] = {
                "displayName": filter_loc(default_plat["displayName"]),
                "svgIconKey": default_plat["svgIconKey"],
                "apps": [clone_default_app(app) for app in default_plat.get("apps", [])],
            }
    return merged


def build_custom_platforms(
    legacy_platforms: dict,
    default_platforms: dict,
) -> dict[str, dict]:
    """Build VPN for Friends platforms from legacy app-config."""
    output_platforms: dict[str, dict] = {}
    for legacy_key, out_key in LEGACY_PLATFORM_MAP.items():
        meta = platform_meta_from_default(default_platforms, out_key)
        apps_raw = legacy_platforms.get(legacy_key, [])
        apps = [transform_app(app, legacy_key) for app in apps_raw]
        output_platforms[out_key] = {**meta, "apps": apps}
    return output_platforms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build vpn-for-friends.json from legacy app-config and v7 default template."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"v7 default template JSON (default: {DEFAULT_SOURCE.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"desired config output path (default: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    legacy = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    default = json.loads(args.source.read_text(encoding="utf-8"))

    branding = legacy["config"]["branding"]
    legacy_platforms = legacy["platforms"]
    default_platforms = default["platforms"]

    custom_platforms = build_custom_platforms(legacy_platforms, default_platforms)
    output_platforms = merge_platforms(custom_platforms, default_platforms)

    result = {
        "locales": list(LOCALES),
        "version": "1",
        "uiConfig": deepcopy(default["uiConfig"]),
        "platforms": output_platforms,
        "svgLibrary": default["svgLibrary"],
        "baseSettings": {
            "metaTitle": "VPN for friends",
            "metaDescription": "VPN subscription setup and device connection",
            "hideGetLinkButton": False,
            "showConnectionKeys": False,
        },
        "baseTranslations": {
            key: {loc: default["baseTranslations"][key][loc] for loc in LOCALES}
            for key in default["baseTranslations"]
        },
        "brandingSettings": {
            "title": "VPN for friends",
            "logoUrl": branding["logoUrl"],
            "supportUrl": branding["supportUrl"],
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
