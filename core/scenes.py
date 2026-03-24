"""Scene protocol and manager for FleetRTS.

Scenes encapsulate event handling, per-frame logic, and drawing for a single
game phase (config menu, combat, debrief, etc.).  SceneManager owns the scene
map and drives the main loop.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple

import pygame


class RunContext:
    """Mutable container for non-GameState resources (screen, window, clock)."""

    __slots__ = ("screen", "window", "clock", "width", "height", "win_w", "win_h")

    def __init__(
        self,
        screen: pygame.Surface,
        window: pygame.Surface,
        clock: pygame.time.Clock,
        width: int,
        height: int,
        win_w: int,
        win_h: int,
    ):
        self.screen = screen
        self.window = window
        self.clock = clock
        self.width = width
        self.height = height
        self.win_w = win_w
        self.win_h = win_h

    def to_internal(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        mx, my = pos
        return (
            int(mx * self.width / max(1, self.win_w)),
            int(my * self.height / max(1, self.win_h)),
        )


class Scene(Protocol):
    """Interface every game scene must satisfy."""

    def handle_event(self, event: pygame.event.Event, gs: Any, ctx: RunContext) -> Optional[str]:
        """Process one pygame event.  Return a phase name to transition, or *None*."""
        ...

    def update(self, dt: float, gs: Any, ctx: RunContext) -> Optional[str]:
        """Per-frame logic (before drawing).  Return a phase name to transition, or *None*."""
        ...

    def draw(self, screen: pygame.Surface, gs: Any, ctx: RunContext) -> None:
        """Draw the scene to *screen*."""
        ...


class SceneManager:
    """Owns the phase→Scene map and drives transitions."""

    def __init__(self, scenes: Dict[str, Scene], initial_phase: str = "config"):
        self.scenes = scenes
        self._phase = initial_phase

    @property
    def phase(self) -> str:
        return self._phase

    @phase.setter
    def phase(self, value: str) -> None:
        if value not in self.scenes:
            raise KeyError(f"No scene registered for phase {value!r}")
        self._phase = value

    @property
    def current(self) -> Scene:
        return self.scenes[self._phase]

    def transition(self, new_phase: Optional[str]) -> None:
        """Apply *new_phase* if it is not None."""
        if new_phase is not None:
            self.phase = new_phase
