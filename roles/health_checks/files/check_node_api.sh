#!/usr/bin/env bash
set -euo pipefail
timeout 3 bash -c '</dev/tcp/127.0.0.1/8444' && echo "OK" || { echo "FAIL"; exit 1; }
