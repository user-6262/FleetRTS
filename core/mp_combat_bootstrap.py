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
    player_setup: Optional[dict] = None,
    mp_pvp: bool = False,
) -> Any:
    """Replace `groups` / `crafts` contents and return the new `mission`."""
    groups.clear()
    crafts.clear()
    if isinstance(player_setup, dict) and isinstance(player_setup.get("players"), list):
        players = [str(p)[:48] for p in player_setup.get("players", []) if str(p).strip()]
        colors = player_setup.get("colors") if isinstance(player_setup.get("colors"), dict) else {}
        designs = player_setup.get("designs") if isinstance(player_setup.get("designs"), dict) else {}
        ax0, ay0 = dg.deploy_anchor_xy()
        for i, pname in enumerate(players[:8]):
            cid = int(max(0, min(int(colors.get(pname, 0)), 5)))
            rows = designs.get(pname) if isinstance(designs, dict) else None
            anchor = (ax0 - 520 + (i % 4) * 320.0, ay0 - 180 + (i // 4) * 360.0)
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
