"""
Centralized game state for FleetRTS.

Every runtime variable that was previously a local inside demo_game.run()
now lives here as an attribute on one of the nested sub-state dataclasses.
"""
from __future__ import annotations

import queue
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from fleet_deployment import DEPLOYMENT_STARTING_SCRAP
    from demo_game import (
        CONTROL_GROUP_SLOTS, FORMATION_MODE_RING,
        ActivePing, Asteroid, BallisticSlug, Craft, FogState, Group,
        Missile, MissionState, SensorGhost, VFXBeam, VFXSpark,
    )
    from pvp_battlegroups import BattlegroupPreset
except ImportError:
    from core.fleet_deployment import DEPLOYMENT_STARTING_SCRAP
    from core.demo_game import (
        CONTROL_GROUP_SLOTS, FORMATION_MODE_RING,
        ActivePing, Asteroid, BallisticSlug, Craft, FogState, Group,
        Missile, MissionState, SensorGhost, VFXBeam, VFXSpark,
    )
    from core.pvp_battlegroups import BattlegroupPreset

import pygame


# ---------------------------------------------------------------------------
# Sub-state dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CombatState:
    groups: List[Group] = field(default_factory=list)
    crafts: List[Craft] = field(default_factory=list)
    mission: Optional[MissionState] = None
    missiles: List[Missile] = field(default_factory=list)
    ballistics: List[BallisticSlug] = field(default_factory=list)
    vfx_sparks: List[VFXSpark] = field(default_factory=list)
    vfx_beams: List[VFXBeam] = field(default_factory=list)
    supplies: List[float] = field(default_factory=lambda: [100.0])
    salvage: List[int] = field(default_factory=lambda: [0])
    pd_rof_mult: List[float] = field(default_factory=lambda: [1.0])
    ciws_stacks: List[int] = field(default_factory=lambda: [0])
    bulk_stacks: List[int] = field(default_factory=lambda: [0])
    fog: FogState = field(default_factory=FogState)
    active_pings: List[ActivePing] = field(default_factory=list)
    sensor_ghosts: List[SensorGhost] = field(default_factory=list)
    seeker_ghosts: List[SensorGhost] = field(default_factory=list)
    ping_ghost_anchor_labels: Set[str] = field(default_factory=set)
    ping_ready_at_ms: int = 0
    control_groups: List[Optional[List[str]]] = field(
        default_factory=lambda: [None] * CONTROL_GROUP_SLOTS
    )
    cg_weapons_free: List[bool] = field(
        default_factory=lambda: [False] * CONTROL_GROUP_SLOTS
    )


@dataclass
class RoundState:
    round_idx: int = 1
    outcome: Optional[str] = None
    phase: str = "config"
    formation_mode: int = FORMATION_MODE_RING


@dataclass
class CameraState:
    cam_x: float = 0.0
    cam_y: float = 0.0


@dataclass
class LoadoutState:
    preview_groups: List[Group] = field(default_factory=list)
    preview_crafts: List[Craft] = field(default_factory=list)
    selected_i: int = 0
    roster_scroll: int = 0
    deployment_scrap: List[int] = field(
        default_factory=lambda: [DEPLOYMENT_STARTING_SCRAP]
    )
    choice_map: Dict[Tuple[str, int], int] = field(default_factory=dict)


@dataclass
class MpState:
    fleet_groups: List[Group] = field(default_factory=list)
    fleet_crafts: List[Craft] = field(default_factory=list)
    loadouts_active: bool = False
    post_combat_phase: Optional[str] = None
    round_idx: int = 1
    use_asteroids: bool = True
    mode_coop: bool = True
    enemy_pressure: int = 0
    lobby_host: bool = True
    lobby_authoritative: str = "player"
    ready: bool = False
    toast_until_ms: int = 0
    toast_text: str = ""
    fleet_http_base: Optional[str] = None
    player_name: str = "Player"
    name_buffer: str = "Player"
    name_focus: bool = False
    join_id_buffer: str = ""
    join_focus: bool = False
    hub_lobby_rows: List[Dict[str, Any]] = field(default_factory=list)
    hub_lobby_scroll: int = 0
    hub_list_last_ms: Optional[int] = None
    hub_list_busy: bool = False
    hub_list_started_ms: int = 0
    hub_list_q: queue.Queue = field(default_factory=queue.Queue)
    http_authority_choice: str = "player"
    chat_log: List[str] = field(default_factory=list)
    chat_input: str = ""
    chat_focus: bool = False
    remote_ready: Dict[str, bool] = field(default_factory=dict)
    match_generation: int = 0
    applied_remote_start_gen: int = 0
    remote_loadouts: Dict[str, bool] = field(default_factory=dict)
    player_color_id: int = 0
    remote_player_colors: Dict[str, int] = field(default_factory=dict)
    player_fleet_designs: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    net_err: Optional[str] = None
    hub_svc_state: str = "offline"
    hub_user_message: Optional[str] = None
    hub_last_ok_ms: int = 0
    remote_lobby_id: Optional[str] = None
    remote_lobby_short: Optional[str] = None
    # Exact string in HTTP lobby players[] for leave_lobby (stable if relay renames display).
    http_lobby_player_name: Optional[str] = None
    # From last create/join lobby.relay; None uses FLEETRTS_RELAY_* env in client.
    relay_host: Optional[str] = None
    relay_port: Optional[int] = None
    remote_lobby_http_players: List[str] = field(default_factory=list)
    remote_relay_players: List[str] = field(default_factory=list)
    relay: Optional[Any] = None
    last_lobby_poll_ms: int = 0
    combat_tick: int = 0
    host_cmd_queue: List[Dict[str, Any]] = field(default_factory=list)
    pending_snap: Optional[Dict[str, Any]] = None
    client_cmd_seq: int = 0
    client_last_snap_tick: int = -1
    last_snap_send_ms: int = 0
    fm_holder: List[int] = field(default_factory=lambda: [FORMATION_MODE_RING])
    desync_until_ms: int = 0
    desync_text: str = ""
    host_snap_tick: int = -1
    hub_debug_frames: int = 0


@dataclass
class InputState:
    drag_anchor: Optional[Tuple[int, int]] = None
    awaiting_bomber_order_click: bool = False
    awaiting_fighter_order_click: bool = False
    awaiting_capital_context_lmb: bool = False
    awaiting_attack_move_click: bool = False
    awaiting_attack_target_click: bool = False
    last_cap_click_t: int = -100000
    last_cap_click_label: Optional[str] = None
    order_hint_until: int = 0
    order_hint_msg: str = ""


@dataclass
class DebriefState:
    run_total_score: int = 0
    last_salvage_gain: int = 0
    store_selected: Optional[str] = None
    store_hover: Optional[str] = None
    test_debrief_resume: bool = False


@dataclass
class TTSState:
    prev_sel_sig: Tuple[str, ...] = ()
    last_enemy_kill_tts: int = -1_000_000
    last_player_cap_loss_tts: int = -1_000_000
    last_carrier_quip_tts: int = -1_000_000
    last_order_quip_tts: int = -1_000_000
    last_low_hull_by_label: Dict[str, int] = field(default_factory=dict)


@dataclass
class UIState:
    test_menu_open: bool = False
    pause_menu_open: bool = False
    pause_main_menu_hover: bool = False
    config_volume_drag: bool = False


@dataclass
class BGEditorState:
    path: str = ""
    presets: List[BattlegroupPreset] = field(default_factory=list)
    selected_i: int = 0
    list_scroll: int = 0
    row_scroll: int = 0
    focus: Optional[str] = None
    name_buf: str = ""
    id_buf: str = ""
    cost_buf: str = ""
    entry_i: int = 0
    rows: List[Dict[str, str]] = field(default_factory=list)
    ship_pick_i: int = 0


@dataclass
class Fonts:
    main: Optional[pygame.font.Font] = None
    tiny: Optional[pygame.font.Font] = None
    micro: Optional[pygame.font.Font] = None
    big: Optional[pygame.font.Font] = None


# ---------------------------------------------------------------------------
# Top-level GameState
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    combat: CombatState = field(default_factory=CombatState)
    round: RoundState = field(default_factory=RoundState)
    camera: CameraState = field(default_factory=CameraState)
    loadout: LoadoutState = field(default_factory=LoadoutState)
    mp: MpState = field(default_factory=MpState)
    input: InputState = field(default_factory=InputState)
    debrief: DebriefState = field(default_factory=DebriefState)
    tts: TTSState = field(default_factory=TTSState)
    ui: UIState = field(default_factory=UIState)
    bg_editor: BGEditorState = field(default_factory=BGEditorState)
    fonts: Fonts = field(default_factory=Fonts)

    data: Dict[str, Any] = field(default_factory=dict)
    stars: List[Tuple[int, int, int]] = field(default_factory=list)
    battle_obstacles: List[Asteroid] = field(default_factory=list)
    audio: Optional[Any] = None
    cap_names_menu: List[str] = field(default_factory=lambda: ["Destroyer"])
