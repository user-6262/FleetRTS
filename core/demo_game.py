"""
Fleet RTS prototype: world-space 2D, JSON-driven weapons/missiles, carrier hangar craft.
"""
from __future__ import annotations

import json
import math
import os
import queue
import random
import sys
import threading
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pygame

from game_audio import GameAudio

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
        clear_shot_xy,
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
        projectile_by_name,
        rally_xy_for_craft,
        resolve_all_units_against_asteroids,
        segment_blocked_by_asteroids,
        separate_player_capitals,
        spawn_enemy_reinforcement,
        update_craft_positions,
        update_fog_of_war,
        weapon_range,
    )
except ImportError:
    from core.combat_engine import (
        begin_combat_round,
        clear_shot_xy,
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
        projectile_by_name,
        rally_xy_for_craft,
        resolve_all_units_against_asteroids,
        segment_blocked_by_asteroids,
        separate_player_capitals,
        spawn_enemy_reinforcement,
        update_craft_positions,
        update_fog_of_war,
        weapon_range,
    )

try:
    from fleet_deployment import (
        DEPLOYMENT_MIN_CAPITALS,
        DEPLOYMENT_STARTING_SCRAP,
        MAX_PLAYER_CAPITALS,
        RECRUIT_LABEL_PREFIX,
        apply_deployment_weapon_choice,
        class_max_weapon_range,
        deploy_anchor_xy,
        deployment_cost_for_class,
        group_max_range_from_weapons,
        loadout_try_add_capital,
        loadout_try_remove_capital,
        next_recruit_label,
        player_capital_count,
        purge_loadout_choices_for_label,
        recruit_spawn_xy,
        resolve_weapon_entry,
        ship_class_by_name,
        sync_loadout_choice_map_for_group,
        weapon_loadout_options_expanded,
        weapon_loadout_slot_choices,
    )
except ImportError:
    from core.fleet_deployment import (
        DEPLOYMENT_MIN_CAPITALS,
        DEPLOYMENT_STARTING_SCRAP,
        MAX_PLAYER_CAPITALS,
        RECRUIT_LABEL_PREFIX,
        apply_deployment_weapon_choice,
        class_max_weapon_range,
        deploy_anchor_xy,
        deployment_cost_for_class,
        group_max_range_from_weapons,
        loadout_try_add_capital,
        loadout_try_remove_capital,
        next_recruit_label,
        player_capital_count,
        purge_loadout_choices_for_label,
        recruit_spawn_xy,
        resolve_weapon_entry,
        ship_class_by_name,
        sync_loadout_choice_map_for_group,
        weapon_loadout_options_expanded,
        weapon_loadout_slot_choices,
    )

try:
    from combat_ordnance import (
        compute_pd_stress_ratio,
        control_group_slots_for_capital_label,
        is_valid_attack_focus_for_side,
        notify_player_unit_damaged_for_engagement,
        pd_stress_color,
        pd_stress_display_level,
    )
except ImportError:
    from core.combat_ordnance import (
        compute_pd_stress_ratio,
        control_group_slots_for_capital_label,
        is_valid_attack_focus_for_side,
        notify_player_unit_damaged_for_engagement,
        pd_stress_color,
        pd_stress_display_level,
    )

_effective_capital_move_speed = effective_capital_move_speed

try:
    from combat_sim import CombatAudioEvents, CombatSimHooks, apply_combat_death_audio, step_combat_frame
except ImportError:
    from core.combat_sim import CombatAudioEvents, CombatSimHooks, apply_combat_death_audio, step_combat_frame

try:
    from mp_spawn_layout import coop_player_spawn_anchor, normalize_mp_player_order, pvp_player_spawn_anchor
except ImportError:
    from core.mp_spawn_layout import coop_player_spawn_anchor, normalize_mp_player_order, pvp_player_spawn_anchor

try:
    from combat_mp import apply_combat_command
    from combat_snapshot import SNAP_VERSION, apply_snapshot_state, hash_state_dict, snapshot_state
    from net.combat_net import COMBAT_CMD, COMBAT_SNAP, combat_cmd, combat_snap
except ImportError:
    from core.combat_mp import apply_combat_command
    from core.combat_snapshot import SNAP_VERSION, apply_snapshot_state, hash_state_dict, snapshot_state
    from core.net.combat_net import COMBAT_CMD, COMBAT_SNAP, combat_cmd, combat_snap

try:
    from pvp_battlegroups import BattlegroupPreset, default_battlegroups_path, load_battlegroups, save_battlegroups
except ImportError:
    from core.pvp_battlegroups import BattlegroupPreset, default_battlegroups_path, load_battlegroups, save_battlegroups

NET_MP = False
FleetHttpError = RuntimeError
RelayClient: Any = None
create_lobby = get_lobby = get_lobby_by_short_id = join_lobby = leave_lobby = list_lobbies = quick_join = None
lobby_loadout = None
try:
    from net.http_client import FleetHttpError as _FleetHttpError
    from net.http_client import create_lobby as _create_lobby
    from net.http_client import get_lobby as _get_lobby
    from net.http_client import get_lobby_by_short_id as _get_lobby_by_short_id
    from net.http_client import join_lobby as _join_lobby
    from net.http_client import leave_lobby as _leave_lobby
    from net.http_client import list_lobbies as _list_lobbies
    from net.http_client import quick_join as _quick_join
    from net.app_messages import host_config as _host_config
    from net.app_messages import lobby_chat as _lobby_chat
    from net.app_messages import lobby_loadout as _lobby_loadout
    from net.app_messages import lobby_presence as _lobby_presence
    from net.app_messages import lobby_ready as _lobby_ready
    from net.app_messages import start_match as _start_match
    from net.relay_client import RelayClient as _RelayClient

    FleetHttpError = _FleetHttpError
    create_lobby = _create_lobby
    get_lobby = _get_lobby
    get_lobby_by_short_id = _get_lobby_by_short_id
    join_lobby = _join_lobby
    leave_lobby = _leave_lobby
    list_lobbies = _list_lobbies
    quick_join = _quick_join
    RelayClient = _RelayClient
    lobby_chat = _lobby_chat
    lobby_loadout = _lobby_loadout
    lobby_ready = _lobby_ready
    lobby_presence = _lobby_presence
    host_config = _host_config
    start_match = _start_match
    NET_MP = True
except ImportError:
    def lobby_chat(text: str) -> dict:  # type: ignore[misc]
        return {"t": "lobby_chat", "text": (text or "")[:240]}

    def lobby_ready(ready: bool) -> dict:  # type: ignore[misc]
        return {"t": "lobby_ready", "v": bool(ready)}

    def host_config(*, coop: bool, use_asteroids: bool, enemy_pressure: int) -> dict:  # type: ignore[misc]
        return {"t": "host_config", "coop": coop, "use_asteroids": use_asteroids, "enemy_pressure": enemy_pressure}

    def start_match(  # type: ignore[misc]
        *,
        generation: int,
        seed: int,
        round_idx: int,
        coop: bool,
        use_asteroids: bool,
        enemy_pressure: int,
        player_setup: Optional[dict] = None,
    ) -> dict:
        out = {
            "t": "start_match",
            "generation": generation,
            "seed": seed,
            "round_idx": round_idx,
            "coop": coop,
            "use_asteroids": use_asteroids,
            "enemy_pressure": enemy_pressure,
        }
        if isinstance(player_setup, dict):
            out["player_setup"] = player_setup
        return out

    def lobby_presence(*, in_fleet_design: bool, color_id: int = 0) -> dict:  # type: ignore[misc]
        return {"t": "lobby_presence", "in_fleet_design": bool(in_fleet_design), "color_id": int(color_id)}

    def lobby_loadout(*, payload: dict) -> dict:  # type: ignore[misc]
        return {"t": "lobby_loadout", "payload": dict(payload or {})}

try:
    from bundle_paths import game_data_json
except ImportError:
    from core.bundle_paths import game_data_json

DATA_PATH = game_data_json()

# Public lobby HTTP API (DigitalOcean stub, port 8765). Friends can run the game with no env vars.
# Override: FLEETRTS_HTTP=http://127.0.0.1:8765  ·  Disable online: FLEETRTS_HTTP=
DEFAULT_FLEETRTS_LOBBY_HTTP = "http://198.199.80.13:8765"

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


def _resolve_fleet_http_base() -> Optional[str]:
    env_raw = os.environ.get("FLEETRTS_HTTP")
    if env_raw is not None:
        return env_raw.strip() or None
    return DEFAULT_FLEETRTS_LOBBY_HTTP.strip() or None


def _friendly_hub_http_message(raw: str) -> str:
    """Single-line player-facing summary; keep technical details for logs only."""
    s = (raw or "").strip()
    low = s.lower()
    if "stalled" in low or "thread" in low:
        return "The lobby list took too long. Try again in a moment."
    if "timed out" in low or "timeout" in low:
        return "The lobby server didn't respond in time."
    if "refused" in low or "actively refused" in low:
        return "No lobby server accepted the connection."
    if "getaddrinfo" in low or "name or service not known" in low or "name resolution" in low:
        return "Couldn't look up the lobby server address."
    if "ssl" in low or "certificate" in low or "tls" in low:
        return "A secure connection to the lobby server couldn't be established."
    if s.startswith("HTTP 401") or " 401" in s[:24]:
        return "The lobby server rejected the request (sign-in or key)."
    if s.startswith("HTTP 403") or " 403" in s[:24]:
        return "Access to the lobby server was denied."
    if s.startswith("HTTP 4"):
        return "The lobby server couldn't fulfill that request."
    if s.startswith("HTTP 5"):
        return "The lobby server reported an error."
    if "invalid json" in low or "unexpected response" in low:
        return "The lobby server sent an unexpected response."
    return "Can't reach the lobby server. Check your internet and try again."


WIDTH, HEIGHT = 1720, 990
# Bottom RTS chrome (control groups, status, click-order panel). World draws above this strip.
BOTTOM_BAR_H = 128
ORDER_PANEL_W = 208
ORDER_PANEL_STANCE_STRIP_H = 36
VIEW_W = WIDTH
VIEW_H = HEIGHT - BOTTOM_BAR_H


def _preload_http_client_stack() -> None:
    """Import ssl/urllib on the main thread before any worker HTTP (reduces Win32 DLL init deadlocks)."""
    try:
        import ssl  # noqa: F401

        ssl.create_default_context()
    except Exception:
        pass
    try:
        import urllib.error  # noqa: F401
        import urllib.request  # noqa: F401
    except Exception:
        pass


def _append_fleetrts_debug_log(line: str) -> None:
    path = os.environ.get("FLEETRTS_DEBUG_LOG", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except OSError:
        pass


def _blit_internal_to_window(window: pygame.Surface, screen: pygame.Surface, win_w: int, win_h: int) -> None:
    if win_w == WIDTH and win_h == HEIGHT:
        window.blit(screen, (0, 0))
    else:
        scaled = pygame.transform.smoothscale(screen, (max(1, win_w), max(1, win_h)))
        window.blit(scaled, (0, 0))
    pygame.display.flip()


CAM_PAN_SPEED = 520.0
OBJECTIVE_RADIUS = 56.0

# Fog grid size / sensor radii: combat_constants.FOG_CW, FOG_CH, SENSOR_RANGE_* (imported above).
ACTIVE_PING_RADIUS = 780.0
ACTIVE_PING_TTL = 1.05
ACTIVE_PING_COOLDOWN = 5.5
SENSOR_GHOST_TTL = 0.42

# Asteroids render at low Z (background); combat ships stay ~16–78 Z. XY collision is impassable.
ASTEROID_VISUAL_Z = 9.0

# NATO-style capital glyph on the map: Frigate smallest, Carrier largest (multiplies camera scale `sc`).
CAPITAL_MARKER_CLASS_SCALE: Dict[str, float] = {
    "Frigate": 0.68,
    "Destroyer": 0.90,
    "Cruiser": 1.22,
    "Battleship": 1.54,
    "Dreadnought": 2.16,
    "Carrier": 1.90,
}


def capital_marker_scale(class_name: str) -> float:
    return CAPITAL_MARKER_CLASS_SCALE.get(class_name, 1.0)


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


def parse_obstacles(data: dict) -> List[Asteroid]:
    bf = data.get("battlefield") or {}
    raw = bf.get("asteroids") or []
    out: List[Asteroid] = []
    for a in raw:
        out.append(Asteroid(float(a["x"]), float(a["y"]), float(a["r"])))
    return out


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
    g.strike_focus_target = None
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
            p.strike_focus_target = mark
        for c in wing_f:
            si = c.squadron_index
            wings = c.parent.strike_rally_wings
            if si < len(wings):
                wings[si] = None
    else:
        for p in parents.values():
            p.strike_focus_target = None
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
            g.strike_focus_target = mark
            for i in fidx:
                if i < len(g.strike_rally_wings):
                    g.strike_rally_wings[i] = None
        else:
            g.strike_focus_target = None
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
                p.strike_focus_target = mark
            for c in bom_wing:
                si = c.squadron_index
                wings = c.parent.strike_rally_wings
                if si < len(wings):
                    wings[si] = None
        else:
            for p in parents.values():
                p.strike_focus_target = None
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
            g.strike_focus_target = mark
            for i in bidx:
                if i < len(g.strike_rally_wings):
                    g.strike_rally_wings[i] = None
        else:
            g.strike_focus_target = None
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


def pick_player_craft_at(
    crafts: List[Craft], mx: int, my: int, cam_x: float, cam_y: float, owner_id: Optional[str] = None
) -> Optional[Craft]:
    best: Optional[Craft] = None
    best_d = 9999.0
    for c in crafts:
        if c.dead or c.side != "player" or c.parent.dead:
            continue
        if owner_id is not None and c.owner_id != owner_id:
            continue
        sx, sy, sc = world_to_screen(c.x, c.y, c.z, cam_x, cam_y)
        pr = 14.0 * max(0.75, sc)
        d = dist_xy(float(mx), float(my), sx, sy)
        if d < pr and d < best_d:
            best_d = d
            best = c
    return best


def _asteroid_visual_seed(o: Asteroid) -> int:
    h = hash((int(o.x) % 104729, int(o.y) % 104729, int(o.r) % 10007))
    return abs(h) % (2**31 - 1) + 1


def draw_asteroids(
    surf: pygame.Surface, obstacles: List[Asteroid], cam_x: float, cam_y: float, fog: FogState
) -> None:
    """Chunky irregular rocks on the low-Z plane (read as terrain below the fleet)."""
    batch: List[Tuple[float, Asteroid]] = []
    for o in obstacles:
        if not fog_cell_explored(fog, o.x, o.y):
            continue
        _, sy, _ = world_to_screen(o.x, o.y, ASTEROID_VISUAL_Z, cam_x, cam_y)
        batch.append((sy, o))
    batch.sort(key=lambda t: t[0], reverse=True)
    for _, o in batch:
        sx, sy, sc = world_to_screen(o.x, o.y, ASTEROID_VISUAL_Z, cam_x, cam_y)
        xi, yi = int(sx), int(sy)
        rng = random.Random(_asteroid_visual_seed(o))
        rr = max(14, int(o.r * sc * 0.98))
        flat = 0.74
        n = 18
        pts: List[Tuple[int, int]] = []
        for i in range(n):
            ang = (i / n) * 2 * math.pi + rng.uniform(-0.07, 0.07)
            rad = rr * rng.uniform(0.86, 1.04)
            pts.append((int(xi + math.cos(ang) * rad), int(yi + math.sin(ang) * rad * flat)))
        core = (32, 36, 48)
        mid = (52, 58, 72)
        rim = (88, 96, 112)
        hi = (118, 126, 138)
        pygame.draw.polygon(surf, core, pts)
        # Facet sheen (upper-left)
        facet = []
        for i in range(0, n, 2):
            facet.append(pts[i])
        if len(facet) >= 3:
            pygame.draw.polygon(surf, mid, facet[: n // 2 + 1])
        pygame.draw.polygon(surf, rim, pts, width=2)
        # Craters / pits
        for _ in range(max(2, min(6, rr // 28))):
            ca = rng.uniform(0, 2 * math.pi)
            cd = rr * rng.uniform(0.12, 0.58)
            cx = int(xi + math.cos(ca) * cd)
            cy = int(yi + math.sin(ca) * cd * flat)
            cw = max(4, int(rr * rng.uniform(0.07, 0.16)))
            ch = max(2, int(cw * 0.55))
            pygame.draw.ellipse(surf, (24, 28, 38), pygame.Rect(cx - cw, cy - ch, cw * 2, ch * 2))
        # Specular glint
        gx = int(xi - rr * 0.28)
        gy = int(yi - rr * 0.22 * flat)
        pygame.draw.circle(surf, hi, (gx, gy), max(2, rr // 14))
        pygame.draw.circle(surf, (160, 168, 182), (gx, gy), max(1, rr // 22))


def draw_fog_overlay(surf: pygame.Surface, fog: FogState, cam_x: float, cam_y: float) -> None:
    """Soft alpha fog on an overlay; unexplored vs memory read as depth + grain."""
    ov = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
    for cj in range(FOG_CH):
        for ci in range(FOG_CW):
            idx = ci + cj * FOG_CW
            if fog.visible[idx]:
                continue
            wx0 = ci / FOG_CW * WORLD_W
            wx1 = (ci + 1) / FOG_CW * WORLD_W
            wy0 = cj / FOG_CH * WORLD_H
            wy1 = (cj + 1) / FOG_CH * WORLD_H
            pts_o: List[Tuple[int, int]] = []
            for wx, wy in ((wx0, wy0), (wx1, wy0), (wx1, wy1), (wx0, wy1)):
                sx, sy, _ = world_to_screen(wx, wy, 22.0, cam_x, cam_y)
                pts_o.append((int(sx), int(sy)))
            if max(p[0] for p in pts_o) < -8 or min(p[0] for p in pts_o) > VIEW_W + 8:
                continue
            if max(p[1] for p in pts_o) < -8 or min(p[1] for p in pts_o) > VIEW_H + 8:
                continue
            grain = (ci * 47 + cj * 19) % 37
            if not fog.explored[idx]:
                base_a = 228 + min(24, grain)
                c0 = (4, 8, 20, base_a)
                c1 = (10, 18, 38, max(40, base_a - 100))
            else:
                base_a = 118 + min(28, grain)
                c0 = (16, 26, 48, base_a)
                c1 = (28, 42, 72, max(28, base_a - 55))
            cx = sum(p[0] for p in pts_o) / len(pts_o)
            cy = sum(p[1] for p in pts_o) / len(pts_o)
            inner: List[Tuple[int, int]] = []
            for px, py in pts_o:
                inner.append((int(cx + (px - cx) * 0.72), int(cy + (py - cy) * 0.72)))
            pygame.draw.polygon(ov, c0, pts_o)
            pygame.draw.polygon(ov, c1, inner)
            pygame.draw.polygon(ov, (0, 0, 0, 24), pts_o, width=1)
    edge = 64
    sh = (3, 8, 18, 38)
    pygame.draw.rect(ov, sh, (0, 0, VIEW_W, edge))
    pygame.draw.rect(ov, sh, (0, VIEW_H - edge, VIEW_W, edge))
    pygame.draw.rect(ov, sh, (0, 0, edge, VIEW_H))
    pygame.draw.rect(ov, sh, (VIEW_W - edge, 0, edge, VIEW_H))
    surf.blit(ov, (0, 0))


def draw_sensor_ghosts(
    surf: pygame.Surface, font: pygame.font.Font, ghosts: List[SensorGhost], cam_x: float, cam_y: float
) -> None:
    for gh in ghosts:
        if gh.ttl <= 0:
            continue
        sx, sy, sc = world_to_screen(gh.x, gh.y, 32.0, cam_x, cam_y)
        col = (180, 120, 255) if gh.quality < 0.42 else (255, 190, 120)
        rr = max(10, int(16 * sc * (0.55 + 0.45 * gh.quality)))
        pygame.draw.circle(surf, col, (int(sx), int(sy)), rr, width=2)
        dash = max(6, rr - 4)
        pygame.draw.circle(surf, col, (int(sx), int(sy)), dash, width=1)
        t = font.render(gh.label, True, col)
        surf.blit(t, (int(sx) - t.get_width() // 2, int(sy) - rr - 14))
TEST_SALVAGE_GRANT = 400
FPS = 60
# World speed for ships & strike craft from JSON (ordnance uses separate mults below).
# 200% of prior 0.46 tuning (faster map crossing / engagements).
SPEED_SCALE = 0.92
CAPITAL_PICK_R = 42
FORMATION_BASE_R = 58
FORMATION_PER_UNIT = 12
FORMATION_MODE_RING = 0
FORMATION_MODE_CARRIER_CORE = 1
FORMATION_MODE_DAMAGED_CORE = 2
FORMATION_MODE_NAMES = ("Ring", "Carrier core", "Damaged core")
CONTROL_GROUP_SLOTS = 9
# Monotonic id for "move together at slowest speed" batches (see issue_move_orders / move_group).
_move_pace_seq = 0


def _alloc_move_pace_group_id() -> int:
    global _move_pace_seq
    _move_pace_seq += 1
    return _move_pace_seq
DRAG_LINE_MIN_PX = 28
DOUBLE_CLICK_MS = 420
TTS_ENEMY_KILL_GAP_MS = 2600
TTS_PLAYER_CAP_LOSS_GAP_MS = 4500
TTS_CARRIER_QUIP_GAP_MS = 4800
# Move / attack-move / strike-rally voice ticks (shared gap avoids TTS pile-up on spam-click).
TTS_ORDER_QUIP_GAP_MS = 2200
# Per-ship label so switching between two damaged capitals still gets a report.
TTS_LOW_HULL_SELECT_GAP_MS = 5200
TTS_LOW_HULL_FRAC = 0.33
TTS_MOVE_VOICE_LINES = ("moving", "orders_received_moving")
TTS_ATTACK_MOVE_VOICE_LINES = ("orders_received_striking",)
TTS_ATTACK_TARGET_VOICE_LINES = ("focus_fire",)
DRAG_CLICK_MAX_PX = 6
# 2.5D "altitude" (0 = combat plane, higher = further from plane — smaller / lifted on screen)
Z_VIS_LIFT = 0.36
Z_SCALE_K = 0.0042
Z_MIN_SCALE = 0.58
# PD slug visuals only (not damage/range): brightness vs time in flight
SLUG_VISUAL_FADE_PER_SEC = 0.068
SLUG_VISUAL_FADE_MIN = 0.5
# Missiles / torpedoes: "ordnance" = diamond + black fill + MSL/TOR tag (lowest UI tier vs craft/capitals).
# Set to "classic" to restore the old rocket/circle sprites (easy A/B or rollback).
MISSILE_VISUAL_STYLE = "ordnance"
# Campaign / between-rounds
COST_REPAIR = 28
COST_RESUPPLY = 34
COST_CIWS = 44
COST_BULKHEAD = 52
MAX_CIWS_STACKS = 5
MAX_BULKHEAD_STACKS = 5
CIWS_ROF_BONUS = 0.085
BULKHEAD_HP_FRAC = 0.06
COST_FRIGATE = 62
COST_DESTROYER = 92
COST_CRUISER = 138
COST_BATTLESHIP = 175
COST_CARRIER = 255
COST_LIGHT_RESUPPLY = 22
LIGHT_RESUPPLY_AMT = 14.0
# Debrief store layout (three panels)
DEBRIEF_MARGIN = 14
DEBRIEF_TOP = 72
DEBRIEF_BOTTOM_PAD = 44
DEBRIEF_PANEL_GAP = 12
DEBRIEF_ROW_H = 26
DEBRIEF_ROW_GAP = 3
DEBRIEF_HEADER_H = 36
DEBRIEF_INNER_PAD = 10
# item_id -> pygame key for one-shot purchase (same as panel order)
STORE_KEY_SHIP = (
    pygame.K_1,
    pygame.K_2,
    pygame.K_3,
    pygame.K_4,
    pygame.K_5,
)
STORE_KEY_UPGRADE = (
    pygame.K_6,
    pygame.K_7,
    pygame.K_8,
    pygame.K_9,
    pygame.K_0,
)

STORE_SHIP_IDS = ("ship_frigate", "ship_destroyer", "ship_cruiser", "ship_battleship", "ship_carrier")
STORE_SHIP_CLASSES = ("Frigate", "Destroyer", "Cruiser", "Battleship", "Carrier")
STORE_SHIP_COSTS = (COST_FRIGATE, COST_DESTROYER, COST_CRUISER, COST_BATTLESHIP, COST_CARRIER)
STORE_UPGRADE_IDS = ("upg_repair", "upg_resupply", "upg_ciws", "upg_bulkhead", "upg_stores")
SHIP_CLASS_BY_STORE_ID = dict(zip(STORE_SHIP_IDS, STORE_SHIP_CLASSES))
SHIP_COST_BY_STORE_ID = dict(zip(STORE_SHIP_IDS, STORE_SHIP_COSTS))
STORE_KEY_BY_ID: dict[str, int] = {}
for i, sid in enumerate(STORE_SHIP_IDS):
    STORE_KEY_BY_ID[sid] = STORE_KEY_SHIP[i]
for i, uid in enumerate(STORE_UPGRADE_IDS):
    STORE_KEY_BY_ID[uid] = STORE_KEY_UPGRADE[i]
STORE_ITEM_BY_KEY = {key: item_id for item_id, key in STORE_KEY_BY_ID.items()}


def load_game_data() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def capital_ship_class_names(data: dict) -> List[str]:
    out: List[str] = []
    for sc in data.get("ship_classes") or []:
        if sc.get("render") == "capital" and sc.get("name"):
            out.append(str(sc["name"]))
    return sorted(out)


@dataclass
class RuntimeWeapon:
    name: str
    projectile_name: str
    fire_rate: float
    cooldown: float = 0.0


def build_runtime_weapons(data: dict, sc: dict) -> List[RuntimeWeapon]:
    out: List[RuntimeWeapon] = []
    for w in sc.get("weapons") or []:
        name, pn, fr = resolve_weapon_entry(data, w)
        out.append(RuntimeWeapon(name=name, projectile_name=pn, fire_rate=float(fr)))
    return out


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
    strike_focus_target: Optional[Any] = None
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
        self.strike_focus_target = None


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


def clamp_camera(cam_x: float, cam_y: float) -> Tuple[float, float]:
    max_cx = max(0.0, WORLD_W - VIEW_W)
    max_cy = max(0.0, WORLD_H - VIEW_H)
    return max(0.0, min(max_cx, cam_x)), max(0.0, min(max_cy, cam_y))


def draw_world_edge(surf: pygame.Surface, cam_x: float, cam_y: float) -> None:
    col = (0, 72, 58)
    corners = [(0, 0), (WORLD_W, 0), (WORLD_W, WORLD_H), (0, WORLD_H), (0, 0)]
    for i in range(4):
        ax, ay = corners[i]
        bx, by = corners[i + 1]
        sax, say, _ = world_to_screen(ax, ay, 0.0, cam_x, cam_y)
        sbx, sby, _ = world_to_screen(bx, by, 0.0, cam_x, cam_y)
        pygame.draw.line(surf, col, (int(sax), int(say)), (int(sbx), int(sby)), 2)


def draw_extract_zone(surf: pygame.Surface, font: pygame.font.Font, cam_x: float, cam_y: float) -> None:
    rw = extract_rect_world()
    pts = [(rw.left, rw.top), (rw.right, rw.top), (rw.right, rw.bottom), (rw.left, rw.bottom)]
    scr = [(world_to_screen(px, py, 0.0, cam_x, cam_y)[0], world_to_screen(px, py, 0.0, cam_x, cam_y)[1]) for px, py in pts]
    pygame.draw.lines(surf, (0, 140, 95), True, [(int(a), int(b)) for a, b in scr], 2)
    tcx = int(sum(p[0] for p in scr) / len(scr))
    tcy = int(min(p[1] for p in scr) - 6)
    lbl = font.render("EXIT — all capitals inside to jump", True, (120, 220, 160))
    surf.blit(lbl, (tcx - lbl.get_width() // 2, tcy - 18))


def initial_camera_for_fleet(groups: List[Group]) -> Tuple[float, float]:
    caps = [g for g in groups if g.side == "player" and not g.dead and g.render_capital]
    if not caps:
        return clamp_camera(WORLD_W * 0.5 - VIEW_W * 0.5, WORLD_H * 0.5 - VIEW_H * 0.5)
    mx = sum(g.x for g in caps) / len(caps)
    my = sum(g.y for g in caps) / len(caps)
    return clamp_camera(mx - VIEW_W * 0.5, my - VIEW_H * 0.5)


def normalize_rect(x0: int, y0: int, x1: int, y1: int) -> pygame.Rect:
    left = min(x0, x1)
    top = min(y0, y1)
    w = abs(x1 - x0)
    h = abs(y1 - y0)
    return pygame.Rect(left, top, max(1, w), max(1, h))


def player_capitals_in_rect(
    groups: List[Group],
    rect: pygame.Rect,
    cam_x: float,
    cam_y: float,
    owner_id: Optional[str] = None,
) -> List[Group]:
    out: List[Group] = []
    for g in groups:
        if g.side != "player" or g.dead or not g.render_capital:
            continue
        if owner_id is not None and getattr(g, "owner_id", "") != owner_id:
            continue
        sx, sy, _ = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        if rect.collidepoint(sx, sy):
            out.append(g)
    return out


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


def pick_player_capital_at(
    groups: List[Group], mx: int, my: int, cam_x: float, cam_y: float, owner_id: Optional[str] = None
) -> Optional[Group]:
    best: Optional[Group] = None
    best_d = 9999.0
    for g in groups:
        if g.side != "player" or g.dead or not g.render_capital:
            continue
        if owner_id is not None and g.owner_id != owner_id:
            continue
        sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        pick_r = CAPITAL_PICK_R * max(0.85, sc)
        d = dist_xy(sx, sy, float(mx), float(my))
        if d < pick_r and d < best_d:
            best_d = d
            best = g
    return best


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
            g.strike_focus_target = None
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
            g.strike_focus_target = None
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


def tts_speak_random_if_cooled(
    audio: GameAudio, line_ids: Tuple[str, ...], now_ms: int, last_ms: int, gap_ms: int
) -> int:
    if not line_ids or now_ms - last_ms < gap_ms:
        return last_ms
    audio.speak_voice(random.choice(line_ids))
    return now_ms


def tts_speak_if_cooled(audio: GameAudio, line_id: str, now_ms: int, last_ms: int, gap_ms: int) -> int:
    lid = line_id.strip()
    if not lid or now_ms - last_ms < gap_ms:
        return last_ms
    audio.speak_voice(lid)
    return now_ms


def capital_on_screen(g: Group, cam_x: float, cam_y: float, margin: float = 64.0) -> bool:
    sx, sy, _ = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
    return -margin <= sx <= VIEW_W + margin and -margin <= sy <= VIEW_H + margin


def select_all_same_class_visible(
    groups: List[Group],
    class_name: str,
    cam_x: float,
    cam_y: float,
    owner_id: Optional[str] = None,
) -> None:
    vis = [
        g
        for g in groups
        if g.side == "player"
        and not g.dead
        and g.render_capital
        and g.class_name == class_name
        and capital_on_screen(g, cam_x, cam_y)
        and (owner_id is None or getattr(g, "owner_id", "") == owner_id)
    ]
    set_selection(groups, vis)


def add_to_selection(groups: List[Group], to_add: List[Group]) -> None:
    for g in to_add:
        if not g.dead and g.render_capital and g.side == "player":
            g.selected = True


def toggle_capital_in_selection(hit: Group, owner_id: Optional[str] = None) -> None:
    if hit.dead or not hit.render_capital:
        return
    if owner_id is not None and getattr(hit, "owner_id", "") != owner_id:
        return
    hit.selected = not hit.selected


def focus_camera_for_selection(cam_x: float, cam_y: float, targets: List[Group]) -> Tuple[float, float]:
    if not targets:
        return cam_x, cam_y
    cx = sum(g.x for g in targets) / len(targets)
    cy = sum(g.y for g in targets) / len(targets)
    return clamp_camera(cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)


def draw_nato_ship(
    surf: pygame.Surface,
    x: float,
    y: float,
    color: Tuple[int, int, int],
    heading: float,
    scale: float = 1.0,
) -> None:
    xi, yi = int(x), int(y)
    w = int(22 * scale)
    h = int(14 * scale)
    rect = pygame.Rect(xi - w // 2, yi - h // 2, w, h)
    pygame.draw.rect(surf, color, rect, width=2, border_radius=2)
    L = int(12 * scale)
    hx = math.cos(heading) * L
    hy = math.sin(heading) * L
    tip = (xi + hx, yi + hy)
    left = (xi + math.cos(heading + 2.4) * 8 * scale, yi + math.sin(heading + 2.4) * 8 * scale)
    right = (xi + math.cos(heading - 2.4) * 8 * scale, yi + math.sin(heading - 2.4) * 8 * scale)
    pygame.draw.polygon(surf, color, [tip, left, right], width=2)


def draw_craft_triangle(
    surf: pygame.Surface,
    x: float,
    y: float,
    color: Tuple[int, int, int],
    heading: float,
    size: float = 7.0,
) -> None:
    xi, yi = int(x), int(y)
    s = size
    p1 = (xi + math.cos(heading) * s, yi + math.sin(heading) * s)
    p2 = (xi + math.cos(heading + 2.35) * s * 0.55, yi + math.sin(heading + 2.35) * s * 0.55)
    p3 = (xi + math.cos(heading - 2.35) * s * 0.55, yi + math.sin(heading - 2.35) * s * 0.55)
    pygame.draw.polygon(surf, color, [p1, p2, p3], width=0)
    pygame.draw.polygon(surf, color, [p1, p2, p3], width=1)


def player_unit_color(color_id: int, *, coop_mode: bool, for_craft: bool) -> Tuple[int, int, int]:
    _ = coop_mode  # reserved: co-op vs PvP still uses distinct per-slot palette for readability
    pal = MP_PLAYER_PALETTE
    base = pal[int(max(0, min(int(color_id), len(pal) - 1)))]
    if for_craft:
        return tuple(min(255, int(ch * 1.1)) for ch in base)
    return base


def draw_ballistic_slug(surf: pygame.Surface, s: BallisticSlug, cam_x: float, cam_y: float) -> None:
    sx, sy, sc = world_to_screen(s.x, s.y, s.z, cam_x, cam_y)
    xi, yi = int(sx), int(sy)
    fade = max(SLUG_VISUAL_FADE_MIN, min(1.0, 1.0 - s.age * SLUG_VISUAL_FADE_PER_SEC))

    def lit(rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
        a, b, c = rgb
        return (min(255, int(a * fade)), min(255, int(b * fade)), min(255, int(c * fade)))

    r = max(2, int(3.2 * sc))
    tr = max(1, int(2.0 * sc))
    tx = int(sx - s.vx * 0.024)
    ty = int(sy - s.vy * 0.024)
    pygame.draw.circle(surf, lit((95, 22, 18)), (tx, ty), tr + 1)
    pygame.draw.circle(surf, lit((200, 48, 38)), (tx, ty), tr)
    pygame.draw.circle(surf, lit((248, 68, 52)), (xi, yi), r)
    if r > 2:
        pygame.draw.circle(surf, lit((240, 145, 118)), (xi, yi), max(1, r - 2))
    pygame.draw.circle(surf, lit((255, 235, 218)), (xi, yi), max(1, r // 3))


def missile_ordnance_abbrev_color(
    proj_name: str, side_fallback: Tuple[int, int, int]
) -> Tuple[str, Tuple[int, int, int]]:
    """3-letter (or TOR) HUD tag + outline color for guided ordnance."""
    t = {
        "Fighter Missile": ("MSL", (110, 175, 255)),
        "Strike Missile": ("MSL", (255, 145, 72)),
        "Torpedo": ("TOR", (255, 108, 88)),
        "Bomber Torpedo": ("TOR", (255, 200, 95)),
    }
    if proj_name in t:
        return t[proj_name]
    pn_u = proj_name.upper()
    if "EMP" in pn_u:
        return ("EMP", (200, 120, 255))
    if "TORP" in pn_u:
        return ("TOR", side_fallback)
    if "MISSILE" in pn_u:
        return ("MSL", side_fallback)
    return ("MSL", side_fallback)


def draw_ordnance_missile_icon(
    surf: pygame.Surface,
    font_micro: Optional[pygame.font.Font],
    m: Missile,
    sx: float,
    sy: float,
    sc: float,
    ang: float,
) -> None:
    abbrev, ac = missile_ordnance_abbrev_color(m.proj_name, m.color)
    x, y = int(sx), int(sy)
    r_a = max(4.5, 6.0 * sc)
    r_b = max(2.8, 3.4 * sc)
    ca, sa = math.cos(ang), math.sin(ang)
    c2, s2 = math.cos(ang + math.pi / 2), math.sin(ang + math.pi / 2)
    pts = [
        (int(x + ca * r_a), int(y + sa * r_a)),
        (int(x + c2 * r_b), int(y + s2 * r_b)),
        (int(x - ca * r_a), int(y - sa * r_a)),
        (int(x - c2 * r_b), int(y - s2 * r_b)),
    ]
    flicker = 0.92 + 0.08 * math.sin(m.anim_t * 22.0)
    ac_l = (
        min(255, int(ac[0] * flicker)),
        min(255, int(ac[1] * flicker)),
        min(255, int(ac[2] * flicker)),
    )
    pygame.draw.polygon(surf, (0, 0, 0), pts)
    pygame.draw.polygon(surf, ac_l, pts, width=max(1, int(1.15 * sc)))
    # Short wake (still reads as ordnance, not a ship)
    wx = int(x - ca * r_a * 1.05)
    wy = int(y - sa * r_a * 1.05)
    wx2 = int(x - ca * r_a * 2.15)
    wy2 = int(y - sa * r_a * 2.15)
    dim = (ac_l[0] // 2 + 30, ac_l[1] // 2 + 25, ac_l[2] // 2 + 35)
    pygame.draw.line(surf, dim, (wx, wy), (wx2, wy2), max(1, int(1.0 * sc)))

    if font_micro is None:
        return
    pad = 2
    label = font_micro.render(abbrev, True, ac_l)
    bw = label.get_width() + pad * 2
    bh = label.get_height() + pad * 2
    bx = int(x - bw // 2)
    by = int(y + r_b + 5)
    bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
    # Lower hierarchy than strike-craft tags: dark wine/slate panel (not teal carrier wing).
    pygame.draw.rect(bg, (18, 12, 24, 200), (0, 0, bw, bh), border_radius=2)
    pygame.draw.rect(bg, (72, 48, 98, 220), (0, 0, bw, bh), width=1, border_radius=2)
    surf.blit(bg, (bx, by))
    surf.blit(label, (bx + pad, by + pad))


def _draw_missile_classic(surf: pygame.Surface, m: Missile, cam_x: float, cam_y: float) -> None:
    ang = math.atan2(m.vy, m.vx) if math.hypot(m.vy, m.vx) > 0.1 else 0.0
    sx, sy, sc = world_to_screen(m.x, m.y, m.z, cam_x, cam_y)
    x, y = int(sx), int(sy)
    flicker = 0.85 + 0.15 * math.sin(m.anim_t * 28.0)
    trail_x = int(sx - m.vx * 0.035)
    trail_y = int(sy - m.vy * 0.035)
    pn = m.proj_name

    def mul(c: Tuple[int, int, int], k: float) -> Tuple[int, int, int]:
        return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))

    if pn == "Fighter Missile":
        tr = max(1, int(2 * sc))
        cr = max(2, int(3 * sc))
        pygame.draw.circle(surf, (60, 100, 180), (trail_x, trail_y), tr)
        pygame.draw.circle(surf, mul((220, 240, 255), flicker), (x, y), cr)
        pygame.draw.circle(surf, (255, 255, 255), (x, y), max(1, cr // 2))
    elif pn == "Strike Missile":
        pygame.draw.circle(surf, (200, 90, 40), (trail_x, trail_y), max(2, int(3 * sc)))
        pygame.draw.circle(surf, mul((255, 200, 80), flicker), (x, y), max(3, int(5 * sc)))
        p1 = (x + math.cos(ang) * 7 * sc, y + math.sin(ang) * 7 * sc)
        p2 = (x + math.cos(ang + 2.3) * 3 * sc, y + math.sin(ang + 2.3) * 3 * sc)
        p3 = (x + math.cos(ang - 2.3) * 3 * sc, y + math.sin(ang - 2.3) * 3 * sc)
        pygame.draw.polygon(surf, (255, 230, 140), [p1, p2, p3], width=0)
    elif pn in ("Torpedo", "Bomber Torpedo"):
        warm = (255, 150, 70) if pn == "Torpedo" else (255, 200, 100)
        pygame.draw.circle(surf, (160, 50, 30), (trail_x, trail_y), max(3, int(4 * sc)))
        pygame.draw.circle(surf, mul(warm, flicker), (x, y), max(4, int(7 * sc)))
        body = (9 if pn == "Torpedo" else 8) * sc
        p1 = (x + math.cos(ang) * body, y + math.sin(ang) * body)
        p2 = (x + math.cos(ang + 2.2) * 4 * sc, y + math.sin(ang + 2.2) * 4 * sc)
        p3 = (x + math.cos(ang - 2.2) * 4 * sc, y + math.sin(ang - 2.2) * 4 * sc)
        pygame.draw.polygon(surf, (255, 220, 160), [p1, p2, p3], width=0)
        pygame.draw.polygon(surf, (80, 40, 20), [p1, p2, p3], width=1)
    else:
        pygame.draw.circle(surf, mul(m.color, 0.6), (trail_x, trail_y), max(2, int(3 * sc)))
        pygame.draw.circle(surf, mul(m.color, flicker), (x, y), max(3, int(5 * sc)))
        sz = 5 * sc
        p1 = (x + math.cos(ang) * sz, y + math.sin(ang) * sz)
        p2 = (x + math.cos(ang + 2.5) * 3 * sc, y + math.sin(ang + 2.5) * 3 * sc)
        p3 = (x + math.cos(ang - 2.5) * 3 * sc, y + math.sin(ang - 2.5) * 3 * sc)
        pygame.draw.polygon(surf, m.color, [p1, p2, p3], width=0)


def draw_missile(
    surf: pygame.Surface,
    m: Missile,
    cam_x: float,
    cam_y: float,
    font_micro: Optional[pygame.font.Font] = None,
) -> None:
    ang = math.atan2(m.vy, m.vx) if math.hypot(m.vy, m.vx) > 0.1 else 0.0
    sx, sy, sc = world_to_screen(m.x, m.y, m.z, cam_x, cam_y)
    if MISSILE_VISUAL_STYLE == "classic":
        _draw_missile_classic(surf, m, cam_x, cam_y)
        return
    draw_ordnance_missile_icon(surf, font_micro, m, sx, sy, sc, ang)


def heading_for_group(g: Group) -> float:
    if g.waypoint:
        wx, wy = g.waypoint
        return math.atan2(wy - g.y, wx - g.x)
    return -math.pi / 2


def draw_starfield(
    surf: pygame.Surface,
    stars: List[Tuple[int, int, int]],
    cam_x: float,
    cam_y: float,
    vis_w: int = VIEW_W,
    vis_h: int = VIEW_H,
) -> None:
    for wx, wy, br in stars:
        sx = int(wx - cam_x)
        sy = int(wy - cam_y)
        if 0 <= sx < vis_w and 0 <= sy < vis_h:
            c = (br, br, min(255, br + 40))
            surf.set_at((sx, sy), c)


def draw_strike_craft_tag(
    surf: pygame.Surface,
    font_micro: pygame.font.Font,
    x: float,
    y: float,
    cls: str,
    hp: float,
    max_hp: float,
) -> None:
    """Minimal tag for AI strike craft (smaller than capital plates)."""
    pad = 2
    short = cls[:3].upper()
    w1 = font_micro.render(short, True, (170, 195, 215))
    bar_w = 28
    frac = max(0.0, min(1.0, hp / max_hp if max_hp > 0 else 0))
    h_bar = 3
    total_h = w1.get_height() + h_bar + pad * 2
    bx = int(x - bar_w // 2 - pad)
    by = int(y - total_h - 2)
    bw = bar_w + pad * 2
    bg = pygame.Surface((bw, total_h), pygame.SRCALPHA)
    pygame.draw.rect(bg, (6, 14, 22, 160), (0, 0, bw, total_h), border_radius=2)
    pygame.draw.rect(bg, (35, 70, 60, 140), (0, 0, bw, total_h), width=1, border_radius=2)
    surf.blit(bg, (bx, by))
    surf.blit(w1, (bx + pad, by + pad))
    bgy = by + pad + w1.get_height() + 1
    pygame.draw.rect(surf, (28, 32, 38), (bx + pad, bgy, bar_w, h_bar), border_radius=1)
    pygame.draw.rect(surf, (70, 160, 110), (bx + pad, bgy, int(bar_w * frac), h_bar), border_radius=1)


def draw_entity_plate(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    x: float,
    y: float,
    label: str,
    cls: str,
    hp: float,
    max_hp: float,
    weapons: List[RuntimeWeapon],
    compact: bool,
) -> None:
    pad = 4
    line1 = f"{label}  {cls}"
    w1 = font_tiny.render(line1, True, (210, 225, 235))
    bar_w = 52 if compact else 64
    frac = max(0.0, min(1.0, hp / max_hp if max_hp > 0 else 0))
    h_bar = 5
    total_h = w1.get_height() + h_bar + pad * 2 + (0 if compact else 10)
    bx = int(x - bar_w // 2 - pad)
    by = int(y - total_h)
    bw = bar_w + pad * 2
    bg = pygame.Surface((bw, total_h), pygame.SRCALPHA)
    pygame.draw.rect(bg, (8, 18, 28, 200), (0, 0, bw, total_h), border_radius=4)
    pygame.draw.rect(bg, (40, 90, 80, 180), (0, 0, bw, total_h), width=1, border_radius=4)
    surf.blit(bg, (bx, by))
    surf.blit(w1, (bx + pad, by + pad))
    bgy = by + pad + w1.get_height() + 2
    pygame.draw.rect(surf, (30, 35, 40), (bx + pad, bgy, bar_w, h_bar), border_radius=2)
    pygame.draw.rect(surf, (80, 200, 120), (bx + pad, bgy, int(bar_w * frac), h_bar), border_radius=2)
    if not compact and weapons:
        ready = sum(1 for w in weapons if w.cooldown <= 0.05)
        t = font_tiny.render(f"W:{ready}/{len(weapons)} hot", True, (140, 170, 190))
        surf.blit(t, (bx + pad, bgy + h_bar + 2))


def draw_pd_stress_badge(
    surf: pygame.Surface,
    font: pygame.font.Font,
    sx: float,
    sy: float,
    sc: float,
    stress_ratio: float,
) -> None:
    level = pd_stress_display_level(stress_ratio)
    col = pd_stress_color(level)
    off = int(20 * sc)
    x0 = int(sx)
    y0 = int(sy + off)
    label = "PD"
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        sh = font.render(label, True, (10, 16, 26))
        surf.blit(sh, (x0 - sh.get_width() // 2 + ox, y0 + oy))
    txt = font.render(label, True, col)
    surf.blit(txt, (x0 - txt.get_width() // 2, y0))


def draw_attack_focus_rings(
    surf: pygame.Surface,
    groups: List[Group],
    cam_x: float,
    cam_y: float,
    fog: Optional["FogState"] = None,
) -> None:
    """One ring per unique focus target (any player capital with a valid attack_target). Drawn on top of ships."""
    seen: Set[int] = set()
    for g in groups:
        if g.side != "player" or g.dead or not g.render_capital:
            continue
        t = g.attack_target
        if not is_valid_attack_focus_for_side("player", t):
            continue
        tid = id(t)
        if tid in seen:
            continue
        seen.add(tid)
        if fog is not None and not fog_cell_visible(fog, t.x, t.y):
            continue
        tz = t.z if isinstance(t, GroundObjective) else getattr(t, "z", 35.0)
        sx, sy, sc = world_to_screen(t.x, t.y, tz, cam_x, cam_y)
        if isinstance(t, GroundObjective):
            rr = max(26, int((t.radius + 18.0) * sc))
        else:
            rr = max(22, int(34 * sc))
        pygame.draw.circle(surf, (255, 40, 45), (int(sx), int(sy)), rr, width=3)
        if rr > 12:
            pygame.draw.circle(surf, (255, 200, 140), (int(sx), int(sy)), max(10, rr - 8), width=2)


def weapon_stance_toggle_rect() -> pygame.Rect:
    r = order_panel_screen_rect()
    h = ORDER_PANEL_STANCE_STRIP_H - 6
    return pygame.Rect(r.x + 4, r.bottom - ORDER_PANEL_STANCE_STRIP_H + 2, r.w - 8, h)


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


def weapon_stance_display_for_selection(
    groups: List[Group],
    control_groups: List[Optional[List[str]]],
    cg_weapons_free: List[bool],
) -> Tuple[str, Tuple[int, int, int]]:
    """Short label + color for the stance strip (selection / control groups)."""
    sel_labels = [
        g.label
        for g in groups
        if g.side == "player" and g.selected and not g.dead and g.render_capital
    ]
    if not sel_labels:
        return ("Weapons: select ship", (130, 145, 165))
    slots: Set[int] = set()
    for lab in sel_labels:
        slots.update(control_group_slots_for_capital_label(control_groups, lab))
    if not slots:
        return ("Weapons: assign Ctrl+1–9", (200, 160, 95))
    if all(cg_weapons_free[s] for s in slots):
        return ("Group weapons: FREE", (95, 220, 130))
    if not any(cg_weapons_free[s] for s in slots):
        return ("Group weapons: HOLD", (230, 175, 85))
    return ("Weapons: mixed slots", (200, 200, 120))


def draw_vfx_beams(surf: pygame.Surface, beams: List[VFXBeam], cam_x: float, cam_y: float) -> None:
    for b in beams:
        f = b.ttl / b.max_ttl if b.max_ttl > 0 else 0.0
        c = tuple(min(255, int(ch * (0.35 + 0.65 * f))) for ch in b.color)
        x0, y0, _ = world_to_screen(b.x0, b.y0, 35.0, cam_x, cam_y)
        x1, y1, _ = world_to_screen(b.x1, b.y1, 35.0, cam_x, cam_y)
        pygame.draw.line(surf, c, (int(x0), int(y0)), (int(x1), int(y1)), b.width)


def draw_vfx_sparks(surf: pygame.Surface, sparks: List[VFXSpark], cam_x: float, cam_y: float) -> None:
    for s in sparks:
        f = s.ttl / s.max_ttl if s.max_ttl > 0 else 0.0
        c = tuple(min(255, int(ch * (0.45 + 0.55 * f))) for ch in s.color)
        sx, sy, _ = world_to_screen(s.x, s.y, 34.0, cam_x, cam_y)
        pygame.draw.circle(surf, c, (int(sx), int(sy)), s.radius)


def clear_selection(groups: List[Group]) -> None:
    for g in groups:
        g.selected = False


def set_selection(groups: List[Group], picked: List[Group]) -> None:
    clear_selection(groups)
    for g in picked:
        g.selected = True


def selected_player_capital_sig(groups: List[Group]) -> Tuple[str, ...]:
    return tuple(
        sorted(
            g.label
            for g in groups
            if g.side == "player" and g.selected and not g.dead and g.render_capital
        )
    )


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


def export_player_fleet_design(groups: List[Group]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for g in groups:
        if g.side == "player" and g.render_capital and not g.dead:
            rows.append({"class_name": g.class_name, "label": g.label})
    return rows


def build_player_fleet_from_design(
    data: dict,
    *,
    owner_id: str,
    color_id: int,
    design_rows: Optional[List[Dict[str, Any]]] = None,
    label_prefix: str = "",
    spawn_anchor: Optional[Tuple[float, float]] = None,
) -> Tuple[List[Group], List[Craft]]:
    if not design_rows:
        return build_initial_player_fleet(data, owner_id=owner_id, color_id=color_id, label_prefix=label_prefix)
    ax, ay = spawn_anchor if spawn_anchor is not None else deploy_anchor_xy()
    groups: List[Group] = []
    for i, row in enumerate(design_rows):
        r = row or {}
        cls = str(r.get("class_name") or "").strip()
        try:
            sc = ship_class_by_name(data, cls)
        except KeyError:
            continue
        px = ax - 320 + (i % 6) * 150.0
        py = ay + (i // 6) * 56.0
        lbl = str(r.get("label") or f"{RECRUIT_LABEL_PREFIX.get(cls, 'UN')}-{i+1}")
        g = make_group(
            data,
            "player",
            f"{label_prefix}{lbl}",
            cls,
            px,
            py,
            owner_id=owner_id,
            color_id=color_id,
        )
        if sc.get("hangar") and r.get("hangar_loadout_choice") is not None:
            try:
                g.hangar_loadout_choice = int(r["hangar_loadout_choice"])
            except (TypeError, ValueError):
                pass
        groups.append(g)
    if not groups:
        return build_initial_player_fleet(data, owner_id=owner_id, color_id=color_id, label_prefix=label_prefix)
    crafts: List[Craft] = []
    for g in groups:
        if ship_class_by_name(data, g.class_name).get("hangar"):
            crafts.extend(spawn_hangar_crafts(data, g))
    clear_selection(groups)
    groups[0].selected = True
    return groups, crafts


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


def all_player_capital_labels(groups: List[Group]) -> List[str]:
    return [g.label for g in groups if g.side == "player" and not g.dead and g.render_capital]


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


def debrief_panel_rects() -> Tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    h = HEIGHT - DEBRIEF_TOP - DEBRIEF_BOTTOM_PAD
    inner_w = WIDTH - DEBRIEF_MARGIN * 2 - DEBRIEF_PANEL_GAP * 2
    pw = inner_w // 3
    x1 = DEBRIEF_MARGIN
    x2 = DEBRIEF_MARGIN + pw + DEBRIEF_PANEL_GAP
    x3 = DEBRIEF_MARGIN + (pw + DEBRIEF_PANEL_GAP) * 2
    r1 = pygame.Rect(x1, DEBRIEF_TOP, pw, h)
    r2 = pygame.Rect(x2, DEBRIEF_TOP, pw, h)
    r3 = pygame.Rect(x3, DEBRIEF_TOP, WIDTH - DEBRIEF_MARGIN - x3, h)
    return r1, r2, r3


def debrief_purchase_rect(info_panel: pygame.Rect) -> pygame.Rect:
    bar_h = 38
    margin_bot = 12
    return pygame.Rect(
        info_panel.x + DEBRIEF_INNER_PAD,
        info_panel.bottom - margin_bot - bar_h,
        info_panel.w - DEBRIEF_INNER_PAD * 2,
        bar_h,
    )


def debrief_hit_regions() -> Tuple[List[Tuple[pygame.Rect, str]], pygame.Rect, Tuple[pygame.Rect, pygame.Rect, pygame.Rect]]:
    r_ship, r_upg, r_info = debrief_panel_rects()
    purchase_r = debrief_purchase_rect(r_info)
    hit: List[Tuple[pygame.Rect, str]] = []
    y0 = r_ship.y + DEBRIEF_HEADER_H
    for sid in STORE_SHIP_IDS:
        row_r = pygame.Rect(r_ship.x + DEBRIEF_INNER_PAD, y0, r_ship.w - DEBRIEF_INNER_PAD * 2, DEBRIEF_ROW_H)
        hit.append((row_r, sid))
        y0 += DEBRIEF_ROW_H + DEBRIEF_ROW_GAP
    y1 = r_upg.y + DEBRIEF_HEADER_H
    for uid in STORE_UPGRADE_IDS:
        row_r = pygame.Rect(r_upg.x + DEBRIEF_INNER_PAD, y1, r_upg.w - DEBRIEF_INNER_PAD * 2, DEBRIEF_ROW_H)
        hit.append((row_r, uid))
        y1 += DEBRIEF_ROW_H + DEBRIEF_ROW_GAP
    return hit, purchase_r, (r_ship, r_upg, r_info)


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


def draw_debrief_store(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    font_micro: pygame.font.Font,
    font_big: pygame.font.Font,
    round_idx: int,
    run_total_score: int,
    salvage: List[int],
    last_salvage_gain: int,
    store_selected: Optional[str],
    store_hover: Optional[str],
    cap_n: int,
    info_lines: List[str],
) -> None:
    hit, purchase_r, (r_ship, r_upg, r_info) = debrief_hit_regions()

    def draw_panel_frame(r: pygame.Rect, title: str, accent: Tuple[int, int, int]) -> int:
        pygame.draw.rect(surf, (14, 22, 34), r, border_radius=10)
        pygame.draw.rect(surf, accent, r, width=2, border_radius=10)
        t = font_big.render(title, True, accent)
        surf.blit(t, (r.x + DEBRIEF_INNER_PAD, r.y + 8))
        return r.y + DEBRIEF_HEADER_H

    # Header strip
    banner = f"Round {round_idx} complete  ·  score {run_total_score}  ·  salvage {salvage[0]} (+{last_salvage_gain} this jump)  ·  capitals {cap_n}/{MAX_PLAYER_CAPITALS}"
    bt = font_big.render(banner, True, (200, 220, 240))
    surf.blit(bt, (WIDTH // 2 - bt.get_width() // 2, 28))

    y0 = draw_panel_frame(r_ship, "SHIPS — commission", (100, 180, 255))
    ship_labels = (
        ("Frigate", f"{COST_FRIGATE}", "[1]"),
        ("Destroyer", f"{COST_DESTROYER}", "[2]"),
        ("Cruiser", f"{COST_CRUISER}", "[3]"),
        ("Battleship", f"{COST_BATTLESHIP}", "[4]"),
        ("Carrier", f"{COST_CARRIER}", "[5]"),
    )
    for i, sid in enumerate(STORE_SHIP_IDS):
        name, cost, hk = ship_labels[i]
        row_r = hit[i][0]
        sel = store_selected == sid
        hov = store_hover == sid
        bg = (28, 44, 62) if sel else (22, 34, 48) if hov else (18, 28, 40)
        pygame.draw.rect(surf, bg, row_r, border_radius=6)
        if sel:
            pygame.draw.rect(surf, (140, 200, 255), row_r, width=1, border_radius=6)
        t1 = font.render(f"{hk}  {name}", True, (230, 240, 250))
        t2 = font_tiny.render(f"{cost} salvage", True, (160, 190, 210))
        surf.blit(t1, (row_r.x + 8, row_r.y + 4))
        surf.blit(t2, (row_r.right - t2.get_width() - 8, row_r.y + 7))
        y0 = row_r.bottom + DEBRIEF_ROW_GAP

    y1 = draw_panel_frame(r_upg, "UPGRADES", (120, 220, 170))
    upg_labels = (
        ("Repair & revive", str(COST_REPAIR), "[6]"),
        ("Resupply +28", str(COST_RESUPPLY), "[7]"),
        ("CIWS tuning", str(COST_CIWS), "[8]"),
        ("Bulkhead refit", str(COST_BULKHEAD), "[9]"),
        ("Combat stores", str(COST_LIGHT_RESUPPLY), "[0]"),
    )
    for i, uid in enumerate(STORE_UPGRADE_IDS):
        title, cost, hk = upg_labels[i]
        row_r = hit[len(STORE_SHIP_IDS) + i][0]
        sel = store_selected == uid
        hov = store_hover == uid
        bg = (28, 52, 44) if sel else (22, 42, 36) if hov else (18, 34, 30)
        pygame.draw.rect(surf, bg, row_r, border_radius=6)
        if sel:
            pygame.draw.rect(surf, (140, 240, 190), row_r, width=1, border_radius=6)
        t1 = font.render(f"{hk}  {title}", True, (230, 240, 250))
        t2 = font_tiny.render(cost, True, (160, 210, 180))
        surf.blit(t1, (row_r.x + 8, row_r.y + 4))
        surf.blit(t2, (row_r.right - t2.get_width() - 8, row_r.y + 7))
        y1 = row_r.bottom + DEBRIEF_ROW_GAP

    y2 = draw_panel_frame(r_info, "BRIEFING", (220, 190, 120))
    info_body = pygame.Rect(
        r_info.x + DEBRIEF_INNER_PAD,
        y2,
        r_info.w - DEBRIEF_INNER_PAD * 2,
        max(64, purchase_r.y - y2 - 8),
    )
    pygame.draw.rect(surf, (12, 20, 30), info_body, border_radius=8)
    iy = info_body.y + 8
    for line in info_lines:
        if iy > info_body.bottom - 14:
            break
        col = (255, 140, 120) if line.startswith("—") else (200, 210, 225)
        f = font_micro if len(line) > 56 else font_tiny
        if line == "":
            iy += 6
            continue
        surf.blit(f.render(line, True, col), (info_body.x + 10, iy))
        iy += 15

    pygame.draw.rect(surf, (40, 55, 70), purchase_r, border_radius=8)
    pygame.draw.rect(surf, (130, 170, 200), purchase_r, width=1, border_radius=8)
    pt = font_big.render("PURCHASE  (ENTER)", True, (220, 235, 250))
    surf.blit(pt, (purchase_r.centerx - pt.get_width() // 2, purchase_r.centery - pt.get_height() // 2))

    foot = font_tiny.render("SPACE — next engagement    Ctrl+Q — quit", True, (150, 170, 190))
    surf.blit(foot, (WIDTH // 2 - foot.get_width() // 2, HEIGHT - 32))


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


def pause_main_menu_button_rect() -> pygame.Rect:
    """Pause overlay: 'Back to main menu' (for now exits the game)."""
    return pygame.Rect(WIDTH // 2 - 150, HEIGHT - 86, 300, 48)


def pause_combat_help_lines(formation_mode: int) -> List[str]:
    """Full controls reference shown only on the pause overlay."""
    fm = FORMATION_MODE_NAMES[formation_mode]
    return [
        "",
        "CAMERA",
        "  WASD — pan the battlefield",
        "",
        "SELECTION",
        "  LMB — select a capital   Shift+LMB — add/remove from selection",
        "  Shift+drag — box select   double-click capital — same class on screen",
        "",
        "MOVEMENT & ORDERS",
        "  RMB — move to point   Shift+drag — line formation move",
        "  Same move order: capitals match the slowest selected hull; solo / new order = full speed",
        "  With capitals selected: RMB enemy or strike relay — focus fire (or [G] then LMB)",
        "  A then LMB — attack-move (fight along the route)",
        "  [G] then LMB — same as RMB-on-enemy focus fire (optional)",
        "  H — hold / clear waypoint (carrier: also clears strike rally)",
        "  Home — focus camera on selection (or whole fleet if none selected)",
        "",
        "WEAPONS (per control group)",
        "  Default HOLD — capitals & their strike craft do not open fire until:",
        "    attack-move, focus target (RMB enemy / [G] / Attack), strip FREE, under fire, or mate in same Ctrl group hit",
        "  Bottom-right orders panel — Attack then LMB (or RMB enemy with selection); weapons strip: HOLD ↔ FREE",
        "",
        "FORMATIONS & CONTROL GROUPS",
        f"  B — cycle formation (current: {fm})",
        "  Ctrl+1–9 — save group from current selection",
        "  1–9 — recall group   Shift+1–9 — add group to selection",
        "  All starting capitals begin in group 1; recruited ships join group 1",
        "  Bottom bar — click slots 1–9 (same as number keys)",
        "",
        "CARRIER / STRIKE CRAFT",
        "  Carrier selected + [F]: LMB = fighter wing order, RMB = bomber wing — enemy/strike relay = attack, empty map = rally",
        "  Fighters/bombers on-map selected + [F]: that wing only (LMB or RMB for fighters; RMB for bombers). Other capitals + F → fleet LMB",
        "  [G] — attack-only LMB",
        "  [7] / [8] — select fighter or bomber wing on map (Shift: add)   [9] — clear strike craft selection",
        "  LMB on strike craft — select that wing   C — recall selected carriers & clear wing rallies",
        "",
        "SENSORS & FOG",
        "  Capitals & strike craft reveal nearby tiles; dark = unseen, dim = remembered",
        "  [P] or Orders “Ping” — brief sweep; contacts fade fast or vanish if you deselect pingers",
        "  Your missiles/torpedoes visible on sensors but lock still in shadow — faint “Seeker contact” trace",
        "",
        "STATUS (BATTLEFIELD)",
        "  Bottom bar — round, formation, salvage, supplies, mission goal",
        "",
        "GAME & WINDOW",
        "  F8 — voice link test   F1 — test menu (cheats / test store)",
        "  ESC — pause (this screen)   Ctrl+Q — quit to desktop",
        "  Resize the window — battle scales to fit",
    ]


def order_panel_screen_rect() -> pygame.Rect:
    return pygame.Rect(WIDTH - ORDER_PANEL_W, VIEW_H, ORDER_PANEL_W, BOTTOM_BAR_H)


def control_group_slot_rect(slot_i: int) -> pygame.Rect:
    slot_w, gap, top_m = 52, 4, 8
    x0 = 8 + slot_i * (slot_w + gap)
    return pygame.Rect(x0, VIEW_H + top_m, slot_w, BOTTOM_BAR_H - top_m * 2)


def order_command_cells() -> List[Tuple[pygame.Rect, str, str]]:
    """Rects (internal coords), action id, label for bottom-right order buttons."""
    r = order_panel_screen_rect()
    pad = 5
    top_title = 14
    stance_reserve = ORDER_PANEL_STANCE_STRIP_H
    bw = max(40, (r.w - pad * 3) // 2)
    inner_h = max(48, r.h - pad * 2 - top_title - stance_reserve)
    bh = max(12, (inner_h - 20) // 6)
    specs = [
        ("Move", "move"),
        ("Attack-move", "attack_move"),
        ("Attack", "attack_target"),
        ("Hold", "hold"),
        ("Formation", "formation"),
        ("Air order (F)", "strike"),
        ("Recall CV", "recall"),
        ("Ping", "ping"),
        ("Focus map", "focus"),
    ]
    out: List[Tuple[pygame.Rect, str, str]] = []
    for i, (lab, act) in enumerate(specs):
        row, col = divmod(i, 2)
        x = r.x + pad + col * (bw + pad)
        y = r.y + pad + top_title + row * (bh + 4)
        out.append((pygame.Rect(x, y, bw, bh), act, lab))
    return out


@dataclass
class ConfigMenuLayout:
    panel: pygame.Rect
    volume_track: pygame.Rect
    tts_toggle: pygame.Rect
    design_fleet_btn: pygame.Rect
    battlegroups_btn: pygame.Rect
    multiplayer_btn: pygame.Rect


def config_menu_layout() -> ConfigMenuLayout:
    pw, ph = 580, 468
    panel = pygame.Rect(WIDTH // 2 - pw // 2, HEIGHT // 2 - ph // 2, pw, ph)
    volume_track = pygame.Rect(panel.centerx - 210, panel.y + 128, 420, 16)
    tts_toggle = pygame.Rect(panel.centerx - 76, panel.y + 196, 152, 34)
    design_fleet_btn = pygame.Rect(panel.centerx - 130, panel.y + 312, 260, 44)
    battlegroups_btn = pygame.Rect(panel.centerx - 130, panel.y + 364, 260, 44)
    multiplayer_btn = pygame.Rect(panel.centerx - 130, panel.y + 416, 260, 44)
    return ConfigMenuLayout(panel, volume_track, tts_toggle, design_fleet_btn, battlegroups_btn, multiplayer_btn)


@dataclass
class MPHubLayout:
    panel: pygame.Rect
    art_rect: pygame.Rect
    name_entry_rect: pygame.Rect
    join_entry_rect: pygame.Rect
    lobby_list_rect: pygame.Rect
    authority_strip: pygame.Rect
    btn_host: pygame.Rect
    btn_quick_join: pygame.Rect
    btn_srv_create: pygame.Rect
    btn_srv_join: pygame.Rect
    btn_back: pygame.Rect


def mp_hub_menu_layout() -> MPHubLayout:
    pw, ph = 820, 640
    panel = pygame.Rect(WIDTH // 2 - pw // 2, HEIGHT // 2 - ph // 2, pw, ph)
    bw, bh = 320, 36
    gap = 8
    n = 5
    stack_h = n * bh + (n - 1) * gap
    y0 = panel.bottom - 20 - stack_h
    art_rect = pygame.Rect(panel.x + 24, panel.y + 78, panel.w - 48, max(220, y0 - panel.y - 88))
    name_entry_rect = pygame.Rect(art_rect.x + 10, art_rect.y + 6, art_rect.w - 20, 46)
    join_entry_rect = pygame.Rect(art_rect.x + 10, name_entry_rect.bottom + 6, art_rect.w - 20, 44)
    footer_reserve = 30
    list_top = join_entry_rect.bottom + 8
    list_h = max(72, art_rect.bottom - list_top - footer_reserve)
    lobby_list_rect = pygame.Rect(art_rect.x + 10, list_top, art_rect.w - 20, list_h)
    authority_strip = pygame.Rect(art_rect.x + 10, lobby_list_rect.bottom + 4, art_rect.w - 20, 22)
    bx = panel.centerx - bw // 2
    return MPHubLayout(
        panel,
        art_rect,
        name_entry_rect,
        join_entry_rect,
        lobby_list_rect,
        authority_strip,
        pygame.Rect(bx, y0, bw, bh),
        pygame.Rect(bx, y0 + bh + gap, bw, bh),
        pygame.Rect(bx, y0 + (bh + gap) * 2, bw, bh),
        pygame.Rect(bx, y0 + (bh + gap) * 3, bw, bh),
        pygame.Rect(bx, y0 + (bh + gap) * 4, bw, bh),
    )


@dataclass
class MPLobbyLayout:
    panel: pygame.Rect
    settings_col: pygame.Rect
    players_col: pygame.Rect
    row_mode: pygame.Rect
    row_mission: pygame.Rect
    row_rocks: pygame.Rect
    row_enemy: pygame.Rect
    chat_log_rect: pygame.Rect
    chat_input_rect: pygame.Rect
    btn_fleet: pygame.Rect
    btn_ready: pygame.Rect
    btn_start: pygame.Rect
    btn_back: pygame.Rect


def mp_lobby_menu_layout() -> MPLobbyLayout:
    m = 36
    panel = pygame.Rect(m, m, WIDTH - m * 2, HEIGHT - m * 2)
    split = panel.x + int(panel.w * 0.52)
    settings_col = pygame.Rect(panel.x + 16, panel.y + 72, split - panel.x - 32, panel.h - 160)
    players_col = pygame.Rect(split + 8, panel.y + 72, panel.right - split - 24, panel.h - 160)
    rw = settings_col.w - 8
    ry = settings_col.y + 8
    rh = 36
    rg = 10
    row_mode = pygame.Rect(settings_col.x + 4, ry, rw, rh)
    row_mission = pygame.Rect(settings_col.x + 4, ry + rh + rg, rw, rh)
    row_rocks = pygame.Rect(settings_col.x + 4, ry + (rh + rg) * 2, rw, rh)
    row_enemy = pygame.Rect(settings_col.x + 4, ry + (rh + rg) * 3, rw, rh)
    chat_top = row_enemy.bottom + 10
    chat_in_h = 28
    chat_log_rect = pygame.Rect(
        settings_col.x + 4,
        chat_top,
        settings_col.w - 8,
        max(48, settings_col.bottom - chat_top - chat_in_h - 12),
    )
    chat_input_rect = pygame.Rect(
        settings_col.x + 4,
        chat_log_rect.bottom + 6,
        settings_col.w - 8,
        chat_in_h,
    )
    bw, bh = 200, 40
    gap = 10
    bx0 = panel.x + 24
    by = panel.bottom - 56
    return MPLobbyLayout(
        panel,
        settings_col,
        players_col,
        row_mode,
        row_mission,
        row_rocks,
        row_enemy,
        chat_log_rect,
        chat_input_rect,
        pygame.Rect(bx0, by, bw, bh),
        pygame.Rect(bx0 + bw + gap, by, bw, bh),
        pygame.Rect(bx0 + (bw + gap) * 2, by, 220, bh),
        pygame.Rect(panel.right - 180, by, 156, bh),
    )


@dataclass
class ShipLoadoutsMenuLayout:
    panel: pygame.Rect
    roster_rect: pygame.Rect
    detail_rect: pygame.Rect
    yard_rect: pygame.Rect
    back_btn: pygame.Rect
    launch_btn: pygame.Rect


def ship_loadouts_menu_layout() -> ShipLoadoutsMenuLayout:
    m = 40
    panel = pygame.Rect(m, m, WIDTH - m * 2, HEIGHT - m * 2)
    inner_w = panel.w - 40
    rw = max(200, int(inner_w * 0.28))
    yw = max(168, int(inner_w * 0.24))
    dw = inner_w - rw - yw - 16
    x0 = panel.x + 20
    x1 = x0 + rw + 8
    x2 = x1 + dw + 8
    top = panel.y + 72
    h = panel.h - 168
    roster_rect = pygame.Rect(x0, top, rw, h)
    detail_rect = pygame.Rect(x1, top, max(220, dw), h)
    yard_rect = pygame.Rect(x2, top, yw, h)
    back_btn = pygame.Rect(panel.x + 24, panel.bottom - 54, 152, 42)
    launch_btn = pygame.Rect(panel.right - 264, panel.bottom - 54, 240, 44)
    return ShipLoadoutsMenuLayout(panel, roster_rect, detail_rect, yard_rect, back_btn, launch_btn)


def ship_loadouts_yard_strip_rect() -> pygame.Rect:
    yr = ship_loadouts_menu_layout().yard_rect
    return pygame.Rect(yr.x + 8, yr.y + 52, yr.w - 16, 30)


def ship_loadouts_yard_recruit_rects() -> List[Tuple[pygame.Rect, str]]:
    lay = ship_loadouts_menu_layout()
    yr = lay.yard_rect
    y = ship_loadouts_yard_strip_rect().bottom + 14
    out: List[Tuple[pygame.Rect, str]] = []
    for cname in STORE_SHIP_CLASSES:
        out.append((pygame.Rect(yr.x + 8, y, yr.w - 16, 28), cname))
        y += 32
    return out


LOADOUT_ROSTER_ROW = 36
LOADOUT_HP_CHIP_W = 108
LOADOUT_HP_CHIP_H = 24
LOADOUT_HP_GAP = 5
LOADOUT_HANGAR_CHIP_W = 132
LOADOUT_DETAIL_BEFORE_HARDPOINTS = 110


def layout_hardpoint_chips(
    g: Group,
    data: dict,
    dx: int,
    y0: int,
    max_right: int,
) -> Tuple[int, List[Tuple[pygame.Rect, int, int]]]:
    sc = ship_class_by_name(data, g.class_name)
    opts = weapon_loadout_options_expanded(data, sc)
    hits: List[Tuple[pygame.Rect, int, int]] = []
    y = y0
    for si, slot in enumerate(opts):
        y += 20
        cx, row_y = dx, y
        for ci in range(len(slot["choices"])):
            r = pygame.Rect(cx, row_y, LOADOUT_HP_CHIP_W, LOADOUT_HP_CHIP_H)
            hits.append((r, si, ci))
            cx += LOADOUT_HP_CHIP_W + LOADOUT_HP_GAP
            if cx + LOADOUT_HP_CHIP_W > max_right:
                cx = dx
                row_y += LOADOUT_HP_CHIP_H + LOADOUT_HP_GAP
        y = row_y + LOADOUT_HP_CHIP_H + 14
    return y, hits


def layout_hangar_preset_chips(
    g: Group,
    data: dict,
    dx: int,
    y0: int,
    max_right: int,
) -> Tuple[int, List[Tuple[pygame.Rect, int]]]:
    sc = ship_class_by_name(data, g.class_name)
    presets = (sc.get("hangar") or {}).get("loadout_presets") or []
    if not presets:
        return y0, []
    hits: List[Tuple[pygame.Rect, int]] = []
    cy = y0
    cx = dx
    W = LOADOUT_HANGAR_CHIP_W
    for pi in range(len(presets)):
        r = pygame.Rect(cx, cy, W, LOADOUT_HP_CHIP_H)
        hits.append((r, pi))
        cx += W + LOADOUT_HP_GAP
        if cx + W > max_right:
            cx = dx
            cy += LOADOUT_HP_CHIP_H + LOADOUT_HP_GAP
    return cy + LOADOUT_HP_CHIP_H + 8, hits


def ship_loadouts_hardpoint_area_y0(lay: ShipLoadoutsMenuLayout) -> int:
    return lay.detail_rect.y + 14 + LOADOUT_DETAIL_BEFORE_HARDPOINTS


def ship_loadouts_resolve_click(
    mx: int,
    my: int,
    data: dict,
    preview_groups: List[Group],
    selected_i: int,
    roster_scroll: int,
) -> Optional[Tuple[Any, ...]]:
    lay = ship_loadouts_menu_layout()
    if lay.back_btn.collidepoint(mx, my):
        return ("back",)
    if lay.launch_btn.collidepoint(mx, my):
        return ("launch",)
    ri = loadout_roster_row_at_mouse(mx, my, preview_groups, roster_scroll)
    if ri is not None:
        return ("roster", ri)
    if ship_loadouts_yard_strip_rect().collidepoint(mx, my):
        return ("strip",)
    for r, cname in ship_loadouts_yard_recruit_rects():
        if r.collidepoint(mx, my):
            return ("recruit", cname)
    roster = loadout_player_capitals_sorted(preview_groups)
    if 0 <= selected_i < len(roster):
        sg = roster[selected_i]
        dr = lay.detail_rect
        y0 = ship_loadouts_hardpoint_area_y0(lay)
        hp_end, hits = layout_hardpoint_chips(sg, data, dr.x + 16, y0, dr.right - 12)
        for hr, si, ci in hits:
            if hr.collidepoint(mx, my):
                return ("hardpoint", sg.label, si, ci)
        if sg.class_name == "Carrier":
            _, hh = layout_hangar_preset_chips(sg, data, dr.x + 16, hp_end + 40, dr.right - 12)
            for hr, pi in hh:
                if hr.collidepoint(mx, my):
                    return ("hangar", sg.label, pi)
    return None


def _wrap_ui_text(s: str, width: int) -> List[str]:
    words = s.replace("\n", " ").split()
    lines: List[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def weapon_loadout_hover_lines(
    data: dict,
    sc: dict,
    slot_i: int,
    choice_i: int,
    g: Group,
    choice_map: Dict[Tuple[str, int], int],
) -> List[str]:
    opts = weapon_loadout_options_expanded(data, sc)
    if slot_i < 0 or slot_i >= len(opts):
        return []
    slot = opts[slot_i]
    choices = slot["choices"]
    if choice_i < 0 or choice_i >= len(choices):
        return []
    ch = choices[choice_i]
    wn, pn, fr = resolve_weapon_entry(data, ch)
    scrap = int(ch.get("scrap_cost", 0))
    cur_ci = choice_map.get((g.label, slot_i), 0)
    cur_scrap = int(choices[cur_ci].get("scrap_cost", 0))
    net = scrap - cur_scrap
    slot_lab = slot.get("label") or f"Mount {slot_i}"
    proj = projectile_by_name(data, pn)
    wr = weapon_range(data, {"projectile": pn, "fire_rate": fr})
    lines: List[str] = [
        wn.upper(),
        slot_lab,
        "",
        f"Ammo / beam: {pn}",
        f"Fire rate: {fr:.2f} s⁻¹",
        f"Range (est.): ~{wr:.0f}",
        f"Delivery: {proj.get('delivery', '?')}",
        f"Damage / shot: {proj.get('damage', '?')}",
    ]
    if proj.get("damageType"):
        lines.append(f"Damage type: {proj['damageType']}")
    if proj.get("delivery") == "missile":
        lines.append(f"Missile speed: {proj.get('speed', '?')}")
        if "lifetime" in proj:
            lines.append(f"Lifetime: {proj['lifetime']} s")
    lines.extend(["", f"Loadout tier: {scrap} scrap"])
    if choice_i != cur_ci:
        if net > 0:
            lines.append(f"Swap vs equipped: +{net} scrap")
        elif net < 0:
            lines.append(f"Refund vs equipped: {-net} scrap")
        else:
            lines.append("Same tier as equipped — no scrap change")
    desc = str(proj.get("description") or "")
    if desc:
        lines.append("")
        for chunk in _wrap_ui_text(desc, 40)[:6]:
            lines.append(chunk)
    return lines


def hangar_preset_hover_lines(
    data: dict,
    sc: dict,
    preset_i: int,
    cur_i: int,
) -> List[str]:
    presets = (sc.get("hangar") or {}).get("loadout_presets") or []
    if not presets or preset_i < 0 or preset_i >= len(presets):
        return []
    pr = presets[preset_i]
    label = str(pr.get("label", f"Preset {preset_i}"))
    sc_cost = int(pr.get("scrap_cost", 0))
    cur_c = int(presets[cur_i].get("scrap_cost", 0)) if 0 <= cur_i < len(presets) else 0
    net = sc_cost - cur_c
    lines: List[str] = [label.upper(), "Air wing preset", ""]
    for sq in pr.get("squadrons") or []:
        lines.append(f"  {int(sq.get('count', 0))}× {sq.get('class', '?')}")
    lines.extend(["", f"Tier: {sc_cost} scrap"])
    if preset_i != cur_i:
        if net > 0:
            lines.append(f"Swap vs current: +{net} scrap")
        elif net < 0:
            lines.append(f"Refund vs current: {-net} scrap")
        else:
            lines.append("Same tier — no scrap change")
    return lines


def ship_loadouts_weapon_or_hangar_hover(
    mx: int,
    my: int,
    data: dict,
    preview_groups: List[Group],
    selected_i: int,
) -> Optional[Tuple[Any, ...]]:
    lay = ship_loadouts_menu_layout()
    dr = lay.detail_rect
    if not dr.collidepoint(mx, my):
        return None
    roster = loadout_player_capitals_sorted(preview_groups)
    if not (0 <= selected_i < len(roster)):
        return None
    sg = roster[selected_i]
    dx = dr.x + 16
    hp_y0 = ship_loadouts_hardpoint_area_y0(lay)
    hp_end, hits = layout_hardpoint_chips(sg, data, dx, hp_y0, dr.right - 12)
    for hr, si, ci in hits:
        if hr.collidepoint(mx, my):
            return ("hardpoint", sg.label, si, ci)
    if sg.class_name == "Carrier":
        _, hh = layout_hangar_preset_chips(sg, data, dx, hp_end + 40, dr.right - 12)
        for hr, pi in hh:
            if hr.collidepoint(mx, my):
                return ("hangar", sg.label, pi)
    return None


def ship_loadouts_inspect_tooltip_lines(
    mx: int,
    my: int,
    data: dict,
    preview_groups: List[Group],
    selected_i: int,
    choice_map: Dict[Tuple[str, int], int],
) -> List[str]:
    hit = ship_loadouts_weapon_or_hangar_hover(mx, my, data, preview_groups, selected_i)
    if hit is None:
        return []
    roster = loadout_player_capitals_sorted(preview_groups)
    if not (0 <= selected_i < len(roster)):
        return []
    sg = roster[selected_i]
    sc = ship_class_by_name(data, sg.class_name)
    if hit[0] == "hardpoint":
        return weapon_loadout_hover_lines(data, sc, int(hit[2]), int(hit[3]), sg, choice_map)
    if hit[0] == "hangar":
        presets = (sc.get("hangar") or {}).get("loadout_presets") or []
        cur_h = max(0, min(int(sg.hangar_loadout_choice), len(presets) - 1)) if presets else 0
        return hangar_preset_hover_lines(data, sc, int(hit[2]), cur_h)
    return []


def draw_ship_loadout_inspect_tooltip(
    surf: pygame.Surface,
    font_tiny: pygame.font.Font,
    lines: List[str],
    mx: int,
    my: int,
    panel_bounds: pygame.Rect,
) -> None:
    if not lines:
        return
    pad = 10
    line_h = font_tiny.get_height() + 3
    nonempty = [L for L in lines if L]
    tw = max((font_tiny.size(L)[0] for L in nonempty), default=120)
    want_w = min(max(tw + pad * 2, 168), panel_bounds.right - panel_bounds.x - 12)
    want_h = min(len(lines) * line_h + pad * 2, panel_bounds.bottom - panel_bounds.y - 12)
    x = mx + 14
    y = my + 14
    x = max(panel_bounds.x + 6, min(x, panel_bounds.right - want_w - 6))
    y = max(panel_bounds.y + 6, min(y, panel_bounds.bottom - want_h - 6))
    r = pygame.Rect(x, y, want_w, want_h)
    bg = pygame.Surface((want_w, want_h), pygame.SRCALPHA)
    bg.fill((10, 18, 28, 244))
    surf.blit(bg, r.topleft)
    pygame.draw.rect(surf, (88, 138, 178), r, width=1, border_radius=10)
    yy = r.y + pad
    for L in lines:
        if L:
            surf.blit(font_tiny.render(L, True, (195, 210, 228)), (r.x + pad, yy))
        yy += line_h


def loadout_player_capitals_sorted(groups: List[Group]) -> List[Group]:
    caps = [g for g in groups if g.side == "player" and not g.dead and g.render_capital]
    return sorted(caps, key=lambda g: (g.label, g.class_name))


def clamp_loadout_roster_scroll(preview_groups: List[Group], scroll: int) -> int:
    lay = ship_loadouts_menu_layout()
    n = len(loadout_player_capitals_sorted(preview_groups))
    max_scroll = max(0, n * LOADOUT_ROSTER_ROW - lay.roster_rect.h + 16)
    return max(0, min(int(scroll), max_scroll))


def loadout_roster_row_at_mouse(
    mx: int, my: int, preview_groups: List[Group], scroll: int
) -> Optional[int]:
    lay = ship_loadouts_menu_layout()
    if not lay.roster_rect.collidepoint(mx, my):
        return None
    roster = loadout_player_capitals_sorted(preview_groups)
    inner_y = my - lay.roster_rect.y - 8 + scroll
    if inner_y < 0:
        return None
    i = inner_y // LOADOUT_ROSTER_ROW
    if 0 <= i < len(roster):
        return i
    return None


def draw_ship_loadouts_menu(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    font_micro: pygame.font.Font,
    font_big: pygame.font.Font,
    data: dict,
    preview_groups: List[Group],
    preview_crafts: List[Craft],
    selected_i: int,
    roster_scroll: int,
    deployment_scrap: List[int],
    choice_map: Dict[Tuple[str, int], int],
    mouse_internal: Optional[Tuple[int, int]] = None,
    *,
    launch_btn_label: str = "Launch mission",
    subtitle: str = "Spend deployment scrap on hulls & weapon swaps · starting task group is free",
    title: str = "Ship loadouts — fleet design",
    footer_bar: Optional[str] = None,
) -> None:
    lay = ship_loadouts_menu_layout()
    pygame.draw.rect(surf, (8, 14, 22), lay.panel, border_radius=16)
    pygame.draw.rect(surf, (48, 88, 118), lay.panel, width=2, border_radius=16)

    title_surf = font_big.render(title, True, (230, 240, 250))
    surf.blit(title_surf, (lay.panel.x + 22, lay.panel.y + 18))
    sub_surf = font_tiny.render(subtitle, True, (155, 175, 198))
    surf.blit(sub_surf, (lay.panel.x + 22, lay.panel.y + 46))

    roster = loadout_player_capitals_sorted(preview_groups)
    n_craft = sum(1 for c in preview_crafts if c.side == "player" and not c.dead and not c.parent.dead)
    cap_n = len(roster)

    pygame.draw.rect(surf, (14, 24, 36), lay.roster_rect, border_radius=10)
    pygame.draw.rect(surf, (55, 85, 105), lay.roster_rect, width=1, border_radius=10)
    rh = font.render("Task group (capitals)", True, (190, 210, 225))
    surf.blit(rh, (lay.roster_rect.x + 10, lay.roster_rect.y - 22))

    scroll = clamp_loadout_roster_scroll(preview_groups, roster_scroll)

    clip = surf.get_clip()
    surf.set_clip(lay.roster_rect.inflate(-8, -8))
    try:
        for i, g in enumerate(roster):
            ry = lay.roster_rect.y + 8 + i * LOADOUT_ROSTER_ROW - scroll
            if ry + LOADOUT_ROSTER_ROW < lay.roster_rect.y or ry > lay.roster_rect.bottom:
                continue
            row_r = pygame.Rect(lay.roster_rect.x + 6, ry, lay.roster_rect.w - 12, LOADOUT_ROSTER_ROW - 4)
            sel = i == selected_i
            pygame.draw.rect(surf, (28, 52, 72) if sel else (18, 30, 44), row_r, border_radius=6)
            pygame.draw.rect(
                surf, (120, 190, 230) if sel else (50, 70, 88), row_r, width=1, border_radius=6
            )
            line = f"{g.label}  ·  {g.class_name}"
            t = font.render(line, True, (230, 238, 248) if sel else (200, 210, 220))
            surf.blit(t, (row_r.x + 8, row_r.centery - t.get_height() // 2))
    finally:
        surf.set_clip(clip)

    pygame.draw.rect(surf, (14, 24, 36), lay.detail_rect, border_radius=10)
    pygame.draw.rect(surf, (55, 85, 105), lay.detail_rect, width=1, border_radius=10)
    dx, dy = lay.detail_rect.x + 16, lay.detail_rect.y + 14
    dh = font.render("Fitting bay", True, (190, 215, 235))
    surf.blit(dh, (dx, dy))
    dy += 28

    if 0 <= selected_i < len(roster):
        sg = roster[selected_i]
        surf.blit(font.render(f"{sg.label}  ·  {sg.class_name}", True, (240, 250, 255)), (dx, dy))
        dy += 22
        surf.blit(
            font_tiny.render(
                f"Hull HP {sg.hp:.0f}/{sg.max_hp:.0f}   Max range ~{sg.max_range:.0f}   Cruise speed ~{sg.speed:.0f}",
                True,
                (165, 185, 205),
            ),
            (dx, dy),
        )
        dy += 36
        surf.blit(
            font.render(
                "Hardpoints — hover for stats · click to swap (scrap refunds on downgrade)",
                True,
                (185, 200, 218),
            ),
            (dx, dy),
        )
        dy += 24

        sc = ship_class_by_name(data, sg.class_name)
        opts = weapon_loadout_options_expanded(data, sc)
        hp_y0 = ship_loadouts_hardpoint_area_y0(lay)
        hp_end, chip_hits = layout_hardpoint_chips(sg, data, dx, hp_y0, lay.detail_rect.right - 12)
        last_si = -1
        for r, si, ci in chip_hits:
            if si != last_si:
                slab = opts[si].get("label") or f"Slot {si}"
                surf.blit(font_tiny.render(slab, True, (175, 195, 215)), (dx, r.y - 18))
                last_si = si
            ch = opts[si]["choices"][ci]
            choices = opts[si]["choices"]
            cur = choice_map.get((sg.label, si), 0)
            cost = int(ch.get("scrap_cost", 0))
            cur_c = int(choices[cur].get("scrap_cost", 0))
            net_scrap = cost - cur_c
            need_pay = max(0, net_scrap)
            affordable = deployment_scrap[0] >= need_pay or ci == cur
            base = (38, 62, 88) if ci != cur else (48, 92, 78)
            if not affordable and ci != cur:
                base = (34, 38, 44)
            pygame.draw.rect(surf, base, r, border_radius=5)
            pygame.draw.rect(
                surf,
                (130, 200, 230) if ci == cur else (70, 100, 120),
                r,
                width=1,
                border_radius=5,
            )
            nm, _, _ = resolve_weapon_entry(data, ch)
            nm = nm[:11]
            if ci != cur and net_scrap != 0:
                tx = f"{nm[:7]}{net_scrap:+d}"
            else:
                tx = nm[:11]
            col = (230, 240, 250) if affordable or ci == cur else (110, 120, 130)
            surf.blit(font_micro.render(tx, True, col), (r.x + 4, r.centery - 6))
        if sg.class_name == "Carrier":
            presets = (sc.get("hangar") or {}).get("loadout_presets") or []
            if presets:
                hy = hp_end + 14
                surf.blit(
                    font.render(
                        "Air wing — hover for wing · presets (scrap refunds on downgrade)",
                        True,
                        (185, 200, 218),
                    ),
                    (dx, hy),
                )
                hy2 = hy + 26
                _, hg_hits = layout_hangar_preset_chips(sg, data, dx, hy2, lay.detail_rect.right - 12)
                cur_h = max(0, min(int(sg.hangar_loadout_choice), len(presets) - 1))
                for r, pi in hg_hits:
                    pr = presets[pi]
                    label = str(pr.get("label", f"Preset {pi}"))[:14]
                    cost = int(pr.get("scrap_cost", 0))
                    old_c = int(presets[cur_h].get("scrap_cost", 0))
                    net_scrap = cost - old_c
                    need_pay = max(0, net_scrap)
                    affordable = deployment_scrap[0] >= need_pay or pi == cur_h
                    base = (42, 58, 82) if pi != cur_h else (48, 92, 78)
                    if not affordable and pi != cur_h:
                        base = (34, 38, 44)
                    pygame.draw.rect(surf, base, r, border_radius=5)
                    pygame.draw.rect(
                        surf,
                        (130, 200, 230) if pi == cur_h else (70, 100, 120),
                        r,
                        width=1,
                        border_radius=5,
                    )
                    if pi != cur_h and net_scrap != 0:
                        tx = f"{label[:9]}{net_scrap:+d}"
                    else:
                        tx = label[:14]
                    col = (230, 240, 250) if affordable or pi == cur_h else (110, 120, 130)
                    surf.blit(font_micro.render(tx, True, col), (r.x + 4, r.centery - 6))
    else:
        surf.blit(font_tiny.render("Select a ship from the task group list.", True, (160, 175, 190)), (dx, dy))

    pygame.draw.rect(surf, (14, 24, 36), lay.yard_rect, border_radius=10)
    pygame.draw.rect(surf, (55, 85, 105), lay.yard_rect, width=1, border_radius=10)
    yx = lay.yard_rect.x + 10
    yy = lay.yard_rect.y + 12
    surf.blit(font.render("Shipyard", True, (200, 220, 235)), (yx, yy))
    yy += 26
    scrap_v = int(deployment_scrap[0])
    surf.blit(
        font_tiny.render(f"Deployment scrap: {scrap_v}", True, (255, 215, 130)),
        (yx, yy),
    )
    yy += 22
    surf.blit(
        font_micro.render(f"Capitals {cap_n}/{MAX_PLAYER_CAPITALS}  ·  min {DEPLOYMENT_MIN_CAPITALS}", True, (140, 160, 178)),
        (yx, yy),
    )

    strip = ship_loadouts_yard_strip_rect()
    can_strip = cap_n > DEPLOYMENT_MIN_CAPITALS and (0 <= selected_i < len(roster))
    pygame.draw.rect(surf, (72, 48, 52) if can_strip else (40, 44, 50), strip, border_radius=6)
    pygame.draw.rect(surf, (180, 120, 120) if can_strip else (80, 85, 90), strip, width=1, border_radius=6)
    st = font_tiny.render("Strip selected hull (refund)", True, (240, 220, 220) if can_strip else (120, 120, 120))
    surf.blit(st, (strip.centerx - st.get_width() // 2, strip.centery - st.get_height() // 2))

    for r, cname in ship_loadouts_yard_recruit_rects():
        cost = deployment_cost_for_class(data, cname)
        can_buy = scrap_v >= cost and cap_n < MAX_PLAYER_CAPITALS
        pygame.draw.rect(surf, (32, 58, 48) if can_buy else (36, 40, 46), r, border_radius=5)
        pygame.draw.rect(
            surf, (100, 180, 130) if can_buy else (70, 75, 80), r, width=1, border_radius=5
        )
        lab = f"+ {cname[:10]}"
        surf.blit(
            font_micro.render(lab, True, (220, 245, 230) if can_buy else (110, 115, 120)),
            (r.x + 6, r.y + 3),
        )
        surf.blit(
            font_micro.render(f"{cost} scrap", True, (255, 210, 140) if can_buy else (90, 95, 100)),
            (r.x + 6, r.y + 14),
        )

    if mouse_internal is not None:
        mxm, mym = mouse_internal
        tip = ship_loadouts_inspect_tooltip_lines(
            mxm, mym, data, preview_groups, selected_i, choice_map
        )
        if tip:
            draw_ship_loadout_inspect_tooltip(surf, font_tiny, tip, mxm, mym, lay.panel)

    summary_y = lay.panel.bottom - 86
    surf.blit(
        font_micro.render(
            f"Strike craft: {n_craft}   Next: wing presets · fleet points · more hulls in data",
            True,
            (120, 140, 160),
        ),
        (lay.panel.x + 22, summary_y),
    )

    pygame.draw.rect(surf, (48, 58, 72), lay.back_btn, border_radius=8)
    pygame.draw.rect(surf, (130, 150, 175), lay.back_btn, width=1, border_radius=8)
    bt = font.render("Back", True, (220, 230, 240))
    surf.blit(bt, (lay.back_btn.centerx - bt.get_width() // 2, lay.back_btn.centery - bt.get_height() // 2))

    pygame.draw.rect(surf, (38, 92, 68), lay.launch_btn, border_radius=10)
    pygame.draw.rect(surf, (140, 220, 160), lay.launch_btn, width=2, border_radius=10)
    lt = font.render(launch_btn_label, True, (235, 255, 245))
    if lt.get_width() > lay.launch_btn.w - 16:
        lt = font_tiny.render(launch_btn_label, True, (235, 255, 245))
    surf.blit(lt, (lay.launch_btn.centerx - lt.get_width() // 2, lay.launch_btn.centery - lt.get_height() // 2))

    foot_txt = footer_bar or (
        "ESC — audio settings   ENTER — launch   Wheel — scroll roster   Hover chips — module details"
    )
    foot = font_micro.render(foot_txt, True, (125, 145, 165))
    surf.blit(foot, (lay.panel.centerx - foot.get_width() // 2, lay.panel.bottom - 26))


def _config_volume_from_mouse_x(track: pygame.Rect, mx: int, audio: GameAudio) -> None:
    t = (mx - track.x) / max(1, track.w)
    audio.master_volume = max(0.0, min(1.0, float(t)))
    audio.apply_master_volume()


def draw_config_menu(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    font_big: pygame.font.Font,
    audio: GameAudio,
) -> None:
    lay = config_menu_layout()
    pygame.draw.rect(surf, (10, 18, 30), lay.panel, border_radius=14)
    pygame.draw.rect(surf, (55, 100, 130), lay.panel, width=2, border_radius=14)
    title = font_big.render("Before battle", True, (230, 240, 250))
    surf.blit(title, (lay.panel.centerx - title.get_width() // 2, lay.panel.y + 20))
    hint = font_tiny.render("Configure audio & voice, then open fleet design", True, (165, 185, 205))
    surf.blit(hint, (lay.panel.centerx - hint.get_width() // 2, lay.panel.y + 50))

    lab_vol = font.render("Master volume", True, (200, 215, 230))
    surf.blit(lab_vol, (lay.panel.x + 36, lay.volume_track.y - 22))
    pygame.draw.rect(surf, (28, 40, 54), lay.volume_track, border_radius=6)
    fill_w = max(0, int(lay.volume_track.w * audio.master_volume))
    if fill_w > 0:
        fr = lay.volume_track.copy()
        fr.w = fill_w
        pygame.draw.rect(surf, (90, 160, 200), fr, border_radius=6)
    pygame.draw.rect(surf, (120, 170, 210), lay.volume_track, width=1, border_radius=6)
    pct = int(round(audio.master_volume * 100))
    pv = font_tiny.render(f"{pct}%", True, (150, 175, 195))
    surf.blit(pv, (lay.volume_track.right + 10, lay.volume_track.y - 2))

    lab_tts = font.render("Voice announcer (TTS)", True, (200, 215, 230))
    surf.blit(lab_tts, (lay.panel.x + 36, lay.tts_toggle.y - 24))
    on = audio.tts_voice_enabled
    tcol = (55, 95, 72) if on else (72, 55, 58)
    pygame.draw.rect(surf, tcol, lay.tts_toggle, border_radius=8)
    pygame.draw.rect(surf, (140, 190, 160) if on else (190, 140, 140), lay.tts_toggle, width=1, border_radius=8)
    tt = font.render("ON" if on else "OFF", True, (230, 245, 235) if on else (245, 220, 220))
    surf.blit(tt, (lay.tts_toggle.centerx - tt.get_width() // 2, lay.tts_toggle.centery - tt.get_height() // 2))

    pygame.draw.rect(surf, (42, 88, 72), lay.design_fleet_btn, border_radius=10)
    pygame.draw.rect(surf, (130, 210, 170), lay.design_fleet_btn, width=2, border_radius=10)
    bt = font.render("Design fleet", True, (235, 255, 245))
    surf.blit(
        bt,
        (
            lay.design_fleet_btn.centerx - bt.get_width() // 2,
            lay.design_fleet_btn.centery - bt.get_height() // 2,
        ),
    )

    pygame.draw.rect(surf, (58, 78, 118), lay.battlegroups_btn, border_radius=10)
    pygame.draw.rect(surf, (150, 185, 235), lay.battlegroups_btn, width=2, border_radius=10)
    bb = font.render("PvP battlegroups", True, (235, 242, 255))
    surf.blit(
        bb,
        (
            lay.battlegroups_btn.centerx - bb.get_width() // 2,
            lay.battlegroups_btn.centery - bb.get_height() // 2,
        ),
    )

    pygame.draw.rect(surf, (52, 72, 108), lay.multiplayer_btn, border_radius=10)
    pygame.draw.rect(surf, (140, 170, 220), lay.multiplayer_btn, width=2, border_radius=10)
    bm = font.render("Multiplayer (stub)", True, (235, 242, 255))
    surf.blit(
        bm,
        (
            lay.multiplayer_btn.centerx - bm.get_width() // 2,
            lay.multiplayer_btn.centery - bm.get_height() // 2,
        ),
    )

    foot = font_tiny.render(
        "ENTER — design fleet   F8 — voice test   Click PvP battlegroups to edit deploy presets",
        True,
        (140, 160, 178),
    )
    surf.blit(foot, (lay.panel.centerx - foot.get_width() // 2, lay.panel.bottom + 14))


BATTLEGROUP_ENTRY_TAGS: Tuple[str, ...] = ("spawn_edge", "spawn_left", "spawn_right")


@dataclass
class BattlegroupEditorLayout:
    panel: pygame.Rect
    list_rect: pygame.Rect
    btn_back: pygame.Rect
    btn_save: pygame.Rect
    btn_new: pygame.Rect
    btn_del: pygame.Rect
    fld_name: pygame.Rect
    fld_id: pygame.Rect
    fld_cost: pygame.Rect
    btn_tag_prev: pygame.Rect
    btn_tag_next: pygame.Rect
    tag_readout: pygame.Rect
    row_area: pygame.Rect
    lbl_ship: pygame.Rect
    ship_prev: pygame.Rect
    ship_next: pygame.Rect
    btn_add: pygame.Rect
    btn_rm: pygame.Rect


def battlegroup_editor_layout() -> BattlegroupEditorLayout:
    m = 18
    panel = pygame.Rect(m, m, WIDTH - 2 * m, HEIGHT - 2 * m)
    split_x = panel.x + int(panel.w * 0.36)
    list_rect = pygame.Rect(panel.x + 12, panel.y + 52, split_x - panel.x - 20, panel.h - 100)
    footer_y = panel.bottom - 46
    btn_back = pygame.Rect(panel.x + 12, footer_y, 100, 36)
    btn_save = pygame.Rect(btn_back.right + 8, footer_y, 100, 36)
    btn_new = pygame.Rect(btn_save.right + 8, footer_y, 100, 36)
    btn_del = pygame.Rect(btn_new.right + 8, footer_y, 100, 36)
    col = split_x + 6
    dw = panel.right - col - 14
    row0 = panel.y + 52
    fld_name = pygame.Rect(col, row0, min(440, dw), 28)
    fld_id = pygame.Rect(col, row0 + 34, min(360, dw), 28)
    fld_cost = pygame.Rect(col, row0 + 68, 90, 28)
    btn_tag_prev = pygame.Rect(fld_cost.right + 10, row0 + 68, 32, 28)
    tag_readout = pygame.Rect(btn_tag_prev.right + 6, row0 + 68, min(220, dw - 200), 28)
    btn_tag_next = pygame.Rect(tag_readout.right + 6, row0 + 68, 32, 28)
    row_top = row0 + 108
    row_area = pygame.Rect(col, row_top, dw, max(120, footer_y - row_top - 44))
    ship_y = row_area.bottom + 8
    lbl_ship = pygame.Rect(col, ship_y, min(340, dw - 140), 26)
    ship_prev = pygame.Rect(lbl_ship.right + 6, ship_y, 30, 26)
    ship_next = pygame.Rect(ship_prev.right + 4, ship_y, 30, 26)
    btn_add = pygame.Rect(ship_next.right + 10, ship_y, 92, 26)
    btn_rm = pygame.Rect(btn_add.right + 8, ship_y, 92, 26)
    return BattlegroupEditorLayout(
        panel,
        list_rect,
        btn_back,
        btn_save,
        btn_new,
        btn_del,
        fld_name,
        fld_id,
        fld_cost,
        btn_tag_prev,
        btn_tag_next,
        tag_readout,
        row_area,
        lbl_ship,
        ship_prev,
        ship_next,
        btn_add,
        btn_rm,
    )


def draw_battlegroup_editor(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    font_big: pygame.font.Font,
    *,
    presets: List[BattlegroupPreset],
    selected_i: int,
    list_scroll: int,
    row_scroll: int,
    name_buf: str,
    id_buf: str,
    cost_buf: str,
    entry_tag: str,
    rows: List[Dict[str, str]],
    ship_pick_i: int,
    cap_names: List[str],
    save_path: str,
    focus: Optional[str],
) -> None:
    lay = battlegroup_editor_layout()
    pygame.draw.rect(surf, (6, 12, 22), lay.panel, border_radius=14)
    pygame.draw.rect(surf, (55, 95, 130), lay.panel, width=2, border_radius=14)
    title = font_big.render("PvP battlegroup presets", True, (230, 240, 250))
    surf.blit(title, (lay.panel.centerx - title.get_width() // 2, lay.panel.y + 14))
    sub = font_tiny.render(
        "Saved for deploy costs in PvP — edit ships like fleet design (capital classes only).",
        True,
        (155, 175, 198),
    )
    surf.blit(sub, (lay.panel.centerx - sub.get_width() // 2, lay.panel.y + 38))

    pygame.draw.rect(surf, (14, 22, 36), lay.list_rect, border_radius=8)
    pygame.draw.rect(surf, (55, 80, 110), lay.list_rect, width=1, border_radius=8)
    lh = 26
    for j, pr in enumerate(presets):
        ry = lay.list_rect.y + 6 + j * lh - list_scroll
        if ry + lh < lay.list_rect.y or ry > lay.list_rect.bottom:
            continue
        sel = j == selected_i
        rr = pygame.Rect(lay.list_rect.x + 4, ry, lay.list_rect.w - 8, lh - 2)
        if sel:
            pygame.draw.rect(surf, (45, 78, 108), rr, border_radius=4)
        t = font_tiny.render(f"{pr.name}  ({pr.preset_id})  cost {pr.deploy_cost}", True, (210, 220, 235))
        surf.blit(t, (rr.x + 6, rr.y + 4))

    def _btn(r: pygame.Rect, lab: str, hot: bool = False) -> None:
        bg = (48, 68, 92) if not hot else (62, 88, 118)
        pygame.draw.rect(surf, bg, r, border_radius=6)
        pygame.draw.rect(surf, (120, 160, 200), r, width=1, border_radius=6)
        ts = font_tiny.render(lab, True, (235, 242, 250))
        surf.blit(ts, (r.centerx - ts.get_width() // 2, r.centery - ts.get_height() // 2))

    _btn(lay.btn_back, "Back")
    _btn(lay.btn_save, "Save")
    _btn(lay.btn_new, "New")
    _btn(lay.btn_del, "Delete")

    def _field(r: pygame.Rect, text: str, active: bool, placeholder: str) -> None:
        pygame.draw.rect(surf, (20, 30, 46), r, border_radius=4)
        pygame.draw.rect(surf, (130, 190, 230) if active else (70, 100, 130), r, width=1, border_radius=4)
        disp = text if text else placeholder
        col = (210, 220, 235) if text else (110, 125, 145)
        surf.blit(font_tiny.render(disp, True, col), (r.x + 6, r.y + 5))

    surf.blit(font_tiny.render("Display name", True, (170, 190, 210)), (lay.fld_name.x, lay.fld_name.y - 14))
    _field(lay.fld_name, name_buf, focus == "name", "e.g. Carrier strike")
    surf.blit(font_tiny.render("Preset id (unique key)", True, (170, 190, 210)), (lay.fld_id.x, lay.fld_id.y - 14))
    _field(lay.fld_id, id_buf, focus == "id", "e.g. carrier_ball")
    surf.blit(font_tiny.render("Deploy cost", True, (170, 190, 210)), (lay.fld_cost.x, lay.fld_cost.y - 14))
    _field(lay.fld_cost, cost_buf, focus == "cost", "0")

    _btn(lay.btn_tag_prev, "<")
    pygame.draw.rect(surf, (18, 28, 42), lay.tag_readout, border_radius=4)
    pygame.draw.rect(surf, (70, 100, 130), lay.tag_readout, width=1, border_radius=4)
    surf.blit(
        font_tiny.render(f"Entry: {entry_tag}", True, (195, 210, 228)),
        (lay.tag_readout.x + 6, lay.tag_readout.y + 5),
    )
    _btn(lay.btn_tag_next, ">")

    pygame.draw.rect(surf, (14, 22, 36), lay.row_area, border_radius=8)
    pygame.draw.rect(surf, (55, 80, 110), lay.row_area, width=1, border_radius=8)
    rh = 22
    for j, row in enumerate(rows):
        ry = lay.row_area.y + 6 + j * rh - row_scroll
        if ry + rh < lay.row_area.y or ry > lay.row_area.bottom:
            continue
        cls = str(row.get("class_name") or "?")
        lbl = str(row.get("label") or "")
        line = f"{j + 1}. {cls}" + (f"  ({lbl})" if lbl else "")
        surf.blit(font_tiny.render(line, True, (200, 215, 230)), (lay.row_area.x + 8, ry + 3))

    ship_name = cap_names[ship_pick_i] if cap_names and 0 <= ship_pick_i < len(cap_names) else "—"
    pygame.draw.rect(surf, (22, 32, 48), lay.lbl_ship, border_radius=4)
    pygame.draw.rect(surf, (75, 105, 135), lay.lbl_ship, width=1, border_radius=4)
    surf.blit(font_tiny.render(f"Add: {ship_name}", True, (210, 220, 235)), (lay.lbl_ship.x + 6, lay.lbl_ship.y + 4))
    _btn(lay.ship_prev, "<", False)
    _btn(lay.ship_next, ">", False)
    _btn(lay.btn_add, "Add ship")
    _btn(lay.btn_rm, "Rm last")

    path_short = save_path if len(save_path) < 72 else "…" + save_path[-68:]
    surf.blit(
        font_tiny.render(f"File: {path_short}", True, (120, 140, 162)),
        (lay.panel.x + 12, lay.panel.bottom - 68),
    )


def draw_mp_hub(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    font_big: pygame.font.Font,
    *,
    http_base: Optional[str],
    name_buffer: str,
    name_focus: bool,
    join_buffer: str,
    join_focus: bool,
    lobby_browser_rows: List[Dict[str, Any]],
    lobby_browser_scroll: int,
    next_online_authority: str = "player",
    status_primary: str = "",
    status_detail: Optional[str] = None,
    status_mode: str = "wait",
    online_actions_ok: bool = False,
    authority_config_ok: bool = False,
    list_busy: bool = False,
) -> None:
    lay = mp_hub_menu_layout()
    pygame.draw.rect(surf, (8, 14, 24), lay.panel, border_radius=16)
    pygame.draw.rect(surf, (60, 100, 150), lay.panel, width=2, border_radius=16)
    title = font_big.render("Multiplayer", True, (230, 238, 250))
    surf.blit(title, (lay.panel.centerx - title.get_width() // 2, lay.panel.y + 18))
    sub = font_tiny.render(
        "Play online with friends or host a custom game on this PC — no online account required.",
        True,
        (155, 175, 200),
    )
    surf.blit(sub, (lay.panel.centerx - sub.get_width() // 2, lay.panel.y + 48))

    pygame.draw.rect(surf, (12, 20, 34), lay.art_rect, border_radius=12)
    pygame.draw.rect(surf, (45, 70, 98), lay.art_rect, width=1, border_radius=12)

    st_y = lay.art_rect.y + 8
    st_col_ok = (140, 200, 160)
    st_col_wait = (200, 200, 140)
    st_col_bad = (200, 150, 140)
    if status_mode == "ok":
        stc = st_col_ok
    elif status_mode == "wait":
        stc = st_col_wait
    else:
        stc = st_col_bad
    sp = font_tiny.render(status_primary[:96] if status_primary else "…", True, stc)
    surf.blit(sp, (lay.art_rect.x + 12, st_y))
    if status_detail:
        sd = font_tiny.render(status_detail[:96], True, (255, 170, 150))
        surf.blit(sd, (lay.art_rect.x + 12, st_y + 16))

    show_url = os.environ.get("FLEETRTS_SHOW_LOBBY_URL", "").strip().lower() in ("1", "true", "yes")
    url_y = st_y + (34 if status_detail else 18)
    if show_url and http_base:
        surf.blit(font_tiny.render(f"Lobby server: {http_base[:68]}", True, (110, 140, 170)), (lay.art_rect.x + 12, url_y))

    nr = lay.name_entry_rect
    pygame.draw.rect(surf, (14, 22, 36), nr, border_radius=8)
    pygame.draw.rect(surf, (70, 120, 160) if name_focus else (50, 75, 100), nr, width=1, border_radius=8)
    surf.blit(
        font_tiny.render("Your name — used when you create or join an online game", True, (150, 175, 198)),
        (nr.x + 6, nr.y + 4),
    )
    nd = name_buffer if name_buffer else "Player"
    surf.blit(font.render(nd[:40], True, (220, 235, 255)), (nr.x + 6, nr.y + 22))
    if name_focus:
        surf.blit(font_tiny.render("▌", True, (180, 220, 255)), (nr.x + 6 + font.size(nd[:40])[0] + 1, nr.y + 22))

    jr = lay.join_entry_rect
    pygame.draw.rect(surf, (14, 22, 36), jr, border_radius=8)
    pygame.draw.rect(surf, (70, 120, 160) if join_focus else (50, 75, 100), jr, width=1, border_radius=8)
    surf.blit(
        font_tiny.render("Friend's game code (8 characters) — click here, then use Join with code", True, (150, 175, 198)),
        (jr.x + 6, jr.y + 4),
    )
    jy = jr.y + 22
    buf_disp = join_buffer if join_buffer else "________"
    jcol = (220, 235, 255) if join_buffer else (95, 110, 128)
    surf.blit(font.render(buf_disp, True, jcol), (jr.x + 6, jy))
    if join_focus:
        surf.blit(font_tiny.render("▌", True, (180, 220, 255)), (jr.x + 6 + font.size(buf_disp)[0] + 2, jy + 2))

    lr = lay.lobby_list_rect
    pygame.draw.rect(surf, (10, 18, 30), lr, border_radius=8)
    pygame.draw.rect(surf, (50, 75, 100), lr, width=1, border_radius=8)
    hdr_h = 22
    pygame.draw.line(surf, (55, 85, 115), (lr.x + 4, lr.y + hdr_h), (lr.right - 4, lr.y + hdr_h))
    surf.blit(
        font_tiny.render("Open games — click the header to refresh · click a row to join when available", True, (140, 170, 200)),
        (lr.x + 6, lr.y + 3),
    )
    row_h = 20
    vis = max(0, (lr.h - hdr_h - 4) // row_h)
    for i in range(vis):
        idx = lobby_browser_scroll + i
        if idx >= len(lobby_browser_rows):
            break
        row = lobby_browser_rows[idx]
        yy = lr.y + hdr_h + 4 + i * row_h
        jok = bool(row.get("joinable"))
        nm = str(row.get("name") or "?")[:18]
        sid = str(row.get("short_id") or "")[:8]
        pc = int(row.get("player_count") or 0)
        mt = str(row.get("match_type") or "custom")[:12]
        line = f"{nm}  {sid}  {pc}p  {mt}  {'JOIN' if jok else '—'}"
        surf.blit(font_tiny.render(line, True, (200, 215, 235) if jok else (120, 130, 145)), (lr.x + 8, yy))

    auth_l = (
        "Game server runs combat (for online hosts)"
        if next_online_authority == "dedicated"
        else "This PC runs combat when you’re the online host"
    )
    ar = lay.authority_strip
    pygame.draw.rect(surf, (14, 24, 38), ar, border_radius=6)
    pygame.draw.rect(surf, (70, 110, 150), ar, width=1, border_radius=6)
    auth_hint = (
        f"Who runs the battle for online games: {auth_l}  ·  F4 or click to toggle"
        if authority_config_ok
        else "Online options below stay off until a lobby server is available."
    )
    ah_col = (160, 188, 215) if authority_config_ok else (120, 130, 145)
    surf.blit(font_tiny.render(auth_hint[:118], True, ah_col), (ar.x + 6, ar.y + 4))

    def _btn(r: pygame.Rect, label: str, hot: bool) -> None:
        pygame.draw.rect(surf, (38, 78, 58) if hot else (36, 52, 72), r, border_radius=10)
        pygame.draw.rect(surf, (130, 200, 160) if hot else (110, 150, 190), r, width=2, border_radius=10)
        t = font.render(label, True, (235, 250, 245))
        surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))

    def _btn_dis(r: pygame.Rect, label: str) -> None:
        pygame.draw.rect(surf, (34, 40, 48), r, border_radius=10)
        pygame.draw.rect(surf, (70, 78, 88), r, width=1, border_radius=10)
        t = font.render(label, True, (130, 140, 150))
        surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))

    _btn(lay.btn_host, "Host custom game (local)", True)
    if online_actions_ok:
        _btn(lay.btn_quick_join, "Quick join (matchmaking)", True)
        _btn(lay.btn_srv_create, "Create online lobby", True)
        _btn(lay.btn_srv_join, "Join with code", True)
    else:
        _btn_dis(lay.btn_quick_join, "Quick join (matchmaking)")
        _btn_dis(lay.btn_srv_create, "Create online lobby")
        _btn_dis(lay.btn_srv_join, "Join with code")
    _btn(lay.btn_back, "Back", False)
    hint = font_tiny.render(
        "Quick join finds an open game or starts a public waiting lobby · ESC — back to main menu",
        True,
        (130, 150, 172),
    )
    surf.blit(hint, (lay.panel.centerx - hint.get_width() // 2, lay.panel.bottom + 12))


def _draw_mp_lobby_setting_row(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    row_r: pygame.Rect,
    label: str,
    value: str,
    host: bool,
) -> None:
    pygame.draw.rect(surf, (16, 26, 40), row_r, border_radius=8)
    pygame.draw.rect(surf, (55, 85, 115), row_r, width=1, border_radius=8)
    lb = font.render(label, True, (190, 205, 220))
    surf.blit(lb, (row_r.x + 10, row_r.y + 4))
    hot = (200, 220, 240) if host else (110, 125, 140)
    vl = font_tiny.render(value + ("  ·  click to change" if host else "  ·  host only"), True, hot)
    surf.blit(vl, (row_r.x + 10, row_r.y + 20))


def draw_mp_lobby(
    surf: pygame.Surface,
    font: pygame.font.Font,
    font_tiny: pygame.font.Font,
    font_big: pygame.font.Font,
    *,
    coop: bool,
    use_asteroids: bool,
    enemy_pressure_i: int,
    player_color_id: int,
    host: bool,
    ready: bool,
    mp_round: int,
    fleet_capital_n: int,
    toast_text: Optional[str],
    online_title: str = "Lobby — custom game (local stub)",
    online_lines: Optional[List[str]] = None,
    relay_status: Optional[str] = None,
    chat_enabled: bool = False,
    chat_log: Optional[List[str]] = None,
    chat_input: str = "",
    chat_focus: bool = False,
) -> None:
    lay = mp_lobby_menu_layout()
    pygame.draw.rect(surf, (6, 12, 22), lay.panel, border_radius=14)
    pygame.draw.rect(surf, (50, 90, 130), lay.panel, width=2, border_radius=14)
    title = font_big.render(online_title, True, (230, 240, 250))
    surf.blit(title, (lay.panel.x + 20, lay.panel.y + 18))
    sub = font_tiny.render(
        "Host edits world rules below · everyone uses Fleet design for loadouts · Start when ready",
        True,
        (155, 175, 198),
    )
    surf.blit(sub, (lay.panel.x + 20, lay.panel.y + 46))

    mode_v = "Objective co-op" if coop else "PvP"
    _draw_mp_lobby_setting_row(surf, font, font_tiny, lay.row_mode, "Mode", mode_v, host)
    _draw_mp_lobby_setting_row(
        surf,
        font,
        font_tiny,
        lay.row_mission,
        "Player color",
        f"Slot {int(max(0, min(player_color_id, 5))) + 1}/6",
        host,
    )
    rock_v = "Asteroid field ON" if use_asteroids else "Asteroid field OFF"
    _draw_mp_lobby_setting_row(surf, font, font_tiny, lay.row_rocks, "World", rock_v, host)
    if coop:
        pressure_labels = ("Standard enemies", "Heavier spawns", "Siege-style", "Custom / open")
        ei = max(0, min(enemy_pressure_i, len(pressure_labels) - 1))
        _draw_mp_lobby_setting_row(surf, font, font_tiny, lay.row_enemy, "Enemy pressure", pressure_labels[ei], host)
    else:
        _draw_mp_lobby_setting_row(
            surf,
            font,
            font_tiny,
            lay.row_enemy,
            "Enemy pressure",
            "Off (PvP — no AI waves)",
            False,
        )

    lr, ir = lay.chat_log_rect, lay.chat_input_rect
    pygame.draw.rect(surf, (12, 18, 28), lr, border_radius=8)
    pygame.draw.rect(surf, (50, 75, 100), lr, width=1, border_radius=8)
    surf.blit(font_tiny.render("Lobby chat (relay)", True, (155, 175, 195)), (lr.x + 6, lr.y + 4))
    if chat_enabled:
        clip = surf.get_clip()
        inner = lr.inflate(-10, -22)
        surf.set_clip(inner)
        try:
            lines = chat_log or []
            lh = font_tiny.get_height() + 2
            max_rows = max(1, inner.h // lh)
            for i, ln in enumerate(lines[-max_rows:]):
                surf.blit(font_tiny.render(ln[:120], True, (185, 200, 218)), (inner.x + 2, inner.y + i * lh))
        finally:
            surf.set_clip(clip)
    else:
        surf.blit(
            font_tiny.render("Online lobby + relay: type below, ENTER to send", True, (110, 125, 145)),
            (lr.x + 6, lr.y + 22),
        )
    pygame.draw.rect(surf, (18, 28, 42), ir, border_radius=6)
    pygame.draw.rect(surf, (85, 130, 170) if chat_focus else (55, 80, 105), ir, width=1, border_radius=6)
    ci = chat_input if chat_input else ("…" if chat_enabled else "(online only)")
    ccol = (220, 235, 250) if chat_enabled else (100, 110, 125)
    surf.blit(font_tiny.render(ci[:100], True, ccol), (ir.x + 6, ir.centery - font_tiny.get_height() // 2))

    pygame.draw.rect(surf, (14, 22, 34), lay.players_col, border_radius=10)
    pygame.draw.rect(surf, (55, 80, 105), lay.players_col, width=1, border_radius=10)
    surf.blit(font.render("Players", True, (195, 210, 225)), (lay.players_col.x + 12, lay.players_col.y + 10))
    y = lay.players_col.y + 40
    if online_lines:
        for line in online_lines[:22]:
            surf.blit(font_tiny.render(line[:96], True, (165, 185, 205)), (lay.players_col.x + 12, y))
            y += 22
    else:
        surf.blit(
            font_tiny.render("You — HOST · ping — ms · fleet slots later", True, (165, 185, 205)),
            (lay.players_col.x + 12, y),
        )
        y += 28
    surf.blit(
        font_tiny.render(f"Saved fleet: {fleet_capital_n} capital(s) · next battle uses round {mp_round}", True, (145, 170, 195)),
        (lay.players_col.x + 12, y),
    )
    y += 26
    if relay_status:
        surf.blit(font_tiny.render(relay_status[:100], True, (200, 210, 150)), (lay.players_col.x + 12, y))

    def _b(r: pygame.Rect, text: str, accent: bool) -> None:
        base = (42, 72, 98) if accent else (36, 48, 62)
        brd = (120, 190, 230) if accent else (85, 110, 135)
        pygame.draw.rect(surf, base, r, border_radius=8)
        pygame.draw.rect(surf, brd, r, width=1, border_radius=8)
        t = font.render(text, True, (235, 245, 255))
        surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))

    _b(lay.btn_fleet, "Fleet design", True)
    rd = "Ready ✓" if ready else "Ready"
    _b(lay.btn_ready, rd, ready)
    can_start = host and ready
    _b(lay.btn_start, "Start battle", can_start)
    _b(lay.btn_back, "Hub", False)

    if toast_text:
        tb = font_tiny.render(toast_text, True, (255, 210, 130))
        surf.blit(tb, (lay.panel.x + 20, lay.panel.bottom - 86))


def run() -> None:
    pygame.init()
    pygame.display.set_caption("Fleet RTS — weapons / missiles / hangar demo")
    screen = pygame.Surface((WIDTH, HEIGHT))
    win_w, win_h = WIDTH, HEIGHT
    window = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
    _preload_http_client_stack()
    if os.environ.get("FLEETRTS_FAULTHANDLER", "").strip().lower() in ("1", "true", "yes"):
        import faulthandler

        _fh_out: Any = sys.stderr
        _fh_path = os.environ.get("FLEETRTS_FAULTHANDLER_FILE", "").strip()
        if _fh_path:
            try:
                _fh_out = open(_fh_path, "a", encoding="utf-8")
            except OSError:
                _fh_out = sys.stderr
        faulthandler.enable(all_threads=True, file=_fh_out)
        try:
            _fh_sec = int(os.environ.get("FLEETRTS_FAULTHANDLER_INTERVAL", "15") or "15")
        except ValueError:
            _fh_sec = 15
        faulthandler.dump_traceback_later(max(5, _fh_sec), repeat=True, file=_fh_out)

    def to_internal(pos: Tuple[int, int]) -> Tuple[int, int]:
        mx, my = pos
        return int(mx * WIDTH / max(1, win_w)), int(my * HEIGHT / max(1, win_h))

    audio = GameAudio()
    audio.init()
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 15)
    font_tiny = pygame.font.SysFont("consolas", 12)
    font_micro = pygame.font.SysFont("consolas", 10)
    font_big = pygame.font.SysFont("consolas", 20)

    data = load_game_data()
    battle_obstacles = parse_obstacles(data)
    random.seed(42)
    stars = [
        (random.randint(0, max(1, WORLD_W - 1)), random.randint(0, max(1, WORLD_H - 1)), random.randint(40, 120))
        for _ in range(960)
    ]

    groups: List[Group] = []
    crafts: List[Craft] = []
    mission: Optional[MissionState] = None
    cam_x, cam_y = WORLD_W * 0.35, WORLD_H * 0.35

    missiles: List[Missile] = []
    ballistics: List[BallisticSlug] = []
    vfx_sparks: List[VFXSpark] = []
    vfx_beams: List[VFXBeam] = []
    supplies = [100.0]
    salvage = [0]
    pd_rof_mult = [1.0]
    ciws_stacks = [0]
    bulk_stacks = [0]
    round_idx = 1
    outcome: Optional[str] = None
    phase = "config"
    config_volume_drag = False
    loadout_preview_groups: List[Group] = []
    loadout_preview_crafts: List[Craft] = []
    loadout_selected_i = 0
    loadout_roster_scroll = 0
    deployment_scrap = [DEPLOYMENT_STARTING_SCRAP]
    loadout_choice_map: Dict[Tuple[str, int], int] = {}
    mp_fleet_groups: List[Group] = []
    mp_fleet_crafts: List[Craft] = []
    mp_loadouts_active = False
    post_combat_phase: Optional[str] = None
    mp_round_idx = 1
    mp_use_asteroids = True
    mp_mode_coop = True
    mp_enemy_pressure = 0
    mp_lobby_host = True
    mp_lobby_authoritative: str = "player"
    mp_ready = False
    mp_toast_until_ms = 0
    mp_toast_text = ""
    fleet_http_base: Optional[str] = _resolve_fleet_http_base()
    _mp_default_name = (os.environ.get("FLEETRTS_PLAYER", "Player").strip() or "Player")[:48]
    mp_player_name: str = _mp_default_name
    mp_name_buffer: str = _mp_default_name
    mp_name_focus: bool = False
    mp_join_id_buffer: str = ""
    mp_join_focus: bool = False
    mp_hub_lobby_rows: List[Dict[str, Any]] = []
    mp_hub_lobby_scroll = 0
    # None = first hub frame stamps time; <0 = user requested refresh; else ticks when last fetch started (auto every 5s).
    mp_hub_list_last_ms: Optional[int] = None
    mp_hub_list_busy = False
    mp_hub_list_started_ms: int = 0
    mp_hub_list_q: queue.Queue = queue.Queue()
    mp_http_authority_choice: str = "player"
    mp_chat_log: List[str] = []
    mp_chat_input: str = ""
    mp_chat_focus: bool = False
    bg_editor_path: str = ""
    bg_editor_presets: List[BattlegroupPreset] = []
    bg_editor_selected_i: int = 0
    bg_editor_list_scroll: int = 0
    bg_editor_row_scroll: int = 0
    bg_editor_focus: Optional[str] = None
    bg_editor_name_buf: str = ""
    bg_editor_id_buf: str = ""
    bg_editor_cost_buf: str = ""
    bg_editor_entry_i: int = 0
    bg_editor_rows: List[Dict[str, str]] = []
    bg_editor_ship_pick_i: int = 0
    remote_ready: Dict[str, bool] = {}
    mp_match_generation = 0
    mp_applied_remote_start_gen = 0
    remote_loadouts: Dict[str, bool] = {}
    mp_player_color_id = 0
    remote_player_colors: Dict[str, int] = {}
    mp_player_fleet_designs: Dict[str, List[Dict[str, str]]] = {}
    mp_net_err: Optional[str] = None
    mp_hub_svc_state: str = "offline"
    mp_hub_user_message: Optional[str] = None
    mp_hub_last_ok_ms: int = 0
    remote_lobby_id: Optional[str] = None
    remote_lobby_short: Optional[str] = None
    remote_lobby_http_players: List[str] = []
    remote_relay_players: List[str] = []
    mp_relay: Optional[Any] = None
    mp_last_lobby_poll_ms: int = 0
    drag_anchor: Optional[Tuple[int, int]] = None
    awaiting_bomber_order_click = False
    awaiting_fighter_order_click = False
    awaiting_capital_context_lmb = False
    run_total_score = 0
    last_salvage_gain = 0
    store_selected: Optional[str] = None
    store_hover: Optional[str] = None
    test_menu_open = False
    pause_menu_open = False
    pause_main_menu_hover = False
    test_debrief_resume = False
    formation_mode = FORMATION_MODE_RING
    control_groups: List[Optional[List[str]]] = [None] * CONTROL_GROUP_SLOTS
    control_groups[0] = all_player_capital_labels(groups)
    awaiting_attack_move_click = False
    awaiting_attack_target_click = False
    last_cap_click_t = -100000
    last_cap_click_label: Optional[str] = None
    # Sentinel so first frame sees a change when the fleet starts with only CV-1 selected.
    tts_prev_sel_sig: Tuple[str, ...] = ()
    tts_last_enemy_kill_tts = -10**6
    tts_last_player_cap_loss_tts = -10**6
    tts_last_carrier_quip_tts = -10**6
    tts_last_order_quip_tts = -10**6
    tts_last_low_hull_by_label: dict[str, int] = {}
    order_hint_until = 0
    order_hint_msg = ""
    cg_weapons_free: List[bool] = [False] * CONTROL_GROUP_SLOTS
    fog = FogState()
    active_pings: List[ActivePing] = []
    sensor_ghosts: List[SensorGhost] = []
    seeker_ghosts: List[SensorGhost] = []
    ping_ghost_anchor_labels: Set[str] = set()
    ping_ready_at_ms = 0
    mp_combat_tick = 0
    mp_host_cmd_queue: List[Dict[str, Any]] = []
    mp_pending_snap: Optional[Dict[str, Any]] = None
    mp_client_cmd_seq = 0
    mp_client_last_snap_tick = -1
    mp_last_snap_send_ms = 0
    mp_fm_holder = [formation_mode]
    mp_desync_until_ms = 0
    mp_desync_text = ""
    mp_host_snap_tick = -1

    def disconnect_mp_session() -> None:
        nonlocal mp_relay, remote_lobby_id, remote_lobby_short, mp_chat_input, mp_chat_focus
        nonlocal mp_match_generation, mp_applied_remote_start_gen, mp_lobby_authoritative
        _leave_lid = remote_lobby_id
        _leave_name = mp_player_name
        _leave_base = fleet_http_base
        if NET_MP and leave_lobby is not None and _leave_base and _leave_lid and (_leave_name or "").strip():
            try:
                leave_lobby(_leave_base, str(_leave_lid), _leave_name)
            except Exception:
                pass
        if mp_relay is not None:
            mp_relay.close()
            mp_relay = None
        remote_lobby_id = None
        remote_lobby_short = None
        remote_lobby_http_players.clear()
        remote_relay_players.clear()
        mp_chat_log.clear()
        mp_chat_input = ""
        mp_chat_focus = False
        remote_ready.clear()
        remote_loadouts.clear()
        remote_player_colors.clear()
        mp_player_fleet_designs.clear()
        mp_match_generation = 0
        mp_applied_remote_start_gen = 0
        mp_lobby_authoritative = "player"

    def sync_mp_player_name_from_field() -> None:
        nonlocal mp_player_name
        mp_player_name = (mp_name_buffer.strip() or "Player")[:48]

    def connect_relay(lobby: Dict[str, Any]) -> None:
        nonlocal mp_relay, mp_net_err, mp_lobby_authoritative
        if mp_relay is not None:
            mp_relay.close()
            mp_relay = None
        mp_net_err = None
        if not NET_MP or RelayClient is None:
            return
        lid = str(lobby.get("id") or "")
        if not lid:
            return
        rel = lobby.get("relay") if isinstance(lobby.get("relay"), dict) else {}
        rh = str(rel.get("host") or os.environ.get("FLEETRTS_RELAY_HOST", "127.0.0.1"))
        try:
            rp = int(rel.get("port", os.environ.get("FLEETRTS_RELAY_PORT", "8766")))
        except (TypeError, ValueError):
            rp = int(os.environ.get("FLEETRTS_RELAY_PORT", "8766"))
        mp_relay = RelayClient(rh, rp, lid, mp_player_name)
        mp_relay.connect()
        if mp_relay.error:
            mp_net_err = mp_relay.error
        au = lobby.get("authoritative")
        mp_lobby_authoritative = str(au) if au in ("player", "dedicated") else "player"

    def send_host_config_if_online() -> None:
        if (
            remote_lobby_id
            and mp_relay is not None
            and not mp_relay.error
            and mp_lobby_host
        ):
            mp_relay.send_payload(
                host_config(
                    coop=mp_mode_coop,
                    use_asteroids=mp_use_asteroids,
                    enemy_pressure=mp_enemy_pressure,
                )
            )

    def on_player_hull_hit(tgt: Any) -> None:
        notify_player_unit_damaged_for_engagement(tgt, control_groups, cg_weapons_free)

    def enter_ship_loadouts(from_multiplayer: bool = False) -> None:
        nonlocal phase, loadout_preview_groups, loadout_preview_crafts, loadout_selected_i, loadout_roster_scroll
        nonlocal mp_loadouts_active
        mp_loadouts_active = from_multiplayer
        loadout_choice_map.clear()
        deployment_scrap[0] = DEPLOYMENT_STARTING_SCRAP
        if from_multiplayer:
            if mp_fleet_groups:
                loadout_preview_groups.clear()
                loadout_preview_groups.extend(mp_fleet_groups)
                loadout_preview_crafts.clear()
                loadout_preview_crafts.extend(mp_fleet_crafts)
            else:
                loadout_preview_groups, loadout_preview_crafts = build_initial_player_fleet(data)
        else:
            loadout_preview_groups, loadout_preview_crafts = build_initial_player_fleet(data)
        snap_strike_crafts_to_carriers(loadout_preview_crafts)
        for g in loadout_preview_groups:
            if g.side == "player" and g.render_capital:
                sync_loadout_choice_map_for_group(data, g, loadout_choice_map)
        clear_selection(loadout_preview_groups)
        clear_craft_selection(loadout_preview_crafts)
        loadout_selected_i = 0
        loadout_roster_scroll = 0
        phase = "ship_loadouts"
        if from_multiplayer and remote_lobby_id and mp_relay is not None and not mp_relay.error:
            mp_relay.send_payload(lobby_presence(in_fleet_design=True, color_id=mp_player_color_id))

    def finish_mp_ship_loadouts_to_lobby() -> None:
        nonlocal phase, mp_loadouts_active
        mp_fleet_groups.clear()
        mp_fleet_groups.extend(loadout_preview_groups)
        mp_fleet_crafts.clear()
        mp_fleet_crafts.extend(loadout_preview_crafts)
        loadout_preview_groups.clear()
        loadout_preview_crafts.clear()
        loadout_choice_map.clear()
        mp_loadouts_active = False
        phase = "mp_lobby"
        if remote_lobby_id and mp_relay is not None and not mp_relay.error:
            mp_relay.send_payload(lobby_presence(in_fleet_design=False, color_id=mp_player_color_id))
            if lobby_loadout is not None:
                mp_relay.send_payload(
                    lobby_loadout(payload={"fleet": export_player_fleet_design(mp_fleet_groups)})
                )

    def launch_mp_combat(match_seed: Optional[int] = None, player_setup: Optional[Dict[str, Any]] = None) -> None:
        nonlocal groups, crafts, mission, cam_x, cam_y, phase, post_combat_phase, round_idx
        nonlocal fog, tts_prev_sel_sig
        nonlocal mp_combat_tick, mp_host_cmd_queue, mp_pending_snap, mp_client_last_snap_tick
        nonlocal mp_last_snap_send_ms, mp_desync_text, mp_host_snap_tick
        post_combat_phase = "mp_lobby"
        mp_combat_tick = 0
        mp_host_cmd_queue.clear()
        mp_pending_snap = None
        mp_client_last_snap_tick = -1
        mp_last_snap_send_ms = 0
        mp_desync_text = ""
        mp_host_snap_tick = -1
        round_idx = mp_round_idx
        loadout_preview_groups.clear()
        loadout_preview_crafts.clear()
        loadout_choice_map.clear()
        if not mp_fleet_groups:
            ng, nc = build_initial_player_fleet(
                data, owner_id=mp_player_name, color_id=mp_player_color_id, label_prefix=f"{mp_player_name}:"
            )
            mp_fleet_groups.extend(ng)
            mp_fleet_crafts.extend(nc)
        if isinstance(player_setup, dict) and isinstance(player_setup.get("players"), list):
            groups.clear()
            crafts.clear()
            players = normalize_mp_player_order(player_setup.get("players") or [])
            if mp_player_name not in players:
                players = normalize_mp_player_order(list(players) + [mp_player_name])
            colors = player_setup.get("colors") if isinstance(player_setup.get("colors"), dict) else {}
            designs = player_setup.get("designs") if isinstance(player_setup.get("designs"), dict) else {}
            ax0, ay0 = deploy_anchor_xy()
            n_pl = max(1, min(len(players), 8))

            for i, pname in enumerate(players[:8]):
                cid = int(max(0, min(int(colors.get(pname, 0)), 5)))
                rows = designs.get(pname) if isinstance(designs, dict) else None
                if mp_mode_coop:
                    anchor = coop_player_spawn_anchor(i, ax0, ay0)
                else:
                    anchor = pvp_player_spawn_anchor(i, n_pl)
                ng, nc = build_player_fleet_from_design(
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
            groups[:] = list(mp_fleet_groups)
            crafts[:] = list(mp_fleet_crafts)
        _mp_online_lobby = bool(NET_MP and remote_lobby_id and mp_relay is not None and not mp_relay.error)
        clear_selection(groups)
        clear_craft_selection(crafts)
        if _mp_online_lobby:
            _picked_self = False
            for g in groups:
                if (
                    g.side == "player"
                    and not g.dead
                    and g.render_capital
                    and getattr(g, "owner_id", "") == mp_player_name
                ):
                    g.selected = True
                    _picked_self = True
                    break
            if not _picked_self:
                roster = loadout_player_capitals_sorted(groups)
                if roster:
                    roster[0].selected = True
        else:
            roster = loadout_player_capitals_sorted(groups)
            if roster:
                roster[0].selected = True
        obs = battle_obstacles if mp_use_asteroids else []
        rng_seed = int(match_seed) if match_seed is not None else round_seed(mp_round_idx)
        mission = begin_combat_round(
            data,
            groups,
            mp_round_idx,
            random.Random(rng_seed),
            obs,
            enemy_pressure=mp_enemy_pressure,
            mp_pvp=not mp_mode_coop,
        )
        if getattr(mission, "mp_pvp", False):
            owners = sorted(
                {
                    str(getattr(g, "owner_id", "")).strip()
                    for g in groups
                    if g.side == "player" and str(getattr(g, "owner_id", "")).strip()
                }
            )
            mission.pvp_scrap = {o: 0 for o in owners}
            mission.pvp_territory = {}
            mission.pvp_battlegroups = {}
        snap_strike_crafts_to_carriers(crafts)
        cam_x, cam_y = initial_camera_for_fleet(groups)
        control_groups[:] = [None] * CONTROL_GROUP_SLOTS
        if _mp_online_lobby:
            control_groups[0] = [
                g.label
                for g in groups
                if g.side == "player"
                and not g.dead
                and g.render_capital
                and getattr(g, "owner_id", "") == mp_player_name
            ]
        else:
            control_groups[0] = all_player_capital_labels(groups)
        fog = FogState()
        active_pings.clear()
        sensor_ghosts.clear()
        seeker_ghosts.clear()
        ping_ghost_anchor_labels.clear()
        ping_ready_at_ms = 0
        awaiting_bomber_order_click = False
        awaiting_fighter_order_click = False
        awaiting_capital_context_lmb = False
        awaiting_attack_move_click = False
        awaiting_attack_target_click = False
        last_cap_click_t = -100000
        last_cap_click_label = None
        tts_prev_sel_sig = ()
        phase = "combat"

    def launch_mission_combat() -> None:
        nonlocal groups, crafts, mission, cam_x, cam_y, phase, post_combat_phase
        nonlocal fog, tts_prev_sel_sig
        post_combat_phase = None
        if not loadout_preview_groups:
            pg, pc = build_initial_player_fleet(data)
            snap_strike_crafts_to_carriers(pc)
        else:
            pg = list(loadout_preview_groups)
            pc = list(loadout_preview_crafts)
        loadout_preview_groups.clear()
        loadout_preview_crafts.clear()
        loadout_choice_map.clear()
        groups[:] = pg
        crafts[:] = pc
        clear_selection(groups)
        clear_craft_selection(crafts)
        roster = loadout_player_capitals_sorted(groups)
        if roster:
            roster[0].selected = True
        mission = begin_combat_round(data, groups, 1, random.Random(round_seed(1)), battle_obstacles)
        snap_strike_crafts_to_carriers(crafts)
        cam_x, cam_y = initial_camera_for_fleet(groups)
        control_groups[:] = [None] * CONTROL_GROUP_SLOTS
        control_groups[0] = all_player_capital_labels(groups)
        fog = FogState()
        active_pings.clear()
        sensor_ghosts.clear()
        seeker_ghosts.clear()
        ping_ghost_anchor_labels.clear()
        ping_ready_at_ms = 0
        awaiting_bomber_order_click = False
        awaiting_fighter_order_click = False
        awaiting_capital_context_lmb = False
        awaiting_attack_move_click = False
        awaiting_attack_target_click = False
        last_cap_click_t = -100000
        last_cap_click_label = None
        tts_prev_sel_sig = ()
        phase = "combat"

    def handle_mp_relay_events() -> None:
        nonlocal mp_net_err, remote_relay_players, mp_chat_log, remote_ready, remote_loadouts
        nonlocal mp_mode_coop, mp_use_asteroids, mp_enemy_pressure, mp_applied_remote_start_gen
        nonlocal mp_round_idx, mp_ready, mp_toast_text, mp_toast_until_ms
        nonlocal mp_host_cmd_queue, mp_pending_snap
        if mp_relay is None:
            return
        if mp_relay.error:
            mp_net_err = mp_relay.error
        for _m in mp_relay.poll():
            if _m.get("t") == "joined":
                remote_relay_players = list(_m.get("players") or [])
                mp_relay.send_payload(lobby_ready(mp_ready))
                if mp_lobby_host:
                    send_host_config_if_online()
                in_fd = phase == "ship_loadouts" and mp_loadouts_active
                mp_relay.send_payload(lobby_presence(in_fleet_design=in_fd, color_id=mp_player_color_id))
                if lobby_loadout is not None:
                    mp_relay.send_payload(
                        lobby_loadout(payload={"fleet": export_player_fleet_design(mp_fleet_groups)})
                    )
            elif _m.get("t") == "peer_left":
                remote_relay_players = list(_m.get("players") or [])
                left_p = str(_m.get("player") or "")
                if left_p:
                    remote_ready.pop(left_p, None)
                    remote_loadouts.pop(left_p, None)
            elif _m.get("t") == "relay":
                body = _m.get("body")
                if isinstance(body, dict) and body.get("t") == "lobby_chat":
                    who = str(_m.get("from") or "?")
                    txt = str(body.get("text") or "")[:240]
                    mp_chat_log.append(f"{who}: {txt}")
                    if len(mp_chat_log) > 80:
                        mp_chat_log[:] = mp_chat_log[-80:]
                elif isinstance(body, dict) and body.get("t") == "lobby_ready":
                    who = str(_m.get("from") or "?")
                    remote_ready[who] = bool(body.get("v"))
                elif isinstance(body, dict) and body.get("t") == "lobby_presence":
                    who = str(_m.get("from") or "?")
                    remote_loadouts[who] = bool(body.get("in_fleet_design", False))
                    remote_player_colors[who] = int(max(0, min(int(body.get("color_id", 0)), 5)))
                elif isinstance(body, dict) and body.get("t") == "lobby_loadout":
                    who = str(_m.get("from") or "?")
                    payload = body.get("payload") or {}
                    fleet_rows = payload.get("fleet") if isinstance(payload, dict) else None
                    if isinstance(fleet_rows, list):
                        cleaned: List[Dict[str, str]] = []
                        for row in fleet_rows[:24]:
                            if isinstance(row, dict):
                                cleaned.append(
                                    {
                                        "class_name": str(row.get("class_name") or "")[:48],
                                        "label": str(row.get("label") or "")[:48],
                                    }
                                )
                        mp_player_fleet_designs[who] = cleaned
                elif isinstance(body, dict) and body.get("t") == "host_config":
                    if not mp_lobby_host:
                        mp_mode_coop = bool(body.get("coop", mp_mode_coop))
                        mp_use_asteroids = bool(body.get("use_asteroids", mp_use_asteroids))
                        ep = int(body.get("enemy_pressure", mp_enemy_pressure))
                        mp_enemy_pressure = max(0, min(ep, 3))
                        if not mp_mode_coop:
                            mp_enemy_pressure = 0
                elif isinstance(body, dict) and body.get("t") == COMBAT_CMD:
                    _host_runs_sim = mp_lobby_host and mp_lobby_authoritative != "dedicated"
                    if (
                        _host_runs_sim
                        and mp_sync_match_active()
                        and phase == "combat"
                        and outcome is None
                    ):
                        q = dict(body)
                        q["_sender"] = str(_m.get("from") or "")
                        mp_host_cmd_queue.append(q)
                elif isinstance(body, dict) and body.get("t") == COMBAT_SNAP:
                    _client_snap = (not mp_lobby_host) or (mp_lobby_authoritative == "dedicated")
                    if _client_snap and mp_sync_match_active() and phase in ("combat", "debrief"):
                        mp_pending_snap = dict(body)
                elif isinstance(body, dict) and body.get("t") == "start_match":
                    if phase == "mp_lobby":
                        gen = int(body.get("generation", 0))
                        if gen > mp_applied_remote_start_gen:
                            mp_applied_remote_start_gen = gen
                            mp_round_idx = int(body.get("round_idx", mp_round_idx))
                            mp_use_asteroids = bool(body.get("use_asteroids", mp_use_asteroids))
                            mp_mode_coop = bool(body.get("coop", True))
                            ep = int(body.get("enemy_pressure", mp_enemy_pressure))
                            mp_enemy_pressure = max(0, min(ep, 3))
                            ms = body.get("seed")
                            mseed = int(ms) if ms is not None else None
                            psetup = body.get("player_setup")
                            launch_mp_combat(mseed, psetup if isinstance(psetup, dict) else None)
                            mp_ready = False
                            audio.play_positive()

    def mp_sync_match_active() -> bool:
        """True while an online lobby match is in progress (combat or debrief return path)."""
        return bool(
            NET_MP
            and remote_lobby_id
            and mp_relay is not None
            and not mp_relay.error
            and post_combat_phase == "mp_lobby"
        )

    def mp_net_combat_active() -> bool:
        return bool(mp_sync_match_active() and phase == "combat" and outcome is None)

    def mp_local_runs_authoritative_sim() -> bool:
        return bool(
            mp_net_combat_active()
            and mp_lobby_host
            and mp_lobby_authoritative != "dedicated"
        )

    def mp_is_net_client() -> bool:
        return bool(mp_net_combat_active() and not mp_local_runs_authoritative_sim())

    def mp_snapshot_broadcast_authority() -> bool:
        """Player lobby host who runs the combat sim (not dedicated relay)."""
        return bool(
            NET_MP
            and remote_lobby_id
            and mp_relay is not None
            and not mp_relay.error
            and post_combat_phase == "mp_lobby"
            and mp_lobby_host
            and mp_lobby_authoritative != "dedicated"
        )

    def mp_receives_combat_snapshots() -> bool:
        return bool(
            mp_sync_match_active()
            and phase in ("combat", "debrief")
            and not mp_snapshot_broadcast_authority()
        )

    def _mp_apply_pending_snapshot(now_ms_frame: int) -> None:
        nonlocal mp_pending_snap, mp_client_last_snap_tick, outcome, phase, ping_ready_at_ms
        nonlocal salvage, run_total_score, last_salvage_gain, store_selected, store_hover, mp_desync_text
        nonlocal mp_desync_until_ms
        if mp_pending_snap is None:
            return
        body = mp_pending_snap
        mp_pending_snap = None
        tsn = int(body.get("tick", -9))
        if tsn <= mp_client_last_snap_tick:
            return
        st = body.get("state")
        if not isinstance(st, dict):
            return
        hx = str(body.get("state_hash", ""))
        lh = hash_state_dict(st)
        if lh != hx:
            mp_desync_text = f"DESYNC hash tick={tsn}"
            mp_desync_until_ms = now_ms_frame + 8000
            print(f"[FleetRTS MP] {mp_desync_text} local={lh[:16]}… host={hx[:16]}…")
        (
            _t,
            snap_outcome,
            snap_phase,
            snap_ping_ms,
            snap_salvage,
            snap_score,
            snap_last_sg,
            snap_store_sel,
            snap_store_hov,
        ) = apply_snapshot_state(
            data=data,
            state=st,
            mission=mission,
            groups=groups,
            crafts=crafts,
            missiles=missiles,
            ballistics=ballistics,
            vfx_sparks=vfx_sparks,
            vfx_beams=vfx_beams,
            supplies=supplies,
            pd_rof_mult=pd_rof_mult,
            cg_weapons_free=cg_weapons_free,
            control_groups=control_groups,
            fog=fog,
            active_pings=active_pings,
            sensor_ghosts=sensor_ghosts,
            seeker_ghosts=seeker_ghosts,
            ping_ghost_anchor_labels=ping_ghost_anchor_labels,
        )
        ping_ready_at_ms = snap_ping_ms
        outcome = snap_outcome
        phase = snap_phase
        salvage[0] = int(snap_salvage)
        run_total_score = snap_score
        last_salvage_gain = snap_last_sg
        store_selected = snap_store_sel
        store_hover = snap_store_hov
        mp_client_last_snap_tick = tsn

    def mp_send_client(kind: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        nonlocal mp_client_cmd_seq
        if not mp_net_combat_active() or mp_local_runs_authoritative_sim():
            return False
        mp_client_cmd_seq += 1
        mp_relay.send_payload(
            combat_cmd(tick=0, seq=mp_client_cmd_seq, kind=str(kind), payload=dict(payload or {}))
        )
        return True

    def mp_sel_player_group_labels() -> List[str]:
        return [g.label for g in groups if g.owner_id == mp_player_name and g.selected and not g.dead]

    def mp_sel_capital_labels() -> List[str]:
        return [
            g.label
            for g in groups
            if g.owner_id == mp_player_name and g.selected and not g.dead and g.render_capital
        ]

    def mp_sel_craft_labels() -> List[str]:
        return [c.label for c in crafts if c.owner_id == mp_player_name and c.selected and not c.dead]

    def _mp_owned_pick_owner() -> Optional[str]:
        return mp_player_name if mp_net_combat_active() else None

    def _mp_pick_hostile_kwargs() -> Dict[str, Any]:
        if not mp_net_combat_active():
            return {}
        return {
            "viewer_owner": mp_player_name,
            "mp_pvp": bool(getattr(mission, "mp_pvp", False)) if mission is not None else False,
        }

    _hub_debug_log = os.environ.get("FLEETRTS_DEBUG_LOG", "").strip()
    _hub_http_disabled = os.environ.get("FLEETRTS_HUB_DISABLE_HTTP", "").strip().lower() in ("1", "true", "yes")

    def _mp_hub_can_use_http() -> bool:
        return (
            not _hub_http_disabled
            and bool(fleet_http_base)
            and NET_MP
            and list_lobbies is not None
        )

    mp_hub_debug_frames = 0

    cap_names_menu = capital_ship_class_names(data)
    if not cap_names_menu:
        cap_names_menu = ["Destroyer"]

    def _bg_entry_idx_from_tag(tag: str) -> int:
        t = str(tag or "").strip()
        if t in BATTLEGROUP_ENTRY_TAGS:
            return list(BATTLEGROUP_ENTRY_TAGS).index(t)
        return 0

    def _bg_sync_from_selection() -> None:
        nonlocal bg_editor_name_buf, bg_editor_id_buf, bg_editor_cost_buf, bg_editor_entry_i, bg_editor_rows
        nonlocal bg_editor_selected_i
        if not bg_editor_presets:
            bg_editor_name_buf = ""
            bg_editor_id_buf = ""
            bg_editor_cost_buf = "0"
            bg_editor_entry_i = 0
            bg_editor_rows = []
            return
        bg_editor_selected_i = max(0, min(bg_editor_selected_i, len(bg_editor_presets) - 1))
        p = bg_editor_presets[bg_editor_selected_i]
        bg_editor_name_buf = p.name
        bg_editor_id_buf = p.preset_id
        bg_editor_cost_buf = str(int(p.deploy_cost))
        bg_editor_entry_i = _bg_entry_idx_from_tag(p.entry_tag)
        bg_editor_rows = [
            {"class_name": str(r.get("class_name", "")), "label": str(r.get("label", ""))} for r in p.design_rows
        ]

    def _bg_sync_to_selection() -> None:
        if not bg_editor_presets or bg_editor_selected_i < 0 or bg_editor_selected_i >= len(bg_editor_presets):
            return
        p = bg_editor_presets[bg_editor_selected_i]
        name = bg_editor_name_buf.strip() or p.name
        pid = bg_editor_id_buf.strip() or p.preset_id
        cost_raw = bg_editor_cost_buf.strip()
        try:
            cost = max(0, int(cost_raw))
        except ValueError:
            cost = p.deploy_cost
        tag = BATTLEGROUP_ENTRY_TAGS[max(0, min(bg_editor_entry_i, len(BATTLEGROUP_ENTRY_TAGS) - 1))]
        p.name = name
        p.preset_id = pid
        p.deploy_cost = cost
        p.entry_tag = tag
        clean_rows: List[Dict[str, str]] = []
        for r in bg_editor_rows:
            cname = str(r.get("class_name") or "").strip()
            if not cname:
                continue
            try:
                ship_class_by_name(data, cname)
            except KeyError:
                continue
            clean_rows.append({"class_name": cname, "label": str(r.get("label") or "").strip()})
        p.design_rows = clean_rows

    def enter_battlegroup_editor() -> None:
        nonlocal phase, bg_editor_path, bg_editor_presets, bg_editor_selected_i
        nonlocal bg_editor_list_scroll, bg_editor_row_scroll, bg_editor_focus
        bg_editor_path = default_battlegroups_path()
        bg_editor_presets = load_battlegroups(bg_editor_path)
        if not bg_editor_presets:
            fc = cap_names_menu[0]
            bg_editor_presets = [
                BattlegroupPreset(
                    preset_id="preset_1",
                    name="First battlegroup",
                    deploy_cost=0,
                    design_rows=[{"class_name": fc, "label": ""}],
                    entry_tag=str(BATTLEGROUP_ENTRY_TAGS[0]),
                )
            ]
        bg_editor_selected_i = 0
        bg_editor_list_scroll = 0
        bg_editor_row_scroll = 0
        bg_editor_focus = None
        _bg_sync_from_selection()
        phase = "battlegroup_editor"

    def exit_battlegroup_editor(*, save_first: bool) -> None:
        nonlocal phase, bg_editor_focus
        if save_first:
            _bg_sync_to_selection()
            save_battlegroups(bg_editor_path, bg_editor_presets)
        bg_editor_focus = None
        phase = "config"

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        mp_hub_online_actions_ok = False
        if phase == "mp_hub" and _hub_debug_log:
            mp_hub_debug_frames += 1
            if mp_hub_debug_frames <= 5 or mp_hub_debug_frames % 120 == 0:
                _append_fleetrts_debug_log(
                    f"mp_hub alive frame={mp_hub_debug_frames} t={pygame.time.get_ticks()} "
                    f"busy={mp_hub_list_busy} svc={mp_hub_svc_state!r} detail={mp_hub_user_message!r}"
                )
        elif phase != "mp_hub":
            mp_hub_debug_frames = 0
        if phase == "mp_hub":
            if not _mp_hub_can_use_http():
                while True:
                    try:
                        mp_hub_list_q.get_nowait()
                    except queue.Empty:
                        break
                mp_hub_list_busy = False
                if not NET_MP or list_lobbies is None:
                    mp_hub_svc_state = "disabled_build"
                else:
                    mp_hub_svc_state = "disabled_config"
            else:
                _hub_now = pygame.time.get_ticks()
                while True:
                    try:
                        _kind, _payload, _hub_sound = mp_hub_list_q.get_nowait()
                    except queue.Empty:
                        break
                    mp_hub_list_busy = False
                    if _kind == "ok":
                        mp_hub_lobby_rows = _payload
                        mp_hub_svc_state = "online"
                        mp_hub_last_ok_ms = _hub_now
                        mp_hub_user_message = None
                        if _hub_sound:
                            audio.play_positive()
                    else:
                        _raw_e = str(_payload)
                        print(f"[FleetRTS hub] list_lobbies error: {_raw_e}", file=sys.stderr)
                        mp_hub_lobby_rows = []
                        mp_hub_svc_state = "offline"
                        mp_hub_user_message = _friendly_hub_http_message(_raw_e)
                        if _hub_sound:
                            audio.play_negative()
                if mp_hub_list_busy and (_hub_now - mp_hub_list_started_ms) > 15000:
                    mp_hub_list_busy = False
                    _stall = "Lobby list stalled (network thread). Try FLEETRTS_HUB_DISABLE_HTTP=1 to test UI."
                    print(f"[FleetRTS hub] {_stall}", file=sys.stderr)
                    mp_hub_svc_state = "offline"
                    mp_hub_user_message = _friendly_hub_http_message(_stall)
                    mp_hub_lobby_rows = []
                if mp_hub_list_last_ms is None:
                    mp_hub_list_last_ms = _hub_now
                elif not mp_hub_list_busy:
                    _hub_manual = mp_hub_list_last_ms < 0
                    _hub_interval = (_hub_now - mp_hub_list_last_ms) >= 5000
                    if _hub_manual or _hub_interval:
                        if mp_hub_svc_state != "online":
                            mp_hub_svc_state = "checking"
                            mp_hub_user_message = None
                        mp_hub_list_last_ms = _hub_now
                        mp_hub_list_busy = True
                        mp_hub_list_started_ms = _hub_now
                        _hub_base = fleet_http_base
                        _hub_notify = _hub_manual

                        def _hub_list_worker() -> None:
                            try:
                                rows = list_lobbies(_hub_base)
                                mp_hub_list_q.put(("ok", rows, _hub_notify))
                            except Exception as e:
                                mp_hub_list_q.put(("err", str(e)[:160], _hub_notify))

                        threading.Thread(target=_hub_list_worker, daemon=True).start()
            mp_hub_online_actions_ok = _mp_hub_can_use_http() and mp_hub_svc_state == "online"
        if (
            mp_sync_match_active()
            and mp_relay is not None
            and not mp_relay.error
            and phase in ("combat", "debrief")
        ):
            handle_mp_relay_events()
        if phase != "combat":
            pause_menu_open = False
            pause_main_menu_hover = False
        if phase == "debrief":
            debrief_hits, debrief_pr, _ = debrief_hit_regions()
            if post_combat_phase == "mp_lobby" and bool(getattr(mission, "mp_pvp", False)):
                debrief_hits = []
                debrief_pr = pygame.Rect(0, 0, 0, 0)
        else:
            debrief_hits = []
            debrief_pr = pygame.Rect(0, 0, 0, 0)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                win_w, win_h = max(960, event.w), max(540, event.h)
                window = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_q and (event.mod & pygame.KMOD_CTRL):
                running = False
            elif phase == "gameover" and event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                groups, crafts = build_initial_player_fleet(data)
                missiles.clear()
                ballistics.clear()
                vfx_sparks.clear()
                vfx_beams.clear()
                supplies[0] = 100.0
                salvage[0] = 0
                pd_rof_mult[0] = 1.0
                ciws_stacks[0] = 0
                bulk_stacks[0] = 0
                round_idx = 1
                outcome = None
                phase = "combat"
                run_total_score = 0
                last_salvage_gain = 0
                drag_anchor = None
                awaiting_bomber_order_click = False
                awaiting_fighter_order_click = False
                awaiting_capital_context_lmb = False
                store_selected = None
                mission = begin_combat_round(data, groups, 1, random.Random(round_seed(1)), battle_obstacles)
                snap_strike_crafts_to_carriers(crafts)
                cam_x, cam_y = initial_camera_for_fleet(groups)
                test_menu_open = False
                pause_menu_open = False
                pause_main_menu_hover = False
                test_debrief_resume = False
                formation_mode = FORMATION_MODE_RING
                control_groups = [None] * CONTROL_GROUP_SLOTS
                control_groups[0] = all_player_capital_labels(groups)
                cg_weapons_free[:] = [False] * CONTROL_GROUP_SLOTS
                fog = FogState()
                active_pings.clear()
                sensor_ghosts.clear()
                seeker_ghosts.clear()
                ping_ghost_anchor_labels.clear()
                ping_ready_at_ms = 0
                awaiting_attack_move_click = False
                awaiting_attack_target_click = False
                last_cap_click_t = -100000
                last_cap_click_label = None
                tts_prev_sel_sig = ()
                tts_last_enemy_kill_tts = -10**6
                tts_last_player_cap_loss_tts = -10**6
                tts_last_carrier_quip_tts = -10**6
                tts_last_order_quip_tts = -10**6
                tts_last_low_hull_by_label.clear()
            elif phase == "config" and event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    enter_ship_loadouts()
                    audio.play_positive()
                elif event.key == pygame.K_F8:
                    audio.speak_voice("voice_link_test")
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    audio.master_volume = max(0.0, audio.master_volume - 0.05)
                    audio.apply_master_volume()
                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    audio.master_volume = min(1.0, audio.master_volume + 0.05)
                    audio.apply_master_volume()
            elif phase == "config" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = to_internal(event.pos)
                lay = config_menu_layout()
                if lay.design_fleet_btn.collidepoint(mx, my):
                    enter_ship_loadouts()
                    audio.play_positive()
                elif lay.battlegroups_btn.collidepoint(mx, my):
                    enter_battlegroup_editor()
                    audio.play_positive()
                elif lay.multiplayer_btn.collidepoint(mx, my):
                    phase = "mp_hub"
                    mp_net_err = None
                    mp_hub_list_last_ms = -1
                    mp_hub_lobby_scroll = 0
                    mp_hub_lobby_rows = []
                    if _mp_hub_can_use_http():
                        mp_hub_svc_state = "checking"
                        mp_hub_user_message = None
                    elif not NET_MP or list_lobbies is None:
                        mp_hub_svc_state = "disabled_build"
                        mp_hub_user_message = None
                    else:
                        mp_hub_svc_state = "disabled_config"
                        mp_hub_user_message = None
                    audio.play_positive()
                elif lay.tts_toggle.collidepoint(mx, my):
                    audio.tts_voice_enabled = not audio.tts_voice_enabled
                    audio.play_positive()
                elif lay.volume_track.collidepoint(mx, my):
                    config_volume_drag = True
                    _config_volume_from_mouse_x(lay.volume_track, mx, audio)
            elif phase == "config" and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                config_volume_drag = False
            elif phase == "config" and event.type == pygame.MOUSEMOTION:
                if config_volume_drag and pygame.mouse.get_pressed()[0]:
                    mx, my = to_internal(event.pos)
                    _config_volume_from_mouse_x(config_menu_layout().volume_track, mx, audio)
            elif phase == "battlegroup_editor" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    exit_battlegroup_editor(save_first=True)
                    audio.play_positive()
                elif event.key == pygame.K_TAB:
                    if bg_editor_focus == "name":
                        bg_editor_focus = "id"
                    elif bg_editor_focus == "id":
                        bg_editor_focus = "cost"
                    else:
                        bg_editor_focus = "name"
                    audio.play_positive()
                elif bg_editor_focus == "name":
                    if event.key == pygame.K_BACKSPACE:
                        bg_editor_name_buf = bg_editor_name_buf[:-1]
                    elif event.unicode and event.unicode.isprintable() and len(bg_editor_name_buf) < 48:
                        bg_editor_name_buf += event.unicode
                elif bg_editor_focus == "id":
                    if event.key == pygame.K_BACKSPACE:
                        bg_editor_id_buf = bg_editor_id_buf[:-1]
                    elif event.unicode and event.unicode.isprintable() and len(bg_editor_id_buf) < 40:
                        ch = event.unicode
                        if ch.isalnum() or ch in ("_", "-"):
                            bg_editor_id_buf += ch
                elif bg_editor_focus == "cost":
                    if event.key == pygame.K_BACKSPACE:
                        bg_editor_cost_buf = bg_editor_cost_buf[:-1]
                    elif event.unicode and event.unicode.isdigit() and len(bg_editor_cost_buf) < 9:
                        bg_editor_cost_buf += event.unicode
            elif phase == "battlegroup_editor" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = to_internal(event.pos)
                el = battlegroup_editor_layout()
                if el.btn_back.collidepoint(mx, my):
                    exit_battlegroup_editor(save_first=True)
                    audio.play_positive()
                elif el.btn_save.collidepoint(mx, my):
                    _bg_sync_to_selection()
                    save_battlegroups(bg_editor_path, bg_editor_presets)
                    audio.play_positive()
                elif el.btn_new.collidepoint(mx, my):
                    _bg_sync_to_selection()
                    nn = len(bg_editor_presets) + 1
                    fc = cap_names_menu[0]
                    bg_editor_presets.append(
                        BattlegroupPreset(
                            preset_id=f"preset_{nn}",
                            name=f"Battlegroup {nn}",
                            deploy_cost=0,
                            design_rows=[{"class_name": fc, "label": ""}],
                            entry_tag=str(BATTLEGROUP_ENTRY_TAGS[0]),
                        )
                    )
                    bg_editor_selected_i = len(bg_editor_presets) - 1
                    _bg_sync_from_selection()
                    audio.play_positive()
                elif el.btn_del.collidepoint(mx, my):
                    if bg_editor_presets:
                        _bg_sync_to_selection()
                        del bg_editor_presets[bg_editor_selected_i]
                        if not bg_editor_presets:
                            fc = cap_names_menu[0]
                            bg_editor_presets = [
                                BattlegroupPreset(
                                    preset_id="preset_1",
                                    name="First battlegroup",
                                    deploy_cost=0,
                                    design_rows=[{"class_name": fc, "label": ""}],
                                    entry_tag=str(BATTLEGROUP_ENTRY_TAGS[0]),
                                )
                            ]
                            bg_editor_selected_i = 0
                        else:
                            bg_editor_selected_i = min(bg_editor_selected_i, len(bg_editor_presets) - 1)
                        _bg_sync_from_selection()
                    audio.play_positive()
                elif el.fld_name.collidepoint(mx, my):
                    bg_editor_focus = "name"
                elif el.fld_id.collidepoint(mx, my):
                    bg_editor_focus = "id"
                elif el.fld_cost.collidepoint(mx, my):
                    bg_editor_focus = "cost"
                elif el.btn_tag_prev.collidepoint(mx, my):
                    bg_editor_entry_i = (bg_editor_entry_i - 1) % len(BATTLEGROUP_ENTRY_TAGS)
                    audio.play_positive()
                elif el.btn_tag_next.collidepoint(mx, my):
                    bg_editor_entry_i = (bg_editor_entry_i + 1) % len(BATTLEGROUP_ENTRY_TAGS)
                    audio.play_positive()
                elif el.list_rect.collidepoint(mx, my):
                    lh = 26
                    rel = my - el.list_rect.y - 6 + bg_editor_list_scroll
                    idx = rel // lh
                    if 0 <= idx < len(bg_editor_presets):
                        _bg_sync_to_selection()
                        bg_editor_selected_i = idx
                        _bg_sync_from_selection()
                        audio.play_positive()
                elif el.ship_prev.collidepoint(mx, my):
                    bg_editor_ship_pick_i = (bg_editor_ship_pick_i - 1) % len(cap_names_menu)
                    audio.play_positive()
                elif el.ship_next.collidepoint(mx, my):
                    bg_editor_ship_pick_i = (bg_editor_ship_pick_i + 1) % len(cap_names_menu)
                    audio.play_positive()
                elif el.btn_add.collidepoint(mx, my):
                    cnm = cap_names_menu[bg_editor_ship_pick_i % len(cap_names_menu)]
                    bg_editor_rows.append({"class_name": cnm, "label": ""})
                    audio.play_positive()
                elif el.btn_rm.collidepoint(mx, my):
                    if bg_editor_rows:
                        bg_editor_rows.pop()
                    audio.play_positive()
            elif phase == "battlegroup_editor" and event.type == pygame.MOUSEWHEEL:
                imx, imy = to_internal(pygame.mouse.get_pos())
                elw = battlegroup_editor_layout()
                d = -int(round(event.y)) * 24
                if elw.list_rect.collidepoint(imx, imy):
                    bg_editor_list_scroll = max(0, bg_editor_list_scroll + d)
                elif elw.row_area.collidepoint(imx, imy):
                    bg_editor_row_scroll = max(0, bg_editor_row_scroll + d)
            elif phase == "mp_hub" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    phase = "config"
                    mp_join_focus = False
                    mp_name_focus = False
                    audio.play_positive()
                elif (
                    event.key == pygame.K_F4
                    and fleet_http_base
                    and NET_MP
                    and not mp_name_focus
                    and not mp_join_focus
                ):
                    mp_http_authority_choice = (
                        "dedicated" if mp_http_authority_choice != "dedicated" else "player"
                    )
                    audio.play_positive()
                elif mp_name_focus:
                    if event.key == pygame.K_BACKSPACE:
                        mp_name_buffer = mp_name_buffer[:-1]
                    elif event.unicode and event.unicode.isprintable() and len(mp_name_buffer) < 40:
                        mp_name_buffer += event.unicode
                elif mp_join_focus:
                    if event.key == pygame.K_BACKSPACE:
                        mp_join_id_buffer = mp_join_id_buffer[:-1]
                    elif event.unicode and event.unicode.isprintable() and len(mp_join_id_buffer) < 16:
                        mp_join_id_buffer += event.unicode
            elif phase == "mp_hub" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = to_internal(event.pos)
                layh = mp_hub_menu_layout()
                if layh.name_entry_rect.collidepoint(mx, my):
                    mp_name_focus = True
                    mp_join_focus = False
                elif layh.join_entry_rect.collidepoint(mx, my):
                    mp_join_focus = True
                    mp_name_focus = False
                else:
                    mp_name_focus = False
                    mp_join_focus = False
                if (
                    layh.authority_strip.collidepoint(mx, my)
                    and fleet_http_base
                    and NET_MP
                ):
                    mp_http_authority_choice = (
                        "dedicated" if mp_http_authority_choice != "dedicated" else "player"
                    )
                    audio.play_positive()
                if layh.btn_back.collidepoint(mx, my):
                    phase = "config"
                    audio.play_positive()
                elif layh.btn_host.collidepoint(mx, my):
                    disconnect_mp_session()
                    mp_lobby_host = True
                    phase = "mp_lobby"
                    mp_ready = False
                    audio.play_positive()
                elif layh.btn_quick_join.collidepoint(mx, my) and mp_hub_online_actions_ok and quick_join is not None:
                    try:
                        sync_mp_player_name_from_field()
                        lob, joined_as, _qj = quick_join(fleet_http_base, mp_player_name)
                        mp_player_name = joined_as[:48]
                        mp_name_buffer = joined_as[:48]
                        remote_lobby_id = str(lob.get("id") or "")
                        remote_lobby_short = str(lob.get("short_id") or "")
                        remote_lobby_http_players = list(lob.get("players") or [])
                        connect_relay(lob)
                        pls = list(lob.get("players") or [])
                        mp_lobby_host = bool(pls) and pls[0] == mp_player_name
                        mp_ready = False
                        phase = "mp_lobby"
                        mp_hub_list_last_ms = -1
                        if mp_relay and mp_relay.error:
                            mp_net_err = mp_relay.error
                        audio.play_positive()
                    except FleetHttpError as e:
                        mp_hub_user_message = _friendly_hub_http_message(str(e))
                        audio.play_negative()
                elif (
                    layh.lobby_list_rect.collidepoint(mx, my)
                    and _mp_hub_can_use_http()
                    and join_lobby is not None
                    and list_lobbies is not None
                ):
                    hdr_c = 22
                    rel_y = my - layh.lobby_list_rect.y
                    if rel_y < hdr_c:
                        mp_hub_list_last_ms = -1
                    else:
                        row_hc = 20
                        row_i = (rel_y - hdr_c - 4) // row_hc + mp_hub_lobby_scroll
                        if 0 <= row_i < len(mp_hub_lobby_rows):
                            rowd = mp_hub_lobby_rows[row_i]
                            if (
                                mp_hub_online_actions_ok
                                and rowd.get("joinable")
                                and rowd.get("id")
                            ):
                                try:
                                    sync_mp_player_name_from_field()
                                    lob, joined_as = join_lobby(
                                        fleet_http_base, str(rowd.get("id")), mp_player_name
                                    )
                                    mp_player_name = joined_as[:48]
                                    mp_name_buffer = joined_as[:48]
                                    remote_lobby_id = str(lob.get("id") or "")
                                    remote_lobby_short = str(lob.get("short_id") or "")
                                    remote_lobby_http_players = list(lob.get("players") or [])
                                    connect_relay(lob)
                                    pls2 = list(lob.get("players") or [])
                                    mp_lobby_host = bool(pls2) and pls2[0] == mp_player_name
                                    mp_ready = False
                                    phase = "mp_lobby"
                                    mp_hub_list_last_ms = -1
                                    if mp_relay and mp_relay.error:
                                        mp_net_err = mp_relay.error
                                    audio.play_positive()
                                except FleetHttpError as e:
                                    mp_hub_user_message = _friendly_hub_http_message(str(e))
                                    audio.play_negative()
                elif layh.btn_srv_create.collidepoint(mx, my) and mp_hub_online_actions_ok and create_lobby is not None:
                    try:
                        sync_mp_player_name_from_field()
                        lob = create_lobby(
                            fleet_http_base,
                            "FleetRTS",
                            mp_player_name,
                            authoritative=mp_http_authority_choice,
                        )
                        remote_lobby_id = str(lob.get("id") or "")
                        remote_lobby_short = str(lob.get("short_id") or "")
                        remote_lobby_http_players = list(lob.get("players") or [])
                        connect_relay(lob)
                        mp_lobby_host = True
                        mp_ready = False
                        phase = "mp_lobby"
                        if mp_relay and mp_relay.error:
                            mp_net_err = mp_relay.error
                        audio.play_positive()
                    except FleetHttpError as e:
                        mp_hub_user_message = _friendly_hub_http_message(str(e))
                        audio.play_negative()
                elif (
                    layh.btn_srv_join.collidepoint(mx, my)
                    and mp_hub_online_actions_ok
                    and get_lobby_by_short_id is not None
                    and join_lobby is not None
                ):
                    sid = mp_join_id_buffer.strip().lower()
                    if len(sid) < 6:
                        mp_hub_user_message = "Enter the host's game code (8 characters)."
                        audio.play_negative()
                    else:
                        try:
                            sync_mp_player_name_from_field()
                            lob0 = get_lobby_by_short_id(fleet_http_base, sid)
                            lob, joined_as = join_lobby(
                                fleet_http_base, str(lob0.get("id") or ""), mp_player_name
                            )
                            mp_player_name = joined_as[:48]
                            mp_name_buffer = joined_as[:48]
                            remote_lobby_id = str(lob.get("id") or "")
                            remote_lobby_short = str(lob.get("short_id") or "")
                            remote_lobby_http_players = list(lob.get("players") or [])
                            connect_relay(lob)
                            mp_lobby_host = False
                            mp_ready = False
                            phase = "mp_lobby"
                            if mp_relay and mp_relay.error:
                                mp_net_err = mp_relay.error
                            audio.play_positive()
                        except FleetHttpError as e:
                            mp_hub_user_message = _friendly_hub_http_message(str(e))
                            audio.play_negative()
            elif phase == "mp_lobby" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if mp_chat_focus:
                        mp_chat_focus = False
                    else:
                        disconnect_mp_session()
                        phase = "mp_hub"
                        mp_net_err = None
                        mp_hub_list_last_ms = -1
                        mp_hub_lobby_rows = []
                        if _mp_hub_can_use_http():
                            mp_hub_svc_state = "checking"
                            mp_hub_user_message = None
                        elif not NET_MP or list_lobbies is None:
                            mp_hub_svc_state = "disabled_build"
                            mp_hub_user_message = None
                        else:
                            mp_hub_svc_state = "disabled_config"
                            mp_hub_user_message = None
                    audio.play_positive()
                elif mp_chat_focus and remote_lobby_id:
                    if event.key == pygame.K_BACKSPACE:
                        mp_chat_input = mp_chat_input[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        msg = mp_chat_input.strip()
                        if msg and mp_relay is not None and not mp_relay.error:
                            mp_relay.send_payload(lobby_chat(msg))
                            mp_chat_log.append(f"{mp_player_name}: {msg[:240]}")
                            if len(mp_chat_log) > 80:
                                mp_chat_log[:] = mp_chat_log[-80:]
                            mp_chat_input = ""
                            audio.play_positive()
                    elif event.unicode and event.unicode.isprintable() and len(mp_chat_input) < 160:
                        mp_chat_input += event.unicode
            elif phase == "mp_lobby" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = to_internal(event.pos)
                layl = mp_lobby_menu_layout()
                if layl.chat_input_rect.collidepoint(mx, my) and remote_lobby_id:
                    mp_chat_focus = True
                elif layl.chat_log_rect.collidepoint(mx, my) and remote_lobby_id:
                    mp_chat_focus = True
                else:
                    mp_chat_focus = False
                if layl.btn_back.collidepoint(mx, my):
                    disconnect_mp_session()
                    phase = "mp_hub"
                    mp_net_err = None
                    mp_hub_list_last_ms = -1
                    mp_hub_lobby_rows = []
                    if _mp_hub_can_use_http():
                        mp_hub_svc_state = "checking"
                        mp_hub_user_message = None
                    elif not NET_MP or list_lobbies is None:
                        mp_hub_svc_state = "disabled_build"
                        mp_hub_user_message = None
                    else:
                        mp_hub_svc_state = "disabled_config"
                        mp_hub_user_message = None
                    audio.play_positive()
                elif layl.btn_fleet.collidepoint(mx, my):
                    enter_ship_loadouts(True)
                    audio.play_positive()
                elif layl.btn_ready.collidepoint(mx, my):
                    mp_ready = not mp_ready
                    if remote_lobby_id and mp_relay is not None and not mp_relay.error:
                        mp_relay.send_payload(lobby_ready(mp_ready))
                    audio.play_positive()
                elif layl.btn_start.collidepoint(mx, my):
                    if mp_lobby_host and mp_ready:
                        if remote_lobby_id and mp_relay is not None and not mp_relay.error:
                            blocking = [
                                p
                                for p in remote_relay_players
                                if p != mp_player_name and remote_loadouts.get(p, False)
                            ]
                            if blocking:
                                tail = ", ".join(blocking[:4])
                                if len(blocking) > 4:
                                    tail += ", …"
                                mp_toast_text = f"Can't start — in fleet design: {tail}"
                                mp_toast_until_ms = pygame.time.get_ticks() + 5200
                                audio.play_negative()
                            else:
                                mp_match_generation += 1
                                mgen = mp_match_generation
                                mseed = random.randint(1, 2**31 - 1)
                                _players = [p for p in remote_relay_players if isinstance(p, str) and p.strip()]
                                if mp_player_name not in _players:
                                    _players.append(mp_player_name)
                                _players = normalize_mp_player_order(_players)
                                _colors: Dict[str, int] = {mp_player_name: int(mp_player_color_id)}
                                for _pn, _cid in remote_player_colors.items():
                                    _colors[str(_pn)] = int(max(0, min(int(_cid), 5)))
                                _designs: Dict[str, List[Dict[str, str]]] = {
                                    mp_player_name: export_player_fleet_design(mp_fleet_groups)
                                }
                                for _pn, _rows in mp_player_fleet_designs.items():
                                    if isinstance(_rows, list):
                                        _designs[str(_pn)] = _rows
                                _setup = {"players": _players, "colors": _colors, "designs": _designs}
                                mp_relay.send_payload(
                                    start_match(
                                        generation=mgen,
                                        seed=mseed,
                                        round_idx=mp_round_idx,
                                        coop=mp_mode_coop,
                                        use_asteroids=mp_use_asteroids,
                                        enemy_pressure=mp_enemy_pressure,
                                        player_setup=_setup,
                                    )
                                )
                                launch_mp_combat(mseed, _setup)
                                audio.play_positive()
                        else:
                            launch_mp_combat()
                            audio.play_positive()
                    else:
                        audio.play_negative()
                elif mp_lobby_host:
                    if layl.row_mode.collidepoint(mx, my):
                        mp_mode_coop = not mp_mode_coop
                        if not mp_mode_coop:
                            mp_enemy_pressure = 0
                        send_host_config_if_online()
                        audio.play_positive()
                    elif layl.row_mission.collidepoint(mx, my):
                        mp_player_color_id = (mp_player_color_id + 1) % len(MP_PLAYER_PALETTE)
                        if remote_lobby_id and mp_relay is not None and not mp_relay.error:
                            mp_relay.send_payload(lobby_presence(in_fleet_design=False, color_id=mp_player_color_id))
                            if lobby_loadout is not None:
                                mp_relay.send_payload(
                                    lobby_loadout(payload={"fleet": export_player_fleet_design(mp_fleet_groups)})
                                )
                        mp_toast_text = f"Player color set to slot {mp_player_color_id + 1}/6."
                        mp_toast_until_ms = pygame.time.get_ticks() + 2200
                        audio.play_positive()
                    elif layl.row_rocks.collidepoint(mx, my):
                        mp_use_asteroids = not mp_use_asteroids
                        send_host_config_if_online()
                        audio.play_positive()
                    elif mp_mode_coop and layl.row_enemy.collidepoint(mx, my):
                        mp_enemy_pressure = (mp_enemy_pressure + 1) % 4
                        send_host_config_if_online()
                        audio.play_positive()
            elif phase == "ship_loadouts" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if mp_loadouts_active:
                        finish_mp_ship_loadouts_to_lobby()
                    else:
                        loadout_preview_groups.clear()
                        loadout_preview_crafts.clear()
                        loadout_choice_map.clear()
                        phase = "config"
                    audio.play_positive()
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if mp_loadouts_active:
                        finish_mp_ship_loadouts_to_lobby()
                    else:
                        launch_mission_combat()
                    audio.play_positive()
            elif phase == "ship_loadouts" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = to_internal(event.pos)
                act = ship_loadouts_resolve_click(
                    mx, my, data, loadout_preview_groups, loadout_selected_i, loadout_roster_scroll
                )
                if act is None:
                    pass
                elif act[0] == "back":
                    if mp_loadouts_active:
                        finish_mp_ship_loadouts_to_lobby()
                    else:
                        loadout_preview_groups.clear()
                        loadout_preview_crafts.clear()
                        loadout_choice_map.clear()
                        phase = "config"
                    audio.play_positive()
                elif act[0] == "launch":
                    if mp_loadouts_active:
                        finish_mp_ship_loadouts_to_lobby()
                    else:
                        launch_mission_combat()
                    audio.play_positive()
                elif act[0] == "roster":
                    loadout_selected_i = int(act[1])
                    audio.play_positive()
                elif act[0] == "strip":
                    roster = loadout_player_capitals_sorted(loadout_preview_groups)
                    if 0 <= loadout_selected_i < len(roster):
                        if loadout_try_remove_capital(
                            data,
                            loadout_preview_groups,
                            loadout_preview_crafts,
                            roster[loadout_selected_i],
                            deployment_scrap,
                            loadout_choice_map,
                        ):
                            roster2 = loadout_player_capitals_sorted(loadout_preview_groups)
                            loadout_selected_i = min(loadout_selected_i, max(0, len(roster2) - 1))
                            audio.play_positive()
                        else:
                            audio.play_negative()
                    else:
                        audio.play_negative()
                elif act[0] == "recruit":
                    if loadout_try_add_capital(
                        data,
                        loadout_preview_groups,
                        loadout_preview_crafts,
                        str(act[1]),
                        deployment_scrap,
                        loadout_choice_map,
                    ):
                        audio.play_positive()
                    else:
                        audio.play_negative()
                elif act[0] == "hardpoint":
                    g_hit = next((x for x in loadout_preview_groups if x.label == act[1]), None)
                    if g_hit and apply_deployment_weapon_choice(
                        data,
                        g_hit,
                        int(act[2]),
                        int(act[3]),
                        loadout_choice_map,
                        deployment_scrap,
                    ):
                        audio.play_positive()
                    else:
                        audio.play_negative()
                elif act[0] == "hangar":
                    g_hit = next((x for x in loadout_preview_groups if x.label == act[1]), None)
                    if g_hit and apply_carrier_hangar_preset(
                        data,
                        g_hit,
                        int(act[2]),
                        loadout_preview_crafts,
                        deployment_scrap,
                    ):
                        audio.play_positive()
                    else:
                        audio.play_negative()
            elif phase == "ship_loadouts" and event.type == pygame.MOUSEWHEEL:
                loadout_roster_scroll = clamp_loadout_roster_scroll(
                    loadout_preview_groups,
                    loadout_roster_scroll - int(event.y) * 28,
                )
            elif phase == "mp_hub" and event.type == pygame.MOUSEWHEEL:
                layw = mp_hub_menu_layout()
                mxw, myw = to_internal(event.pos)
                if layw.lobby_list_rect.collidepoint(mxw, myw):
                    hdr_w = 22
                    row_hw = 20
                    vis_w = max(1, (layw.lobby_list_rect.h - hdr_w - 4) // row_hw)
                    max_sc = max(0, len(mp_hub_lobby_rows) - vis_w)
                    mp_hub_lobby_scroll = max(0, min(max_sc, mp_hub_lobby_scroll - int(event.y)))
            elif phase == "combat" and event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pause_menu_open = not pause_menu_open
                if pause_menu_open:
                    drag_anchor = None
                    awaiting_attack_move_click = False
                    awaiting_attack_target_click = False
                    awaiting_bomber_order_click = False
                    awaiting_fighter_order_click = False
                    awaiting_capital_context_lmb = False
                    test_menu_open = False
                    pause_main_menu_hover = False
            elif phase == "combat" and not pause_menu_open and event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
                test_menu_open = not test_menu_open
            elif test_menu_open and phase == "combat" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:
                    test_menu_open = False
                    test_debrief_resume = True
                    outcome = "[TEST] Store — SPACE returns to this fight (no round advance)"
                    phase = "debrief"
                    store_selected = None
                    store_hover = None
                    last_salvage_gain = 0
                elif event.key == pygame.K_2:
                    salvage[0] += TEST_SALVAGE_GRANT
                    audio.play_positive()
            elif phase == "debrief" and event.type == pygame.MOUSEMOTION:
                store_hover = None
                mx, my = to_internal(event.pos)
                for r, iid in debrief_hits:
                    if r.collidepoint(mx, my):
                        store_hover = iid
                        break
            elif phase == "debrief" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = to_internal(event.pos)
                if debrief_pr.collidepoint(mx, my):
                    buy_id = store_selected or store_hover
                    if buy_id and attempt_debrief_purchase(
                        buy_id,
                        data,
                        groups,
                        crafts,
                        salvage,
                        supplies,
                        pd_rof_mult,
                        ciws_stacks,
                        bulk_stacks,
                        control_groups,
                    ):
                        audio.play_positive()
                    else:
                        audio.play_negative()
                else:
                    for r, iid in debrief_hits:
                        if r.collidepoint(mx, my):
                            store_selected = iid
                            break
            elif phase == "debrief" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    if post_combat_phase == "mp_lobby":
                        groups[:] = [g for g in groups if g.side == "player" and not g.dead]
                        _roster_lp = (
                            normalize_mp_player_order(remote_relay_players)
                            if (NET_MP and remote_lobby_id and remote_relay_players)
                            else None
                        )
                        reset_mp_fleets_for_lobby(
                            groups,
                            crafts,
                            mp_mode_coop=mp_mode_coop,
                            roster_names=_roster_lp,
                        )
                        for g in groups:
                            if g.side == "player" and g.class_name == "Carrier":
                                clear_carrier_air_orders(g)
                        mp_fleet_groups.clear()
                        mp_fleet_groups.extend(groups)
                        mp_fleet_crafts.clear()
                        mp_fleet_crafts.extend(
                            c for c in crafts if c.side == "player" and not c.dead and not c.parent.dead
                        )
                        mp_round_idx += 1
                        outcome = None
                        phase = "mp_lobby"
                        post_combat_phase = None
                        mp_ready = False
                        missiles.clear()
                        ballistics.clear()
                        vfx_sparks.clear()
                        vfx_beams.clear()
                        audio.play_positive()
                        store_selected = None
                        store_hover = None
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                        awaiting_attack_move_click = False
                        awaiting_attack_target_click = False
                        last_cap_click_t = -100000
                        last_cap_click_label = None
                        snap_strike_crafts_to_carriers(crafts)
                    elif test_debrief_resume:
                        test_debrief_resume = False
                        outcome = None
                        phase = "combat"
                        missiles.clear()
                        ballistics.clear()
                        vfx_sparks.clear()
                        vfx_beams.clear()
                        audio.play_positive()
                        store_selected = None
                        store_hover = None
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                        awaiting_attack_move_click = False
                        awaiting_attack_target_click = False
                        last_cap_click_t = -100000
                        last_cap_click_label = None
                        snap_strike_crafts_to_carriers(crafts)
                    else:
                        groups[:] = [g for g in groups if g.side == "player" and not g.dead]
                        reset_player_spawn_positions(groups, crafts)
                        for g in groups:
                            if g.side == "player" and g.class_name == "Carrier":
                                clear_carrier_air_orders(g)
                        round_idx += 1
                        outcome = None
                        phase = "combat"
                        missiles.clear()
                        ballistics.clear()
                        vfx_sparks.clear()
                        vfx_beams.clear()
                        audio.play_positive()
                        store_selected = None
                        mission = begin_combat_round(
                            data, groups, round_idx, random.Random(round_seed(round_idx)), battle_obstacles
                        )
                        fog = FogState()
                        active_pings.clear()
                        sensor_ghosts.clear()
                        seeker_ghosts.clear()
                        ping_ghost_anchor_labels.clear()
                        ping_ready_at_ms = 0
                        cam_x, cam_y = initial_camera_for_fleet(groups)
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                        awaiting_attack_move_click = False
                        awaiting_attack_target_click = False
                        last_cap_click_t = -100000
                        last_cap_click_label = None
                elif event.key == pygame.K_RETURN:
                    buy_id = store_selected or store_hover
                    if buy_id and attempt_debrief_purchase(
                        buy_id,
                        data,
                        groups,
                        crafts,
                        salvage,
                        supplies,
                        pd_rof_mult,
                        ciws_stacks,
                        bulk_stacks,
                        control_groups,
                    ):
                        audio.play_positive()
                    else:
                        audio.play_negative()
                elif event.key in STORE_ITEM_BY_KEY:
                    iid = STORE_ITEM_BY_KEY[event.key]
                    store_selected = iid
                    if attempt_debrief_purchase(
                        iid,
                        data,
                        groups,
                        crafts,
                        salvage,
                        supplies,
                        pd_rof_mult,
                        ciws_stacks,
                        bulk_stacks,
                        control_groups,
                    ):
                        audio.play_positive()
                    else:
                        audio.play_negative()
            elif phase == "combat":
                if pause_menu_open:
                    if event.type == pygame.MOUSEMOTION:
                        pause_main_menu_hover = pause_main_menu_button_rect().collidepoint(to_internal(event.pos))
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        if pause_main_menu_button_rect().collidepoint(to_internal(event.pos)):
                            running = False
                elif event.type == pygame.KEYDOWN:
                    mods = pygame.key.get_mods()
                    mp_own_k = _mp_owned_pick_owner()
                    if mods & pygame.KMOD_CTRL and pygame.K_1 <= event.key <= pygame.K_9:
                        slot = event.key - pygame.K_1
                        sel = [
                            g
                            for g in groups
                            if g.side == "player"
                            and g.selected
                            and not g.dead
                            and g.render_capital
                            and (mp_own_k is None or getattr(g, "owner_id", "") == mp_own_k)
                        ]
                        if sel:
                            labs = [g.label for g in sel]
                            if mp_is_net_client():
                                mp_send_client("control_assign", {"slot": slot, "labels": labs})
                            control_groups[slot] = labs
                    elif (
                        not (mods & pygame.KMOD_CTRL)
                        and not (mods & pygame.KMOD_ALT)
                        and pygame.K_1 <= event.key <= pygame.K_9
                    ):
                        slot = event.key - pygame.K_1
                        labels = control_groups[slot]
                        if labels:
                            picked = [
                                g
                                for g in groups
                                if g.side == "player"
                                and not g.dead
                                and g.render_capital
                                and g.label in labels
                                and (mp_own_k is None or getattr(g, "owner_id", "") == mp_own_k)
                            ]
                            if picked:
                                if mods & pygame.KMOD_SHIFT:
                                    add_to_selection(groups, picked)
                                else:
                                    set_selection(groups, picked)
                    elif event.key == pygame.K_HOME:
                        sel_cam = [
                            g
                            for g in groups
                            if g.side == "player"
                            and g.selected
                            and not g.dead
                            and g.render_capital
                            and (mp_own_k is None or getattr(g, "owner_id", "") == mp_own_k)
                        ]
                        if not sel_cam:
                            sel_cam = [
                                g
                                for g in groups
                                if g.side == "player"
                                and not g.dead
                                and g.render_capital
                                and (mp_own_k is None or getattr(g, "owner_id", "") == mp_own_k)
                            ]
                        cam_x, cam_y = focus_camera_for_selection(cam_x, cam_y, sel_cam)
                    elif event.key == pygame.K_h:
                        if mp_is_net_client():
                            mp_send_client(
                                "hold",
                                {
                                    "group_labels": mp_sel_player_group_labels(),
                                    "craft_labels": mp_sel_craft_labels(),
                                },
                            )
                        else:
                            for g in groups:
                                if g.side != "player" or g.dead or not g.selected:
                                    continue
                                if mp_own_k is not None and getattr(g, "owner_id", "") != mp_own_k:
                                    continue
                                g.hold_position()
                                if g.class_name == "Carrier":
                                    clear_carrier_air_orders(g)
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                        awaiting_attack_move_click = False
                        awaiting_attack_target_click = False
                    elif event.key == pygame.K_a:
                        awaiting_attack_move_click = True
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                        awaiting_attack_target_click = False
                    elif event.key == pygame.K_g:
                        awaiting_attack_target_click = True
                        awaiting_attack_move_click = False
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                    elif event.key == pygame.K_b:
                        if mp_is_net_client():
                            mp_send_client("formation_cycle", {})
                        formation_mode = (formation_mode + 1) % 3
                    elif event.key == pygame.K_f:
                        sel = [
                            g
                            for g in groups
                            if g.side == "player"
                            and g.selected
                            and not g.dead
                            and (mp_own_k is None or getattr(g, "owner_id", "") == mp_own_k)
                        ]
                        wing_sel = [
                            c
                            for c in crafts
                            if c.side == "player"
                            and c.selected
                            and not c.dead
                            and c.parent.class_name == "Carrier"
                            and (mp_own_k is None or getattr(c, "owner_id", "") == mp_own_k)
                        ]
                        fight_w = any(c.class_name in ("Fighter", "Interceptor") for c in wing_sel)
                        bomb_w = any(c.class_name == "Bomber" for c in wing_sel)
                        if fight_w and bomb_w:
                            awaiting_fighter_order_click = True
                            awaiting_bomber_order_click = True
                            awaiting_capital_context_lmb = False
                            awaiting_attack_move_click = False
                            awaiting_attack_target_click = False
                        elif fight_w:
                            awaiting_fighter_order_click = True
                            awaiting_bomber_order_click = False
                            awaiting_capital_context_lmb = False
                            awaiting_attack_move_click = False
                            awaiting_attack_target_click = False
                        elif bomb_w:
                            awaiting_bomber_order_click = True
                            awaiting_fighter_order_click = False
                            awaiting_capital_context_lmb = False
                            awaiting_attack_move_click = False
                            awaiting_attack_target_click = False
                        elif any(g.class_name == "Carrier" for g in sel):
                            awaiting_fighter_order_click = True
                            awaiting_bomber_order_click = True
                            awaiting_capital_context_lmb = False
                            awaiting_attack_move_click = False
                            awaiting_attack_target_click = False
                        elif any(g.render_capital for g in sel):
                            awaiting_capital_context_lmb = True
                            awaiting_bomber_order_click = False
                            awaiting_fighter_order_click = False
                            awaiting_attack_move_click = False
                            awaiting_attack_target_click = False
                    elif event.key == pygame.K_c:
                        if mp_is_net_client():
                            mp_send_client(
                                "recall_carriers",
                                {
                                    "group_labels": mp_sel_player_group_labels(),
                                    "craft_labels": mp_sel_craft_labels(),
                                },
                            )
                        else:
                            for g in groups:
                                if (
                                    g.side == "player"
                                    and g.selected
                                    and g.class_name == "Carrier"
                                    and (mp_own_k is None or getattr(g, "owner_id", "") == mp_own_k)
                                ):
                                    clear_carrier_air_orders(g)
                        awaiting_bomber_order_click = False
                        awaiting_fighter_order_click = False
                        awaiting_capital_context_lmb = False
                        awaiting_attack_move_click = False
                        awaiting_attack_target_click = False
                    elif event.key == pygame.K_p:
                        nowp = pygame.time.get_ticks()
                        if mp_is_net_client():
                            if nowp >= ping_ready_at_ms:
                                mp_send_client("sensor_ping", {"rng_seed": nowp % 100003})
                                audio.play_positive()
                            else:
                                audio.play_negative()
                        elif nowp >= ping_ready_at_ms:
                            spawn_active_sensor_pings(
                                groups,
                                crafts,
                                active_pings,
                                sensor_ghosts,
                                mission.obstacles,
                                random.Random(nowp % 100003),
                                anchor_labels=ping_ghost_anchor_labels,
                            )
                            ping_ready_at_ms = nowp + int(ACTIVE_PING_COOLDOWN * 1000)
                            audio.play_positive()
                        else:
                            audio.play_negative()
                    elif event.key == pygame.K_7:
                        sh = pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[pygame.K_RSHIFT]
                        select_strike_wing_for_carriers(crafts, groups, 0, sh, mp_own_k)
                    elif event.key == pygame.K_8:
                        sh = pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[pygame.K_RSHIFT]
                        select_strike_wing_for_carriers(crafts, groups, 1, sh, mp_own_k)
                    elif event.key == pygame.K_9:
                        clear_craft_selection(crafts)
                        awaiting_fighter_order_click = False
                        awaiting_bomber_order_click = False
                        awaiting_capital_context_lmb = False
                    elif event.key == pygame.K_F8:
                        audio.speak_voice("voice_link_test")
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = to_internal(event.pos)
                    if my >= VIEW_H:
                        if event.button == 1:
                            hit_order = False
                            mp_own_ord = _mp_owned_pick_owner()
                            if weapon_stance_toggle_rect().collidepoint(mx, my):
                                if mp_is_net_client():
                                    mp_send_client(
                                        "weapons_toggle",
                                        {
                                            "group_labels": mp_sel_player_group_labels(),
                                            "craft_labels": mp_sel_craft_labels(),
                                        },
                                    )
                                    audio.play_positive()
                                elif toggle_weapon_stance_for_selection(groups, control_groups, cg_weapons_free):
                                    audio.play_positive()
                                else:
                                    audio.play_negative()
                                hit_order = True
                            if not hit_order:
                                for rect, act, _ in order_command_cells():
                                    if rect.collidepoint(mx, my):
                                        hit_order = True
                                        if act == "move":
                                            order_hint_msg = "Right-click map: move — Shift+drag: line formation"
                                            order_hint_until = pygame.time.get_ticks() + 5500
                                            awaiting_attack_move_click = False
                                            awaiting_attack_target_click = False
                                            awaiting_bomber_order_click = False
                                            awaiting_fighter_order_click = False
                                            awaiting_capital_context_lmb = False
                                            audio.play_positive()
                                        elif act == "attack_move":
                                            awaiting_attack_move_click = True
                                            awaiting_bomber_order_click = False
                                            awaiting_fighter_order_click = False
                                            awaiting_capital_context_lmb = False
                                            awaiting_attack_target_click = False
                                            audio.play_positive()
                                        elif act == "attack_target":
                                            awaiting_attack_target_click = True
                                            awaiting_attack_move_click = False
                                            awaiting_bomber_order_click = False
                                            awaiting_fighter_order_click = False
                                            awaiting_capital_context_lmb = False
                                            audio.play_positive()
                                        elif act == "hold":
                                            if mp_is_net_client():
                                                mp_send_client(
                                                    "hold",
                                                    {
                                                        "group_labels": mp_sel_player_group_labels(),
                                                        "craft_labels": mp_sel_craft_labels(),
                                                    },
                                                )
                                            else:
                                                for g in groups:
                                                    if g.side != "player" or g.dead or not g.selected:
                                                        continue
                                                    if mp_own_ord is not None and getattr(g, "owner_id", "") != mp_own_ord:
                                                        continue
                                                    g.hold_position()
                                                    if g.class_name == "Carrier":
                                                        clear_carrier_air_orders(g)
                                            awaiting_bomber_order_click = False
                                            awaiting_fighter_order_click = False
                                            awaiting_capital_context_lmb = False
                                            awaiting_attack_move_click = False
                                            awaiting_attack_target_click = False
                                            audio.play_positive()
                                        elif act == "formation":
                                            if mp_is_net_client():
                                                mp_send_client("formation_cycle", {})
                                            formation_mode = (formation_mode + 1) % 3
                                            audio.play_positive()
                                        elif act == "strike":
                                            ssel = [
                                                g
                                                for g in groups
                                                if g.side == "player"
                                                and g.selected
                                                and not g.dead
                                                and (mp_own_ord is None or getattr(g, "owner_id", "") == mp_own_ord)
                                            ]
                                            wsel = [
                                                c
                                                for c in crafts
                                                if c.side == "player"
                                                and c.selected
                                                and not c.dead
                                                and c.parent.class_name == "Carrier"
                                                and (mp_own_ord is None or getattr(c, "owner_id", "") == mp_own_ord)
                                            ]
                                            fight_ws = any(
                                                c.class_name in ("Fighter", "Interceptor") for c in wsel
                                            )
                                            bomb_ws = any(c.class_name == "Bomber" for c in wsel)
                                            if fight_ws and bomb_ws:
                                                awaiting_fighter_order_click = True
                                                awaiting_bomber_order_click = True
                                                awaiting_capital_context_lmb = False
                                                awaiting_attack_move_click = False
                                                awaiting_attack_target_click = False
                                                audio.play_positive()
                                            elif fight_ws:
                                                awaiting_fighter_order_click = True
                                                awaiting_bomber_order_click = False
                                                awaiting_capital_context_lmb = False
                                                awaiting_attack_move_click = False
                                                awaiting_attack_target_click = False
                                                audio.play_positive()
                                            elif bomb_ws:
                                                awaiting_bomber_order_click = True
                                                awaiting_fighter_order_click = False
                                                awaiting_capital_context_lmb = False
                                                awaiting_attack_move_click = False
                                                awaiting_attack_target_click = False
                                                audio.play_positive()
                                            elif any(g.class_name == "Carrier" for g in ssel):
                                                awaiting_fighter_order_click = True
                                                awaiting_bomber_order_click = True
                                                awaiting_capital_context_lmb = False
                                                awaiting_attack_move_click = False
                                                awaiting_attack_target_click = False
                                                audio.play_positive()
                                            elif any(g.render_capital for g in ssel):
                                                awaiting_capital_context_lmb = True
                                                awaiting_bomber_order_click = False
                                                awaiting_fighter_order_click = False
                                                awaiting_attack_move_click = False
                                                awaiting_attack_target_click = False
                                                audio.play_positive()
                                            else:
                                                audio.play_negative()
                                        elif act == "recall":
                                            if mp_is_net_client():
                                                mp_send_client(
                                                    "recall_carriers",
                                                    {
                                                        "group_labels": mp_sel_player_group_labels(),
                                                        "craft_labels": mp_sel_craft_labels(),
                                                    },
                                                )
                                            else:
                                                for g in groups:
                                                    if (
                                                        g.side == "player"
                                                        and g.selected
                                                        and g.class_name == "Carrier"
                                                        and (
                                                            mp_own_ord is None
                                                            or getattr(g, "owner_id", "") == mp_own_ord
                                                        )
                                                    ):
                                                        clear_carrier_air_orders(g)
                                            awaiting_bomber_order_click = False
                                            awaiting_fighter_order_click = False
                                            awaiting_capital_context_lmb = False
                                            awaiting_attack_move_click = False
                                            awaiting_attack_target_click = False
                                            audio.play_positive()
                                        elif act == "ping":
                                            nowp = pygame.time.get_ticks()
                                            if mp_is_net_client():
                                                if nowp >= ping_ready_at_ms:
                                                    mp_send_client("sensor_ping", {"rng_seed": nowp % 100003})
                                                    audio.play_positive()
                                                else:
                                                    audio.play_negative()
                                            elif nowp >= ping_ready_at_ms:
                                                spawn_active_sensor_pings(
                                                    groups,
                                                    crafts,
                                                    active_pings,
                                                    sensor_ghosts,
                                                    mission.obstacles,
                                                    random.Random(nowp % 100003),
                                                    anchor_labels=ping_ghost_anchor_labels,
                                                )
                                                ping_ready_at_ms = nowp + int(ACTIVE_PING_COOLDOWN * 1000)
                                                audio.play_positive()
                                            else:
                                                audio.play_negative()
                                        elif act == "focus":
                                            sel_cam = [
                                                g
                                                for g in groups
                                                if g.side == "player"
                                                and g.selected
                                                and not g.dead
                                                and g.render_capital
                                                and (mp_own_ord is None or getattr(g, "owner_id", "") == mp_own_ord)
                                            ]
                                            if not sel_cam:
                                                sel_cam = [
                                                    g
                                                    for g in groups
                                                    if g.side == "player"
                                                    and not g.dead
                                                    and g.render_capital
                                                    and (mp_own_ord is None or getattr(g, "owner_id", "") == mp_own_ord)
                                                ]
                                            cam_x, cam_y = focus_camera_for_selection(cam_x, cam_y, sel_cam)
                                            audio.play_positive()
                                        break
                            if not hit_order:
                                for si in range(CONTROL_GROUP_SLOTS):
                                    if control_group_slot_rect(si).collidepoint(mx, my):
                                        labels = control_groups[si]
                                        if labels:
                                            picked = [
                                                g
                                                for g in groups
                                                if g.side == "player"
                                                and not g.dead
                                                and g.render_capital
                                                and g.label in labels
                                                and (mp_own_ord is None or getattr(g, "owner_id", "") == mp_own_ord)
                                            ]
                                            if picked:
                                                if pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[
                                                    pygame.K_RSHIFT
                                                ]:
                                                    add_to_selection(groups, picked)
                                                else:
                                                    clear_craft_selection(crafts)
                                                    set_selection(groups, picked)
                                                audio.play_positive()
                                        break
                    else:
                        if event.button == 1:
                            drag_anchor = (mx, my)
                        elif event.button == 3:
                            mp_own = _mp_owned_pick_owner()
                            sel = [
                                g
                                for g in groups
                                if g.side == "player"
                                and g.selected
                                and not g.dead
                                and (mp_own is None or getattr(g, "owner_id", "") == mp_own)
                            ]
                            sel_caps = [g for g in sel if g.render_capital]
                            wpx, wpy = screen_to_world_waypoint(float(mx), float(my), cam_x, cam_y)
                            now_rmb = pygame.time.get_ticks()
                            if my < VIEW_H:
                                awaiting_capital_context_lmb = False
                            wing_rsel = [
                                c
                                for c in crafts
                                if c.side == "player"
                                and c.selected
                                and not c.dead
                                and c.parent.class_name == "Carrier"
                                and (mp_own is None or getattr(c, "owner_id", "") == mp_own)
                            ]
                            if awaiting_bomber_order_click and my < VIEW_H:
                                eligible = any(g.class_name == "Carrier" for g in sel) or any(
                                    c.class_name == "Bomber" for c in wing_rsel
                                )
                                if mp_is_net_client():
                                    if eligible:
                                        mp_send_client(
                                            "bomber_strike_pick",
                                            {
                                                "cam_x": float(cam_x),
                                                "cam_y": float(cam_y),
                                                "mx": float(mx),
                                                "my": float(my),
                                                "group_labels": mp_sel_player_group_labels(),
                                                "craft_labels": mp_sel_craft_labels(),
                                            },
                                        )
                                        tts_last_order_quip_tts = tts_speak_if_cooled(
                                            audio,
                                            "bombers_acknowledge",
                                            now_rmb,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    awaiting_bomber_order_click = False
                                    awaiting_fighter_order_click = False
                                    awaiting_capital_context_lmb = False
                                    awaiting_attack_move_click = False
                                    awaiting_attack_target_click = False
                                elif eligible:
                                    mark = pick_hostile_at(
                                        groups, crafts, mx, my, cam_x, cam_y, **_mp_pick_hostile_kwargs()
                                    )
                                    if mark is None:
                                        if (
                                            mission.kind == "strike"
                                            and mission.objective
                                            and not mission.objective.dead
                                            and pick_strike_objective_at(
                                                mission.objective, mx, my, cam_x, cam_y
                                            )
                                        ):
                                            mark = mission.objective
                                    ok = apply_bomber_context_order(
                                        data, crafts, sel, wpx, wpy, mark
                                    )
                                    awaiting_bomber_order_click = False
                                    awaiting_fighter_order_click = False
                                    awaiting_capital_context_lmb = False
                                    awaiting_attack_move_click = False
                                    awaiting_attack_target_click = False
                                    if ok:
                                        tts_last_order_quip_tts = tts_speak_if_cooled(
                                            audio,
                                            "bombers_acknowledge",
                                            now_rmb,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    else:
                                        audio.play_negative()
                                else:
                                    awaiting_bomber_order_click = False
                                    awaiting_fighter_order_click = False
                                    awaiting_capital_context_lmb = False
                            elif awaiting_fighter_order_click and my < VIEW_H:
                                eligible = any(g.class_name == "Carrier" for g in sel) or any(
                                    c.class_name in ("Fighter", "Interceptor") for c in wing_rsel
                                )
                                if mp_is_net_client():
                                    if eligible:
                                        mp_send_client(
                                            "fighter_strike_pick",
                                            {
                                                "cam_x": float(cam_x),
                                                "cam_y": float(cam_y),
                                                "mx": float(mx),
                                                "my": float(my),
                                                "group_labels": mp_sel_player_group_labels(),
                                                "craft_labels": mp_sel_craft_labels(),
                                            },
                                        )
                                        tts_last_order_quip_tts = tts_speak_if_cooled(
                                            audio,
                                            "fighters_acknowledge",
                                            now_rmb,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    awaiting_fighter_order_click = False
                                    awaiting_bomber_order_click = False
                                    awaiting_capital_context_lmb = False
                                    awaiting_attack_move_click = False
                                    awaiting_attack_target_click = False
                                elif eligible:
                                    mark = pick_hostile_at(
                                        groups, crafts, mx, my, cam_x, cam_y, **_mp_pick_hostile_kwargs()
                                    )
                                    if mark is None:
                                        if (
                                            mission.kind == "strike"
                                            and mission.objective
                                            and not mission.objective.dead
                                            and pick_strike_objective_at(
                                                mission.objective, mx, my, cam_x, cam_y
                                            )
                                        ):
                                            mark = mission.objective
                                    ok = apply_fighter_strike_order(
                                        data, crafts, sel, wpx, wpy, mark
                                    )
                                    awaiting_fighter_order_click = False
                                    awaiting_bomber_order_click = False
                                    awaiting_capital_context_lmb = False
                                    awaiting_attack_move_click = False
                                    awaiting_attack_target_click = False
                                    if ok:
                                        tts_last_order_quip_tts = tts_speak_if_cooled(
                                            audio,
                                            "fighters_acknowledge",
                                            now_rmb,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    else:
                                        audio.play_negative()
                                else:
                                    awaiting_fighter_order_click = False
                                    awaiting_bomber_order_click = False
                                    awaiting_capital_context_lmb = False
                            elif my < VIEW_H and sel_caps:
                                if mp_is_net_client():
                                    mp_send_client(
                                        "capital_context_pick",
                                        {
                                            "cam_x": float(cam_x),
                                            "cam_y": float(cam_y),
                                            "mx": float(mx),
                                            "my": float(my),
                                            "group_labels": mp_sel_player_group_labels(),
                                            "craft_labels": mp_sel_craft_labels(),
                                        },
                                    )
                                    audio.play_positive()
                                    awaiting_attack_move_click = False
                                    awaiting_attack_target_click = False
                                else:
                                    mark = pick_hostile_at(
                                        groups, crafts, mx, my, cam_x, cam_y, **_mp_pick_hostile_kwargs()
                                    )
                                    atk_set = False
                                    if mark is not None:
                                        for gc in sel_caps:
                                            gc.attack_target = mark
                                        atk_set = True
                                    elif (
                                        mission.kind == "strike"
                                        and mission.objective
                                        and not mission.objective.dead
                                        and pick_strike_objective_at(
                                            mission.objective, mx, my, cam_x, cam_y
                                        )
                                    ):
                                        for gc in sel_caps:
                                            gc.attack_target = mission.objective
                                        atk_set = True
                                    if atk_set:
                                        awaiting_attack_move_click = False
                                        awaiting_attack_target_click = False
                                        tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                            audio,
                                            TTS_ATTACK_TARGET_VOICE_LINES,
                                            now_rmb,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    elif sel:
                                        if issue_move_orders(sel, wpx, wpy, formation_mode):
                                            tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                                audio,
                                                TTS_MOVE_VOICE_LINES,
                                                now_rmb,
                                                tts_last_order_quip_tts,
                                                TTS_ORDER_QUIP_GAP_MS,
                                            )
                                        awaiting_attack_move_click = False
                                        awaiting_attack_target_click = False
                            elif sel:
                                if mp_is_net_client():
                                    mp_send_client(
                                        "move_world",
                                        {
                                            "wpx": float(wpx),
                                            "wpy": float(wpy),
                                            "formation_mode": int(formation_mode),
                                            "attack_move": False,
                                            "group_labels": mp_sel_player_group_labels(),
                                            "craft_labels": mp_sel_craft_labels(),
                                        },
                                    )
                                    tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                        audio,
                                        TTS_MOVE_VOICE_LINES,
                                        now_rmb,
                                        tts_last_order_quip_tts,
                                        TTS_ORDER_QUIP_GAP_MS,
                                    )
                                elif issue_move_orders(sel, wpx, wpy, formation_mode):
                                    tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                        audio,
                                        TTS_MOVE_VOICE_LINES,
                                        now_rmb,
                                        tts_last_order_quip_tts,
                                        TTS_ORDER_QUIP_GAP_MS,
                                    )
                                awaiting_attack_move_click = False
                                awaiting_attack_target_click = False
                elif event.type == pygame.MOUSEBUTTONUP:
                    mx, my = to_internal(event.pos)
                    if event.button == 1 and drag_anchor is not None:
                        if my >= VIEW_H:
                            drag_anchor = None
                        else:
                            x0, y0 = drag_anchor
                            drag_anchor = None
                            drag = math.hypot(mx - x0, my - y0)
                            shift_down = pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[
                                pygame.K_RSHIFT
                            ]
                            mp_own_up = _mp_owned_pick_owner()
                            sel_caps = [
                                g
                                for g in groups
                                if g.side == "player"
                                and g.selected
                                and not g.dead
                                and g.render_capital
                                and (mp_own_up is None or getattr(g, "owner_id", "") == mp_own_up)
                            ]
                            mouse_done = False
                            now_ord = pygame.time.get_ticks()
                            if awaiting_attack_target_click:
                                if drag <= DRAG_CLICK_MAX_PX:
                                    if sel_caps:
                                        if mp_is_net_client():
                                            mp_send_client(
                                                "attack_target_pick",
                                                {
                                                    "cam_x": float(cam_x),
                                                    "cam_y": float(cam_y),
                                                    "mx": float(mx),
                                                    "my": float(my),
                                                    "group_labels": mp_sel_player_group_labels(),
                                                    "craft_labels": mp_sel_craft_labels(),
                                                },
                                            )
                                            tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                                audio,
                                                TTS_ATTACK_TARGET_VOICE_LINES,
                                                now_ord,
                                                tts_last_order_quip_tts,
                                                TTS_ORDER_QUIP_GAP_MS,
                                            )
                                            audio.play_positive()
                                            mouse_done = True
                                        else:
                                            mark = pick_hostile_at(
                                                groups,
                                                crafts,
                                                mx,
                                                my,
                                                cam_x,
                                                cam_y,
                                                **_mp_pick_hostile_kwargs(),
                                            )
                                            ok_set = False
                                            if mark is not None:
                                                for gc in sel_caps:
                                                    gc.attack_target = mark
                                                ok_set = True
                                            elif (
                                                mission.kind == "strike"
                                                and mission.objective
                                                and not mission.objective.dead
                                                and pick_strike_objective_at(
                                                    mission.objective, mx, my, cam_x, cam_y
                                                )
                                            ):
                                                for gc in sel_caps:
                                                    gc.attack_target = mission.objective
                                                ok_set = True
                                            if ok_set:
                                                tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                                    audio,
                                                    TTS_ATTACK_TARGET_VOICE_LINES,
                                                    now_ord,
                                                    tts_last_order_quip_tts,
                                                    TTS_ORDER_QUIP_GAP_MS,
                                                )
                                                audio.play_positive()
                                            else:
                                                audio.play_negative()
                                            mouse_done = True
                                    awaiting_attack_target_click = False
                                else:
                                    awaiting_attack_target_click = False

                            if awaiting_attack_move_click:
                                if drag <= DRAG_CLICK_MAX_PX:
                                    if sel_caps:
                                        wpx, wpy = screen_to_world_waypoint(float(mx), float(my), cam_x, cam_y)
                                        if mp_is_net_client():
                                            mp_send_client(
                                                "move_world",
                                                {
                                                    "wpx": float(wpx),
                                                    "wpy": float(wpy),
                                                    "formation_mode": int(formation_mode),
                                                    "attack_move": True,
                                                    "group_labels": mp_sel_player_group_labels(),
                                                    "craft_labels": mp_sel_craft_labels(),
                                                },
                                            )
                                            tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                                audio,
                                                TTS_ATTACK_MOVE_VOICE_LINES,
                                                now_ord,
                                                tts_last_order_quip_tts,
                                                TTS_ORDER_QUIP_GAP_MS,
                                            )
                                        elif issue_attack_move_orders(sel_caps, wpx, wpy, formation_mode):
                                            tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                                audio,
                                                TTS_ATTACK_MOVE_VOICE_LINES,
                                                now_ord,
                                                tts_last_order_quip_tts,
                                                TTS_ORDER_QUIP_GAP_MS,
                                            )
                                        mouse_done = True
                                    awaiting_attack_move_click = False
                                else:
                                    awaiting_attack_move_click = False

                            if (
                                not mouse_done
                                and awaiting_capital_context_lmb
                                and drag <= DRAG_CLICK_MAX_PX
                                and my < VIEW_H
                            ):
                                sel_ord = [
                                    g
                                    for g in groups
                                    if g.side == "player"
                                    and g.selected
                                    and not g.dead
                                    and (mp_own_up is None or getattr(g, "owner_id", "") == mp_own_up)
                                ]
                                sel_caps_ctx = [g for g in sel_ord if g.render_capital]
                                if not sel_caps_ctx:
                                    awaiting_capital_context_lmb = False
                                elif mp_is_net_client():
                                    mp_send_client(
                                        "capital_context_pick",
                                        {
                                            "cam_x": float(cam_x),
                                            "cam_y": float(cam_y),
                                            "mx": float(mx),
                                            "my": float(my),
                                            "group_labels": mp_sel_player_group_labels(),
                                            "craft_labels": mp_sel_craft_labels(),
                                        },
                                    )
                                    audio.play_positive()
                                    awaiting_capital_context_lmb = False
                                    awaiting_attack_move_click = False
                                    awaiting_attack_target_click = False
                                    mouse_done = True
                                else:
                                    wpx, wpy = screen_to_world_waypoint(
                                        float(mx), float(my), cam_x, cam_y
                                    )
                                    mark = pick_hostile_at(
                                        groups,
                                        crafts,
                                        mx,
                                        my,
                                        cam_x,
                                        cam_y,
                                        **_mp_pick_hostile_kwargs(),
                                    )
                                    atk_set = False
                                    if mark is not None:
                                        for gc in sel_caps_ctx:
                                            gc.attack_target = mark
                                        atk_set = True
                                    elif (
                                        mission.kind == "strike"
                                        and mission.objective
                                        and not mission.objective.dead
                                        and pick_strike_objective_at(
                                            mission.objective, mx, my, cam_x, cam_y
                                        )
                                    ):
                                        for gc in sel_caps_ctx:
                                            gc.attack_target = mission.objective
                                        atk_set = True
                                    if atk_set:
                                        awaiting_attack_move_click = False
                                        awaiting_attack_target_click = False
                                        tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                            audio,
                                            TTS_ATTACK_TARGET_VOICE_LINES,
                                            now_ord,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    elif issue_move_orders(
                                        sel_ord, wpx, wpy, formation_mode
                                    ):
                                        awaiting_attack_move_click = False
                                        awaiting_attack_target_click = False
                                        tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                            audio,
                                            TTS_MOVE_VOICE_LINES,
                                            now_ord,
                                            tts_last_order_quip_tts,
                                            TTS_ORDER_QUIP_GAP_MS,
                                        )
                                        audio.play_positive()
                                    else:
                                        audio.play_negative()
                                    awaiting_capital_context_lmb = False
                                    mouse_done = True

                            if (
                                not mouse_done
                                and awaiting_fighter_order_click
                                and drag <= DRAG_CLICK_MAX_PX
                                and my < VIEW_H
                            ):
                                sel_f = [
                                    g
                                    for g in groups
                                    if g.side == "player"
                                    and g.selected
                                    and not g.dead
                                    and (mp_own_up is None or getattr(g, "owner_id", "") == mp_own_up)
                                ]
                                wpx, wpy = screen_to_world_waypoint(
                                    float(mx), float(my), cam_x, cam_y
                                )
                                mark = pick_hostile_at(
                                    groups,
                                    crafts,
                                    mx,
                                    my,
                                    cam_x,
                                    cam_y,
                                    **_mp_pick_hostile_kwargs(),
                                )
                                if mp_is_net_client():
                                    mp_send_client(
                                        "fighter_strike_pick",
                                        {
                                            "cam_x": float(cam_x),
                                            "cam_y": float(cam_y),
                                            "mx": float(mx),
                                            "my": float(my),
                                            "group_labels": mp_sel_player_group_labels(),
                                            "craft_labels": mp_sel_craft_labels(),
                                        },
                                    )
                                    tts_last_order_quip_tts = tts_speak_if_cooled(
                                        audio,
                                        "fighters_acknowledge",
                                        now_ord,
                                        tts_last_order_quip_tts,
                                        TTS_ORDER_QUIP_GAP_MS,
                                    )
                                    audio.play_positive()
                                elif apply_fighter_strike_order(
                                    data, crafts, sel_f, wpx, wpy, mark
                                ):
                                    tts_last_order_quip_tts = tts_speak_if_cooled(
                                        audio,
                                        "fighters_acknowledge",
                                        now_ord,
                                        tts_last_order_quip_tts,
                                        TTS_ORDER_QUIP_GAP_MS,
                                    )
                                    audio.play_positive()
                                else:
                                    audio.play_negative()
                                awaiting_fighter_order_click = False
                                awaiting_bomber_order_click = False
                                mouse_done = True

                            if not mouse_done and shift_down and drag >= DRAG_LINE_MIN_PX and len(sel_caps) >= 1:
                                wx0, wy0 = screen_to_world_waypoint(float(x0), float(y0), cam_x, cam_y)
                                wx1, wy1 = screen_to_world_waypoint(float(mx), float(my), cam_x, cam_y)
                                if mp_is_net_client():
                                    mp_send_client(
                                        "line_move_world",
                                        {
                                            "wx0": float(wx0),
                                            "wy0": float(wy0),
                                            "wx1": float(wx1),
                                            "wy1": float(wy1),
                                            "formation_mode": int(formation_mode),
                                            "attack_move": False,
                                            "group_labels": mp_sel_player_group_labels(),
                                            "craft_labels": mp_sel_craft_labels(),
                                        },
                                    )
                                    tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                        audio,
                                        TTS_MOVE_VOICE_LINES,
                                        now_ord,
                                        tts_last_order_quip_tts,
                                        TTS_ORDER_QUIP_GAP_MS,
                                    )
                                elif issue_line_move_orders(sel_caps, wx0, wy0, wx1, wy1, formation_mode):
                                    tts_last_order_quip_tts = tts_speak_random_if_cooled(
                                        audio,
                                        TTS_MOVE_VOICE_LINES,
                                        now_ord,
                                        tts_last_order_quip_tts,
                                        TTS_ORDER_QUIP_GAP_MS,
                                    )
                                mouse_done = True

                            if not mouse_done and drag <= DRAG_CLICK_MAX_PX:
                                c_hit = pick_player_craft_at(
                                    crafts, mx, my, cam_x, cam_y, _mp_owned_pick_owner()
                                )
                                if c_hit:
                                    if not shift_down:
                                        clear_selection(groups)
                                        clear_craft_selection(crafts)
                                    for c in crafts:
                                        if (
                                            c.dead
                                            or c.parent is not c_hit.parent
                                            or c.squadron_index != c_hit.squadron_index
                                        ):
                                            continue
                                        c.selected = True
                                    last_cap_click_t = -100000
                                    last_cap_click_label = None
                                    mouse_done = True
                                if not mouse_done:
                                    hit = pick_player_capital_at(
                                        groups, mx, my, cam_x, cam_y, _mp_owned_pick_owner()
                                    )
                                    now = pygame.time.get_ticks()
                                    if hit:
                                        if (
                                            now - last_cap_click_t < DOUBLE_CLICK_MS
                                            and last_cap_click_label == hit.label
                                        ):
                                            clear_craft_selection(crafts)
                                            select_all_same_class_visible(
                                                groups, hit.class_name, cam_x, cam_y, _mp_owned_pick_owner()
                                            )
                                            last_cap_click_t = -100000
                                            last_cap_click_label = None
                                        elif shift_down:
                                            toggle_capital_in_selection(hit, _mp_owned_pick_owner())
                                            last_cap_click_t = -100000
                                            last_cap_click_label = None
                                        else:
                                            clear_craft_selection(crafts)
                                            set_selection(groups, [hit])
                                            last_cap_click_t = now
                                            last_cap_click_label = hit.label
                                    else:
                                        last_cap_click_t = -100000
                                        last_cap_click_label = None
                                        if not shift_down:
                                            clear_selection(groups)
                                            clear_craft_selection(crafts)
                            elif not mouse_done:
                                rect = normalize_rect(x0, y0, mx, my)
                                caps = player_capitals_in_rect(
                                    groups, rect, cam_x, cam_y, _mp_owned_pick_owner()
                                )
                                if caps:
                                    if shift_down:
                                        add_to_selection(groups, caps)
                                    else:
                                        clear_craft_selection(crafts)
                                        set_selection(groups, caps)
                                elif not shift_down:
                                    clear_selection(groups)
                                    clear_craft_selection(crafts)

        if phase == "combat" and not pause_menu_open:
            sel_caps_tts = [
                g
                for g in groups
                if g.side == "player" and g.selected and not g.dead and g.render_capital
            ]
            sig_tts = tuple(sorted(g.label for g in sel_caps_tts))
            if sig_tts != tts_prev_sel_sig:
                if len(sel_caps_tts) == 1:
                    g0 = sel_caps_tts[0]
                    now_sel = pygame.time.get_ticks()
                    hull_frac = g0.hp / g0.max_hp if g0.max_hp > 0 else 1.0
                    if hull_frac < TTS_LOW_HULL_FRAC:
                        prev_lh = tts_last_low_hull_by_label.get(g0.label, -10**9)
                        if now_sel - prev_lh >= TTS_LOW_HULL_SELECT_GAP_MS:
                            audio.speak_voice("hull_integrity_low")
                            tts_last_low_hull_by_label[g0.label] = now_sel
                    elif g0.class_name == "Carrier":
                        if now_sel - tts_last_carrier_quip_tts >= TTS_CARRIER_QUIP_GAP_MS:
                            audio.speak_voice("orders_query")
                            tts_last_carrier_quip_tts = now_sel
                tts_prev_sel_sig = sig_tts

        if phase == "combat" and not pause_menu_open:
            keys = pygame.key.get_pressed()
            sp = CAM_PAN_SPEED * dt
            if keys[pygame.K_w]:
                cam_y -= sp
            if keys[pygame.K_s]:
                cam_y += sp
            if keys[pygame.K_a]:
                cam_x -= sp
            if keys[pygame.K_d]:
                cam_x += sp
            cam_x, cam_y = clamp_camera(cam_x, cam_y)

        if phase == "combat" and not pause_menu_open:
            if not outcome and not test_menu_open:
                now_ms_frame = pygame.time.get_ticks()
                mp_fm_holder[0] = formation_mode

                if mp_receives_combat_snapshots():
                    _mp_apply_pending_snapshot(now_ms_frame)
                    now_death = now_ms_frame
                    tts_last_player_cap_loss_tts, tts_last_enemy_kill_tts = apply_combat_death_audio(
                        CombatAudioEvents(),
                        audio,
                        now_death,
                        tts_last_player_cap_loss_tts=tts_last_player_cap_loss_tts,
                        tts_last_enemy_kill_tts=tts_last_enemy_kill_tts,
                        tts_player_cap_loss_gap_ms=TTS_PLAYER_CAP_LOSS_GAP_MS,
                        tts_enemy_kill_gap_ms=TTS_ENEMY_KILL_GAP_MS,
                    )
                elif mp_net_combat_active() and mp_local_runs_authoritative_sim():
                    ping_holder = [ping_ready_at_ms]
                    for qcmd in mp_host_cmd_queue:
                        apply_combat_command(
                            data=data,
                            groups=groups,
                            crafts=crafts,
                            mission=mission,
                            formation_mode_holder=mp_fm_holder,
                            active_pings=active_pings,
                            sensor_ghosts=sensor_ghosts,
                            ping_ghost_anchor_labels=ping_ghost_anchor_labels,
                            mission_obstacles=mission.obstacles,
                            cg_weapons_free=cg_weapons_free,
                            control_groups=control_groups,
                            ping_ready_at_ms_holder=ping_holder,
                            now_ms=now_ms_frame,
                            audio=audio,
                            cmd={
                                "kind": str(qcmd.get("kind", "")),
                                "payload": dict(qcmd.get("payload") or {}),
                                "sender": str(qcmd.get("_sender") or ""),
                            },
                        )
                    mp_host_cmd_queue.clear()
                    formation_mode = mp_fm_holder[0]
                    ping_ready_at_ms = ping_holder[0]
                    res = step_combat_frame(
                        data=data,
                        dt=dt,
                        round_idx=round_idx,
                        mission=mission,
                        groups=groups,
                        crafts=crafts,
                        fog=fog,
                        active_pings=active_pings,
                        sensor_ghosts=sensor_ghosts,
                        ping_ghost_anchor_labels=ping_ghost_anchor_labels,
                        seeker_ghosts=seeker_ghosts,
                        control_groups=control_groups,
                        cg_weapons_free=cg_weapons_free,
                        missiles=missiles,
                        supplies=supplies,
                        vfx_sparks=vfx_sparks,
                        vfx_beams=vfx_beams,
                        ballistics=ballistics,
                        pd_rof_mult=pd_rof_mult,
                        hooks=CombatSimHooks(on_player_hull_hit=on_player_hull_hit),
                        phase=phase,
                        outcome=outcome,
                    )
                    now_death = now_ms_frame
                    tts_last_player_cap_loss_tts, tts_last_enemy_kill_tts = apply_combat_death_audio(
                        res.death_audio,
                        audio,
                        now_death,
                        tts_last_player_cap_loss_tts=tts_last_player_cap_loss_tts,
                        tts_last_enemy_kill_tts=tts_last_enemy_kill_tts,
                        tts_player_cap_loss_gap_ms=TTS_PLAYER_CAP_LOSS_GAP_MS,
                        tts_enemy_kill_gap_ms=TTS_ENEMY_KILL_GAP_MS,
                    )
                    if res.flow:
                        f = res.flow
                        outcome = f.outcome
                        phase = f.phase
                        if f.phase == "debrief":
                            run_total_score += f.run_total_score_add
                            salvage[0] += f.salvage_gain
                            last_salvage_gain = f.last_salvage_gain
                            store_selected = f.store_selected
                            store_hover = f.store_hover
                    if now_ms_frame - mp_last_snap_send_ms >= 50:
                        st = snapshot_state(
                            tick=mp_combat_tick,
                            round_idx=round_idx,
                            mission=mission,
                            groups=groups,
                            crafts=crafts,
                            missiles=missiles,
                            ballistics=ballistics,
                            vfx_sparks=vfx_sparks,
                            vfx_beams=vfx_beams,
                            supplies=supplies,
                            pd_rof_mult=pd_rof_mult,
                            cg_weapons_free=cg_weapons_free,
                            control_groups=control_groups,
                            fog=fog,
                            active_pings=active_pings,
                            sensor_ghosts=sensor_ghosts,
                            seeker_ghosts=seeker_ghosts,
                            ping_ghost_anchor_labels=ping_ghost_anchor_labels,
                            ping_ready_at_ms=ping_ready_at_ms,
                            outcome=outcome,
                            phase=phase,
                            salvage=float(salvage[0]),
                            run_total_score=run_total_score,
                            last_salvage_gain=last_salvage_gain,
                            store_selected=store_selected,
                            store_hover=store_hover,
                        )
                        h = hash_state_dict(st)
                        mp_host_snap_tick = mp_combat_tick
                        mp_relay.send_payload(
                            combat_snap(
                                tick=mp_combat_tick,
                                snap_version=SNAP_VERSION,
                                state_hash=h,
                                state=st,
                            )
                        )
                        mp_last_snap_send_ms = now_ms_frame
                    mp_combat_tick += 1
                else:
                    res = step_combat_frame(
                        data=data,
                        dt=dt,
                        round_idx=round_idx,
                        mission=mission,
                        groups=groups,
                        crafts=crafts,
                        fog=fog,
                        active_pings=active_pings,
                        sensor_ghosts=sensor_ghosts,
                        ping_ghost_anchor_labels=ping_ghost_anchor_labels,
                        seeker_ghosts=seeker_ghosts,
                        control_groups=control_groups,
                        cg_weapons_free=cg_weapons_free,
                        missiles=missiles,
                        supplies=supplies,
                        vfx_sparks=vfx_sparks,
                        vfx_beams=vfx_beams,
                        ballistics=ballistics,
                        pd_rof_mult=pd_rof_mult,
                        hooks=CombatSimHooks(on_player_hull_hit=on_player_hull_hit),
                        phase=phase,
                        outcome=outcome,
                    )
                    now_death = pygame.time.get_ticks()
                    tts_last_player_cap_loss_tts, tts_last_enemy_kill_tts = apply_combat_death_audio(
                        res.death_audio,
                        audio,
                        now_death,
                        tts_last_player_cap_loss_tts=tts_last_player_cap_loss_tts,
                        tts_last_enemy_kill_tts=tts_last_enemy_kill_tts,
                        tts_player_cap_loss_gap_ms=TTS_PLAYER_CAP_LOSS_GAP_MS,
                        tts_enemy_kill_gap_ms=TTS_ENEMY_KILL_GAP_MS,
                    )
                    if res.flow:
                        f = res.flow
                        outcome = f.outcome
                        phase = f.phase
                        if f.phase == "debrief":
                            run_total_score += f.run_total_score_add
                            salvage[0] += f.salvage_gain
                            last_salvage_gain = f.last_salvage_gain
                            store_selected = f.store_selected
                            store_hover = f.store_hover

        elif phase == "debrief" and not test_menu_open and not pause_menu_open:
            now_ms_frame = pygame.time.get_ticks()
            if mp_receives_combat_snapshots():
                _mp_apply_pending_snapshot(now_ms_frame)
                now_death = now_ms_frame
                tts_last_player_cap_loss_tts, tts_last_enemy_kill_tts = apply_combat_death_audio(
                    CombatAudioEvents(),
                    audio,
                    now_death,
                    tts_last_player_cap_loss_tts=tts_last_player_cap_loss_tts,
                    tts_last_enemy_kill_tts=tts_last_enemy_kill_tts,
                    tts_player_cap_loss_gap_ms=TTS_PLAYER_CAP_LOSS_GAP_MS,
                    tts_enemy_kill_gap_ms=TTS_ENEMY_KILL_GAP_MS,
                )
            elif mp_snapshot_broadcast_authority():
                if now_ms_frame - mp_last_snap_send_ms >= 50:
                    st = snapshot_state(
                        tick=mp_combat_tick,
                        round_idx=round_idx,
                        mission=mission,
                        groups=groups,
                        crafts=crafts,
                        missiles=missiles,
                        ballistics=ballistics,
                        vfx_sparks=vfx_sparks,
                        vfx_beams=vfx_beams,
                        supplies=supplies,
                        pd_rof_mult=pd_rof_mult,
                        cg_weapons_free=cg_weapons_free,
                        control_groups=control_groups,
                        fog=fog,
                        active_pings=active_pings,
                        sensor_ghosts=sensor_ghosts,
                        seeker_ghosts=seeker_ghosts,
                        ping_ghost_anchor_labels=ping_ghost_anchor_labels,
                        ping_ready_at_ms=ping_ready_at_ms,
                        outcome=outcome,
                        phase=phase,
                        salvage=float(salvage[0]),
                        run_total_score=run_total_score,
                        last_salvage_gain=last_salvage_gain,
                        store_selected=store_selected,
                        store_hover=store_hover,
                    )
                    h = hash_state_dict(st)
                    mp_host_snap_tick = mp_combat_tick
                    mp_relay.send_payload(
                        combat_snap(
                            tick=mp_combat_tick,
                            snap_version=SNAP_VERSION,
                            state_hash=h,
                            state=st,
                        )
                    )
                    mp_last_snap_send_ms = now_ms_frame
                mp_combat_tick += 1

        if phase == "config":
            screen.fill((4, 12, 18))
            draw_starfield(screen, stars, cam_x, cam_y, WIDTH, HEIGHT)
            draw_world_edge(screen, cam_x, cam_y)
            draw_config_menu(screen, font, font_tiny, font_big, audio)
            ch = font.render("Audio — ENTER or Design fleet · Multiplayer opens LAN-flow stub", True, (190, 210, 220))
            screen.blit(ch, (12, HEIGHT - 26))
            _blit_internal_to_window(window, screen, win_w, win_h)
            continue

        if phase == "battlegroup_editor":
            screen.fill((4, 12, 18))
            draw_starfield(screen, stars, cam_x, cam_y, WIDTH, HEIGHT)
            draw_world_edge(screen, cam_x, cam_y)
            _et = BATTLEGROUP_ENTRY_TAGS[
                max(0, min(bg_editor_entry_i, len(BATTLEGROUP_ENTRY_TAGS) - 1))
            ]
            draw_battlegroup_editor(
                screen,
                font,
                font_tiny,
                font_big,
                presets=bg_editor_presets,
                selected_i=bg_editor_selected_i,
                list_scroll=bg_editor_list_scroll,
                row_scroll=bg_editor_row_scroll,
                name_buf=bg_editor_name_buf,
                id_buf=bg_editor_id_buf,
                cost_buf=bg_editor_cost_buf,
                entry_tag=_et,
                rows=bg_editor_rows,
                ship_pick_i=bg_editor_ship_pick_i,
                cap_names=cap_names_menu,
                save_path=bg_editor_path,
                focus=bg_editor_focus,
            )
            bh = font_tiny.render("ESC — save & back   Tab — cycle fields", True, (150, 170, 190))
            screen.blit(bh, (12, HEIGHT - 26))
            _blit_internal_to_window(window, screen, win_w, win_h)
            continue

        if phase == "mp_hub":
            screen.fill((4, 12, 18))
            draw_starfield(screen, stars, cam_x, cam_y, WIDTH, HEIGHT)
            draw_world_edge(screen, cam_x, cam_y)
            _auth_cfg = bool(fleet_http_base and NET_MP)
            if not _mp_hub_can_use_http():
                if not NET_MP or list_lobbies is None:
                    _hp1, _hp2 = "Online multiplayer isn't available in this build.", None
                elif _hub_http_disabled:
                    _hp1, _hp2 = "Online lobby features are turned off.", None
                else:
                    _hp1, _hp2 = "No lobby server is configured for online play.", None
                _hsm = "bad"
            elif mp_hub_svc_state == "online":
                _hp1, _hp2 = "Connected to the lobby server.", None
                _hsm = "ok"
            elif mp_hub_list_busy or mp_hub_svc_state == "checking":
                _hp1, _hp2 = "Checking connection…", None
                _hsm = "wait"
            elif mp_hub_svc_state == "offline":
                _hp1 = "Not connected to the lobby server."
                _hp2 = mp_hub_user_message
                _hsm = "bad"
            else:
                _hp1, _hp2 = "Checking connection…", None
                _hsm = "wait"
            draw_mp_hub(
                screen,
                font,
                font_tiny,
                font_big,
                http_base=fleet_http_base,
                name_buffer=mp_name_buffer,
                name_focus=mp_name_focus,
                join_buffer=mp_join_id_buffer,
                join_focus=mp_join_focus,
                lobby_browser_rows=mp_hub_lobby_rows,
                lobby_browser_scroll=mp_hub_lobby_scroll,
                next_online_authority=mp_http_authority_choice,
                status_primary=_hp1,
                status_detail=_hp2,
                status_mode=_hsm,
                online_actions_ok=mp_hub_online_actions_ok,
                authority_config_ok=_auth_cfg,
                list_busy=mp_hub_list_busy,
            )
            now_t = pygame.time.get_ticks()
            if now_t < mp_toast_until_ms:
                tb = font_tiny.render(mp_toast_text, True, (255, 215, 140))
                screen.blit(tb, (WIDTH // 2 - tb.get_width() // 2, HEIGHT - 36))
            _blit_internal_to_window(window, screen, win_w, win_h)
            continue

        if phase == "mp_lobby":
            screen.fill((4, 12, 18))
            draw_starfield(screen, stars, cam_x, cam_y, WIDTH, HEIGHT)
            draw_world_edge(screen, cam_x, cam_y)
            now_ms = pygame.time.get_ticks()
            handle_mp_relay_events()
            if remote_lobby_id and fleet_http_base and get_lobby and now_ms - mp_last_lobby_poll_ms > 2500:
                mp_last_lobby_poll_ms = now_ms
                try:
                    _lob = get_lobby(fleet_http_base, remote_lobby_id)
                    remote_lobby_http_players = list(_lob.get("players") or [])
                except FleetHttpError:
                    pass
            toast = mp_toast_text if now_ms < mp_toast_until_ms else None
            if remote_lobby_id:
                online_title = "Lobby — online (HTTP + TCP relay)"
                online_lines = [
                    f"Share code: {remote_lobby_short or remote_lobby_id[:8]}",
                    "Relay: ready · host_config · presence [fleet] · start_match (shared seed)",
                ]
                if remote_lobby_http_players:
                    online_lines.append("Players (HTTP):")
                    for p in remote_lobby_http_players[:12]:
                        rdy = mp_ready if p == mp_player_name else remote_ready.get(p, False)
                        fd = remote_loadouts.get(p, False)
                        online_lines.append(
                            f"  · {p}{'  ✓ ready' if rdy else ''}{'  [fleet]' if fd else ''}"
                        )
                if remote_relay_players:
                    online_lines.append("Relay TCP: " + ", ".join(remote_relay_players[:10]))
                if mp_lobby_authoritative == "dedicated":
                    online_lines.append(
                        "Combat authority: dedicated — pygame peers apply snapshots only; run headless_combat_host.py on the droplet with this lobby id."
                    )
                    online_lines.append(
                        "Start battle: first HTTP player still sends start_match (same as player-host mode)."
                    )
                else:
                    online_lines.append(
                        "Combat authority: player host — first HTTP player steps the sim and sends combat_snap."
                    )
                if mp_net_err:
                    online_lines.append("Note: " + str(mp_net_err)[:72])
                relay_status = (
                    "Relay: connected"
                    if mp_relay is not None and not mp_relay.error
                    else ("Relay: error — check tcp_relay.py" if mp_relay is not None else "Relay: off")
                )
            else:
                online_title = "Lobby — custom game (local stub)"
                online_lines = None
                relay_status = None
            chat_on = bool(remote_lobby_id and mp_relay is not None and not mp_relay.error)
            draw_mp_lobby(
                screen,
                font,
                font_tiny,
                font_big,
                coop=mp_mode_coop,
                use_asteroids=mp_use_asteroids,
                enemy_pressure_i=mp_enemy_pressure,
                player_color_id=mp_player_color_id,
                host=mp_lobby_host,
                ready=mp_ready,
                mp_round=mp_round_idx,
                fleet_capital_n=len(loadout_player_capitals_sorted(mp_fleet_groups)),
                toast_text=toast,
                online_title=online_title,
                online_lines=online_lines,
                relay_status=relay_status,
                chat_enabled=chat_on,
                chat_log=mp_chat_log,
                chat_input=mp_chat_input,
                chat_focus=mp_chat_focus,
            )
            _blit_internal_to_window(window, screen, win_w, win_h)
            continue

        if phase == "ship_loadouts":
            screen.fill((4, 12, 18))
            draw_starfield(screen, stars, cam_x, cam_y, WIDTH, HEIGHT)
            draw_world_edge(screen, cam_x, cam_y)
            draw_ship_loadouts_menu(
                screen,
                font,
                font_tiny,
                font_micro,
                font_big,
                data,
                loadout_preview_groups,
                loadout_preview_crafts,
                loadout_selected_i,
                loadout_roster_scroll,
                deployment_scrap,
                loadout_choice_map,
                to_internal(pygame.mouse.get_pos()),
                **(
                    {
                        "title": "Ship loadouts — multiplayer fleet",
                        "subtitle": "Same tools as single-player · confirm saves to the lobby fleet (local stub).",
                        "launch_btn_label": "Save & return to lobby",
                        "footer_bar": "ESC / Back — lobby   ENTER / Save — lobby   Wheel — roster · Hover — details",
                    }
                    if mp_loadouts_active
                    else {}
                ),
            )
            loadout_roster_scroll = clamp_loadout_roster_scroll(
                loadout_preview_groups, loadout_roster_scroll
            )
            roster_n = len(loadout_player_capitals_sorted(loadout_preview_groups))
            if roster_n <= 0:
                loadout_selected_i = 0
            else:
                loadout_selected_i = max(0, min(loadout_selected_i, roster_n - 1))
            if mp_loadouts_active and remote_lobby_id and mp_relay is not None:
                handle_mp_relay_events()
            _blit_internal_to_window(window, screen, win_w, win_h)
            continue

        if phase == "combat":
            screen.fill((14, 22, 34), (0, VIEW_H, WIDTH, BOTTOM_BAR_H))
            screen.fill((4, 12, 18), (0, 0, VIEW_W, VIEW_H))
            screen.set_clip(pygame.Rect(0, 0, VIEW_W, VIEW_H))
        else:
            screen.fill((4, 12, 18))

        draw_starfield(
            screen,
            stars,
            cam_x,
            cam_y,
            VIEW_W if phase == "combat" else WIDTH,
            VIEW_H if phase == "combat" else HEIGHT,
        )
        draw_world_edge(screen, cam_x, cam_y)

        if phase == "combat":
            draw_asteroids(screen, mission.obstacles, cam_x, cam_y, fog)
            draw_extract_zone(screen, font, cam_x, cam_y)

        if phase == "combat":
            for g in groups:
                if g.dead or g.class_name != "Carrier":
                    continue
                if g.strike_rally is not None:
                    rx, ry = g.strike_rally
                    rsx, rsy, _ = world_to_screen(rx, ry, g.z, cam_x, cam_y)
                    pygame.draw.circle(screen, (65, 130, 160), (int(rsx), int(rsy)), 48, width=2)
                    pygame.draw.circle(screen, (150, 230, 255), (int(rsx), int(rsy)), 6)
                for wi, wpt in enumerate(g.strike_rally_wings):
                    if wpt is None:
                        continue
                    rx, ry = wpt
                    rsx, rsy, _ = world_to_screen(rx, ry, g.z, cam_x, cam_y)
                    ac = (70, 150, 200) if wi == 0 else (200, 140, 90)
                    bc = (140, 220, 255) if wi == 0 else (255, 210, 150)
                    pygame.draw.circle(screen, ac, (int(rsx), int(rsy)), 40, width=2)
                    pygame.draw.circle(screen, bc, (int(rsx), int(rsy)), 5)

        if phase == "combat":
            if mission.objective and not mission.objective.dead:
                obj_vis = mission.kind == "strike" or fog_cell_visible(
                    fog, mission.objective.x, mission.objective.y
                )
                if obj_vis:
                    o = mission.objective
                    sx, sy, sc = world_to_screen(o.x, o.y, o.z, cam_x, cam_y)
                    rr = max(14, int(o.radius * (0.82 + 0.18 * min(1.2, sc))))
                    pygame.draw.circle(screen, (210, 65, 50), (int(sx), int(sy)), rr, width=3)
                    bar_w = rr * 2
                    frac = max(0.0, min(1.0, o.hp / o.max_hp if o.max_hp > 0 else 0))
                    by = int(sy - rr - 10)
                    pygame.draw.line(screen, (35, 40, 48), (int(sx - bar_w // 2), by), (int(sx + bar_w // 2), by), 4)
                    pygame.draw.line(
                        screen,
                        (255, 130, 80),
                        (int(sx - bar_w // 2), by),
                        (int(sx - bar_w // 2 + int(bar_w * frac)), by),
                        4,
                    )
            for pod in mission.pods:
                if pod.collected:
                    continue
                if not fog_cell_visible(fog, pod.x, pod.y):
                    continue
                sx, sy, _ = world_to_screen(pod.x, pod.y, 20.0, cam_x, cam_y)
                pygame.draw.circle(screen, (230, 195, 70), (int(sx), int(sy)), 17, width=2)
                pygame.draw.circle(screen, (255, 245, 200), (int(sx), int(sy)), 5)

        draw_vfx_beams(screen, vfx_beams, cam_x, cam_y)
        for m in sorted(missiles, key=lambda mm: mm.z):
            draw_missile(screen, m, cam_x, cam_y, font_micro)
        for s in sorted(ballistics, key=lambda b: b.z):
            draw_ballistic_slug(screen, s, cam_x, cam_y)
        draw_vfx_sparks(screen, vfx_sparks, cam_x, cam_y)

        drawables: List[Tuple[float, str, Any]] = []
        for g in groups:
            if not g.dead:
                drawables.append((g.z, "g", g))
        for c in crafts:
            if not c.dead:
                drawables.append((c.z, "c", c))
        drawables.sort(key=lambda t: t[0])
        for _, kind, ent in drawables:
            if kind == "g":
                g = ent
                if phase == "combat" and g.side == "enemy" and not fog_cell_visible(fog, g.x, g.y):
                    continue
                sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
                col = (
                    player_unit_color(g.color_id, coop_mode=mp_mode_coop, for_craft=False)
                    if not str(g.side).startswith("enemy")
                    else (255, 85, 85)
                )
                if g.selected:
                    col = (255, 240, 120)
                h = heading_for_group(g)
                cap_scale = capital_marker_scale(g.class_name)
                draw_nato_ship(screen, sx, sy, col, h, scale=cap_scale * sc)
                if g.side == "player" and g.attack_move and g.render_capital:
                    rr = int(22 * sc * cap_scale)
                    pygame.draw.circle(screen, (255, 160, 70), (int(sx), int(sy)), rr, width=1)
                draw_entity_plate(
                    screen,
                    font,
                    font_tiny,
                    sx,
                    sy - (12 + 9 * cap_scale) * sc,
                    g.label,
                    g.class_name,
                    g.hp,
                    g.max_hp,
                    g.weapons,
                    compact=False,
                )
                if phase == "combat":
                    pr = compute_pd_stress_ratio(data, g, missiles, pd_rof_mult[0])
                    if pr is not None:
                        draw_pd_stress_badge(screen, font_micro, sx, sy, sc, pr)
            else:
                c = ent
                if phase == "combat" and c.side == "enemy" and not fog_cell_visible(fog, c.x, c.y):
                    continue
                sx, sy, sc = world_to_screen(c.x, c.y, c.z, cam_x, cam_y)
                col = (
                    player_unit_color(c.color_id, coop_mode=mp_mode_coop, for_craft=True)
                    if not str(c.side).startswith("enemy")
                    else (255, 130, 130)
                )
                draw_craft_triangle(screen, sx, sy, col, c.heading, size=6.5 * sc)
                draw_strike_craft_tag(screen, font_micro, sx, sy, c.class_name, c.hp, c.max_hp)
                if c.selected and c.side == "player":
                    pygame.draw.circle(screen, (255, 240, 140), (int(sx), int(sy)), int(10 * sc), width=2)
                if phase == "combat":
                    pr = compute_pd_stress_ratio(data, c, missiles, pd_rof_mult[0])
                    if pr is not None:
                        draw_pd_stress_badge(screen, font_micro, sx, sy, sc, pr)

        if phase == "combat":
            draw_fog_overlay(screen, fog, cam_x, cam_y)
            draw_sensor_ghosts(screen, font_micro, sensor_ghosts, cam_x, cam_y)
            draw_sensor_ghosts(screen, font_micro, seeker_ghosts, cam_x, cam_y)
            draw_attack_focus_rings(screen, groups, cam_x, cam_y, fog)
            screen.set_clip(None)

        sel_player = [g for g in groups if g.side == "player" and g.selected and not g.dead]
        if len(sel_player) == 1 and sel_player[0].class_name == "Carrier":
            cg = sel_player[0]
            panel = pygame.Surface((340, 102), pygame.SRCALPHA)
            pygame.draw.rect(panel, (12, 24, 36, 228), (0, 0, 340, 102), border_radius=8)
            pygame.draw.rect(panel, (55, 110, 95, 210), (0, 0, 340, 102), width=1, border_radius=8)
            screen.blit(panel, (WIDTH - 354, 14))
            t0 = font_tiny.render("Carrier air wing", True, (160, 230, 200))
            t1 = font_tiny.render("[F]: LMB fighters / RMB bombers — [7]/[8] optional wing select", True, (200, 215, 225))
            t2 = font_tiny.render("[C]: recall — escort carrier again", True, (200, 215, 225))
            screen.blit(t0, (WIDTH - 342, 22))
            screen.blit(t1, (WIDTH - 342, 40))
            screen.blit(t2, (WIDTH - 342, 56))
            if cg.strike_rally:
                t3 = font_micro.render(
                    f"Rally {int(cg.strike_rally[0])}, {int(cg.strike_rally[1])}",
                    True,
                    (140, 200, 255),
                )
                screen.blit(t3, (WIDTH - 342, 72))

        if awaiting_fighter_order_click and awaiting_bomber_order_click:
            bh = font_tiny.render(
                "→ LMB: fighters — RMB: bombers — enemy/strike relay = attack; empty map = rally",
                True,
                (255, 220, 130),
            )
            screen.blit(bh, (WIDTH // 2 - bh.get_width() // 2, min(100, VIEW_H // 4)))
        elif awaiting_fighter_order_click:
            bh = font_tiny.render(
                "→ RMB or LMB: fighters — enemy/strike relay = attack; empty map = rally (RTS right-click OK)",
                True,
                (255, 220, 130),
            )
            screen.blit(bh, (WIDTH // 2 - bh.get_width() // 2, min(100, VIEW_H // 4)))
        elif awaiting_capital_context_lmb:
            bh = font_tiny.render(
                "→ LMB: fleet — enemy/strike relay = focus fire; empty map = move (like RMB)",
                True,
                (255, 220, 130),
            )
            screen.blit(bh, (WIDTH // 2 - bh.get_width() // 2, min(100, VIEW_H // 4)))
        elif awaiting_bomber_order_click:
            bh = font_tiny.render(
                "→ RMB: bombers — click enemy/strike relay to attack, or empty map to rally (carrier = all bomber squadrons)",
                True,
                (255, 220, 130),
            )
            screen.blit(bh, (WIDTH // 2 - bh.get_width() // 2, min(100, VIEW_H // 4)))
        elif awaiting_attack_target_click:
            bh = font_tiny.render(
                "→ Left-click enemy — or strike relay (strike) — focus fire (or right-click enemy with selection)",
                True,
                (255, 95, 88),
            )
            screen.blit(bh, (WIDTH // 2 - bh.get_width() // 2, min(100, VIEW_H // 4)))
        elif awaiting_attack_move_click:
            bh = font_tiny.render("→ Left-click destination — attack-move (move + engage along the way)", True, (255, 170, 95))
            screen.blit(bh, (WIDTH // 2 - bh.get_width() // 2, min(100, VIEW_H // 4)))

        if drag_anchor is not None and pygame.mouse.get_pressed()[0]:
            imx, imy = to_internal(pygame.mouse.get_pos())
            if phase == "combat" and imy < VIEW_H and (
                pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[pygame.K_RSHIFT]
            ):
                pygame.draw.line(screen, (150, 230, 255), drag_anchor, (imx, imy), 2)
            elif phase == "combat" and imy < VIEW_H:
                sel_rect = normalize_rect(drag_anchor[0], drag_anchor[1], imx, imy)
                pygame.draw.rect(screen, (100, 220, 255), sel_rect, width=1)
            elif phase != "combat":
                if pygame.key.get_pressed()[pygame.K_LSHIFT] or pygame.key.get_pressed()[pygame.K_RSHIFT]:
                    pygame.draw.line(screen, (150, 230, 255), drag_anchor, (imx, imy), 2)
                else:
                    sel_rect = normalize_rect(drag_anchor[0], drag_anchor[1], imx, imy)
                    pygame.draw.rect(screen, (100, 220, 255), sel_rect, width=1)

        if phase == "combat":
            pygame.draw.line(screen, (55, 85, 110), (0, VIEW_H), (WIDTH, VIEW_H), 2)

            now_hint = pygame.time.get_ticks()
            if now_hint < order_hint_until and order_hint_msg:
                ht = font_tiny.render(order_hint_msg, True, (255, 230, 160))
                screen.blit(ht, (12, max(8, VIEW_H - 24)))

            mxh, myh = to_internal(pygame.mouse.get_pos())
            order_hover_act: Optional[str] = None
            stance_hover = False
            if myh >= VIEW_H:
                if weapon_stance_toggle_rect().collidepoint(mxh, myh):
                    stance_hover = True
                else:
                    for rect, act, _ in order_command_cells():
                        if rect.collidepoint(mxh, myh):
                            order_hover_act = act
                            break

            otitle = font_micro.render("Orders (click)", True, (165, 185, 205))
            screen.blit(otitle, (order_panel_screen_rect().x + 6, VIEW_H + 4))

            for rect, act, lab in order_command_cells():
                on = order_hover_act == act
                bg = (44, 62, 86) if on else (30, 42, 58)
                bd = (130, 175, 215) if on else (68, 90, 118)
                pygame.draw.rect(screen, bg, rect, border_radius=5)
                pygame.draw.rect(screen, bd, rect, width=1, border_radius=5)
                ts = font_micro.render(lab, True, (225, 232, 245))
                screen.blit(ts, (rect.centerx - ts.get_width() // 2, rect.centery - ts.get_height() // 2))

            st_rect = weapon_stance_toggle_rect()
            slang, scol = weapon_stance_display_for_selection(groups, control_groups, cg_weapons_free)
            sbg = (52, 74, 102) if stance_hover else (36, 50, 70)
            if slang.startswith("Group weapons: FREE"):
                sbd = (95, 200, 125) if stance_hover else (72, 150, 98)
            elif slang.startswith("Group weapons: HOLD"):
                sbd = (220, 120, 95) if stance_hover else (175, 95, 75)
            else:
                sbd = (120, 165, 205) if stance_hover else (85, 115, 148)
            pygame.draw.rect(screen, sbg, st_rect, border_radius=5)
            pygame.draw.rect(screen, sbd, st_rect, width=1, border_radius=5)
            ts_st = font_micro.render(slang, True, scol)
            screen.blit(
                ts_st,
                (st_rect.centerx - ts_st.get_width() // 2, st_rect.centery - ts_st.get_height() // 2),
            )

            for i in range(CONTROL_GROUP_SLOTS):
                srect = control_group_slot_rect(i)
                pygame.draw.rect(screen, (26, 38, 54), srect, border_radius=4)
                pygame.draw.rect(screen, (72, 98, 126), srect, width=1, border_radius=4)
                num = font_micro.render(str(i + 1), True, (200, 210, 225))
                screen.blit(num, (srect.x + 4, srect.y + 2))
                labs = control_groups[i]
                if labs:
                    short = (labs[0] if len(labs) == 1 else f"{labs[0]}+{len(labs) - 1}")[:10]
                    t = font_micro.render(short, True, (155, 180, 205))
                    screen.blit(t, (srect.x + 4, srect.y + 16))

            status_x = control_group_slot_rect(CONTROL_GROUP_SLOTS - 1).right + 14
            st1 = font_tiny.render(
                f"Round {round_idx}  |  {FORMATION_MODE_NAMES[formation_mode]}  |  Salvage {salvage[0]}  |  Supplies {supplies[0]:.0f}",
                True,
                (175, 195, 215),
            )
            screen.blit(st1, (status_x, VIEW_H + 14))
            if mission.kind == "strike":
                if mission.objective and not mission.objective.dead:
                    gshort = f"STRIKE — relay {mission.objective.hp:.0f}/{mission.objective.max_hp:.0f}"
                else:
                    gshort = "STRIKE — destroy relay"
            elif mission.kind == "pvp":
                gshort = "PVP — eliminate enemy fleets"
            else:
                gshort = f"SALVAGE — pods {mission.pods_collected}/{len(mission.pods)} (need {mission.pods_required})"
            st2 = font_micro.render(gshort, True, (145, 165, 188))
            screen.blit(st2, (status_x, VIEW_H + 36))
            if mp_sync_match_active():
                if mp_lobby_authoritative == "dedicated":
                    tick_shown = mp_client_last_snap_tick
                    tick_disp = str(tick_shown) if tick_shown >= 0 else "—"
                    mp_line = f"MP dedicated sim  last_snap_tick={tick_disp}"
                else:
                    tick_shown = mp_host_snap_tick if mp_lobby_host else mp_client_last_snap_tick
                    tick_disp = str(tick_shown) if tick_shown >= 0 else "—"
                    mp_line = f"MP {'HOST' if mp_lobby_host else 'CLIENT'}  last_snap_tick={tick_disp}"
                st_mp = font_micro.render(mp_line, True, (120, 200, 160))
                screen.blit(st_mp, (status_x, VIEW_H + 52))
            now_ds = pygame.time.get_ticks()
            if now_ds < mp_desync_until_ms and mp_desync_text:
                banner = font.render(mp_desync_text, True, (255, 70, 70))
                screen.blit(banner, (WIDTH // 2 - banner.get_width() // 2, 10))

        if phase == "combat" and pause_menu_open:
            menu_ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            menu_ov.fill((12, 18, 32, 230))
            screen.blit(menu_ov, (0, 0))
            title = font_big.render("PAUSED", True, (230, 238, 250))
            screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 28))
            sub = font.render("ESC — resume", True, (170, 190, 210))
            screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 54))
            sec = font.render("CONTROLS & HELP", True, (140, 200, 230))
            screen.blit(sec, (WIDTH // 2 - sec.get_width() // 2, 78))
            help_lines = pause_combat_help_lines(formation_mode)
            col_x = 36
            cy = 100
            split_y = HEIGHT - 108
            second_col_x = WIDTH // 2 + 12
            using_second_col = False
            for hl in help_lines:
                if not using_second_col and cy > split_y:
                    using_second_col = True
                    col_x = second_col_x
                    cy = 100
                col = (210, 220, 235) if hl and not hl.startswith(" ") else (175, 190, 208)
                if hl.strip() and hl == hl.upper() and not hl.startswith(" "):
                    col = (120, 200, 225)
                ts = font_micro.render(hl, True, col)
                screen.blit(ts, (col_x, cy))
                cy += 14
            btn_r = pause_main_menu_button_rect()
            btn_bg = (52, 72, 98) if pause_main_menu_hover else (36, 52, 72)
            btn_bd = (130, 175, 220) if pause_main_menu_hover else (80, 110, 145)
            pygame.draw.rect(screen, btn_bg, btn_r, border_radius=8)
            pygame.draw.rect(screen, btn_bd, btn_r, width=2, border_radius=8)
            bt = font.render("Back to main menu", True, (235, 240, 248))
            screen.blit(bt, (btn_r.centerx - bt.get_width() // 2, btn_r.centery - bt.get_height() // 2))
            hint = font_tiny.render("(exits game for now)", True, (140, 155, 175))
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 28))

        if phase == "combat" and test_menu_open:
            menu_ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            menu_ov.fill((10, 16, 28, 210))
            screen.blit(menu_ov, (0, 0))
            test_lines = [
                "TEST MENU",
                "F1 — close",
                "",
                "[1] Open store",
                "    (SPACE returns here; round unchanged)",
                f"[2] +{TEST_SALVAGE_GRANT} salvage",
            ]
            my = HEIGHT // 2 - 100
            for tl in test_lines:
                fnt = font_big if tl.startswith("[") else (font if tl else font_tiny)
                if not tl:
                    my += 8
                    continue
                ts = fnt.render(tl, True, (230, 238, 250))
                screen.blit(ts, (WIDTH // 2 - ts.get_width() // 2, my))
                my += 30 if fnt is font_big else 20

        selected_caps = [g for g in groups if g.side == "player" and g.selected and not g.dead]

        if phase == "debrief":
            ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            ov.fill((6, 14, 24, 215))
            screen.blit(ov, (0, 0))
            if post_combat_phase == "mp_lobby" and bool(getattr(mission, "mp_pvp", False)):
                lines_mp = [
                    "PvP match ended",
                    outcome or "",
                    "",
                    "SPACE — return to lobby for another match",
                ]
                y0 = HEIGHT // 2 - 120
                for i, line in enumerate(lines_mp):
                    if not line:
                        y0 += 16
                        continue
                    fnt = font_big if i == 0 else font
                    col = (230, 240, 250) if i == 0 else ((200, 220, 245) if i == 1 else (150, 175, 198))
                    ts = fnt.render(line, True, col)
                    screen.blit(ts, (WIDTH // 2 - ts.get_width() // 2, y0))
                    y0 += 44 if fnt is font_big else 32
            else:
                cap_n = player_capital_count(groups)
                info_for = store_selected or store_hover
                info_lines = debrief_info_lines(
                    info_for,
                    data,
                    groups,
                    crafts,
                    salvage,
                    supplies,
                    pd_rof_mult,
                    ciws_stacks,
                    bulk_stacks,
                    cap_n,
                )
                draw_debrief_store(
                    screen,
                    font,
                    font_tiny,
                    font_micro,
                    font_big,
                    round_idx,
                    run_total_score,
                    salvage,
                    last_salvage_gain,
                    store_selected,
                    store_hover,
                    cap_n,
                    info_lines,
                )
        elif phase == "gameover":
            ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            ov.fill((18, 6, 10, 220))
            screen.blit(ov, (0, 0))
            for i, line in enumerate(
                [
                    outcome or "Game over",
                    f"Total score: {run_total_score}   Salvage had: {salvage[0]}",
                    "[R] new campaign   Ctrl+Q — quit",
                ]
            ):
                surf = font_big.render(line, True, (255, 200, 200)) if i == 0 else font.render(line, True, (220, 190, 190))
                screen.blit(surf, (WIDTH // 2 - surf.get_width() // 2, 280 + i * 36))

        hud_lines: List[str] = []
        if phase == "combat":
            hud_lines = []
            if selected_caps:
                if len(selected_caps) == 1:
                    g0 = selected_caps[0]
                    hud_lines.append(f"Selected {g0.label} ({g0.class_name})  HP {g0.hp:.0f}/{g0.max_hp:.0f}")
                else:
                    names = ", ".join(g.label for g in selected_caps)
                    hud_lines.append(f"Selected ({len(selected_caps)}): {names}")
            if test_menu_open:
                hud_lines.append("F1 — close test menu")
            if not hud_lines:
                hud_lines = ["ESC — pause for controls & help"]
        elif phase == "debrief":
            hud_lines = [outcome or ""]
            if post_combat_phase == "mp_lobby" and bool(getattr(mission, "mp_pvp", False)):
                hud_lines.append("SPACE — return to multiplayer lobby")
            else:
                if test_debrief_resume:
                    hud_lines.append("TEST: SPACE — back to battle (same round, enemies kept)")
                hud_lines.append(
                    "Click row to select · ENTER / purchase bar to buy · 1–5 ships · 6–0 upgrades · SPACE next"
                )
        elif phase == "gameover":
            hud_lines = ["See center panel — [R] restart campaign"]

        if phase == "combat":
            y0 = max(8, VIEW_H - 20 * len(hud_lines) - 10)
        else:
            y0 = HEIGHT - 20 * len(hud_lines) - 8
        for i, line in enumerate(hud_lines):
            if not line:
                continue
            surf = font.render(line, True, (190, 210, 220))
            screen.blit(surf, (12, y0 + i * 20))

        _blit_internal_to_window(window, screen, win_w, win_h)

    audio.shutdown()
    pygame.quit()


def main() -> None:
    try:
        run()
    except FileNotFoundError:
        print(f"Missing {DATA_PATH}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
