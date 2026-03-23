#!/usr/bin/env bash
# SAI command: server_status
# Parameters: none (stdin JSON is ignored for this command)
# Reads JSON params from stdin (SAI convention).

read -r params  # consume stdin (unused for this command)

echo "=== Server Status ==="
echo "Hostname : $(hostname)"
echo "Uptime   : $(uptime -p 2>/dev/null || uptime)"
echo ""
echo "=== CPU Load ==="
uptime | awk -F'load average:' '{print "Load avg:" $2}'
echo ""
echo "=== Memory ==="
if command -v free &>/dev/null; then
    free -h
else
    vm_stat 2>/dev/null | head -10
fi
