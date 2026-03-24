"""Game-over overlay shown at the end of a campaign run or after PvP match."""
from __future__ import annotations

from typing import Any, Optional

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, TEXT_PRIMARY, TEXT_DIM,
    TEXT_ACCENT, ACCENT_GREEN, ACCENT_RED,
    WIDTH, HEIGHT, BOTTOM_BAR_H, VIEW_H,
    draw_battle_world, draw_panel, draw_button,
)
from scenes import RunContext


class GameOverScene:
    """Translucent overlay over the last combat frame with results + restart."""

    def __init__(self) -> None:
        self._hover_restart = False
        self._hover_menu = False
        self._flash_t = 0.0

    def _restart_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 150, HEIGHT // 2 + 60, 130, 48)

    def _menu_rect(self) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 + 20, HEIGHT // 2 + 60, 130, 48)

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        self._flash_t += dt
        return None

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover_restart = self._restart_rect().collidepoint(mx, my)
            self._hover_menu = self._menu_rect().collidepoint(mx, my)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            if self._restart_rect().collidepoint(mx, my):
                gs.audio.play_positive()
                _reset_for_new_run(gs)
                return "ship_loadouts"
            if self._menu_rect().collidepoint(mx, my):
                gs.audio.play_positive()
                _reset_for_new_run(gs)
                return "config"

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                gs.audio.play_positive()
                _reset_for_new_run(gs)
                return "ship_loadouts"
            if event.key == pygame.K_ESCAPE:
                _reset_for_new_run(gs)
                return "config"
        return None

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        draw_battle_world(screen, gs, show_fog=False)

        overlay = pygame.Surface((WIDTH, VIEW_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))

        outcome = gs.round.outcome or "defeat"
        won = outcome.lower() in ("victory", "win")
        banner_col = ACCENT_GREEN if won else ACCENT_RED
        banner = gs.fonts.big.render(outcome.upper(), True, banner_col)
        screen.blit(banner, (WIDTH // 2 - banner.get_width() // 2, HEIGHT // 2 - 90))

        score_text = gs.fonts.main.render(
            f"Score: {gs.debrief.run_total_score}   Rounds survived: {gs.round.round_idx}",
            True, TEXT_PRIMARY)
        screen.blit(score_text, (WIDTH // 2 - score_text.get_width() // 2, HEIGHT // 2 - 36))

        draw_button(screen, self._restart_rect(), "New Run", gs.fonts.main,
                    hot=self._hover_restart, accent=ACCENT_GREEN)
        draw_button(screen, self._menu_rect(), "Main Menu", gs.fonts.main,
                    hot=self._hover_menu)

        bottom = pygame.Rect(0, HEIGHT - BOTTOM_BAR_H, WIDTH, BOTTOM_BAR_H)
        pygame.draw.rect(screen, BG_DEEP, bottom)

        hint = gs.fonts.micro.render("ENTER — new run  |  ESC — menu", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))


def _reset_for_new_run(gs: Any) -> None:
    """Wipe per-run state so the player can start fresh."""
    from game_state import CombatState, RoundState, LoadoutState, DebriefState, TTSState, InputState
    gs.combat = CombatState()
    gs.round = RoundState()
    gs.loadout = LoadoutState()
    gs.debrief = DebriefState()
    gs.tts = TTSState()
    gs.input = InputState()
