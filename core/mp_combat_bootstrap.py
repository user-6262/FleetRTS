"""Shared bootstrap for starting an MP combat match (default player fleet).

Used by the headless authoritative relay host so it does not duplicate
`launch_mp_combat` logic from demo_game.
"""

from __future__ import annotations

import random
from typing import Any, List, Optional

import demo_game as dg


def bootstrap_mp_combat_match(
    *,
    data: dict,
    round_idx: int,
    match_seed: Optional[int],
    use_asteroids: bool,
    enemy_pressure: int,
    groups: List[Any],
    crafts: List[Any],
) -> Any:
    """Replace `groups` / `crafts` contents and return the new `mission`."""
    groups.clear()
    crafts.clear()
    ng, nc = dg.build_initial_player_fleet(data)
    groups.extend(ng)
    crafts.extend(nc)
    dg.clear_selection(groups)
    dg.clear_craft_selection(crafts)
    roster = dg.loadout_player_capitals_sorted(groups)
    if roster:
        roster[0].selected = True
    obs = dg.parse_obstacles(data) if use_asteroids else []
    rng_seed = int(match_seed) if match_seed is not None else dg.round_seed(round_idx)
    mission = dg.begin_combat_round(
        data,
        groups,
        round_idx,
        random.Random(rng_seed),
        obs,
        enemy_pressure=enemy_pressure,
    )
    dg.snap_strike_crafts_to_carriers(crafts)
    return mission
