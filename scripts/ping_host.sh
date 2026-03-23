#!/usr/bin/env bash
# SAI command: ping_host
# Parameters (stdin JSON): {"args": {"host": "example.com"}}

set -euo pipefail

params=$(cat)
host=$(echo "$params" | python3 -c "
import json, sys
data = json.load(sys.stdin)
h = data.get('args', {}).get('host', '').strip()
print(h)
")

# Validate: only allow safe hostnames/IPs (no shell metacharacters)
if [[ ! "$host" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "Error: invalid hostname" >&2
    exit 1
fi

echo "=== Ping: $host ==="
ping -c 4 "$host"
