"""
Online multiplayer session: TCP relay dispatch and client combat snapshot apply.

Keeps relay/snapshot orchestration out of the main pygame run loop in demo_game.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

try:
    from combat import apply_snapshot_state, hash_state_dict
    from net.app_messages import lobby_loadout, lobby_presence, lobby_ready
    from net.combat_net import COMBAT_CMD, COMBAT_SNAP
except ImportError:
    from core.combat import apply_snapshot_state, hash_state_dict
    from core.net.app_messages import lobby_loadout, lobby_presence, lobby_ready
    from core.net.combat_net import COMBAT_CMD, COMBAT_SNAP


def sync_match_active(
    net_mp: bool,
    remote_lobby_id: Optional[str],
    mp_relay: Any,
    post_combat_phase: Optional[str],
) -> bool:
    return bool(
        net_mp
        and remote_lobby_id
        and mp_relay is not None
        and not getattr(mp_relay, "error", True)
        and post_combat_phase == "mp_lobby"
    )


def net_combat_active(
    net_mp: bool,
    remote_lobby_id: Optional[str],
    mp_relay: Any,
    post_combat_phase: Optional[str],
    phase: str,
    outcome: Optional[str],
) -> bool:
    return bool(
        sync_match_active(net_mp, remote_lobby_id, mp_relay, post_combat_phase)
        and phase == "combat"
        and outcome is None
    )


def local_runs_authoritative_sim(
    net_mp: bool,
    remote_lobby_id: Optional[str],
    mp_relay: Any,
    post_combat_phase: Optional[str],
    phase: str,
    outcome: Optional[str],
    mp_lobby_host: bool,
    mp_lobby_authoritative: str,
) -> bool:
    return bool(
        net_combat_active(net_mp, remote_lobby_id, mp_relay, post_combat_phase, phase, outcome)
        and mp_lobby_host
        and mp_lobby_authoritative != "dedicated"
    )


def is_net_client(
    net_mp: bool,
    remote_lobby_id: Optional[str],
    mp_relay: Any,
    post_combat_phase: Optional[str],
    phase: str,
    outcome: Optional[str],
    mp_lobby_host: bool,
    mp_lobby_authoritative: str,
) -> bool:
    return bool(
        net_combat_active(net_mp, remote_lobby_id, mp_relay, post_combat_phase, phase, outcome)
        and not local_runs_authoritative_sim(
            net_mp,
            remote_lobby_id,
            mp_relay,
            post_combat_phase,
            phase,
            outcome,
            mp_lobby_host,
            mp_lobby_authoritative,
        )
    )


def snapshot_broadcast_authority(
    net_mp: bool,
    remote_lobby_id: Optional[str],
    mp_relay: Any,
    post_combat_phase: Optional[str],
    mp_lobby_host: bool,
    mp_lobby_authoritative: str,
) -> bool:
    return bool(
        net_mp
        and remote_lobby_id
        and mp_relay is not None
        and not getattr(mp_relay, "error", True)
        and post_combat_phase == "mp_lobby"
        and mp_lobby_host
        and mp_lobby_authoritative != "dedicated"
    )


def receives_combat_snapshots(
    net_mp: bool,
    remote_lobby_id: Optional[str],
    mp_relay: Any,
    post_combat_phase: Optional[str],
    phase: str,
    mp_lobby_host: bool,
    mp_lobby_authoritative: str,
) -> bool:
    return bool(
        sync_match_active(net_mp, remote_lobby_id, mp_relay, post_combat_phase)
        and phase in ("combat", "debrief")
        and not snapshot_broadcast_authority(
            net_mp,
            remote_lobby_id,
            mp_relay,
            post_combat_phase,
            mp_lobby_host,
            mp_lobby_authoritative,
        )
    )


@dataclass
class MpRelayEnv:
    """Session flags refreshed each frame before polling the relay."""

    net_mp: bool = False
    remote_lobby_id: Optional[str] = None
    mp_lobby_host: bool = True
    mp_lobby_authoritative: str = "player"
    post_combat_phase: Optional[str] = None
    mp_loadouts_active: bool = False
    mp_player_color_id: int = 0
    mp_ready: bool = False
    lobby_loadout_enabled: bool = False


@dataclass
class MpRelaySync:
    """Mutable MP state shared with demo_game.run (lists/dicts are shared by reference)."""

    remote_relay_players: List[str]
    mp_chat_log: List[str]
    remote_ready: Dict[str, bool]
    remote_loadouts: Dict[str, bool]
    remote_player_colors: Dict[str, int]
    mp_player_fleet_designs: Dict[str, List[Dict[str, str]]]
    mp_host_cmd_queue: List[Any]
    phase: str = "mp_lobby"
    outcome: Optional[str] = None
    mp_net_err: Optional[str] = None
    mp_mode_coop: bool = True
    mp_use_asteroids: bool = True
    mp_enemy_pressure: int = 0
    mp_applied_remote_start_gen: int = 0
    mp_round_idx: int = 1
    mp_pending_snap: Optional[Dict[str, Any]] = None
    mp_client_last_snap_tick: int = -1


@dataclass
class MpRelayCallbacks:
    send_host_config_if_online: Callable[[], None]
    on_start_match: Callable[[Optional[int], Optional[Dict[str, Any]]], None]
    play_positive: Callable[[], None]
    export_fleet_rows: Callable[[], List[Dict[str, str]]]


def poll_relay(relay: Any, sync: MpRelaySync, env: MpRelayEnv, cb: MpRelayCallbacks) -> None:
    if relay is None:
        return
    if getattr(relay, "error", None):
        sync.mp_net_err = relay.error
    for _m in relay.poll():
        _dispatch_relay_message(_m, relay, sync, env, cb)


def _dispatch_relay_message(
    _m: Dict[str, Any],
    relay: Any,
    sync: MpRelaySync,
    env: MpRelayEnv,
    cb: MpRelayCallbacks,
) -> None:
    if _m.get("t") == "joined":
        sync.remote_relay_players[:] = list(_m.get("players") or [])
        relay.send_payload(lobby_ready(env.mp_ready))
        if env.mp_lobby_host:
            cb.send_host_config_if_online()
        in_fd = sync.phase == "ship_loadouts" and env.mp_loadouts_active
        relay.send_payload(lobby_presence(in_fleet_design=in_fd, color_id=env.mp_player_color_id))
        if env.lobby_loadout_enabled:
            relay.send_payload(lobby_loadout(payload={"fleet": cb.export_fleet_rows()}))
    elif _m.get("t") == "peer_left":
        sync.remote_relay_players[:] = list(_m.get("players") or [])
        left_p = str(_m.get("player") or "")
        if left_p:
            sync.remote_ready.pop(left_p, None)
            sync.remote_loadouts.pop(left_p, None)
    elif _m.get("t") == "relay":
        body = _m.get("body")
        if not isinstance(body, dict):
            return
        kind = body.get("t")
        if kind == "lobby_chat":
            who = str(_m.get("from") or "?")
            txt = str(body.get("text") or "")[:240]
            sync.mp_chat_log.append(f"{who}: {txt}")
            if len(sync.mp_chat_log) > 80:
                sync.mp_chat_log[:] = sync.mp_chat_log[-80:]
        elif kind == "lobby_ready":
            who = str(_m.get("from") or "?")
            sync.remote_ready[who] = bool(body.get("v"))
        elif kind == "lobby_presence":
            who = str(_m.get("from") or "?")
            sync.remote_loadouts[who] = bool(body.get("in_fleet_design", False))
            sync.remote_player_colors[who] = int(max(0, min(int(body.get("color_id", 0)), 5)))
        elif kind == "lobby_loadout":
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
                sync.mp_player_fleet_designs[who] = cleaned
        elif kind == "host_config":
            if not env.mp_lobby_host:
                sync.mp_mode_coop = bool(body.get("coop", sync.mp_mode_coop))
                sync.mp_use_asteroids = bool(body.get("use_asteroids", sync.mp_use_asteroids))
                ep = int(body.get("enemy_pressure", sync.mp_enemy_pressure))
                sync.mp_enemy_pressure = max(0, min(ep, 3))
                if not sync.mp_mode_coop:
                    sync.mp_enemy_pressure = 0
        elif kind == COMBAT_CMD:
            _host_runs_sim = env.mp_lobby_host and env.mp_lobby_authoritative != "dedicated"
            if (
                _host_runs_sim
                and sync_match_active(
                    env.net_mp, env.remote_lobby_id, relay, env.post_combat_phase
                )
                and sync.phase == "combat"
                and sync.outcome is None
            ):
                q = dict(body)
                q["_sender"] = str(_m.get("from") or "")
                sync.mp_host_cmd_queue.append(q)
        elif kind == COMBAT_SNAP:
            _client_snap = (not env.mp_lobby_host) or (env.mp_lobby_authoritative == "dedicated")
            if _client_snap and sync_match_active(
                env.net_mp, env.remote_lobby_id, relay, env.post_combat_phase
            ) and sync.phase in ("combat", "debrief"):
                t_new = int(body.get("tick", -1))
                if t_new > sync.mp_client_last_snap_tick:
                    t_pending = (
                        int(sync.mp_pending_snap.get("tick", -2))
                        if isinstance(sync.mp_pending_snap, dict)
                        else -2
                    )
                    if sync.mp_pending_snap is None or t_new >= t_pending:
                        sync.mp_pending_snap = dict(body)
        elif kind == "start_match":
            if sync.phase == "mp_lobby":
                gen = int(body.get("generation", 0))
                if gen > sync.mp_applied_remote_start_gen:
                    sync.mp_applied_remote_start_gen = gen
                    sync.mp_round_idx = int(body.get("round_idx", sync.mp_round_idx))
                    sync.mp_use_asteroids = bool(body.get("use_asteroids", sync.mp_use_asteroids))
                    sync.mp_mode_coop = bool(body.get("coop", True))
                    ep = int(body.get("enemy_pressure", sync.mp_enemy_pressure))
                    sync.mp_enemy_pressure = max(0, min(ep, 3))
                    ms = body.get("seed")
                    mseed = int(ms) if ms is not None else None
                    psetup = body.get("player_setup")
                    cb.on_start_match(mseed, psetup if isinstance(psetup, dict) else None)
                    cb.play_positive()


@dataclass
class MpClientSnapshotIO:
    """Scalars updated by apply_pending_combat_snapshot (owned by run loop)."""

    outcome: Optional[str] = None
    phase: str = "combat"
    ping_ready_at_ms: int = 0
    run_total_score: int = 0
    last_salvage_gain: int = 0
    store_selected: Optional[str] = None
    store_hover: Optional[str] = None
    mp_desync_text: str = ""
    mp_desync_until_ms: int = 0


def apply_pending_combat_snapshot(
    sync: MpRelaySync,
    io: MpClientSnapshotIO,
    salvage: List[float],
    *,
    now_ms_frame: int,
    data: dict,
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
) -> bool:
    if sync.mp_pending_snap is None:
        return False
    body = sync.mp_pending_snap
    sync.mp_pending_snap = None
    tsn = int(body.get("tick", -9))
    if tsn <= sync.mp_client_last_snap_tick:
        return False
    st = body.get("state")
    if not isinstance(st, dict):
        return False
    hx = str(body.get("state_hash", ""))
    lh = hash_state_dict(st)
    if lh != hx:
        io.mp_desync_text = f"DESYNC hash tick={tsn}"
        io.mp_desync_until_ms = now_ms_frame + 8000
        print(f"[FleetRTS MP] {io.mp_desync_text} local={lh[:16]}… host={hx[:16]}…")
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
    io.ping_ready_at_ms = snap_ping_ms
    io.outcome = snap_outcome
    io.phase = snap_phase
    if salvage:
        salvage[0] = float(int(snap_salvage))
    io.run_total_score = snap_score
    io.last_salvage_gain = snap_last_sg
    io.store_selected = snap_store_sel
    io.store_hover = snap_store_hov
    if os.environ.get("FLEETRTS_MP_SNAP_TRACE"):
        prev = int(sync.mp_client_last_snap_tick)
        if prev >= 0 and tsn - prev > 30:
            print(f"[FleetRTS MP] snap tick jump {prev} -> {tsn}")
    sync.mp_client_last_snap_tick = tsn
    return True
