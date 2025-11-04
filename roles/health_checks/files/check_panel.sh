#!/usr/bin/env bash
set -euo pipefail
curl -sk --max-time 3 https://127.0.0.1:4443/ >/dev/null && echo "OK" || { echo "FAIL"; exit 1; }
