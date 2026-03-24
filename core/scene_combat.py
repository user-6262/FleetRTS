"""Combat scene — the core gameplay loop.

Handles camera movement, unit selection, right-click orders, step_combat_frame
integration, bottom HUD, pause overlay, and multiplayer sync (host/client).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import pygame

try:
    from combat_constants import WORLD_H, WORLD_W
    from combat_engine import fog_cell_visible
    from combat_math import dist_xy
    from combat_mp import apply_combat_command, _save_selection, _restore_selection
    from combat_sim import (
        CombatAudioEvents, CombatSimHooks, CombatStepResult,
        apply_combat_death_audio, step_combat_frame,
    )
    from combat_snapshot import (
        snapshot_state, apply_snapshot_state, hash_state_dict, SNAP_VERSION,
    )
    from demo_game import (
        CONTROL_GROUP_SLOTS, FORMATION_MODE_CARRIER_CORE,
        FORMATION_MODE_DAMAGED_CORE, FORMATION_MODE_RING,
    )
    from net.combat_net import (
        combat_cmd as net_combat_cmd, combat_snap as net_combat_snap,
        COMBAT_CMD, COMBAT_SNAP,
    )
except ImportError:
    from core.combat_constants import WORLD_H, WORLD_W
    from core.combat_engine import fog_cell_visible
    from core.combat_math import dist_xy
    from core.combat_mp import apply_combat_command, _save_selection, _restore_selection
    from core.combat_sim import (
        CombatAudioEvents, CombatSimHooks, CombatStepResult,
        apply_combat_death_audio, step_combat_frame,
    )
    from core.combat_snapshot import (
        snapshot_state, apply_snapshot_state, hash_state_dict, SNAP_VERSION,
    )
    from core.demo_game import (
        CONTROL_GROUP_SLOTS, FORMATION_MODE_CARRIER_CORE,
        FORMATION_MODE_DAMAGED_CORE, FORMATION_MODE_RING,
    )
    from core.net.combat_net import (
        combat_cmd as net_combat_cmd, combat_snap as net_combat_snap,
        COMBAT_CMD, COMBAT_SNAP,
    )

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, ACCENT_GREEN, ACCENT_RED, SELECT_YELLOW,
    WIDTH, HEIGHT, BOTTOM_BAR_H, VIEW_W, VIEW_H, CAM_PAN_SPEED,
    draw_battle_world, draw_panel, draw_button,
    world_to_screen, screen_to_world, clamp_camera,
)
from scenes import RunContext

# ── tuning ──────────────────────────────────────────────────────────────────
CAPITAL_PICK_R = 42
FORMATION_BASE_R = 58
FORMATION_PER_UNIT = 12
FORMATION_MODE_NAMES = ("Ring", "Carrier core", "Damaged core")
ORDER_PANEL_W = 208
TTS_ENEMY_KILL_GAP_MS = 2600
TTS_PLAYER_CAP_LOSS_GAP_MS = 4500
TTS_ORDER_QUIP_GAP_MS = 2200
SNAP_BROADCAST_INTERVAL_MS = 100

_next_pace_id = 0

def _alloc_pace_id() -> int:
    global _next_pace_id
    _next_pace_id += 1
    return _next_pace_id

# ── helpers ─────────────────────────────────────────────────────────────────

def _order_panel_rect() -> pygame.Rect:
    return pygame.Rect(WIDTH - ORDER_PANEL_W, VIEW_H, ORDER_PANEL_W, BOTTOM_BAR_H)


def _cg_slot_rect(slot: int) -> pygame.Rect:
    w, gap, tm = 52, 4, 8
    return pygame.Rect(8 + slot * (w + gap), VIEW_H + tm, w, BOTTOM_BAR_H - tm * 2)


def _order_cells() -> List[Tuple[pygame.Rect, str, str]]:
    r = _order_panel_rect()
    pad, title_h, stance_h = 5, 14, 36
    bw = max(40, (r.w - pad * 3) // 2)
    inner = max(48, r.h - pad * 2 - title_h - stance_h)
    bh = max(12, (inner - 20) // 6)
    specs = [
        ("Move", "move"), ("Atk-move", "attack_move"),
        ("Attack", "attack_target"), ("Hold", "hold"),
        ("Formation", "formation"), ("Strike (F)", "strike"),
        ("Recall CV", "recall"), ("Ping", "ping"),
        ("Focus", "focus"),
    ]
    out: List[Tuple[pygame.Rect, str, str]] = []
    for i, (lab, act) in enumerate(specs):
        row, col = divmod(i, 2)
        x = r.x + pad + col * (bw + pad)
        y = r.y + pad + title_h + row * (bh + 4)
        out.append((pygame.Rect(x, y, bw, bh), act, lab))
    return out


def _pause_btn_rect() -> pygame.Rect:
    return pygame.Rect(WIDTH // 2 - 100, HEIGHT - 80, 200, 44)


def _sel_caps(gs: Any) -> List[Any]:
    return [g for g in gs.combat.groups
            if g.side == "player" and g.selected and not g.dead and g.render_capital]


def _set_selection(groups: list, picked: list) -> None:
    for g in groups:
        g.selected = False
    for g in picked:
        g.selected = True


def _add_selection(groups: list, add: list) -> None:
    for g in add:
        if not g.dead and g.render_capital and g.side == "player":
            g.selected = True


def _pick_capital_at(groups: list, mx: int, my: int,
                     cam_x: float, cam_y: float) -> Any | None:
    best, best_d = None, 9999.0
    for g in groups:
        if g.side != "player" or g.dead or not g.render_capital:
            continue
        sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        d = dist_xy(sx, sy, float(mx), float(my))
        if d < CAPITAL_PICK_R * max(0.85, sc) and d < best_d:
            best, best_d = g, d
    return best


def _pick_hostile_at(groups: list, crafts: list, mx: int, my: int,
                     cam_x: float, cam_y: float) -> Any | None:
    best, best_d = None, 9999.0
    for g in groups:
        if g.dead or g.side == "player" or not g.render_capital:
            continue
        sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        d = dist_xy(sx, sy, float(mx), float(my))
        if d < CAPITAL_PICK_R * max(0.85, sc) and d < best_d:
            best, best_d = g, d
    for c in crafts:
        if c.dead or c.side == "player":
            continue
        sx, sy, sc = world_to_screen(c.x, c.y, c.z, cam_x, cam_y)
        d = dist_xy(sx, sy, float(mx), float(my))
        if d < 24.0 * max(0.78, sc) and d < best_d:
            best, best_d = c, d
    return best


def _focus_camera(cam_x: float, cam_y: float, targets: list) -> Tuple[float, float]:
    if not targets:
        return cam_x, cam_y
    cx = sum(g.x for g in targets) / len(targets)
    cy = sum(g.y for g in targets) / len(targets)
    return clamp_camera(cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)


def _formation_offsets(n: int) -> List[Tuple[float, float]]:
    if n <= 1:
        return [(0.0, 0.0)] * max(1, n)
    r = FORMATION_BASE_R + min(n, 8) * FORMATION_PER_UNIT * 0.15
    return [(math.cos(i * 2 * math.pi / n) * r,
             math.sin(i * 2 * math.pi / n) * r) for i in range(n)]


def _issue_move(selected: list, mx: float, my: float,
                fm: int, attack: bool = False) -> bool:
    alive = [g for g in selected if not g.dead and g.render_capital]
    if not alive:
        return False
    alive.sort(key=lambda g: (g.label, g.class_name))
    offs = _formation_offsets(len(alive))
    pid = _alloc_pace_id()
    for g, (ox, oy) in zip(alive, offs):
        g.set_waypoint(mx + ox, my + oy)
        g.move_pace_key = pid
        g.attack_move = attack
        if not attack:
            g.attack_target = None
    return True


# ── scene class ─────────────────────────────────────────────────────────────

class CombatScene:
    def __init__(self) -> None:
        self._paused = False
        self._hover_menu_btn = False
        self._order_hover: Optional[str] = None
        self._drag_anchor: Optional[Tuple[int, int]] = None
        self._awaiting: Optional[str] = None  # "move", "attack_move", "attack_target"

    # ── update ──────────────────────────────────────────────────────────────

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        if self._paused:
            return None

        keys = pygame.key.get_pressed()
        dx = dy = 0.0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= CAM_PAN_SPEED * dt
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += CAM_PAN_SPEED * dt
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= CAM_PAN_SPEED * dt
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += CAM_PAN_SPEED * dt
        if dx or dy:
            gs.camera.cam_x, gs.camera.cam_y = clamp_camera(
                gs.camera.cam_x + dx, gs.camera.cam_y + dy)

        mp = gs.mp.relay is not None
        if mp:
            self._poll_relay(gs)

        # Client: apply host snapshot, skip local sim
        if mp and not gs.mp.lobby_host:
            return self._client_apply_snapshot(gs)

        # Host or single-player: apply queued remote commands, then step sim
        if mp:
            self._host_apply_commands(gs)

        hooks = CombatSimHooks(on_player_hull_hit=lambda _g: None)
        res: CombatStepResult = step_combat_frame(
            data=gs.data, dt=dt,
            round_idx=gs.round.round_idx,
            mission=gs.combat.mission,
            groups=gs.combat.groups,
            crafts=gs.combat.crafts,
            fog=gs.combat.fog,
            active_pings=gs.combat.active_pings,
            sensor_ghosts=gs.combat.sensor_ghosts,
            ping_ghost_anchor_labels=gs.combat.ping_ghost_anchor_labels,
            seeker_ghosts=gs.combat.seeker_ghosts,
            control_groups=gs.combat.control_groups,
            cg_weapons_free=gs.combat.cg_weapons_free,
            missiles=gs.combat.missiles,
            supplies=gs.combat.supplies,
            vfx_sparks=gs.combat.vfx_sparks,
            vfx_beams=gs.combat.vfx_beams,
            ballistics=gs.combat.ballistics,
            pd_rof_mult=gs.combat.pd_rof_mult,
            hooks=hooks,
            phase=gs.round.phase,
            outcome=gs.round.outcome,
        )

        now_ms = pygame.time.get_ticks()
        gs.tts.last_player_cap_loss_tts, gs.tts.last_enemy_kill_tts = (
            apply_combat_death_audio(
                res.death_audio, gs.audio, now_ms,
                tts_last_player_cap_loss_tts=gs.tts.last_player_cap_loss_tts,
                tts_last_enemy_kill_tts=gs.tts.last_enemy_kill_tts,
                tts_player_cap_loss_gap_ms=TTS_PLAYER_CAP_LOSS_GAP_MS,
                tts_enemy_kill_gap_ms=TTS_ENEMY_KILL_GAP_MS,
            )
        )

        if res.flow:
            f = res.flow
            gs.round.outcome = f.outcome
            gs.round.phase = f.phase
            if f.phase == "debrief":
                gs.debrief.run_total_score += f.run_total_score_add
                gs.combat.salvage[0] += f.salvage_gain
                gs.debrief.last_salvage_gain = f.last_salvage_gain
                return "debrief"
            if f.phase == "gameover":
                return "gameover"

        if mp:
            self._host_broadcast_snapshot(gs)

        return None

    # ── MP sync ──────────────────────────────────────────────────────────────

    def _poll_relay(self, gs: Any) -> None:
        msgs = gs.mp.relay.poll()
        for msg in msgs:
            t = msg.get("t", "")
            if t == COMBAT_CMD and gs.mp.lobby_host:
                gs.mp.host_cmd_queue.append(msg)
            elif t == COMBAT_SNAP and not gs.mp.lobby_host:
                gs.mp.pending_snap = msg

    def _host_apply_commands(self, gs: Any) -> None:
        now_ms = pygame.time.get_ticks()
        pram = [gs.combat.ping_ready_at_ms]
        while gs.mp.host_cmd_queue:
            cmd = gs.mp.host_cmd_queue.pop(0)
            pram[0] = gs.combat.ping_ready_at_ms
            apply_combat_command(
                data=gs.data,
                groups=gs.combat.groups,
                crafts=gs.combat.crafts,
                mission=gs.combat.mission,
                formation_mode_holder=gs.mp.fm_holder,
                active_pings=gs.combat.active_pings,
                sensor_ghosts=gs.combat.sensor_ghosts,
                ping_ghost_anchor_labels=gs.combat.ping_ghost_anchor_labels,
                mission_obstacles=(
                    gs.combat.mission.obstacles if gs.combat.mission else []
                ),
                cg_weapons_free=gs.combat.cg_weapons_free,
                control_groups=gs.combat.control_groups,
                ping_ready_at_ms_holder=pram,
                now_ms=now_ms,
                audio=gs.audio,
                cmd=cmd,
            )
            gs.combat.ping_ready_at_ms = pram[0]

    def _host_broadcast_snapshot(self, gs: Any) -> None:
        now_ms = pygame.time.get_ticks()
        if now_ms - gs.mp.last_snap_send_ms < SNAP_BROADCAST_INTERVAL_MS:
            return
        gs.mp.last_snap_send_ms = now_ms
        gs.mp.combat_tick += 1
        state_dict = snapshot_state(
            tick=gs.mp.combat_tick,
            round_idx=gs.round.round_idx,
            mission=gs.combat.mission,
            groups=gs.combat.groups,
            crafts=gs.combat.crafts,
            missiles=gs.combat.missiles,
            ballistics=gs.combat.ballistics,
            vfx_sparks=gs.combat.vfx_sparks,
            vfx_beams=gs.combat.vfx_beams,
            supplies=gs.combat.supplies,
            pd_rof_mult=gs.combat.pd_rof_mult,
            cg_weapons_free=gs.combat.cg_weapons_free,
            control_groups=gs.combat.control_groups,
            fog=gs.combat.fog,
            active_pings=gs.combat.active_pings,
            sensor_ghosts=gs.combat.sensor_ghosts,
            seeker_ghosts=gs.combat.seeker_ghosts,
            ping_ghost_anchor_labels=gs.combat.ping_ghost_anchor_labels,
            ping_ready_at_ms=gs.combat.ping_ready_at_ms,
            outcome=gs.round.outcome,
            phase=gs.round.phase,
            salvage=float(gs.combat.salvage[0]),
            run_total_score=gs.debrief.run_total_score,
            last_salvage_gain=gs.debrief.last_salvage_gain,
            store_selected=gs.debrief.store_selected,
            store_hover=gs.debrief.store_hover,
        )
        h = hash_state_dict(state_dict)
        gs.mp.relay.send_payload(net_combat_snap(
            tick=gs.mp.combat_tick,
            snap_version=SNAP_VERSION,
            state_hash=h,
            state=state_dict,
        ))

    def _client_apply_snapshot(self, gs: Any) -> Optional[str]:
        snap = gs.mp.pending_snap
        if snap is None:
            return None
        gs.mp.pending_snap = None
        state = snap.get("state", {})
        saved_g, saved_c = _save_selection(gs.combat.groups, gs.combat.crafts)
        result = apply_snapshot_state(
            data=gs.data,
            state=state,
            mission=gs.combat.mission,
            groups=gs.combat.groups,
            crafts=gs.combat.crafts,
            missiles=gs.combat.missiles,
            ballistics=gs.combat.ballistics,
            vfx_sparks=gs.combat.vfx_sparks,
            vfx_beams=gs.combat.vfx_beams,
            supplies=gs.combat.supplies,
            pd_rof_mult=gs.combat.pd_rof_mult,
            cg_weapons_free=gs.combat.cg_weapons_free,
            control_groups=gs.combat.control_groups,
            fog=gs.combat.fog,
            active_pings=gs.combat.active_pings,
            sensor_ghosts=gs.combat.sensor_ghosts,
            seeker_ghosts=gs.combat.seeker_ghosts,
            ping_ghost_anchor_labels=gs.combat.ping_ghost_anchor_labels,
        )
        _restore_selection(saved_g, saved_c)
        tick, outcome, phase, ping_ms, salvage, score, last_sal, st_sel, st_hov = result
        gs.mp.client_last_snap_tick = tick
        gs.round.outcome = outcome
        gs.round.phase = phase
        gs.combat.ping_ready_at_ms = ping_ms
        gs.debrief.run_total_score = score
        gs.debrief.last_salvage_gain = last_sal
        expected = snap.get("state_hash", "")
        if expected:
            actual = hash_state_dict(state)
            if actual != expected:
                gs.mp.desync_until_ms = pygame.time.get_ticks() + 3000
                gs.mp.desync_text = f"Desync at tick {tick}"
        if phase == "debrief":
            return "debrief"
        if phase == "gameover":
            return "gameover"
        return None

    def _send_cmd(self, gs: Any, kind: str, **payload: Any) -> None:
        """Send a combat command to the host. No-op for host and single-player."""
        if gs.mp.relay is None or gs.mp.lobby_host:
            return
        gs.mp.client_cmd_seq += 1
        gs.mp.relay.send_payload(net_combat_cmd(
            tick=max(0, gs.mp.client_last_snap_tick),
            seq=gs.mp.client_cmd_seq,
            kind=kind,
            payload=payload if payload else None,
        ))

    # ── events ──────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._paused = not self._paused
            return None
        if self._paused:
            return self._handle_pause_event(event, gs, ctx)

        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._order_hover = None
            for rect, act, _lab in _order_cells():
                if rect.collidepoint(mx, my):
                    self._order_hover = act

        elif event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = ctx.to_internal(event.pos)
            if my >= VIEW_H:
                return self._handle_hud_click(event, mx, my, gs)
            return self._handle_world_click(event, mx, my, gs)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            if self._drag_anchor and my < VIEW_H:
                ax, ay = self._drag_anchor
                if abs(mx - ax) > 12 or abs(my - ay) > 12:
                    self._box_select(gs, ax, ay, mx, my)
            self._drag_anchor = None

        elif event.type == pygame.KEYDOWN:
            return self._handle_key(event, gs)

        return None

    def _handle_pause_event(self, event: pygame.event.Event,
                            gs: Any, ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover_menu_btn = _pause_btn_rect().collidepoint(mx, my)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            if _pause_btn_rect().collidepoint(mx, my):
                self._paused = False
                return "config"
        return None

    def _handle_world_click(self, event: pygame.event.Event,
                            mx: int, my: int, gs: Any) -> Optional[str]:
        cam_x, cam_y = gs.camera.cam_x, gs.camera.cam_y
        if event.button == 1:
            if self._awaiting in ("attack_target",):
                target = _pick_hostile_at(gs.combat.groups, gs.combat.crafts,
                                          mx, my, cam_x, cam_y)
                if target:
                    sel = _sel_caps(gs)
                    for g in sel:
                        g.attack_target = target
                    gs.audio.play_positive()
                    self._send_cmd(gs, "attack_target_pick",
                                   group_labels=[g.label for g in sel],
                                   cam_x=cam_x, cam_y=cam_y, mx=mx, my=my)
                self._awaiting = None
                return None
            shift = (pygame.key.get_mods() & pygame.KMOD_SHIFT) != 0
            hit = _pick_capital_at(gs.combat.groups, mx, my, cam_x, cam_y)
            if hit:
                if shift:
                    hit.selected = not hit.selected
                else:
                    _set_selection(gs.combat.groups, [hit])
                gs.audio.play_positive()
            else:
                self._drag_anchor = (mx, my)

        elif event.button == 3:
            wpx, wpy = screen_to_world(float(mx), float(my), cam_x, cam_y)
            sel = _sel_caps(gs)
            if self._awaiting == "attack_move":
                _issue_move(sel, wpx, wpy, gs.round.formation_mode, attack=True)
                gs.audio.play_positive()
                self._send_cmd(gs, "move_world",
                               group_labels=[g.label for g in sel],
                               wpx=wpx, wpy=wpy,
                               formation_mode=gs.round.formation_mode,
                               attack_move=True)
                self._awaiting = None
            else:
                target = _pick_hostile_at(gs.combat.groups, gs.combat.crafts,
                                          mx, my, cam_x, cam_y)
                if target:
                    for g in sel:
                        g.attack_target = target
                    gs.audio.play_positive()
                    self._send_cmd(gs, "attack_target_pick",
                                   group_labels=[g.label for g in sel],
                                   cam_x=cam_x, cam_y=cam_y, mx=mx, my=my)
                else:
                    _issue_move(sel, wpx, wpy, gs.round.formation_mode)
                    gs.audio.play_positive()
                    self._send_cmd(gs, "move_world",
                                   group_labels=[g.label for g in sel],
                                   wpx=wpx, wpy=wpy,
                                   formation_mode=gs.round.formation_mode)
        return None

    def _handle_hud_click(self, event: pygame.event.Event,
                          mx: int, my: int, gs: Any) -> Optional[str]:
        if event.button != 1:
            return None
        for rect, act, _lab in _order_cells():
            if rect.collidepoint(mx, my):
                return self._exec_order(act, gs)
        for si in range(CONTROL_GROUP_SLOTS):
            if _cg_slot_rect(si).collidepoint(mx, my):
                labels = gs.combat.control_groups[si]
                if labels:
                    picked = [g for g in gs.combat.groups
                              if g.side == "player" and not g.dead
                              and g.render_capital and g.label in labels]
                    if picked:
                        shift = (pygame.key.get_mods() & pygame.KMOD_SHIFT) != 0
                        if shift:
                            _add_selection(gs.combat.groups, picked)
                        else:
                            _set_selection(gs.combat.groups, picked)
                        gs.audio.play_positive()
                break
        return None

    def _exec_order(self, act: str, gs: Any) -> Optional[str]:
        sel = _sel_caps(gs)
        if act == "move":
            self._awaiting = "move"
            gs.audio.play_positive()
        elif act == "attack_move":
            self._awaiting = "attack_move"
            gs.audio.play_positive()
        elif act == "attack_target":
            self._awaiting = "attack_target"
            gs.audio.play_positive()
        elif act == "hold":
            for g in sel:
                g.waypoint = None
                g.attack_move = False
            gs.audio.play_positive()
            self._send_cmd(gs, "hold",
                           group_labels=[g.label for g in sel])
        elif act == "formation":
            fm = gs.round.formation_mode
            fm = (fm + 1) % 3
            gs.round.formation_mode = fm
            gs.audio.play_positive()
            self._send_cmd(gs, "formation_cycle")
        elif act == "focus":
            targets = sel or [g for g in gs.combat.groups
                              if g.side == "player" and not g.dead and g.render_capital]
            gs.camera.cam_x, gs.camera.cam_y = _focus_camera(
                gs.camera.cam_x, gs.camera.cam_y, targets)
            gs.audio.play_positive()
        elif act == "ping":
            from demo_game import spawn_active_sensor_pings, ACTIVE_PING_COOLDOWN
            now = pygame.time.get_ticks()
            if now >= gs.combat.ping_ready_at_ms:
                spawn_active_sensor_pings(
                    gs.combat.groups, gs.combat.crafts,
                    gs.combat.active_pings, gs.combat.sensor_ghosts,
                    gs.combat.mission.obstacles,
                    random.Random(now % 100003),
                    anchor_labels=gs.combat.ping_ghost_anchor_labels,
                )
                gs.combat.ping_ready_at_ms = now + int(ACTIVE_PING_COOLDOWN * 1000)
                gs.audio.play_positive()
                self._send_cmd(gs, "sensor_ping", rng_seed=now % 100003)
            else:
                gs.audio.play_negative()
        return None

    def _handle_key(self, event: pygame.event.Event, gs: Any) -> Optional[str]:
        key = event.key
        mods = event.mod

        if key == pygame.K_SPACE:
            targets = _sel_caps(gs) or [
                g for g in gs.combat.groups
                if g.side == "player" and not g.dead and g.render_capital]
            gs.camera.cam_x, gs.camera.cam_y = _focus_camera(
                gs.camera.cam_x, gs.camera.cam_y, targets)

        elif key == pygame.K_TAB:
            gs.round.formation_mode = (gs.round.formation_mode + 1) % 3
            gs.audio.play_positive()
            self._send_cmd(gs, "formation_cycle")

        elif key == pygame.K_h:
            sel = _sel_caps(gs)
            for g in sel:
                g.waypoint = None
                g.attack_move = False
            gs.audio.play_positive()
            self._send_cmd(gs, "hold",
                           group_labels=[g.label for g in sel])

        elif key == pygame.K_g:
            self._awaiting = "attack_move"
            gs.audio.play_positive()

        elif key == pygame.K_f:
            self._awaiting = "attack_target"
            gs.audio.play_positive()

        elif pygame.K_1 <= key <= pygame.K_9:
            slot = key - pygame.K_1
            if slot < CONTROL_GROUP_SLOTS:
                if mods & pygame.KMOD_CTRL:
                    sel_labels = [g.label for g in _sel_caps(gs)]
                    if sel_labels:
                        gs.combat.control_groups[slot] = sel_labels
                        gs.audio.play_positive()
                        self._send_cmd(gs, "control_assign",
                                       slot=slot, labels=sel_labels)
                else:
                    labels = gs.combat.control_groups[slot]
                    if labels:
                        picked = [g for g in gs.combat.groups
                                  if g.side == "player" and not g.dead
                                  and g.render_capital and g.label in labels]
                        if picked:
                            _set_selection(gs.combat.groups, picked)
                            gs.audio.play_positive()

        return None

    def _box_select(self, gs: Any, x0: int, y0: int, x1: int, y1: int) -> None:
        left, right = min(x0, x1), max(x0, x1)
        top, bottom = min(y0, y1), max(y0, y1)
        cam_x, cam_y = gs.camera.cam_x, gs.camera.cam_y
        picked = []
        for g in gs.combat.groups:
            if g.side != "player" or g.dead or not g.render_capital:
                continue
            sx, sy, _ = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
            if left <= sx <= right and top <= sy <= bottom:
                picked.append(g)
        shift = (pygame.key.get_mods() & pygame.KMOD_SHIFT) != 0
        if picked:
            if shift:
                _add_selection(gs.combat.groups, picked)
            else:
                _set_selection(gs.combat.groups, picked)
            gs.audio.play_positive()

    # ── draw ────────────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        view = screen.subsurface(pygame.Rect(0, 0, VIEW_W, VIEW_H))
        draw_battle_world(view, gs, show_fog=True)

        if self._drag_anchor:
            mx, my = ctx.to_internal(pygame.mouse.get_pos())
            ax, ay = self._drag_anchor
            r = pygame.Rect(min(ax, mx), min(ay, my), abs(mx - ax), abs(my - ay))
            if r.w > 8 or r.h > 8:
                pygame.draw.rect(view, SELECT_YELLOW, r, width=1)

        bar_rect = pygame.Rect(0, VIEW_H, WIDTH, BOTTOM_BAR_H)
        pygame.draw.rect(screen, BG_DEEP, bar_rect)
        pygame.draw.line(screen, BORDER_PANEL, (0, VIEW_H), (WIDTH, VIEW_H), 2)

        self._draw_control_groups(screen, gs)
        self._draw_status_text(screen, gs)
        self._draw_order_panel(screen, gs)

        if self._awaiting:
            hint = gs.fonts.main.render(
                f"Click to issue: {self._awaiting.replace('_', ' ')} (RMB to cancel)",
                True, TEXT_ACCENT)
            screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, VIEW_H - 24))

        if gs.mp.relay is not None and gs.mp.desync_until_ms > pygame.time.get_ticks():
            dt = gs.fonts.tiny.render(gs.mp.desync_text, True, ACCENT_RED)
            screen.blit(dt, (WIDTH // 2 - dt.get_width() // 2, 8))

        if gs.mp.relay is not None:
            role = "HOST" if gs.mp.lobby_host else "CLIENT"
            ri = gs.fonts.micro.render(role, True, TEXT_DIM)
            screen.blit(ri, (WIDTH - ri.get_width() - 8, 4))

        if self._paused:
            self._draw_pause(screen, gs)

    def _draw_control_groups(self, screen: pygame.Surface, gs: Any) -> None:
        for i in range(CONTROL_GROUP_SLOTS):
            r = _cg_slot_rect(i)
            pygame.draw.rect(screen, (26, 38, 54), r, border_radius=4)
            pygame.draw.rect(screen, (72, 98, 126), r, width=1, border_radius=4)
            num = gs.fonts.micro.render(str(i + 1), True, (200, 210, 225))
            screen.blit(num, (r.x + 4, r.y + 2))
            labs = gs.combat.control_groups[i]
            if labs:
                short = (labs[0] if len(labs) == 1 else f"{labs[0]}+{len(labs)-1}")[:10]
                t = gs.fonts.micro.render(short, True, (155, 180, 205))
                screen.blit(t, (r.x + 4, r.y + 16))

    def _draw_status_text(self, screen: pygame.Surface, gs: Any) -> None:
        x0 = _cg_slot_rect(CONTROL_GROUP_SLOTS - 1).right + 14
        fm_name = FORMATION_MODE_NAMES[gs.round.formation_mode]
        line1 = (f"Round {gs.round.round_idx}  |  {fm_name}"
                 f"  |  Salvage {gs.combat.salvage[0]}"
                 f"  |  Supplies {gs.combat.supplies[0]:.0f}")
        st1 = gs.fonts.tiny.render(line1, True, TEXT_SECONDARY)
        screen.blit(st1, (x0, VIEW_H + 14))

        if gs.combat.mission:
            m = gs.combat.mission
            if m.kind == "strike":
                obj = m.objective
                if obj and not obj.dead:
                    line2 = f"STRIKE -- relay {obj.hp:.0f}/{obj.max_hp:.0f}"
                else:
                    line2 = "STRIKE -- destroy relay"
            elif m.kind == "pvp":
                line2 = "PVP -- eliminate enemy fleets"
            else:
                line2 = f"SALVAGE -- pods {m.pods_collected}/{len(m.pods)} (need {m.pods_required})"
            st2 = gs.fonts.micro.render(line2, True, TEXT_DIM)
            screen.blit(st2, (x0, VIEW_H + 36))

    def _draw_order_panel(self, screen: pygame.Surface, gs: Any) -> None:
        r = _order_panel_rect()
        pygame.draw.rect(screen, BG_PANEL, r)
        pygame.draw.rect(screen, BORDER_PANEL, r, width=1)
        title = gs.fonts.tiny.render("ORDERS", True, TEXT_ACCENT)
        screen.blit(title, (r.x + 6, r.y + 2))

        for rect, act, lab in _order_cells():
            hot = self._order_hover == act
            fill = BTN_FILL_HOT if hot else BTN_FILL
            border = BORDER_BTN_HOT if hot else BORDER_BTN
            pygame.draw.rect(screen, fill, rect, border_radius=4)
            pygame.draw.rect(screen, border, rect, width=1, border_radius=4)
            t = gs.fonts.micro.render(lab, True, TEXT_PRIMARY)
            screen.blit(t, (rect.x + 4, rect.centery - t.get_height() // 2))

    def _draw_pause(self, screen: pygame.Surface, gs: Any) -> None:
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((12, 18, 32, 230))
        screen.blit(ov, (0, 0))
        title = gs.fonts.big.render("PAUSED", True, TEXT_PRIMARY)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 100))
        hint = gs.fonts.main.render("ESC -- resume", True, TEXT_SECONDARY)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT // 2 - 60))
        draw_button(screen, _pause_btn_rect(), "Main Menu", gs.fonts.main,
                    hot=self._hover_menu_btn)
