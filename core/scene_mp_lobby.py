"""In-lobby scene — settings, player list, chat, ready/start, relay polling."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, TEXT_WARN, ACCENT_GREEN, ACCENT_RED,
    WIDTH, HEIGHT,
    draw_starfield, draw_world_edge, draw_panel, draw_button, draw_text_field,
)
from scenes import RunContext

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

    def _back_rect(self) -> pygame.Rect:
        return pygame.Rect(20, HEIGHT - 70, 120, 48)

    def _ready_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 100, HEIGHT - 70, 200, 48)

    def _start_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 + 120, HEIGHT - 70, 160, 48)

    def _chat_input_rect(self) -> pygame.Rect:
        return pygame.Rect(CHAT_X, CHAT_Y + CHAT_H + 6, CHAT_W, CHAT_INPUT_H)

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        # Poll relay if connected
        if gs.mp.relay is not None:
            msgs = gs.mp.relay.poll()
            for msg in msgs:
                t = msg.get("t", "")
                if t == "chat":
                    sender = msg.get("from", "?")
                    text = msg.get("text", "")
                    gs.mp.chat_log.append(f"{sender}: {text}")
                elif t == "ready":
                    who = msg.get("player", "?")
                    gs.mp.remote_ready[who] = msg.get("ready", False)
                elif t == "start_match":
                    gs.mp.match_generation = msg.get("gen", gs.mp.match_generation + 1)
                    return self._launch_combat(gs)
                elif t == "players":
                    gs.mp.remote_relay_players = msg.get("list", [])

            if gs.mp.relay.error:
                gs.mp.net_err = gs.mp.relay.error
                gs.mp.relay.close()
                gs.mp.relay = None
                self._relay_connected = False

        # Auto-connect relay
        if not self._relay_connected and gs.mp.remote_lobby_id:
            self._connect_relay(gs)
        return None

    def _connect_relay(self, gs: Any) -> None:
        try:
            from net.relay_client import RelayClient
        except ImportError:
            from core.net.relay_client import RelayClient
        host = os.environ.get("FLEETRTS_RELAY_HOST", "127.0.0.1")
        port = int(os.environ.get("FLEETRTS_RELAY_PORT", str(RELAY_DEFAULT_PORT)))
        gs.mp.relay = RelayClient(host, port, gs.mp.remote_lobby_id, gs.mp.player_name)
        gs.mp.relay.connect()
        self._relay_connected = True

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
                    from net.app_messages import lobby_ready
                    gs.mp.relay.send_payload(lobby_ready(gs.mp.ready))
                gs.audio.play_positive()
            if self._start_rect().collidepoint(mx, my) and gs.mp.lobby_host:
                gs.audio.play_positive()
                if gs.mp.relay:
                    import random as _rng
                    from net.app_messages import start_match
                    gs.mp.match_generation += 1
                    gs.mp.relay.send_payload(start_match(
                        generation=gs.mp.match_generation,
                        seed=_rng.randint(0, 2**31),
                        round_idx=gs.mp.round_idx,
                        coop=gs.mp.mode_coop,
                        use_asteroids=gs.mp.use_asteroids,
                        enemy_pressure=gs.mp.enemy_pressure,
                    ))
                return self._launch_combat(gs)

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
                        from net.app_messages import lobby_chat
                        gs.mp.relay.send_payload(lobby_chat(text))
                        gs.mp.chat_log.append(f"{gs.mp.player_name}: {text}")
                    gs.mp.chat_input = ""
                elif event.unicode and len(gs.mp.chat_input) < 200:
                    gs.mp.chat_input += event.unicode
        return None

    def _disconnect(self, gs: Any) -> None:
        if gs.mp.relay:
            gs.mp.relay.close()
            gs.mp.relay = None
        self._relay_connected = False

    def _launch_combat(self, gs: Any) -> str:
        gs.mp.post_combat_phase = "mp_lobby"
        gs.mp.loadouts_active = True
        return "ship_loadouts"

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        screen.fill(BG_DEEP)
        draw_starfield(screen, gs.stars, gs.camera.cam_x, gs.camera.cam_y, WIDTH, HEIGHT)

        short = gs.mp.remote_lobby_short or gs.mp.remote_lobby_id or "?"
        title = gs.fonts.big.render(f"LOBBY  [{short}]", True, TEXT_ACCENT)
        screen.blit(title, (40, 20))

        role = "HOST" if gs.mp.lobby_host else "CLIENT"
        role_t = gs.fonts.tiny.render(role, True, ACCENT_GREEN if gs.mp.lobby_host else TEXT_SECONDARY)
        screen.blit(role_t, (40, 52))

        # Player list
        players_label = gs.fonts.main.render("PLAYERS", True, TEXT_ACCENT)
        screen.blit(players_label, (40, 80))
        y = 108
        all_players = gs.mp.remote_relay_players or [gs.mp.player_name]
        for pname in all_players:
            is_ready = gs.mp.remote_ready.get(pname, False) or (pname == gs.mp.player_name and gs.mp.ready)
            ready_col = ACCENT_GREEN if is_ready else TEXT_DIM
            ready_lbl = "READY" if is_ready else "..."
            pt = gs.fonts.main.render(f"  {pname}", True, TEXT_PRIMARY)
            rt = gs.fonts.tiny.render(ready_lbl, True, ready_col)
            screen.blit(pt, (50, y))
            screen.blit(rt, (300, y + 2))
            y += 26

        # Settings panel (host only)
        if gs.mp.lobby_host:
            sp = pygame.Rect(WIDTH - 340, 80, 300, 180)
            draw_panel(screen, sp)
            sh = gs.fonts.main.render("SETTINGS", True, TEXT_ACCENT)
            screen.blit(sh, (sp.x + 12, sp.y + 8))
            mode = "Co-op" if gs.mp.mode_coop else "PvP"
            mt = gs.fonts.tiny.render(f"Mode: {mode}", True, TEXT_PRIMARY)
            screen.blit(mt, (sp.x + 12, sp.y + 40))
            at = gs.fonts.tiny.render(
                f"Authority: {gs.mp.lobby_authoritative}", True, TEXT_PRIMARY)
            screen.blit(at, (sp.x + 12, sp.y + 62))

        # Chat panel
        chat_panel = pygame.Rect(CHAT_X - 4, CHAT_Y - 4, CHAT_W + 8, CHAT_H + CHAT_INPUT_H + 18)
        draw_panel(screen, chat_panel)
        ch = gs.fonts.tiny.render("CHAT", True, TEXT_ACCENT)
        screen.blit(ch, (CHAT_X, CHAT_Y - 2))
        visible = gs.mp.chat_log[-MAX_CHAT_LINES:]
        cy = CHAT_Y + 16
        for line in visible:
            ct = gs.fonts.micro.render(line[:100], True, TEXT_PRIMARY)
            screen.blit(ct, (CHAT_X + 4, cy))
            cy += 16
        draw_text_field(screen, self._chat_input_rect(), gs.mp.chat_input,
                        gs.fonts.main, active=gs.mp.chat_focus, placeholder="Type a message...")

        if gs.mp.net_err:
            err = gs.fonts.tiny.render(f"Error: {gs.mp.net_err[:60]}", True, ACCENT_RED)
            screen.blit(err, (40, HEIGHT - 120))

        draw_button(screen, self._back_rect(), "Leave", gs.fonts.main,
                    hot=self._hover == "back")
        ready_label = "READY" if not gs.mp.ready else "NOT READY"
        draw_button(screen, self._ready_rect(), ready_label, gs.fonts.main,
                    hot=self._hover == "ready",
                    accent=ACCENT_GREEN if not gs.mp.ready else ACCENT_RED)
        if gs.mp.lobby_host:
            draw_button(screen, self._start_rect(), "START", gs.fonts.main,
                        hot=self._hover == "start", accent=ACCENT_GREEN)

        hint = gs.fonts.micro.render(
            "ESC -- leave lobby  |  ENTER to send chat", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))
