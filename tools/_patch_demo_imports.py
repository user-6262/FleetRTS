"""Patch demo_game: full combat_engine wiring + remove duplicate fog/movement."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "core" / "demo_game.py"
text = p.read_text(encoding="utf-8")

old1 = """from game_audio import GameAudio

# PATCH_TEST

try:
    from combat_constants import (
        FOG_CH,
        FOG_CW,
        REINF_INTERVAL_BASE,
        SALVAGE_PICKUP_R,
        SALVAGE_POD_VALUE,
        SENSOR_RANGE_CAPITAL,
        SENSOR_RANGE_STRIKE,
        WORLD_H,
        WORLD_W,
    )
    from combat_math import dist_xy, round_seed
except ImportError:
    from core.combat_constants import (
        REINF_INTERVAL_BASE,
        SALVAGE_PICKUP_R,
        SALVAGE_POD_VALUE,
        WORLD_H,
        WORLD_W,
    )
    from core.combat_math import dist_xy, round_seed

try:
    from combat_engine import (
        begin_combat_round,
        compute_mission_salvage_reward,
        extract_rect_world,
        finalize_deaths,
        finalize_objective_if_dead,
        mission_allows_extract,
        spawn_enemy_reinforcement,
    )
except ImportError:
    from core.combat_engine import (
        begin_combat_round,
        compute_mission_salvage_reward,
        extract_rect_world,
        finalize_deaths,
        finalize_objective_if_dead,
        mission_allows_extract,
        spawn_enemy_reinforcement,
    )
"""

new1 = """from game_audio import GameAudio

try:
    from combat_constants import (
        FOG_CH,
        FOG_CW,
        REINF_INTERVAL_BASE,
        SALVAGE_PICKUP_R,
        SALVAGE_POD_VALUE,
        SENSOR_RANGE_CAPITAL,
        SENSOR_RANGE_STRIKE,
        WORLD_H,
        WORLD_W,
    )
    from combat_math import dist_xy, round_seed
except ImportError:
    from core.combat_constants import (
        FOG_CH,
        FOG_CW,
        REINF_INTERVAL_BASE,
        SALVAGE_PICKUP_R,
        SALVAGE_POD_VALUE,
        SENSOR_RANGE_CAPITAL,
        SENSOR_RANGE_STRIKE,
        WORLD_H,
        WORLD_W,
    )
    from core.combat_math import dist_xy, round_seed

try:
    from combat_engine import (
        begin_combat_round,
        compute_mission_salvage_reward,
        cull_sensor_ghosts_if_ping_anchors_lost,
        effective_capital_move_speed,
        enemy_ai,
        extract_rect_world,
        finalize_deaths,
        finalize_objective_if_dead,
        fog_cell_explored,
        fog_cell_index,
        fog_cell_visible,
        fog_stamp_disk,
        mission_allows_extract,
        move_group,
        move_toward_xy,
        rally_xy_for_craft,
        separate_player_capitals,
        spawn_enemy_reinforcement,
        update_craft_positions,
        update_fog_of_war,
    )
except ImportError:
    from core.combat_engine import (
        begin_combat_round,
        compute_mission_salvage_reward,
        cull_sensor_ghosts_if_ping_anchors_lost,
        effective_capital_move_speed,
        enemy_ai,
        extract_rect_world,
        finalize_deaths,
        finalize_objective_if_dead,
        fog_cell_explored,
        fog_cell_index,
        fog_cell_visible,
        fog_stamp_disk,
        mission_allows_extract,
        move_group,
        move_toward_xy,
        rally_xy_for_craft,
        separate_player_capitals,
        spawn_enemy_reinforcement,
        update_craft_positions,
        update_fog_of_war,
    )

_effective_capital_move_speed = effective_capital_move_speed
"""

if old1 not in text:
    raise SystemExit("import block not found")
text = text.replace(old1, new1, 1)

# ... rest same as before (old2 through old8)
old2 = """# Fog-of-war grid (world XY; independent of visual Z lift).
FOG_CW = 48
FOG_CH = 29
SENSOR_RANGE_CAPITAL = 400.0
SENSOR_RANGE_STRIKE = 260.0
ACTIVE_PING_RADIUS = 780.0
"""
new2 = """# Fog grid / sensor radii: FOG_CW, FOG_CH, SENSOR_RANGE_* from combat_constants (imported above).
ACTIVE_PING_RADIUS = 780.0
"""
if old2 not in text:
    raise SystemExit("fog const block not found")
text = text.replace(old2, new2, 1)

old3 = """TTS_ATTACK_TARGET_LINES = ("Focus fire.",)
CAPITAL_SEPARATION = 52.0
SEPARATION_PUSH = 72.0
DRAG_CLICK_MAX_PX = 6
"""
new3 = """TTS_ATTACK_TARGET_LINES = ("Focus fire.",)
DRAG_CLICK_MAX_PX = 6
"""
if old3 not in text:
    raise SystemExit("capital sep block not found")
text = text.replace(old3, new3, 1)

old4 = """def parse_obstacles(data: dict) -> List[Asteroid]:
    bf = data.get("battlefield") or {}
    raw = bf.get("asteroids") or []
    out: List[Asteroid] = []
    for a in raw:
        out.append(Asteroid(float(a["x"]), float(a["y"]), float(a["r"])))
    return out


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


def update_fog_of_war(
    fog: FogState,
    groups: List[Group],
    crafts: List[Craft],
    pings: List[ActivePing],
) -> None:
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


def fog_cell_visible(fog: FogState, wx: float, wy: float) -> bool:
    return fog.visible[fog_cell_index(wx, wy)]


def fog_cell_explored(fog: FogState, wx: float, wy: float) -> bool:
    return fog.explored[fog_cell_index(wx, wy)]


def dist_point_segment_sq(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
"""

new4 = """def parse_obstacles(data: dict) -> List[Asteroid]:
    bf = data.get("battlefield") or {}
    raw = bf.get("asteroids") or []
    out: List[Asteroid] = []
    for a in raw:
        out.append(Asteroid(float(a["x"]), float(a["y"]), float(a["r"])))
    return out


def dist_point_segment_sq(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
"""
if old4 not in text:
    raise SystemExit("fog funcs block not found")
text = text.replace(old4, new4, 1)

old5 = """def clear_carrier_air_orders(g: Group) -> None:
    g.strike_rally = None
    for i in range(len(g.strike_rally_wings)):
        g.strike_rally_wings[i] = None


def rally_xy_for_craft(c: Craft) -> Tuple[float, float]:
    p = c.parent
    wings = p.strike_rally_wings
    if c.squadron_index < len(wings) and wings[c.squadron_index] is not None:
        return wings[c.squadron_index]  # type: ignore[return-value]
    if p.strike_rally is not None:
        return p.strike_rally
    return p.x, p.y


def carrier_squadron_indices_for_class(data: dict, carrier: Group, class_name: str) -> List[int]:
"""

new5 = """def clear_carrier_air_orders(g: Group) -> None:
    g.strike_rally = None
    for i in range(len(g.strike_rally_wings)):
        g.strike_rally_wings[i] = None


def carrier_squadron_indices_for_class(data: dict, carrier: Group, class_name: str) -> List[int]:
"""
if old5 not in text:
    raise SystemExit("rally block not found")
text = text.replace(old5, new5, 1)

old6 = """def dist_g(a: Group, b: Group) -> float:
    return dist_xy(a.x, a.y, b.x, b.y)


def move_toward_xy(x: float, y: float, tx: float, ty: float, step: float) -> Tuple[float, float]:
    dx, dy = tx - x, ty - y
    d = math.hypot(dx, dy)
    if d < 3:
        return tx, ty
    if step >= d:
        return tx, ty
    return x + dx / d * step, y + dy / d * step


def _effective_capital_move_speed(g: Group, player_capitals: List[Group]) -> float:
    \"\"\"Capitals issued a move in the same batch share the slowest hull speed until waypoints diverge.\"\"\"
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


def move_group(g: Group, dt: float, player_capitals: List[Group]) -> None:
    if g.waypoint:
        wx, wy = g.waypoint
        step = _effective_capital_move_speed(g, player_capitals) * dt
        g.x, g.y = move_toward_xy(g.x, g.y, wx, wy, step)
        if dist_xy(g.x, g.y, wx, wy) < 6:
            g.clear_waypoint()
            g.attack_move = False


def normalize_rect(x0: int, y0: int, x1: int, y1: int) -> pygame.Rect:
"""

new6 = """def normalize_rect(x0: int, y0: int, x1: int, y1: int) -> pygame.Rect:
"""
if old6 not in text:
    raise SystemExit("move_group block not found")
text = text.replace(old6, new6, 1)

old7 = """def focus_camera_for_selection(cam_x: float, cam_y: float, targets: List[Group]) -> Tuple[float, float]:
    if not targets:
        return cam_x, cam_y
    cx = sum(g.x for g in targets) / len(targets)
    cy = sum(g.y for g in targets) / len(targets)
    return clamp_camera(cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)


def separate_player_capitals(groups: List[Group], dt: float, mp_pvp: bool = False) -> None:
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


def update_craft_positions(crafts: List[Craft], dt: float) -> None:
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


def draw_nato_ship(
"""

new7 = """def focus_camera_for_selection(cam_x: float, cam_y: float, targets: List[Group]) -> Tuple[float, float]:
    if not targets:
        return cam_x, cam_y
    cx = sum(g.x for g in targets) / len(targets)
    cy = sum(g.y for g in targets) / len(targets)
    return clamp_camera(cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)


def draw_nato_ship(
"""
if old7 not in text:
    raise SystemExit("separate/craft block not found")
text = text.replace(old7, new7, 1)

old8 = """def enemy_ai(eg: Group, players: List[Group], dt: float) -> None:
    alive = [p for p in players if not p.dead]
    if not alive:
        return
    target = min(alive, key=lambda p: dist_g(eg, p))
    eg.x, eg.y = move_toward_xy(eg.x, eg.y, target.x, target.y, eg.speed * dt * 0.70)


def pause_main_menu_button_rect() -> pygame.Rect:
"""

new8 = """def pause_main_menu_button_rect() -> pygame.Rect:
"""
if old8 not in text:
    raise SystemExit("enemy_ai block not found")
text = text.replace(old8, new8, 1)

p.write_text(text, encoding="utf-8")
print("demo_game patched OK")
