#!/usr/bin/env bash
# SAI command: disk_usage
# Parameters (stdin JSON): {"args": {"path": "/target/path"}}

set -euo pipefail

# Read JSON from stdin and extract the "path" argument
params=$(cat)
target_path=$(echo "$params" | python3 -c "
import json, sys
data = json.load(sys.stdin)
p = data.get('args', {}).get('path', '').strip()
print(p if p else '/')
")

# Validate: only allow absolute paths, no shell metacharacters
if [[ ! "$target_path" =~ ^/[a-zA-Z0-9_./ -]*$ ]]; then
    echo "Error: invalid path" >&2
    exit 1
fi

echo "=== Disk Usage: $target_path ==="
df -h "$target_path"
echo ""
echo "=== Top directories by size ==="
du -sh "$target_path"/* 2>/dev/null | sort -rh | head -10
