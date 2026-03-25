"""Load and cache ship portrait PNGs for combat HUD (player faction_a art only).

Stems match tools/split_ship_portrait_sheet.py output. If craft selection is wired in
CombatScene later, reuse portrait_for_class with craft.label / craft.class_name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import pygame

try:
    from bundle_paths import assets_portraits_ships_dir
except ImportError:
    from core.bundle_paths import assets_portraits_ships_dir

# Max edge length for HUD thumbnails (scaled once at load).
PORTRAIT_THUMB_MAX = 72

# class_name -> single stem (no .png), faction_a_* from sheet
_SINGLE_STEMS: Dict[str, str] = {
    "Fighter": "faction_a_r0c0_Fighter",
    "Interceptor": "faction_a_r0c1_Interceptor",
    "Cruiser": "faction_a_r2c1_Cruiser",
    "Carrier": "faction_a_r3c1_Carrier",
}

# Two sheet variants; pick by hash(label) for stability
_VARIANT_STEMS: Dict[str, Tuple[str, ...]] = {
    "Frigate": (
        "faction_a_r1c0_Frigate",
        "faction_a_r1c1_Frigate",
    ),
    "Battleship": (
        "faction_a_r2c0_Battleship",
        "faction_a_r3c0_Battleship",
    ),
}


def portrait_stem_for_unit(class_name: str, unit_label: str) -> Optional[str]:
    """Return PNG stem for a player capital/craft, or None if no art (e.g. Bomber, Destroyer)."""
    if class_name in _SINGLE_STEMS:
        return _SINGLE_STEMS[class_name]
    variants = _VARIANT_STEMS.get(class_name)
    if not variants:
        return None
    i = hash(unit_label) % len(variants)
    return variants[i]


class ShipPortraitCache:
    def __init__(self) -> None:
        self._dir: Path = assets_portraits_ships_dir()
        self._scaled: Dict[str, pygame.Surface] = {}

    def get_surface(self, stem: str) -> Optional[pygame.Surface]:
        if stem in self._scaled:
            return self._scaled[stem]
        path = self._dir / f"{stem}.png"
        if not path.is_file():
            return None
        try:
            surf = pygame.image.load(str(path)).convert_alpha()
        except Exception:
            return None
        w, h = surf.get_size()
        if w <= 0 or h <= 0:
            return None
        scale = min(PORTRAIT_THUMB_MAX / w, PORTRAIT_THUMB_MAX / h, 1.0)
        if scale < 1.0:
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            surf = pygame.transform.smoothscale(surf, (nw, nh))
        self._scaled[stem] = surf
        return surf

    def surface_for_unit(self, class_name: str, unit_label: str) -> Optional[pygame.Surface]:
        stem = portrait_stem_for_unit(class_name, unit_label)
        if stem is None:
            return None
        return self.get_surface(stem)
