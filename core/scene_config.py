"""Title / config scene — the first thing the player sees."""
from __future__ import annotations

from typing import Any, Optional

import pygame

from draw import (
    BG_DEEP, BORDER_PANEL, BTN_FILL, BTN_FILL_HOT, BORDER_BTN, BORDER_BTN_HOT,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM, TEXT_ACCENT, ACCENT_GREEN,
    WIDTH, HEIGHT, draw_starfield, draw_world_edge, draw_panel,
)
from scenes import RunContext


class ConfigScene:
    """Atmospheric title screen with three primary actions."""

    def __init__(self) -> None:
        self._hover: Optional[str] = None
        self._cam_drift = 0.0
        self._volume_drag = False

    # ── layout ──────────────────────────────────────────────────────────────

    def _card_rects(self) -> dict[str, pygame.Rect]:
        cw, ch = 320, 54
        cx = WIDTH // 2 - cw // 2
        y0 = HEIGHT // 2 - 20
        gap = 18
        return {
            "launch":      pygame.Rect(cx, y0, cw, ch),
            "multiplayer": pygame.Rect(cx, y0 + ch + gap, cw, ch),
            "editor":      pygame.Rect(cx, y0 + (ch + gap) * 2, cw, ch),
        }

    def _settings_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 200, HEIGHT - 90, 400, 48)

    def _volume_track(self) -> pygame.Rect:
        sr = self._settings_rect()
        return pygame.Rect(sr.x + 80, sr.centery - 6, sr.w - 160, 12)

    # ── scene protocol ──────────────────────────────────────────────────────

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        self._cam_drift += dt * 8.0
        return None

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        cards = self._card_rects()

        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover = None
            for key, rect in cards.items():
                if rect.collidepoint(mx, my):
                    self._hover = key
            if self._volume_drag:
                vt = self._volume_track()
                gs.audio.master_volume = max(0.0, min(1.0, (mx - vt.x) / max(1, vt.w)))
                gs.audio.apply_master_volume()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            for key, rect in cards.items():
                if rect.collidepoint(mx, my):
                    gs.audio.play_positive()
                    if key == "launch":
                        return "ship_loadouts"
                    elif key == "multiplayer":
                        gs.mp.hub_list_last_ms = -1
                        gs.mp.hub_lobby_rows = []
                        gs.mp.hub_lobby_scroll = 0
                        gs.mp.hub_svc_state = "checking"
                        gs.mp.hub_user_message = None
                        return "mp_hub"
                    elif key == "editor":
                        return "battlegroup_editor"
            vt = self._volume_track()
            if vt.collidepoint(mx, my):
                self._volume_drag = True
                gs.audio.master_volume = max(0.0, min(1.0, (mx - vt.x) / max(1, vt.w)))
                gs.audio.apply_master_volume()

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._volume_drag = False

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                gs.audio.play_positive()
                return "ship_loadouts"

        return None

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        screen.fill(BG_DEEP)
        cam_x = gs.camera.cam_x + self._cam_drift
        cam_y = gs.camera.cam_y + self._cam_drift * 0.4
        draw_starfield(screen, gs.stars, cam_x, cam_y, WIDTH, HEIGHT)
        draw_world_edge(screen, cam_x, cam_y)

        title = gs.fonts.big.render("FLEET  RTS", True, TEXT_ACCENT)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 120))

        subtitle = gs.fonts.tiny.render(
            "Carrier strike group tactical sim", True, TEXT_DIM)
        screen.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2, HEIGHT // 2 - 82))

        cards = self._card_rects()
        labels = {"launch": "Launch Mission", "multiplayer": "Multiplayer",
                  "editor": "Fleet Editor"}
        accents = {"launch": ACCENT_GREEN, "multiplayer": None, "editor": None}
        for key, rect in cards.items():
            hot = self._hover == key
            fill = BTN_FILL_HOT if hot else BTN_FILL
            accent = accents[key]
            border = accent or (BORDER_BTN_HOT if hot else BORDER_BTN)
            pygame.draw.rect(screen, fill, rect, border_radius=10)
            pygame.draw.rect(screen, border, rect, width=2, border_radius=10)
            lbl = gs.fonts.main.render(labels[key], True, TEXT_PRIMARY)
            screen.blit(lbl, (rect.centerx - lbl.get_width() // 2,
                              rect.centery - lbl.get_height() // 2))

        # Volume control
        sr = self._settings_rect()
        vol_label = gs.fonts.tiny.render("Volume", True, TEXT_SECONDARY)
        screen.blit(vol_label, (sr.x + 8, sr.centery - vol_label.get_height() // 2))
        vt = self._volume_track()
        pygame.draw.rect(screen, (28, 40, 54), vt, border_radius=6)
        fill_w = int(vt.w * gs.audio.master_volume)
        if fill_w > 0:
            pygame.draw.rect(screen, (90, 160, 200),
                             pygame.Rect(vt.x, vt.y, fill_w, vt.h), border_radius=6)
        pygame.draw.rect(screen, (120, 170, 210), vt, width=1, border_radius=6)

        hint = gs.fonts.micro.render("ENTER — launch  |  Ctrl+Q — quit", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 28))
