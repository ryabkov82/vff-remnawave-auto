#!/usr/bin/env bash
set -euo pipefail
code=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:4443/ || true)
[[ "$code" =~ ^2|3 ]] && echo "SMOKE PANEL OK" || { echo "SMOKE PANEL FAIL ($code)"; exit 2; }
