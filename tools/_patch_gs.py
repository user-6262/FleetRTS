"""Mechanical replacement of run()'s local variables with GameState attributes.

Run once then delete:  python tools/_patch_gs.py
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "core" / "demo_game.py"

# ── variable mapping ────────────────────────────────────────────────────────
# old local name -> new gs.* path.
MAPPING = {
    # CombatState
    "groups": "gs.combat.groups",
    "crafts": "gs.combat.crafts",
    "mission": "gs.combat.mission",
    "missiles": "gs.combat.missiles",
    "ballistics": "gs.combat.ballistics",
    "vfx_sparks": "gs.combat.vfx_sparks",
    "vfx_beams": "gs.combat.vfx_beams",
    "supplies": "gs.combat.supplies",
    "salvage": "gs.combat.salvage",
    "pd_rof_mult": "gs.combat.pd_rof_mult",
    "ciws_stacks": "gs.combat.ciws_stacks",
    "bulk_stacks": "gs.combat.bulk_stacks",
    "fog": "gs.combat.fog",
    "active_pings": "gs.combat.active_pings",
    "sensor_ghosts": "gs.combat.sensor_ghosts",
    "seeker_ghosts": "gs.combat.seeker_ghosts",
    "ping_ghost_anchor_labels": "gs.combat.ping_ghost_anchor_labels",
    "ping_ready_at_ms": "gs.combat.ping_ready_at_ms",
    "control_groups": "gs.combat.control_groups",
    "cg_weapons_free": "gs.combat.cg_weapons_free",
    # RoundState
    "round_idx": "gs.round.round_idx",
    "outcome": "gs.round.outcome",
    "phase": "gs.round.phase",
    "formation_mode": "gs.round.formation_mode",
    # CameraState
    "cam_x": "gs.camera.cam_x",
    "cam_y": "gs.camera.cam_y",
    # LoadoutState
    "loadout_preview_groups": "gs.loadout.preview_groups",
    "loadout_preview_crafts": "gs.loadout.preview_crafts",
    "loadout_selected_i": "gs.loadout.selected_i",
    "loadout_roster_scroll": "gs.loadout.roster_scroll",
    "deployment_scrap": "gs.loadout.deployment_scrap",
    "loadout_choice_map": "gs.loadout.choice_map",
    # MpState
    "mp_fleet_groups": "gs.mp.fleet_groups",
    "mp_fleet_crafts": "gs.mp.fleet_crafts",
    "mp_loadouts_active": "gs.mp.loadouts_active",
    "post_combat_phase": "gs.mp.post_combat_phase",
    "mp_round_idx": "gs.mp.round_idx",
    "mp_use_asteroids": "gs.mp.use_asteroids",
    "mp_mode_coop": "gs.mp.mode_coop",
    "mp_enemy_pressure": "gs.mp.enemy_pressure",
    "mp_lobby_host": "gs.mp.lobby_host",
    "mp_lobby_authoritative": "gs.mp.lobby_authoritative",
    "mp_ready": "gs.mp.ready",
    "mp_toast_until_ms": "gs.mp.toast_until_ms",
    "mp_toast_text": "gs.mp.toast_text",
    "fleet_http_base": "gs.mp.fleet_http_base",
    "mp_player_name": "gs.mp.player_name",
    "mp_name_buffer": "gs.mp.name_buffer",
    "mp_name_focus": "gs.mp.name_focus",
    "mp_join_id_buffer": "gs.mp.join_id_buffer",
    "mp_join_focus": "gs.mp.join_focus",
    "mp_hub_lobby_rows": "gs.mp.hub_lobby_rows",
    "mp_hub_lobby_scroll": "gs.mp.hub_lobby_scroll",
    "mp_hub_list_last_ms": "gs.mp.hub_list_last_ms",
    "mp_hub_list_busy": "gs.mp.hub_list_busy",
    "mp_hub_list_started_ms": "gs.mp.hub_list_started_ms",
    "mp_hub_list_q": "gs.mp.hub_list_q",
    "mp_http_authority_choice": "gs.mp.http_authority_choice",
    "mp_chat_log": "gs.mp.chat_log",
    "mp_chat_input": "gs.mp.chat_input",
    "mp_chat_focus": "gs.mp.chat_focus",
    "remote_ready": "gs.mp.remote_ready",
    "mp_match_generation": "gs.mp.match_generation",
    "mp_applied_remote_start_gen": "gs.mp.applied_remote_start_gen",
    "remote_loadouts": "gs.mp.remote_loadouts",
    "mp_player_color_id": "gs.mp.player_color_id",
    "remote_player_colors": "gs.mp.remote_player_colors",
    "mp_player_fleet_designs": "gs.mp.player_fleet_designs",
    "mp_net_err": "gs.mp.net_err",
    "mp_hub_svc_state": "gs.mp.hub_svc_state",
    "mp_hub_user_message": "gs.mp.hub_user_message",
    "mp_hub_last_ok_ms": "gs.mp.hub_last_ok_ms",
    "remote_lobby_id": "gs.mp.remote_lobby_id",
    "remote_lobby_short": "gs.mp.remote_lobby_short",
    "http_lobby_player_name": "gs.mp.http_lobby_player_name",
    "relay_host": "gs.mp.relay_host",
    "relay_port": "gs.mp.relay_port",
    "remote_lobby_http_players": "gs.mp.remote_lobby_http_players",
    "remote_relay_players": "gs.mp.remote_relay_players",
    "mp_relay": "gs.mp.relay",
    "mp_last_lobby_poll_ms": "gs.mp.last_lobby_poll_ms",
    "mp_combat_tick": "gs.mp.combat_tick",
    "mp_host_cmd_queue": "gs.mp.host_cmd_queue",
    "mp_pending_snap": "gs.mp.pending_snap",
    "mp_client_cmd_seq": "gs.mp.client_cmd_seq",
    "mp_client_last_snap_tick": "gs.mp.client_last_snap_tick",
    "mp_last_snap_send_ms": "gs.mp.last_snap_send_ms",
    "mp_fm_holder": "gs.mp.fm_holder",
    "mp_desync_until_ms": "gs.mp.desync_until_ms",
    "mp_desync_text": "gs.mp.desync_text",
    "mp_host_snap_tick": "gs.mp.host_snap_tick",
    "mp_hub_debug_frames": "gs.mp.hub_debug_frames",
    # InputState
    "drag_anchor": "gs.input.drag_anchor",
    "awaiting_bomber_order_click": "gs.input.awaiting_bomber_order_click",
    "awaiting_fighter_order_click": "gs.input.awaiting_fighter_order_click",
    "awaiting_capital_context_lmb": "gs.input.awaiting_capital_context_lmb",
    "awaiting_attack_move_click": "gs.input.awaiting_attack_move_click",
    "awaiting_attack_target_click": "gs.input.awaiting_attack_target_click",
    "last_cap_click_t": "gs.input.last_cap_click_t",
    "last_cap_click_label": "gs.input.last_cap_click_label",
    "order_hint_until": "gs.input.order_hint_until",
    "order_hint_msg": "gs.input.order_hint_msg",
    # DebriefState
    "run_total_score": "gs.debrief.run_total_score",
    "last_salvage_gain": "gs.debrief.last_salvage_gain",
    "store_selected": "gs.debrief.store_selected",
    "store_hover": "gs.debrief.store_hover",
    "test_debrief_resume": "gs.debrief.test_debrief_resume",
    # TTSState
    "tts_prev_sel_sig": "gs.tts.prev_sel_sig",
    "tts_last_enemy_kill_tts": "gs.tts.last_enemy_kill_tts",
    "tts_last_player_cap_loss_tts": "gs.tts.last_player_cap_loss_tts",
    "tts_last_carrier_quip_tts": "gs.tts.last_carrier_quip_tts",
    "tts_last_order_quip_tts": "gs.tts.last_order_quip_tts",
    "tts_last_low_hull_by_label": "gs.tts.last_low_hull_by_label",
    # UIState
    "test_menu_open": "gs.ui.test_menu_open",
    "pause_menu_open": "gs.ui.pause_menu_open",
    "pause_main_menu_hover": "gs.ui.pause_main_menu_hover",
    "config_volume_drag": "gs.ui.config_volume_drag",
    # BGEditorState
    "bg_editor_path": "gs.bg_editor.path",
    "bg_editor_presets": "gs.bg_editor.presets",
    "bg_editor_selected_i": "gs.bg_editor.selected_i",
    "bg_editor_list_scroll": "gs.bg_editor.list_scroll",
    "bg_editor_row_scroll": "gs.bg_editor.row_scroll",
    "bg_editor_focus": "gs.bg_editor.focus",
    "bg_editor_name_buf": "gs.bg_editor.name_buf",
    "bg_editor_id_buf": "gs.bg_editor.id_buf",
    "bg_editor_cost_buf": "gs.bg_editor.cost_buf",
    "bg_editor_entry_i": "gs.bg_editor.entry_i",
    "bg_editor_rows": "gs.bg_editor.rows",
    "bg_editor_ship_pick_i": "gs.bg_editor.ship_pick_i",
    # Top-level resources
    "data": "gs.data",
    "stars": "gs.stars",
    "battle_obstacles": "gs.battle_obstacles",
    "audio": "gs.audio",
    "font_tiny": "gs.fonts.tiny",
    "font_micro": "gs.fonts.micro",
    "font_big": "gs.fonts.big",
    "font": "gs.fonts.main",
    "cap_names_menu": "gs.cap_names_menu",
}

# Pre-compile patterns sorted longest-first to avoid partial matches.
SORTED_NAMES = sorted(MAPPING, key=len, reverse=True)
PATTERNS = {}
for _name in SORTED_NAMES:
    PATTERNS[_name] = re.compile(
        r"(?<!\.)\b" + re.escape(_name) + r"\b(?!=[^=])"
    )


# ── GS initialisation block (replaces the old local declarations) ───────────
GS_INIT_BLOCK = r'''
    try:
        from game_state import GameState
    except ImportError:
        from core.game_state import GameState

    gs = GameState()
    gs.data = load_game_data()
    gs.battle_obstacles = parse_obstacles(gs.data)
    random.seed(42)
    gs.stars = [
        (random.randint(0, max(1, WORLD_W - 1)), random.randint(0, max(1, WORLD_H - 1)), random.randint(40, 120))
        for _ in range(960)
    ]
    gs.camera.cam_x = WORLD_W * 0.35
    gs.camera.cam_y = WORLD_H * 0.35

    _mp_default_name = (os.environ.get("FLEETRTS_PLAYER", "Player").strip() or "Player")[:48]
    gs.mp.player_name = _mp_default_name
    gs.mp.name_buffer = _mp_default_name
    gs.mp.fleet_http_base = _resolve_fleet_http_base()

    gs.mp.fm_holder = [gs.round.formation_mode]
    gs.combat.control_groups[0] = all_player_capital_labels(gs.combat.groups)
    gs.audio = audio
    gs.fonts.main = font
    gs.fonts.tiny = font_tiny
    gs.fonts.micro = font_micro
    gs.fonts.big = font_big
'''.lstrip("\n").rstrip() + "\n"


def apply_replacements(line: str) -> str:
    for name in SORTED_NAMES:
        line = PATTERNS[name].sub(MAPPING[name], line)
    return line


def transform(text: str) -> str:
    lines = text.split("\n")

    # Find key line indices (0-based).
    run_def = None
    init_start = None  # "data = load_game_data()"
    init_end = None    # "mp_host_snap_tick = -1"
    for i, raw in enumerate(lines):
        s = raw.strip()
        if run_def is None and raw.startswith("def run()"):
            run_def = i
        if run_def is not None and init_start is None and s == "data = load_game_data()":
            init_start = i
        if run_def is not None and init_start is not None and init_end is None and s == "mp_host_snap_tick = -1":
            init_end = i

    if run_def is None or init_start is None or init_end is None:
        raise ValueError(
            f"Landmarks not found: run_def={run_def}, init_start={init_start}, init_end={init_end}"
        )

    # Build the new file.
    out: list[str] = []

    # 1) Everything before init block stays unchanged.
    out.extend(lines[:init_start])

    # 2) Insert the gs init block.
    out.extend(GS_INIT_BLOCK.split("\n"))

    # 3) Transform the rest of run() (inner functions + main loop).
    transform_start = init_end + 1
    for line in lines[transform_start:]:
        stripped = line.lstrip()

        # Remove nonlocal declarations (all mapped vars are now gs attrs).
        if stripped.startswith("nonlocal "):
            # Keep line as blank to preserve file structure / line proximity.
            out.append("")
            continue

        out.append(apply_replacements(line))

    return "\n".join(out)


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    result = transform(text)
    SRC.write_text(result, encoding="utf-8")
    print(f"OK Patched {SRC}  ({len(text)} -> {len(result)} chars)")

    # Quick compile check.
    import py_compile
    try:
        py_compile.compile(str(SRC), doraise=True)
        print("  py_compile OK")
    except py_compile.PyCompileError as e:
        print(f"  py_compile FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
