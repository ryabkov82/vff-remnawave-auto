#!/usr/bin/env python3
"""Tests for Remnawave Subscription Page config Ansible filters."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "roles/remnawave_subscription_page_config/filter_plugins"
    ),
)

from remnawave_subpage_config import FilterModule  # noqa: E402


class RemnawaveSubpageConfigFiltersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.filters = FilterModule()
        self.canonicalize = self.filters.canonicalize
        self.diff_paths = self.filters.diff_paths

    def test_strips_en_ru_values(self) -> None:
        config = {
            "locales": ["en", "ru"],
            "platforms": {
                "ios": {
                    "displayName": {"en": "  iOS  ", "ru": " iOS"},
                    "apps": [],
                }
            },
            "baseTranslations": {
                "title": {"en": " Hello ", "ru": " Привет "},
            },
        }
        result = self.canonicalize(config)
        self.assertEqual(result["platforms"]["ios"]["displayName"], {"en": "iOS", "ru": "iOS"})
        self.assertEqual(result["baseTranslations"]["title"], {"en": "Hello", "ru": "Привет"})

    def test_removes_locale_not_in_locales_list(self) -> None:
        config = {
            "locales": ["en", "ru"],
            "platforms": {
                "android": {
                    "displayName": {"en": "Android", "ru": "Android", "zh": "安卓"},
                    "apps": [],
                }
            },
            "baseTranslations": {
                "subtitle": {"en": "Sub", "ru": "Подзаг", "fa": "زیر"},
            },
        }
        result = self.canonicalize(config)
        self.assertEqual(
            result["platforms"]["android"]["displayName"],
            {"en": "Android", "ru": "Android"},
        )
        self.assertEqual(result["baseTranslations"]["subtitle"], {"en": "Sub", "ru": "Подзаг"})

    def test_preserves_nested_localized_strings(self) -> None:
        config = {
            "locales": ["en", "ru"],
            "platforms": {
                "ios": {
                    "apps": [
                        {
                            "blocks": [
                                {
                                    "title": {"en": " Title ", "ru": " Заголовок "},
                                    "description": {"en": " Body ", "ru": " Текст "},
                                }
                            ]
                        }
                    ]
                }
            },
            "baseTranslations": {},
        }
        result = self.canonicalize(config)
        block = result["platforms"]["ios"]["apps"][0]["blocks"][0]
        self.assertEqual(block["title"], {"en": "Title", "ru": "Заголовок"})
        self.assertEqual(block["description"], {"en": "Body", "ru": "Текст"})

    def test_does_not_trim_urls_svg_or_plain_strings(self) -> None:
        svg = "<svg>  spaced  </svg>"
        url = " https://example.com/path "
        config = {
            "locales": ["en", "ru"],
            "platforms": {
                "android": {
                    "apps": [
                        {
                            "blocks": [
                                {
                                    "buttons": [
                                        {
                                            "link": url,
                                            "svgIconKey": "ExternalLink",
                                        }
                                    ],
                                    "svgIconKey": "DownloadIcon",
                                }
                            ],
                            "svgIconKey": "Happ",
                            "name": " Happ ",
                        }
                    ]
                }
            },
            "svgLibrary": {"TV": svg},
            "baseTranslations": {},
            "baseSettings": {"metaTitle": " VPN "},
        }
        result = self.canonicalize(config)
        button = result["platforms"]["android"]["apps"][0]["blocks"][0]["buttons"][0]
        self.assertEqual(button["link"], url)
        self.assertEqual(result["svgLibrary"]["TV"], svg)
        self.assertEqual(result["baseSettings"]["metaTitle"], " VPN ")
        self.assertEqual(result["platforms"]["android"]["apps"][0]["name"], " Happ ")

    def test_does_not_mutate_input_object(self) -> None:
        config = {
            "locales": ["en", "ru"],
            "platforms": {
                "linux": {
                    "displayName": {"en": " Linux ", "ru": " Linux "},
                    "apps": [],
                }
            },
            "baseTranslations": {
                "key": {"en": " Value ", "ru": " Значение "},
            },
        }
        original = copy.deepcopy(config)
        self.canonicalize(config)
        self.assertEqual(config, original)

    def test_semantically_equal_raw_and_stored_configs(self) -> None:
        desired = {
            "locales": ["en", "ru"],
            "platforms": {
                "ios": {
                    "displayName": {"en": "iOS", "ru": "iOS", "zh": "iOS"},
                    "apps": [
                        {
                            "blocks": [
                                {
                                    "title": {"en": "Install", "ru": "Установка"},
                                }
                            ]
                        }
                    ],
                }
            },
            "baseTranslations": {
                "welcome": {"en": "Welcome", "ru": "Добро пожаловать", "fa": "fa"},
            },
        }
        stored = {
            "locales": ["en", "ru"],
            "platforms": {
                "ios": {
                    "displayName": {"en": "iOS", "ru": "iOS"},
                    "apps": [
                        {
                            "blocks": [
                                {
                                    "title": {"en": "Install", "ru": "Установка"},
                                }
                            ]
                        }
                    ],
                }
            },
            "baseTranslations": {
                "welcome": {"en": "Welcome", "ru": "Добро пожаловать"},
            },
        }
        self.assertEqual(self.canonicalize(desired), self.canonicalize(stored))

    def test_diff_paths_returns_only_paths_without_values(self) -> None:
        left = {
            "locales": ["en", "ru"],
            "platforms": {
                "ios": {
                    "apps": [
                        {
                            "blocks": [
                                {
                                    "buttons": [
                                        {"link": "https://left.example"},
                                    ]
                                }
                            ]
                        }
                    ]
                }
            },
            "baseTranslations": {},
        }
        right = {
            "locales": ["en", "ru"],
            "platforms": {
                "ios": {
                    "apps": [
                        {
                            "blocks": [
                                {
                                    "buttons": [
                                        {"link": "https://right.example/secret"},
                                    ]
                                }
                            ]
                        }
                    ]
                }
            },
            "baseTranslations": {},
        }
        paths = self.diff_paths(left, right)
        self.assertEqual(
            paths,
            ["platforms.ios.apps[0].blocks[0].buttons[0].link"],
        )
        for path in paths:
            self.assertNotIn("https://", path)
            self.assertNotIn("secret", path)


if __name__ == "__main__":
    unittest.main()
