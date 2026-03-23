"""
Headless combat simulation tick (one frame).

Extracted from demo_game.run() so the same step can later run on a server or under tests.
Delegates mission setup, movement, fog, pod pickup, engagement timers, deaths, extract zone, and salvage math
to combat_engine; weapons / VFX / missiles / ballistics use combat_ordnance (no demo_game import here).
See core/COMBAT_DESIGN.txt for sandbox & MP direction.
Audio and pygame time stay in the client via CombatAudioEvents + CombatFlowDelta.

`CombatSimHooks` groups callbacks so a headless server can log or enqueue events instead of pygame audio.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

try:
    from combat_constants import REINF_INTERVAL_BASE, SALVAGE_PICKUP_R
    from combat_math import dist_xy, round_seed
except ImportError:
    from core.combat_constants import REINF_INTERVAL_BASE, SALVAGE_PICKUP_R
    from core.combat_math import dist_xy, round_seed

try:
    import combat_engine as ce
    import combat_ordnance as co
except ImportError:
    import core.combat_engine as ce
    import core.combat_ordnance as co


@dataclass
class CombatSimHooks:
    """Per-tick callbacks for combat sim (extend for command/damage streams later)."""

    on_player_hull_hit: Callable[[Any], None]


@dataclass
class CombatAudioEvents:
    """Death notifications for the client to play (preserves original ordering)."""

    player_caps_lost: List[Tuple[str, bool]] = field(default_factory=list)  # (label, render_capital)
    player_crafts_lost: int = 0
    enemy_cap_losses: int = 0  # enemy capitals with render_capital
    enemy_craft_losses: int = 0


@dataclass
class CombatFlowDelta:
    """Phase/outcome changes after this tick (apply in the game loop)."""

    outcome: str
    phase: str
    store_selected: Optional[str] = None
    store_hover: Optional[str] = None
    run_total_score_add: int = 0
    salvage_gain: int = 0
    last_salvage_gain: int = 0


@dataclass
class CombatStepResult:
    death_audio: CombatAudioEvents
    flow: Optional[CombatFlowDelta] = None


def apply_combat_death_audio(
    events: CombatAudioEvents,
    audio: Any,
    now_ms: int,
    *,
    tts_last_player_cap_loss_tts: int,
    tts_last_enemy_kill_tts: int,
    tts_player_cap_loss_gap_ms: int,
    tts_enemy_kill_gap_ms: int,
) -> Tuple[int, int]:
    """Play ship/TTS cues matching the former inline combat loop; returns updated throttle timestamps."""
    pc, ek = tts_last_player_cap_loss_tts, tts_last_enemy_kill_tts
    for _label, render_capital in events.player_caps_lost:
        audio.play_ship_destroyed()
        if render_capital and now_ms - pc >= tts_player_cap_loss_gap_ms:
            audio.speak_voice("Capital ship lost.")
            pc = now_ms
    for _ in range(events.player_crafts_lost):
        audio.play_ship_destroyed()
    for _ in range(events.enemy_cap_losses):
        if now_ms - ek >= tts_enemy_kill_gap_ms:
            audio.speak_voice("Enemy ship destroyed.")
            ek = now_ms
    for _ in range(events.enemy_craft_losses):
        if now_ms - ek >= tts_enemy_kill_gap_ms:
            audio.speak_voice("Enemy ship destroyed.")
            ek = now_ms
    return pc, ek


def step_combat_frame(
    *,
    data: dict,
    dt: float,
    round_idx: int,
    mission: Any,
    groups: List[Any],
    crafts: List[Any],
    fog: Any,
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    ping_ghost_anchor_labels: Any,
    seeker_ghosts: List[Any],
    control_groups: List[Any],
    cg_weapons_free: List[bool],
    missiles: List[Any],
    supplies: List[float],
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    ballistics: List[Any],
    pd_rof_mult: List[float],
    hooks: CombatSimHooks,
    phase: str,
    outcome: Optional[str],
) -> CombatStepResult:
    death = CombatAudioEvents()
    flow: Optional[CombatFlowDelta] = None
    hull_hit = hooks.on_player_hull_hit

    mission.reinf_timer -= dt
    if mission.reinf_timer <= 0 and mission.reinf_remaining > 0:
        ce.spawn_enemy_reinforcement(
            data,
            groups,
            mission,
            random.Random(round_seed(round_idx) + mission.enemy_label_serial * 131),
        )
        mission.reinf_remaining -= 1
        mission.reinf_timer = REINF_INTERVAL_BASE + random.uniform(3.5, 13.0)

    ce.collect_salvage_pods(mission, groups)

    strike_obj = mission.objective if mission.kind == "strike" else None

    players_g = [g for g in groups if g.side == "player"]
    player_caps_move = [g for g in players_g if not g.dead and g.render_capital]

    for g in players_g:
        if g.dead:
            continue
        ce.move_group(g, dt, player_caps_move)

    ce.separate_player_capitals(groups, dt, mp_pvp=bool(getattr(mission, "mp_pvp", False)))

    for g in groups:
        if g.side != "enemy" or g.dead:
            continue
        ce.enemy_ai(g, players_g, dt)

    ce.update_craft_positions(crafts, dt)

    ce.resolve_all_units_against_asteroids(groups, crafts, mission.obstacles)

    ce.tick_player_engagement_timers(groups, crafts, dt)

    co.prune_attack_targets(groups, mission)

    ce.update_fog_of_war(fog, groups, crafts, active_pings)
    for p in active_pings:
        p.ttl -= dt
    active_pings[:] = [p for p in active_pings if p.ttl > 0]
    ce.cull_sensor_ghosts_if_ping_anchors_lost(groups, crafts, sensor_ghosts, ping_ghost_anchor_labels)
    for gh in sensor_ghosts:
        gh.ttl -= dt
    sensor_ghosts[:] = [g for g in sensor_ghosts if g.ttl > 0]
    if not sensor_ghosts:
        ping_ghost_anchor_labels.clear()

    obs = mission.obstacles
    for g in groups:
        if g.dead:
            continue
        co.update_pd_overheat_streak(g, dt, data, missiles, pd_rof_mult[0])
        w_auth = g.side != "player" or co.player_capital_may_fire_weapons(
            g, control_groups, cg_weapons_free, mp_pvp=bool(getattr(mission, "mp_pvp", False))
        )
        co.try_fire_weapons(
            data,
            g.x,
            g.y,
            g.z,
            g.side,
            g.weapons,
            g.max_range,
            groups,
            crafts,
            missiles,
            supplies,
            dt,
            vfx_sparks,
            vfx_beams,
            ballistics,
            pd_rof_mult[0],
            strike_obj,
            pd_perf_mult=co.pd_overheat_rof_multiplier(g.pd_overheat_streak),
            launcher_speed=g.speed,
            weapons_authorized=w_auth,
            player_damage_hook=hull_hit,
            prefer_attack_target=g.attack_target,
            obstacles=obs,
            fog=fog,
            launcher_owner=getattr(g, "owner_id", None),
            mp_pvp=bool(getattr(mission, "mp_pvp", False)),
            launcher=g,
        )
    for c in crafts:
        if c.dead:
            continue
        co.update_pd_overheat_streak(c, dt, data, missiles, pd_rof_mult[0])
        w_auth = c.side != "player" or co.player_craft_may_fire_weapons(
            c, control_groups, cg_weapons_free, mp_pvp=bool(getattr(mission, "mp_pvp", False))
        )
        co.try_fire_weapons(
            data,
            c.x,
            c.y,
            c.z,
            c.side,
            c.weapons,
            c.max_range,
            groups,
            crafts,
            missiles,
            supplies,
            dt,
            vfx_sparks,
            vfx_beams,
            ballistics,
            pd_rof_mult[0],
            None,
            pd_perf_mult=co.pd_overheat_rof_multiplier(c.pd_overheat_streak),
            launcher_speed=c.speed,
            weapons_authorized=w_auth,
            player_damage_hook=hull_hit,
            prefer_attack_target=c.parent.attack_target,
            obstacles=obs,
            fog=fog,
            launcher_owner=getattr(c, "owner_id", None),
            mp_pvp=bool(getattr(mission, "mp_pvp", False)),
            launcher=c,
        )

    co.update_vfx_sparks(vfx_sparks, dt)
    co.update_vfx_beams(vfx_beams, dt)
    co.update_ballistics(
        ballistics,
        dt,
        groups,
        crafts,
        missiles,
        supplies,
        vfx_sparks,
        strike_obj,
        player_damage_hook=hull_hit,
        obstacles=obs,
    )
    co.update_missiles(
        missiles,
        dt,
        groups,
        crafts,
        supplies,
        strike_obj,
        data,
        player_damage_hook=hull_hit,
        obstacles=obs,
        vfx_sparks=vfx_sparks,
        fog=fog,
    )
    co.rebuild_seeker_lock_ghosts(fog, missiles, mission.obstacles, seeker_ghosts)
    player_cap_was_alive = {id(g): (not g.dead) for g in groups if g.side == "player"}
    player_craft_was_alive = {id(c): (not c.dead) for c in crafts if c.side == "player"}
    enemy_cap_was_alive = {id(g): (not g.dead) for g in groups if g.side == "enemy" and g.render_capital}
    enemy_craft_was_alive = {id(c): (not c.dead) for c in crafts if c.side == "enemy"}
    ce.finalize_deaths(groups, crafts)
    ce.finalize_objective_if_dead(mission.objective)

    for g in groups:
        if g.side == "player" and player_cap_was_alive.get(id(g)) and g.dead:
            death.player_caps_lost.append((g.label, bool(g.render_capital)))
    for c in crafts:
        if c.side == "player" and player_craft_was_alive.get(id(c)) and c.dead:
            death.player_crafts_lost += 1
    for g in groups:
        if g.side == "enemy" and enemy_cap_was_alive.get(id(g)) and g.dead and g.render_capital:
            death.enemy_cap_losses += 1
    for c in crafts:
        if c.side == "enemy" and enemy_craft_was_alive.get(id(c)) and c.dead:
            death.enemy_craft_losses += 1

    supplies[0] = max(0.0, supplies[0])

    alive_player_cap = [g for g in groups if g.side == "player" and not g.dead]
    if flow is None and bool(getattr(mission, "mp_pvp", False)):
        owners_alive = sorted(
            {
                str(getattr(g, "owner_id", "")).strip()
                for g in alive_player_cap
                if getattr(g, "render_capital", False) and str(getattr(g, "owner_id", "")).strip()
            }
        )
        if len(owners_alive) <= 1:
            if owners_alive:
                out_str = f"pvp victory — {owners_alive[0]} controls the field"
            else:
                out_str = "pvp draw — all fleets destroyed"
            flow = CombatFlowDelta(
                outcome=out_str,
                phase="debrief",
                store_selected=None,
                store_hover=None,
                run_total_score_add=0,
                salvage_gain=0,
                last_salvage_gain=0,
            )
    ex_zone = ce.extract_rect_world()
    if flow is None and not alive_player_cap:
        flow = CombatFlowDelta(outcome="campaign over — fleet lost", phase="gameover")
    elif flow is None and (
        alive_player_cap
        and ce.mission_allows_extract(mission)
        and all(ex_zone.collidepoint(g.x, g.y) for g in alive_player_cap)
    ):
        total = sum(g.hp / g.max_hp for g in alive_player_cap) / len(alive_player_cap)
        round_score = int(supplies[0] * 12 + total * 520 + mission.enemy_label_serial * 18)
        salvage_gain = ce.compute_mission_salvage_reward(mission, supplies[0], total)
        tag = "STRIKE" if mission.kind == "strike" else ("PVP" if mission.kind == "pvp" else "SALVAGE")
        out_str = f"round {round_idx} ({tag}) cleared  +{salvage_gain} salvage  (score +{round_score})"
        flow = CombatFlowDelta(
            outcome=out_str,
            phase="debrief",
            store_selected=None,
            store_hover=None,
            run_total_score_add=round_score,
            salvage_gain=salvage_gain,
            last_salvage_gain=salvage_gain,
        )

    if flow is None and phase == "combat" and supplies[0] <= 0 and not outcome:
        flow = CombatFlowDelta(outcome="campaign over — supplies exhausted", phase="gameover")

    return CombatStepResult(death_audio=death, flow=flow)
