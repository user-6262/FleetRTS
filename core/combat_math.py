"""Small deterministic helpers shared by demo_game and combat_sim."""

from __future__ import annotations

import math


def dist_xy(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def round_seed(round_idx: int) -> int:
    return round_idx * 10007 + 1337
