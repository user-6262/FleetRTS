"""Multiplayer hub scene — lobby browser, host/join."""
from __future__ import annotations

import queue
import threading
from typing import Any, Dict, List, Optional

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, TEXT_WARN, ACCENT_GREEN,
    WIDTH, HEIGHT,
    draw_starfield, draw_world_edge, draw_panel, draw_button, draw_text_field,
)
from scenes import RunContext

LIST_POLL_MS = 6000
ROW_H = 34
ROW_GAP = 4
LIST_X = 80
LIST_Y = 160
LIST_W = WIDTH - 160
MAX_VISIBLE = 12


def _http_available(gs: Any) -> bool:
    return gs.mp.fleet_http_base is not None


def _back_rect() -> pygame.Rect:
    return pygame.Rect(20, HEIGHT - 70, 120, 48)

def _host_rect() -> pygame.Rect:
    return pygame.Rect(LIST_X, HEIGHT - 70, 180, 48)

def _join_rect() -> pygame.Rect:
    return pygame.Rect(LIST_X + 200, HEIGHT - 70, 180, 48)

def _name_rect() -> pygame.Rect:
    return pygame.Rect(LIST_X, 100, 280, 32)

def _join_id_rect() -> pygame.Rect:
    return pygame.Rect(LIST_X + 300, 100, 220, 32)


class MpHubScene:
    def __init__(self) -> None:
        self._hover: Optional[str] = None
        self._list_thread: Optional[threading.Thread] = None

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        if not _http_available(gs):
            return None
        now = pygame.time.get_ticks()
        if gs.mp.hub_list_last_ms is None or (now - (gs.mp.hub_list_last_ms or 0)) > LIST_POLL_MS:
            if not gs.mp.hub_list_busy:
                self._start_list_fetch(gs)
        if gs.mp.hub_list_busy:
            try:
                result = gs.mp.hub_list_q.get_nowait()
                gs.mp.hub_list_busy = False
                if isinstance(result, list):
                    gs.mp.hub_lobby_rows = result
                    gs.mp.hub_svc_state = "online"
                    gs.mp.hub_last_ok_ms = now
                elif isinstance(result, str):
                    gs.mp.hub_user_message = result
                    gs.mp.hub_svc_state = "error"
            except queue.Empty:
                pass
        return None

    def _start_list_fetch(self, gs: Any) -> None:
        gs.mp.hub_list_busy = True
        gs.mp.hub_list_last_ms = pygame.time.get_ticks()
        base = gs.mp.fleet_http_base

        def _work() -> None:
            try:
                from net.http_client import list_lobbies
                rows = list_lobbies(base)
                gs.mp.hub_list_q.put(rows)
            except Exception as e:
                gs.mp.hub_list_q.put(str(e))

        t = threading.Thread(target=_work, daemon=True)
        t.start()
        self._list_thread = t

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover = None
            if _back_rect().collidepoint(mx, my):
                self._hover = "back"
            elif _host_rect().collidepoint(mx, my):
                self._hover = "host"
            elif _join_rect().collidepoint(mx, my):
                self._hover = "join"

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            gs.mp.name_focus = _name_rect().collidepoint(mx, my)
            gs.mp.join_focus = _join_id_rect().collidepoint(mx, my)

            if _back_rect().collidepoint(mx, my):
                gs.audio.play_positive()
                return "config"
            if _host_rect().collidepoint(mx, my) and _http_available(gs):
                gs.audio.play_positive()
                return self._host_lobby(gs)
            if _join_rect().collidepoint(mx, my) and gs.mp.join_id_buffer.strip():
                gs.audio.play_positive()
                return self._join_lobby(gs)
            # Click a lobby row
            for i, _row in enumerate(gs.mp.hub_lobby_rows[gs.mp.hub_lobby_scroll:
                                                           gs.mp.hub_lobby_scroll + MAX_VISIBLE]):
                r = pygame.Rect(LIST_X, LIST_Y + i * (ROW_H + ROW_GAP), LIST_W, ROW_H)
                if r.collidepoint(mx, my):
                    row = gs.mp.hub_lobby_rows[gs.mp.hub_lobby_scroll + i]
                    gs.mp.join_id_buffer = str(row.get("short_id", row.get("lobby_id", "")))
                    gs.audio.play_positive()
                    break

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "config"
            if gs.mp.name_focus:
                if event.key == pygame.K_BACKSPACE:
                    gs.mp.name_buffer = gs.mp.name_buffer[:-1]
                elif event.key == pygame.K_TAB:
                    gs.mp.name_focus = False
                    gs.mp.join_focus = True
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    gs.mp.player_name = gs.mp.name_buffer.strip() or "Player"
                    gs.mp.name_focus = False
                elif event.unicode and len(gs.mp.name_buffer) < 48:
                    gs.mp.name_buffer += event.unicode
            elif gs.mp.join_focus:
                if event.key == pygame.K_BACKSPACE:
                    gs.mp.join_id_buffer = gs.mp.join_id_buffer[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if gs.mp.join_id_buffer.strip():
                        gs.audio.play_positive()
                        return self._join_lobby(gs)
                elif event.key == pygame.K_TAB:
                    gs.mp.join_focus = False
                    gs.mp.name_focus = True
                elif event.unicode and len(gs.mp.join_id_buffer) < 32:
                    gs.mp.join_id_buffer += event.unicode

        elif event.type == pygame.MOUSEWHEEL:
            gs.mp.hub_lobby_scroll = max(
                0, min(gs.mp.hub_lobby_scroll - event.y,
                       max(0, len(gs.mp.hub_lobby_rows) - MAX_VISIBLE)))
        return None

    def _host_lobby(self, gs: Any) -> str:
        try:
            from net.http_client import create_lobby
            lobby = create_lobby(
                gs.mp.fleet_http_base,
                name=f"{gs.mp.player_name}'s game",
                as_player=gs.mp.player_name,
                authoritative=gs.mp.http_authority_choice,
            )
            gs.mp.remote_lobby_id = lobby.get("lobby_id")
            gs.mp.remote_lobby_short = lobby.get("short_id")
            gs.mp.lobby_host = True
            gs.mp.ready = False
            gs.mp.chat_log = [f"Lobby created: {gs.mp.remote_lobby_short}"]
        except Exception as e:
            gs.mp.hub_user_message = str(e)
            return "mp_hub"
        return "mp_lobby"

    def _join_lobby(self, gs: Any) -> str:
        try:
            from net.http_client import join_lobby, get_lobby_by_short_id
            sid = gs.mp.join_id_buffer.strip()
            try:
                lobby_info = get_lobby_by_short_id(gs.mp.fleet_http_base, sid)
            except Exception:
                lobby_info = {"lobby_id": sid}
            lid = lobby_info.get("lobby_id", sid)
            lobby, joined_as = join_lobby(gs.mp.fleet_http_base, lid, gs.mp.player_name)
            gs.mp.remote_lobby_id = lobby.get("lobby_id")
            gs.mp.remote_lobby_short = lobby.get("short_id")
            gs.mp.player_name = joined_as
            gs.mp.name_buffer = joined_as
            gs.mp.lobby_host = False
            gs.mp.ready = False
            gs.mp.chat_log = [f"Joined lobby: {gs.mp.remote_lobby_short}"]
        except Exception as e:
            gs.mp.hub_user_message = str(e)
            return "mp_hub"
        return "mp_lobby"

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        screen.fill(BG_DEEP)
        draw_starfield(screen, gs.stars, gs.camera.cam_x, gs.camera.cam_y, WIDTH, HEIGHT)
        draw_world_edge(screen, gs.camera.cam_x, gs.camera.cam_y)

        title = gs.fonts.big.render("MULTIPLAYER", True, TEXT_ACCENT)
        screen.blit(title, (LIST_X, 20))

        status_col = ACCENT_GREEN if gs.mp.hub_svc_state == "online" else TEXT_WARN
        status_text = gs.mp.hub_svc_state.upper()
        st = gs.fonts.tiny.render(f"Server: {status_text}", True, status_col)
        screen.blit(st, (LIST_X + title.get_width() + 20, 26))

        # Name + join ID fields
        nl = gs.fonts.tiny.render("Player name:", True, TEXT_SECONDARY)
        screen.blit(nl, (LIST_X, 82))
        draw_text_field(screen, _name_rect(), gs.mp.name_buffer, gs.fonts.main,
                        active=gs.mp.name_focus, placeholder="Player")
        jl = gs.fonts.tiny.render("Join code:", True, TEXT_SECONDARY)
        screen.blit(jl, (LIST_X + 300, 82))
        draw_text_field(screen, _join_id_rect(), gs.mp.join_id_buffer, gs.fonts.main,
                        active=gs.mp.join_focus, placeholder="lobby ID")

        # Lobby list header
        hdr = gs.fonts.main.render("OPEN LOBBIES", True, TEXT_ACCENT)
        screen.blit(hdr, (LIST_X, LIST_Y - 28))
        if not gs.mp.hub_lobby_rows:
            empty = gs.fonts.tiny.render(
                "No lobbies found. Host one or enter a join code.", True, TEXT_DIM)
            screen.blit(empty, (LIST_X, LIST_Y + 8))
        else:
            visible = gs.mp.hub_lobby_rows[gs.mp.hub_lobby_scroll:
                                            gs.mp.hub_lobby_scroll + MAX_VISIBLE]
            for i, row in enumerate(visible):
                r = pygame.Rect(LIST_X, LIST_Y + i * (ROW_H + ROW_GAP), LIST_W, ROW_H)
                pygame.draw.rect(screen, BTN_FILL, r, border_radius=4)
                pygame.draw.rect(screen, BORDER_BTN, r, width=1, border_radius=4)
                name = str(row.get("name", row.get("short_id", "?")))[:40]
                players = row.get("players", [])
                pcount = len(players) if isinstance(players, list) else 0
                sid = str(row.get("short_id", ""))[:8]
                t1 = gs.fonts.main.render(name, True, TEXT_PRIMARY)
                screen.blit(t1, (r.x + 8, r.y + 4))
                t2 = gs.fonts.tiny.render(f"{pcount}p  [{sid}]", True, TEXT_SECONDARY)
                screen.blit(t2, (r.right - t2.get_width() - 10, r.y + 8))

        if gs.mp.hub_user_message:
            msg = gs.fonts.tiny.render(gs.mp.hub_user_message[:80], True, TEXT_WARN)
            screen.blit(msg, (LIST_X, HEIGHT - 120))

        draw_button(screen, _back_rect(), "Back", gs.fonts.main,
                    hot=self._hover == "back")
        draw_button(screen, _host_rect(), "Host Game", gs.fonts.main,
                    hot=self._hover == "host", accent=ACCENT_GREEN)
        draw_button(screen, _join_rect(), "Join", gs.fonts.main,
                    hot=self._hover == "join")

        hint = gs.fonts.micro.render(
            "ESC -- back  |  Click lobby row to fill join code  |  ENTER in join field to connect",
            True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))
