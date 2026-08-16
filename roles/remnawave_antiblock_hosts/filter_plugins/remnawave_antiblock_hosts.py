"""Ansible filters for Remnawave AntiBlock Host plan / adopt / verify."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import remnawave_antiblock_hosts as _lib  # noqa: E402


class FilterModule:
    """Current-API AntiBlock Host helpers. DELETE stays in the role after desired verify."""

    def filters(self) -> dict[str, Any]:
        return {
            "remnawave_antiblock_trusted_ingress_ips": _lib.validate_trusted_ingress_ips,
            "remnawave_antiblock_hosts_desired": _lib.build_desired_antiblock_hosts,
            "remnawave_antiblock_hosts_plan": _lib.plan_from_filter,
            "remnawave_antiblock_hosts_verify": _lib.verify_from_filter,
            "remnawave_antiblock_hosts_assert_delete": _lib.assert_delete_items_from_filter,
            "remnawave_antiblock_hosts_verify_deleted": _lib.verify_deleted_from_filter,
        }
