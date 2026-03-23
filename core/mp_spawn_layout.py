"""Shared MP fleet spawn anchors for co-op vs PvP (client launch + headless bootstrap)."""

from __future__ import annotations

from typing import Tuple

try:
    from combat_constants import WORLD_H, WORLD_W
except ImportError:
    from core.combat_constants import WORLD_H, WORLD_W


def coop_player_spawn_anchor(i: int, ax0: float, ay0: float) -> Tuple[float, float]:
    return (ax0 - 520.0 + (i % 4) * 320.0, ay0 - 180.0 + (i // 4) * 360.0)


def pvp_player_spawn_anchor(player_index: int, n_players: int) -> Tuple[float, float]:
    """West vs east staging; mirrors launch_mp_combat PvP layout."""
    n = max(1, min(int(n_players), 8))
    pvp_left = max(1, (n + 1) // 2)
    i = max(0, min(int(player_index), n - 1))
    if i < pvp_left:
        li = i
        lx = WORLD_W * 0.20 + (li % 2) * 210.0
        ly = WORLD_H * 0.36 + (li // 2) * 210.0
        return lx, ly
    ri = i - pvp_left
    rx = WORLD_W * 0.80 - (ri % 2) * 210.0
    ry = WORLD_H * 0.36 + (ri // 2) * 210.0
    return rx, ry
