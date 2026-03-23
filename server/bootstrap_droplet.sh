#!/usr/bin/env bash
# One-time (or repeat-safe) setup for a fresh Linux droplet: packages, UFW, fleetrts.env, start scripts.
# Run as root on the server:
#   cd ~/FleetRTS && sudo bash server/bootstrap_droplet.sh
# Options:
#   --no-ufw     Skip firewall (configure DO cloud firewall yourself).
#   --no-start   Do not run start_fleetrts.sh at the end.
#   --force-env  Recreate server/fleetrts.env from the example (default: keep existing file).
#
# Public IP for FLEETRTS_RELAY_HOST: uses env FLEETRTS_RELAY_HOST if set; else tries DigitalOcean
# metadata; else prompts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DO_UFW=1
DO_START=1
FORCE_ENV=0
for arg in "$@"; do
  case "$arg" in
    --no-ufw) DO_UFW=0 ;;
    --no-start) DO_START=0 ;;
    --force-env) FORCE_ENV=1 ;;
  esac
done

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root so apt and ufw work, e.g.: sudo bash server/bootstrap_droplet.sh" >&2
  exit 1
fi

echo "==> apt update / install python3 git curl"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 git curl

RELAY_IP="${FLEETRTS_RELAY_HOST:-}"
if [[ -z "$RELAY_IP" ]]; then
  echo "==> Trying DigitalOcean metadata for public IPv4..."
  RELAY_IP="$(curl -s --max-time 2 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || true)"
fi
if [[ -z "$RELAY_IP" ]]; then
  read -r -p "Enter this droplet's public IPv4 for FLEETRTS_RELAY_HOST: " RELAY_IP
fi
if [[ -z "$RELAY_IP" ]]; then
  echo "No relay IP — aborting." >&2
  exit 1
fi
echo "    Using FLEETRTS_RELAY_HOST=$RELAY_IP"

ENV_FILE="$SCRIPT_DIR/fleetrts.env"
if [[ -f "$ENV_FILE" && "$FORCE_ENV" -eq 0 ]]; then
  echo "==> Keeping existing $ENV_FILE (use --force-env to replace)"
else
  echo "==> Writing $ENV_FILE"
  cp "$SCRIPT_DIR/fleetrts.env.example" "$ENV_FILE"
  sed -i 's/^export FLEETRTS_RELAY_HOST=.*/export FLEETRTS_RELAY_HOST="'"$RELAY_IP"'"/' "$ENV_FILE"
fi

chmod +x "$SCRIPT_DIR/start_fleetrts.sh" "$SCRIPT_DIR/stop_fleetrts.sh"

if [[ "$DO_UFW" -eq 1 ]]; then
  echo "==> UFW: allow SSH, 8765, 8766"
  ufw allow OpenSSH
  ufw allow 8765/tcp
  ufw allow 8766/tcp
  ufw --force enable || true
fi

if [[ "$DO_START" -eq 1 ]]; then
  echo "==> Starting stub + relay"
  bash "$SCRIPT_DIR/start_fleetrts.sh" || true
  echo "==> Local health check:"
  curl -sS "http://127.0.0.1:8765/health" || echo "(curl failed — check ~/fleetrts-logs/stub.log)"
else
  echo "==> Skipped start (--no-start). Run: $SCRIPT_DIR/start_fleetrts.sh"
fi

echo "Done. From your PC: curl -s http://${RELAY_IP}:8765/health"
