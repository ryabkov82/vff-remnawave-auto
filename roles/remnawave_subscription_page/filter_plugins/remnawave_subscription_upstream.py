"""Ansible filters for production subscription upstream selection and vhost analysis."""

from __future__ import annotations

from typing import Any


def _upstream_marker(host: str, port: int | str) -> str:
    return f"server {host}:{port};"


def _detect_vhost_upstream(content: str, legacy_marker: str, next_marker: str) -> dict[str, bool]:
    has_legacy = legacy_marker in content
    has_next = next_marker in content
    current_is_legacy = has_legacy and not has_next
    current_is_next = has_next and not has_legacy
    return {
        "current_is_legacy": current_is_legacy,
        "current_is_next": current_is_next,
        "known": current_is_legacy or current_is_next,
        "has_legacy_marker": has_legacy,
        "has_next_marker": has_next,
    }


def _current_target_label(upstream_state: dict[str, bool]) -> str:
    if upstream_state.get("has_legacy_marker") and upstream_state.get("has_next_marker"):
        return "ambiguous"
    if upstream_state.get("current_is_legacy"):
        return "legacy"
    if upstream_state.get("current_is_next"):
        return "next"
    return "unknown"


def _cutover_plan(
    upstream_state: dict[str, bool],
    cutover_already_applied: bool,
    stable_legacy_backup_exists: bool,
    production_vhost_exists: bool,
) -> dict[str, Any]:
    cutover_needed = not cutover_already_applied
    current_is_legacy = bool(upstream_state.get("current_is_legacy"))
    stable_backup_would_be_created = (
        cutover_needed
        and not stable_legacy_backup_exists
        and current_is_legacy
    )
    vhost_would_change = cutover_needed
    return {
        "current_target": _current_target_label(upstream_state),
        "planned_target": "next",
        "cutover_already_applied": cutover_already_applied,
        "cutover_needed": cutover_needed,
        "stable_legacy_backup_exists": stable_legacy_backup_exists,
        "stable_legacy_backup_would_be_created": stable_backup_would_be_created,
        "timestamp_backup_would_be_created": cutover_needed and production_vhost_exists,
        "production_vhost_would_change": vhost_would_change,
        "nginx_reload_would_be_required": vhost_would_change,
        "production_healthcheck_would_run": True,
    }


def _uri_transport_error_category(msg: str) -> str:
    text = (msg or "").lower()
    if any(token in text for token in ("name or service", "resolve", "nodename", "getaddrinfo")):
        return "dns"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "certificate" in text or "ssl" in text or "tls" in text:
        return "tls"
    if "connection" in text or "refused" in text or "unreachable" in text:
        return "connection"
    return "unknown"


def _uri_reported_target(result: dict[str, Any]) -> str | None:
    raw = result.get("x_vff_subscription_target")
    if raw is None:
        return None
    text = str(raw).strip().lower()
    return text or None


def _uri_status_is_transport_error(status: Any) -> bool:
    if status is None:
        return True
    try:
        return int(status) < 0
    except (TypeError, ValueError):
        return True


def _uri_health_diagnostics(
    result: Any,
    stage: str = "public_external",
    expected_target: str | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}

    status_raw = result.get("status")
    transport_error = _uri_status_is_transport_error(status_raw)
    content = result.get("content", "")
    if content is None:
        content = ""
    elif not isinstance(content, str):
        content = str(content)

    content_length = len(content) if "content" in result else 0
    content_type = str(result.get("content_type", "") or "")
    reported_target = _uri_reported_target(result)
    normalized_expected = str(expected_target).strip().lower() if expected_target else None

    if transport_error:
        http_status = None if status_raw is None else int(status_raw)
        error_category = _uri_transport_error_category(str(result.get("msg", "")))
    else:
        http_status = int(status_raw)
        error_category = "http" if http_status != 200 else None

    if normalized_expected:
        target_matches = reported_target == normalized_expected
    else:
        target_matches = None

    return {
        "stage": stage,
        "execution_node": "controller",
        "http_status": http_status,
        "content_type": content_type,
        "content_length": content_length,
        "contains_branding": "VPN for friends" in content,
        "expected_target": normalized_expected,
        "reported_target": reported_target,
        "target_matches": target_matches,
        "transport_error": transport_error,
        "error_category": error_category,
    }


def _resolve_preserve_target(upstream_state: dict[str, bool], vhost_exists: bool) -> str:
    if not vhost_exists:
        return "legacy"
    if not isinstance(upstream_state, dict):
        upstream_state = {}
    if upstream_state.get("current_is_legacy"):
        return "legacy"
    if upstream_state.get("current_is_next"):
        return "next"
    raise ValueError(
        "Existing production subscription vhost has an unknown or ambiguous upstream. "
        "Refusing to select an upstream in preserve mode."
    )


def _effective_upstream(
    target: str,
    legacy_host: str,
    legacy_port: int | str,
    legacy_scheme: str,
    next_host: str,
    next_port: int | str,
    next_scheme: str,
) -> dict[str, Any]:
    if target not in {"legacy", "next"}:
        raise ValueError(f"remnawave_subscription_upstream_target must be legacy or next, got {target!r}")

    if target == "legacy":
        return {
            "host": legacy_host,
            "port": int(legacy_port),
            "scheme": legacy_scheme,
            "target": "legacy",
        }

    return {
        "host": next_host,
        "port": int(next_port),
        "scheme": next_scheme,
        "target": "next",
    }


class FilterModule:
    """Filter plugin for subscription production upstream helpers."""

    def filters(self) -> dict[str, Any]:
        return {
            "remnawave_subscription_upstream_marker": self.upstream_marker,
            "remnawave_subscription_vhost_upstream_state": self.vhost_upstream_state,
            "remnawave_subscription_effective_upstream": self.effective_upstream,
            "remnawave_subscription_resolve_preserve_target": self.resolve_preserve_target,
            "remnawave_subscription_cutover_plan": self.cutover_plan,
            "remnawave_subscription_uri_health_diagnostics": self.uri_health_diagnostics,
        }

    def upstream_marker(self, host: str, port: int | str) -> str:
        return _upstream_marker(host, port)

    def vhost_upstream_state(
        self,
        content: str,
        legacy_marker: str,
        next_marker: str,
    ) -> dict[str, bool]:
        if not isinstance(content, str):
            content = str(content or "")
        return _detect_vhost_upstream(content, legacy_marker, next_marker)

    def effective_upstream(
        self,
        target: str,
        legacy_host: str,
        legacy_port: int | str,
        legacy_scheme: str,
        next_host: str,
        next_port: int | str,
        next_scheme: str,
    ) -> dict[str, Any]:
        return _effective_upstream(
            target,
            legacy_host,
            legacy_port,
            legacy_scheme,
            next_host,
            next_port,
            next_scheme,
        )

    def resolve_preserve_target(self, upstream_state: dict[str, bool], vhost_exists: bool) -> str:
        return _resolve_preserve_target(upstream_state, bool(vhost_exists))

    def cutover_plan(
        self,
        upstream_state: dict[str, bool],
        cutover_already_applied: bool,
        stable_legacy_backup_exists: bool,
        production_vhost_exists: bool,
    ) -> dict[str, Any]:
        if not isinstance(upstream_state, dict):
            upstream_state = {}
        return _cutover_plan(
            upstream_state,
            bool(cutover_already_applied),
            bool(stable_legacy_backup_exists),
            bool(production_vhost_exists),
        )

    def uri_health_diagnostics(
        self,
        result: Any,
        stage: str = "public_external",
        expected_target: str | None = None,
    ) -> dict[str, Any]:
        return _uri_health_diagnostics(result, str(stage or "public_external"), expected_target)
