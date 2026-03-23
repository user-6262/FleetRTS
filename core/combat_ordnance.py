"""
Authoritative ordnance tick: targeting, PD overload, firing, ballistics, missiles, light VFX state.

Dataclasses (Group, Missile, VFXSpark, …) remain in demo_game; this module lazy-imports demo_game only
inside call paths so import order stays: demo_game → combat_sim → combat_ordnance (no cycle).
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, List, Optional, Set, Tuple

try:
    from combat_constants import (
        BALLISTIC_DESPAWN_PAD,
        BALLISTIC_SPEED_MULT,
        ENGAGEMENT_RETURN_FIRE_SEC,
        FIGHTER_MISSILE_RETARGET_R,
        MAX_BALLISTICS,
        MISSILE_ACCEL_TIME,
        MISSILE_CRUISE_NOMINAL_MULT,
        MISSILE_CRUISE_SHIP_MULT,
        MISSILE_LAUNCH_MAX_START_FRAC,
        MISSILE_LAUNCH_SPEED_FLOOR_FRAC,
        MISSILE_PD_INTERCEPT_HP_DEFAULT,
        MISSILE_SPEED_MULT,
        MISSILE_TURN_MULT,
        PD_OVERLOAD_GRACE_SEC,
        PD_OVERLOAD_LEVEL_THRESHOLD,
        PD_OVERLOAD_MIN_ROF_MULT,
        PD_OVERLOAD_RAMP_SEC,
        PD_OVERLOAD_RECOVERY_RATE,
        PD_STRESS_WINDOW_SEC,
        SPARK_SPEED_SCALE,
        WORLD_H,
        WORLD_W,
        Z_HIT_BAND,
    )
    from combat_math import dist_xy
except ImportError:
    from core.combat_constants import (
        BALLISTIC_DESPAWN_PAD,
        BALLISTIC_SPEED_MULT,
        ENGAGEMENT_RETURN_FIRE_SEC,
        FIGHTER_MISSILE_RETARGET_R,
        MAX_BALLISTICS,
        MISSILE_ACCEL_TIME,
        MISSILE_CRUISE_NOMINAL_MULT,
        MISSILE_CRUISE_SHIP_MULT,
        MISSILE_LAUNCH_MAX_START_FRAC,
        MISSILE_LAUNCH_SPEED_FLOOR_FRAC,
        MISSILE_PD_INTERCEPT_HP_DEFAULT,
        MISSILE_SPEED_MULT,
        MISSILE_TURN_MULT,
        PD_OVERLOAD_GRACE_SEC,
        PD_OVERLOAD_LEVEL_THRESHOLD,
        PD_OVERLOAD_MIN_ROF_MULT,
        PD_OVERLOAD_RAMP_SEC,
        PD_OVERLOAD_RECOVERY_RATE,
        PD_STRESS_WINDOW_SEC,
        SPARK_SPEED_SCALE,
        WORLD_H,
        WORLD_W,
        Z_HIT_BAND,
    )
    from core.combat_math import dist_xy

try:
    import combat_engine as ce
except ImportError:
    import core.combat_engine as ce


def _dg():
    import demo_game as dg

    return dg


def control_group_slots_for_capital_label(
    control_groups: List[Optional[List[str]]], capital_label: str
) -> List[int]:
    return [i for i, labs in enumerate(control_groups) if labs and capital_label in labs]


def is_valid_attack_focus_for_side(
    attacker_side: str,
    pref: Optional[Any],
    *,
    attacker_owner: Optional[str] = None,
    mp_pvp: bool = False,
) -> bool:
    if pref is None or getattr(pref, "dead", True):
        return False
    dg = _dg()
    if isinstance(pref, dg.GroundObjective):
        return True
    ps = getattr(pref, "side", None)
    if ps is None:
        return False
    if ps != attacker_side:
        return True
    if mp_pvp and attacker_side == "player" and attacker_owner:
        towner = getattr(pref, "owner_id", None)
        if towner and towner != attacker_owner:
            return True
    return False


def prefer_attack_target_in_weapon_range(
    pref: Optional[Any],
    x: float,
    y: float,
    origin_z: float,
    r: float,
    attacker_side: str,
    *,
    attacker_owner: Optional[str] = None,
    mp_pvp: bool = False,
) -> bool:
    if not is_valid_attack_focus_for_side(
        attacker_side, pref, attacker_owner=attacker_owner, mp_pvp=mp_pvp
    ):
        return False
    dg = _dg()
    if isinstance(pref, dg.GroundObjective):
        return dist_xy(x, y, pref.x, pref.y) <= r + pref.radius * 0.28
    if dist_xy(x, y, pref.x, pref.y) > r:
        return False
    pz = getattr(pref, "z", 35.0)
    return abs(pz - origin_z) <= Z_HIT_BAND + 30.0


def prune_attack_targets(groups: List[Any], mission: Optional[Any] = None) -> None:
    pvp = bool(getattr(mission, "mp_pvp", False)) if mission is not None else False
    for g in groups:
        if g.side != "player":
            continue
        if not is_valid_attack_focus_for_side(
            "player",
            g.attack_target,
            attacker_owner=getattr(g, "owner_id", None),
            mp_pvp=pvp,
        ):
            g.attack_target = None


def apply_damage(
    target: Any,
    dmg: float,
    supplies_holder: List[float],
    target_is_player: bool,
    player_damage_hook: Optional[Callable[[Any], None]] = None,
) -> None:
    if dmg <= 0:
        return
    target.hp -= dmg
    if target_is_player:
        supplies_holder[0] -= dmg * 0.06
        if player_damage_hook is not None:
            player_damage_hook(target)


def notify_player_unit_damaged_for_engagement(
    target: Any,
    control_groups: List[Optional[List[str]]],
    cg_weapons_free: List[bool],
) -> None:
    """Any player hull hit: return-fire window; shared control group goes weapons-free."""
    dg = _dg()
    if isinstance(target, dg.Group):
        if target.side != "player":
            return
        target.engagement_timer = max(target.engagement_timer, ENGAGEMENT_RETURN_FIRE_SEC)
        for si in control_group_slots_for_capital_label(control_groups, target.label):
            cg_weapons_free[si] = True
    elif isinstance(target, dg.Craft):
        if target.side != "player" or target.parent.dead:
            return
        target.engagement_timer = max(target.engagement_timer, ENGAGEMENT_RETURN_FIRE_SEC)
        target.parent.engagement_timer = max(target.parent.engagement_timer, ENGAGEMENT_RETURN_FIRE_SEC)
        for si in control_group_slots_for_capital_label(control_groups, target.parent.label):
            cg_weapons_free[si] = True


def iter_hostiles(
    groups: List[Any],
    crafts: List[Any],
    side: str,
    *,
    viewer_owner: Optional[str] = None,
    mp_pvp: bool = False,
):
    for g in groups:
        if g.dead:
            continue
        if g.side != side:
            yield g
        elif mp_pvp and side == "player" and viewer_owner and getattr(g, "owner_id", None) != viewer_owner:
            yield g
    for c in crafts:
        if c.dead:
            continue
        if c.side != side:
            yield c
        elif mp_pvp and side == "player" and viewer_owner and getattr(c, "owner_id", None) != viewer_owner:
            yield c


def nearest_hostile(
    x: float,
    y: float,
    max_r: float,
    groups: List[Any],
    crafts: List[Any],
    side: str,
    fog: Optional[Any] = None,
    *,
    viewer_owner: Optional[str] = None,
    mp_pvp: bool = False,
) -> Optional[Any]:
    if side == "enemy" and fog is not None and not ce.fog_cell_visible(fog, x, y):
        return None
    best = None
    best_d = max_r + 1
    for t in iter_hostiles(
        groups, crafts, side, viewer_owner=viewer_owner, mp_pvp=mp_pvp
    ):
        if fog is not None and not ce.fog_cell_visible(fog, t.x, t.y):
            continue
        d = dist_xy(x, y, t.x, t.y)
        if d < best_d:
            best_d = d
            best = t
    return best if best_d <= max_r else None


def best_pd_missile_target(
    x: float, y: float, z: float, side: str, max_r: float, missiles: List[Any]
) -> Optional[Any]:
    best: Optional[Any] = None
    best_key = 1e18
    for m in missiles:
        if m.side == side:
            continue
        d = dist_xy(x, y, m.x, m.y)
        if d > max_r or abs(m.z - z) > Z_HIT_BAND + 20.0:
            continue
        dx, dy = x - m.x, y - m.y
        dist = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dist, dy / dist
        closing = -(m.vx * ux + m.vy * uy)
        incoming = max(0.0, closing)
        key = d * 1.0 - incoming * 1.8
        if key < best_key:
            best_key = key
            best = m
    return best


def _craft_is_hostile_to_side(
    c: Any,
    side: str,
    *,
    viewer_owner: Optional[str],
    mp_pvp: bool,
) -> bool:
    if c.side != side:
        return True
    return bool(
        mp_pvp
        and side == "player"
        and viewer_owner
        and getattr(c, "owner_id", None) != viewer_owner
    )


def best_fighter_missile_weapon_target(
    x: float,
    y: float,
    origin_z: float,
    side: str,
    max_r: float,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    prefer_attack_target: Optional[Any],
    fog: Optional[Any] = None,
    *,
    launcher_owner: Optional[str] = None,
    mp_pvp: bool = False,
) -> Optional[Any]:
    pref = prefer_attack_target
    if prefer_attack_target_in_weapon_range(
        pref,
        x,
        y,
        origin_z,
        max_r,
        side,
        attacker_owner=launcher_owner,
        mp_pvp=mp_pvp,
    ):
        dg = _dg()
        if isinstance(pref, dg.Craft) and not pref.dead:
            if _craft_is_hostile_to_side(
                pref, side, viewer_owner=launcher_owner, mp_pvp=mp_pvp
            ):
                if fog is None or ce.fog_cell_visible(fog, pref.x, pref.y):
                    return pref
    for class_tier in (("Fighter", "Interceptor"), ("Bomber",)):
        best_c: Optional[Any] = None
        best_d = max_r + 1.0
        for c in crafts:
            if c.dead or c.class_name not in class_tier:
                continue
            if not _craft_is_hostile_to_side(
                c, side, viewer_owner=launcher_owner, mp_pvp=mp_pvp
            ):
                continue
            if fog is not None and not ce.fog_cell_visible(fog, c.x, c.y):
                continue
            pz = getattr(c, "z", 35.0)
            d = dist_xy(x, y, c.x, c.y)
            if d > max_r or abs(pz - origin_z) > Z_HIT_BAND + 30.0:
                continue
            if d < best_d:
                best_d = d
                best_c = c
        if best_c is not None:
            return best_c
    pm = best_pd_missile_target(x, y, origin_z, side, max_r, missiles)
    if pm is not None:
        return pm
    return nearest_hostile(
        x,
        y,
        max_r,
        groups,
        crafts,
        side,
        fog,
        viewer_owner=launcher_owner,
        mp_pvp=mp_pvp,
    )


def _pd_slug_acquisition_range(data: dict, ship_max_range: float) -> float:
    wr = ce.weapon_range(data, {"projectile": "PD Slug", "fire_rate": 1.0})
    return min(ship_max_range, wr)


def count_missiles_in_pd_envelope(
    x: float, y: float, z: float, side: str, max_r: float, missiles: List[Any]
) -> int:
    n = 0
    for m in missiles:
        if m.side == side:
            continue
        d = dist_xy(x, y, m.x, m.y)
        if d > max_r or abs(m.z - z) > Z_HIT_BAND + 20.0:
            continue
        n += 1
    return n


def pd_intercepts_per_sec(weapons: List[Any], side: str, pd_rof_mult: float) -> float:
    t = 0.0
    for w in weapons:
        if w.projectile_name != "PD Slug":
            continue
        rof = w.fire_rate * (pd_rof_mult if side == "player" else 1.0)
        t += rof
    return t


def compute_pd_stress_ratio(
    data: dict, ent: Any, missiles: List[Any], pd_rof_mult: float
) -> Optional[float]:
    if not any(w.projectile_name == "PD Slug" for w in ent.weapons):
        return None
    max_r = _pd_slug_acquisition_range(data, ent.max_range)
    incoming = count_missiles_in_pd_envelope(ent.x, ent.y, ent.z, ent.side, max_r, missiles)
    ips = pd_intercepts_per_sec(ent.weapons, ent.side, pd_rof_mult)
    capacity = max(0.35, ips * PD_STRESS_WINDOW_SEC)
    return incoming / capacity


def _lerp_rgb(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def pd_stress_color(level: float) -> Tuple[int, int, int]:
    level = max(0.0, min(1.0, level))
    green = (45, 205, 105)
    yellow = (235, 195, 55)
    red = (255, 52, 58)
    if level < 0.5:
        return _lerp_rgb(green, yellow, level * 2.0)
    return _lerp_rgb(yellow, red, (level - 0.5) * 2.0)


def pd_stress_display_level(ratio: float) -> float:
    return max(0.0, min(1.0, (ratio - 0.1) / 1.25))


def update_pd_overheat_streak(
    ent: Any,
    dt: float,
    data: dict,
    missiles: List[Any],
    pd_rof_mult: float,
) -> None:
    if not any(w.projectile_name == "PD Slug" for w in ent.weapons):
        ent.pd_overheat_streak = 0.0
        return
    sr = compute_pd_stress_ratio(data, ent, missiles, pd_rof_mult)
    if sr is None:
        ent.pd_overheat_streak = 0.0
        return
    lv = pd_stress_display_level(sr)
    if lv >= PD_OVERLOAD_LEVEL_THRESHOLD:
        ent.pd_overheat_streak += dt
    else:
        ent.pd_overheat_streak = max(0.0, ent.pd_overheat_streak - dt * PD_OVERLOAD_RECOVERY_RATE)


def pd_overheat_rof_multiplier(streak_sec: float) -> float:
    if streak_sec < PD_OVERLOAD_GRACE_SEC:
        return 1.0
    u = (streak_sec - PD_OVERLOAD_GRACE_SEC) / PD_OVERLOAD_RAMP_SEC
    u = max(0.0, min(1.0, u))
    return 1.0 - u * (1.0 - PD_OVERLOAD_MIN_ROF_MULT)


def player_capital_may_fire_weapons(
    g: Any,
    control_groups: List[Optional[List[str]]],
    cg_weapons_free: List[bool],
    *,
    mp_pvp: bool = False,
) -> bool:
    if g.side != "player" or g.dead:
        return False
    if g.attack_move:
        return True
    if is_valid_attack_focus_for_side(
        "player",
        g.attack_target,
        attacker_owner=getattr(g, "owner_id", None),
        mp_pvp=mp_pvp,
    ):
        return True
    if g.engagement_timer > 0:
        return True
    for si in control_group_slots_for_capital_label(control_groups, g.label):
        if cg_weapons_free[si]:
            return True
    return False


def player_craft_may_fire_weapons(
    c: Any,
    control_groups: List[Optional[List[str]]],
    cg_weapons_free: List[bool],
    *,
    mp_pvp: bool = False,
) -> bool:
    if c.side != "player" or c.dead or c.parent.dead:
        return False
    p = c.parent
    if p.attack_move:
        return True
    if is_valid_attack_focus_for_side(
        "player",
        p.attack_target,
        attacker_owner=getattr(p, "owner_id", None),
        mp_pvp=mp_pvp,
    ):
        return True
    if c.engagement_timer > 0 or p.engagement_timer > 0:
        return True
    for si in control_group_slots_for_capital_label(control_groups, p.label):
        if cg_weapons_free[si]:
            return True
    return False


def spawn_missile_intercept_burst(x: float, y: float, sparks: List[Any]) -> None:
    dg = _dg()
    for _ in range(10):
        ang = random.uniform(0, 2 * math.pi)
        v = random.uniform(80, 220) * SPARK_SPEED_SCALE
        sparks.append(
            dg.VFXSpark(
                x + random.uniform(-4, 4),
                y + random.uniform(-4, 4),
                math.cos(ang) * v,
                math.sin(ang) * v,
                0.11 + random.uniform(0, 0.06),
                0.11 + random.uniform(0, 0.06),
                random.choice([2, 3, 3]),
                (random.randint(200, 255), random.randint(140, 220), random.randint(80, 140)),
            )
        )


def spawn_hitscan_vfx(
    proj_name: str,
    sx: float,
    sy: float,
    tx: float,
    ty: float,
    sparks: List[Any],
    beams: List[Any],
) -> None:
    dg = _dg()
    dx, dy = tx - sx, ty - sy
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    perp_x, perp_y = -uy, ux
    base_ang = math.atan2(uy, ux)
    spd_streak = 760 * SPARK_SPEED_SCALE

    def add_spark(px: float, py: float, vx: float, vy: float, ttl: float, r: int, col: Tuple[int, int, int]) -> None:
        sparks.append(dg.VFXSpark(px, py, vx, vy, ttl, ttl, r, col))

    if proj_name == "Light Rail":
        L = min(dist * 0.36, 165)
        beams.append(dg.VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.08, 0.08, (160, 220, 255), 2))
        for i in range(5):
            t = 0.12 + i * 0.17
            px, py = sx + ux * dist * t, sy + uy * dist * t
            add_spark(
                px + perp_x * random.uniform(-2, 2),
                py + perp_y * random.uniform(-2, 2),
                ux * spd_streak,
                uy * spd_streak,
                0.055,
                2,
                (210, 245, 255),
            )

    elif proj_name == "Heavy Shell":
        L = min(dist * 0.3, 215)
        beams.append(dg.VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.15, 0.15, (255, 145, 65), 5))
        beams.append(
            dg.VFXBeam(sx - ux * 8, sy - uy * 8, sx + ux * (L + 12), sy + uy * (L + 12), 0.11, 0.11, (255, 215, 100), 3)
        )
        for _ in range(5):
            j = random.uniform(-0.22, 0.22)
            ang = base_ang + j
            v = spd_streak * 0.5
            add_spark(
                sx + random.uniform(-9, 9),
                sy + random.uniform(-9, 9),
                math.cos(ang) * v,
                math.sin(ang) * v,
                0.17,
                4,
                (255, 185, 70),
            )

    elif proj_name == "Particle Lance":
        L = min(dist * 0.4, 225)
        beams.append(dg.VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.095, 0.095, (205, 130, 255), 3))
        for i in range(7):
            along = dist * (0.15 + i * 0.11)
            add_spark(
                sx + ux * along + perp_x * random.uniform(-4, 4),
                sy + uy * along + perp_y * random.uniform(-4, 4),
                ux * spd_streak * 0.95,
                uy * spd_streak * 0.95,
                0.07,
                2,
                (190, 110, 255),
            )

    elif proj_name == "Plasma Bolt":
        L = min(dist * 0.34, 255)
        beams.append(dg.VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.12, 0.12, (255, 255, 130), 6))
        beams.append(
            dg.VFXBeam(sx - ux * 5, sy - uy * 5, sx + ux * (L + 18), sy + uy * (L + 18), 0.095, 0.095, (195, 255, 95), 4)
        )
        for _ in range(8):
            j = random.uniform(-0.4, 0.4)
            ang = base_ang + j
            add_spark(
                sx + random.uniform(-4, 4),
                sy + random.uniform(-4, 4),
                math.cos(ang) * spd_streak * 0.85,
                math.sin(ang) * spd_streak * 0.85,
                0.1,
                3,
                (235, 255, 140),
            )

    else:
        L = min(dist * 0.28, 120)
        beams.append(dg.VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.065, 0.065, (190, 200, 210), 2))


def update_vfx_sparks(sparks: List[Any], dt: float) -> None:
    for s in sparks:
        s.x += s.vx * dt
        s.y += s.vy * dt
        s.ttl -= dt
    sparks[:] = [s for s in sparks if s.ttl > 0]


def update_vfx_beams(beams: List[Any], dt: float) -> None:
    for b in beams:
        b.ttl -= dt
    beams[:] = [b for b in beams if b.ttl > 0]


def update_ballistics(
    ballistics: List[Any],
    dt: float,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    supplies: List[float],
    vfx_sparks: List[Any],
    objective: Optional[Any],
    player_damage_hook: Optional[Callable[[Any], None]] = None,
    obstacles: Optional[List[Any]] = None,
) -> None:
    dg = _dg()
    pad = BALLISTIC_DESPAWN_PAD
    alive: List[Any] = []
    missile_hit_r = 16.0
    dead_missile_ids: Set[int] = set()
    rocks = obstacles or []
    for s in ballistics:
        s.age += dt
        s.x += s.vx * dt
        s.y += s.vy * dt
        s.z += s.vz * dt
        s.z = max(0.0, min(92.0, s.z))
        if s.x < -pad or s.x > WORLD_W + pad or s.y < -pad or s.y > WORLD_H + pad:
            continue
        hit = False
        for o in rocks:
            if dist_xy(s.x, s.y, o.x, o.y) < o.r + 5.0 and abs(s.z - 30.0) < Z_HIT_BAND + 24.0:
                hit = True
                spawn_missile_intercept_burst(s.x, s.y, vfx_sparks)
                break
        if hit:
            continue
        for m in missiles:
            mid = id(m)
            if mid in dead_missile_ids or m.side == s.side:
                continue
            if dist_xy(s.x, s.y, m.x, m.y) < missile_hit_r and abs(s.z - m.z) < Z_HIT_BAND + 12.0:
                m.intercept_hp -= s.damage
                if m.intercept_hp <= 0:
                    dead_missile_ids.add(mid)
                    spawn_missile_intercept_burst(m.x, m.y, vfx_sparks)
                hit = True
                break
        if not hit:
            candidates: List[Tuple[Any, float]] = []
            for g in groups:
                if g.dead or g.side == s.side:
                    continue
                hr = 24.0 if g.render_capital else 17.0
                candidates.append((g, hr))
            for c in crafts:
                if c.dead or c.side == s.side:
                    continue
                candidates.append((c, 10.5))
            for ent, hr in candidates:
                ez = getattr(ent, "z", 35.0)
                if dist_xy(s.x, s.y, ent.x, ent.y) < hr and abs(s.z - ez) < Z_HIT_BAND:
                    apply_damage(
                        ent,
                        s.damage,
                        supplies,
                        getattr(ent, "side", "") == "player",
                        player_damage_hook,
                    )
                    hit = True
                    break
        if not hit and objective and not objective.dead:
            oz = objective.z
            if dist_xy(s.x, s.y, objective.x, objective.y) < objective.radius + 14.0 and abs(s.z - oz) < Z_HIT_BAND + 18.0:
                apply_damage(objective, s.damage, supplies, False)
                hit = True
        if not hit:
            alive.append(s)
    ballistics.clear()
    ballistics.extend(alive)
    if dead_missile_ids:
        missiles[:] = [m for m in missiles if id(m) not in dead_missile_ids]


def try_fire_weapons(
    data: dict,
    x: float,
    y: float,
    origin_z: float,
    side: str,
    weapons: List[Any],
    max_range: float,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    supplies: List[float],
    dt: float,
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    ballistics: List[Any],
    pd_rof_mult: float = 1.0,
    objective: Optional[Any] = None,
    pd_perf_mult: float = 1.0,
    launcher_speed: float = 0.0,
    weapons_authorized: bool = True,
    player_damage_hook: Optional[Callable[[Any], None]] = None,
    prefer_attack_target: Optional[Any] = None,
    obstacles: Optional[List[Any]] = None,
    fog: Optional[Any] = None,
    launcher_owner: Optional[str] = None,
    mp_pvp: bool = False,
) -> None:
    dg = _dg()

    def _pref_blocked_by_fog(pref: Optional[Any]) -> bool:
        if fog is None or pref is None or not isinstance(pref, (dg.Group, dg.Craft)):
            return False
        if not ce.fog_cell_visible(fog, pref.x, pref.y):
            if getattr(pref, "side", "") != side:
                return True
            if mp_pvp and side == "player" and launcher_owner:
                if getattr(pref, "owner_id", None) != launcher_owner:
                    return True
        return False

    for rw in weapons:
        rw.cooldown -= dt
    if not weapons_authorized:
        return
    if side == "enemy" and fog is not None and not ce.fog_cell_visible(fog, x, y):
        return
    for rw in weapons:
        if rw.cooldown > 0:
            continue
        proj = ce.projectile_by_name(data, rw.projectile_name)
        wr = ce.weapon_range(data, {"projectile": rw.projectile_name, "fire_rate": rw.fire_rate})
        r = min(max_range, wr)
        pref = prefer_attack_target
        if proj["delivery"] == "ballistic" and rw.projectile_name == "PD Slug":
            tgt = best_pd_missile_target(x, y, origin_z, side, r, missiles)
            if tgt is None:
                if prefer_attack_target_in_weapon_range(
                    pref,
                    x,
                    y,
                    origin_z,
                    r,
                    side,
                    attacker_owner=launcher_owner,
                    mp_pvp=mp_pvp,
                ) and not _pref_blocked_by_fog(pref):
                    tgt = pref
                else:
                    tgt = nearest_hostile(
                        x,
                        y,
                        r,
                        groups,
                        crafts,
                        side,
                        fog,
                        viewer_owner=launcher_owner,
                        mp_pvp=mp_pvp,
                    )
        elif rw.projectile_name == "Fighter Missile":
            tgt = best_fighter_missile_weapon_target(
                x,
                y,
                origin_z,
                side,
                r,
                groups,
                crafts,
                missiles,
                pref,
                fog,
                launcher_owner=launcher_owner,
                mp_pvp=mp_pvp,
            )
        else:
            if prefer_attack_target_in_weapon_range(
                pref,
                x,
                y,
                origin_z,
                r,
                side,
                attacker_owner=launcher_owner,
                mp_pvp=mp_pvp,
            ) and not _pref_blocked_by_fog(pref):
                tgt = pref
            else:
                tgt = nearest_hostile(
                    x,
                    y,
                    r,
                    groups,
                    crafts,
                    side,
                    fog,
                    viewer_owner=launcher_owner,
                    mp_pvp=mp_pvp,
                )
        if side == "player" and objective and not objective.dead:
            use_obj = not prefer_attack_target_in_weapon_range(
                pref,
                x,
                y,
                origin_z,
                r,
                side,
                attacker_owner=launcher_owner,
                mp_pvp=mp_pvp,
            )
            if use_obj:
                d_o = dist_xy(x, y, objective.x, objective.y)
                if d_o <= r:
                    if tgt is None or d_o < dist_xy(x, y, tgt.x, tgt.y):
                        tgt = objective
        if tgt is None:
            continue
        d = dist_xy(x, y, tgt.x, tgt.y)
        if isinstance(tgt, dg.GroundObjective):
            if d > r + tgt.radius * 0.32:
                continue
        elif d > r:
            continue
        obs_list = obstacles or []
        if obs_list:
            if proj["delivery"] == "missile" and not ce.clear_shot_xy(
                x, y, tgt.x, tgt.y, obs_list, "missile"
            ):
                rw.cooldown = 0.15
                continue
            if (
                proj["delivery"] == "ballistic"
                and rw.projectile_name == "PD Slug"
                and not ce.clear_shot_xy(x, y, tgt.x, tgt.y, obs_list, "pd_slug")
            ):
                rw.cooldown = 0.08
                continue
        rof_upgrade = pd_rof_mult if side == "player" else 1.0
        eff_rof = rw.fire_rate * rof_upgrade if rw.projectile_name == "PD Slug" else rw.fire_rate
        if rw.projectile_name == "PD Slug":
            eff_rof *= max(0.08, pd_perf_mult)
        rw.cooldown = 1.0 / max(0.1, eff_rof)
        if proj["delivery"] == "hitscan":
            spawn_hitscan_vfx(rw.projectile_name, x, y, tgt.x, tgt.y, vfx_sparks, vfx_beams)
            apply_damage(
                tgt,
                float(proj["damage"]),
                supplies,
                getattr(tgt, "side", "") == "player",
                player_damage_hook,
            )
        elif proj["delivery"] == "ballistic":
            if len(ballistics) >= MAX_BALLISTICS:
                ballistics.pop(0)
            spd = float(proj["speed"]) * BALLISTIC_SPEED_MULT
            ang = math.atan2(tgt.y - y, tgt.x - x)
            ux, uy = math.cos(ang), math.sin(ang)
            sz = origin_z + random.uniform(-4, 4)
            tz = getattr(tgt, "z", 35.0)
            vz = (tz - sz) * 0.14
            muzzle = 10.0
            ballistics.append(
                dg.BallisticSlug(
                    x=x + ux * muzzle,
                    y=y + uy * muzzle,
                    z=sz,
                    vx=ux * spd,
                    vy=uy * spd,
                    vz=vz,
                    damage=float(proj["damage"]),
                    side=side,
                    proj_name=rw.projectile_name,
                )
            )
            vfx_sparks.append(
                dg.VFXSpark(
                    x + ux * 4,
                    y + uy * 4,
                    ux * 130 * SPARK_SPEED_SCALE,
                    uy * 130 * SPARK_SPEED_SCALE,
                    0.06,
                    0.06,
                    3,
                    (255, 100, 85),
                )
            )
        elif proj["delivery"] == "missile":
            nominal = float(proj["speed"]) * MISSILE_SPEED_MULT * MISSILE_CRUISE_NOMINAL_MULT
            cruise = max(nominal, MISSILE_CRUISE_SHIP_MULT * max(0.0, launcher_speed))
            floor_spd = cruise * MISSILE_LAUNCH_SPEED_FLOOR_FRAC
            raw_launch = min(cruise, max(floor_spd, launcher_speed))
            launch_cap = cruise * MISSILE_LAUNCH_MAX_START_FRAC
            launch_spd = min(raw_launch, launch_cap)
            ang = math.atan2(tgt.y - y, tgt.x - x)
            ux, uy = math.cos(ang), math.sin(ang)
            if side == "player":
                cid = int(getattr(launcher, "color_id", 0))
                base = dg.MP_PLAYER_PALETTE[cid % len(dg.MP_PLAYER_PALETTE)]
                col = tuple(min(255, int(ch * 1.15)) for ch in base)
            else:
                col = (255, 120, 100)
            mz = origin_z + random.uniform(-4, 4)
            intercept_hp = float(proj.get("pd_intercept_hp", MISSILE_PD_INTERCEPT_HP_DEFAULT))
            missiles.append(
                dg.Missile(
                    x=x + ux * 14,
                    y=y + uy * 14,
                    vx=ux * launch_spd,
                    vy=uy * launch_spd,
                    speed=cruise,
                    launch_speed=launch_spd,
                    boost_elapsed=0.0,
                    intercept_hp=intercept_hp,
                    damage=float(proj["damage"]),
                    turn_rate_rad=math.radians(float(proj["turn_rate_deg"])) * MISSILE_TURN_MULT,
                    ttl=float(proj["lifetime"]),
                    side=side,
                    color=col,
                    proj_name=rw.projectile_name,
                    z=mz,
                    target=tgt,
                )
            )


def _missile_seek_target_valid(tgt: Any, side: str, all_missiles: List[Any]) -> bool:
    dg = _dg()
    if tgt is None:
        return False
    if isinstance(tgt, dg.Missile):
        if tgt.side == side or tgt.ttl <= 0:
            return False
        return any(tgt is mm for mm in all_missiles)
    return not getattr(tgt, "dead", False)


def _missile_reacquire_range(data: dict, proj_name: str) -> float:
    return max(140.0, ce.weapon_range(data, {"projectile": proj_name, "fire_rate": 0.35}) * 1.2)


def update_missiles(
    missiles: List[Any],
    dt: float,
    groups: List[Any],
    crafts: List[Any],
    supplies: List[float],
    objective: Optional[Any],
    data: dict,
    player_damage_hook: Optional[Callable[[Any], None]] = None,
    obstacles: Optional[List[Any]] = None,
    vfx_sparks: Optional[List[Any]] = None,
    fog: Optional[Any] = None,
) -> None:
    dg = _dg()
    alive: List[Any] = []
    acquire_r = max(WORLD_W, WORLD_H) * 0.22
    rocks = obstacles or []
    dead_m_ids: Set[int] = set()
    for m in missiles:
        if id(m) in dead_m_ids:
            continue
        m.anim_t += dt
        m.ttl -= dt
        if m.ttl <= 0:
            continue
        m.boost_elapsed += dt
        if m.launch_speed < 0:
            eff_spd = m.speed
        else:
            u = min(1.0, m.boost_elapsed / MISSILE_ACCEL_TIME)
            eff_spd = m.launch_speed + (m.speed - m.launch_speed) * u
        tgt = m.target
        if tgt is None or not _missile_seek_target_valid(tgt, m.side, missiles):
            if m.proj_name == "Fighter Missile":
                m.target = best_fighter_missile_weapon_target(
                    m.x,
                    m.y,
                    m.z,
                    m.side,
                    FIGHTER_MISSILE_RETARGET_R,
                    groups,
                    crafts,
                    missiles,
                    None,
                    fog,
                )
            else:
                cap_r = min(acquire_r, _missile_reacquire_range(data, m.proj_name))
                m.target = nearest_hostile(m.x, m.y, cap_r, groups, crafts, m.side, fog)
            tgt = m.target
        if tgt is not None and id(tgt) not in dead_m_ids:
            desired = math.atan2(tgt.y - m.y, tgt.x - m.x)
            cur = math.atan2(m.vy, m.vx) if math.hypot(m.vy, m.vx) > 0.35 else desired
            diff = (desired - cur + math.pi) % (2 * math.pi) - math.pi
            turn = m.turn_rate_rad * dt
            if diff > turn:
                cur += turn
            elif diff < -turn:
                cur -= turn
            else:
                cur = desired
            m.vx = math.cos(cur) * eff_spd
            m.vy = math.sin(cur) * eff_spd
        m.x += m.vx * dt
        m.y += m.vy * dt
        rock_hit = False
        for o in rocks:
            if dist_xy(m.x, m.y, o.x, o.y) < o.r + 9.0 and abs(m.z - 32.0) < Z_HIT_BAND + 20.0:
                rock_hit = True
                break
        if rock_hit:
            if vfx_sparks is not None:
                spawn_missile_intercept_burst(m.x, m.y, vfx_sparks)
            continue
        hit_r = 12.0
        if tgt is not None and id(tgt) not in dead_m_ids and _missile_seek_target_valid(tgt, m.side, missiles):
            if isinstance(tgt, dg.Missile):
                tz = tgt.z
                if dist_xy(m.x, m.y, tgt.x, tgt.y) < 14.0 and abs(m.z - tz) < Z_HIT_BAND + 12.0:
                    tgt.intercept_hp -= m.damage
                    if vfx_sparks is not None:
                        spawn_missile_intercept_burst(m.x, m.y, vfx_sparks)
                    if tgt.intercept_hp <= 0:
                        dead_m_ids.add(id(tgt))
                    dead_m_ids.add(id(m))
                    continue
            elif not tgt.dead:
                tz = getattr(tgt, "z", 35.0)
                hr = hit_r
                if isinstance(tgt, dg.GroundObjective):
                    hr = tgt.radius * 0.35 + 8.0
                if dist_xy(m.x, m.y, tgt.x, tgt.y) < hr and abs(m.z - tz) < Z_HIT_BAND + 10.0:
                    apply_damage(
                        tgt,
                        m.damage,
                        supplies,
                        getattr(tgt, "side", "") == "player",
                        player_damage_hook,
                    )
                    continue
        alive.append(m)
    missiles.clear()
    missiles.extend(m for m in alive if id(m) not in dead_m_ids)


def rebuild_seeker_lock_ghosts(
    fog: Any,
    missiles: List[Any],
    obstacles: List[Any],
    out: List[Any],
) -> None:
    dg = _dg()
    out.clear()
    seen_tid: Set[int] = set()
    for m in missiles:
        if m.side != "player" or m.ttl <= 0:
            continue
        tgt = m.target
        if tgt is None or getattr(tgt, "dead", False):
            continue
        if isinstance(tgt, dg.GroundObjective):
            pass
        elif isinstance(tgt, (dg.Group, dg.Craft)):
            if getattr(tgt, "side", "") != "enemy":
                continue
        else:
            continue
        if not ce.fog_cell_visible(fog, m.x, m.y):
            continue
        if ce.fog_cell_visible(fog, tgt.x, tgt.y):
            continue
        tid = id(tgt)
        if tid in seen_tid:
            continue
        seen_tid.add(tid)
        rng = random.Random(tid & 0xFFFFFFFF)
        qual = 0.30 + (tid % 89) / 260.0
        if obstacles and ce.segment_blocked_by_asteroids(m.x, m.y, tgt.x, tgt.y, obstacles, inflate=14.0):
            qual = max(0.08, qual * 0.72)
            lab = "Obscured seeker trace"
        else:
            lab = "Seeker contact"
        jitter = (1.0 - min(1.0, qual + 0.15)) * 110.0 + 20.0
        jx = rng.uniform(-jitter, jitter)
        jy = rng.uniform(-jitter, jitter)
        out.append(
            dg.SensorGhost(
                x=tgt.x + jx,
                y=tgt.y + jy,
                ttl=1.0,
                label=lab,
                quality=min(0.92, qual),
            )
        )
