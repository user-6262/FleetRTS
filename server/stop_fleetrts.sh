#!/usr/bin/env bash
# Stop processes started by start_fleetrts.sh (same pidfile).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="${FLEETRTS_PIDFILE:-$HOME/.fleetrts-server.pids}"

if [[ ! -f "$PIDFILE" ]]; then
  echo "No pidfile at $PIDFILE — nothing to stop." >&2
  exit 0
fi

while read -r pid; do
  [[ -z "$pid" ]] && continue
  kill "$pid" 2>/dev/null || true
done <"$PIDFILE"

rm -f "$PIDFILE"
echo "Stopped FleetRTS stub + relay."
