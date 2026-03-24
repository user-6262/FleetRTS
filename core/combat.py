"""
FleetRTS unified combat module.

Entities, constants, simulation, orders, multiplayer, fleet management, and
debrief economy.  No pygame dependency -- safe to import from headless servers.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

try:
    from bundle_paths import game_data_json
except ImportError:
    from core.bundle_paths import game_data_json

DATA_PATH = game_data_json()


# ════════════════════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════════════════════

# World size (authoritative geometry for sim + camera clamp). Window / UI pixels stay in demo_game.
WORLD_W = 5600
WORLD_H = 3400

# Fog-of-war grid (world XY).
FOG_CW = 48
FOG_CH = 29
SENSOR_RANGE_CAPITAL = 400.0
SENSOR_RANGE_STRIKE = 260.0

# Player capital soft collision while moving.
CAPITAL_SEPARATION = 52.0
SEPARATION_PUSH = 72.0

REINF_INTERVAL_BASE = 36.0
SALVAGE_PICKUP_R = 105.0
SALVAGE_POD_VALUE = 16

# Impassable asteroid XY resolution (capital vs craft hit radii).
SHIP_BLOCK_RADIUS_CAPITAL = 26.0
SHIP_BLOCK_RADIUS_CRAFT = 11.0
WORLD_EDGE_MARGIN = 22.0

# Altitude band for hit detection (ships / ordnance).
Z_HIT_BAND = 24.0

# PD HUD stress + overload (RoF taper when saturated).
PD_STRESS_WINDOW_SEC = 0.5
PD_OVERLOAD_LEVEL_THRESHOLD = 0.78
PD_OVERLOAD_GRACE_SEC = 1.0
PD_OVERLOAD_RAMP_SEC = 2.75
PD_OVERLOAD_MIN_ROF_MULT = 0.38
PD_OVERLOAD_RECOVERY_RATE = 0.72

# Ballistics / missiles / VFX (authoritative tuning for sim + client).
BALLISTIC_ACQUISITION_MULT = 4.85
BALLISTIC_SPEED_MULT = 0.52
MAX_BALLISTICS = 1400
BALLISTIC_DESPAWN_PAD = 280
MISSILE_SPEED_MULT = 0.38
MISSILE_ACCEL_TIME = 0.88
MISSILE_CRUISE_SHIP_MULT = 2.85
MISSILE_CRUISE_NOMINAL_MULT = 1.18
MISSILE_LAUNCH_MAX_START_FRAC = 0.68
MISSILE_LAUNCH_SPEED_FLOOR_FRAC = 0.1
MISSILE_PD_INTERCEPT_HP_DEFAULT = 1.05
MISSILE_TURN_MULT = 0.82
SPARK_SPEED_SCALE = 0.48
FIGHTER_MISSILE_RETARGET_R = 128.0

# Return-fire window after hull damage (UI + sim).
ENGAGEMENT_RETURN_FIRE_SEC = 4.0

# Balance / economy constants (moved from demo_game.py)
COST_REPAIR = 28
COST_RESUPPLY = 34
COST_CIWS = 44
COST_BULKHEAD = 52
MAX_CIWS_STACKS = 5
MAX_BULKHEAD_STACKS = 5
CIWS_ROF_BONUS = 0.085
BULKHEAD_HP_FRAC = 0.06
MAX_PLAYER_CAPITALS = 14
DEPLOYMENT_STARTING_SCRAP = 420
DEPLOYMENT_MIN_CAPITALS = 1
COST_FRIGATE = 62
COST_DESTROYER = 92
COST_CRUISER = 138
COST_BATTLESHIP = 175
COST_CARRIER = 255
COST_LIGHT_RESUPPLY = 22
LIGHT_RESUPPLY_AMT = 14.0

STORE_SHIP_IDS = ("ship_frigate", "ship_destroyer", "ship_cruiser", "ship_battleship", "ship_carrier")
STORE_SHIP_CLASSES = ("Frigate", "Destroyer", "Cruiser", "Battleship", "Carrier")
STORE_SHIP_COSTS = (COST_FRIGATE, COST_DESTROYER, COST_CRUISER, COST_BATTLESHIP, COST_CARRIER)
STORE_UPGRADE_IDS = ("upg_repair", "upg_resupply", "upg_ciws", "upg_bulkhead", "upg_stores")
SHIP_CLASS_BY_STORE_ID = dict(zip(STORE_SHIP_IDS, STORE_SHIP_CLASSES))
SHIP_COST_BY_STORE_ID = dict(zip(STORE_SHIP_IDS, STORE_SHIP_COSTS))

TTS_ENEMY_KILL_GAP_MS = 2600
TTS_PLAYER_CAP_LOSS_GAP_MS = 4500

MP_PLAYER_PALETTE: List[Tuple[int, int, int]] = [
    (90, 170, 255),   # blue
    (120, 210, 150),  # green
    (255, 170, 95),   # orange
    (220, 130, 255),  # purple
    (255, 225, 110),  # yellow
    (255, 120, 120),  # red
]
MP_COOP_BLUE_PALETTE: List[Tuple[int, int, int]] = [
    (90, 170, 255),
    (110, 185, 255),
    (130, 200, 255),
    (80, 160, 230),
    (105, 175, 235),
    (125, 195, 245),
]


# ════════════════════════════════════════════════════════════════════════════
#  Math helpers
# ════════════════════════════════════════════════════════════════════════════

def dist_xy(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def round_seed(round_idx: int) -> int:
    return round_idx * 10007 + 1337


# ════════════════════════════════════════════════════════════════════════════
#  Lightweight Rect (no pygame)
# ════════════════════════════════════════════════════════════════════════════

class _Rect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def collidepoint(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


# ════════════════════════════════════════════════════════════════════════════
#  Entity types
# ════════════════════════════════════════════════════════════════════════════

OBJECTIVE_RADIUS = 56.0
SPEED_SCALE = 0.92
CONTROL_GROUP_SLOTS = 9


@dataclass
class Asteroid:
    x: float
    y: float
    r: float


@dataclass
class ActivePing:
    x: float
    y: float
    ttl: float
    radius: float


@dataclass
class SensorGhost:
    x: float
    y: float
    ttl: float
    label: str
    quality: float  # 0 = vague, 1 = sharper (UI / jitter)


@dataclass
class FogState:
    explored: List[bool] = field(default_factory=list)
    visible: List[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = FOG_CW * FOG_CH
        if len(self.explored) != n:
            self.explored = [False] * n
        if len(self.visible) != n:
            self.visible = [False] * n


@dataclass
class RuntimeWeapon:
    name: str
    projectile_name: str
    fire_rate: float
    cooldown: float = 0.0


@dataclass
class Group:
    side: str
    owner_id: str
    color_id: int
    label: str
    class_name: str
    x: float
    y: float
    max_hp: float
    hp: float
    speed: float
    max_range: float
    weapons: List[RuntimeWeapon]
    render_capital: bool
    z: float = 35.0
    waypoint: Optional[Tuple[float, float]] = None
    move_pace_key: Optional[int] = None
    strike_rally: Optional[Tuple[float, float]] = None
    strike_rally_wings: List[Optional[Tuple[float, float]]] = field(default_factory=list)
    attack_move: bool = False
    selected: bool = False
    pd_overheat_streak: float = 0.0
    engagement_timer: float = 0.0
    attack_target: Optional[Any] = None
    dead: bool = False
    hangar_loadout_choice: int = 0

    def set_waypoint(self, wx: float, wy: float) -> None:
        self.waypoint = (wx, wy)

    def clear_waypoint(self) -> None:
        self.waypoint = None
        self.move_pace_key = None

    def hold_position(self) -> None:
        self.waypoint = None
        self.move_pace_key = None
        self.attack_move = False
        self.attack_target = None


@dataclass
class Craft:
    side: str
    owner_id: str
    color_id: int
    label: str
    class_name: str
    parent: Group
    slot_index: int
    squadron_index: int
    x: float
    y: float
    max_hp: float
    hp: float
    speed: float
    max_range: float
    weapons: List[RuntimeWeapon]
    z: float = 38.0
    orbit_phase: float = 0.0
    heading: float = 0.0
    pd_overheat_streak: float = 0.0
    engagement_timer: float = 0.0
    selected: bool = False
    dead: bool = False


@dataclass
class Missile:
    x: float
    y: float
    vx: float
    vy: float
    speed: float
    damage: float
    turn_rate_rad: float
    ttl: float
    side: str
    color: Tuple[int, int, int]
    proj_name: str
    z: float = 35.0
    target: Optional[Any] = None
    anim_t: float = 0.0
    launch_speed: float = -1.0
    boost_elapsed: float = 0.0
    intercept_hp: float = 1.0


@dataclass
class BallisticSlug:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    damage: float
    side: str
    proj_name: str
    age: float = 0.0


@dataclass
class VFXSpark:
    x: float
    y: float
    vx: float
    vy: float
    ttl: float
    max_ttl: float
    radius: int
    color: Tuple[int, int, int]


@dataclass
class VFXBeam:
    x0: float
    y0: float
    x1: float
    y1: float
    ttl: float
    max_ttl: float
    color: Tuple[int, int, int]
    width: int


@dataclass
class GroundObjective:
    x: float
    y: float
    z: float = 24.0
    hp: float = 800.0
    max_hp: float = 800.0
    radius: float = OBJECTIVE_RADIUS
    dead: bool = False


@dataclass
class SalvagePod:
    x: float
    y: float
    value: int = SALVAGE_POD_VALUE
    collected: bool = False


@dataclass
class MissionState:
    kind: str
    objective: Optional[GroundObjective]
    pods: List[SalvagePod]
    reinf_remaining: int
    reinf_timer: float
    pods_collected: int
    pods_required: int
    enemy_label_serial: int
    initial_enemies_spawned: int
    obstacles: List[Asteroid] = field(default_factory=list)
    mp_pvp: bool = False
    pvp_scrap: Dict[str, int] = field(default_factory=dict)
    pvp_territory: Dict[str, str] = field(default_factory=dict)
    pvp_battlegroups: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════════════
#  Ship data lookup
# ════════════════════════════════════════════════════════════════════════════

def ship_class_by_name(data: dict, name: str) -> dict:
    for sc in data["ship_classes"]:
        if sc["name"] == name:
            return sc
    raise KeyError(name)


def weapon_loadout_slot_choices(data: dict, slot: dict) -> List[dict]:
    cset = slot.get("choice_set")
    if cset:
        sets = data.get("weapon_loadout_choice_sets") or {}
        row = sets.get(str(cset))
        if row is None:
            raise KeyError(f"weapon_loadout_choice_sets[{cset!r}] missing")
        return [dict(x) for x in row]
    return [dict(x) for x in (slot.get("choices") or [])]


def weapon_loadout_options_expanded(data: dict, sc: dict) -> List[dict]:
    out: List[dict] = []
    for slot in sc.get("weapon_loadout_options") or []:
        e = dict(slot)
        e["choices"] = weapon_loadout_slot_choices(data, slot)
        out.append(e)
    return out


def resolve_weapon_entry(data: dict, entry: dict) -> Tuple[str, str, float]:
    if "module_id" in entry:
        mid = str(entry["module_id"])
        mods = data.get("weapon_modules") or {}
        if mid not in mods:
            raise KeyError(f"weapon_modules[{mid!r}] missing")
        m = mods[mid]
        return str(m["name"]), str(m["projectile"]), float(m["fire_rate"])
    return str(entry["name"]), str(entry["projectile"]), float(entry["fire_rate"])


# ════════════════════════════════════════════════════════════════════════════
#  Weapon / projectile lookup
# ════════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════════
#  Entity factories
# ════════════════════════════════════════════════════════════════════════════

def class_max_weapon_range(data: dict, sc: dict) -> float:
    weapons = sc.get("weapons") or []
    if not weapons:
        return 120.0
    return max(
        weapon_range(data, {"projectile": pn, "fire_rate": fr})
        for _, pn, fr in (resolve_weapon_entry(data, w) for w in weapons)
    )


def build_runtime_weapons(data: dict, sc: dict) -> List[RuntimeWeapon]:
    out: List[RuntimeWeapon] = []
    for w in sc.get("weapons") or []:
        name, pn, fr = resolve_weapon_entry(data, w)
        out.append(RuntimeWeapon(name=name, projectile_name=pn, fire_rate=float(fr)))
    return out


def make_group(
    data: dict,
    side: str,
    label: str,
    class_name: str,
    x: float,
    y: float,
    *,
    owner_id: str = "player",
    color_id: int = 0,
) -> Group:
    sc = ship_class_by_name(data, class_name)
    max_hp = float(sc.get("hull_hp", sc["armor"] * 10 + sc["shields"]))
    spd = (16.0 + (float(sc["speed"]) / 100.0) * 76.0) * SPEED_SCALE
    mr = class_max_weapon_range(data, sc)
    capital = sc.get("render", "capital") == "capital"
    rng = random.Random(hash((side, label, class_name)) % (2**32))
    z = rng.uniform(16.0, 58.0)
    return Group(
        side=side,
        owner_id=str(owner_id or "player"),
        color_id=int(max(0, min(int(color_id), 5))),
        label=label,
        class_name=class_name,
        x=x,
        y=y,
        max_hp=max_hp,
        hp=max_hp,
        speed=spd,
        max_range=mr,
        weapons=build_runtime_weapons(data, sc),
        render_capital=capital,
        z=z,
    )


# ════════════════════════════════════════════════════════════════════════════
#  Game data loading
# ════════════════════════════════════════════════════════════════════════════

def load_game_data() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def parse_obstacles(data: dict) -> List[Asteroid]:
    bf = data.get("battlefield") or {}
    raw = bf.get("asteroids") or []
    out: List[Asteroid] = []
    for a in raw:
        out.append(Asteroid(float(a["x"]), float(a["y"]), float(a["r"])))
    return out


def capital_ship_class_names(data: dict) -> List[str]:
    out: List[str] = []
    for sc in data.get("ship_classes") or []:
        if sc.get("render") == "capital" and sc.get("name"):
            out.append(str(sc["name"]))
    return sorted(out)


# ════════════════════════════════════════════════════════════════════════════
#  Engine: extract zone, salvage, engagement, deaths
# ════════════════════════════════════════════════════════════════════════════

def extract_rect_world() -> _Rect:
    return _Rect(WORLD_W // 2 - 320, 64, 640, 112)


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
    groups[:] = [g for g in groups if g.side != "enemy"]
    serial = 0
    ep = max(0, min(3, int(enemy_pressure)))
    n_en_boost = ep
    reinf_boost = (ep + 1) // 2

    if mp_pvp:
        return MissionState(
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
        groups.append(make_group(data, "enemy", f"E-{serial}", cls_name, ex, ey))

    kind = "strike" if (round_idx % 2 == 1) else "recovery"
    objective: Optional[Any] = None
    pods: List[Any] = []
    pods_required = 0

    if kind == "strike":
        ox, oy = WORLD_W * 0.73, WORLD_H * 0.34
        hp = 600.0 + float(round_idx) * 125.0
        objective = GroundObjective(x=ox, y=oy, hp=hp, max_hp=hp)
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
        base_x, base_y = WORLD_W * 0.58, WORLD_H * 0.26
        n_pods = 3 + min(5, (round_idx + 1) // 2)
        for i in range(n_pods):
            pods.append(
                SalvagePod(
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

    return MissionState(
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
    mission.enemy_label_serial += 1
    side = rng.choice(["left", "right"])
    ex = 60.0 if side == "left" else WORLD_W - 60.0
    ey = rng.uniform(WORLD_H * 0.16, WORLD_H * 0.8)
    pool = ["Frigate", "Destroyer", "Cruiser", "Destroyer", "Frigate"]
    if mission.enemy_label_serial > 10 and rng.random() < 0.28:
        pool.extend(["Battleship", "Cruiser"])
    cls_name = rng.choice(pool)
    groups.append(make_group(data, "enemy", f"E-{mission.enemy_label_serial}", cls_name, ex, ey))


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


# ════════════════════════════════════════════════════════════════════════════
#  Ordnance: targeting, PD, firing, ballistics, missiles, VFX
# ════════════════════════════════════════════════════════════════════════════

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
    if isinstance(pref, GroundObjective):
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
    if isinstance(pref, GroundObjective):
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
    if isinstance(target, Group):
        if target.side != "player":
            return
        target.engagement_timer = max(target.engagement_timer, ENGAGEMENT_RETURN_FIRE_SEC)
        for si in control_group_slots_for_capital_label(control_groups, target.label):
            cg_weapons_free[si] = True
    elif isinstance(target, Craft):
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
    if side == "enemy" and fog is not None and not fog_cell_visible(fog, x, y):
        return None
    best = None
    best_d = max_r + 1
    for t in iter_hostiles(
        groups, crafts, side, viewer_owner=viewer_owner, mp_pvp=mp_pvp
    ):
        if fog is not None and not fog_cell_visible(fog, t.x, t.y):
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
        if isinstance(pref, Craft) and not pref.dead:
            if _craft_is_hostile_to_side(
                pref, side, viewer_owner=launcher_owner, mp_pvp=mp_pvp
            ):
                if fog is None or fog_cell_visible(fog, pref.x, pref.y):
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
            if fog is not None and not fog_cell_visible(fog, c.x, c.y):
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
    wr = weapon_range(data, {"projectile": "PD Slug", "fire_rate": 1.0})
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
    for _ in range(10):
        ang = random.uniform(0, 2 * math.pi)
        v = random.uniform(80, 220) * SPARK_SPEED_SCALE
        sparks.append(
            VFXSpark(
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
    dx, dy = tx - sx, ty - sy
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    perp_x, perp_y = -uy, ux
    base_ang = math.atan2(uy, ux)
    spd_streak = 760 * SPARK_SPEED_SCALE

    def add_spark(px: float, py: float, vx: float, vy: float, ttl: float, r: int, col: Tuple[int, int, int]) -> None:
        sparks.append(VFXSpark(px, py, vx, vy, ttl, ttl, r, col))

    if proj_name == "Light Rail":
        L = min(dist * 0.36, 165)
        beams.append(VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.08, 0.08, (160, 220, 255), 2))
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
        beams.append(VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.15, 0.15, (255, 145, 65), 5))
        beams.append(
            VFXBeam(sx - ux * 8, sy - uy * 8, sx + ux * (L + 12), sy + uy * (L + 12), 0.11, 0.11, (255, 215, 100), 3)
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
        beams.append(VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.095, 0.095, (205, 130, 255), 3))
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
        beams.append(VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.12, 0.12, (255, 255, 130), 6))
        beams.append(
            VFXBeam(sx - ux * 5, sy - uy * 5, sx + ux * (L + 18), sy + uy * (L + 18), 0.095, 0.095, (195, 255, 95), 4)
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
        beams.append(VFXBeam(sx, sy, sx + ux * L, sy + uy * L, 0.065, 0.065, (190, 200, 210), 2))


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
    launcher: Optional[Any] = None,
) -> None:

    def _pref_blocked_by_fog(pref: Optional[Any]) -> bool:
        if fog is None or pref is None or not isinstance(pref, (Group, Craft)):
            return False
        if not fog_cell_visible(fog, pref.x, pref.y):
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
    if side == "enemy" and fog is not None and not fog_cell_visible(fog, x, y):
        return
    for rw in weapons:
        if rw.cooldown > 0:
            continue
        proj = projectile_by_name(data, rw.projectile_name)
        wr = weapon_range(data, {"projectile": rw.projectile_name, "fire_rate": rw.fire_rate})
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
        if isinstance(tgt, GroundObjective):
            if d > r + tgt.radius * 0.32:
                continue
        elif d > r:
            continue
        obs_list = obstacles or []
        if obs_list:
            if proj["delivery"] == "missile" and not clear_shot_xy(
                x, y, tgt.x, tgt.y, obs_list, "missile"
            ):
                rw.cooldown = 0.15
                continue
            if (
                proj["delivery"] == "ballistic"
                and rw.projectile_name == "PD Slug"
                and not clear_shot_xy(x, y, tgt.x, tgt.y, obs_list, "pd_slug")
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
                BallisticSlug(
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
                VFXSpark(
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
                cid = int(getattr(launcher, "color_id", 0)) if launcher is not None else 0
                base = MP_PLAYER_PALETTE[cid % len(MP_PLAYER_PALETTE)]
                col = tuple(min(255, int(ch * 1.15)) for ch in base)
            else:
                col = (255, 120, 100)
            mz = origin_z + random.uniform(-4, 4)
            intercept_hp = float(proj.get("pd_intercept_hp", MISSILE_PD_INTERCEPT_HP_DEFAULT))
            missiles.append(
                Missile(
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
    if tgt is None:
        return False
    if isinstance(tgt, Missile):
        if tgt.side == side or tgt.ttl <= 0:
            return False
        return any(tgt is mm for mm in all_missiles)
    return not getattr(tgt, "dead", False)


def _missile_reacquire_range(data: dict, proj_name: str) -> float:
    return max(140.0, weapon_range(data, {"projectile": proj_name, "fire_rate": 0.35}) * 1.2)


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
            if isinstance(tgt, Missile):
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
                if isinstance(tgt, GroundObjective):
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
    out.clear()
    seen_tid: Set[int] = set()
    for m in missiles:
        if m.side != "player" or m.ttl <= 0:
            continue
        tgt = m.target
        if tgt is None or getattr(tgt, "dead", False):
            continue
        if isinstance(tgt, GroundObjective):
            pass
        elif isinstance(tgt, (Group, Craft)):
            if getattr(tgt, "side", "") != "enemy":
                continue
        else:
            continue
        if not fog_cell_visible(fog, m.x, m.y):
            continue
        if fog_cell_visible(fog, tgt.x, tgt.y):
            continue
        tid = id(tgt)
        if tid in seen_tid:
            continue
        seen_tid.add(tid)
        rng = random.Random(tid & 0xFFFFFFFF)
        qual = 0.30 + (tid % 89) / 260.0
        if obstacles and segment_blocked_by_asteroids(m.x, m.y, tgt.x, tgt.y, obstacles, inflate=14.0):
            qual = max(0.08, qual * 0.72)
            lab = "Obscured seeker trace"
        else:
            lab = "Seeker contact"
        jitter = (1.0 - min(1.0, qual + 0.15)) * 110.0 + 20.0
        jx = rng.uniform(-jitter, jitter)
        jy = rng.uniform(-jitter, jitter)
        out.append(
            SensorGhost(
                x=tgt.x + jx,
                y=tgt.y + jy,
                ttl=1.0,
                label=lab,
                quality=min(0.92, qual),
            )
        )


# ════════════════════════════════════════════════════════════════════════════
#  Orders: formations, picking, fleet construction
# ════════════════════════════════════════════════════════════════════════════

ACTIVE_PING_RADIUS = 780.0
ACTIVE_PING_TTL = 1.05
ACTIVE_PING_COOLDOWN = 5.5
SENSOR_GHOST_TTL = 0.42

Z_VIS_LIFT = 0.36
Z_SCALE_K = 0.0042
Z_MIN_SCALE = 0.58

CAPITAL_PICK_R = 42
FORMATION_BASE_R = 58
FORMATION_PER_UNIT = 12
FORMATION_MODE_RING = 0
FORMATION_MODE_CARRIER_CORE = 1
FORMATION_MODE_DAMAGED_CORE = 2
FORMATION_MODE_NAMES = ("Ring", "Carrier core", "Damaged core")

RECRUIT_LABEL_PREFIX = {
    "Frigate": "FF",
    "Destroyer": "DD",
    "Cruiser": "CG",
    "Battleship": "BB",
    "Carrier": "CV",
}

_move_pace_seq = 0


def _alloc_move_pace_group_id() -> int:
    global _move_pace_seq
    _move_pace_seq += 1
    return _move_pace_seq


def project_visual(wx: float, wy: float, wz: float) -> Tuple[float, float, float]:
    """Map world position + altitude to screen (fake 3D / radar depth)."""
    sx = wx
    sy = wy - wz * Z_VIS_LIFT
    sc = max(Z_MIN_SCALE, 1.0 - wz * Z_SCALE_K)
    return sx, sy, sc


def world_to_screen(wx: float, wy: float, wz: float, cam_x: float, cam_y: float) -> Tuple[float, float, float]:
    px, py, sc = project_visual(wx, wy, wz)
    return px - cam_x, py - cam_y, sc


def screen_to_world_waypoint(mx: float, my: float, cam_x: float, cam_y: float, assume_z: float = 36.0) -> Tuple[float, float]:
    return mx + cam_x, my + cam_y + assume_z * Z_VIS_LIFT


def deploy_anchor_xy() -> Tuple[float, float]:
    return WORLD_W * 0.5, WORLD_H * 0.86


def spawn_active_sensor_pings(
    groups: List[Group],
    crafts: List[Craft],
    pings: List[ActivePing],
    ghosts: List[SensorGhost],
    obstacles: List[Asteroid],
    now_rng: random.Random,
    anchor_labels: Optional[Set[str]] = None,
) -> None:
    sources: List[Tuple[float, float]] = []
    for g in groups:
        if g.side == "player" and g.selected and not g.dead and g.render_capital:
            sources.append((g.x, g.y))
    for c in crafts:
        if c.side == "player" and c.selected and not c.dead and not c.parent.dead:
            sources.append((c.x, c.y))
    if not sources:
        return
    if anchor_labels is not None:
        anchor_labels.clear()
        for g in groups:
            if g.side == "player" and g.selected and not g.dead and g.render_capital:
                anchor_labels.add(g.label)
        for c in crafts:
            if c.side == "player" and c.selected and not c.dead and not c.parent.dead:
                anchor_labels.add(c.label)
                anchor_labels.add(c.parent.label)
    for sx, sy in sources:
        pings.append(ActivePing(x=sx, y=sy, ttl=ACTIVE_PING_TTL, radius=ACTIVE_PING_RADIUS))
    ghost_seen: Set[int] = set()
    for g in groups:
        if g.side != "enemy" or g.dead:
            continue
        eid = id(g)
        if eid in ghost_seen:
            continue
        for sx, sy in sources:
            if dist_xy(sx, sy, g.x, g.y) > ACTIVE_PING_RADIUS * 0.92:
                continue
            if obstacles and segment_blocked_by_asteroids(sx, sy, g.x, g.y, obstacles, inflate=18.0):
                qual = now_rng.uniform(0.0, 0.45)
                lab = "Obscured trace"
            else:
                qual = now_rng.uniform(0.35, 1.0)
                if getattr(g, "render_capital", False):
                    lab = "Capital-class contact"
                else:
                    lab = "Strike craft trace"
            jitter = (1.15 - qual) * 200.0 + 28.0
            ghosts.append(
                SensorGhost(
                    x=g.x + now_rng.uniform(-jitter, jitter),
                    y=g.y + now_rng.uniform(-jitter, jitter),
                    ttl=SENSOR_GHOST_TTL,
                    label=lab,
                    quality=qual,
                )
            )
            ghost_seen.add(eid)
            break
    for c in crafts:
        if c.side != "enemy" or c.dead:
            continue
        eid = id(c)
        if eid in ghost_seen:
            continue
        for sx, sy in sources:
            if dist_xy(sx, sy, c.x, c.y) > ACTIVE_PING_RADIUS * 0.88:
                continue
            if obstacles and segment_blocked_by_asteroids(sx, sy, c.x, c.y, obstacles, inflate=14.0):
                qual = now_rng.uniform(0.0, 0.5)
                lab = "Fuzzy return"
            else:
                qual = now_rng.uniform(0.4, 1.0)
                lab = "Strike craft trace"
            jitter = (1.0 - qual) * 160.0 + 22.0
            ghosts.append(
                SensorGhost(
                    x=c.x + now_rng.uniform(-jitter, jitter),
                    y=c.y + now_rng.uniform(-jitter, jitter),
                    ttl=SENSOR_GHOST_TTL,
                    label=lab,
                    quality=qual,
                )
            )
            ghost_seen.add(eid)
            break


def clear_craft_selection(crafts: List[Craft]) -> None:
    for c in crafts:
        c.selected = False


def clear_selection(groups: List[Group]) -> None:
    for g in groups:
        g.selected = False


def set_selection(groups: List[Group], picked: List[Group]) -> None:
    clear_selection(groups)
    for g in picked:
        g.selected = True


def add_to_selection(groups: List[Group], to_add: List[Group]) -> None:
    for g in to_add:
        if not g.dead and g.render_capital and g.side == "player":
            g.selected = True


def carrier_hangar_squadrons(data: dict, carrier: Group) -> List[dict]:
    """Resolved squadrons for this carrier (JSON presets or default hangar layout)."""
    sc = ship_class_by_name(data, carrier.class_name)
    h = sc.get("hangar") or {}
    presets = h.get("loadout_presets")
    if presets:
        i = max(0, min(int(carrier.hangar_loadout_choice), len(presets) - 1))
        inner = presets[i].get("squadrons")
        return list(inner) if inner else []
    sq = h.get("squadrons")
    return list(sq) if sq else []


def carrier_squadron_count(data: dict, g: Group) -> int:
    if g.class_name != "Carrier":
        return 0
    return len(carrier_hangar_squadrons(data, g))


def ensure_carrier_wing_rallies(data: dict, g: Group) -> None:
    n = carrier_squadron_count(data, g)
    while len(g.strike_rally_wings) < n:
        g.strike_rally_wings.append(None)
    if len(g.strike_rally_wings) > n:
        g.strike_rally_wings[:] = g.strike_rally_wings[:n]


def clear_carrier_air_orders(g: Group) -> None:
    g.strike_rally = None
    for i in range(len(g.strike_rally_wings)):
        g.strike_rally_wings[i] = None


def carrier_squadron_indices_for_class(data: dict, carrier: Group, class_name: str) -> List[int]:
    squadrons = carrier_hangar_squadrons(data, carrier)
    out: List[int] = []
    for i, sq in enumerate(squadrons):
        if str(sq.get("class", "")) == class_name:
            out.append(i)
    return out


def apply_fighter_wing_context_order(
    data: dict,
    wing_f: List[Craft],
    wpx: float,
    wpy: float,
    mark: Optional[Any],
) -> bool:
    if not wing_f or not all(c.class_name in ("Fighter", "Interceptor") for c in wing_f):
        return False
    parents: Dict[int, Group] = {}
    for c in wing_f:
        parents[id(c.parent)] = c.parent
    for p in parents.values():
        ensure_carrier_wing_rallies(data, p)
        p.strike_rally = None
    if mark is not None:
        for p in parents.values():
            p.attack_target = mark
        for c in wing_f:
            si = c.squadron_index
            wings = c.parent.strike_rally_wings
            if si < len(wings):
                wings[si] = None
    else:
        for p in parents.values():
            p.attack_target = None
        for c in wing_f:
            si = c.squadron_index
            wings = c.parent.strike_rally_wings
            if si < len(wings):
                wings[si] = (wpx, wpy)
    return True


def apply_fighter_strike_order(
    data: dict,
    crafts: List[Craft],
    selected_groups: List[Group],
    wpx: float,
    wpy: float,
    mark: Optional[Any],
) -> bool:
    """Fighter/interceptor orders: selected wing craft, else all fighter squadrons on selected carriers."""
    wing_pick = [
        c
        for c in crafts
        if c.side == "player" and c.selected and not c.dead and not c.parent.dead and c.parent.class_name == "Carrier"
    ]
    wing_f = [c for c in wing_pick if c.class_name in ("Fighter", "Interceptor")]
    if wing_f:
        return apply_fighter_wing_context_order(data, wing_f, wpx, wpy, mark)
    carriers_sel = [g for g in selected_groups if g.class_name == "Carrier" and not g.dead]
    if not carriers_sel:
        return False
    did = False
    for g in carriers_sel:
        fidx: List[int] = []
        for cn in ("Fighter", "Interceptor"):
            fidx.extend(carrier_squadron_indices_for_class(data, g, cn))
        fidx = sorted(set(fidx))
        if not fidx:
            continue
        did = True
        ensure_carrier_wing_rallies(data, g)
        g.strike_rally = None
        if mark is not None:
            g.attack_target = mark
            for i in fidx:
                if i < len(g.strike_rally_wings):
                    g.strike_rally_wings[i] = None
        else:
            g.attack_target = None
            for i in fidx:
                if i < len(g.strike_rally_wings):
                    g.strike_rally_wings[i] = (wpx, wpy)
    return did


def apply_bomber_context_order(
    data: dict,
    crafts: List[Craft],
    selected_groups: List[Group],
    wpx: float,
    wpy: float,
    mark: Optional[Any],
) -> bool:
    wing_pick = [
        c
        for c in crafts
        if c.side == "player" and c.selected and not c.dead and not c.parent.dead and c.parent.class_name == "Carrier"
    ]
    bom_wing = [c for c in wing_pick if c.class_name == "Bomber"]
    if bom_wing:
        parents = {id(c.parent): c.parent for c in bom_wing}
        for p in parents.values():
            ensure_carrier_wing_rallies(data, p)
            p.strike_rally = None
        if mark is not None:
            for p in parents.values():
                p.attack_target = mark
            for c in bom_wing:
                si = c.squadron_index
                wings = c.parent.strike_rally_wings
                if si < len(wings):
                    wings[si] = None
        else:
            for p in parents.values():
                p.attack_target = None
            for c in bom_wing:
                si = c.squadron_index
                wings = c.parent.strike_rally_wings
                if si < len(wings):
                    wings[si] = (wpx, wpy)
        return True
    carriers_sel = [g for g in selected_groups if g.class_name == "Carrier" and not g.dead]
    if not carriers_sel:
        return False
    did = False
    for g in carriers_sel:
        bidx = carrier_squadron_indices_for_class(data, g, "Bomber")
        if not bidx:
            continue
        did = True
        ensure_carrier_wing_rallies(data, g)
        g.strike_rally = None
        if mark is not None:
            g.attack_target = mark
            for i in bidx:
                if i < len(g.strike_rally_wings):
                    g.strike_rally_wings[i] = None
        else:
            g.attack_target = None
            for i in bidx:
                if i < len(g.strike_rally_wings):
                    g.strike_rally_wings[i] = (wpx, wpy)
    return did


def select_strike_wing_for_carriers(
    crafts: List[Craft],
    groups: List[Group],
    squadron_index: int,
    additive: bool,
    owner_id: Optional[str] = None,
) -> None:
    carriers = [
        g
        for g in groups
        if g.side == "player"
        and g.selected
        and not g.dead
        and g.class_name == "Carrier"
        and (owner_id is None or getattr(g, "owner_id", "") == owner_id)
    ]
    if not carriers:
        carriers = [
            g
            for g in groups
            if g.side == "player"
            and not g.dead
            and g.class_name == "Carrier"
            and (owner_id is None or getattr(g, "owner_id", "") == owner_id)
        ]
    if not additive:
        clear_craft_selection(crafts)
    car_set = set(id(g) for g in carriers)
    for c in crafts:
        if c.dead or id(c.parent) not in car_set:
            continue
        if c.squadron_index == squadron_index:
            c.selected = True


def _is_hostile_pick_target(
    u: Any,
    *,
    viewer_side: str,
    viewer_owner: Optional[str],
    mp_pvp: bool,
) -> bool:
    if u.dead:
        return False
    if u.side == "enemy":
        return True
    if mp_pvp and viewer_side == "player" and u.side == "player" and viewer_owner:
        return getattr(u, "owner_id", None) != viewer_owner
    return u.side != viewer_side


def pick_hostile_at(
    groups: List[Group],
    crafts: List[Craft],
    mx: int,
    my: int,
    cam_x: float,
    cam_y: float,
    viewer_side: str = "player",
    viewer_owner: Optional[str] = None,
    mp_pvp: bool = False,
) -> Optional[Any]:
    """Closest enemy capital or strike craft under the cursor (screen px)."""
    best: Optional[Any] = None
    best_d = 9999.0
    for g in groups:
        if not g.render_capital or not _is_hostile_pick_target(
            g, viewer_side=viewer_side, viewer_owner=viewer_owner, mp_pvp=mp_pvp
        ):
            continue
        sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        pick_r = CAPITAL_PICK_R * max(0.85, sc)
        d = dist_xy(sx, sy, float(mx), float(my))
        if d < pick_r and d < best_d:
            best_d = d
            best = g
    for c in crafts:
        if not _is_hostile_pick_target(
            c, viewer_side=viewer_side, viewer_owner=viewer_owner, mp_pvp=mp_pvp
        ):
            continue
        sx, sy, sc = world_to_screen(c.x, c.y, c.z, cam_x, cam_y)
        pick_r = 24.0 * max(0.78, sc)
        d = dist_xy(sx, sy, float(mx), float(my))
        if d < pick_r and d < best_d:
            best_d = d
            best = c
    return best


def pick_strike_objective_at(
    objective: GroundObjective, mx: int, my: int, cam_x: float, cam_y: float
) -> bool:
    if objective.dead:
        return False
    sx, sy, sc = world_to_screen(objective.x, objective.y, objective.z, cam_x, cam_y)
    pick_r = max(28.0, objective.radius * sc * 0.55)
    return dist_xy(sx, sy, float(mx), float(my)) < pick_r


def formation_offsets(n: int) -> List[Tuple[float, float]]:
    if n <= 0:
        return []
    if n == 1:
        return [(0.0, 0.0)]
    r = FORMATION_BASE_R + min(n, 8) * FORMATION_PER_UNIT * 0.15
    return [(math.cos(i * 2 * math.pi / n) * r, math.sin(i * 2 * math.pi / n) * r) for i in range(n)]


def formation_offsets_layered(n_inner: int, n_total: int) -> List[Tuple[float, float]]:
    """Inner ring for protected ships, outer ring for the rest."""
    if n_total <= 0:
        return []
    r_in = FORMATION_BASE_R * 0.42
    r_out = FORMATION_BASE_R + FORMATION_PER_UNIT * 1.35
    ni = max(0, min(n_inner, n_total))
    out: List[Tuple[float, float]] = []
    if ni <= 0:
        return formation_offsets(n_total)
    if ni == 1:
        out.append((0.0, 0.0))
    else:
        for i in range(ni):
            ang = i * 2 * math.pi / ni
            out.append((math.cos(ang) * r_in, math.sin(ang) * r_in))
    rem = n_total - ni
    for j in range(rem):
        ang = j * 2 * math.pi / max(1, rem) + 0.2
        out.append((math.cos(ang) * r_out, math.sin(ang) * r_out))
    return out


def order_capitals_for_formation(selected: List[Group], mode: int) -> List[Group]:
    alive = [g for g in selected if not g.dead and g.render_capital]
    if not alive:
        return []
    if mode == FORMATION_MODE_CARRIER_CORE:
        carriers = [g for g in alive if g.class_name == "Carrier"]
        rest = sorted([g for g in alive if g.class_name != "Carrier"], key=lambda g: (g.label, g.class_name))
        return sorted(carriers, key=lambda g: (g.label, g.class_name)) + rest
    if mode == FORMATION_MODE_DAMAGED_CORE:
        return sorted(alive, key=lambda g: (g.hp / max(g.max_hp, 1e-6), g.label))
    return sorted(alive, key=lambda g: (g.label, g.class_name))


def formation_offsets_for_mode(ordered: List[Group], mode: int) -> List[Tuple[float, float]]:
    n = len(ordered)
    if n == 0:
        return []
    if mode == FORMATION_MODE_RING:
        return formation_offsets(n)
    if mode == FORMATION_MODE_CARRIER_CORE:
        n_carriers = sum(1 for g in ordered if g.class_name == "Carrier")
        n_inner = max(1, n_carriers) if n_carriers else 1
        return formation_offsets_layered(min(n_inner, n), n)
    if mode == FORMATION_MODE_DAMAGED_CORE:
        n_inner = max(1, n // 2)
        return formation_offsets_layered(n_inner, n)
    return formation_offsets(n)


def issue_move_orders(selected: List[Group], mx: float, my: float, formation_mode: int) -> bool:
    if not selected:
        return False
    for g in selected:
        if not g.dead:
            g.attack_move = False
            g.attack_target = None
    ordered = order_capitals_for_formation(selected, formation_mode)
    if not ordered:
        return False
    offs = formation_offsets_for_mode(ordered, formation_mode)
    pace_id = _alloc_move_pace_group_id()
    for g, (ox, oy) in zip(ordered, offs):
        g.set_waypoint(mx + ox, my + oy)
        g.move_pace_key = pace_id
    return True


def issue_line_move_orders(selected: List[Group], x0: float, y0: float, x1: float, y1: float, formation_mode: int) -> bool:
    for g in selected:
        if not g.dead:
            g.attack_move = False
            g.attack_target = None
    ordered = order_capitals_for_formation(selected, formation_mode)
    if not ordered:
        return False
    n = len(ordered)
    pace_id = _alloc_move_pace_group_id()
    if n == 1:
        ordered[0].set_waypoint((x0 + x1) * 0.5, (y0 + y1) * 0.5)
        ordered[0].move_pace_key = pace_id
        return True
    for i, g in enumerate(ordered):
        t = i / (n - 1)
        g.set_waypoint(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        g.move_pace_key = pace_id
    return True


def issue_attack_move_orders(selected: List[Group], mx: float, my: float, formation_mode: int) -> bool:
    if not issue_move_orders(selected, mx, my, formation_mode):
        return False
    for g in selected:
        if not g.dead and g.render_capital:
            g.attack_move = True
    return True


def issue_attack_line_move_orders(
    selected: List[Group], x0: float, y0: float, x1: float, y1: float, formation_mode: int
) -> bool:
    if not issue_line_move_orders(selected, x0, y0, x1, y1, formation_mode):
        return False
    for g in selected:
        if not g.dead and g.render_capital:
            g.attack_move = True
    return True


def toggle_weapon_stance_for_selection(
    groups: List[Group],
    control_groups: List[Optional[List[str]]],
    cg_weapons_free: List[bool],
) -> bool:
    """Flip weapons-free for every control group slot that contains a selected capital. False if none."""
    sel_labels = [
        g.label
        for g in groups
        if g.side == "player" and g.selected and not g.dead and g.render_capital
    ]
    slots: Set[int] = set()
    for lab in sel_labels:
        slots.update(control_group_slots_for_capital_label(control_groups, lab))
    if not slots:
        return False
    new_val = not any(cg_weapons_free[s] for s in slots)
    for s in slots:
        cg_weapons_free[s] = new_val
    return True


def spawn_hangar_crafts(data: dict, carrier: Group) -> List[Craft]:
    squadrons = carrier_hangar_squadrons(data, carrier)
    carrier.strike_rally_wings = [None] * len(squadrons)
    crafts: List[Craft] = []
    idx = 0
    for sq_i, sq in enumerate(squadrons):
        cname = sq["class"]
        count = int(sq["count"])
        csc = ship_class_by_name(data, cname)
        for _ in range(count):
            spd = (22.0 + (float(csc["speed"]) / 100.0) * 95.0) * SPEED_SCALE
            mr = class_max_weapon_range(data, csc)
            crafts.append(
                Craft(
                    side=carrier.side,
                    owner_id=carrier.owner_id,
                    color_id=carrier.color_id,
                    label=f"{carrier.label}-{cname[:3]}{idx}",
                    class_name=cname,
                    parent=carrier,
                    slot_index=idx,
                    squadron_index=sq_i,
                    x=carrier.x,
                    y=carrier.y,
                    max_hp=float(csc.get("hull_hp", 20)),
                    hp=float(csc.get("hull_hp", 20)),
                    speed=spd,
                    max_range=mr,
                    weapons=build_runtime_weapons(data, csc),
                    z=carrier.z + (idx % 5) * 3.5 + random.uniform(-2, 2),
                    orbit_phase=idx * 0.9,
                )
            )
            idx += 1
    return crafts


def build_initial_player_fleet(
    data: dict,
    *,
    owner_id: str = "player",
    color_id: int = 0,
    label_prefix: str = "",
) -> Tuple[List[Group], List[Craft]]:
    ax, ay = deploy_anchor_xy()
    groups: List[Group] = [
        make_group(data, "player", f"{label_prefix}CV-1", "Carrier", ax - 200, ay, owner_id=owner_id, color_id=color_id),
        make_group(data, "player", f"{label_prefix}DD-1", "Destroyer", ax + 30, ay + 28, owner_id=owner_id, color_id=color_id),
        make_group(data, "player", f"{label_prefix}CG-1", "Cruiser", ax + 230, ay - 12, owner_id=owner_id, color_id=color_id),
        make_group(data, "player", f"{label_prefix}FF-1", "Frigate", ax - 360, ay - 6, owner_id=owner_id, color_id=color_id),
    ]
    crafts: List[Craft] = []
    for g in groups:
        if ship_class_by_name(data, g.class_name).get("hangar"):
            crafts.extend(spawn_hangar_crafts(data, g))
    clear_selection(groups)
    groups[0].selected = True
    return groups, crafts


def build_player_fleet_from_design(
    data: dict,
    *,
    owner_id: str,
    color_id: int,
    design_rows: Optional[List[Dict[str, str]]] = None,
    label_prefix: str = "",
    spawn_anchor: Optional[Tuple[float, float]] = None,
) -> Tuple[List[Group], List[Craft]]:
    if not design_rows:
        return build_initial_player_fleet(data, owner_id=owner_id, color_id=color_id, label_prefix=label_prefix)
    ax, ay = spawn_anchor if spawn_anchor is not None else deploy_anchor_xy()
    groups: List[Group] = []
    for i, row in enumerate(design_rows):
        cls = str((row or {}).get("class_name") or "").strip()
        try:
            ship_class_by_name(data, cls)
        except KeyError:
            continue
        px = ax - 320 + (i % 6) * 150.0
        py = ay + (i // 6) * 56.0
        lbl = str((row or {}).get("label") or f"{RECRUIT_LABEL_PREFIX.get(cls, 'UN')}-{i+1}")
        groups.append(
            make_group(
                data,
                "player",
                f"{label_prefix}{lbl}",
                cls,
                px,
                py,
                owner_id=owner_id,
                color_id=color_id,
            )
        )
    if not groups:
        return build_initial_player_fleet(data, owner_id=owner_id, color_id=color_id, label_prefix=label_prefix)
    crafts: List[Craft] = []
    for g in groups:
        if ship_class_by_name(data, g.class_name).get("hangar"):
            crafts.extend(spawn_hangar_crafts(data, g))
    clear_selection(groups)
    groups[0].selected = True
    return groups, crafts


# ════════════════════════════════════════════════════════════════════════════
#  MP command dispatch
# ════════════════════════════════════════════════════════════════════════════

def combat_cmd_tick_allowed(cmd: Dict[str, Any], *, host_tick: int) -> bool:
    """True if the client's basis tick is not ahead of the host sim tick.

    Legacy clients always sent tick=0; for host_tick >= 0 that remains accepted.
    Clients should set tick to the last combat_snap tick they applied (see mp_send_client).
    """
    try:
        ct = int(cmd.get("tick", 0))
    except (TypeError, ValueError):
        return True
    try:
        ht = int(host_tick)
    except (TypeError, ValueError):
        return True
    return ct <= ht


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
    kind = str(cmd.get("kind", ""))
    pl = cmd.get("payload") or {}
    glab = [str(x) for x in (pl.get("group_labels") or [])]
    clab = [str(x) for x in (pl.get("craft_labels") or [])]
    sender = str(cmd.get("sender") or "").strip()
    mpv = bool(getattr(mission, "mp_pvp", False))
    _pick_hostile = lambda mx, my, cx, cy: pick_hostile_at(
        groups,
        crafts,
        int(mx),
        int(my),
        float(cx),
        float(cy),
        viewer_owner=sender if sender else None,
        mp_pvp=mpv,
    )

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
                    clear_carrier_air_orders(g)
        elif kind == "move_world":
            wpx, wpy = float(pl["wpx"]), float(pl["wpy"])
            fm = int(pl.get("formation_mode", formation_mode_holder[0]))
            sel = groups_pick()
            if pl.get("attack_move"):
                issue_attack_move_orders(sel, wpx, wpy, fm)
            else:
                issue_move_orders(sel, wpx, wpy, fm)
        elif kind == "line_move_world":
            wx0, wy0 = float(pl["wx0"]), float(pl["wy0"])
            wx1, wy1 = float(pl["wx1"]), float(pl["wy1"])
            fm = int(pl.get("formation_mode", formation_mode_holder[0]))
            sel = [g for g in groups_pick() if g.render_capital]
            if pl.get("attack_move"):
                issue_attack_line_move_orders(sel, wx0, wy0, wx1, wy1, fm)
            else:
                issue_line_move_orders(sel, wx0, wy0, wx1, wy1, fm)
        elif kind == "attack_target_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            caps = [g for g in groups_pick() if g.render_capital]
            mark = _pick_hostile(mx, my, cam_x, cam_y)
            if mark is None and mission.kind == "strike" and mission.objective and not mission.objective.dead:
                if pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y):
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
            wpx, wpy = screen_to_world_waypoint(mx, my, cam_x, cam_y)
            mark = _pick_hostile(mx, my, cam_x, cam_y)
            atk_set = False
            if mark is not None:
                for gc in sel_caps_ctx:
                    gc.attack_target = mark
                atk_set = True
            elif (
                mission.kind == "strike"
                and mission.objective
                and not mission.objective.dead
                and pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y)
            ):
                for gc in sel_caps_ctx:
                    gc.attack_target = mission.objective
                atk_set = True
            if not atk_set:
                issue_move_orders(sel_ord, wpx, wpy, formation_mode_holder[0])
        elif kind == "fighter_strike_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            wpx, wpy = screen_to_world_waypoint(mx, my, cam_x, cam_y)
            mark = _pick_hostile(mx, my, cam_x, cam_y)
            if mark is None and mission.kind == "strike" and mission.objective and not mission.objective.dead:
                if pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y):
                    mark = mission.objective
            apply_fighter_strike_order(data, crafts, groups_pick(), wpx, wpy, mark)
        elif kind == "bomber_strike_pick":
            cam_x, cam_y = float(pl["cam_x"]), float(pl["cam_y"])
            mx, my = float(pl["mx"]), float(pl["my"])
            wpx, wpy = screen_to_world_waypoint(mx, my, cam_x, cam_y)
            mark = _pick_hostile(mx, my, cam_x, cam_y)
            if mark is None and mission.kind == "strike" and mission.objective and not mission.objective.dead:
                if pick_strike_objective_at(mission.objective, mx, my, cam_x, cam_y):
                    mark = mission.objective
            apply_bomber_context_order(data, crafts, groups_pick(), wpx, wpy, mark)
        elif kind == "sensor_ping":
            seed = int(pl.get("rng_seed", now_ms))
            if now_ms >= ping_ready_at_ms_holder[0]:
                spawn_active_sensor_pings(
                    groups,
                    crafts,
                    active_pings,
                    sensor_ghosts,
                    mission_obstacles,
                    random.Random(seed % 100003),
                    anchor_labels=ping_ghost_anchor_labels,
                )
                ping_ready_at_ms_holder[0] = now_ms + int(ACTIVE_PING_COOLDOWN * 1000)
        elif kind == "recall_carriers":
            for g in groups_pick():
                if g.class_name == "Carrier":
                    clear_carrier_air_orders(g)
        elif kind == "clear_carrier_air_selected":
            if glab:
                gm = {g.label: g for g in groups}
                for lab in glab:
                    g = gm.get(lab)
                    if g and g.side == "player" and g.class_name == "Carrier":
                        if not sender or getattr(g, "owner_id", "") == sender:
                            clear_carrier_air_orders(g)
            elif sender:
                for g in groups:
                    if (
                        g.side == "player"
                        and g.selected
                        and g.class_name == "Carrier"
                        and getattr(g, "owner_id", "") == sender
                    ):
                        clear_carrier_air_orders(g)
            else:
                for g in groups:
                    if g.side == "player" and g.selected and g.class_name == "Carrier":
                        clear_carrier_air_orders(g)
        elif kind == "formation_cycle":
            formation_mode_holder[0] = (formation_mode_holder[0] + 1) % 3
        elif kind == "weapons_toggle":
            if toggle_weapon_stance_for_selection(groups, control_groups, cg_weapons_free):
                if audio:
                    audio.play_positive()
            elif audio:
                audio.play_negative()
        elif kind == "control_assign":
            slot = int(pl["slot"])
            labels = [str(x) for x in (pl.get("labels") or [])]
            if sender:
                gm = {g.label: g for g in groups}
                labels = [
                    lab
                    for lab in labels
                    if lab in gm and getattr(gm[lab], "owner_id", "") == sender
                ]
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
                    if g.side == "player"
                    and not g.dead
                    and g.render_capital
                    and g.label in labels
                    and (not sender or getattr(g, "owner_id", "") == sender)
                ]
                if picked:
                    if shift:
                        add_to_selection(groups, picked)
                    else:
                        clear_craft_selection(crafts)
                        set_selection(groups, picked)
        elif kind == "select_strike_wing":
            sq = int(pl["squadron_index"])
            shift = bool(pl.get("shift"))
            select_strike_wing_for_carriers(
                crafts, groups, sq, shift, sender if sender else None
            )
        elif kind == "pvp_set_territory_owner":
            if bool(getattr(mission, "mp_pvp", False)):
                node_id = str(pl.get("node_id") or "").strip()
                owner = str(pl.get("owner_id") or "").strip()
                if node_id:
                    terr = getattr(mission, "pvp_territory", {}) or {}
                    if owner:
                        terr[node_id] = owner
                    elif node_id in terr:
                        terr.pop(node_id, None)
                    mission.pvp_territory = terr
        elif kind == "pvp_add_scrap":
            if bool(getattr(mission, "mp_pvp", False)):
                owner = str(pl.get("owner_id") or sender or "").strip()
                amt = int(pl.get("amount", 0))
                if owner and amt:
                    scrap = getattr(mission, "pvp_scrap", {}) or {}
                    scrap[owner] = int(scrap.get(owner, 0)) + int(amt)
                    mission.pvp_scrap = scrap
        elif kind == "purchase_deploy":
            if bool(getattr(mission, "mp_pvp", False)) and sender:
                rows = pl.get("design_rows") if isinstance(pl.get("design_rows"), list) else None
                if rows:
                    cost = max(0, int(pl.get("cost", 0)))
                    scrap = getattr(mission, "pvp_scrap", {}) or {}
                    have = int(scrap.get(sender, 0))
                    if have >= cost:
                        sx = float(pl.get("spawn_x", 0.0))
                        sy = float(pl.get("spawn_y", 0.0))
                        color_id = 0
                        for g in groups:
                            if g.side == "player" and getattr(g, "owner_id", "") == sender:
                                color_id = int(getattr(g, "color_id", 0))
                                break
                        ng, nc = build_player_fleet_from_design(
                            data,
                            owner_id=sender,
                            color_id=color_id,
                            design_rows=rows,
                            label_prefix=f"{sender}:BG-{now_ms}:",
                            spawn_anchor=(sx, sy),
                        )
                        groups.extend(ng)
                        crafts.extend(nc)
                        scrap[sender] = have - cost
                        mission.pvp_scrap = scrap
                        bag = getattr(mission, "pvp_battlegroups", {}) or {}
                        hist = bag.get(sender)
                        if not isinstance(hist, list):
                            hist = []
                        hist.append({"cost": cost, "spawn_x": sx, "spawn_y": sy, "rows": list(rows)})
                        bag[sender] = hist[-12:]
                        mission.pvp_battlegroups = bag
        elif kind == "clear_craft_selection":
            clear_craft_selection(crafts)
    finally:
        _restore_selection(sg, sc)


# ════════════════════════════════════════════════════════════════════════════
#  Snapshot serialization
# ════════════════════════════════════════════════════════════════════════════

SNAP_VERSION = 2


def _roundf(x: Any, nd: int = 5) -> Any:
    if isinstance(x, float):
        return round(x, nd)
    return x


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_state_dict(state: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(state)).hexdigest()


def _attack_target_ref(
    tgt: Any,
    mission: Any,
    missiles: List[Any],
) -> Optional[Dict[str, Any]]:
    if tgt is None:
        return None
    if isinstance(tgt, GroundObjective):
        if mission.objective is tgt:
            return {"k": "objective"}
        return {"k": "ground", "x": _roundf(tgt.x), "y": _roundf(tgt.y)}
    if isinstance(tgt, Group):
        return {"k": "group", "label": tgt.label, "side": tgt.side}
    if isinstance(tgt, Craft):
        return {"k": "craft", "label": tgt.label}
    if isinstance(tgt, Missile):
        try:
            i = missiles.index(tgt)
        except ValueError:
            i = -1
        return {"k": "missile", "i": i}
    return None


def _resolve_attack_target(
    ref: Optional[Dict[str, Any]],
    mission: Any,
    label_group: Dict[str, Any],
    label_craft: Dict[str, Any],
    missiles: List[Any],
) -> Any:
    if not ref:
        return None

    k = ref.get("k")
    if k == "objective":
        return mission.objective
    if k == "ground":
        if mission.objective and not mission.objective.dead:
            return mission.objective
        return None
    if k == "group":
        g = label_group.get(ref.get("label") or "")
        if g and getattr(g, "side", None) == ref.get("side"):
            return g
        return label_group.get(ref.get("label") or "")
    if k == "craft":
        return label_craft.get(ref.get("label") or "")
    if k == "missile":
        i = int(ref.get("i", -1))
        if 0 <= i < len(missiles):
            return missiles[i]
        return None
    return None


def _serialize_weapons(ws: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for w in ws:
        out.append(
            {
                "name": w.name,
                "projectile_name": w.projectile_name,
                "fire_rate": _roundf(w.fire_rate, 6),
                "cooldown": _roundf(w.cooldown, 6),
            }
        )
    return out


def _apply_weapons(g: Any, rows: List[Dict[str, Any]]) -> None:
    by_pn: Dict[str, List[RuntimeWeapon]] = {}
    for w in g.weapons:
        by_pn.setdefault(w.projectile_name, []).append(w)
    used: Set[int] = set()
    for row in rows:
        pn = row.get("projectile_name")
        name = row.get("name")
        pool = by_pn.get(pn) or []
        cand = None
        for w in pool:
            wid = id(w)
            if wid in used:
                continue
            if w.name == name:
                cand = w
                break
        if cand is None:
            for w in pool:
                wid = id(w)
                if wid not in used:
                    cand = w
                    break
        if cand is not None:
            cand.cooldown = float(row.get("cooldown", 0.0))
            used.add(id(cand))


def snapshot_state(
    *,
    tick: int,
    round_idx: int,
    mission: Any,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    ballistics: List[Any],
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    supplies: List[float],
    pd_rof_mult: List[float],
    cg_weapons_free: List[bool],
    control_groups: List[Any],
    fog: Any,
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    seeker_ghosts: List[Any],
    ping_ghost_anchor_labels: Set[str],
    ping_ready_at_ms: int,
    outcome: Optional[str],
    phase: str,
    salvage: float,
    run_total_score: int,
    last_salvage_gain: int,
    store_selected: Optional[str],
    store_hover: Optional[str],
) -> Dict[str, Any]:
    gl = []
    for g in sorted(groups, key=lambda x: (x.side, x.label)):
        gl.append(
            {
                "side": g.side,
                "owner_id": getattr(g, "owner_id", "player"),
                "color_id": int(getattr(g, "color_id", 0)),
                "label": g.label,
                "class_name": g.class_name,
                "x": _roundf(g.x),
                "y": _roundf(g.y),
                "z": _roundf(g.z),
                "max_hp": _roundf(g.max_hp),
                "hp": _roundf(g.hp),
                "speed": _roundf(g.speed),
                "max_range": _roundf(g.max_range),
                "dead": bool(g.dead),
                "waypoint": [ _roundf(g.waypoint[0]), _roundf(g.waypoint[1]) ] if g.waypoint else None,
                "move_pace_key": g.move_pace_key,
                "strike_rally": [ _roundf(g.strike_rally[0]), _roundf(g.strike_rally[1]) ] if g.strike_rally else None,
                "strike_rally_wings": [
                    [ _roundf(t[0]), _roundf(t[1]) ] if t else None for t in g.strike_rally_wings
                ],
                "attack_move": bool(g.attack_move),
                "pd_overheat_streak": _roundf(g.pd_overheat_streak, 6),
                "engagement_timer": _roundf(g.engagement_timer, 6),
                "attack_target": _attack_target_ref(g.attack_target, mission, missiles),
                "render_capital": bool(g.render_capital),
                "hangar_loadout_choice": int(g.hangar_loadout_choice),
                "weapons": _serialize_weapons(g.weapons),
            }
        )
    cl = []
    for c in sorted(crafts, key=lambda x: (x.parent.label, x.label)):
        cl.append(
            {
                "side": c.side,
                "owner_id": getattr(c, "owner_id", getattr(c.parent, "owner_id", "player")),
                "color_id": int(getattr(c, "color_id", getattr(c.parent, "color_id", 0))),
                "label": c.label,
                "parent_label": c.parent.label,
                "class_name": c.class_name,
                "slot_index": int(c.slot_index),
                "squadron_index": int(c.squadron_index),
                "x": _roundf(c.x),
                "y": _roundf(c.y),
                "z": _roundf(c.z),
                "max_hp": _roundf(c.max_hp),
                "hp": _roundf(c.hp),
                "speed": _roundf(c.speed),
                "max_range": _roundf(c.max_range),
                "dead": bool(c.dead),
                "orbit_phase": _roundf(c.orbit_phase, 6),
                "heading": _roundf(c.heading, 6),
                "pd_overheat_streak": _roundf(c.pd_overheat_streak, 6),
                "engagement_timer": _roundf(c.engagement_timer, 6),
                "weapons": _serialize_weapons(c.weapons),
            }
        )
    ml = []
    for m in missiles:
        ml.append(
            {
                "x": _roundf(m.x),
                "y": _roundf(m.y),
                "vx": _roundf(m.vx),
                "vy": _roundf(m.vy),
                "speed": _roundf(m.speed),
                "damage": _roundf(m.damage),
                "turn_rate_rad": _roundf(m.turn_rate_rad, 6),
                "ttl": _roundf(m.ttl, 6),
                "side": m.side,
                "color": [int(m.color[0]), int(m.color[1]), int(m.color[2])],
                "proj_name": m.proj_name,
                "z": _roundf(m.z),
                "target": _attack_target_ref(m.target, mission, missiles),
                "anim_t": _roundf(m.anim_t, 6),
                "launch_speed": _roundf(m.launch_speed, 6),
                "boost_elapsed": _roundf(m.boost_elapsed, 6),
                "intercept_hp": _roundf(m.intercept_hp, 6),
            }
        )
    bl = []
    for s in ballistics:
        bl.append(
            {
                "x": _roundf(s.x),
                "y": _roundf(s.y),
                "z": _roundf(s.z),
                "vx": _roundf(s.vx),
                "vy": _roundf(s.vy),
                "vz": _roundf(s.vz),
                "damage": _roundf(s.damage),
                "side": s.side,
                "proj_name": s.proj_name,
                "age": _roundf(s.age, 6),
            }
        )
    vxs = []
    for s in vfx_sparks:
        vxs.append(
            {
                "x": _roundf(s.x),
                "y": _roundf(s.y),
                "vx": _roundf(s.vx),
                "vy": _roundf(s.vy),
                "ttl": _roundf(s.ttl, 6),
                "max_ttl": _roundf(s.max_ttl, 6),
                "radius": int(s.radius),
                "color": [int(s.color[0]), int(s.color[1]), int(s.color[2])],
            }
        )
    vxb = []
    for b in vfx_beams:
        vxb.append(
            {
                "x0": _roundf(b.x0),
                "y0": _roundf(b.y0),
                "x1": _roundf(b.x1),
                "y1": _roundf(b.y1),
                "ttl": _roundf(b.ttl, 6),
                "max_ttl": _roundf(b.max_ttl, 6),
                "color": [int(b.color[0]), int(b.color[1]), int(b.color[2])],
                "width": int(b.width),
            }
        )
    obj = None
    if mission.objective:
        o = mission.objective
        obj = {
            "x": _roundf(o.x),
            "y": _roundf(o.y),
            "z": _roundf(o.z),
            "hp": _roundf(o.hp),
            "max_hp": _roundf(o.max_hp),
            "radius": _roundf(o.radius),
            "dead": bool(o.dead),
        }
    pods = [
        {
            "x": _roundf(p.x),
            "y": _roundf(p.y),
            "value": int(p.value),
            "collected": bool(p.collected),
        }
        for p in mission.pods
    ]
    obs = [{"x": _roundf(o.x), "y": _roundf(o.y), "r": _roundf(o.r)} for o in mission.obstacles]
    n = FOG_CW * FOG_CH
    ex = "".join("1" if fog.explored[i] else "0" for i in range(min(n, len(fog.explored))))
    vis = "".join("1" if fog.visible[i] else "0" for i in range(min(n, len(fog.visible))))
    pings = [{"x": _roundf(p.x), "y": _roundf(p.y), "ttl": _roundf(p.ttl, 6), "radius": _roundf(p.radius)} for p in active_pings]
    ghosts = [
        {
            "x": _roundf(g.x),
            "y": _roundf(g.y),
            "ttl": _roundf(g.ttl, 6),
            "label": g.label,
            "quality": _roundf(g.quality, 6),
        }
        for g in sensor_ghosts
    ]
    sk = [
        {
            "x": _roundf(g.x),
            "y": _roundf(g.y),
            "ttl": _roundf(g.ttl, 6),
            "label": g.label,
            "quality": _roundf(g.quality, 6),
        }
        for g in seeker_ghosts
    ]
    cg = []
    for row in control_groups:
        if row is None:
            cg.append(None)
        else:
            cg.append(list(row))
    return {
        "snap_version": SNAP_VERSION,
        "tick": int(tick),
        "round_idx": int(round_idx),
        "mission": {
            "kind": mission.kind,
            "mp_pvp": bool(getattr(mission, "mp_pvp", False)),
            "pvp_scrap": {
                str(k): int(v)
                for k, v in (getattr(mission, "pvp_scrap", {}) or {}).items()
                if str(k).strip()
            },
            "pvp_territory": {
                str(k): str(v)
                for k, v in (getattr(mission, "pvp_territory", {}) or {}).items()
                if str(k).strip()
            },
            "pvp_battlegroups": {
                str(k): list(v) if isinstance(v, list) else []
                for k, v in (getattr(mission, "pvp_battlegroups", {}) or {}).items()
                if str(k).strip()
            },
            "objective": obj,
            "pods": pods,
            "reinf_remaining": int(mission.reinf_remaining),
            "reinf_timer": _roundf(mission.reinf_timer, 6),
            "pods_collected": int(mission.pods_collected),
            "pods_required": int(mission.pods_required),
            "enemy_label_serial": int(mission.enemy_label_serial),
            "initial_enemies_spawned": int(mission.initial_enemies_spawned),
            "obstacles": obs,
        },
        "groups": gl,
        "crafts": cl,
        "missiles": ml,
        "ballistics": bl,
        "vfx_sparks": vxs,
        "vfx_beams": vxb,
        "supplies": _roundf(supplies[0], 6) if supplies else 0.0,
        "pd_rof_mult": _roundf(pd_rof_mult[0], 6) if pd_rof_mult else 1.0,
        "cg_weapons_free": [bool(x) for x in cg_weapons_free],
        "control_groups": cg,
        "fog_explored_bits": ex,
        "fog_visible_bits": vis,
        "active_pings": pings,
        "sensor_ghosts": ghosts,
        "seeker_ghosts": sk,
        "ping_anchor_labels": sorted(ping_ghost_anchor_labels),
        "ping_ready_at_ms": int(ping_ready_at_ms),
        "outcome": outcome,
        "phase": phase,
        "salvage": _roundf(salvage, 6),
        "run_total_score": int(run_total_score),
        "last_salvage_gain": int(last_salvage_gain),
        "store_selected": store_selected,
        "store_hover": store_hover,
    }


def apply_snapshot_state(
    *,
    data: dict,
    state: Dict[str, Any],
    mission: Any,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    ballistics: List[Any],
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    supplies: List[float],
    pd_rof_mult: List[float],
    cg_weapons_free: List[bool],
    control_groups: List[Any],
    fog: Any,
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    seeker_ghosts: List[Any],
    ping_ghost_anchor_labels: Set[str],
) -> Tuple[int, Optional[str], str, int, float, int, int, Optional[str], Optional[str]]:
    """Returns tick, outcome, phase, ping_ready_at_ms, salvage, run_total_score, last_salvage_gain, store_sel, store_hov."""
    if int(state.get("snap_version", 0)) != SNAP_VERSION:
        raise ValueError(f"unsupported snap_version {state.get('snap_version')}")
    tick = int(state["tick"])
    if supplies:
        supplies[0] = float(state.get("supplies", 0.0))
    if pd_rof_mult:
        pd_rof_mult[0] = float(state.get("pd_rof_mult", 1.0))
    cw = state.get("cg_weapons_free") or []
    for i in range(min(len(cg_weapons_free), len(cw))):
        cg_weapons_free[i] = bool(cw[i])
    cg = state.get("control_groups") or []
    slots = CONTROL_GROUP_SLOTS
    while len(control_groups) < slots:
        control_groups.append(None)
    control_groups[:] = control_groups[:slots]
    for i in range(slots):
        row = cg[i] if i < len(cg) else None
        control_groups[i] = None if row is None else list(row)

    ms = state["mission"]
    mission.kind = str(ms["kind"])
    mission.mp_pvp = bool(ms.get("mp_pvp", False))
    mission.pvp_scrap = {
        str(k): int(v)
        for k, v in (ms.get("pvp_scrap") or {}).items()
        if str(k).strip()
    }
    mission.pvp_territory = {
        str(k): str(v)
        for k, v in (ms.get("pvp_territory") or {}).items()
        if str(k).strip()
    }
    mission.pvp_battlegroups = {
        str(k): list(v) if isinstance(v, list) else []
        for k, v in (ms.get("pvp_battlegroups") or {}).items()
        if str(k).strip()
    }
    mission.reinf_remaining = int(ms["reinf_remaining"])
    mission.reinf_timer = float(ms["reinf_timer"])
    mission.pods_collected = int(ms["pods_collected"])
    mission.pods_required = int(ms["pods_required"])
    mission.enemy_label_serial = int(ms["enemy_label_serial"])
    mission.initial_enemies_spawned = int(ms["initial_enemies_spawned"])
    if mission.objective and ms.get("objective"):
        o = ms["objective"]
        ob = mission.objective
        ob.x, ob.y, ob.z = float(o["x"]), float(o["y"]), float(o["z"])
        ob.hp, ob.max_hp = float(o["hp"]), float(o["max_hp"])
        ob.radius = float(o["radius"])
        ob.dead = bool(o["dead"])
    mission.pods.clear()
    for p in ms.get("pods") or []:
        mission.pods.append(
            SalvagePod(
                x=float(p["x"]),
                y=float(p["y"]),
                value=int(p.get("value", SALVAGE_POD_VALUE)),
                collected=bool(p.get("collected")),
            )
        )
    mission.obstacles.clear()
    for o in ms.get("obstacles") or []:
        mission.obstacles.append(Asteroid(float(o["x"]), float(o["y"]), float(o["r"])))

    n = FOG_CW * FOG_CH
    ex = state.get("fog_explored_bits") or ""
    vis = state.get("fog_visible_bits") or ""
    for i in range(min(n, len(ex))):
        fog.explored[i] = ex[i] == "1"
    for i in range(min(n, len(vis))):
        fog.visible[i] = vis[i] == "1"

    ping_ghost_anchor_labels.clear()
    ping_ghost_anchor_labels.update(str(x) for x in (state.get("ping_anchor_labels") or []))

    label_group: Dict[str, Any] = {g.label: g for g in groups}

    g_rows = state.get("groups") or []
    seen_g: Set[str] = set()
    for gd in g_rows:
        lab = gd["label"]
        seen_g.add(lab)
        g = label_group.get(lab)
        if g is None:
            g = make_group(
                data,
                gd["side"],
                lab,
                gd["class_name"],
                float(gd["x"]),
                float(gd["y"]),
                owner_id=str(gd.get("owner_id") or "player"),
                color_id=int(gd.get("color_id", 0)),
            )
            groups.append(g)
            label_group[lab] = g
        g.side = gd["side"]
        g.owner_id = str(gd.get("owner_id") or getattr(g, "owner_id", "player"))
        g.color_id = int(max(0, min(int(gd.get("color_id", getattr(g, "color_id", 0))), 5)))
        g.class_name = gd["class_name"]
        g.x, g.y, g.z = float(gd["x"]), float(gd["y"]), float(gd["z"])
        g.max_hp, g.hp = float(gd["max_hp"]), float(gd["hp"])
        g.speed, g.max_range = float(gd["speed"]), float(gd["max_range"])
        g.dead = bool(gd["dead"])
        wp = gd.get("waypoint")
        g.waypoint = (float(wp[0]), float(wp[1])) if wp else None
        g.move_pace_key = gd.get("move_pace_key")
        sr = gd.get("strike_rally")
        g.strike_rally = (float(sr[0]), float(sr[1])) if sr else None
        wings = gd.get("strike_rally_wings") or []
        while len(g.strike_rally_wings) < len(wings):
            g.strike_rally_wings.append(None)
        g.strike_rally_wings[:] = g.strike_rally_wings[: len(wings)]
        for i, t in enumerate(wings):
            g.strike_rally_wings[i] = (float(t[0]), float(t[1])) if t else None
        g.attack_move = bool(gd.get("attack_move"))
        g.pd_overheat_streak = float(gd.get("pd_overheat_streak", 0.0))
        g.engagement_timer = float(gd.get("engagement_timer", 0.0))
        g.render_capital = bool(gd.get("render_capital"))
        g.hangar_loadout_choice = int(gd.get("hangar_loadout_choice", 0))
        _apply_weapons(g, gd.get("weapons") or [])

    groups[:] = [g for g in groups if g.label in seen_g]
    label_group = {g.label: g for g in groups}

    label_craft: Dict[str, Any] = {c.label: c for c in crafts}
    c_rows = state.get("crafts") or []
    seen_c: Set[str] = set()
    for cd in c_rows:
        lab = cd["label"]
        seen_c.add(lab)
        parent = label_group.get(cd["parent_label"])
        if parent is None:
            continue
        c = label_craft.get(lab)
        if c is None:
            csc = ship_class_by_name(data, cd["class_name"])
            spd = (22.0 + (float(csc["speed"]) / 100.0) * 95.0) * SPEED_SCALE
            mr = class_max_weapon_range(data, csc)
            c = Craft(
                side=cd["side"],
                owner_id=str(cd.get("owner_id") or getattr(parent, "owner_id", "player")),
                color_id=int(cd.get("color_id", getattr(parent, "color_id", 0))),
                label=lab,
                class_name=cd["class_name"],
                parent=parent,
                slot_index=int(cd["slot_index"]),
                squadron_index=int(cd["squadron_index"]),
                x=float(cd["x"]),
                y=float(cd["y"]),
                max_hp=float(cd["max_hp"]),
                hp=float(cd["hp"]),
                speed=spd,
                max_range=mr,
                weapons=we.build_runtime_weapons(data, csc),
                z=float(cd["z"]),
            )
            crafts.append(c)
            label_craft[lab] = c
        c.parent = parent
        c.side = cd["side"]
        c.owner_id = str(cd.get("owner_id") or getattr(parent, "owner_id", "player"))
        c.color_id = int(max(0, min(int(cd.get("color_id", getattr(parent, "color_id", 0))), 5)))
        c.class_name = cd["class_name"]
        c.slot_index = int(cd["slot_index"])
        c.squadron_index = int(cd["squadron_index"])
        c.x, c.y, c.z = float(cd["x"]), float(cd["y"]), float(cd["z"])
        c.max_hp, c.hp = float(cd["max_hp"]), float(cd["hp"])
        c.speed = float(cd["speed"])
        c.max_range = float(cd["max_range"])
        c.dead = bool(cd["dead"])
        c.orbit_phase = float(cd.get("orbit_phase", 0.0))
        c.heading = float(cd.get("heading", 0.0))
        c.pd_overheat_streak = float(cd.get("pd_overheat_streak", 0.0))
        c.engagement_timer = float(cd.get("engagement_timer", 0.0))
        _apply_weapons(c, cd.get("weapons") or [])

    crafts[:] = [c for c in crafts if c.label in seen_c]

    label_group = {g.label: g for g in groups}
    label_craft = {c.label: c for c in crafts}

    missiles.clear()
    m_rows = state.get("missiles") or []
    for md in m_rows:
        col = md["color"]
        missiles.append(
            Missile(
                x=float(md["x"]),
                y=float(md["y"]),
                vx=float(md["vx"]),
                vy=float(md["vy"]),
                speed=float(md["speed"]),
                damage=float(md["damage"]),
                turn_rate_rad=float(md["turn_rate_rad"]),
                ttl=float(md["ttl"]),
                side=md["side"],
                color=(int(col[0]), int(col[1]), int(col[2])),
                proj_name=md["proj_name"],
                z=float(md["z"]),
                target=None,
                anim_t=float(md.get("anim_t", 0.0)),
                launch_speed=float(md.get("launch_speed", -1.0)),
                boost_elapsed=float(md.get("boost_elapsed", 0.0)),
                intercept_hp=float(md.get("intercept_hp", 1.0)),
            )
        )
    for md, m in zip(m_rows, missiles):
        m.target = _resolve_attack_target(md.get("target"), mission, label_group, label_craft, missiles)

    ballistics.clear()
    for bd in state.get("ballistics") or []:
        ballistics.append(
            BallisticSlug(
                x=float(bd["x"]),
                y=float(bd["y"]),
                z=float(bd["z"]),
                vx=float(bd["vx"]),
                vy=float(bd["vy"]),
                vz=float(bd["vz"]),
                damage=float(bd["damage"]),
                side=bd["side"],
                proj_name=bd["proj_name"],
                age=float(bd.get("age", 0.0)),
            )
        )

    vfx_sparks.clear()
    for s in state.get("vfx_sparks") or []:
        col = s["color"]
        vfx_sparks.append(
            VFXSpark(
                float(s["x"]),
                float(s["y"]),
                float(s["vx"]),
                float(s["vy"]),
                float(s["ttl"]),
                float(s["max_ttl"]),
                int(s["radius"]),
                (int(col[0]), int(col[1]), int(col[2])),
            )
        )
    vfx_beams.clear()
    for b in state.get("vfx_beams") or []:
        col = b["color"]
        vfx_beams.append(
            VFXBeam(
                float(b["x0"]),
                float(b["y0"]),
                float(b["x1"]),
                float(b["y1"]),
                float(b["ttl"]),
                float(b["max_ttl"]),
                (int(col[0]), int(col[1]), int(col[2])),
                int(b["width"]),
            )
        )

    for g in groups:
        g.attack_target = None
    for gd in g_rows:
        g = label_group.get(gd["label"])
        if g:
            g.attack_target = _resolve_attack_target(gd.get("attack_target"), mission, label_group, label_craft, missiles)

    active_pings.clear()
    for p in state.get("active_pings") or []:
        active_pings.append(
            ActivePing(
                x=float(p["x"]),
                y=float(p["y"]),
                ttl=float(p["ttl"]),
                radius=float(p["radius"]),
            )
        )
    sensor_ghosts.clear()
    for g in state.get("sensor_ghosts") or []:
        sensor_ghosts.append(
            SensorGhost(
                x=float(g["x"]),
                y=float(g["y"]),
                ttl=float(g["ttl"]),
                label=str(g.get("label", "")),
                quality=float(g.get("quality", 0.5)),
            )
        )
    seeker_ghosts.clear()
    for g in state.get("seeker_ghosts") or []:
        seeker_ghosts.append(
            SensorGhost(
                x=float(g["x"]),
                y=float(g["y"]),
                ttl=float(g["ttl"]),
                label=str(g.get("label", "")),
                quality=float(g.get("quality", 0.5)),
            )
        )

    return (
        tick,
        state.get("outcome"),
        str(state.get("phase", "combat")),
        int(state.get("ping_ready_at_ms", 0)),
        float(state.get("salvage", 0.0)),
        int(state.get("run_total_score", 0)),
        int(state.get("last_salvage_gain", 0)),
        state.get("store_selected"),
        state.get("store_hover"),
    )


# ════════════════════════════════════════════════════════════════════════════
#  Combat simulation tick
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class CombatSimHooks:
    """Per-tick callbacks for combat sim (extend for command/damage streams later)."""

    on_player_hull_hit: Callable[[Any], None]


@dataclass
class CombatAudioEvents:
    """Death notifications for the client to play (preserves original ordering)."""

    player_caps_lost: List[Tuple[str, bool]] = field(default_factory=list)  # (label, render_capital)
    player_crafts_lost: int = 0
    enemy_cap_losses: int = 0  # enemy capitals with render_capital
    enemy_craft_losses: int = 0


@dataclass
class CombatFlowDelta:
    """Phase/outcome changes after this tick (apply in the game loop)."""

    outcome: str
    phase: str
    store_selected: Optional[str] = None
    store_hover: Optional[str] = None
    run_total_score_add: int = 0
    salvage_gain: int = 0
    last_salvage_gain: int = 0


@dataclass
class CombatStepResult:
    death_audio: CombatAudioEvents
    flow: Optional[CombatFlowDelta] = None


def apply_combat_death_audio(
    events: CombatAudioEvents,
    audio: Any,
    now_ms: int,
    *,
    tts_last_player_cap_loss_tts: int,
    tts_last_enemy_kill_tts: int,
    tts_player_cap_loss_gap_ms: int,
    tts_enemy_kill_gap_ms: int,
) -> Tuple[int, int]:
    """Play ship/TTS cues matching the former inline combat loop; returns updated throttle timestamps."""
    pc, ek = tts_last_player_cap_loss_tts, tts_last_enemy_kill_tts
    for _label, render_capital in events.player_caps_lost:
        audio.play_ship_destroyed()
        if render_capital and now_ms - pc >= tts_player_cap_loss_gap_ms:
            audio.speak_voice("Capital ship lost.")
            pc = now_ms
    for _ in range(events.player_crafts_lost):
        audio.play_ship_destroyed()
    for _ in range(events.enemy_cap_losses):
        if now_ms - ek >= tts_enemy_kill_gap_ms:
            audio.speak_voice("Enemy ship destroyed.")
            ek = now_ms
    for _ in range(events.enemy_craft_losses):
        if now_ms - ek >= tts_enemy_kill_gap_ms:
            audio.speak_voice("Enemy ship destroyed.")
            ek = now_ms
    return pc, ek


def step_combat_frame(
    *,
    data: dict,
    dt: float,
    round_idx: int,
    mission: Any,
    groups: List[Any],
    crafts: List[Any],
    fog: Any,
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    ping_ghost_anchor_labels: Any,
    seeker_ghosts: List[Any],
    control_groups: List[Any],
    cg_weapons_free: List[bool],
    missiles: List[Any],
    supplies: List[float],
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    ballistics: List[Any],
    pd_rof_mult: List[float],
    hooks: CombatSimHooks,
    phase: str,
    outcome: Optional[str],
) -> CombatStepResult:
    death = CombatAudioEvents()
    flow: Optional[CombatFlowDelta] = None
    hull_hit = hooks.on_player_hull_hit

    mission.reinf_timer -= dt
    if mission.reinf_timer <= 0 and mission.reinf_remaining > 0:
        spawn_enemy_reinforcement(
            data,
            groups,
            mission,
            random.Random(round_seed(round_idx) + mission.enemy_label_serial * 131),
        )
        mission.reinf_remaining -= 1
        mission.reinf_timer = REINF_INTERVAL_BASE + random.uniform(3.5, 13.0)

    collect_salvage_pods(mission, groups)

    strike_obj = mission.objective if mission.kind == "strike" else None

    players_g = [g for g in groups if g.side == "player"]
    player_caps_move = [g for g in players_g if not g.dead and g.render_capital]

    for g in players_g:
        if g.dead:
            continue
        move_group(g, dt, player_caps_move)

    separate_player_capitals(groups, dt, mp_pvp=bool(getattr(mission, "mp_pvp", False)))

    for g in groups:
        if g.side != "enemy" or g.dead:
            continue
        enemy_ai(g, players_g, dt)

    update_craft_positions(crafts, dt)

    resolve_all_units_against_asteroids(groups, crafts, mission.obstacles)

    tick_player_engagement_timers(groups, crafts, dt)

    prune_attack_targets(groups, mission)

    update_fog_of_war(fog, groups, crafts, active_pings)
    for p in active_pings:
        p.ttl -= dt
    active_pings[:] = [p for p in active_pings if p.ttl > 0]
    cull_sensor_ghosts_if_ping_anchors_lost(groups, crafts, sensor_ghosts, ping_ghost_anchor_labels)
    for gh in sensor_ghosts:
        gh.ttl -= dt
    sensor_ghosts[:] = [g for g in sensor_ghosts if g.ttl > 0]
    if not sensor_ghosts:
        ping_ghost_anchor_labels.clear()

    obs = mission.obstacles
    for g in groups:
        if g.dead:
            continue
        update_pd_overheat_streak(g, dt, data, missiles, pd_rof_mult[0])
        w_auth = g.side != "player" or player_capital_may_fire_weapons(
            g, control_groups, cg_weapons_free, mp_pvp=bool(getattr(mission, "mp_pvp", False))
        )
        try_fire_weapons(
            data,
            g.x,
            g.y,
            g.z,
            g.side,
            g.weapons,
            g.max_range,
            groups,
            crafts,
            missiles,
            supplies,
            dt,
            vfx_sparks,
            vfx_beams,
            ballistics,
            pd_rof_mult[0],
            strike_obj,
            pd_perf_mult=pd_overheat_rof_multiplier(g.pd_overheat_streak),
            launcher_speed=g.speed,
            weapons_authorized=w_auth,
            player_damage_hook=hull_hit,
            prefer_attack_target=g.attack_target,
            obstacles=obs,
            fog=fog,
            launcher_owner=getattr(g, "owner_id", None),
            mp_pvp=bool(getattr(mission, "mp_pvp", False)),
            launcher=g,
        )
    for c in crafts:
        if c.dead:
            continue
        update_pd_overheat_streak(c, dt, data, missiles, pd_rof_mult[0])
        w_auth = c.side != "player" or player_craft_may_fire_weapons(
            c, control_groups, cg_weapons_free, mp_pvp=bool(getattr(mission, "mp_pvp", False))
        )
        try_fire_weapons(
            data,
            c.x,
            c.y,
            c.z,
            c.side,
            c.weapons,
            c.max_range,
            groups,
            crafts,
            missiles,
            supplies,
            dt,
            vfx_sparks,
            vfx_beams,
            ballistics,
            pd_rof_mult[0],
            None,
            pd_perf_mult=pd_overheat_rof_multiplier(c.pd_overheat_streak),
            launcher_speed=c.speed,
            weapons_authorized=w_auth,
            player_damage_hook=hull_hit,
            prefer_attack_target=c.parent.attack_target,
            obstacles=obs,
            fog=fog,
            launcher_owner=getattr(c, "owner_id", None),
            mp_pvp=bool(getattr(mission, "mp_pvp", False)),
            launcher=c,
        )

    update_vfx_sparks(vfx_sparks, dt)
    update_vfx_beams(vfx_beams, dt)
    update_ballistics(
        ballistics,
        dt,
        groups,
        crafts,
        missiles,
        supplies,
        vfx_sparks,
        strike_obj,
        player_damage_hook=hull_hit,
        obstacles=obs,
    )
    update_missiles(
        missiles,
        dt,
        groups,
        crafts,
        supplies,
        strike_obj,
        data,
        player_damage_hook=hull_hit,
        obstacles=obs,
        vfx_sparks=vfx_sparks,
        fog=fog,
    )
    rebuild_seeker_lock_ghosts(fog, missiles, mission.obstacles, seeker_ghosts)
    player_cap_was_alive = {id(g): (not g.dead) for g in groups if g.side == "player"}
    player_craft_was_alive = {id(c): (not c.dead) for c in crafts if c.side == "player"}
    enemy_cap_was_alive = {id(g): (not g.dead) for g in groups if g.side == "enemy" and g.render_capital}
    enemy_craft_was_alive = {id(c): (not c.dead) for c in crafts if c.side == "enemy"}
    finalize_deaths(groups, crafts)
    finalize_objective_if_dead(mission.objective)

    for g in groups:
        if g.side == "player" and player_cap_was_alive.get(id(g)) and g.dead:
            death.player_caps_lost.append((g.label, bool(g.render_capital)))
    for c in crafts:
        if c.side == "player" and player_craft_was_alive.get(id(c)) and c.dead:
            death.player_crafts_lost += 1
    for g in groups:
        if g.side == "enemy" and enemy_cap_was_alive.get(id(g)) and g.dead and g.render_capital:
            death.enemy_cap_losses += 1
    for c in crafts:
        if c.side == "enemy" and enemy_craft_was_alive.get(id(c)) and c.dead:
            death.enemy_craft_losses += 1

    supplies[0] = max(0.0, supplies[0])

    alive_player_cap = [g for g in groups if g.side == "player" and not g.dead]
    if flow is None and bool(getattr(mission, "mp_pvp", False)):
        owners_alive = sorted(
            {
                str(getattr(g, "owner_id", "")).strip()
                for g in alive_player_cap
                if getattr(g, "render_capital", False) and str(getattr(g, "owner_id", "")).strip()
            }
        )
        if len(owners_alive) <= 1:
            if owners_alive:
                out_str = f"pvp victory — {owners_alive[0]} controls the field"
            else:
                out_str = "pvp draw — all fleets destroyed"
            flow = CombatFlowDelta(
                outcome=out_str,
                phase="debrief",
                store_selected=None,
                store_hover=None,
                run_total_score_add=0,
                salvage_gain=0,
                last_salvage_gain=0,
            )
    ex_zone = extract_rect_world()
    if flow is None and not alive_player_cap:
        flow = CombatFlowDelta(outcome="campaign over — fleet lost", phase="gameover")
    elif flow is None and (
        alive_player_cap
        and mission_allows_extract(mission)
        and all(ex_zone.collidepoint(g.x, g.y) for g in alive_player_cap)
    ):
        total = sum(g.hp / g.max_hp for g in alive_player_cap) / len(alive_player_cap)
        round_score = int(supplies[0] * 12 + total * 520 + mission.enemy_label_serial * 18)
        salvage_gain = compute_mission_salvage_reward(mission, supplies[0], total)
        tag = "STRIKE" if mission.kind == "strike" else ("PVP" if mission.kind == "pvp" else "SALVAGE")
        out_str = f"round {round_idx} ({tag}) cleared  +{salvage_gain} salvage  (score +{round_score})"
        flow = CombatFlowDelta(
            outcome=out_str,
            phase="debrief",
            store_selected=None,
            store_hover=None,
            run_total_score_add=round_score,
            salvage_gain=salvage_gain,
            last_salvage_gain=salvage_gain,
        )

    if flow is None and phase == "combat" and supplies[0] <= 0 and not outcome:
        flow = CombatFlowDelta(outcome="campaign over — supplies exhausted", phase="gameover")

    return CombatStepResult(death_audio=death, flow=flow)


# ════════════════════════════════════════════════════════════════════════════
#  MP spawn layout
# ════════════════════════════════════════════════════════════════════════════

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


def normalize_mp_player_order(players: Iterable[str]) -> List[str]:
    """Case-insensitive sort so host, clients, and headless agree on spawn indices."""
    return sorted((str(p)[:48] for p in players if str(p).strip()), key=lambda s: s.lower())[:8]


# ════════════════════════════════════════════════════════════════════════════
#  Fleet management
# ════════════════════════════════════════════════════════════════════════════


def sync_loadout_choice_map_for_group(
    data: dict, g: Group, choice_map: Dict[Tuple[str, int], int]
) -> None:
    """Align per-row choice indices with the group's current weapons (shared choice_sets, etc.)."""
    sc = ship_class_by_name(data, g.class_name)
    opts = weapon_loadout_options_expanded(data, sc)
    for si, slot in enumerate(opts):
        wi = int(slot["weapon_index"])
        if wi < 0 or wi >= len(g.weapons):
            continue
        rw = g.weapons[wi]
        choices = slot["choices"]
        best_i = 0
        for ci, ch in enumerate(choices):
            name, pn, fr = resolve_weapon_entry(data, ch)
            if (
                pn == rw.projectile_name
                and abs(fr - rw.fire_rate) < 1e-4
                and name == rw.name
            ):
                best_i = ci
                break
        else:
            for ci, ch in enumerate(choices):
                name, pn, fr = resolve_weapon_entry(data, ch)
                if pn == rw.projectile_name and abs(fr - rw.fire_rate) < 1e-4:
                    best_i = ci
                    break
        choice_map[(g.label, si)] = best_i


def group_max_range_from_weapons(data: dict, weapons: List[RuntimeWeapon]) -> float:
    if not weapons:
        return 120.0
    return max(weapon_range(data, {"projectile": w.projectile_name}) for w in weapons)


def deployment_cost_for_class(data: dict, class_name: str) -> int:
    sc = ship_class_by_name(data, class_name)
    v = sc.get("deployment_cost")
    if v is not None:
        return int(v)
    if sc.get("render") == "capital":
        return 72
    return 0


def purge_loadout_choices_for_label(choice_map: Dict[Tuple[str, int], int], label: str) -> None:
    for k in list(choice_map.keys()):
        if k[0] == label:
            del choice_map[k]


def apply_deployment_weapon_choice(
    data: dict,
    g: Group,
    loadout_slot_i: int,
    new_choice_i: int,
    choice_map: Dict[Tuple[str, int], int],
    deployment_scrap: List[int],
) -> bool:
    sc = ship_class_by_name(data, g.class_name)
    opts = weapon_loadout_options_expanded(data, sc)
    if loadout_slot_i < 0 or loadout_slot_i >= len(opts):
        return False
    slot = opts[loadout_slot_i]
    choices = slot["choices"]
    if new_choice_i < 0 or new_choice_i >= len(choices):
        return False
    key = (g.label, loadout_slot_i)
    cur_i = choice_map.get(key, 0)
    if new_choice_i == cur_i:
        return True
    old_c = int(choices[cur_i].get("scrap_cost", 0))
    new_c = int(choices[new_choice_i].get("scrap_cost", 0))
    net_scrap = new_c - old_c
    if net_scrap > 0 and deployment_scrap[0] < net_scrap:
        return False
    wi = int(slot["weapon_index"])
    if wi < 0 or wi >= len(g.weapons):
        return False
    deployment_scrap[0] -= net_scrap
    choice_map[key] = new_choice_i
    ch = choices[new_choice_i]
    wn, pn, fr = resolve_weapon_entry(data, ch)
    g.weapons[wi] = RuntimeWeapon(
        name=wn,
        projectile_name=pn,
        fire_rate=float(fr),
        cooldown=0.0,
    )
    g.max_range = group_max_range_from_weapons(data, g.weapons)
    return True


def loadout_try_add_capital(
    data: dict,
    preview_groups: List[Group],
    preview_crafts: List[Craft],
    class_name: str,
    deployment_scrap: List[int],
    choice_map: Dict[Tuple[str, int], int],
) -> bool:
    if player_capital_count(preview_groups) >= MAX_PLAYER_CAPITALS:
        return False
    cost = deployment_cost_for_class(data, class_name)
    if deployment_scrap[0] < cost:
        return False
    deployment_scrap[0] -= cost
    recruit_player_capital(
        data,
        preview_groups,
        preview_crafts,
        class_name,
        control_groups=None,
        loadout_choice_map=choice_map,
    )
    return True


def loadout_try_remove_capital(
    data: dict,
    preview_groups: List[Group],
    preview_crafts: List[Craft],
    g: Group,
    deployment_scrap: List[int],
    choice_map: Dict[Tuple[str, int], int],
) -> bool:
    if player_capital_count(preview_groups) <= DEPLOYMENT_MIN_CAPITALS:
        return False
    if g not in preview_groups:
        return False
    deployment_scrap[0] += deployment_cost_for_class(data, g.class_name)
    purge_loadout_choices_for_label(choice_map, g.label)
    preview_groups[:] = [x for x in preview_groups if x is not g]
    preview_crafts[:] = [c for c in preview_crafts if c.parent is not g]
    return True


def replace_carrier_hangar_crafts(data: dict, carrier: Group, crafts: List[Craft]) -> None:
    """Drop strike craft for this carrier and respawn from current hangar preset."""
    crafts[:] = [c for c in crafts if c.parent is not carrier]
    crafts.extend(spawn_hangar_crafts(data, carrier))


def apply_carrier_hangar_preset(
    data: dict,
    carrier: Group,
    new_idx: int,
    crafts: List[Craft],
    deployment_scrap: List[int],
) -> bool:
    if carrier.class_name != "Carrier":
        return False
    sc = ship_class_by_name(data, carrier.class_name)
    presets = (sc.get("hangar") or {}).get("loadout_presets") or []
    if not presets or new_idx < 0 or new_idx >= len(presets):
        return False
    old_i = max(0, min(int(carrier.hangar_loadout_choice), len(presets) - 1))
    if new_idx == old_i:
        return True
    old_c = int(presets[old_i].get("scrap_cost", 0))
    new_c = int(presets[new_idx].get("scrap_cost", 0))
    net_scrap = new_c - old_c
    if net_scrap > 0 and deployment_scrap[0] < net_scrap:
        return False
    deployment_scrap[0] -= net_scrap
    carrier.hangar_loadout_choice = new_idx
    replace_carrier_hangar_crafts(data, carrier, crafts)
    return True


def snap_strike_crafts_to_carriers(crafts: List[Craft]) -> None:
    """Place strike craft at their parent carrier (orbit updates next tick)."""
    for c in crafts:
        if c.dead or c.side != "player" or c.parent.dead:
            continue
        p = c.parent
        c.x = p.x
        c.y = p.y
        c.z = p.z + (c.slot_index % 5) * 3.5
        c.orbit_phase = c.slot_index * 0.9


def export_player_fleet_design(groups: List[Group]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for g in groups:
        if g.side == "player" and g.render_capital and not g.dead:
            rows.append({"class_name": g.class_name, "label": g.label})
    return rows


def reset_player_spawn_positions(groups: List[Group], crafts: List[Craft]) -> None:
    ax, ay = deploy_anchor_xy()
    layout = {
        "CV-1": (ax - 200, ay),
        "DD-1": (ax + 30, ay + 28),
        "CG-1": (ax + 230, ay - 12),
        "FF-1": (ax - 360, ay - 6),
    }
    player_caps = [g for g in groups if g.side == "player" and not g.dead and g.render_capital]
    for g in player_caps:
        if g.label in layout:
            g.x, g.y = layout[g.label]
            g.waypoint = None
    extras = [g for g in player_caps if g.label not in layout]
    for i, g in enumerate(extras):
        g.x = ax - 420 + (i % 6) * 150.0
        g.y = ay + 36 + (i // 6) * 48.0
        g.waypoint = None
    snap_strike_crafts_to_carriers(crafts)


def reset_mp_fleets_for_lobby(
    groups: List[Group],
    crafts: List[Craft],
    *,
    mp_mode_coop: bool,
    roster_names: Optional[List[str]] = None,
) -> None:
    """Spread surviving capitals by owner for MP lobby preview (labels are prefixed, not CV-1)."""
    owners_caps: Dict[str, List[Group]] = {}
    for g in groups:
        if g.side == "player" and not g.dead and g.render_capital:
            oid = str(getattr(g, "owner_id", "")).strip() or "player"
            owners_caps.setdefault(oid, []).append(g)
    if roster_names:
        ordered = [n for n in roster_names if n in owners_caps]
        for oid in sorted(owners_caps.keys(), key=lambda s: s.lower()):
            if oid not in ordered:
                ordered.append(oid)
    else:
        ordered = sorted(owners_caps.keys(), key=lambda s: s.lower())
    ordered = ordered[:8]
    ax0, ay0 = deploy_anchor_xy()
    n_pl = max(1, min(len(ordered), 8))
    for i, owner in enumerate(ordered):
        caps = sorted(owners_caps.get(owner, []), key=lambda g: g.label)
        if mp_mode_coop:
            ax, ay = coop_player_spawn_anchor(i, ax0, ay0)
        else:
            ax, ay = pvp_player_spawn_anchor(i, n_pl)
        for j, g in enumerate(caps):
            g.x = ax - 320 + (j % 6) * 150.0
            g.y = ay + (j // 6) * 56.0
            g.waypoint = None
    snap_strike_crafts_to_carriers(crafts)


def player_capital_count(groups: List[Group]) -> int:
    return sum(1 for g in groups if g.side == "player" and not g.dead and g.render_capital)


def all_player_capital_labels(groups: List[Group]) -> List[str]:
    return [g.label for g in groups if g.side == "player" and not g.dead and g.render_capital]


def next_recruit_label(groups: List[Group], class_name: str) -> str:
    prefix = RECRUIT_LABEL_PREFIX[class_name]
    nums: List[int] = []
    for g in groups:
        if g.side != "player" or g.class_name != class_name:
            continue
        if g.label.startswith(prefix + "-"):
            try:
                nums.append(int(g.label.split("-", 1)[1]))
            except ValueError:
                pass
    n = max(nums) + 1 if nums else 1
    return f"{prefix}-{n}"


def recruit_spawn_xy(groups: List[Group]) -> Tuple[float, float]:
    ax, ay = deploy_anchor_xy()
    n = sum(1 for g in groups if g.side == "player" and not g.dead and g.render_capital)
    x = ax - 420 + (n % 6) * 150.0
    y = ay + 36 + (n // 6) * 48.0
    return x, y


def recruit_player_capital(
    data: dict,
    groups: List[Group],
    crafts: List[Craft],
    class_name: str,
    control_groups: Optional[List[Optional[List[str]]]] = None,
    loadout_choice_map: Optional[Dict[Tuple[str, int], int]] = None,
) -> None:
    lbl = next_recruit_label(groups, class_name)
    x, y = recruit_spawn_xy(groups)
    ng = make_group(data, "player", lbl, class_name, x, y)
    groups.append(ng)
    sc = ship_class_by_name(data, class_name)
    if sc.get("hangar"):
        crafts.extend(spawn_hangar_crafts(data, ng))
    if loadout_choice_map is not None and sc.get("weapon_loadout_options"):
        sync_loadout_choice_map_for_group(data, ng, loadout_choice_map)
    if control_groups is not None:
        if control_groups[0] is None:
            control_groups[0] = [lbl]
        elif lbl not in control_groups[0]:
            control_groups[0].append(lbl)


def loadout_player_capitals_sorted(groups: List[Group]) -> List[Group]:
    caps = [g for g in groups if g.side == "player" and not g.dead and g.render_capital]
    return sorted(caps, key=lambda g: (g.label, g.class_name))


# ════════════════════════════════════════════════════════════════════════════
#  Debrief economy
# ════════════════════════════════════════════════════════════════════════════


def full_repair_and_revive_wing(groups: List[Group], crafts: List[Craft]) -> None:
    for g in groups:
        if g.side == "player" and not g.dead:
            g.hp = g.max_hp
    for c in crafts:
        if c.side != "player" or c.parent.dead:
            continue
        c.dead = False
        c.hp = c.max_hp
        c.x = c.parent.x
        c.y = c.parent.y


def apply_bulkhead_bonus(groups: List[Group], crafts: List[Craft]) -> None:
    for g in groups:
        if g.side == "player" and not g.dead:
            add = g.max_hp * BULKHEAD_HP_FRAC
            g.max_hp += add
            g.hp += add
    for c in crafts:
        if c.side == "player" and not c.dead:
            add = c.max_hp * BULKHEAD_HP_FRAC
            c.max_hp += add
            c.hp += add


def attempt_debrief_purchase(
    item_id: str,
    data: dict,
    groups: List[Group],
    crafts: List[Craft],
    salvage: List[int],
    supplies: List[float],
    pd_rof_mult: List[float],
    ciws_stacks: List[int],
    bulk_stacks: List[int],
    control_groups: List[Optional[List[str]]],
) -> bool:
    cap_n = player_capital_count(groups)
    if item_id in SHIP_CLASS_BY_STORE_ID:
        cost = SHIP_COST_BY_STORE_ID[item_id]
        if salvage[0] < cost or cap_n >= MAX_PLAYER_CAPITALS:
            return False
        salvage[0] -= cost
        recruit_player_capital(data, groups, crafts, SHIP_CLASS_BY_STORE_ID[item_id], control_groups)
        return True
    if item_id == "upg_repair":
        if salvage[0] < COST_REPAIR:
            return False
        salvage[0] -= COST_REPAIR
        full_repair_and_revive_wing(groups, crafts)
        return True
    if item_id == "upg_resupply":
        if salvage[0] < COST_RESUPPLY:
            return False
        salvage[0] -= COST_RESUPPLY
        supplies[0] = min(100.0, supplies[0] + 28.0)
        return True
    if item_id == "upg_ciws":
        if salvage[0] < COST_CIWS or ciws_stacks[0] >= MAX_CIWS_STACKS:
            return False
        salvage[0] -= COST_CIWS
        ciws_stacks[0] += 1
        pd_rof_mult[0] += CIWS_ROF_BONUS
        return True
    if item_id == "upg_bulkhead":
        if salvage[0] < COST_BULKHEAD or bulk_stacks[0] >= MAX_BULKHEAD_STACKS:
            return False
        salvage[0] -= COST_BULKHEAD
        bulk_stacks[0] += 1
        apply_bulkhead_bonus(groups, crafts)
        return True
    if item_id == "upg_stores":
        if salvage[0] < COST_LIGHT_RESUPPLY or supplies[0] >= 100.0:
            return False
        salvage[0] -= COST_LIGHT_RESUPPLY
        supplies[0] = min(100.0, supplies[0] + LIGHT_RESUPPLY_AMT)
        return True
    return False


def debrief_item_blocked_reason(
    item_id: str,
    groups: List[Group],
    salvage: List[int],
    supplies: List[float],
    ciws_stacks: List[int],
    bulk_stacks: List[int],
) -> Optional[str]:
    cap_n = player_capital_count(groups)
    if item_id in SHIP_CLASS_BY_STORE_ID:
        cost = SHIP_COST_BY_STORE_ID[item_id]
        if cap_n >= MAX_PLAYER_CAPITALS:
            return "Fleet capital limit reached."
        if salvage[0] < cost:
            return f"Need {cost} salvage (have {salvage[0]})."
        return None
    if item_id == "upg_repair":
        return None if salvage[0] >= COST_REPAIR else f"Need {COST_REPAIR} salvage."
    if item_id == "upg_resupply":
        return None if salvage[0] >= COST_RESUPPLY else f"Need {COST_RESUPPLY} salvage."
    if item_id == "upg_ciws":
        if ciws_stacks[0] >= MAX_CIWS_STACKS:
            return "CIWS tuning maxed."
        return None if salvage[0] >= COST_CIWS else f"Need {COST_CIWS} salvage."
    if item_id == "upg_bulkhead":
        if bulk_stacks[0] >= MAX_BULKHEAD_STACKS:
            return "Bulkhead refits maxed."
        return None if salvage[0] >= COST_BULKHEAD else f"Need {COST_BULKHEAD} salvage."
    if item_id == "upg_stores":
        if supplies[0] >= 100.0:
            return "Supplies already full."
        return None if salvage[0] >= COST_LIGHT_RESUPPLY else f"Need {COST_LIGHT_RESUPPLY} salvage."
    return "Unknown item."


def debrief_info_lines(
    item_id: Optional[str],
    data: dict,
    groups: List[Group],
    crafts: List[Craft],
    salvage: List[int],
    supplies: List[float],
    pd_rof_mult: List[float],
    ciws_stacks: List[int],
    bulk_stacks: List[int],
    cap_n: int,
) -> List[str]:
    if not item_id:
        return [
            "Selection",
            "",
            "Hover any row for a live summary.",
            "Click to pin that row as your",
            "active choice.",
            "",
            "ENTER or Purchase bar buys the",
            "pinned row, or the row under",
            "the mouse if nothing is pinned.",
            "",
            "Hotkeys: 1–5 ships, 6–0 upgrades",
            "(same order as listed).",
            "SPACE — deploy next engagement",
        ]
    lines: List[str] = []
    reason = debrief_item_blocked_reason(item_id, groups, salvage, supplies, ciws_stacks, bulk_stacks)
    if item_id in SHIP_CLASS_BY_STORE_ID:
        cname = SHIP_CLASS_BY_STORE_ID[item_id]
        cost = SHIP_COST_BY_STORE_ID[item_id]
        sc = ship_class_by_name(data, cname)
        lines = [
            cname.upper(),
            sc.get("description", ""),
            "",
            f"Hull (design): {sc.get('hull_hp', '—')}",
            f"Role: {sc.get('role', '—')}",
            f"Cost: {cost} salvage",
            f"Fleet capitals: {cap_n}/{MAX_PLAYER_CAPITALS}",
            f"Bank: {salvage[0]} salvage",
        ]
        hangar = sc.get("hangar") or {}
        sq = hangar.get("squadrons") or []
        if sq:
            bits = [f"{s.get('count', 0)}× {s.get('class', '?')}" for s in sq]
            lines.extend(["", "Hangar: " + ", ".join(bits)])
        wps = sc.get("weapons") or []
        if wps:
            lines.append("")
            lines.append("Weapons (JSON):")
            for w in wps[:6]:
                try:
                    wn, wp, _ = resolve_weapon_entry(data, w)
                    lines.append(f"  • {wn}: {wp}")
                except KeyError:
                    lines.append(f"  • {w.get('name', '?')}: {w.get('projectile', '?')}")
            if len(wps) > 6:
                lines.append(f"  … +{len(wps) - 6} more")
    elif item_id == "upg_repair":
        lines = [
            "REPAIR & REVIVE",
            "Restore full HP on all surviving",
            "player capitals and strike craft.",
            "",
            f"Cost: {COST_REPAIR} salvage",
            f"Bank: {salvage[0]} salvage",
        ]
    elif item_id == "upg_resupply":
        lines = [
            "RESUPPLY",
            "+28 supplies (campaign cap 100).",
            "",
            f"Cost: {COST_RESUPPLY} salvage",
            f"Supplies: {supplies[0]:.0f}/100",
        ]
    elif item_id == "upg_ciws":
        lines = [
            "CIWS TUNING",
            f"+{int(CIWS_ROF_BONUS * 100)}% point-defense rate.",
            f"Stacks: {ciws_stacks[0]}/{MAX_CIWS_STACKS}",
            "",
            f"Cost: {COST_CIWS} salvage",
            f"Current PD mult: ×{pd_rof_mult[0]:.2f}",
        ]
    elif item_id == "upg_bulkhead":
        lines = [
            "BULKHEAD REFIT",
            f"+{int(BULKHEAD_HP_FRAC * 100)}% max hull (all ships).",
            f"Stacks: {bulk_stacks[0]}/{MAX_BULKHEAD_STACKS}",
            "",
            f"Cost: {COST_BULKHEAD} salvage",
        ]
    elif item_id == "upg_stores":
        lines = [
            "COMBAT STORES",
            f"+{int(LIGHT_RESUPPLY_AMT)} supplies (cap 100).",
            "",
            f"Cost: {COST_LIGHT_RESUPPLY} salvage",
            f"Supplies: {supplies[0]:.0f}/100",
        ]
    if reason:
        lines.extend(["", f"— {reason} —"])
    else:
        lines.extend(["", "Ready to purchase."])
    return lines
