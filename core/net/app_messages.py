"""Application-layer payloads carried inside TCP relay `client_msg.body` (v1).

The relay is opaque: it only forwards JSON. These types are agreed between clients.
"""

from __future__ import annotations
from typing import Optional

LOBBY_CHAT = "lobby_chat"
LOBBY_READY = "lobby_ready"
HOST_CONFIG = "host_config"
START_MATCH = "start_match"
LOBBY_PRESENCE = "lobby_presence"
LOBBY_LOADOUT = "lobby_loadout"


def lobby_chat(text: str) -> dict:
    s = (text or "").strip()
    if len(s) > 240:
        s = s[:240]
    return {"t": LOBBY_CHAT, "text": s}


def lobby_ready(ready: bool) -> dict:
    return {"t": LOBBY_READY, "v": bool(ready)}


def host_config(*, coop: bool, use_asteroids: bool, enemy_pressure: int) -> dict:
    return {
        "t": HOST_CONFIG,
        "coop": bool(coop),
        "use_asteroids": bool(use_asteroids),
        "enemy_pressure": int(max(0, min(int(enemy_pressure), 255))),
    }


def lobby_presence(*, in_fleet_design: bool, color_id: int = 0) -> dict:
    """Tell the room you're in mp_lobby vs multiplayer ship loadouts (no auto-pull on start)."""
    return {
        "t": LOBBY_PRESENCE,
        "in_fleet_design": bool(in_fleet_design),
        "color_id": int(max(0, min(int(color_id), 5))),
    }


def lobby_loadout(*, payload: dict) -> dict:
    return {"t": LOBBY_LOADOUT, "payload": dict(payload or {})}


def start_match(
    *,
    generation: int,
    seed: int,
    round_idx: int,
    coop: bool,
    use_asteroids: bool,
    enemy_pressure: int,
    player_setup: Optional[dict] = None,
) -> dict:
    out = {
        "t": START_MATCH,
        "generation": int(generation),
        "seed": int(seed),
        "round_idx": int(round_idx),
        "coop": bool(coop),
        "use_asteroids": bool(use_asteroids),
        "enemy_pressure": int(max(0, min(int(enemy_pressure), 255))),
    }
    if isinstance(player_setup, dict):
        out["player_setup"] = player_setup
    return out
