#!/usr/bin/env python3
"""Shared non-interactive Yandex Cloud auth and HTTP helpers.

Used by Certificate Manager and CDN scripts. Interactive `yc init` is not used.
Service-account authorized key JSON -> JWT PS256 -> IAM token.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

IAM_TOKENS_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
IAM_AUD = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
OPS_API = "https://operation.api.cloud.yandex.net/operations"


def api_get(obj: dict[str, Any] | None, *names: str, default: Any = None) -> Any:
    """Return the first present key (camelCase or snake_case)."""
    if not isinstance(obj, dict):
        return default
    for name in names:
        if name in obj and obj[name] is not None:
            return obj[name]
    return default


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt_ps256(sa_key: dict[str, Any]) -> str:
    """Build a Yandex SA JWT. Requires the cryptography package on the controller."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover - environment
        raise RuntimeError(
            "cryptography is required on the Ansible controller for service-account JWT auth"
        ) from exc

    key_id = str(sa_key.get("id") or sa_key.get("key_id") or "")
    sa_id = str(sa_key.get("service_account_id") or sa_key.get("serviceAccountId") or "")
    private_pem = str(sa_key.get("private_key") or sa_key.get("privateKey") or "")
    if not key_id or not sa_id or not private_pem:
        raise ValueError(
            "SA authorized key JSON must include id, service_account_id, private_key"
        )
    now = int(time.time())
    header = {"typ": "JWT", "alg": "PS256", "kid": key_id}
    payload = {"iss": sa_id, "aud": IAM_AUD, "iat": now, "exp": now + 3600}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    signature = key.sign(  # type: ignore[union-attr]
        signing_input.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )
    return f"{signing_input}.{_b64url(signature)}"


def iam_token_from_sa_key(sa_key: dict[str, Any]) -> str:
    jwt = jwt_ps256(sa_key)
    body = json.dumps({"jwt": jwt}).encode()
    req = urllib.request.Request(
        IAM_TOKENS_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    token = payload.get("iamToken") or payload.get("iam_token")
    if not token:
        raise RuntimeError("IAM token response did not include iamToken")
    return str(token)


def request_json(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Yandex API {method} {url} failed: {exc.code} {detail}") from exc


def wait_operation(
    token: str,
    operation: dict[str, Any],
    timeout: int = 60,
    poll_interval: float = 2,
) -> dict[str, Any]:
    """Poll a long-running Operation until done, error, or timeout.

    HTTP 200 / operation creation is not success. Writes must wait for done.
    """
    if operation.get("done"):
        if operation.get("error"):
            raise RuntimeError(f"Yandex operation failed: {operation['error']}")
        return operation.get("response") or {}
    op_id = str(operation.get("id") or "")
    if not op_id:
        raise RuntimeError("Yandex API returned an operation without id")
    deadline = time.time() + timeout
    current = operation
    interval = max(float(poll_interval), 0.1)
    while time.time() < deadline:
        if current.get("done"):
            if current.get("error"):
                raise RuntimeError(f"Yandex operation failed: {current['error']}")
            return current.get("response") or {}
        time.sleep(interval)
        current = request_json("GET", f"{OPS_API}/{urllib.parse.quote(op_id)}", token)
    raise RuntimeError(f"Timed out waiting for Yandex operation {op_id}")


def load_sa_key(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("SA authorized key must be a JSON object")
    return data


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def token_from_cli_args(args: Any) -> str:
    if getattr(args, "iam_token_file", ""):
        token = read_text(args.iam_token_file).strip()
        if not token:
            raise SystemExit("IAM token file is empty")
        return token
    if getattr(args, "sa_key_file", ""):
        return iam_token_from_sa_key(load_sa_key(read_text(args.sa_key_file)))
    if getattr(args, "iam_token_stdin", False):
        token = sys.stdin.read().strip()
        if not token:
            raise SystemExit("IAM token stdin is empty")
        return token
    if getattr(args, "sa_key_stdin", False):
        return iam_token_from_sa_key(load_sa_key(sys.stdin.read()))
    raise SystemExit(
        "Provide --sa-key-file, --iam-token-file, --sa-key-stdin, or --iam-token-stdin"
    )


def add_auth_args(parser: Any) -> None:
    parser.add_argument("--sa-key-file", default="")
    parser.add_argument("--iam-token-file", default="")
    parser.add_argument("--sa-key-stdin", action="store_true")
    parser.add_argument("--iam-token-stdin", action="store_true")
