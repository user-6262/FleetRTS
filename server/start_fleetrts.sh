#!/usr/bin/env bash
# Start HTTP lobby stub + TCP relay in the background (DigitalOcean / Linux).
# Usage: ./server/start_fleetrts.sh          OR   bash server/start_fleetrts.sh
#        ./server/start_fleetrts.sh --force  (if a stale pidfile exists)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PIDFILE="${FLEETRTS_PIDFILE:-$HOME/.fleetrts-server.pids}"

if [[ "${1:-}" == "--force" ]]; then
  rm -f "$PIDFILE"
fi

if [[ -f "$PIDFILE" ]]; then
  first_pid="$(head -n1 "$PIDFILE" || true)"
  if [[ -n "$first_pid" ]] && kill -0 "$first_pid" 2>/dev/null; then
    echo "Already running (pidfile $PIDFILE). Run server/stop_fleetrts.sh first or use --force." >&2
    exit 1
  fi
  rm -f "$PIDFILE"
fi

if [[ -f "$SCRIPT_DIR/fleetrts.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/fleetrts.env"
  set +a
fi
if [[ -f "$HOME/.fleetrts.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$HOME/.fleetrts.env"
  set +a
fi

if [[ -z "${FLEETRTS_RELAY_HOST:-}" ]]; then
  echo "Missing FLEETRTS_RELAY_HOST. Copy server/fleetrts.env.example to server/fleetrts.env and edit." >&2
  exit 1
fi

export FLEETRTS_RELAY_PORT="${FLEETRTS_RELAY_PORT:-8766}"
LOGDIR="${FLEETRTS_LOGDIR:-$HOME/fleetrts-logs}"
mkdir -p "$LOGDIR"

: >"$PIDFILE"

nohup python3 "$SCRIPT_DIR/droplet_http_stub.py" --host 0.0.0.0 --port 8765 >>"$LOGDIR/stub.log" 2>&1 &
echo $! >>"$PIDFILE"

nohup python3 "$SCRIPT_DIR/tcp_relay.py" --host 0.0.0.0 --port "$FLEETRTS_RELAY_PORT" >>"$LOGDIR/relay.log" 2>&1 &
echo $! >>"$PIDFILE"

echo "FleetRTS started — HTTP :8765  relay :$FLEETRTS_RELAY_HOST:$FLEETRTS_RELAY_PORT"
echo "PIDs: $(tr '\n' ' ' <"$PIDFILE")  |  logs: $LOGDIR  |  stop: $SCRIPT_DIR/stop_fleetrts.sh"
