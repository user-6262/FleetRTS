#!/usr/bin/env python3
"""
Authoritative combat sim for dedicated MP lobbies (no pygame window).

Connects to the same TCP relay as clients, joins the lobby as a reserved name, and
when it receives start_match from the lobby host, runs step_combat_frame at a fixed
rate, applies combat_cmd from peers, and broadcasts combat_snap (same protocol as
the pygame host).

Prerequisites on the droplet: droplet_http_stub.py + tcp_relay.py running; create
the lobby with authoritative: \"dedicated\" (pygame hub: F4 then Create online lobby).

Run from repo root (or any cwd) — adjusts sys.path:

  set SDL_VIDEODRIVER=dummy
  python server/headless_combat_host.py --lobby-id <uuid>

Env:
  FLEETRTS_RELAY_HOST / FLEETRTS_RELAY_PORT — relay address (defaults 127.0.0.1:8766)
  FLEETRTS_SIM_PLAYER — display name on relay (default __FleetRTS_Sim__)
  FLEETRTS_SIM_HZ — fixed sim rate (default 20)

Limitation: uses the default starter fleet from build_initial_player_fleet, not
per-player HTTP fleet payloads (future work).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Headless pygame (mixer not initialized — we use a no-op audio shim).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORE_DIR = _REPO_ROOT / "core"
for _p in (str(_CORE_DIR), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pygame  # noqa: E402

pygame.init()

import combat as cb  # noqa: E402
import mp_combat_bootstrap as mpboot  # noqa: E402
from combat import (  # noqa: E402
    CONTROL_GROUP_SLOTS,
    FORMATION_MODE_RING,
    FogState,
    SNAP_VERSION,
    TTS_ENEMY_KILL_GAP_MS,
    TTS_PLAYER_CAP_LOSS_GAP_MS,
    CombatSimHooks,
    all_player_capital_labels,
    apply_combat_command,
    apply_combat_death_audio,
    combat_cmd_tick_allowed,
    hash_state_dict,
    load_game_data,
    snapshot_state,
    step_combat_frame,
)
from net.app_messages import lobby_presence, lobby_ready  # noqa: E402
from net.combat_net import COMBAT_CMD, combat_snap  # noqa: E402
from net.relay_client import RelayClient  # noqa: E402


class _NullAudio:
    def play_positive(self) -> None:
        pass

    def play_negative(self) -> None:
        pass

    def play_ship_destroyed(self) -> None:
        pass

    def speak_voice(self, *_a: Any, **_k: Any) -> None:
        pass


def _relay_dispatch(
    msg: Dict[str, Any],
    *,
    cmd_queue: List[Dict[str, Any]],
    applied_gen_holder: List[int],
    cfg: Dict[str, Any],
    combat_holder: List[Any],
) -> None:
    """Handle relay control messages; append combat_cmd to cmd_queue when in combat."""
    if msg.get("t") != "relay":
        return
    body = msg.get("body")
    if not isinstance(body, dict):
        return
    kind = body.get("t")
    if kind == "host_config":
        cfg["coop"] = bool(body.get("coop", cfg["coop"]))
        cfg["use_asteroids"] = bool(body.get("use_asteroids", cfg["use_asteroids"]))
        ep = int(body.get("enemy_pressure", cfg["enemy_pressure"]))
        cfg["enemy_pressure"] = max(0, min(ep, 3))
        return
    if kind == "start_match":
        gen = int(body.get("generation", 0))
        if gen <= applied_gen_holder[0]:
            return
        applied_gen_holder[0] = gen
        cfg["round_idx"] = int(body.get("round_idx", cfg["round_idx"]))
        cfg["match_seed"] = body.get("seed")
        cfg["use_asteroids"] = bool(body.get("use_asteroids", cfg["use_asteroids"]))
        cfg["enemy_pressure"] = max(0, min(int(body.get("enemy_pressure", cfg["enemy_pressure"])), 3))
        psetup = body.get("player_setup")
        cfg["player_setup"] = psetup if isinstance(psetup, dict) else None
        combat_holder[0] = "bootstrap"
        return
    if kind == COMBAT_CMD and combat_holder[0] == "running":
        q = dict(body)
        q["_sender"] = str(msg.get("from") or "")
        cmd_queue.append(q)


def main() -> None:
    ap = argparse.ArgumentParser(description="FleetRTS headless authoritative combat host (TCP relay).")
    ap.add_argument("--relay-host", default=os.environ.get("FLEETRTS_RELAY_HOST", "127.0.0.1"))
    ap.add_argument("--relay-port", type=int, default=int(os.environ.get("FLEETRTS_RELAY_PORT", "8766")))
    ap.add_argument("--lobby-id", required=True, help="UUID from HTTP lobby JSON")
    ap.add_argument(
        "--player-name",
        default=os.environ.get("FLEETRTS_SIM_PLAYER", "__FleetRTS_Sim__"),
        help="Name shown in relay room (keep distinct from human players)",
    )
    args = ap.parse_args()

    sim_hz = float(os.environ.get("FLEETRTS_SIM_HZ", "20"))
    step_dt = 1.0 / max(1.0, sim_hz)

    data = load_game_data()
    audio = _NullAudio()
    relay = RelayClient(args.relay_host, args.relay_port, args.lobby_id.strip(), str(args.player_name)[:64])
    relay.connect()
    if relay.error:
        print(f"[FleetRTS sim] Relay connect failed: {relay.error}", file=sys.stderr)
        sys.exit(1)

    relay.send_payload(lobby_ready(True))
    relay.send_payload(lobby_presence(in_fleet_design=False))
    print(
        f"[FleetRTS sim] Connected to relay {args.relay_host}:{args.relay_port} lobby={args.lobby_id} as {args.player_name!r}",
        flush=True,
    )

    cfg: Dict[str, Any] = {
        "coop": True,
        "use_asteroids": True,
        "enemy_pressure": 0,
        "round_idx": 1,
        "match_seed": None,
        "player_setup": None,
    }
    applied_gen: List[int] = [0]
    combat_mode: List[Any] = [None]  # None | "bootstrap" | "running"

    groups: List[Any] = []
    crafts: List[Any] = []
    mission: Any = None
    missiles: List[Any] = []
    ballistics: List[Any] = []
    vfx_sparks: List[Any] = []
    vfx_beams: List[Any] = []
    supplies = [100.0]
    salvage = [0]
    pd_rof_mult = [1.0]
    fog = FogState()
    active_pings: List[Any] = []
    sensor_ghosts: List[Any] = []
    seeker_ghosts: List[Any] = []
    ping_ghost_anchor_labels: Set[str] = set()
    ping_ready_at_ms = 0
    control_groups: List[Any] = [None] * CONTROL_GROUP_SLOTS
    cg_weapons_free: List[bool] = [False] * CONTROL_GROUP_SLOTS
    mp_fm_holder = [FORMATION_MODE_RING]
    cmd_queue: List[Dict[str, Any]] = []
    mp_combat_tick = 0
    last_snap_ms = 0
    outcome: Optional[str] = None
    phase = "lobby"
    run_total_score = 0
    last_salvage_gain = 0
    store_selected: Optional[str] = None
    store_hover: Optional[str] = None
    tts_pc = -10**6
    tts_ek = -10**6

    loop_last = time.monotonic()
    accum = 0.0
    running = True
    while running:
        if relay.error:
            print(f"[FleetRTS sim] Relay error: {relay.error}", file=sys.stderr)
            break
        now = time.monotonic()
        accum += now - loop_last
        loop_last = now

        for m in relay.poll():
            _relay_dispatch(
                m,
                cmd_queue=cmd_queue,
                applied_gen_holder=applied_gen,
                cfg=cfg,
                combat_holder=combat_mode,
            )

        if combat_mode[0] == "bootstrap":
            cmd_queue.clear()
            mp_combat_tick = 0
            outcome = None
            phase = "combat"
            missiles.clear()
            ballistics.clear()
            vfx_sparks.clear()
            vfx_beams.clear()
            supplies[0] = 100.0
            salvage[0] = 0
            pd_rof_mult[0] = 1.0
            fog = FogState()
            active_pings.clear()
            sensor_ghosts.clear()
            seeker_ghosts.clear()
            ping_ghost_anchor_labels.clear()
            ping_ready_at_ms = 0
            control_groups[:] = [None] * CONTROL_GROUP_SLOTS
            cg_weapons_free[:] = [False] * CONTROL_GROUP_SLOTS
            mission = mpboot.bootstrap_mp_combat_match(
                data=data,
                round_idx=int(cfg["round_idx"]),
                match_seed=cfg["match_seed"],
                use_asteroids=bool(cfg["use_asteroids"]),
                enemy_pressure=int(cfg["enemy_pressure"]),
                groups=groups,
                crafts=crafts,
                player_setup=cfg.get("player_setup"),
                mp_pvp=not bool(cfg.get("coop", True)),
            )
            control_groups[0] = all_player_capital_labels(groups)
            combat_mode[0] = "running"
            last_snap_ms = 0
            print("[FleetRTS sim] Match started — stepping combat.", flush=True)

        step_budget = 8
        while combat_mode[0] == "running" and accum >= step_dt and step_budget > 0:
            step_budget -= 1
            accum -= step_dt
            for m in relay.poll():
                _relay_dispatch(
                    m,
                    cmd_queue=cmd_queue,
                    applied_gen_holder=applied_gen,
                    cfg=cfg,
                    combat_holder=combat_mode,
                )

            now_ms = pygame.time.get_ticks()
            ping_holder = [ping_ready_at_ms]
            for qcmd in cmd_queue:
                cmd_in = {
                    "kind": str(qcmd.get("kind", "")),
                    "payload": dict(qcmd.get("payload") or {}),
                    "sender": str(qcmd.get("_sender") or ""),
                    "tick": int(qcmd.get("tick", 0)),
                }
                if not combat_cmd_tick_allowed(cmd_in, host_tick=mp_combat_tick):
                    if os.environ.get("FLEETRTS_MP_CMD_TRACE"):
                        print(
                            f"[FleetRTS MP] drop cmd kind={cmd_in['kind']!r} "
                            f"cmd_tick={cmd_in['tick']} host_tick={mp_combat_tick} "
                            f"sender={cmd_in['sender']!r}",
                            flush=True,
                        )
                    continue
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
                    now_ms=now_ms,
                    audio=audio,
                    cmd={
                        "kind": cmd_in["kind"],
                        "payload": cmd_in["payload"],
                        "sender": cmd_in["sender"],
                    },
                )
            cmd_queue.clear()
            ping_ready_at_ms = ping_holder[0]

            res = step_combat_frame(
                data=data,
                dt=step_dt,
                round_idx=int(cfg["round_idx"]),
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
                hooks=CombatSimHooks(on_player_hull_hit=lambda _t: None),
                phase=phase,
                outcome=outcome,
            )
            tts_pc, tts_ek = apply_combat_death_audio(
                res.death_audio,
                audio,
                now_ms,
                tts_last_player_cap_loss_tts=tts_pc,
                tts_last_enemy_kill_tts=tts_ek,
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

            if now_ms - last_snap_ms >= 50:
                st = snapshot_state(
                    tick=mp_combat_tick,
                    round_idx=int(cfg["round_idx"]),
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
                relay.send_payload(
                    combat_snap(
                        tick=mp_combat_tick,
                        snap_version=SNAP_VERSION,
                        state_hash=h,
                        state=st,
                    )
                )
                last_snap_ms = now_ms
            mp_combat_tick += 1

            if phase == "debrief":
                st = snapshot_state(
                    tick=mp_combat_tick,
                    round_idx=int(cfg["round_idx"]),
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
                relay.send_payload(
                    combat_snap(
                        tick=mp_combat_tick,
                        snap_version=SNAP_VERSION,
                        state_hash=h,
                        state=st,
                    )
                )
                combat_mode[0] = None
                print("[FleetRTS sim] Match ended (debrief) — idle until next start_match.", flush=True)
                break

        accum = min(accum, step_dt * 4)
        time.sleep(0.001)

    relay.close()
    pygame.quit()


if __name__ == "__main__":
    main()
