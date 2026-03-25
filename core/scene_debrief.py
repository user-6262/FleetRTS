"""Debrief / store scene — purchase upgrades and ships between combat rounds."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BG_CHROME, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, TEXT_WARN, ACCENT_GREEN, ACCENT_RED,
    WIDTH, HEIGHT, VIEW_W, VIEW_H, BOTTOM_BAR_H,
    draw_battle_world, draw_panel,
)
from scenes import RunContext

try:
    from combat_math import round_seed
    from combat_engine import begin_combat_round
except ImportError:
    from core.combat_math import round_seed
    from core.combat_engine import begin_combat_round

# ── store data ──────────────────────────────────────────────────────────────
COST_REPAIR = 28
COST_RESUPPLY = 34
COST_CIWS = 44
COST_BULKHEAD = 52
MAX_CIWS_STACKS = 5
MAX_BULKHEAD_STACKS = 5
CIWS_ROF_BONUS = 0.085
BULKHEAD_HP_FRAC = 0.06
MAX_PLAYER_CAPITALS = 14
COST_LIGHT_RESUPPLY = 22
LIGHT_RESUPPLY_AMT = 14.0

SHIP_ROWS: List[Tuple[str, str, int]] = [
    ("Frigate",     "ship_frigate",    62),
    ("Destroyer",   "ship_destroyer",  92),
    ("Cruiser",     "ship_cruiser",   138),
    ("Battleship",  "ship_battleship", 175),
    ("Carrier",     "ship_carrier",   255),
]
UPG_ROWS: List[Tuple[str, str, int]] = [
    ("Full Repair",       "upg_repair",   COST_REPAIR),
    ("Resupply +28",      "upg_resupply", COST_RESUPPLY),
    ("CIWS tuning",       "upg_ciws",     COST_CIWS),
    ("Bulkhead refit",    "upg_bulkhead", COST_BULKHEAD),
    ("Light resupply +14", "upg_stores",  COST_LIGHT_RESUPPLY),
]
ALL_IDS = [r[1] for r in SHIP_ROWS] + [r[1] for r in UPG_ROWS]
KEY_MAP = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
           pygame.K_4: 3, pygame.K_5: 4, pygame.K_6: 5,
           pygame.K_7: 6, pygame.K_8: 7, pygame.K_9: 8, pygame.K_0: 9}

MARGIN = 14
TOP_Y = 72
BOTTOM_PAD = 44
PANEL_GAP = 12
ROW_H = 26
ROW_GAP = 3
HEADER_H = 36
INNER_PAD = 10

RECRUIT_LABEL_PREFIX = {
    "Frigate": "FF", "Destroyer": "DD", "Cruiser": "CG",
    "Battleship": "BB", "Carrier": "CV",
}


def _panel_rects() -> Tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
    h = HEIGHT - TOP_Y - BOTTOM_PAD
    inner_w = WIDTH - MARGIN * 2 - PANEL_GAP * 2
    pw = inner_w // 3
    x1 = MARGIN
    x2 = x1 + pw + PANEL_GAP
    x3 = x2 + pw + PANEL_GAP
    return (pygame.Rect(x1, TOP_Y, pw, h),
            pygame.Rect(x2, TOP_Y, pw, h),
            pygame.Rect(x3, TOP_Y, WIDTH - MARGIN - x3, h))


def _row_rects(panel: pygame.Rect, n: int) -> List[pygame.Rect]:
    out = []
    y = panel.y + HEADER_H
    for _ in range(n):
        out.append(pygame.Rect(panel.x + INNER_PAD, y,
                                panel.w - INNER_PAD * 2, ROW_H))
        y += ROW_H + ROW_GAP
    return out


def _purchase_rect(info_panel: pygame.Rect) -> pygame.Rect:
    return pygame.Rect(info_panel.x + INNER_PAD,
                       info_panel.bottom - 50,
                       info_panel.w - INNER_PAD * 2, 38)


def _cap_count(gs: Any) -> int:
    return sum(1 for g in gs.combat.groups
               if g.side == "player" and not g.dead and g.render_capital)


def _next_label(groups: list, cls: str) -> str:
    prefix = RECRUIT_LABEL_PREFIX[cls]
    nums = []
    for g in groups:
        if g.side == "player" and g.class_name == cls and g.label.startswith(prefix + "-"):
            try:
                nums.append(int(g.label.split("-", 1)[1]))
            except ValueError:
                pass
    n = (max(nums) + 1) if nums else 1
    return f"{prefix}-{n}"


def _attempt_purchase(item_id: str, gs: Any) -> bool:
    try:
        from fleet_deployment import ship_class_by_name
    except ImportError:
        from core.fleet_deployment import ship_class_by_name
    from demo_game import make_group, spawn_hangar_crafts
    salvage = gs.combat.salvage
    groups = gs.combat.groups
    crafts = gs.combat.crafts
    for cls, sid, cost in SHIP_ROWS:
        if sid == item_id:
            if salvage[0] < cost or _cap_count(gs) >= MAX_PLAYER_CAPITALS:
                return False
            salvage[0] -= cost
            lbl = _next_label(groups, cls)
            from draw import WORLD_W, WORLD_H
            ng = make_group(gs.data, "player", lbl, cls,
                            WORLD_W * 0.5, WORLD_H * 0.86)
            groups.append(ng)
            sc = ship_class_by_name(gs.data, cls)
            if sc.get("hangar"):
                crafts.extend(spawn_hangar_crafts(gs.data, ng))
            cg = gs.combat.control_groups
            if cg[0] is None:
                cg[0] = [lbl]
            elif lbl not in cg[0]:
                cg[0].append(lbl)
            return True
    if item_id == "upg_repair":
        if salvage[0] < COST_REPAIR:
            return False
        salvage[0] -= COST_REPAIR
        from demo_game import full_repair_and_revive_wing
        full_repair_and_revive_wing(groups, crafts)
        return True
    if item_id == "upg_resupply":
        if salvage[0] < COST_RESUPPLY:
            return False
        salvage[0] -= COST_RESUPPLY
        gs.combat.supplies[0] = min(100.0, gs.combat.supplies[0] + 28.0)
        return True
    if item_id == "upg_ciws":
        if salvage[0] < COST_CIWS or gs.combat.ciws_stacks[0] >= MAX_CIWS_STACKS:
            return False
        salvage[0] -= COST_CIWS
        gs.combat.ciws_stacks[0] += 1
        gs.combat.pd_rof_mult[0] += CIWS_ROF_BONUS
        return True
    if item_id == "upg_bulkhead":
        if salvage[0] < COST_BULKHEAD or gs.combat.bulk_stacks[0] >= MAX_BULKHEAD_STACKS:
            return False
        salvage[0] -= COST_BULKHEAD
        gs.combat.bulk_stacks[0] += 1
        from demo_game import apply_bulkhead_bonus
        apply_bulkhead_bonus(groups, crafts)
        return True
    if item_id == "upg_stores":
        if salvage[0] < COST_LIGHT_RESUPPLY or gs.combat.supplies[0] >= 100.0:
            return False
        salvage[0] -= COST_LIGHT_RESUPPLY
        gs.combat.supplies[0] = min(100.0, gs.combat.supplies[0] + LIGHT_RESUPPLY_AMT)
        return True
    return False


class DebriefScene:
    def __init__(self) -> None:
        self._hover_id: Optional[str] = None
        self._hover_purchase = False
        self._hover_next = False

    def _next_btn_rect(self) -> pygame.Rect:
        _, _, info = _panel_rects()
        return pygame.Rect(info.x + INNER_PAD,
                           info.bottom - 100,
                           info.w - INNER_PAD * 2, 38)

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        return None

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover_id = None
            self._hover_purchase = False
            self._hover_next = False
            ship_p, upg_p, info_p = _panel_rects()
            for rect, (_, sid, _cost) in zip(_row_rects(ship_p, len(SHIP_ROWS)), SHIP_ROWS):
                if rect.collidepoint(mx, my):
                    self._hover_id = sid
            for rect, (_, uid, _cost) in zip(_row_rects(upg_p, len(UPG_ROWS)), UPG_ROWS):
                if rect.collidepoint(mx, my):
                    self._hover_id = uid
            if _purchase_rect(info_p).collidepoint(mx, my):
                self._hover_purchase = True
            if self._next_btn_rect().collidepoint(mx, my):
                self._hover_next = True

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            ship_p, upg_p, info_p = _panel_rects()
            for rect, (_, sid, _cost) in zip(_row_rects(ship_p, len(SHIP_ROWS)), SHIP_ROWS):
                if rect.collidepoint(mx, my):
                    gs.debrief.store_selected = sid
                    gs.audio.play_positive()
                    return None
            for rect, (_, uid, _cost) in zip(_row_rects(upg_p, len(UPG_ROWS)), UPG_ROWS):
                if rect.collidepoint(mx, my):
                    gs.debrief.store_selected = uid
                    gs.audio.play_positive()
                    return None
            if _purchase_rect(info_p).collidepoint(mx, my) and gs.debrief.store_selected:
                if _attempt_purchase(gs.debrief.store_selected, gs):
                    gs.audio.play_positive()
                else:
                    gs.audio.play_negative()
                return None
            if self._next_btn_rect().collidepoint(mx, my):
                return self._advance_round(gs)

        elif event.type == pygame.KEYDOWN:
            if event.key in KEY_MAP:
                idx = KEY_MAP[event.key]
                if idx < len(ALL_IDS):
                    item_id = ALL_IDS[idx]
                    if _attempt_purchase(item_id, gs):
                        gs.audio.play_positive()
                    else:
                        gs.audio.play_negative()
                return None
            if event.key == pygame.K_SPACE:
                return self._advance_round(gs)
        return None

    def _advance_round(self, gs: Any) -> str:
        if gs.mp.post_combat_phase:
            dest = gs.mp.post_combat_phase
            gs.mp.post_combat_phase = None
            gs.round.outcome = None
            gs.debrief.store_selected = None
            gs.debrief.store_hover = None
            return dest

        gs.round.round_idx += 1
        gs.round.outcome = None
        gs.round.phase = "combat"
        gs.debrief.store_selected = None
        gs.debrief.store_hover = None
        seed = round_seed(gs.round.round_idx)
        gs.combat.mission = begin_combat_round(
            gs.data, gs.combat.groups, gs.round.round_idx,
            random.Random(seed), gs.battle_obstacles)
        try:
            from combat import reset_combat_control_groups_for_spawn
        except ImportError:
            from core.combat import reset_combat_control_groups_for_spawn
        reset_combat_control_groups_for_spawn(
            gs.combat.groups, gs.combat.control_groups, gs.combat.cg_weapons_free)
        from draw import clamp_camera, VIEW_W, VIEW_H
        caps = [g for g in gs.combat.groups
                if g.side == "player" and not g.dead and g.render_capital]
        if caps:
            cx = sum(g.x for g in caps) / len(caps)
            cy = sum(g.y for g in caps) / len(caps)
            gs.camera.cam_x, gs.camera.cam_y = clamp_camera(
                cx - VIEW_W * 0.5, cy - VIEW_H * 0.5)
        return "combat"

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        draw_battle_world(screen, gs, show_fog=False)
        ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        ov.fill((6, 14, 24, 215))
        screen.blit(ov, (0, 0))

        # Header
        title = gs.fonts.big.render(
            f"ROUND {gs.round.round_idx} COMPLETE -- {gs.round.outcome or 'Victory'}",
            True, TEXT_ACCENT)
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 20))
        score_t = gs.fonts.tiny.render(
            f"Score: {gs.debrief.run_total_score}   Salvage: {gs.combat.salvage[0]}   "
            f"(+{gs.debrief.last_salvage_gain} this round)",
            True, TEXT_SECONDARY)
        screen.blit(score_t, (WIDTH // 2 - score_t.get_width() // 2, 50))

        ship_p, upg_p, info_p = _panel_rects()
        self._draw_ship_panel(screen, gs, ship_p)
        self._draw_upg_panel(screen, gs, upg_p)
        self._draw_info_panel(screen, gs, info_p)

        next_hint = "SPACE return to lobby" if gs.mp.post_combat_phase else "SPACE next round"
        hint = gs.fonts.micro.render(
            f"1-5 recruit ships  |  6-0 upgrades  |  {next_hint}", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 28))

    def _draw_ship_panel(self, screen: pygame.Surface, gs: Any,
                         panel: pygame.Rect) -> None:
        draw_panel(screen, panel)
        hdr = gs.fonts.main.render("RECRUIT", True, TEXT_ACCENT)
        screen.blit(hdr, (panel.x + INNER_PAD, panel.y + 8))
        for rect, (cls, sid, cost) in zip(_row_rects(panel, len(SHIP_ROWS)), SHIP_ROWS):
            selected = gs.debrief.store_selected == sid
            hovered = self._hover_id == sid
            bg = BTN_FILL_HOT if (selected or hovered) else BTN_FILL
            bd = ACCENT_GREEN if selected else (BORDER_BTN_HOT if hovered else BORDER_BTN)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            pygame.draw.rect(screen, bd, rect, width=1, border_radius=4)
            t = gs.fonts.tiny.render(f"{cls}  ({cost})", True, TEXT_PRIMARY)
            screen.blit(t, (rect.x + 6, rect.centery - t.get_height() // 2))

    def _draw_upg_panel(self, screen: pygame.Surface, gs: Any,
                        panel: pygame.Rect) -> None:
        draw_panel(screen, panel)
        hdr = gs.fonts.main.render("UPGRADES", True, TEXT_ACCENT)
        screen.blit(hdr, (panel.x + INNER_PAD, panel.y + 8))
        for rect, (name, uid, cost) in zip(_row_rects(panel, len(UPG_ROWS)), UPG_ROWS):
            selected = gs.debrief.store_selected == uid
            hovered = self._hover_id == uid
            bg = BTN_FILL_HOT if (selected or hovered) else BTN_FILL
            bd = ACCENT_GREEN if selected else (BORDER_BTN_HOT if hovered else BORDER_BTN)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            pygame.draw.rect(screen, bd, rect, width=1, border_radius=4)
            t = gs.fonts.tiny.render(f"{name}  ({cost})", True, TEXT_PRIMARY)
            screen.blit(t, (rect.x + 6, rect.centery - t.get_height() // 2))

    def _draw_info_panel(self, screen: pygame.Surface, gs: Any,
                         panel: pygame.Rect) -> None:
        draw_panel(screen, panel)
        hdr = gs.fonts.main.render("INFO", True, TEXT_ACCENT)
        screen.blit(hdr, (panel.x + INNER_PAD, panel.y + 8))

        sel = gs.debrief.store_selected or self._hover_id
        y = panel.y + HEADER_H + 4
        if sel:
            for cls, sid, cost in SHIP_ROWS:
                if sid == sel:
                    lines = [f"{cls} -- cost {cost} salvage",
                             f"Fleet: {_cap_count(gs)}/{MAX_PLAYER_CAPITALS} capitals"]
                    for line in lines:
                        t = gs.fonts.tiny.render(line, True, TEXT_PRIMARY)
                        screen.blit(t, (panel.x + INNER_PAD, y))
                        y += 18
                    break
            for name, uid, cost in UPG_ROWS:
                if uid == sel:
                    t = gs.fonts.tiny.render(f"{name} -- cost {cost}", True, TEXT_PRIMARY)
                    screen.blit(t, (panel.x + INNER_PAD, y))
                    y += 18
                    break
        else:
            t = gs.fonts.tiny.render("Select an item for details.", True, TEXT_DIM)
            screen.blit(t, (panel.x + INNER_PAD, y))

        # Purchase bar
        pr = _purchase_rect(panel)
        buy_active = sel is not None
        fill = BTN_FILL_HOT if (self._hover_purchase and buy_active) else BTN_FILL
        bd = ACCENT_GREEN if buy_active else BORDER_BTN
        pygame.draw.rect(screen, fill, pr, border_radius=6)
        pygame.draw.rect(screen, bd, pr, width=2, border_radius=6)
        buy_label = "PURCHASE" if buy_active else "Select an item"
        bt = gs.fonts.main.render(buy_label, True, TEXT_PRIMARY if buy_active else TEXT_DIM)
        screen.blit(bt, (pr.centerx - bt.get_width() // 2,
                         pr.centery - bt.get_height() // 2))

        # Next round button
        nr = self._next_btn_rect()
        nfill = BTN_FILL_HOT if self._hover_next else BTN_FILL
        pygame.draw.rect(screen, nfill, nr, border_radius=6)
        pygame.draw.rect(screen, ACCENT_GREEN, nr, width=2, border_radius=6)
        next_label = "RETURN TO LOBBY  (SPACE)" if gs.mp.post_combat_phase else "NEXT ROUND  (SPACE)"
        nt = gs.fonts.main.render(next_label, True, TEXT_PRIMARY)
        screen.blit(nt, (nr.centerx - nt.get_width() // 2,
                         nr.centery - nt.get_height() // 2))
