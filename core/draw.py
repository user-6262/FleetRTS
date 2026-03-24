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
            grain = (ci * 47 + cj * 19) % 37
            if not fog.explored[idx]:
                base_a = 228 + min(24, grain)
                c0 = (4, 8, 20, base_a)
                c1 = (10, 18, 38, max(40, base_a - 100))
            else:
                base_a = 118 + min(28, grain)
                c0 = (16, 26, 48, base_a)
                c1 = (28, 42, 72, max(28, base_a - 55))
            cx = sum(p[0] for p in pts_o) / len(pts_o)
            cy = sum(p[1] for p in pts_o) / len(pts_o)
            inner = [(int(cx + (px - cx) * 0.72), int(cy + (py - cy) * 0.72))
                     for px, py in pts_o]
            pygame.draw.polygon(ov, c0, pts_o)
            pygame.draw.polygon(ov, c1, inner)
            pygame.draw.polygon(ov, (0, 0, 0, 24), pts_o, width=1)
    edge = 64
    sh = (3, 8, 18, 38)
    pygame.draw.rect(ov, sh, (0, 0, VIEW_W, edge))
    pygame.draw.rect(ov, sh, (0, VIEW_H - edge, VIEW_W, edge))
    pygame.draw.rect(ov, sh, (0, 0, edge, VIEW_H))
    pygame.draw.rect(ov, sh, (VIEW_W - edge, 0, edge, VIEW_H))
    surf.blit(ov, (0, 0))

# ---------------------------------------------------------------------------
# NATO-style capital ship glyph
# ---------------------------------------------------------------------------

def heading_for_group(g: Group) -> float:
    if g.waypoint:
        wx, wy = g.waypoint
        return math.atan2(wy - g.y, wx - g.x)
    return -math.pi / 2

def draw_capital(surf: pygame.Surface, x: float, y: float,
                 color: Tuple[int, int, int], heading: float,
                 scale: float = 1.0) -> None:
    xi, yi = int(x), int(y)
    w = int(22 * scale)
    h = int(14 * scale)
    rect = pygame.Rect(xi - w // 2, yi - h // 2, w, h)
    pygame.draw.rect(surf, color, rect, width=2, border_radius=2)
    L = int(12 * scale)
    hx = math.cos(heading) * L
    hy = math.sin(heading) * L
    tip = (xi + hx, yi + hy)
    left = (xi + math.cos(heading + 2.4) * 8 * scale,
            yi + math.sin(heading + 2.4) * 8 * scale)
    right = (xi + math.cos(heading - 2.4) * 8 * scale,
             yi + math.sin(heading - 2.4) * 8 * scale)
    pygame.draw.polygon(surf, color, [tip, left, right], width=2)

# ---------------------------------------------------------------------------
# Strike craft triangle
# ---------------------------------------------------------------------------

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
    pygame.draw.polygon(surf, color, [p1, p2, p3])
    pygame.draw.polygon(surf, color, [p1, p2, p3], width=1)

# ---------------------------------------------------------------------------
# Entity plates (HP label above ships)
# ---------------------------------------------------------------------------

def draw_entity_plate(surf: pygame.Surface, font: pygame.font.Font,
                      font_tiny: pygame.font.Font,
                      x: float, y: float, label: str, cls: str,
                      hp: float, max_hp: float, compact: bool = False) -> None:
    pad = 4
    line1 = f"{label}  {cls}"
    w1 = font_tiny.render(line1, True, (210, 225, 235))
    bar_w = 52 if compact else 64
    frac = max(0.0, min(1.0, hp / max_hp if max_hp > 0 else 0))
    h_bar = 5
    total_h = w1.get_height() + h_bar + pad * 2 + (0 if compact else 10)
    bx = int(x - bar_w // 2 - pad)
    by = int(y - total_h)
    bw = bar_w + pad * 2
    bg = pygame.Surface((bw, total_h), pygame.SRCALPHA)
    pygame.draw.rect(bg, (8, 18, 28, 200), (0, 0, bw, total_h), border_radius=4)
    pygame.draw.rect(bg, (40, 90, 80, 180), (0, 0, bw, total_h), width=1, border_radius=4)
    surf.blit(bg, (bx, by))
    surf.blit(w1, (bx + pad, by + pad))
    bgy = by + pad + w1.get_height() + 2
    pygame.draw.rect(surf, (30, 35, 40), (bx + pad, bgy, bar_w, h_bar), border_radius=2)
    pygame.draw.rect(surf, (80, 200, 120), (bx + pad, bgy, int(bar_w * frac), h_bar), border_radius=2)

# ---------------------------------------------------------------------------
# Strike craft tag
# ---------------------------------------------------------------------------

def draw_craft_tag(surf: pygame.Surface, font_micro: pygame.font.Font,
                   x: float, y: float, cls: str,
                   hp: float, max_hp: float) -> None:
    pad = 2
    short = cls[:3].upper()
    w1 = font_micro.render(short, True, (170, 195, 215))
    bar_w = 28
    frac = max(0.0, min(1.0, hp / max_hp if max_hp > 0 else 0))
    h_bar = 3
    total_h = w1.get_height() + h_bar + pad * 2
    bx = int(x - bar_w // 2 - pad)
    by = int(y - total_h - 2)
    bw = bar_w + pad * 2
    bg = pygame.Surface((bw, total_h), pygame.SRCALPHA)
    pygame.draw.rect(bg, (6, 14, 22, 160), (0, 0, bw, total_h), border_radius=2)
    pygame.draw.rect(bg, (35, 70, 60, 140), (0, 0, bw, total_h), width=1, border_radius=2)
    surf.blit(bg, (bx, by))
    surf.blit(w1, (bx + pad, by + pad))
    bgy = by + pad + w1.get_height() + 1
    pygame.draw.rect(surf, (28, 32, 38), (bx + pad, bgy, bar_w, h_bar), border_radius=1)
    pygame.draw.rect(surf, (70, 160, 110), (bx + pad, bgy, int(bar_w * frac), h_bar), border_radius=1)

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
    pygame.draw.polygon(surf, (0, 0, 0), pts)
    pygame.draw.polygon(surf, ac_l, pts, width=max(1, int(1.15 * sc)))
    wx = int(x - ca * r_a * 1.05)
    wy = int(y - sa * r_a * 1.05)
    wx2 = int(x - ca * r_a * 2.15)
    wy2 = int(y - sa * r_a * 2.15)
    dim = (ac_l[0] // 2 + 30, ac_l[1] // 2 + 25, ac_l[2] // 2 + 35)
    pygame.draw.line(surf, dim, (wx, wy), (wx2, wy2), max(1, int(sc)))
    if font_micro is not None:
        label = font_micro.render(abbrev, True, ac_l)
        bw = label.get_width() + 4
        bh = label.get_height() + 4
        bx, by_l = int(x - bw // 2), int(y + r_b + 5)
        bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
        pygame.draw.rect(bg, (18, 12, 24, 200), (0, 0, bw, bh), border_radius=2)
        pygame.draw.rect(bg, (72, 48, 98, 220), (0, 0, bw, bh), width=1, border_radius=2)
        surf.blit(bg, (bx, by_l))
        surf.blit(label, (bx + 2, by_l + 2))

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

# ---------------------------------------------------------------------------
# Composite: draw the full battle world (background + entities + fog)
# Used by CombatScene and DebriefScene.
# ---------------------------------------------------------------------------

def draw_battle_world(surf: pygame.Surface, gs: Any, show_fog: bool = True) -> None:
    """Render the complete battlefield onto *surf* (VIEW_W x VIEW_H region)."""
    cam_x, cam_y = gs.camera.cam_x, gs.camera.cam_y
    fog = gs.combat.fog

    surf.fill(BG_DEEP)
    draw_starfield(surf, gs.stars, cam_x, cam_y, VIEW_W, VIEW_H)
    draw_world_edge(surf, cam_x, cam_y)

    draw_asteroids(surf, gs.battle_obstacles, cam_x, cam_y, fog)
    draw_objective(surf, gs.fonts.tiny, gs.combat.mission, cam_x, cam_y, fog)
    draw_salvage_pods(surf, gs.combat.mission, cam_x, cam_y, fog)

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
            draw_capital(surf, sx, sy, col, heading_for_group(g), cls_sc * sc)
            draw_entity_plate(surf, gs.fonts.main, gs.fonts.tiny,
                              sx, sy - int(16 * sc), g.label, g.class_name,
                              g.hp, g.max_hp, compact=len(gs.combat.groups) > 8)
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
        if c.selected:
            pygame.draw.circle(surf, (255, 240, 140), (int(sx), int(sy)),
                               max(6, int(10 * sc)), width=2)

    if show_fog:
        draw_fog_overlay(surf, fog, cam_x, cam_y)

    draw_sensor_ghosts(surf, gs.fonts.tiny, gs.combat.sensor_ghosts, cam_x, cam_y)
    draw_sensor_ghosts(surf, gs.fonts.tiny, gs.combat.seeker_ghosts, cam_x, cam_y)
    draw_active_pings(surf, gs.combat.active_pings, cam_x, cam_y)
    draw_attack_focus_rings(surf, gs.combat.groups, cam_x, cam_y, fog)


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
