#!/usr/bin/env bash
# SAI command: datetime_info
# Parameters: timezone (optional) — IANA timezone name e.g. "Asia/Tokyo"
# Reads JSON params from stdin (SAI convention).

set -euo pipefail

params=$(cat)

# Extract optional timezone param (default: system timezone)
timezone=$(echo "$params" | python3 -c "
import json, sys
p = json.load(sys.stdin)
print(p.get('timezone', ''))
" 2>/dev/null || true)

if [[ -n "$timezone" ]]; then
    # Validate: allow only IANA-style names (letters, digits, slash, underscore, hyphen)
    if ! echo "$timezone" | grep -qE '^[A-Za-z0-9/_+-]{1,64}$'; then
        echo "Error: invalid timezone name" >&2
        exit 1
    fi
    TZ="$timezone"
    export TZ
fi

echo "=== Date & Time ==="
echo "Date     : $(date '+%Y-%m-%d')"
echo "Time     : $(date '+%H:%M:%S')"
echo "Day      : $(date '+%A')"
echo "Timezone : $(date '+%Z %z')"
echo ""
echo "=== Additional Info ==="
echo "UTC      : $(TZ=UTC date '+%Y-%m-%d %H:%M:%S UTC')"
echo "Unix ts  : $(date '+%s')"
echo "Week     : Week $(date '+%V') of $(date '+%Y')"
