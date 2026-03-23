"""Shared bootstrap for starting an MP combat match (default player fleet).

Used by the headless authoritative relay host so it does not duplicate
`launch_mp_combat` logic from demo_game.
"""

from __future__ import annotations

import random
from typing import Any, List, Optional

import demo_game as dg

try:
    from mp_spawn_layout import (
        coop_player_spawn_anchor,
        normalize_mp_player_order,
        pvp_player_spawn_anchor,
    )
except ImportError:
    from core.mp_spawn_layout import (
        coop_player_spawn_anchor,
        normalize_mp_player_order,
        pvp_player_spawn_anchor,
    )


def bootstrap_mp_combat_match(
    *,
    data: dict,
    round_idx: int,
    match_seed: Optional[int],
    use_asteroids: bool,
    enemy_pressure: int,
    groups: List[Any],
    crafts: List[Any],
    player_setup: Optional[dict] = None,
    mp_pvp: bool = False,
) -> Any:
    """Replace `groups` / `crafts` contents and return the new `mission`."""
    groups.clear()
    crafts.clear()
    if isinstance(player_setup, dict) and isinstance(player_setup.get("players"), list):
        players = normalize_mp_player_order(player_setup.get("players") or [])
        colors = player_setup.get("colors") if isinstance(player_setup.get("colors"), dict) else {}
        designs = player_setup.get("designs") if isinstance(player_setup.get("designs"), dict) else {}
        ax0, ay0 = dg.deploy_anchor_xy()
        n_pl = max(1, min(len(players), 8))
        for i, pname in enumerate(players[:8]):
            cid = int(max(0, min(int(colors.get(pname, 0)), 5)))
            rows = designs.get(pname) if isinstance(designs, dict) else None
            if mp_pvp:
                anchor = pvp_player_spawn_anchor(i, n_pl)
            else:
                anchor = coop_player_spawn_anchor(i, ax0, ay0)
            ng, nc = dg.build_player_fleet_from_design(
                data,
                owner_id=pname,
                color_id=cid,
                design_rows=rows if isinstance(rows, list) else None,
                label_prefix=f"{pname}:",
                spawn_anchor=anchor,
            )
            groups.extend(ng)
            crafts.extend(nc)
    else:
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
        mp_pvp=bool(mp_pvp),
    )
    dg.snap_strike_crafts_to_carriers(crafts)
    return mission
