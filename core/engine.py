"""FleetRTS main loop.

Initialises pygame, creates GameState and RunContext, registers scenes,
and runs the SceneManager loop.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path
from typing import Any, List, Tuple

import pygame

try:
    from bundle_paths import game_data_json
    from combat_constants import WORLD_H, WORLD_W
    from game_audio import GameAudio
    from game_state import GameState
    from scenes import RunContext, SceneManager
    from demo_game import Asteroid
except ImportError:
    from core.bundle_paths import game_data_json
    from core.combat_constants import WORLD_H, WORLD_W
    from core.game_audio import GameAudio
    from core.game_state import GameState
    from core.scenes import RunContext, SceneManager
    from core.demo_game import Asteroid

try:
    from draw import WIDTH, HEIGHT, clamp_camera
except ImportError:
    from core.draw import WIDTH, HEIGHT, clamp_camera

FPS = 60
DEFAULT_FLEETRTS_LOBBY_HTTP = "http://198.199.80.13:8765"


def _load_game_data() -> dict:
    with open(game_data_json(), encoding="utf-8") as f:
        return json.load(f)


def _parse_obstacles(data: dict) -> List[Asteroid]:
    bf = data.get("battlefield") or data.get("battle_field") or {}
    raw = bf.get("asteroids") or bf.get("obstacles") or []
    out: List[Asteroid] = []
    for entry in raw:
        if isinstance(entry, dict):
            out.append(Asteroid(
                x=float(entry.get("x", 0)),
                y=float(entry.get("y", 0)),
                r=float(entry.get("r", entry.get("radius", 40))),
            ))
    return out


def _capital_ship_class_names(data: dict) -> List[str]:
    out: List[str] = []
    for sc in data.get("ship_classes") or []:
        if sc.get("render") == "capital" and sc.get("name"):
            out.append(str(sc["name"]))
    return sorted(out)


def _resolve_fleet_http_base() -> str | None:
    env_raw = os.environ.get("FLEETRTS_HTTP")
    if env_raw is not None:
        return env_raw.strip() or None
    return DEFAULT_FLEETRTS_LOBBY_HTTP.strip() or None


def _generate_stars() -> List[Tuple[int, int, int]]:
    random.seed(42)
    stars = [
        (random.randint(0, max(1, WORLD_W - 1)),
         random.randint(0, max(1, WORLD_H - 1)),
         random.randint(40, 120))
        for _ in range(960)
    ]
    random.seed()
    return stars


def run() -> None:
    pygame.init()
    pygame.display.set_caption("Fleet RTS")
    screen = pygame.Surface((WIDTH, HEIGHT))
    win_w, win_h = WIDTH, HEIGHT
    window = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)

    audio = GameAudio()
    audio.init()
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 15)
    font_tiny = pygame.font.SysFont("consolas", 12)
    font_micro = pygame.font.SysFont("consolas", 10)
    font_big = pygame.font.SysFont("consolas", 20)

    gs = GameState()
    gs.data = _load_game_data()
    gs.battle_obstacles = _parse_obstacles(gs.data)
    gs.stars = _generate_stars()
    gs.camera.cam_x, gs.camera.cam_y = clamp_camera(WORLD_W * 0.35, WORLD_H * 0.35)
    gs.cap_names_menu = _capital_ship_class_names(gs.data) or ["Destroyer"]
    gs.audio = audio
    gs.fonts.main = font
    gs.fonts.tiny = font_tiny
    gs.fonts.micro = font_micro
    gs.fonts.big = font_big

    _mp_name = (os.environ.get("FLEETRTS_PLAYER", "Player").strip() or "Player")[:48]
    gs.mp.player_name = _mp_name
    gs.mp.name_buffer = _mp_name
    gs.mp.fleet_http_base = _resolve_fleet_http_base()

    ctx = RunContext(screen, window, clock, WIDTH, HEIGHT, win_w, win_h)

    # Late-import scenes to avoid circular deps at module level.
    from scene_config import ConfigScene       # type: ignore[import-untyped]
    from scene_gameover import GameOverScene    # type: ignore[import-untyped]
    from scene_combat import CombatScene       # type: ignore[import-untyped]
    from scene_debrief import DebriefScene     # type: ignore[import-untyped]
    from scene_loadouts import LoadoutsScene   # type: ignore[import-untyped]
    from scene_mp_hub import MpHubScene        # type: ignore[import-untyped]
    from scene_mp_lobby import MpLobbyScene    # type: ignore[import-untyped]
    from scene_bg_editor import BGEditorScene  # type: ignore[import-untyped]

    manager = SceneManager({
        "config":              ConfigScene(),
        "gameover":            GameOverScene(),
        "combat":              CombatScene(),
        "debrief":             DebriefScene(),
        "ship_loadouts":       LoadoutsScene(),
        "mp_hub":              MpHubScene(),
        "mp_lobby":            MpLobbyScene(),
        "battlegroup_editor":  BGEditorScene(),
    }, initial_phase="config")

    try:
        from draw import blit_to_window
    except ImportError:
        from core.draw import blit_to_window

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        # Process input before sim so clicks (e.g. box select) are not delayed by a heavy update step.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            if event.type == pygame.VIDEORESIZE:
                ctx.win_w = max(960, event.w)
                ctx.win_h = max(540, event.h)
                ctx.window = pygame.display.set_mode(
                    (ctx.win_w, ctx.win_h), pygame.RESIZABLE)
                continue
            if (event.type == pygame.KEYDOWN
                    and event.key == pygame.K_q
                    and (event.mod & pygame.KMOD_CTRL)):
                running = False
                continue
            result = manager.current.handle_event(event, gs, ctx)
            if result:
                gs.round.phase = result
                manager.phase = result

        scene = manager.current
        transition = scene.update(dt, gs, ctx)
        if transition:
            gs.round.phase = transition
            manager.phase = transition

        manager.current.draw(screen, gs, ctx)
        blit_to_window(ctx.window, screen, ctx.win_w, ctx.win_h)

    audio.shutdown()
    pygame.quit()


def main() -> None:
    try:
        run()
    except FileNotFoundError as e:
        print(f"Missing data file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
