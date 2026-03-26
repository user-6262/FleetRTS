"""In-lobby scene — player list, fleet design, ready/start, chat, relay polling.

Handles the full relay protocol: unwraps {"t":"relay","body":{...}} envelopes,
exchanges fleet designs via lobby_loadout, and bootstraps MP combat on start_match.
"""
from __future__ import annotations

import os
import random as _rng
from typing import Any, Dict, List, Optional

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, TEXT_WARN, ACCENT_GREEN, ACCENT_RED,
    WIDTH, HEIGHT,
    blit_menu_background, draw_panel, draw_button, draw_text_field,
)
from scenes import RunContext

try:
    from mp_combat_bootstrap import bootstrap_mp_combat_match, ensure_mp_player_setup_designs
    from net.app_messages import (
        lobby_ready, lobby_chat, lobby_loadout, lobby_presence,
        start_match, host_config,
    )
    from net.combat_net import COMBAT_CMD, COMBAT_SNAP
except ImportError:
    from core.mp_combat_bootstrap import bootstrap_mp_combat_match, ensure_mp_player_setup_designs
    from core.net.app_messages import (
        lobby_ready, lobby_chat, lobby_loadout, lobby_presence,
        start_match, host_config,
    )
    from core.net.combat_net import COMBAT_CMD, COMBAT_SNAP

CHAT_X = 40
CHAT_Y = 300
CHAT_W = WIDTH - 80
CHAT_H = 260
CHAT_INPUT_H = 32
MAX_CHAT_LINES = 14

RELAY_DEFAULT_PORT = 8766


class MpLobbyScene:
    def __init__(self) -> None:
        self._hover: Optional[str] = None
        self._relay_connected = False
        self._title_short: Optional[str] = None
        self._title_surf: Optional[pygame.Surface] = None
        self._cache_players_label: Optional[pygame.Surface] = None
        self._cache_chat_hdr: Optional[pygame.Surface] = None
        self._cache_settings_hdr: Optional[pygame.Surface] = None
        self._cache_hint: Optional[pygame.Surface] = None
        self._pl_snapshot: Optional[tuple] = None
        self._pl_rows_main: List[pygame.Surface] = []
        self._pl_rows_ready: List[pygame.Surface] = []
        self._chat_key: tuple[str, ...] = ()
        self._chat_surfs: List[pygame.Surface] = []

    def _back_rect(self) -> pygame.Rect:
        return pygame.Rect(20, HEIGHT - 70, 120, 48)

    def _ready_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 100, HEIGHT - 70, 200, 48)

    def _start_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 + 120, HEIGHT - 70, 160, 48)

    def _fleet_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH - 200, HEIGHT - 70, 160, 48)

    def _chat_input_rect(self) -> pygame.Rect:
        return pygame.Rect(CHAT_X, CHAT_Y + CHAT_H + 6, CHAT_W, CHAT_INPUT_H)

    # ── update ──────────────────────────────────────────────────────────────

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        if gs.mp.relay is not None:
            msgs = gs.mp.relay.poll()
            for msg in msgs:
                mt = msg.get("t", "")
                if mt == "joined":
                    you = msg.get("you")
                    prev_players = gs.mp.remote_relay_players
                    prev_n = len(prev_players)
                    if isinstance(you, str) and you.strip():
                        new_n = you.strip()[:64]
                        old_n = gs.mp.player_name
                        if new_n != old_n:
                            if old_n in gs.mp.player_fleet_designs:
                                gs.mp.player_fleet_designs[new_n] = gs.mp.player_fleet_designs.pop(
                                    old_n)
                            if old_n in gs.mp.remote_player_colors:
                                gs.mp.remote_player_colors[new_n] = gs.mp.remote_player_colors.pop(
                                    old_n)
                        gs.mp.player_name = new_n
                        gs.mp.name_buffer = new_n
                    gs.mp.remote_relay_players = list(msg.get("players") or [])
                    new_n_players = len(gs.mp.remote_relay_players)
                    # Only our first join or when someone new enters needs a full state push.
                    announce = bool(you and str(you).strip()) or new_n_players > prev_n
                    if announce:
                        gs.mp.relay.send_payload(lobby_ready(gs.mp.ready))
                        gs.mp.relay.send_payload(lobby_presence(
                            in_fleet_design=False, color_id=gs.mp.player_color_id))
                        design = self._my_fleet_design(gs)
                        if design:
                            gs.mp.relay.send_payload(lobby_loadout(payload={"fleet": design}))
                elif mt == "peer_left":
                    gs.mp.remote_relay_players = list(msg.get("players") or [])
                    left = str(msg.get("player") or "")
                    if left:
                        gs.mp.remote_ready.pop(left, None)
                        gs.mp.player_fleet_designs.pop(left, None)
                elif mt == "relay":
                    body = msg.get("body")
                    if isinstance(body, dict):
                        result = self._on_relay_body(body, msg, gs)
                        if result is not None:
                            return result
                elif mt == "error":
                    gs.mp.net_err = str(msg.get("message", "relay error"))

            if gs.mp.relay.error:
                gs.mp.net_err = gs.mp.relay.error
                gs.mp.relay.close()
                gs.mp.relay = None
                self._relay_connected = False

        if not self._relay_connected and gs.mp.remote_lobby_id:
            self._connect_relay(gs)
        return None

    def _on_relay_body(self, body: dict, msg: dict, gs: Any) -> Optional[str]:
        bt = body.get("t", "")
        sender = str(msg.get("from") or "?")

        if bt == "lobby_chat":
            txt = str(body.get("text") or "")[:240]
            gs.mp.chat_log.append(f"{sender}: {txt}")
        elif bt == "lobby_ready":
            gs.mp.remote_ready[sender] = bool(body.get("v"))
        elif bt == "lobby_presence":
            gs.mp.remote_player_colors[sender] = int(
                max(0, min(int(body.get("color_id", 0)), 5)))
        elif bt == "lobby_loadout":
            payload = body.get("payload") or {}
            fleet_rows = payload.get("fleet") if isinstance(payload, dict) else None
            if isinstance(fleet_rows, list):
                cleaned: List[Dict[str, str]] = []
                for row in fleet_rows[:24]:
                    if isinstance(row, dict):
                        cleaned.append({
                            "class_name": str(row.get("class_name") or "")[:48],
                            "label": str(row.get("label") or "")[:48],
                        })
                gs.mp.player_fleet_designs[sender] = cleaned
        elif bt == "host_config":
            if not gs.mp.lobby_host:
                gs.mp.mode_coop = bool(body.get("coop", gs.mp.mode_coop))
                gs.mp.use_asteroids = bool(body.get("use_asteroids", gs.mp.use_asteroids))
                ep = int(body.get("enemy_pressure", gs.mp.enemy_pressure))
                gs.mp.enemy_pressure = max(0, min(ep, 3))
        elif bt == "start_match":
            gen = int(body.get("generation", 0))
            if gen > gs.mp.applied_remote_start_gen:
                gs.mp.applied_remote_start_gen = gen
                gs.mp.round_idx = int(body.get("round_idx", gs.mp.round_idx))
                gs.mp.use_asteroids = bool(body.get("use_asteroids", gs.mp.use_asteroids))
                gs.mp.mode_coop = bool(body.get("coop", True))
                ep = int(body.get("enemy_pressure", gs.mp.enemy_pressure))
                gs.mp.enemy_pressure = max(0, min(ep, 3))
                seed = body.get("seed")
                match_seed = int(seed) if seed is not None else None
                psetup = body.get("player_setup")
                return self._launch_combat(
                    gs, match_seed, psetup if isinstance(psetup, dict) else None)
        return None

    # ── relay connect ───────────────────────────────────────────────────────

    def _connect_relay(self, gs: Any) -> None:
        try:
            from net.relay_client import RelayClient
        except ImportError:
            from core.net.relay_client import RelayClient
        rh = (gs.mp.relay_host or "").strip() or os.environ.get(
            "FLEETRTS_RELAY_HOST", "127.0.0.1")
        if gs.mp.relay_port is not None:
            try:
                rp = int(gs.mp.relay_port)
            except (TypeError, ValueError):
                rp = int(os.environ.get("FLEETRTS_RELAY_PORT", str(RELAY_DEFAULT_PORT)))
        else:
            rp = int(os.environ.get("FLEETRTS_RELAY_PORT", str(RELAY_DEFAULT_PORT)))
        gs.mp.relay = RelayClient(rh, rp, str(gs.mp.remote_lobby_id or ""), gs.mp.player_name)
        gs.mp.relay.connect()
        self._relay_connected = True

    def _disconnect(self, gs: Any) -> None:
        base = gs.mp.fleet_http_base
        lid = gs.mp.remote_lobby_id
        leave_name = (gs.mp.http_lobby_player_name or gs.mp.player_name or "").strip()
        if base and lid and leave_name:
            try:
                from net.http_client import leave_lobby
            except ImportError:
                from core.net.http_client import leave_lobby
            try:
                leave_lobby(base, str(lid), leave_name)
            except Exception:
                pass
        if gs.mp.relay:
            gs.mp.relay.close()
            gs.mp.relay = None
        self._relay_connected = False
        gs.mp.remote_lobby_id = None
        gs.mp.remote_lobby_short = None
        gs.mp.relay_host = None
        gs.mp.relay_port = None
        gs.mp.http_lobby_player_name = None
        gs.mp.remote_relay_players.clear()
        gs.mp.remote_ready.clear()
        gs.mp.player_fleet_designs.clear()
        gs.mp.remote_player_colors.clear()
        gs.mp.chat_log.clear()
        gs.mp.chat_input = ""
        gs.mp.chat_focus = False
        gs.mp.net_err = None
        gs.mp.ready = False
        gs.mp.match_generation = 0
        gs.mp.applied_remote_start_gen = 0
        self._title_short = None
        self._title_surf = None
        self._pl_snapshot = None
        self._pl_rows_main = []
        self._pl_rows_ready = []
        self._chat_key = ()

    # ── fleet design helpers ────────────────────────────────────────────────

    def _my_fleet_design(self, gs: Any) -> list:
        stored = gs.mp.player_fleet_designs.get(gs.mp.player_name)
        if stored:
            return stored
        rows = []
        for g in gs.combat.groups:
            if g.side == "player" and g.render_capital and not g.dead:
                rows.append({"class_name": g.class_name, "label": g.label})
        return rows

    def _all_others_ready(self, gs: Any) -> bool:
        others = [p for p in gs.mp.remote_relay_players if p != gs.mp.player_name]
        if not others:
            return True
        return all(gs.mp.remote_ready.get(p, False) for p in others)

    # ── combat launch ───────────────────────────────────────────────────────

    def _launch_combat(self, gs: Any, match_seed: Optional[int] = None,
                       player_setup: Optional[dict] = None) -> str:
        gs.mp.post_combat_phase = "mp_lobby"
        gs.mp.combat_tick = 0
        gs.mp.host_cmd_queue.clear()
        gs.mp.pending_snap = None
        gs.mp.client_last_snap_tick = -1
        gs.mp.last_snap_send_ms = 0
        gs.mp.desync_text = ""
        gs.mp.host_snap_tick = -1
        gs.mp.ready = False
        gs.round.round_idx = gs.mp.round_idx

        if player_setup is None:
            all_players = list(gs.mp.remote_relay_players or [gs.mp.player_name])
            if gs.mp.player_name not in all_players:
                all_players.append(gs.mp.player_name)
            designs = dict(gs.mp.player_fleet_designs)
            my_design = self._my_fleet_design(gs)
            if my_design:
                designs[gs.mp.player_name] = my_design
            colors: Dict[str, int] = {gs.mp.player_name: gs.mp.player_color_id}
            colors.update(gs.mp.remote_player_colors)
            player_setup = {
                "players": all_players,
                "colors": colors,
                "designs": designs,
            }

        mission = bootstrap_mp_combat_match(
            data=gs.data,
            round_idx=gs.mp.round_idx,
            match_seed=match_seed,
            use_asteroids=gs.mp.use_asteroids,
            enemy_pressure=gs.mp.enemy_pressure,
            groups=gs.combat.groups,
            crafts=gs.combat.crafts,
            player_setup=player_setup,
            mp_pvp=not gs.mp.mode_coop,
            control_groups=gs.combat.control_groups,
            cg_weapons_free=gs.combat.cg_weapons_free,
        )
        gs.combat.mission = mission
        gs.round.outcome = None
        gs.round.phase = "combat"

        if getattr(mission, "mp_pvp", False):
            owners = sorted({
                str(getattr(g, "owner_id", "")).strip()
                for g in gs.combat.groups
                if g.side == "player" and str(getattr(g, "owner_id", "")).strip()
            })
            mission.pvp_scrap = {o: 0 for o in owners}
            mission.pvp_territory = {}
            mission.pvp_battlegroups = {}

        from draw import clamp_camera, VIEW_W, VIEW_H
        own = [g for g in gs.combat.groups
               if g.side == "player" and not g.dead and g.render_capital
               and getattr(g, "owner_id", "") == gs.mp.player_name]
        if not own:
            own = [g for g in gs.combat.groups
                   if g.side == "player" and not g.dead and g.render_capital]
        if own:
            cx = sum(g.x for g in own) / len(own)
            cy = sum(g.y for g in own) / len(own)
            gs.camera.cam_x, gs.camera.cam_y = clamp_camera(
                cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)

        gs.audio.play_positive()
        return "combat"

    # ── events ──────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover = None
            if self._back_rect().collidepoint(mx, my):
                self._hover = "back"
            elif self._ready_rect().collidepoint(mx, my):
                self._hover = "ready"
            elif self._start_rect().collidepoint(mx, my):
                self._hover = "start"
            elif self._fleet_rect().collidepoint(mx, my):
                self._hover = "fleet"

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            gs.mp.chat_focus = self._chat_input_rect().collidepoint(mx, my)

            if self._back_rect().collidepoint(mx, my):
                gs.audio.play_positive()
                self._disconnect(gs)
                return "mp_hub"

            if self._ready_rect().collidepoint(mx, my):
                gs.mp.ready = not gs.mp.ready
                if gs.mp.relay:
                    gs.mp.relay.send_payload(lobby_ready(gs.mp.ready))
                    design = self._my_fleet_design(gs)
                    if design:
                        gs.mp.relay.send_payload(lobby_loadout(payload={"fleet": design}))
                gs.audio.play_positive()

            if self._start_rect().collidepoint(mx, my) and gs.mp.lobby_host:
                if self._all_others_ready(gs):
                    all_players = list(gs.mp.remote_relay_players or [gs.mp.player_name])
                    if gs.mp.player_name not in all_players:
                        all_players.append(gs.mp.player_name)
                    designs = dict(gs.mp.player_fleet_designs)
                    my_design = self._my_fleet_design(gs)
                    if my_design:
                        designs[gs.mp.player_name] = my_design
                    colors: Dict[str, int] = {gs.mp.player_name: gs.mp.player_color_id}
                    colors.update(gs.mp.remote_player_colors)
                    psetup = {
                        "players": all_players,
                        "colors": colors,
                        "designs": designs,
                    }
                    ensure_mp_player_setup_designs(gs.data, psetup)
                    gs.mp.match_generation += 1
                    seed = _rng.randint(0, 2**31)
                    if gs.mp.relay:
                        gs.mp.relay.send_payload(start_match(
                            generation=gs.mp.match_generation,
                            seed=seed,
                            round_idx=gs.mp.round_idx,
                            coop=gs.mp.mode_coop,
                            use_asteroids=gs.mp.use_asteroids,
                            enemy_pressure=gs.mp.enemy_pressure,
                            player_setup=psetup,
                        ))
                    return self._launch_combat(gs, seed, psetup)
                else:
                    gs.audio.play_negative()

            if self._fleet_rect().collidepoint(mx, my):
                gs.audio.play_positive()
                gs.mp.loadouts_active = True
                return "ship_loadouts"

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._disconnect(gs)
                return "mp_hub"
            if gs.mp.chat_focus:
                if event.key == pygame.K_BACKSPACE:
                    gs.mp.chat_input = gs.mp.chat_input[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    text = gs.mp.chat_input.strip()
                    if text and gs.mp.relay:
                        gs.mp.relay.send_payload(lobby_chat(text))
                        gs.mp.chat_log.append(f"{gs.mp.player_name}: {text}")
                    gs.mp.chat_input = ""
                elif event.unicode and len(gs.mp.chat_input) < 200:
                    gs.mp.chat_input += event.unicode
        return None

    # ── draw ────────────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        blit_menu_background(screen, WIDTH, HEIGHT)

        short = gs.mp.remote_lobby_short or gs.mp.remote_lobby_id or "?"
        if self._title_short != short or self._title_surf is None:
            self._title_short = short
            self._title_surf = gs.fonts.big.render(f"LOBBY  [{short}]", True, TEXT_ACCENT)
        screen.blit(self._title_surf, (40, 20))

        role = "HOST" if gs.mp.lobby_host else "CLIENT"
        role_t = gs.fonts.tiny.render(role, True, ACCENT_GREEN if gs.mp.lobby_host else TEXT_SECONDARY)
        screen.blit(role_t, (40, 52))

        mode = "Co-op" if gs.mp.mode_coop else "PvP"
        mode_t = gs.fonts.tiny.render(f"Mode: {mode}", True, TEXT_PRIMARY)
        screen.blit(mode_t, (140, 52))

        # Player list (rebuild cached column when roster / ready / fleets change)
        if self._cache_players_label is None:
            self._cache_players_label = gs.fonts.main.render("PLAYERS", True, TEXT_ACCENT)
        screen.blit(self._cache_players_label, (40, 80))
        all_players = gs.mp.remote_relay_players or [gs.mp.player_name]
        pl_key = (
            tuple(all_players),
            gs.mp.player_name,
            gs.mp.ready,
            tuple((p, gs.mp.remote_ready.get(p, False)) for p in all_players),
            tuple((p, p in gs.mp.player_fleet_designs) for p in all_players),
        )
        if pl_key != self._pl_snapshot:
            self._pl_snapshot = pl_key
            self._pl_rows_main = []
            self._pl_rows_ready = []
            for pname in all_players:
                is_self = pname == gs.mp.player_name
                is_ready = gs.mp.remote_ready.get(pname, False) or (is_self and gs.mp.ready)
                has_fleet = pname in gs.mp.player_fleet_designs
                ready_col = ACCENT_GREEN if is_ready else TEXT_DIM
                ready_lbl = "READY" if is_ready else "..."
                fleet_lbl = " [fleet]" if has_fleet else ""
                self._pl_rows_main.append(
                    gs.fonts.main.render(f"  {pname}{fleet_lbl}", True, TEXT_PRIMARY))
                self._pl_rows_ready.append(
                    gs.fonts.tiny.render(ready_lbl, True, ready_col))
        y = 108
        for pt, rt in zip(self._pl_rows_main, self._pl_rows_ready):
            screen.blit(pt, (50, y))
            screen.blit(rt, (340, y + 2))
            y += 26

        # Settings panel (host only)
        if gs.mp.lobby_host:
            sp = pygame.Rect(WIDTH - 340, 80, 300, 180)
            draw_panel(screen, sp)
            if self._cache_settings_hdr is None:
                self._cache_settings_hdr = gs.fonts.main.render("SETTINGS", True, TEXT_ACCENT)
            screen.blit(self._cache_settings_hdr, (sp.x + 12, sp.y + 8))
            mt = gs.fonts.tiny.render(f"Mode: {mode}", True, TEXT_PRIMARY)
            screen.blit(mt, (sp.x + 12, sp.y + 40))
            at = gs.fonts.tiny.render(
                f"Authority: {gs.mp.lobby_authoritative}", True, TEXT_PRIMARY)
            screen.blit(at, (sp.x + 12, sp.y + 62))

        # Chat panel
        chat_panel = pygame.Rect(CHAT_X - 4, CHAT_Y - 4, CHAT_W + 8, CHAT_H + CHAT_INPUT_H + 18)
        draw_panel(screen, chat_panel)
        if self._cache_chat_hdr is None:
            self._cache_chat_hdr = gs.fonts.tiny.render("CHAT", True, TEXT_ACCENT)
        screen.blit(self._cache_chat_hdr, (CHAT_X, CHAT_Y - 2))
        visible = gs.mp.chat_log[-MAX_CHAT_LINES:]
        chat_key = tuple(visible)
        if chat_key != self._chat_key:
            self._chat_key = chat_key
            self._chat_surfs = [
                gs.fonts.micro.render(line[:100], True, TEXT_PRIMARY) for line in visible
            ]
        cy = CHAT_Y + 16
        for ct in self._chat_surfs:
            screen.blit(ct, (CHAT_X + 4, cy))
            cy += 16
        draw_text_field(screen, self._chat_input_rect(), gs.mp.chat_input,
                        gs.fonts.main, active=gs.mp.chat_focus, placeholder="Type a message...")

        if gs.mp.net_err:
            err = gs.fonts.tiny.render(f"Error: {gs.mp.net_err[:60]}", True, ACCENT_RED)
            screen.blit(err, (40, HEIGHT - 120))

        # Buttons
        draw_button(screen, self._back_rect(), "Leave", gs.fonts.main,
                    hot=self._hover == "back")

        ready_label = "READY" if not gs.mp.ready else "NOT READY"
        draw_button(screen, self._ready_rect(), ready_label, gs.fonts.main,
                    hot=self._hover == "ready",
                    accent=ACCENT_GREEN if not gs.mp.ready else ACCENT_RED)

        if gs.mp.lobby_host:
            can_start = self._all_others_ready(gs)
            start_accent = ACCENT_GREEN if can_start else BORDER_BTN
            draw_button(screen, self._start_rect(), "START", gs.fonts.main,
                        hot=self._hover == "start", accent=start_accent)

        draw_button(screen, self._fleet_rect(), "FLEET", gs.fonts.main,
                    hot=self._hover == "fleet")

        if self._cache_hint is None:
            self._cache_hint = gs.fonts.micro.render(
                "ESC -- leave  |  ENTER to chat  |  FLEET to design ships", True, TEXT_DIM)
        screen.blit(self._cache_hint, (WIDTH // 2 - self._cache_hint.get_width() // 2, HEIGHT - 20))
