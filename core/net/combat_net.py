"""Host-authoritative combat messages over the TCP relay (JSON bodies).

- combat_cmd: client → host player intent (kind + JSON payload). The host applies
  these before step_combat_frame (see core/combat_mp.py).
- combat_snap: host → clients; includes snap_version, canonical state dict, and
  state_hash (SHA-256 of sorted JSON) for desync detection (see core/combat_snapshot.py).

Payloads must be JSON-serializable; RelayClient.send_payload forwards them as
newline-delimited JSON.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Bump when snapshot schema changes (must match combat_snapshot.SNAP_VERSION).
COMBAT_NET_VERSION = 2

COMBAT_CMD = "combat_cmd"
COMBAT_SNAP = "combat_snap"


def combat_cmd(
    *,
    tick: int,
    seq: int,
    kind: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Player intent for the host to apply before stepping the sim.

    ``tick`` should be the last ``combat_snap`` tick the client applied (basis for
    host-side validation in ``combat_mp.combat_cmd_tick_allowed``). Send ``0`` if
    no snapshot has been applied yet; legacy clients that always sent ``0`` remain
    compatible.
    """
    return {
        "t": COMBAT_CMD,
        "tick": int(tick),
        "seq": int(seq),
        "kind": str(kind),
        "payload": dict(payload or {}),
    }


def combat_snap(
    *,
    tick: int,
    snap_version: int,
    state_hash: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Authoritative slice from host; clients apply then verify state_hash."""
    return {
        "t": COMBAT_SNAP,
        "tick": int(tick),
        "snap_version": int(snap_version),
        "state_hash": str(state_hash),
        "state": state,
    }
