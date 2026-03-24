"""Ship loadouts scene — build and preview the initial fleet before combat."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, ACCENT_GREEN,
    WIDTH, HEIGHT, BOTTOM_BAR_H,
    draw_panel, draw_button,
)
from scenes import RunContext

try:
    from combat_engine import begin_combat_round
    from combat_math import round_seed
except ImportError:
    from core.combat_engine import begin_combat_round
    from core.combat_math import round_seed

ROSTER_X = 40
ROSTER_Y = 60
ROSTER_W = 260
ROW_H = 44
ROW_GAP = 6
DEPLOY_BTN = pygame.Rect(WIDTH // 2 - 100, HEIGHT - 70, 200, 48)
BACK_BTN = pygame.Rect(20, HEIGHT - 70, 120, 48)


class LoadoutsScene:
    def __init__(self) -> None:
        self._hover_deploy = False
        self._hover_back = False
        self._hover_row: int = -1
        self._built = False

    def _ensure_fleet(self, gs: Any) -> None:
        if self._built and gs.combat.groups:
            return
        from demo_game import build_initial_player_fleet
        groups, crafts = build_initial_player_fleet(gs.data)
        gs.combat.groups = groups
        gs.combat.crafts = crafts
        self._built = True

    def _roster(self, gs: Any) -> List[Any]:
        return [g for g in gs.combat.groups
                if g.side == "player" and not g.dead and g.render_capital]

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        self._ensure_fleet(gs)
        return None

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover_deploy = DEPLOY_BTN.collidepoint(mx, my)
            self._hover_back = BACK_BTN.collidepoint(mx, my)
            self._hover_row = -1
            roster = self._roster(gs)
            for i in range(len(roster)):
                r = pygame.Rect(ROSTER_X, ROSTER_Y + i * (ROW_H + ROW_GAP), ROSTER_W, ROW_H)
                if r.collidepoint(mx, my):
                    self._hover_row = i

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            if DEPLOY_BTN.collidepoint(mx, my):
                gs.audio.play_positive()
                return self._deploy(gs)
            if BACK_BTN.collidepoint(mx, my):
                gs.audio.play_positive()
                return "config"
            roster = self._roster(gs)
            for i in range(len(roster)):
                r = pygame.Rect(ROSTER_X, ROSTER_Y + i * (ROW_H + ROW_GAP), ROSTER_W, ROW_H)
                if r.collidepoint(mx, my):
                    gs.loadout.selected_i = i
                    gs.audio.play_positive()

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                gs.audio.play_positive()
                return self._deploy(gs)
            if event.key == pygame.K_ESCAPE:
                return "config"
        return None

    def _deploy(self, gs: Any) -> str:
        gs.round.round_idx = 1
        gs.round.outcome = None
        gs.round.phase = "combat"
        from draw import clamp_camera, VIEW_W, VIEW_H, WORLD_W, WORLD_H
        seed = round_seed(1)
        gs.combat.mission = begin_combat_round(
            gs.data, gs.combat.groups, 1,
            random.Random(seed), gs.battle_obstacles)
        caps = [g for g in gs.combat.groups
                if g.side == "player" and not g.dead and g.render_capital]
        if caps:
            cx = sum(g.x for g in caps) / len(caps)
            cy = sum(g.y for g in caps) / len(caps)
            gs.camera.cam_x, gs.camera.cam_y = clamp_camera(
                cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)
        else:
            gs.camera.cam_x, gs.camera.cam_y = clamp_camera(
                WORLD_W * 0.35, WORLD_H * 0.35)
        return "combat"

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        screen.fill(BG_DEEP)

        title = gs.fonts.big.render("FLEET LOADOUTS", True, TEXT_ACCENT)
        screen.blit(title, (ROSTER_X, 18))

        roster = self._roster(gs)
        for i, g in enumerate(roster):
            r = pygame.Rect(ROSTER_X, ROSTER_Y + i * (ROW_H + ROW_GAP), ROSTER_W, ROW_H)
            selected = i == gs.loadout.selected_i
            hovered = i == self._hover_row
            fill = BTN_FILL_HOT if (selected or hovered) else BTN_FILL
            bd = ACCENT_GREEN if selected else (BORDER_BTN_HOT if hovered else BORDER_BTN)
            pygame.draw.rect(screen, fill, r, border_radius=6)
            pygame.draw.rect(screen, bd, r, width=2, border_radius=6)
            lbl = gs.fonts.main.render(f"{g.label}  {g.class_name}", True, TEXT_PRIMARY)
            screen.blit(lbl, (r.x + 10, r.y + 4))
            hp = gs.fonts.tiny.render(f"HP {g.hp:.0f}/{g.max_hp:.0f}", True, TEXT_SECONDARY)
            screen.blit(hp, (r.x + 10, r.y + 24))
            weap = gs.fonts.micro.render(
                f"Weapons: {len(g.weapons)}", True, TEXT_DIM)
            screen.blit(weap, (r.x + ROSTER_W - 90, r.y + 26))

        # Detail panel for selected ship
        if 0 <= gs.loadout.selected_i < len(roster):
            g = roster[gs.loadout.selected_i]
            dp = pygame.Rect(ROSTER_X + ROSTER_W + 40, ROSTER_Y, 400, 300)
            draw_panel(screen, dp)
            name = gs.fonts.big.render(f"{g.label} -- {g.class_name}", True, TEXT_ACCENT)
            screen.blit(name, (dp.x + 14, dp.y + 12))
            y = dp.y + 48
            for w in g.weapons:
                wt = gs.fonts.tiny.render(
                    f"{w.name}  ({w.projectile_name})  RoF {w.fire_rate:.2f}",
                    True, TEXT_PRIMARY)
                screen.blit(wt, (dp.x + 14, y))
                y += 20

        draw_button(screen, DEPLOY_BTN, "DEPLOY", gs.fonts.main,
                    hot=self._hover_deploy, accent=ACCENT_GREEN)
        draw_button(screen, BACK_BTN, "Back", gs.fonts.main,
                    hot=self._hover_back)

        hint = gs.fonts.micro.render(
            "ENTER -- deploy fleet  |  ESC -- main menu", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))
