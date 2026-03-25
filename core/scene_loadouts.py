"""Ship loadouts scene — build and preview the initial fleet before combat."""
from __future__ import annotations

import random
import time
from typing import Any, List, Optional, Tuple

import pygame

from draw import (
    BG_DEEP, BG_PANEL, BORDER_PANEL, BORDER_BTN, BORDER_BTN_HOT,
    BTN_FILL, BTN_FILL_HOT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DIM,
    TEXT_ACCENT, ACCENT_GREEN, ACCENT_RED,
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

try:
    from fleet_deployment import (
        DEPLOYMENT_MIN_CAPITALS,
        DEPLOYMENT_STARTING_SCRAP,
        HULL_CLASSES_DEPLOYABLE,
        apply_deployment_weapon_choice,
        deployment_cost_for_class,
        group_max_range_from_weapons,
        loadout_try_add_capital,
        loadout_try_remove_capital,
        next_recruit_label,
        recruit_spawn_xy,
        resolve_weapon_entry,
        ship_class_by_name,
        sync_loadout_choice_map_for_group,
        weapon_loadout_options_expanded,
    )
    from demo_game import (
        RuntimeWeapon,
        apply_carrier_hangar_preset,
        build_initial_player_fleet,
        make_group,
        spawn_hangar_crafts,
    )
    from pvp_battlegroups import (
        BattlegroupPreset,
        default_battlegroups_path,
        load_battlegroups,
        save_battlegroups,
    )
except ImportError:
    from core.fleet_deployment import (
        DEPLOYMENT_MIN_CAPITALS,
        DEPLOYMENT_STARTING_SCRAP,
        HULL_CLASSES_DEPLOYABLE,
        apply_deployment_weapon_choice,
        deployment_cost_for_class,
        group_max_range_from_weapons,
        loadout_try_add_capital,
        loadout_try_remove_capital,
        next_recruit_label,
        recruit_spawn_xy,
        resolve_weapon_entry,
        ship_class_by_name,
        sync_loadout_choice_map_for_group,
        weapon_loadout_options_expanded,
    )
    from core.demo_game import (
        RuntimeWeapon,
        apply_carrier_hangar_preset,
        build_initial_player_fleet,
        make_group,
        spawn_hangar_crafts,
    )
    from core.pvp_battlegroups import (
        BattlegroupPreset,
        default_battlegroups_path,
        load_battlegroups,
        save_battlegroups,
    )

ROSTER_X = 40
ROSTER_Y = 72
ROSTER_W = 260
ROW_H = 44
ROW_GAP = 6
TOOL_Y = 46
DETAIL_X = ROSTER_X + ROSTER_W + 36
DETAIL_Y = ROSTER_Y
DETAIL_W = min(420, WIDTH - DETAIL_X - 200)
DEPLOY_BTN = pygame.Rect(WIDTH // 2 - 100, HEIGHT - 70, 200, 48)
BACK_BTN = pygame.Rect(20, HEIGHT - 70, 120, 48)

BTN_ADD = pygame.Rect(280, TOOL_Y, 88, 28)
BTN_NEXT_CLASS = pygame.Rect(BTN_ADD.right + 4, TOOL_Y, 36, 28)
BTN_REMOVE = pygame.Rect(BTN_NEXT_CLASS.right + 8, TOOL_Y, 100, 28)
PRESET_X = WIDTH - 360
BTN_PREV = pygame.Rect(PRESET_X, TOOL_Y, 72, 26)
BTN_NEXT = pygame.Rect(BTN_PREV.right + 6, TOOL_Y, 72, 26)
BTN_LOAD = pygame.Rect(PRESET_X, TOOL_Y + 32, 100, 26)
BTN_SAVE = pygame.Rect(BTN_LOAD.right + 8, TOOL_Y + 32, 100, 26)


def _player_capitals(preview: List[Any]) -> List[Any]:
    return [g for g in preview if g.side == "player" and not g.dead and g.render_capital]


def _sorted_roster(gs: Any) -> List[Any]:
    caps = _player_capitals(gs.loadout.preview_groups)
    return sorted(caps, key=lambda g: (g.label, g.class_name))


def _carrier_hangar_presets_list(data: dict, g: Any) -> Optional[List[dict]]:
    sc = ship_class_by_name(data, g.class_name)
    presets = (sc.get("hangar") or {}).get("loadout_presets") or []
    return presets if presets else None


def _hangar_preset_nav_rects(gs: Any, g: Any) -> Optional[Tuple[pygame.Rect, pygame.Rect]]:
    if _carrier_hangar_presets_list(gs.data, g) is None:
        return None
    sc = ship_class_by_name(gs.data, g.class_name)
    opts = weapon_loadout_options_expanded(gs.data, sc)
    y = DETAIL_Y + 96 + len(opts) * 28 + 18
    prev_r = pygame.Rect(DETAIL_X + 12, y, 88, 28)
    next_r = pygame.Rect(prev_r.right + 6, y, 88, 28)
    return prev_r, next_r


def _apply_row_hangar_choice(g: Any, row: dict, sc: dict) -> None:
    if not sc.get("hangar"):
        return
    hlc = row.get("hangar_loadout_choice")
    if hlc is None:
        return
    try:
        g.hangar_loadout_choice = int(hlc)
    except (TypeError, ValueError):
        pass


def _deploy_preview_to_combat(gs: Any) -> None:
    data = gs.data
    new_groups: List[Any] = []
    new_crafts: List[Any] = []
    for g in _sorted_roster(gs):
        oid = getattr(g, "owner_id", "player")
        cid = int(getattr(g, "color_id", 0))
        ng = make_group(
            data, "player", g.label, g.class_name, g.x, g.y,
            owner_id=str(oid), color_id=cid,
        )
        ng.hp = ng.max_hp
        ng.weapons = [
            RuntimeWeapon(w.name, w.projectile_name, w.fire_rate, 0.0)
            for w in g.weapons
        ]
        ng.max_range = group_max_range_from_weapons(data, ng.weapons)
        ng.hangar_loadout_choice = int(getattr(g, "hangar_loadout_choice", 0))
        ng.z = float(getattr(g, "z", ng.z))
        new_groups.append(ng)
        sc = ship_class_by_name(data, g.class_name)
        if sc.get("hangar"):
            new_crafts.extend(spawn_hangar_crafts(data, ng))
    gs.combat.groups = new_groups
    gs.combat.crafts = new_crafts


def _preview_from_mp_rows(gs: Any, rows: List[dict]) -> None:
    data = gs.data
    gs.loadout.preview_groups.clear()
    gs.loadout.preview_crafts.clear()
    gs.loadout.choice_map.clear()
    spent = 0
    for row in rows:
        cls = str(row.get("class_name") or "").strip()
        if not cls:
            continue
        spent += deployment_cost_for_class(data, cls)
        lbl = str(row.get("label") or "").strip()
        if not lbl:
            lbl = next_recruit_label(gs.loadout.preview_groups, cls)
        x, y = recruit_spawn_xy(gs.loadout.preview_groups)
        g = make_group(
            data, "player", lbl, cls, x, y,
            owner_id=gs.mp.player_name,
            color_id=int(getattr(gs.mp, "player_color_id", 0)),
        )
        sc = ship_class_by_name(data, cls)
        _apply_row_hangar_choice(g, row, sc)
        gs.loadout.preview_groups.append(g)
        if sc.get("hangar"):
            gs.loadout.preview_crafts.extend(spawn_hangar_crafts(data, g))
        if sc.get("weapon_loadout_options"):
            sync_loadout_choice_map_for_group(data, g, gs.loadout.choice_map)
    gs.loadout.deployment_scrap[0] = max(0, DEPLOYMENT_STARTING_SCRAP - spent)


def _preview_from_battlegroup_rows(gs: Any, rows: List[dict]) -> None:
    data = gs.data
    gs.loadout.preview_groups.clear()
    gs.loadout.preview_crafts.clear()
    gs.loadout.choice_map.clear()
    spent = 0
    for row in rows:
        cls = str(row.get("class_name") or "").strip()
        if not cls:
            continue
        spent += deployment_cost_for_class(data, cls)
        lbl = str(row.get("label") or "").strip()
        if not lbl:
            lbl = next_recruit_label(gs.loadout.preview_groups, cls)
        x, y = recruit_spawn_xy(gs.loadout.preview_groups)
        g = make_group(data, "player", lbl, cls, x, y)
        sc = ship_class_by_name(data, cls)
        _apply_row_hangar_choice(g, row, sc)
        gs.loadout.preview_groups.append(g)
        if sc.get("hangar"):
            gs.loadout.preview_crafts.extend(spawn_hangar_crafts(data, g))
        if sc.get("weapon_loadout_options"):
            sync_loadout_choice_map_for_group(data, g, gs.loadout.choice_map)
    gs.loadout.deployment_scrap[0] = max(0, DEPLOYMENT_STARTING_SCRAP - spent)


class LoadoutsScene:
    def __init__(self) -> None:
        self._hover_deploy = False
        self._hover_back = False
        self._hover_row: int = -1
        self._hover_add = False
        self._hover_remove = False
        self._hover_prev = False
        self._hover_next = False
        self._hover_load = False
        self._hover_save = False
        self._weapon_hover: int = -1
        self._hover_hangar_prev = False
        self._hover_hangar_next = False
        self._add_class_i: int = 0
        self._preset_i: int = 0
        self._presets_cache: List[BattlegroupPreset] = []
        self._presets_path: str = ""

    def _is_mp(self, gs: Any) -> bool:
        return gs.mp.loadouts_active

    def _ensure_preview(self, gs: Any) -> None:
        if _player_capitals(gs.loadout.preview_groups):
            return
        if self._is_mp(gs):
            stored = gs.mp.player_fleet_designs.get(gs.mp.player_name)
            if stored:
                _preview_from_mp_rows(gs, stored)
                return
            groups, crafts = build_initial_player_fleet(
                gs.data,
                owner_id=gs.mp.player_name,
                color_id=gs.mp.player_color_id,
                label_prefix=f"{gs.mp.player_name}:",
            )
        else:
            groups, crafts = build_initial_player_fleet(gs.data)
        gs.loadout.preview_groups = list(groups)
        gs.loadout.preview_crafts = list(crafts)
        gs.loadout.choice_map.clear()
        gs.loadout.deployment_scrap[0] = DEPLOYMENT_STARTING_SCRAP
        for g in _player_capitals(gs.loadout.preview_groups):
            sc = ship_class_by_name(gs.data, g.class_name)
            if sc.get("weapon_loadout_options"):
                sync_loadout_choice_map_for_group(gs.data, g, gs.loadout.choice_map)

    def _reload_presets(self) -> None:
        path = default_battlegroups_path()
        self._presets_path = path
        self._presets_cache = load_battlegroups(path)
        if self._preset_i >= len(self._presets_cache):
            self._preset_i = max(0, len(self._presets_cache) - 1)

    def _weapon_slot_rects(self, gs: Any, g: Any) -> List[Tuple[int, pygame.Rect]]:
        sc = ship_class_by_name(gs.data, g.class_name)
        opts = weapon_loadout_options_expanded(gs.data, sc)
        rects: List[Tuple[int, pygame.Rect]] = []
        y = DETAIL_Y + 96
        for si, _slot in enumerate(opts):
            rects.append((si, pygame.Rect(DETAIL_X + 12, y, DETAIL_W - 24, 24)))
            y += 28
        return rects

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        self._ensure_preview(gs)
        return None

    def handle_event(self, event: pygame.event.Event, gs: Any,
                     ctx: RunContext) -> Optional[str]:
        self._ensure_preview(gs)

        if event.type == pygame.MOUSEMOTION:
            mx, my = ctx.to_internal(event.pos)
            self._hover_deploy = DEPLOY_BTN.collidepoint(mx, my)
            self._hover_back = BACK_BTN.collidepoint(mx, my)
            self._hover_add = BTN_ADD.collidepoint(mx, my)
            self._hover_next_class = BTN_NEXT_CLASS.collidepoint(mx, my)
            self._hover_remove = BTN_REMOVE.collidepoint(mx, my)
            self._hover_prev = BTN_PREV.collidepoint(mx, my)
            self._hover_next = BTN_NEXT.collidepoint(mx, my)
            self._hover_load = BTN_LOAD.collidepoint(mx, my)
            self._hover_save = BTN_SAVE.collidepoint(mx, my)
            self._hover_row = -1
            roster = _sorted_roster(gs)
            for i in range(len(roster)):
                r = pygame.Rect(ROSTER_X, ROSTER_Y + i * (ROW_H + ROW_GAP), ROSTER_W, ROW_H)
                if r.collidepoint(mx, my):
                    self._hover_row = i
            self._weapon_hover = -1
            self._hover_hangar_prev = False
            self._hover_hangar_next = False
            if 0 <= gs.loadout.selected_i < len(roster):
                g = roster[gs.loadout.selected_i]
                for si, wr in self._weapon_slot_rects(gs, g):
                    if wr.collidepoint(mx, my):
                        self._weapon_hover = si
                        break
                nav = _hangar_preset_nav_rects(gs, g)
                if nav is not None:
                    pr, nr = nav
                    self._hover_hangar_prev = pr.collidepoint(mx, my)
                    self._hover_hangar_next = nr.collidepoint(mx, my)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = ctx.to_internal(event.pos)
            if DEPLOY_BTN.collidepoint(mx, my):
                gs.audio.play_positive()
                if self._is_mp(gs):
                    return self._save_and_return(gs)
                return self._deploy(gs)
            if BACK_BTN.collidepoint(mx, my):
                gs.audio.play_positive()
                if self._is_mp(gs):
                    return "mp_lobby"
                return "config"
            if BTN_NEXT_CLASS.collidepoint(mx, my):
                self._add_class_i = (self._add_class_i + 1) % len(HULL_CLASSES_DEPLOYABLE)
                gs.audio.play_positive()
                return None
            if BTN_ADD.collidepoint(mx, my):
                cls = HULL_CLASSES_DEPLOYABLE[self._add_class_i % len(HULL_CLASSES_DEPLOYABLE)]
                if loadout_try_add_capital(
                    gs.data,
                    gs.loadout.preview_groups,
                    gs.loadout.preview_crafts,
                    cls,
                    gs.loadout.deployment_scrap,
                    gs.loadout.choice_map,
                ):
                    gs.audio.play_positive()
                else:
                    gs.audio.play_negative()
                return None
            if BTN_REMOVE.collidepoint(mx, my):
                roster = _sorted_roster(gs)
                if 0 <= gs.loadout.selected_i < len(roster):
                    g = roster[gs.loadout.selected_i]
                    if loadout_try_remove_capital(
                        gs.data,
                        gs.loadout.preview_groups,
                        gs.loadout.preview_crafts,
                        g,
                        gs.loadout.deployment_scrap,
                        gs.loadout.choice_map,
                    ):
                        gs.audio.play_positive()
                        gs.loadout.selected_i = min(
                            gs.loadout.selected_i,
                            max(0, len(_sorted_roster(gs)) - 1),
                        )
                    else:
                        gs.audio.play_negative()
                return None
            if BTN_PREV.collidepoint(mx, my):
                self._reload_presets()
                if self._presets_cache:
                    self._preset_i = (self._preset_i - 1) % len(self._presets_cache)
                    gs.audio.play_positive()
                return None
            if BTN_NEXT.collidepoint(mx, my):
                self._reload_presets()
                if self._presets_cache:
                    self._preset_i = (self._preset_i + 1) % len(self._presets_cache)
                    gs.audio.play_positive()
                return None
            if BTN_LOAD.collidepoint(mx, my):
                self._reload_presets()
                if self._presets_cache and 0 <= self._preset_i < len(self._presets_cache):
                    p = self._presets_cache[self._preset_i]
                    _preview_from_battlegroup_rows(gs, list(p.design_rows))
                    gs.loadout.selected_i = 0
                    gs.audio.play_positive()
                else:
                    gs.audio.play_negative()
                return None
            if BTN_SAVE.collidepoint(mx, my):
                self._export_preset(gs)
                return None

            roster = _sorted_roster(gs)
            for i in range(len(roster)):
                r = pygame.Rect(ROSTER_X, ROSTER_Y + i * (ROW_H + ROW_GAP), ROSTER_W, ROW_H)
                if r.collidepoint(mx, my):
                    gs.loadout.selected_i = i
                    gs.audio.play_positive()
                    return None

            if 0 <= gs.loadout.selected_i < len(roster):
                g = roster[gs.loadout.selected_i]
                nav = _hangar_preset_nav_rects(gs, g)
                if nav is not None:
                    pr, nr = nav
                    presets = _carrier_hangar_presets_list(gs.data, g) or []
                    npre = len(presets)
                    if npre <= 0:
                        return None
                    cur_i = max(0, min(int(getattr(g, "hangar_loadout_choice", 0)), npre - 1))
                    if pr.collidepoint(mx, my):
                        new_i = (cur_i - 1) % npre
                        if apply_carrier_hangar_preset(
                            gs.data, g, new_i,
                            gs.loadout.preview_crafts, gs.loadout.deployment_scrap,
                        ):
                            gs.audio.play_positive()
                        else:
                            gs.audio.play_negative()
                        return None
                    if nr.collidepoint(mx, my):
                        new_i = (cur_i + 1) % npre
                        if apply_carrier_hangar_preset(
                            gs.data, g, new_i,
                            gs.loadout.preview_crafts, gs.loadout.deployment_scrap,
                        ):
                            gs.audio.play_positive()
                        else:
                            gs.audio.play_negative()
                        return None
                for si, wr in self._weapon_slot_rects(gs, g):
                    if wr.collidepoint(mx, my):
                        sc = ship_class_by_name(gs.data, g.class_name)
                        opts = weapon_loadout_options_expanded(gs.data, sc)
                        if 0 <= si < len(opts):
                            n = len(opts[si]["choices"])
                            if n <= 0:
                                break
                            key = (g.label, si)
                            cur = gs.loadout.choice_map.get(key, 0)
                            nxt = (cur + 1) % n
                            if apply_deployment_weapon_choice(
                                gs.data, g, si, nxt,
                                gs.loadout.choice_map,
                                gs.loadout.deployment_scrap,
                            ):
                                gs.audio.play_positive()
                            else:
                                gs.audio.play_negative()
                        return None

        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                gs.audio.play_positive()
                if self._is_mp(gs):
                    return self._save_and_return(gs)
                return self._deploy(gs)
            if event.key == pygame.K_ESCAPE:
                return "mp_lobby" if self._is_mp(gs) else "config"
        return None

    def _export_preset(self, gs: Any) -> None:
        roster = _sorted_roster(gs)
        if not roster:
            gs.audio.play_negative()
            return
        rows = []
        for g in roster:
            row: dict = {"class_name": g.class_name, "label": g.label}
            if g.class_name == "Carrier":
                row["hangar_loadout_choice"] = int(getattr(g, "hangar_loadout_choice", 0))
            rows.append(row)
        cost = sum(deployment_cost_for_class(gs.data, g.class_name) for g in roster)
        pid = f"sp_export_{int(time.time())}"
        preset = BattlegroupPreset(
            preset_id=pid,
            name=f"Exported {len(roster)} ships",
            deploy_cost=cost,
            design_rows=rows,
            entry_tag="spawn_edge",
        )
        self._reload_presets()
        self._presets_cache.append(preset)
        try:
            save_battlegroups(self._presets_path, self._presets_cache)
            self._preset_i = len(self._presets_cache) - 1
            gs.audio.play_positive()
        except Exception:
            gs.audio.play_negative()

    def _save_and_return(self, gs: Any) -> str:
        rows = []
        for g in _sorted_roster(gs):
            row: dict = {"class_name": g.class_name, "label": g.label}
            if g.class_name == "Carrier":
                row["hangar_loadout_choice"] = int(getattr(g, "hangar_loadout_choice", 0))
            rows.append(row)
        gs.mp.player_fleet_designs[gs.mp.player_name] = rows
        gs.mp.loadouts_active = False
        return "mp_lobby"

    def _deploy(self, gs: Any) -> str:
        _deploy_preview_to_combat(gs)
        gs.round.round_idx = 1
        gs.round.outcome = None
        gs.round.phase = "combat"
        from draw import clamp_camera, VIEW_W, VIEW_H, WORLD_W, WORLD_H
        seed = round_seed(1)
        gs.combat.mission = begin_combat_round(
            gs.data, gs.combat.groups, 1,
            random.Random(seed), gs.battle_obstacles)
        try:
            from combat import reset_combat_control_groups_for_spawn
        except ImportError:
            from core.combat import reset_combat_control_groups_for_spawn
        reset_combat_control_groups_for_spawn(
            gs.combat.groups, gs.combat.control_groups, gs.combat.cg_weapons_free)
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
        self._ensure_preview(gs)
        if not self._presets_cache and not self._presets_path:
            self._reload_presets()

        screen.fill(BG_DEEP)

        title = gs.fonts.big.render("FLEET LOADOUTS", True, TEXT_ACCENT)
        screen.blit(title, (ROSTER_X, 14))

        scrap_t = gs.fonts.tiny.render(
            f"Scrap: {gs.loadout.deployment_scrap[0]}  (min {DEPLOYMENT_MIN_CAPITALS} capitals)",
            True, TEXT_SECONDARY,
        )
        screen.blit(scrap_t, (ROSTER_X, TOOL_Y + 4))

        add_lbl = f"+ Add {HULL_CLASSES_DEPLOYABLE[self._add_class_i % len(HULL_CLASSES_DEPLOYABLE)]}"
        draw_button(screen, BTN_ADD, add_lbl[:18], gs.fonts.micro,
                    hot=self._hover_add, accent=TEXT_ACCENT)
        draw_button(screen, BTN_REMOVE, "Remove hull", gs.fonts.micro,
                    hot=self._hover_remove, accent=ACCENT_RED)

        roster = _sorted_roster(gs)
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

        if 0 <= gs.loadout.selected_i < len(roster):
            g = roster[gs.loadout.selected_i]
            sc = ship_class_by_name(gs.data, g.class_name)
            opts = weapon_loadout_options_expanded(gs.data, sc)
            hangar_extra = 62 if _carrier_hangar_presets_list(gs.data, g) else 0
            base_bottom = 96 + len(opts) * 28 + hangar_extra + 36
            dp_h = min(max(200, base_bottom), HEIGHT - DETAIL_Y - 100)
            dp = pygame.Rect(DETAIL_X, DETAIL_Y, DETAIL_W, dp_h)
            draw_panel(screen, dp)
            name = gs.fonts.big.render(f"{g.label} -- {g.class_name}", True, TEXT_ACCENT)
            screen.blit(name, (dp.x + 14, dp.y + 12))
            for si, slot in enumerate(opts):
                choices = slot["choices"]
                key = (g.label, si)
                ci = gs.loadout.choice_map.get(key, 0)
                if 0 <= ci < len(choices):
                    ch = choices[ci]
                    wn, pn, _fr = resolve_weapon_entry(gs.data, ch)
                    line = f"{slot.get('label', 'Mount')}: {wn} ({pn})"
                else:
                    line = f"Slot {si}"
                y = DETAIL_Y + 96 + si * 28
                wr = pygame.Rect(DETAIL_X + 12, y, DETAIL_W - 24, 24)
                hot = self._weapon_hover == si
                pygame.draw.rect(
                    screen, BTN_FILL_HOT if hot else (22, 32, 46), wr, border_radius=4)
                pygame.draw.rect(
                    screen, BORDER_BTN_HOT if hot else BORDER_BTN, wr, width=1, border_radius=4)
                wt = gs.fonts.tiny.render(line[:52], True, TEXT_PRIMARY)
                screen.blit(wt, (wr.x + 6, wr.y + 4))
            hpresets = _carrier_hangar_presets_list(gs.data, g)
            if hpresets:
                hy = DETAIL_Y + 96 + len(opts) * 28 + 12
                hci = max(0, min(int(getattr(g, "hangar_loadout_choice", 0)), len(hpresets) - 1))
                plab = hpresets[hci].get("label", f"Preset {hci}")
                pcost = int(hpresets[hci].get("scrap_cost", 0))
                ht = gs.fonts.tiny.render(
                    f"Hangar: {plab}  (scrap {pcost})", True, TEXT_SECONDARY)
                screen.blit(ht, (dp.x + 14, hy))
                nav = _hangar_preset_nav_rects(gs, g)
                if nav is not None:
                    pr, nr = nav
                    draw_button(
                        screen, pr, "Prev", gs.fonts.micro,
                        hot=self._hover_hangar_prev, accent=TEXT_ACCENT)
                    draw_button(
                        screen, nr, "Next", gs.fonts.micro,
                        hot=self._hover_hangar_next, accent=TEXT_ACCENT)
            hint_w = gs.fonts.micro.render("Click weapon row to cycle (costs scrap)", True, TEXT_DIM)
            screen.blit(hint_w, (dp.x + 14, dp.bottom - 22))

        preset_title = gs.fonts.tiny.render("BATTLEGROUP PRESETS", True, TEXT_ACCENT)
        screen.blit(preset_title, (PRESET_X, TOOL_Y - 22))
        if self._presets_cache and 0 <= self._preset_i < len(self._presets_cache):
            pn = self._presets_cache[self._preset_i].name[:28]
        else:
            pn = "(no presets file)"
        pname = gs.fonts.micro.render(pn, True, TEXT_SECONDARY)
        screen.blit(pname, (PRESET_X, TOOL_Y - 6))
        draw_button(screen, BTN_PREV, "<", gs.fonts.micro, hot=self._hover_prev)
        draw_button(screen, BTN_NEXT, ">", gs.fonts.micro, hot=self._hover_next)
        draw_button(screen, BTN_LOAD, "Load", gs.fonts.micro, hot=self._hover_load, accent=ACCENT_GREEN)
        draw_button(screen, BTN_SAVE, "Save", gs.fonts.micro, hot=self._hover_save, accent=TEXT_ACCENT)

        deploy_label = "DONE" if self._is_mp(gs) else "DEPLOY"
        back_label = "LOBBY" if self._is_mp(gs) else "Back"
        draw_button(screen, DEPLOY_BTN, deploy_label, gs.fonts.main,
                    hot=self._hover_deploy, accent=ACCENT_GREEN)
        draw_button(screen, BACK_BTN, back_label, gs.fonts.main,
                    hot=self._hover_back)

        cur_cls = HULL_CLASSES_DEPLOYABLE[self._add_class_i % len(HULL_CLASSES_DEPLOYABLE)]
        hint = gs.fonts.micro.render(
            f"ENTER deploy  |  ESC back  |  Next hull: {cur_cls}  (use > then Add)", True, TEXT_DIM)
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 20))
