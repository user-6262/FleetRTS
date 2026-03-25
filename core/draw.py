"""Shared rendering primitives for FleetRTS.

Every visual element — ships, ordnance, fog, UI chrome — is drawn through
functions in this module.  Scene files import what they need; nothing here
imports from scene files or engine.py.
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Set, Tuple

import pygame

try:
    from combat_constants import FOG_CH, FOG_CW, WORLD_H, WORLD_W
    from combat_engine import fog_cell_explored, fog_cell_visible
    from combat_ordnance import (
        compute_pd_stress_ratio,
        is_valid_attack_focus_for_side,
        pd_stress_color,
        pd_stress_display_level,
    )
    from demo_game import (
        Asteroid, BallisticSlug, Craft, FogState, Group,
        GroundObjective, Missile, SensorGhost, VFXBeam, VFXSpark,
    )
except ImportError:
    from core.combat_constants import FOG_CH, FOG_CW, WORLD_H, WORLD_W
    from core.combat_engine import fog_cell_explored, fog_cell_visible
    from core.combat_ordnance import (
        compute_pd_stress_ratio,
        is_valid_attack_focus_for_side,
        pd_stress_color,
        pd_stress_display_level,
    )
    from core.demo_game import (
        Asteroid, BallisticSlug, Craft, FogState, Group,
        GroundObjective, Missile, SensorGhost, VFXBeam, VFXSpark,
    )

# ---------------------------------------------------------------------------
# Screen geometry
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1720, 990
BOTTOM_BAR_H = 128
VIEW_W = WIDTH
VIEW_H = HEIGHT - BOTTOM_BAR_H

# ---------------------------------------------------------------------------
# Theme palette
# ---------------------------------------------------------------------------
BG_DEEP = (4, 12, 18)
BG_PANEL = (10, 18, 30)
BG_CHROME = (14, 22, 34)
BORDER_PANEL = (55, 100, 130)
BORDER_BTN = (68, 90, 118)
BORDER_BTN_HOT = (130, 175, 215)
BTN_FILL = (30, 42, 58)
BTN_FILL_HOT = (44, 62, 86)
TEXT_PRIMARY = (210, 225, 240)
TEXT_SECONDARY = (170, 190, 210)
TEXT_DIM = (130, 148, 168)
TEXT_ACCENT = (100, 200, 240)
TEXT_WARN = (255, 180, 90)
ACCENT_GREEN = (80, 200, 130)
ACCENT_RED = (255, 85, 85)
ACCENT_TEAL = (0, 72, 58)
SELECT_YELLOW = (255, 240, 120)

# In-battle navy unit cards (capital > strike craft > ordnance)
NAVY_GLYPH_FILL = (6, 12, 26)
NAVY_GLYPH_EDGE = (40, 68, 108)
NAVY_CARD_FACE = (12, 20, 38)
NAVY_CARD_FACE_HI = (20, 32, 54)
NAVY_CARD_OUTLINE = (52, 82, 118)
NAVY_CARD_OUTLINE_SEL = (240, 215, 110)
NAVY_BAR_TROUGH = (16, 22, 34)

MP_PLAYER_PALETTE: List[Tuple[int, int, int]] = [
    (90, 170, 255), (120, 210, 150), (255, 170, 95),
    (220, 130, 255), (255, 225, 110), (255, 120, 120),
]

# ---------------------------------------------------------------------------
# 2.5-D projection
# ---------------------------------------------------------------------------
Z_VIS_LIFT = 0.36
Z_SCALE_K = 0.0042
Z_MIN_SCALE = 0.58
ASTEROID_VISUAL_Z = 9.0
CAM_PAN_SPEED = 520.0


def project_visual(wx: float, wy: float, wz: float) -> Tuple[float, float, float]:
    sx = wx
    sy = wy - wz * Z_VIS_LIFT
    sc = max(Z_MIN_SCALE, 1.0 - wz * Z_SCALE_K)
    return sx, sy, sc


def world_to_screen(wx: float, wy: float, wz: float,
                    cam_x: float, cam_y: float) -> Tuple[float, float, float]:
    px, py, sc = project_visual(wx, wy, wz)
    return px - cam_x, py - cam_y, sc


def screen_to_world(mx: float, my: float,
                    cam_x: float, cam_y: float,
                    assume_z: float = 36.0) -> Tuple[float, float]:
    return mx + cam_x, my + cam_y + assume_z * Z_VIS_LIFT


def clamp_camera(cam_x: float, cam_y: float) -> Tuple[float, float]:
    max_cx = max(0.0, WORLD_W - VIEW_W)
    max_cy = max(0.0, WORLD_H - VIEW_H)
    return max(0.0, min(max_cx, cam_x)), max(0.0, min(max_cy, cam_y))

# ---------------------------------------------------------------------------
# Capital marker class scale (Frigate smallest → Carrier largest)
# ---------------------------------------------------------------------------
CAPITAL_MARKER_CLASS_SCALE: Dict[str, float] = {
    "Frigate": 0.68, "Destroyer": 0.90, "Cruiser": 1.22,
    "Battleship": 1.54, "Dreadnought": 2.16, "Carrier": 1.90,
}

# ---------------------------------------------------------------------------
# Player unit color
# ---------------------------------------------------------------------------

def player_unit_color(color_id: int, *, for_craft: bool = False) -> Tuple[int, int, int]:
    base = MP_PLAYER_PALETTE[max(0, min(int(color_id), len(MP_PLAYER_PALETTE) - 1))]
    if for_craft:
        return tuple(min(255, int(ch * 1.1)) for ch in base)  # type: ignore[return-value]
    return base

# ---------------------------------------------------------------------------
# Starfield
# ---------------------------------------------------------------------------

def draw_starfield(surf: pygame.Surface,
                   stars: List[Tuple[int, int, int]],
                   cam_x: float, cam_y: float,
                   vis_w: int = VIEW_W, vis_h: int = VIEW_H) -> None:
    for wx, wy, br in stars:
        sx = int(wx - cam_x)
        sy = int(wy - cam_y)
        if 0 <= sx < vis_w and 0 <= sy < vis_h:
            surf.set_at((sx, sy), (br, br, min(255, br + 40)))

# ---------------------------------------------------------------------------
# World edge
# ---------------------------------------------------------------------------

def draw_world_edge(surf: pygame.Surface, cam_x: float, cam_y: float) -> None:
    corners = [(0, 0), (WORLD_W, 0), (WORLD_W, WORLD_H), (0, WORLD_H), (0, 0)]
    for i in range(4):
        ax, ay = corners[i]
        bx, by = corners[i + 1]
        sax, say, _ = world_to_screen(ax, ay, 0.0, cam_x, cam_y)
        sbx, sby, _ = world_to_screen(bx, by, 0.0, cam_x, cam_y)
        pygame.draw.line(surf, ACCENT_TEAL, (int(sax), int(say)), (int(sbx), int(sby)), 2)

# ---------------------------------------------------------------------------
# Asteroids
# ---------------------------------------------------------------------------

def _asteroid_seed(o: Asteroid) -> int:
    return int(o.x * 31 + o.y * 17 + o.r * 7) & 0xFFFFFF

def draw_asteroids(surf: pygame.Surface, obstacles: List[Asteroid],
                   cam_x: float, cam_y: float, fog: FogState) -> None:
    batch: List[Tuple[float, Asteroid]] = []
    for o in obstacles:
        if not fog_cell_explored(fog, o.x, o.y):
            continue
        _, sy, _ = world_to_screen(o.x, o.y, ASTEROID_VISUAL_Z, cam_x, cam_y)
        batch.append((sy, o))
    batch.sort(key=lambda t: t[0], reverse=True)
    for _, o in batch:
        sx, sy, sc = world_to_screen(o.x, o.y, ASTEROID_VISUAL_Z, cam_x, cam_y)
        xi, yi = int(sx), int(sy)
        rng = random.Random(_asteroid_seed(o))
        rr = max(14, int(o.r * sc * 0.98))
        flat = 0.74
        n = 18
        pts: List[Tuple[int, int]] = []
        for i in range(n):
            ang = (i / n) * 2 * math.pi + rng.uniform(-0.07, 0.07)
            rad = rr * rng.uniform(0.86, 1.04)
            pts.append((int(xi + math.cos(ang) * rad), int(yi + math.sin(ang) * rad * flat)))
        pygame.draw.polygon(surf, (32, 36, 48), pts)
        facet = [pts[i] for i in range(0, n, 2)]
        if len(facet) >= 3:
            pygame.draw.polygon(surf, (52, 58, 72), facet[:n // 2 + 1])
        pygame.draw.polygon(surf, (88, 96, 112), pts, width=2)
        for _ in range(max(2, min(6, rr // 28))):
            ca = rng.uniform(0, 2 * math.pi)
            cd = rr * rng.uniform(0.12, 0.58)
            cw = max(4, int(rr * rng.uniform(0.07, 0.16)))
            ch = max(2, int(cw * 0.55))
            pygame.draw.ellipse(surf, (24, 28, 38), pygame.Rect(
                int(xi + math.cos(ca) * cd) - cw,
                int(yi + math.sin(ca) * cd * flat) - ch, cw * 2, ch * 2))
        gx = int(xi - rr * 0.28)
        gy = int(yi - rr * 0.22 * flat)
        pygame.draw.circle(surf, (118, 126, 138), (gx, gy), max(2, rr // 14))
        pygame.draw.circle(surf, (160, 168, 182), (gx, gy), max(1, rr // 22))

# ---------------------------------------------------------------------------
# Fog of war
# ---------------------------------------------------------------------------

def draw_fog_overlay(surf: pygame.Surface, fog: FogState,
                     cam_x: float, cam_y: float) -> None:
    ov = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
    unseen_rgba = (0, 0, 0, 240)
    memory_rgba = (0, 0, 0, 88)
    for cj in range(FOG_CH):
        for ci in range(FOG_CW):
            idx = ci + cj * FOG_CW
            if fog.visible[idx]:
                continue
            wx0 = ci / FOG_CW * WORLD_W
            wx1 = (ci + 1) / FOG_CW * WORLD_W
            wy0 = cj / FOG_CH * WORLD_H
            wy1 = (cj + 1) / FOG_CH * WORLD_H
            pts_o: List[Tuple[int, int]] = []
            for wx, wy in ((wx0, wy0), (wx1, wy0), (wx1, wy1), (wx0, wy1)):
                psx, psy, _ = world_to_screen(wx, wy, 22.0, cam_x, cam_y)
                pts_o.append((int(psx), int(psy)))
            if max(p[0] for p in pts_o) < -8 or min(p[0] for p in pts_o) > VIEW_W + 8:
                continue
            if max(p[1] for p in pts_o) < -8 or min(p[1] for p in pts_o) > VIEW_H + 8:
                continue
            fill = unseen_rgba if not fog.explored[idx] else memory_rgba
            pygame.draw.polygon(ov, fill, pts_o)
    edge = 64
    edge_rgba = (0, 0, 0, 160)
    pygame.draw.rect(ov, edge_rgba, (0, 0, VIEW_W, edge))
    pygame.draw.rect(ov, edge_rgba, (0, VIEW_H - edge, VIEW_W, edge))
    pygame.draw.rect(ov, edge_rgba, (0, 0, edge, VIEW_H))
    pygame.draw.rect(ov, edge_rgba, (VIEW_W - edge, 0, edge, VIEW_H))
    surf.blit(ov, (0, 0))

# ---------------------------------------------------------------------------
# Ship glyphs + navy HUD cards (hierarchy: capital > strike craft > ordnance)
# ---------------------------------------------------------------------------

def heading_for_group(g: Group) -> float:
    if g.waypoint:
        wx, wy = g.waypoint
        return math.atan2(wy - g.y, wx - g.x)
    return -math.pi / 2


def craft_type_abbrev(class_name: str) -> str:
    c = (class_name or "").strip()
    low = c.lower()
    if "bomber" in low:
        return "BOM"
    if "interceptor" in low:
        return "INT"
    if "fighter" in low:
        return "FIG"
    return (c[:3].upper() if c else "---")


def draw_capital(surf: pygame.Surface, x: float, y: float,
                 color: Tuple[int, int, int], heading: float,
                 scale: float = 1.0) -> None:
    xi, yi = int(x), int(y)
    w = int(22 * scale)
    h = int(14 * scale)
    rect = pygame.Rect(xi - w // 2, yi - h // 2, w, h)
    pygame.draw.rect(surf, NAVY_GLYPH_FILL, rect, border_radius=2)
    pygame.draw.rect(surf, color, rect, width=2, border_radius=2)
    L = int(12 * scale)
    hx = math.cos(heading) * L
    hy = math.sin(heading) * L
    tip = (xi + hx, yi + hy)
    left = (xi + math.cos(heading + 2.4) * 8 * scale,
            yi + math.sin(heading + 2.4) * 8 * scale)
    right = (xi + math.cos(heading - 2.4) * 8 * scale,
             yi + math.sin(heading - 2.4) * 8 * scale)
    pygame.draw.polygon(surf, NAVY_GLYPH_FILL, [tip, left, right])
    pygame.draw.polygon(surf, color, [tip, left, right], width=2)


def draw_craft(surf: pygame.Surface, x: float, y: float,
               color: Tuple[int, int, int], heading: float,
               size: float = 7.0) -> None:
    xi, yi = int(x), int(y)
    s = size
    p1 = (xi + math.cos(heading) * s, yi + math.sin(heading) * s)
    p2 = (xi + math.cos(heading + 2.35) * s * 0.55,
          yi + math.sin(heading + 2.35) * s * 0.55)
    p3 = (xi + math.cos(heading - 2.35) * s * 0.55,
          yi + math.sin(heading - 2.35) * s * 0.55)
    pygame.draw.polygon(surf, NAVY_GLYPH_FILL, [p1, p2, p3])
    pygame.draw.polygon(surf, color, [p1, p2, p3], width=2)


def draw_navy_hud_card(
    surf: pygame.Surface,
    tip_x: float,
    tip_y: float,
    sc: float,
    *,
    tier: int,
    line1: str,
    line2: Optional[str],
    hp_frac: Optional[float],
    accent: Tuple[int, int, int],
    selected: bool,
    font_top: pygame.font.Font,
    font_bot: pygame.font.Font,
) -> None:
    """Dark navy panel with a chevron pointing at the unit (tip = screen anchor)."""
    k = max(0.78, min(1.18, float(sc)))
    if tier == 0:
        pad_x, pad_y = 7, 5
        bar_h = max(4, int(5 * k))
        min_w, min_h = 96, 42
        radius = 5
    elif tier == 1:
        pad_x, pad_y = 3, 2
        bar_h = max(2, int(2.5 * k))
        min_w, min_h = 30, 18
        radius = 3
    else:
        pad_x, pad_y = 3, 2
        bar_h = 0
        min_w, min_h = 36, 18
        radius = 3

    t1 = font_top.render(line1[:36], True, TEXT_PRIMARY)
    t2 = font_bot.render((line2 or "")[:44], True, TEXT_SECONDARY) if line2 else None
    text_w = t1.get_width()
    if t2:
        text_w = max(text_w, t2.get_width())
    inner_h = t1.get_height() + ((t2.get_height() + 2) if t2 else 0)
    if hp_frac is not None and tier <= 1 and bar_h > 0:
        inner_h += bar_h + (3 if tier == 0 else 2)

    cw = max(int(min_w * k), text_w + pad_x * 2)
    ch = max(int(min_h * k), inner_h + pad_y * 2)
    ptr_h = max(5, int((9 if tier == 0 else 5 if tier == 1 else 4) * k))
    notch = max(5, min(cw // 2 - 4, int(14 * k)))

    cx = int(tip_x)
    top_y = int(tip_y) - ptr_h - ch
    rect = pygame.Rect(cx - cw // 2, top_y, cw, ch)
    border_col = NAVY_CARD_OUTLINE_SEL if selected else accent
    border_w = 2 if selected else 1

    pmid = rect.bottom
    pleft = (rect.left + notch, pmid)
    pright = (rect.right - notch, pmid)
    tip_pt = (int(tip_x), int(tip_y))
    pygame.draw.polygon(surf, NAVY_CARD_FACE, [pleft, pright, tip_pt])
    pygame.draw.polygon(surf, border_col, [pleft, pright, tip_pt], width=1)

    pygame.draw.rect(surf, NAVY_CARD_FACE, rect, border_radius=radius)
    strip_frac = 0.22 if tier == 1 else 0.36
    strip_h = max(3 if tier == 1 else 5, int(ch * strip_frac))
    strip = pygame.Rect(rect.left + 2, rect.top + 2, rect.w - 4, min(strip_h, rect.h - 4))
    pygame.draw.rect(surf, NAVY_CARD_FACE_HI, strip, border_radius=max(1, radius - 2))
    pygame.draw.line(surf, accent, (rect.left + 3, rect.top + 3), (rect.right - 3, rect.top + 3), 1)
    pygame.draw.rect(surf, border_col, rect, width=border_w, border_radius=radius)

    ty = rect.y + pad_y
    surf.blit(t1, (rect.x + pad_x, ty))
    ty += t1.get_height() + 1
    if t2:
        surf.blit(t2, (rect.x + pad_x, ty))
        ty += t2.get_height() + 2
    if hp_frac is not None and tier <= 1 and bar_h > 0:
        bw = cw - pad_x * 2
        bx = rect.x + pad_x
        frac = max(0.0, min(1.0, hp_frac))
        pygame.draw.rect(surf, NAVY_BAR_TROUGH, (bx, ty, bw, bar_h), border_radius=2)
        if frac > 0:
            fill_w = max(1, int(bw * frac))
            col = ACCENT_GREEN if frac > 0.35 else TEXT_WARN if frac > 0.15 else ACCENT_RED
            pygame.draw.rect(surf, col, (bx, ty, fill_w, bar_h), border_radius=2)


def draw_entity_plate(surf: pygame.Surface, font: pygame.font.Font,
                      font_tiny: pygame.font.Font,
                      x: float, y: float, label: str, cls: str,
                      hp: float, max_hp: float, compact: bool = False) -> None:
    """Legacy hook: same anchor semantics as before (y = point near top of ship)."""
    frac = max(0.0, min(1.0, hp / max_hp if max_hp > 0 else 0))
    draw_navy_hud_card(
        surf, x, y, 1.0,
        tier=0,
        line1=label if not compact else f"{label}  {cls}",
        line2=None if compact else cls,
        hp_frac=frac,
        accent=NAVY_CARD_OUTLINE,
        selected=False,
        font_top=font_tiny,
        font_bot=font_tiny,
    )


def draw_craft_tag(surf: pygame.Surface, font_micro: pygame.font.Font,
                   x: float, y: float, cls: str,
                   hp: float, max_hp: float) -> None:
    frac = max(0.0, min(1.0, hp / max_hp if max_hp > 0 else 0))
    ab = craft_type_abbrev(cls)
    draw_navy_hud_card(
        surf, x, y, 1.0,
        tier=1,
        line1=ab,
        line2=None,
        hp_frac=frac,
        accent=NAVY_CARD_OUTLINE,
        selected=False,
        font_top=font_micro,
        font_bot=font_micro,
    )

# ---------------------------------------------------------------------------
# Missiles (ordnance diamond style)
# ---------------------------------------------------------------------------
_MSL_ABBREV: Dict[str, Tuple[str, Tuple[int, int, int]]] = {
    "Fighter Missile": ("MSL", (110, 175, 255)),
    "Strike Missile": ("MSL", (255, 145, 72)),
    "Torpedo": ("TOR", (255, 108, 88)),
    "Bomber Torpedo": ("TOR", (255, 200, 95)),
}

def _missile_accent(proj_name: str, fallback: Tuple[int, int, int]) -> Tuple[str, Tuple[int, int, int]]:
    if proj_name in _MSL_ABBREV:
        return _MSL_ABBREV[proj_name]
    pn = proj_name.upper()
    if "EMP" in pn:
        return ("EMP", (200, 120, 255))
    if "TORP" in pn:
        return ("TOR", fallback)
    return ("MSL", fallback)

def draw_missile(surf: pygame.Surface, m: Missile,
                 cam_x: float, cam_y: float,
                 font_micro: Optional[pygame.font.Font] = None) -> None:
    ang = math.atan2(m.vy, m.vx) if math.hypot(m.vy, m.vx) > 0.1 else 0.0
    sx, sy, sc = world_to_screen(m.x, m.y, m.z, cam_x, cam_y)
    x, y = int(sx), int(sy)
    abbrev, ac = _missile_accent(m.proj_name, m.color)
    r_a = max(4.5, 6.0 * sc)
    r_b = max(2.8, 3.4 * sc)
    ca, sa = math.cos(ang), math.sin(ang)
    c2, s2 = math.cos(ang + math.pi / 2), math.sin(ang + math.pi / 2)
    pts = [
        (int(x + ca * r_a), int(y + sa * r_a)),
        (int(x + c2 * r_b), int(y + s2 * r_b)),
        (int(x - ca * r_a), int(y - sa * r_a)),
        (int(x - c2 * r_b), int(y - s2 * r_b)),
    ]
    flicker = 0.92 + 0.08 * math.sin(m.anim_t * 22.0)
    ac_l = tuple(min(255, int(ch * flicker)) for ch in ac)
    pygame.draw.polygon(surf, NAVY_GLYPH_FILL, pts)
    pygame.draw.polygon(surf, ac_l, pts, width=max(1, int(1.15 * sc)))
    wx = int(x - ca * r_a * 1.05)
    wy = int(y - sa * r_a * 1.05)
    wx2 = int(x - ca * r_a * 2.15)
    wy2 = int(y - sa * r_a * 2.15)
    dim = (ac_l[0] // 2 + 30, ac_l[1] // 2 + 25, ac_l[2] // 2 + 35)
    pygame.draw.line(surf, dim, (wx, wy), (wx2, wy2), max(1, int(sc)))
    if font_micro is not None:
        back = max(14.0, r_a + 10.0 * sc)
        tcx = x - ca * back
        tcy = y - sa * back
        draw_navy_hud_card(
            surf, tcx, tcy, sc,
            tier=2,
            line1=abbrev,
            line2=None,
            hp_frac=None,
            accent=ac_l,
            selected=False,
            font_top=font_micro,
            font_bot=font_micro,
        )

# ---------------------------------------------------------------------------
# Ballistics
# ---------------------------------------------------------------------------
SLUG_FADE_PER_SEC = 0.068
SLUG_FADE_MIN = 0.5

def draw_ballistic(surf: pygame.Surface, s: BallisticSlug,
                   cam_x: float, cam_y: float) -> None:
    sx, sy, sc = world_to_screen(s.x, s.y, s.z, cam_x, cam_y)
    xi, yi = int(sx), int(sy)
    fade = max(SLUG_FADE_MIN, min(1.0, 1.0 - s.age * SLUG_FADE_PER_SEC))
    def lit(rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
        return tuple(min(255, int(c * fade)) for c in rgb)  # type: ignore[return-value]
    r = max(2, int(3.2 * sc))
    tr = max(1, int(2.0 * sc))
    tx = int(sx - s.vx * 0.024)
    ty = int(sy - s.vy * 0.024)
    pygame.draw.circle(surf, lit((95, 22, 18)), (tx, ty), tr + 1)
    pygame.draw.circle(surf, lit((200, 48, 38)), (tx, ty), tr)
    pygame.draw.circle(surf, lit((248, 68, 52)), (xi, yi), r)
    if r > 2:
        pygame.draw.circle(surf, lit((240, 145, 118)), (xi, yi), max(1, r - 2))
    pygame.draw.circle(surf, lit((255, 235, 218)), (xi, yi), max(1, r // 3))

# ---------------------------------------------------------------------------
# VFX beams and sparks
# ---------------------------------------------------------------------------

def draw_vfx_beams(surf: pygame.Surface, beams: List[VFXBeam],
                   cam_x: float, cam_y: float) -> None:
    for b in beams:
        f = b.ttl / b.max_ttl if b.max_ttl > 0 else 0.0
        c = tuple(min(255, int(ch * (0.35 + 0.65 * f))) for ch in b.color)
        x0, y0, _ = world_to_screen(b.x0, b.y0, 35.0, cam_x, cam_y)
        x1, y1, _ = world_to_screen(b.x1, b.y1, 35.0, cam_x, cam_y)
        pygame.draw.line(surf, c, (int(x0), int(y0)), (int(x1), int(y1)), b.width)

def draw_vfx_sparks(surf: pygame.Surface, sparks: List[VFXSpark],
                    cam_x: float, cam_y: float) -> None:
    for s in sparks:
        f = s.ttl / s.max_ttl if s.max_ttl > 0 else 0.0
        c = tuple(min(255, int(ch * (0.45 + 0.55 * f))) for ch in s.color)
        sx, sy, _ = world_to_screen(s.x, s.y, 34.0, cam_x, cam_y)
        pygame.draw.circle(surf, c, (int(sx), int(sy)), s.radius)

# ---------------------------------------------------------------------------
# Sensor ghosts
# ---------------------------------------------------------------------------

def draw_sensor_ghosts(surf: pygame.Surface, font: pygame.font.Font,
                       ghosts: List[SensorGhost],
                       cam_x: float, cam_y: float) -> None:
    for gh in ghosts:
        sx, sy, sc = world_to_screen(gh.x, gh.y, 35.0, cam_x, cam_y)
        col = (180, 120, 255) if gh.quality < 0.5 else (255, 190, 120)
        r = max(10, int(22 * sc))
        pygame.draw.circle(surf, col, (int(sx), int(sy)), r, width=2)
        pygame.draw.circle(surf, col, (int(sx), int(sy)), max(6, r - 6), width=1)

# ---------------------------------------------------------------------------
# Active pings
# ---------------------------------------------------------------------------

def draw_active_pings(surf: pygame.Surface, pings: List[Any],
                      cam_x: float, cam_y: float) -> None:
    for p in pings:
        sx, sy, sc = world_to_screen(p.x, p.y, 0.0, cam_x, cam_y)
        r = max(8, int(p.radius * sc * 0.18))
        alpha = max(20, int(180 * (p.ttl / 1.1)))
        ring = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring, (100, 180, 255, alpha), (r + 2, r + 2), r, width=2)
        surf.blit(ring, (int(sx) - r - 2, int(sy) - r - 2))

# ---------------------------------------------------------------------------
# Attack focus rings
# ---------------------------------------------------------------------------

def draw_attack_focus_rings(surf: pygame.Surface, groups: List[Group],
                            cam_x: float, cam_y: float,
                            fog: Optional[FogState] = None) -> None:
    seen: Set[int] = set()
    for g in groups:
        if g.side != "player" or g.dead or not g.render_capital:
            continue
        t = g.attack_target
        if not is_valid_attack_focus_for_side("player", t):
            continue
        tid = id(t)
        if tid in seen:
            continue
        seen.add(tid)
        if fog is not None and not fog_cell_visible(fog, t.x, t.y):
            continue
        tz = t.z if isinstance(t, GroundObjective) else getattr(t, "z", 35.0)
        sx, sy, sc = world_to_screen(t.x, t.y, tz, cam_x, cam_y)
        rr = max(22, int(34 * sc))
        pygame.draw.circle(surf, (255, 40, 45), (int(sx), int(sy)), rr, width=3)
        if rr > 12:
            pygame.draw.circle(surf, (255, 200, 140), (int(sx), int(sy)), max(10, rr - 8), width=2)


# ---------------------------------------------------------------------------
# Unit intent (movement paths, attack beams, selection formation bracket)
# ---------------------------------------------------------------------------

_INTENT_MOVE_PLAYER = (72, 118, 152)
_INTENT_MOVE_ENEMY = (120, 72, 78)
_INTENT_ATTACK = (220, 95, 88)
_INTENT_RALLY = (95, 165, 145)
_INTENT_BRACKET = (210, 185, 95)


def _intent_line(
    surf: pygame.Surface,
    ax: float,
    ay: float,
    az: float,
    bx: float,
    by: float,
    bz: float,
    cam_x: float,
    cam_y: float,
    color: Tuple[int, int, int],
    width: int = 1,
) -> None:
    x0, y0, _ = world_to_screen(ax, ay, az, cam_x, cam_y)
    x1, y1, _ = world_to_screen(bx, by, bz, cam_x, cam_y)
    if max(x0, x1) < -40 or min(x0, x1) > VIEW_W + 40:
        return
    if max(y0, y1) < -40 or min(y0, y1) > VIEW_H + 40:
        return
    pygame.draw.line(surf, color, (int(x0), int(y0)), (int(x1), int(y1)), width)


def draw_movement_intent_lines(
    surf: pygame.Surface,
    groups: List[Group],
    cam_x: float,
    cam_y: float,
    fog: Optional[FogState],
    *,
    in_combat: bool,
) -> None:
    if not in_combat:
        return
    for g in groups:
        if g.dead or not g.render_capital or not g.waypoint:
            continue
        wx, wy = g.waypoint
        if g.side == "player":
            if fog is not None and not fog_cell_visible(fog, g.x, g.y):
                continue
            if fog is not None and not fog_cell_visible(fog, wx, wy):
                continue
            _intent_line(surf, g.x, g.y, g.z, wx, wy, g.z, cam_x, cam_y, _INTENT_MOVE_PLAYER, 1)
        else:
            if fog is not None and (
                not fog_cell_visible(fog, g.x, g.y)
                or not fog_cell_visible(fog, wx, wy)
            ):
                continue
            _intent_line(surf, g.x, g.y, g.z, wx, wy, g.z, cam_x, cam_y, _INTENT_MOVE_ENEMY, 1)


def draw_strike_rally_intent_lines(
    surf: pygame.Surface,
    crafts: List[Craft],
    cam_x: float,
    cam_y: float,
    fog: Optional[FogState],
    *,
    in_combat: bool,
) -> None:
    if not in_combat:
        return
    for c in crafts:
        if c.dead or c.side != "player":
            continue
        if fog is not None and not fog_cell_visible(fog, c.x, c.y):
            continue
        wings = getattr(c.parent, "strike_rally_wings", None)
        if not wings or c.squadron_index >= len(wings):
            continue
        rp = wings[c.squadron_index]
        if rp is None:
            continue
        wpx, wpy = float(rp[0]), float(rp[1])
        if fog is not None and not fog_cell_visible(fog, wpx, wpy):
            continue
        _intent_line(surf, c.x, c.y, c.z, wpx, wpy, c.z, cam_x, cam_y, _INTENT_RALLY, 1)


def draw_attack_intent_beams(
    surf: pygame.Surface,
    groups: List[Group],
    crafts: List[Craft],
    cam_x: float,
    cam_y: float,
    fog: Optional[FogState],
    mission: Any,
    *,
    in_combat: bool,
) -> None:
    if not in_combat:
        return
    mpv = bool(getattr(mission, "mp_pvp", False)) if mission is not None else False
    for g in groups:
        if g.side != "player" or g.dead or not g.render_capital:
            continue
        t = g.attack_target
        if not is_valid_attack_focus_for_side(
            "player",
            t,
            attacker_owner=getattr(g, "owner_id", None),
            mp_pvp=mpv,
        ):
            continue
        if fog is not None and not fog_cell_visible(fog, g.x, g.y):
            continue
        tz = t.z if isinstance(t, GroundObjective) else getattr(t, "z", 35.0)
        if fog is not None and not fog_cell_visible(fog, t.x, t.y):
            continue
        _intent_line(surf, g.x, g.y, g.z, t.x, t.y, tz, cam_x, cam_y, _INTENT_ATTACK, 1)

    for c in crafts:
        if c.dead or c.side != "player":
            continue
        p = c.parent
        if p.dead:
            continue
        t = getattr(p, "strike_focus_target", None)
        owner = getattr(c, "owner_id", None) or getattr(p, "owner_id", None)
        if not is_valid_attack_focus_for_side(
            "player", t, attacker_owner=owner, mp_pvp=mpv
        ):
            continue
        if fog is not None and not fog_cell_visible(fog, c.x, c.y):
            continue
        tz = t.z if isinstance(t, GroundObjective) else getattr(t, "z", 35.0)
        if fog is not None and not fog_cell_visible(fog, t.x, t.y):
            continue
        _intent_line(surf, c.x, c.y, c.z, t.x, t.y, tz, cam_x, cam_y, _INTENT_ATTACK, 1)


def draw_selection_formation_bracket(
    surf: pygame.Surface,
    groups: List[Group],
    cam_x: float,
    cam_y: float,
    fog: Optional[FogState],
    *,
    in_combat: bool,
) -> None:
    if not in_combat:
        return
    sel = [
        g
        for g in groups
        if g.side == "player" and not g.dead and g.render_capital and g.selected
    ]
    if not sel:
        return
    xs: List[float] = []
    ys: List[float] = []
    for g in sel:
        if fog is not None and not fog_cell_visible(fog, g.x, g.y):
            continue
        sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        cls_sc = CAPITAL_MARKER_CLASS_SCALE.get(g.class_name, 1.0)
        r = max(20.0, 30.0 * cls_sc * sc)
        xs.extend([sx - r, sx + r])
        ys.extend([sy - r, sy + r])
    if len(xs) < 2:
        return
    pad = 10.0
    left = int(min(xs) - pad)
    right = int(max(xs) + pad)
    top = int(min(ys) - pad)
    bottom = int(max(ys) + pad)
    col = _INTENT_BRACKET
    ln = 14
    w = 2
    # Top-left
    pygame.draw.line(surf, col, (left, top), (left + ln, top), w)
    pygame.draw.line(surf, col, (left, top), (left, top + ln), w)
    # Top-right
    pygame.draw.line(surf, col, (right, top), (right - ln, top), w)
    pygame.draw.line(surf, col, (right, top), (right, top + ln), w)
    # Bottom-left
    pygame.draw.line(surf, col, (left, bottom), (left + ln, bottom), w)
    pygame.draw.line(surf, col, (left, bottom), (left, bottom - ln), w)
    # Bottom-right
    pygame.draw.line(surf, col, (right, bottom), (right - ln, bottom), w)
    pygame.draw.line(surf, col, (right, bottom), (right, bottom - ln), w)


# ---------------------------------------------------------------------------
# Salvage pods
# ---------------------------------------------------------------------------

def draw_salvage_pods(surf: pygame.Surface, mission: Any,
                      cam_x: float, cam_y: float, fog: FogState) -> None:
    if mission is None or not hasattr(mission, "pods"):
        return
    for pod in mission.pods:
        if pod.collected:
            continue
        if not fog_cell_visible(fog, pod.x, pod.y):
            continue
        sx, sy, sc = world_to_screen(pod.x, pod.y, 0.0, cam_x, cam_y)
        pygame.draw.circle(surf, (230, 195, 70), (int(sx), int(sy)), max(8, int(17 * sc)), width=2)
        pygame.draw.circle(surf, (255, 245, 200), (int(sx), int(sy)), max(2, int(5 * sc)))

# ---------------------------------------------------------------------------
# Objective (strike relay)
# ---------------------------------------------------------------------------

def draw_objective(surf: pygame.Surface, font: pygame.font.Font,
                   mission: Any, cam_x: float, cam_y: float,
                   fog: FogState) -> None:
    if mission is None or not hasattr(mission, "objective") or mission.objective is None:
        return
    obj = mission.objective
    if obj.dead:
        return
    if not fog_cell_visible(fog, obj.x, obj.y):
        return
    sx, sy, sc = world_to_screen(obj.x, obj.y, getattr(obj, "z", 0.0), cam_x, cam_y)
    rr = max(18, int(obj.radius * sc))
    pygame.draw.circle(surf, (210, 65, 50), (int(sx), int(sy)), rr, width=3)
    bar_w = max(30, int(60 * sc))
    bar_h = 4
    frac = max(0.0, min(1.0, obj.hp / obj.max_hp if obj.max_hp > 0 else 0))
    bx = int(sx - bar_w // 2)
    by = int(sy + rr + 6)
    pygame.draw.rect(surf, (35, 40, 48), (bx, by, bar_w, bar_h), border_radius=1)
    pygame.draw.rect(surf, (255, 130, 80), (bx, by, int(bar_w * frac), bar_h), border_radius=1)

# ---------------------------------------------------------------------------
# UI primitives
# ---------------------------------------------------------------------------

def draw_panel(surf: pygame.Surface, rect: pygame.Rect,
               fill: Tuple = BG_PANEL, border: Tuple = BORDER_PANEL,
               radius: int = 14, border_w: int = 2) -> None:
    pygame.draw.rect(surf, fill, rect, border_radius=radius)
    pygame.draw.rect(surf, border, rect, width=border_w, border_radius=radius)

def draw_button(surf: pygame.Surface, rect: pygame.Rect, label: str,
                font: pygame.font.Font, hot: bool = False, *,
                accent: Optional[Tuple[int, int, int]] = None) -> None:
    fill = BTN_FILL_HOT if hot else BTN_FILL
    border = accent or (BORDER_BTN_HOT if hot else BORDER_BTN)
    pygame.draw.rect(surf, fill, rect, border_radius=8)
    pygame.draw.rect(surf, border, rect, width=2, border_radius=8)
    txt = font.render(label, True, TEXT_PRIMARY)
    surf.blit(txt, (rect.centerx - txt.get_width() // 2,
                     rect.centery - txt.get_height() // 2))

def draw_text_field(surf: pygame.Surface, rect: pygame.Rect, text: str,
                    font: pygame.font.Font, active: bool = False,
                    placeholder: str = "") -> None:
    fill = (18, 28, 42) if active else (12, 20, 32)
    border = (90, 150, 200) if active else (50, 75, 100)
    pygame.draw.rect(surf, fill, rect, border_radius=6)
    pygame.draw.rect(surf, border, rect, width=1, border_radius=6)
    display = text if text else placeholder
    color = TEXT_PRIMARY if text else TEXT_DIM
    rendered = font.render(display[:64], True, color)
    surf.blit(rendered, (rect.x + 8, rect.centery - rendered.get_height() // 2))
    if active:
        caret_x = rect.x + 8 + font.size(text[:64])[0]
        caret = font.render("|", True, (180, 220, 255))
        surf.blit(caret, (caret_x, rect.centery - caret.get_height() // 2))

def draw_progress_bar(surf: pygame.Surface, rect: pygame.Rect,
                      frac: float, color: Tuple[int, int, int] = ACCENT_GREEN,
                      track: Tuple[int, int, int] = (28, 36, 48)) -> None:
    pygame.draw.rect(surf, track, rect, border_radius=3)
    fill_w = int(rect.w * max(0.0, min(1.0, frac)))
    if fill_w > 0:
        pygame.draw.rect(surf, color, pygame.Rect(rect.x, rect.y, fill_w, rect.h), border_radius=3)


def draw_pd_stress_badge(
    surf: pygame.Surface,
    font: pygame.font.Font,
    sx: float,
    sy: float,
    sc: float,
    stress_ratio: float,
) -> None:
    """Small 'PD' label under the hull marker; green→yellow→red from combat_ordnance stress."""
    level = pd_stress_display_level(stress_ratio)
    col = pd_stress_color(level)
    off = int(20 * sc)
    x0 = int(sx)
    y0 = int(sy + off)
    label = "PD"
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        sh = font.render(label, True, (10, 16, 26))
        surf.blit(sh, (x0 - sh.get_width() // 2 + ox, y0 + oy))
    txt = font.render(label, True, col)
    surf.blit(txt, (x0 - txt.get_width() // 2, y0))


# ---------------------------------------------------------------------------
# Composite: draw the full battle world (background + entities + fog)
# Used by CombatScene and DebriefScene.
# ---------------------------------------------------------------------------

def draw_battle_world(surf: pygame.Surface, gs: Any, show_fog: bool = True) -> None:
    """Render the complete battlefield onto *surf* (VIEW_W x VIEW_H region)."""
    cam_x, cam_y = gs.camera.cam_x, gs.camera.cam_y
    fog = gs.combat.fog
    in_combat = getattr(gs.round, "phase", "") == "combat"
    pd_mult = gs.combat.pd_rof_mult[0] if gs.combat.pd_rof_mult else 1.0

    surf.fill(BG_DEEP)
    draw_starfield(surf, gs.stars, cam_x, cam_y, VIEW_W, VIEW_H)
    draw_world_edge(surf, cam_x, cam_y)

    draw_asteroids(surf, gs.battle_obstacles, cam_x, cam_y, fog)
    draw_objective(surf, gs.fonts.tiny, gs.combat.mission, cam_x, cam_y, fog)
    draw_salvage_pods(surf, gs.combat.mission, cam_x, cam_y, fog)

    draw_movement_intent_lines(
        surf, gs.combat.groups, cam_x, cam_y, fog, in_combat=in_combat
    )
    draw_strike_rally_intent_lines(
        surf, gs.combat.crafts, cam_x, cam_y, fog, in_combat=in_combat
    )

    for b in gs.combat.ballistics:
        draw_ballistic(surf, b, cam_x, cam_y)
    draw_vfx_beams(surf, gs.combat.vfx_beams, cam_x, cam_y)
    draw_vfx_sparks(surf, gs.combat.vfx_sparks, cam_x, cam_y)
    for m in gs.combat.missiles:
        draw_missile(surf, m, cam_x, cam_y, gs.fonts.micro)

    for g in gs.combat.groups:
        if g.dead:
            continue
        if g.side == "enemy" and not fog_cell_visible(fog, g.x, g.y):
            continue
        sx, sy, sc = world_to_screen(g.x, g.y, g.z, cam_x, cam_y)
        cls_sc = CAPITAL_MARKER_CLASS_SCALE.get(g.class_name, 1.0)
        if g.selected:
            col = SELECT_YELLOW
        elif g.side == "enemy":
            col = ACCENT_RED
        else:
            col = player_unit_color(g.color_id)
        if g.render_capital:
            hdg = heading_for_group(g)
            draw_capital(surf, sx, sy, col, hdg, cls_sc * sc)
            tip_y = sy - max(8.0, 9.0 * cls_sc * sc)
            compact = len(gs.combat.groups) > 8
            draw_navy_hud_card(
                surf, sx, tip_y, sc,
                tier=0,
                line1=g.label if not compact else f"{g.label}  {g.class_name}",
                line2=None if compact else g.class_name,
                hp_frac=max(0.0, min(1.0, g.hp / g.max_hp if g.max_hp > 0 else 0.0)),
                accent=col,
                selected=g.selected,
                font_top=gs.fonts.tiny,
                font_bot=gs.fonts.micro,
            )
            if in_combat and gs.fonts.micro is not None:
                pr = compute_pd_stress_ratio(gs.data, g, gs.combat.missiles, pd_mult)
                if pr is not None:
                    draw_pd_stress_badge(surf, gs.fonts.micro, sx, sy, sc, pr)
        if g.selected and g.render_capital:
            pygame.draw.circle(surf, SELECT_YELLOW, (int(sx), int(sy)),
                               max(16, int(28 * cls_sc * sc)), width=1)

    for c in gs.combat.crafts:
        if c.dead:
            continue
        if c.side == "enemy" and not fog_cell_visible(fog, c.x, c.y):
            continue
        sx, sy, sc = world_to_screen(c.x, c.y, c.z, cam_x, cam_y)
        if c.side == "enemy":
            col = (255, 130, 130)
        else:
            col = player_unit_color(c.color_id, for_craft=True)
        draw_craft(surf, sx, sy, col, c.heading, 6.5 * sc)
        tip_cy = sy - max(5.0, 6.2 * sc)
        draw_navy_hud_card(
            surf, sx, tip_cy, sc,
            tier=1,
            line1=craft_type_abbrev(c.class_name),
            line2=None,
            hp_frac=max(0.0, min(1.0, c.hp / c.max_hp if c.max_hp > 0 else 0.0)),
            accent=col,
            selected=c.selected,
            font_top=gs.fonts.micro,
            font_bot=gs.fonts.micro,
        )
        if in_combat and gs.fonts.micro is not None:
            pr = compute_pd_stress_ratio(gs.data, c, gs.combat.missiles, pd_mult)
            if pr is not None:
                draw_pd_stress_badge(surf, gs.fonts.micro, sx, sy, sc, pr)
        if c.selected:
            pygame.draw.circle(surf, (255, 240, 140), (int(sx), int(sy)),
                               max(6, int(10 * sc)), width=2)

    draw_attack_intent_beams(
        surf,
        gs.combat.groups,
        gs.combat.crafts,
        cam_x,
        cam_y,
        fog,
        gs.combat.mission,
        in_combat=in_combat,
    )

    if show_fog:
        draw_fog_overlay(surf, fog, cam_x, cam_y)

    draw_sensor_ghosts(surf, gs.fonts.tiny, gs.combat.sensor_ghosts, cam_x, cam_y)
    draw_sensor_ghosts(surf, gs.fonts.tiny, gs.combat.seeker_ghosts, cam_x, cam_y)
    draw_active_pings(surf, gs.combat.active_pings, cam_x, cam_y)
    draw_attack_focus_rings(surf, gs.combat.groups, cam_x, cam_y, fog)
    draw_selection_formation_bracket(
        surf, gs.combat.groups, cam_x, cam_y, fog, in_combat=in_combat
    )


# ---------------------------------------------------------------------------
# Blit internal framebuffer to the resizable window
# ---------------------------------------------------------------------------

def blit_to_window(window: pygame.Surface, screen: pygame.Surface,
                   win_w: int, win_h: int) -> None:
    if win_w == WIDTH and win_h == HEIGHT:
        window.blit(screen, (0, 0))
    else:
        scaled = pygame.transform.smoothscale(screen, (max(1, win_w), max(1, win_h)))
        window.blit(scaled, (0, 0))
    pygame.display.flip()
