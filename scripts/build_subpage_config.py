#!/usr/bin/env python3
"""Build a Remnawave Subscription Page JSON from base + brand patch.

Examples:
  scripts/build_subpage_config.py \\
    --base roles/.../files/base.json \\
    --patch roles/.../files/brands/vpn-for-friends.patch.json

  scripts/build_subpage_config.py --brand vff --stdout
  scripts/build_subpage_config.py --brand fc --output /tmp/fc.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE_FILES = ROOT / "roles/remnawave_subscription_page_config/files"
DEFAULT_BASE = ROLE_FILES / "base.json"
BRAND_PRESETS = {
    "vff": ROLE_FILES / "brands/vpn-for-friends.patch.json",
    "vpn-for-friends": ROLE_FILES / "brands/vpn-for-friends.patch.json",
    "fc": ROLE_FILES / "brands/friends-connect.patch.json",
    "friends-connect": ROLE_FILES / "brands/friends-connect.patch.json",
}

sys.path.insert(0, str(ROOT / "scripts"))
from subpage_branding import deep_merge  # noqa: E402

# Reuse validator without spawning a subprocess when imported.
sys.path.insert(0, str(ROOT / "scripts"))
import validate_subpage_config as validator  # noqa: E402


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def build(base_path: Path, patch_path: Path) -> dict:
    base = load_json(base_path)
    patch = load_json(patch_path)
    if not isinstance(base, dict):
        raise SystemExit(f"Base config must be a JSON object: {base_path}")
    if not isinstance(patch, dict):
        raise SystemExit(f"Brand patch must be a JSON object: {patch_path}")
    merged = deep_merge(base, patch)
    if not isinstance(merged, dict):
        raise SystemExit("Merged config must be a JSON object")
    return merged


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Subscription Page base.json with a brand patch.",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=DEFAULT_BASE,
        help=f"Base config path (default: {DEFAULT_BASE})",
    )
    parser.add_argument(
        "--patch",
        type=Path,
        default=None,
        help="Brand patch JSON path (or use --brand)",
    )
    parser.add_argument(
        "--brand",
        choices=sorted(BRAND_PRESETS),
        default=None,
        help="Brand preset resolving to a known patch file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write merged JSON to this file",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print merged JSON to stdout",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip structural validation (not recommended)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    patch_path = args.patch
    if args.brand:
        patch_path = BRAND_PRESETS[args.brand]
    if patch_path is None:
        print("Either --patch or --brand is required", file=sys.stderr)
        return 2

    try:
        merged = build(args.base, patch_path)
        if not args.skip_validate:
            validator.validate_config(merged)
    except validator.ValidationError as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        if exc.code not in (0, None):
            if exc.args:
                print(exc.args[0], file=sys.stderr)
            return int(exc.code) if isinstance(exc.code, int) else 1
        raise

    text = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    wrote_somewhere = False
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"OK: wrote {args.output}", file=sys.stderr)
        wrote_somewhere = True
    if args.stdout or not wrote_somewhere:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
