#!/usr/bin/env bash
set -euo pipefail
echo | openssl s_client -servername www.cloudflare.com -connect 127.0.0.1:8444 -tls1_3 -brief < /dev/null >/dev/null 2>&1       && echo "SMOKE NODE OK" || { echo "SMOKE NODE FAIL"; exit 2; }
