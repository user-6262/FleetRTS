"""
Authoritative-friendly combat rules: mission setup, movement, fog, asteroids, reinforcements, deaths, extract, salvage.

Uses lazy `import demo_game as dg` only where ship factories / datatypes still live (make_group, MissionState, …).
World geometry lives in combat_constants so headless code does not depend on demo_game for WORLD_W/H.

See COMBAT_DESIGN.txt for sandbox / MP direction (multi-side, custom objectives, scenario params).
"""
from __future__ import annotations

import math
import random
from itertools import combinations
from typing import Any, List, Optional, Set, Tuple

import pygame

try:
    from combat_constants import (
        BALLISTIC_ACQUISITION_MULT,
        CAPITAL_SEPARATION,
        FOG_CH,
        FOG_CW,
        REINF_INTERVAL_BASE,
        SALVAGE_PICKUP_R,
        SALVAGE_POD_VALUE,
        SENSOR_RANGE_CAPITAL,
        SENSOR_RANGE_STRIKE,
        SEPARATION_PUSH,
        SHIP_BLOCK_RADIUS_CAPITAL,
        SHIP_BLOCK_RADIUS_CRAFT,
        WORLD_EDGE_MARGIN,
        WORLD_H,
        WORLD_W,
    )
    from combat_math import dist_xy
except ImportError:
    from core.combat_constants import (
        BALLISTIC_ACQUISITION_MULT,
        CAPITAL_SEPARATION,
        FOG_CH,
        FOG_CW,
        REINF_INTERVAL_BASE,
        SALVAGE_PICKUP_R,
        SALVAGE_POD_VALUE,
        SENSOR_RANGE_CAPITAL,
        SENSOR_RANGE_STRIKE,
        SEPARATION_PUSH,
        SHIP_BLOCK_RADIUS_CAPITAL,
        SHIP_BLOCK_RADIUS_CRAFT,
        WORLD_EDGE_MARGIN,
        WORLD_H,
        WORLD_W,
    )
    from core.combat_math import dist_xy


def extract_rect_world() -> pygame.Rect:
    return pygame.Rect(WORLD_W // 2 - 320, 64, 640, 112)


def collect_salvage_pods(mission: Any, groups: List[Any]) -> None:
    """Recovery rounds: player capitals pick up pods (side hard-coded as today — generalize with team ids later)."""
    for pod in mission.pods:
        if pod.collected:
            continue
        for g in groups:
            if g.side == "player" and not g.dead and g.render_capital:
                if dist_xy(g.x, g.y, pod.x, pod.y) < SALVAGE_PICKUP_R:
                    pod.collected = True
                    mission.pods_collected += 1
                    break


def tick_player_engagement_timers(groups: List[Any], crafts: List[Any], dt: float) -> None:
    for g in groups:
        if g.side == "player":
            g.engagement_timer = max(0.0, g.engagement_timer - dt)
    for c in crafts:
        if c.side == "player":
            c.engagement_timer = max(0.0, c.engagement_timer - dt)


def finalize_deaths(groups: List[Any], crafts: List[Any]) -> None:
    for g in groups:
        if g.hp <= 0 and not g.dead:
            g.dead = True
            g.hp = 0
    for c in crafts:
        if c.hp <= 0 and not c.dead:
            c.dead = True
            c.hp = 0


def mission_allows_extract(ms: Any) -> bool:
    if ms.kind == "pvp":
        return False
    if ms.kind == "strike":
        return ms.objective is not None and ms.objective.dead
    return ms.pods_collected >= ms.pods_required


def finalize_objective_if_dead(obj: Optional[Any]) -> None:
    if obj and not obj.dead and obj.hp <= 0:
        obj.dead = True
        obj.hp = 0.0


def begin_combat_round(
    data: dict,
    groups: List[Any],
    round_idx: int,
    rng: random.Random,
    obstacles: List[Any],
    enemy_pressure: int = 0,
    mp_pvp: bool = False,
) -> Any:
    import demo_game as dg

    groups[:] = [g for g in groups if g.side != "enemy"]
    serial = 0
    ep = max(0, min(3, int(enemy_pressure)))
    n_en_boost = ep
    reinf_boost = (ep + 1) // 2

    if mp_pvp:
        return dg.MissionState(
            kind="pvp",
            objective=None,
            pods=[],
            reinf_remaining=0,
            reinf_timer=REINF_INTERVAL_BASE,
            pods_collected=0,
            pods_required=0,
            enemy_label_serial=0,
            initial_enemies_spawned=0,
            obstacles=list(obstacles),
            mp_pvp=True,
        )

    def add_enemy(cls_name: str, ex: float, ey: float) -> None:
        nonlocal serial
        serial += 1
        groups.append(dg.make_group(data, "enemy", f"E-{serial}", cls_name, ex, ey))

    kind = "strike" if (round_idx % 2 == 1) else "recovery"
    objective: Optional[Any] = None
    pods: List[Any] = []
    pods_required = 0

    if kind == "strike":
        # Random relay position on the enemy side (deterministic from rng / round_seed).
        ox = rng.uniform(WORLD_W * 0.58, WORLD_W * 0.82)
        oy = rng.uniform(WORLD_H * 0.18, WORLD_H * 0.52)
        hp = 600.0 + float(round_idx) * 125.0
        objective = dg.GroundObjective(x=ox, y=oy, hp=hp, max_hp=hp)
        n_en = min(18, 4 + min(10, round_idx * 2) + n_en_boost)
        pool = ["Frigate", "Destroyer", "Frigate", "Cruiser"]
        if round_idx >= 3:
            pool = ["Destroyer", "Cruiser", "Cruiser", "Frigate"]
        if round_idx >= 5:
            pool = ["Cruiser", "Destroyer", "Battleship", "Cruiser", "Frigate"]
        for i in range(n_en):
            ang = (i / max(1, n_en)) * 2 * math.pi + rng.uniform(0, 0.45)
            rad = 185.0 + (i % 4) * 54.0 + rng.uniform(-18, 18)
            add_enemy(rng.choice(pool), ox + math.cos(ang) * rad, oy + math.sin(ang) * rad * 0.88)
    else:
        base_x = rng.uniform(WORLD_W * 0.48, WORLD_W * 0.68)
        base_y = rng.uniform(WORLD_H * 0.18, WORLD_H * 0.36)
        n_pods = 3 + min(5, (round_idx + 1) // 2)
        for i in range(n_pods):
            pods.append(
                dg.SalvagePod(
                    x=base_x + i * 128.0 + rng.randint(-40, 40),
                    y=base_y + rng.randint(-150, 170),
                    value=SALVAGE_POD_VALUE + rng.randint(0, 8),
                )
            )
        n_en = min(14, 2 + min(8, round_idx + 2) + n_en_boost)
        esc_pool = ["Frigate", "Destroyer", "Frigate"]
        if round_idx >= 4:
            esc_pool.append("Cruiser")
        for _ in range(n_en):
            add_enemy(
                rng.choice(esc_pool),
                base_x - 100 + rng.randint(-80, 240),
                base_y + rng.randint(-110, 210),
            )
        pods_required = max(1, (n_pods + 1) // 2)

    reinf_n = min(24, 2 + (round_idx + 1) // 2 + (1 if kind == "strike" else 0) + reinf_boost)

    return dg.MissionState(
        kind=kind,
        objective=objective,
        pods=pods,
        reinf_remaining=reinf_n,
        reinf_timer=REINF_INTERVAL_BASE + rng.uniform(2.0, 11.0),
        pods_collected=0,
        pods_required=pods_required,
        enemy_label_serial=serial,
        initial_enemies_spawned=serial,
        obstacles=list(obstacles),
        mp_pvp=bool(mp_pvp),
    )


def spawn_enemy_reinforcement(data: dict, groups: List[Any], mission: Any, rng: random.Random) -> None:
    import demo_game as dg

    mission.enemy_label_serial += 1
    side = rng.choice(["left", "right"])
    ex = 60.0 if side == "left" else WORLD_W - 60.0
    ey = rng.uniform(WORLD_H * 0.16, WORLD_H * 0.8)
    pool = ["Frigate", "Destroyer", "Cruiser", "Destroyer", "Frigate"]
    if mission.enemy_label_serial > 10 and rng.random() < 0.28:
        pool.extend(["Battleship", "Cruiser"])
    cls_name = rng.choice(pool)
    groups.append(dg.make_group(data, "enemy", f"E-{mission.enemy_label_serial}", cls_name, ex, ey))


def compute_mission_salvage_reward(mission: Any, supplies_left: float, avg_hp_frac: float) -> int:
    strike_bonus = 40 if mission.kind == "strike" and mission.objective and mission.objective.dead else 0
    recovery_bonus = mission.pods_collected * 10
    threat = mission.enemy_label_serial * 3
    return int(16 + threat + supplies_left * 0.2 + avg_hp_frac * 52 + recovery_bonus + strike_bonus)


# --- Fog of war (player-centric visibility grid; server can reuse the same rules) ---


def fog_cell_index(wx: float, wy: float) -> int:
    ci = int(wx / WORLD_W * FOG_CW)
    cj = int(wy / WORLD_H * FOG_CH)
    ci = max(0, min(FOG_CW - 1, ci))
    cj = max(0, min(FOG_CH - 1, cj))
    return ci + cj * FOG_CW


def fog_stamp_disk(visible: List[bool], px: float, py: float, radius: float) -> None:
    if radius <= 0:
        return
    pad = radius + max(WORLD_W / FOG_CW, WORLD_H / FOG_CH) * 2
    ci0 = int((px - pad) / WORLD_W * FOG_CW)
    ci1 = int((px + pad) / WORLD_W * FOG_CW)
    cj0 = int((py - pad) / WORLD_H * FOG_CH)
    cj1 = int((py + pad) / WORLD_H * FOG_CH)
    ci0 = max(0, min(FOG_CW - 1, ci0))
    ci1 = max(0, min(FOG_CW - 1, ci1))
    cj0 = max(0, min(FOG_CH - 1, cj0))
    cj1 = max(0, min(FOG_CH - 1, cj1))
    r2 = radius * radius
    for cj in range(cj0, cj1 + 1):
        cy = (cj + 0.5) / FOG_CH * WORLD_H
        for ci in range(ci0, ci1 + 1):
            cx = (ci + 0.5) / FOG_CW * WORLD_W
            dx, dy = cx - px, cy - py
            if dx * dx + dy * dy <= r2:
                visible[ci + cj * FOG_CW] = True


def update_fog_of_war(fog: Any, groups: List[Any], crafts: List[Any], pings: List[Any]) -> None:
    n = FOG_CW * FOG_CH
    vis = [False] * n
    for g in groups:
        if g.side != "player" or g.dead:
            continue
        fog_stamp_disk(vis, g.x, g.y, SENSOR_RANGE_CAPITAL)
    for c in crafts:
        if c.side != "player" or c.dead or c.parent.dead:
            continue
        fog_stamp_disk(vis, c.x, c.y, SENSOR_RANGE_STRIKE)
    for p in pings:
        if p.ttl > 0:
            fog_stamp_disk(vis, p.x, p.y, p.radius)
    for i in range(n):
        if vis[i]:
            fog.explored[i] = True
    fog.visible = vis


def fog_cell_visible(fog: Any, wx: float, wy: float) -> bool:
    return fog.visible[fog_cell_index(wx, wy)]


def fog_cell_explored(fog: Any, wx: float, wy: float) -> bool:
    return fog.explored[fog_cell_index(wx, wy)]


def cull_sensor_ghosts_if_ping_anchors_lost(
    groups: List[Any],
    crafts: List[Any],
    sensor_ghosts: List[Any],
    anchor_labels: Set[str],
) -> None:
    if not anchor_labels or not sensor_ghosts:
        return
    sel: Set[str] = set()
    for g in groups:
        if g.side == "player" and g.selected and not g.dead and g.render_capital:
            sel.add(g.label)
    for c in crafts:
        if c.side == "player" and c.selected and not c.dead and not c.parent.dead:
            sel.add(c.label)
            sel.add(c.parent.label)
    if not (anchor_labels & sel):
        sensor_ghosts.clear()
        anchor_labels.clear()


# --- Movement & craft orbit (no pygame; Group/Craft duck-typed) ---


def move_toward_xy(x: float, y: float, tx: float, ty: float, step: float) -> Tuple[float, float]:
    dx, dy = tx - x, ty - y
    d = math.hypot(dx, dy)
    if d < 3:
        return tx, ty
    if step >= d:
        return tx, ty
    return x + dx / d * step, y + dy / d * step


def effective_capital_move_speed(g: Any, player_capitals: List[Any]) -> float:
    if not g.waypoint or g.move_pace_key is None:
        return g.speed
    peers = [
        h
        for h in player_capitals
        if not h.dead
        and h.render_capital
        and h.move_pace_key == g.move_pace_key
        and h.waypoint is not None
    ]
    if len(peers) <= 1:
        return g.speed
    return min(h.speed for h in peers)


def move_group(g: Any, dt: float, player_capitals: List[Any]) -> None:
    if g.waypoint:
        wx, wy = g.waypoint
        step = effective_capital_move_speed(g, player_capitals) * dt
        g.x, g.y = move_toward_xy(g.x, g.y, wx, wy, step)
        if dist_xy(g.x, g.y, wx, wy) < 6:
            g.clear_waypoint()
            g.attack_move = False


def separate_player_capitals(groups: List[Any], dt: float, mp_pvp: bool = False) -> None:
    caps = [g for g in groups if g.side == "player" and not g.dead and g.render_capital]
    for a, b in combinations(caps, 2):
        if mp_pvp and getattr(a, "owner_id", None) != getattr(b, "owner_id", None):
            continue
        dx = b.x - a.x
        dy = b.y - a.y
        d = math.hypot(dx, dy)
        if d >= CAPITAL_SEPARATION or d < 0.001:
            continue
        push = (CAPITAL_SEPARATION - d) * (SEPARATION_PUSH / CAPITAL_SEPARATION) * dt
        nx, ny = dx / d, dy / d
        a.x -= nx * push
        a.y -= ny * push
        b.x += nx * push
        b.y += ny * push


def rally_xy_for_craft(c: Any) -> Tuple[float, float]:
    p = c.parent
    wings = p.strike_rally_wings
    # Bombers: strike wing focus beats stale wing/fleet rallies (capital attack_target is separate).
    if getattr(c, "class_name", None) == "Bomber":
        t = getattr(p, "strike_focus_target", None)
        if t is not None and not getattr(t, "dead", False):
            tx, ty = float(t.x), float(t.y)
            px, py = float(p.x), float(p.y)
            d_tp = dist_xy(tx, ty, px, py)
            if d_tp > 1.0:
                ux = (px - tx) / d_tp
                uy = (py - ty) / d_tp
            else:
                ux, uy = 1.0, 0.0
            mr = float(getattr(c, "max_range", 200.0))
            standoff = max(72.0, min(mr * 0.82, d_tp * 0.95))
            return tx + ux * standoff, ty + uy * standoff
    if c.squadron_index < len(wings) and wings[c.squadron_index] is not None:
        return wings[c.squadron_index]  # type: ignore[return-value]
    if p.strike_rally is not None:
        return p.strike_rally
    return p.x, p.y


def update_craft_positions(crafts: List[Any], dt: float) -> None:
    base_r = 64.0
    for c in crafts:
        if c.dead:
            continue
        if c.parent.dead:
            c.dead = True
            continue
        c.orbit_phase += dt * 0.48 + c.slot_index * 0.025
        r = base_r + (c.slot_index % 4) * 10
        ox = math.cos(c.orbit_phase) * r
        oy = math.sin(c.orbit_phase) * r * 0.75
        ax, ay = rally_xy_for_craft(c)
        tx = ax + ox
        ty = ay + oy
        c.x, c.y = move_toward_xy(c.x, c.y, tx, ty, c.speed * dt)
        c.heading = math.atan2(ty - c.y, tx - c.x) if dist_xy(c.x, c.y, tx, ty) > 2 else c.heading
        tz = c.parent.z + math.sin(c.orbit_phase * 1.25) * 11.0
        c.z += (tz - c.z) * min(1.0, dt * 2.4)
        c.z = max(6.0, min(78.0, c.z))


def enemy_ai(eg: Any, players: List[Any], dt: float) -> None:
    alive = [p for p in players if not p.dead]
    if not alive:
        return
    target = min(alive, key=lambda p: dist_xy(eg.x, eg.y, p.x, p.y))
    eg.x, eg.y = move_toward_xy(eg.x, eg.y, target.x, target.y, eg.speed * dt * 0.70)


def clamp_xy_world(x: float, y: float, margin: float = WORLD_EDGE_MARGIN) -> Tuple[float, float]:
    return (
        max(margin, min(WORLD_W - margin, x)),
        max(margin, min(WORLD_H - margin, y)),
    )


def resolve_xy_from_asteroids(
    x: float, y: float, ship_r: float, obstacles: List[Any]
) -> Tuple[float, float]:
    if not obstacles:
        return x, y
    px, py = x, y
    for _ in range(10):
        adjusted = False
        for o in obstacles:
            dx = px - o.x
            dy = py - o.y
            d = math.hypot(dx, dy)
            need = o.r + ship_r + 1.5
            if d < 1e-5:
                px += need
                adjusted = True
                break
            if d < need:
                s = need / d
                px = o.x + dx * s
                py = o.y + dy * s
                adjusted = True
        if not adjusted:
            break
    return px, py


def resolve_all_units_against_asteroids(
    groups: List[Any], crafts: List[Any], obstacles: List[Any]
) -> None:
    if not obstacles:
        return
    for g in groups:
        if g.dead:
            continue
        rad = SHIP_BLOCK_RADIUS_CAPITAL if g.render_capital else SHIP_BLOCK_RADIUS_CRAFT
        g.x, g.y = resolve_xy_from_asteroids(g.x, g.y, rad, obstacles)
        g.x, g.y = clamp_xy_world(g.x, g.y)
    for c in crafts:
        if c.dead:
            continue
        c.x, c.y = resolve_xy_from_asteroids(c.x, c.y, SHIP_BLOCK_RADIUS_CRAFT, obstacles)
        c.x, c.y = clamp_xy_world(c.x, c.y)


# --- Line-of-sight vs asteroids & JSON weapon lookup (headless) ---


def dist_point_segment_sq(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    abx, aby = bx - ax, by - ay
    t = ((px - ax) * abx + (py - ay) * aby) / (abx * abx + aby * aby + 1e-12)
    t = max(0.0, min(1.0, t))
    qx, qy = ax + abx * t, ay + aby * t
    dx, dy = px - qx, py - qy
    return dx * dx + dy * dy


def segment_blocked_by_asteroids(
    ax: float, ay: float, bx: float, by: float, obstacles: List[Any], inflate: float = 0.0
) -> bool:
    for o in obstacles:
        rr = o.r + inflate
        if dist_point_segment_sq(o.x, o.y, ax, ay, bx, by) < rr * rr:
            return True
    return False


def clear_shot_xy(
    x0: float, y0: float, x1: float, y1: float, obstacles: List[Any], delivery: str
) -> bool:
    if not obstacles:
        return True
    if delivery == "missile":
        inflate = 22.0
    elif delivery == "pd_slug":
        inflate = 10.0
    else:
        inflate = 12.0
    return not segment_blocked_by_asteroids(x0, y0, x1, y1, obstacles, inflate=inflate)


def projectile_by_name(data: dict, name: str) -> dict:
    for p in data["projectile_types"]:
        if p["name"] == name:
            return p
    raise KeyError(name)


def weapon_range(data: dict, weapon: dict) -> float:
    proj = projectile_by_name(data, weapon["projectile"])
    if proj["delivery"] == "hitscan":
        return float(proj["range"])
    if proj["delivery"] == "ballistic":
        return float(proj["range"]) * BALLISTIC_ACQUISITION_MULT
    if proj["delivery"] == "missile" and "range" in proj:
        return float(proj["range"])
    return float(proj["speed"]) * float(proj["lifetime"]) * 0.85
