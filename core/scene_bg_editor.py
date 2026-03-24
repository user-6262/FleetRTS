"""Battlegroup preset editor scene."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pygame

try:
    from pvp_battlegroups import (
        BattlegroupPreset, default_battlegroups_path,
        load_battlegroups, save_battlegroups,
    )
except ImportError:
    from core.pvp_battlegroups import (
        BattlegroupPreset, default_battlegroups_path,
        load_battlegroups, save_battlegroups,
    )

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, ACCENT_GREEN,
    WIDTH, HEIGHT,
    draw_starfield, draw_world_edge, draw_panel, draw_button, draw_text_field,
)
from scenes import RunContext

ENTRY_TAGS = ("spawn_edge", "spawn_left", "spawn_right")
LIST_X, LIST_Y = 30, 80
LIST_W = 260
ROW_H = 30
ROW_GAP = 4
MAX_VISIBLE = 18

EDIT_X = LIST_X + LIST_W + 30
EDIT_Y = 80
EDIT_W = WIDTH - EDIT_X - 30
FIELD_H = 28
FIELD_GAP = 8
SHIP_ROW_H = 26
SHIP_ROW_GAP = 3


class BGEditorScene:
    def __init__(self) -> None:
        self._loaded = False
        self._hover: Optional[str] = None

    def _ensure_loaded(self, gs: Any) -> None:
        if self._loaded:
            return
        path = default_battlegroups_path()
        gs.bg_editor.path = path
        gs.bg_editor.presets = load_battlegroups(path)
        gs.bg_editor.selected_i = 0
        self._sync_fields(gs)
        self._loaded = True

    def _sync_fields(self, gs: Any) -> None:
        presets = gs.bg_editor.presets
        i = gs.bg_editor.selected_i
        if 0 <= i < len(presets):
            p = presets[i]
            gs.bg_editor.name_buf = p.name
            gs.bg_editor.id_buf = p.preset_id
            gs.bg_editor.cost_buf = str(p.deploy_cost)
            gs.bg_editor.rows = list(p.design_rows)
            gs.bg_editor.entry_i = ENTRY_TAGS.index(p.entry_tag) if p.entry_tag in ENTRY_TAGS else 0
        else:
            gs.bg_editor.name_buf = ""
            gs.bg_editor.id_buf = ""
            gs.bg_editor.cost_buf = "0"
            gs.bg_editor.rows = []
            gs.bg_editor.entry_i = 0

    def _apply_fields(self, gs: Any) -> None:
        presets = gs.bg_editor.presets
        i = gs.bg_editor.selected_i
        if 0 <= i < len(presets):
            p = presets[i]
            p.name = gs.bg_editor.name_buf.strip() or p.name
            p.preset_id = gs.bg_editor.id_buf.strip() or p.preset_id
            try:
                p.deploy_cost = max(0, int(gs.bg_editor.cost_buf))
            except ValueError:
                pass
            p.design_rows = list(gs.bg_editor.rows)
            p.entry_tag = ENTRY_TAGS[gs.bg_editor.entry_i % len(ENTRY_TAGS)]

    def _save(self, gs: Any) -> None:
        self._apply_fields(gs)
        save_battlegroups(gs.bg_editor.path, gs.bg_editor.presets)

    # -- layout helpers --

    def _list_row_rect(self, i: int) -> pygame.Rect:
        return pygame.Rect(LIST_X, LIST_Y + i * (ROW_H + ROW_GAP), LIST_W, ROW_H)

    def _name_field(self) -> pygame.Rect:
        return pygame.Rect(EDIT_X + 60, EDIT_Y, EDIT_W - 60, FIELD_H)

    def _id_field(self) -> pygame.Rect:
        return pygame.Rect(EDIT_X + 60, EDIT_Y + FIELD_H + FIELD_GAP, EDIT_W - 60, FIELD_H)

    def _cost_field(self) -> pygame.Rect:
        return pygame.Rect(EDIT_X + 60, EDIT_Y + (FIELD_H + FIELD_GAP) * 2, 100, FIELD_H)

    def _add_ship_btn(self) -> pygame.Rect:
        return pygame.Rect(EDIT_X, EDIT_Y + (FIELD_H + FIELD_GAP) * 3 + 4, 100, 30)

    def _new_preset_btn(self) -> pygame.Rect:
        return pygame.Rect(LIST_X, LIST_Y + MAX_VISIBLE * (ROW_H + ROW_GAP) + 10, LIST_W, 34)

    def _ship_rows_y0(self) -> int:
        return EDIT_Y + (FIELD_H + FIELD_GAP) * 3 + 44

    # -- scene protocol --

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        self._ensure_loaded(gs)
        return None

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover = None
            if self._add_ship_btn().collidepoint(mx, my):
                self._hover = "add_ship"
            elif self._new_preset_btn().collidepoint(mx, my):
                self._hover = "new_preset"

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            gs.bg_editor.focus = None
            if self._name_field().collidepoint(mx, my):
                gs.bg_editor.focus = "name"
            elif self._id_field().collidepoint(mx, my):
                gs.bg_editor.focus = "id"
            elif self._cost_field().collidepoint(mx, my):
                gs.bg_editor.focus = "cost"

            # List click
            presets = gs.bg_editor.presets
            scroll = gs.bg_editor.list_scroll
            for vi in range(min(MAX_VISIBLE, len(presets) - scroll)):
                if self._list_row_rect(vi).collidepoint(mx, my):
                    self._apply_fields(gs)
                    gs.bg_editor.selected_i = scroll + vi
                    self._sync_fields(gs)
                    gs.audio.play_positive()
                    break

            if self._new_preset_btn().collidepoint(mx, my):
                self._apply_fields(gs)
                n = len(presets) + 1
                presets.append(BattlegroupPreset(
                    preset_id=f"bg_{n}", name=f"BG {n}", deploy_cost=100))
                gs.bg_editor.selected_i = len(presets) - 1
                self._sync_fields(gs)
                gs.audio.play_positive()

            if self._add_ship_btn().collidepoint(mx, my):
                cap_names = gs.cap_names_menu
                pick = gs.bg_editor.ship_pick_i % len(cap_names) if cap_names else 0
                cls = cap_names[pick] if cap_names else "Destroyer"
                gs.bg_editor.rows.append({"class_name": cls, "label": ""})
                gs.bg_editor.ship_pick_i = (pick + 1) % max(1, len(cap_names))
                gs.audio.play_positive()

            # Ship row delete (click far right)
            y0 = self._ship_rows_y0()
            for ri, row in enumerate(gs.bg_editor.rows):
                ry = y0 + ri * (SHIP_ROW_H + SHIP_ROW_GAP)
                del_r = pygame.Rect(EDIT_X + EDIT_W - 40, ry, 30, SHIP_ROW_H)
                if del_r.collidepoint(mx, my):
                    gs.bg_editor.rows.pop(ri)
                    gs.audio.play_positive()
                    break

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._save(gs)
                gs.audio.play_positive()
                return "config"
            if event.key == pygame.K_TAB:
                focus_cycle = ["name", "id", "cost"]
                cur = gs.bg_editor.focus
                if cur in focus_cycle:
                    ni = (focus_cycle.index(cur) + 1) % len(focus_cycle)
                    gs.bg_editor.focus = focus_cycle[ni]
                else:
                    gs.bg_editor.focus = "name"
                return None

            focus = gs.bg_editor.focus
            if focus == "name":
                if event.key == pygame.K_BACKSPACE:
                    gs.bg_editor.name_buf = gs.bg_editor.name_buf[:-1]
                elif event.unicode and len(gs.bg_editor.name_buf) < 48:
                    gs.bg_editor.name_buf += event.unicode
            elif focus == "id":
                if event.key == pygame.K_BACKSPACE:
                    gs.bg_editor.id_buf = gs.bg_editor.id_buf[:-1]
                elif event.unicode and len(gs.bg_editor.id_buf) < 32:
                    gs.bg_editor.id_buf += event.unicode
            elif focus == "cost":
                if event.key == pygame.K_BACKSPACE:
                    gs.bg_editor.cost_buf = gs.bg_editor.cost_buf[:-1]
                elif event.unicode and event.unicode.isdigit() and len(gs.bg_editor.cost_buf) < 6:
                    gs.bg_editor.cost_buf += event.unicode

        elif event.type == pygame.MOUSEWHEEL:
            presets = gs.bg_editor.presets
            gs.bg_editor.list_scroll = max(
                0, min(gs.bg_editor.list_scroll - event.y,
                       max(0, len(presets) - MAX_VISIBLE)))
        return None

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        screen.fill(BG_DEEP)
        draw_starfield(screen, gs.stars, gs.camera.cam_x, gs.camera.cam_y, WIDTH, HEIGHT)

        title = gs.fonts.big.render("FLEET EDITOR", True, TEXT_ACCENT)
        screen.blit(title, (LIST_X, 20))
        save_path = gs.fonts.micro.render(gs.bg_editor.path, True, TEXT_DIM)
        screen.blit(save_path, (LIST_X, 50))

        # Preset list
        presets = gs.bg_editor.presets
        scroll = gs.bg_editor.list_scroll
        for vi in range(min(MAX_VISIBLE, len(presets) - scroll)):
            pi = scroll + vi
            r = self._list_row_rect(vi)
            sel = pi == gs.bg_editor.selected_i
            fill = BTN_FILL_HOT if sel else BTN_FILL
            bd = ACCENT_GREEN if sel else BORDER_BTN
            pygame.draw.rect(screen, fill, r, border_radius=4)
            pygame.draw.rect(screen, bd, r, width=1, border_radius=4)
            p = presets[pi]
            t = gs.fonts.tiny.render(f"{p.name}  ({p.preset_id})", True, TEXT_PRIMARY)
            screen.blit(t, (r.x + 6, r.centery - t.get_height() // 2))

        draw_button(screen, self._new_preset_btn(), "+ New Preset", gs.fonts.main,
                    hot=self._hover == "new_preset", accent=ACCENT_GREEN)

        # Edit panel
        ep = pygame.Rect(EDIT_X - 10, EDIT_Y - 30, EDIT_W + 20, HEIGHT - EDIT_Y)
        draw_panel(screen, ep)
        eh = gs.fonts.main.render("EDIT PRESET", True, TEXT_ACCENT)
        screen.blit(eh, (EDIT_X, EDIT_Y - 24))

        nl = gs.fonts.tiny.render("Name:", True, TEXT_SECONDARY)
        screen.blit(nl, (EDIT_X, EDIT_Y + 4))
        draw_text_field(screen, self._name_field(), gs.bg_editor.name_buf,
                        gs.fonts.main, active=gs.bg_editor.focus == "name")

        il = gs.fonts.tiny.render("ID:", True, TEXT_SECONDARY)
        screen.blit(il, (EDIT_X, EDIT_Y + FIELD_H + FIELD_GAP + 4))
        draw_text_field(screen, self._id_field(), gs.bg_editor.id_buf,
                        gs.fonts.main, active=gs.bg_editor.focus == "id")

        cl = gs.fonts.tiny.render("Cost:", True, TEXT_SECONDARY)
        screen.blit(cl, (EDIT_X, EDIT_Y + (FIELD_H + FIELD_GAP) * 2 + 4))
        draw_text_field(screen, self._cost_field(), gs.bg_editor.cost_buf,
                        gs.fonts.main, active=gs.bg_editor.focus == "cost")

        draw_button(screen, self._add_ship_btn(), "+ Ship", gs.fonts.main,
                    hot=self._hover == "add_ship")

        # Design rows
        y0 = self._ship_rows_y0()
        for ri, row in enumerate(gs.bg_editor.rows):
            ry = y0 + ri * (SHIP_ROW_H + SHIP_ROW_GAP)
            r = pygame.Rect(EDIT_X, ry, EDIT_W - 50, SHIP_ROW_H)
            pygame.draw.rect(screen, BTN_FILL, r, border_radius=3)
            pygame.draw.rect(screen, BORDER_BTN, r, width=1, border_radius=3)
            cls = row.get("class_name", "?")
            lbl = row.get("label", "")
            t = gs.fonts.tiny.render(f"{cls}  {lbl}", True, TEXT_PRIMARY)
            screen.blit(t, (r.x + 6, r.centery - t.get_height() // 2))
            # Delete button
            del_r = pygame.Rect(EDIT_X + EDIT_W - 40, ry, 30, SHIP_ROW_H)
            pygame.draw.rect(screen, (80, 30, 30), del_r, border_radius=3)
            xt = gs.fonts.tiny.render("X", True, (255, 120, 120))
            screen.blit(xt, (del_r.centerx - xt.get_width() // 2,
                             del_r.centery - xt.get_height() // 2))

        hint = gs.fonts.micro.render(
            "ESC -- save & back  |  TAB -- cycle fields", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))
