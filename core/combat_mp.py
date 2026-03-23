"""Apply remote (or local) combat commands on the authoritative host."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _save_selection(groups: List[Any], crafts: List[Any]) -> Tuple[List[Tuple[Any, bool]], List[Tuple[Any, bool]]]:
    return [(g, g.selected) for g in groups], [(c, c.selected) for c in crafts]


def _restore_selection(
    gs: List[Tuple[Any, bool]], cs: List[Tuple[Any, bool]]
) -> None:
    for g, s in gs:
        g.selected = s
    for c, s in cs:
        c.selected = s


def _overlay_selection(
    groups: List[Any],
    crafts: List[Any],
    group_labels: List[str],
    craft_labels: List[str],
) -> None:
    gls = set(group_labels)
    cls = set(craft_labels)
    for g in groups:
        g.selected = g.label in gls
    for c in crafts:
        c.selected = c.label in cls


def apply_combat_command(
    *,
    data: dict,
    groups: List[Any],
    crafts: List[Any],
    mission: Any,
    formation_mode_holder: List[int],
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    ping_ghost_anchor_labels: Any,
    mission_obstacles: List[Any],
    cg_weapons_free: List[bool],
    control_groups: List[Any],
    ping_ready_at_ms_holder: List[int],
    now_ms: int,
    audio: Any,
    cmd: Dict[str, Any],
) -> None:
    """Mutates world state. Caller is the host only."""
    import random

    import demo_game as dg

    kind = str(cmd.get("kind", ""))
    pl = cmd.get("payload") or {}
    glab = [str(x) for x in (pl.get("group_labels") or [])]
    clab = [str(x) for x in (pl.get("craft_labels") or [])]
    sender = str(cmd.get("sender") or "").strip()

    def groups_pick() -> List[Any]:
        m = {g.label: g for g in groups}
        out = [m[l] for l in glab if l in m and not m[l].dead]
        if sender:
            out = [g for g in out if getattr(g, "owner_id", "") == sender]
        return out

    def crafts_pick() -> List[Any]:
        m = {c.label: c for c in crafts}
        out = [m[l] for l in clab if l in m and not m[l].dead]
        if sender:
            out = [c for c in out if getattr(c, "owner_id", "") == sender]
        return out

    sg, sc = _save_selection(groups, crafts)
    try:
        if glab or clab:
            _overlay_selection(groups, crafts, glab, clab)
        if kind == "hold":
            for g in groups_pick():
                g.hold_position()
                if g.class_name == "Carrier":
                    dg.clear_carrier_air_orders(g)
        elif kind == "move_world":
            wpx, wpy = float(pl["wpx"]), float(pl["wpy"])
            fm = int(pl.get("formation_mode", formation_mode_holder[0]))
            sel = groups_pick()
            if pl.get("attack_move"):
                dg.issue_attack_move_orders(sel, wpx, wpy, fm)
            else:
                dg.issue_move_orders(sel, wpx, wpy, fm)
        elif kind == "line_move_world":
            wx0, wy0 = float(pl["wx0"]), float(pl["wy0"])
            wx1, wy1 = float(pl["wx1"]), float(pl["wy1"])
            fm = int(pl.get("formation_mode", formation_mode_holder[0]))
            sel = [g for g in groups_pick() if g.render_capital]
            if pl.get("attack_move"):
                dg.issue_attack_line_move_orders(sel, wx0, wy0, wx1, wy1, fm)
            else:
                dg.issue_line_move_orders(sel, wx0, wy0, wx1, wy1, fm)
        elif kind == "attack_target_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            caps = [g for g in groups_pick() if g.render_capital]
            mark = dg.pick_hostile_at(groups, crafts, mx, my, cam_x, cam_y)
            if mark is None and mission.kind == "strike" and mission.objective and not mission.objective.dead:
                if dg.pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y):
                    mark = mission.objective
            if mark is not None:
                for gc in caps:
                    gc.attack_target = mark
        elif kind == "capital_context_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            sel_ord = groups_pick()
            sel_caps_ctx = [g for g in sel_ord if g.render_capital]
            if not sel_caps_ctx:
                return
            wpx, wpy = dg.screen_to_world_waypoint(mx, my, cam_x, cam_y)
            mark = dg.pick_hostile_at(groups, crafts, mx, my, cam_x, cam_y)
            atk_set = False
            if mark is not None:
                for gc in sel_caps_ctx:
                    gc.attack_target = mark
                atk_set = True
            elif (
                mission.kind == "strike"
                and mission.objective
                and not mission.objective.dead
                and dg.pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y)
            ):
                for gc in sel_caps_ctx:
                    gc.attack_target = mission.objective
                atk_set = True
            if not atk_set:
                dg.issue_move_orders(sel_ord, wpx, wpy, formation_mode_holder[0])
        elif kind == "fighter_strike_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            wpx, wpy = dg.screen_to_world_waypoint(mx, my, cam_x, cam_y)
            mark = dg.pick_hostile_at(groups, crafts, mx, my, cam_x, cam_y)
            if mark is None and mission.kind == "strike" and mission.objective and not mission.objective.dead:
                if dg.pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y):
                    mark = mission.objective
            dg.apply_fighter_strike_order(data, crafts, groups_pick(), wpx, wpy, mark)
        elif kind == "bomber_strike_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            wpx, wpy = dg.screen_to_world_waypoint(mx, my, cam_x, cam_y)
            mark = dg.pick_hostile_at(groups, crafts, mx, my, cam_x, cam_y)
            if mark is None and mission.kind == "strike" and mission.objective and not mission.objective.dead:
                if dg.pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y):
                    mark = mission.objective
            dg.apply_bomber_context_order(data, crafts, groups_pick(), wpx, wpy, mark)
        elif kind == "sensor_ping":
            seed = int(pl.get("rng_seed", now_ms))
            if now_ms >= ping_ready_at_ms_holder[0]:
                dg.spawn_active_sensor_pings(
                    groups,
                    crafts,
                    active_pings,
                    sensor_ghosts,
                    mission_obstacles,
                    random.Random(seed % 100003),
                    anchor_labels=ping_ghost_anchor_labels,
                )
                ping_ready_at_ms_holder[0] = now_ms + int(dg.ACTIVE_PING_COOLDOWN * 1000)
        elif kind == "recall_carriers":
            for g in groups_pick():
                if g.class_name == "Carrier":
                    dg.clear_carrier_air_orders(g)
        elif kind == "clear_carrier_air_selected":
            if glab:
                gm = {g.label: g for g in groups}
                for lab in glab:
                    g = gm.get(lab)
                    if g and g.side == "player" and g.class_name == "Carrier":
                        dg.clear_carrier_air_orders(g)
            else:
                for g in groups:
                    if g.side == "player" and g.selected and g.class_name == "Carrier":
                        dg.clear_carrier_air_orders(g)
        elif kind == "formation_cycle":
            formation_mode_holder[0] = (formation_mode_holder[0] + 1) % 3
        elif kind == "weapons_toggle":
            if dg.toggle_weapon_stance_for_selection(groups, control_groups, cg_weapons_free):
                if audio:
                    audio.play_positive()
            elif audio:
                audio.play_negative()
        elif kind == "control_assign":
            slot = int(pl["slot"])
            labels = [str(x) for x in (pl.get("labels") or [])]
            if 0 <= slot < len(control_groups):
                control_groups[slot] = labels
        elif kind == "select_slot":
            slot = int(pl["slot"])
            shift = bool(pl.get("shift"))
            labels = control_groups[slot] if 0 <= slot < len(control_groups) else None
            if labels:
                picked = [
                    g
                    for g in groups
                    if g.side == "player" and not g.dead and g.render_capital and g.label in labels
                ]
                if picked:
                    if shift:
                        dg.add_to_selection(groups, picked)
                    else:
                        dg.clear_craft_selection(crafts)
                        dg.set_selection(groups, picked)
        elif kind == "select_strike_wing":
            sq = int(pl["squadron_index"])
            shift = bool(pl.get("shift"))
            dg.select_strike_wing_for_carriers(crafts, groups, sq, shift)
        elif kind == "clear_craft_selection":
            dg.clear_craft_selection(crafts)
    finally:
        _restore_selection(sg, sc)
