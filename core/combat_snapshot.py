"""
Serialize / apply authoritative combat state for host→client MP sync.

Uses lazy demo_game imports inside functions to avoid import cycles.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from combat_constants import FOG_CH, FOG_CW
except ImportError:
    from core.combat_constants import FOG_CH, FOG_CW

SNAP_VERSION = 3


def _roundf(x: Any, nd: int = 5) -> Any:
    if isinstance(x, float):
        return round(x, nd)
    return x


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_state_dict(state: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(state)).hexdigest()


def _attack_target_ref(
    tgt: Any,
    mission: Any,
    missiles: List[Any],
) -> Optional[Dict[str, Any]]:
    if tgt is None:
        return None
    import demo_game as dg

    if isinstance(tgt, dg.GroundObjective):
        if mission.objective is tgt:
            return {"k": "objective"}
        return {"k": "ground", "x": _roundf(tgt.x), "y": _roundf(tgt.y)}
    if isinstance(tgt, dg.Group):
        return {"k": "group", "label": tgt.label, "side": tgt.side}
    if isinstance(tgt, dg.Craft):
        return {"k": "craft", "label": tgt.label}
    if isinstance(tgt, dg.Missile):
        try:
            i = missiles.index(tgt)
        except ValueError:
            i = -1
        return {"k": "missile", "i": i}
    return None


def _resolve_attack_target(
    ref: Optional[Dict[str, Any]],
    mission: Any,
    label_group: Dict[str, Any],
    label_craft: Dict[str, Any],
    missiles: List[Any],
) -> Any:
    if not ref:
        return None
    import demo_game as dg

    k = ref.get("k")
    if k == "objective":
        return mission.objective
    if k == "ground":
        if mission.objective and not mission.objective.dead:
            return mission.objective
        return None
    if k == "group":
        g = label_group.get(ref.get("label") or "")
        if g and getattr(g, "side", None) == ref.get("side"):
            return g
        return label_group.get(ref.get("label") or "")
    if k == "craft":
        return label_craft.get(ref.get("label") or "")
    if k == "missile":
        i = int(ref.get("i", -1))
        if 0 <= i < len(missiles):
            return missiles[i]
        return None
    return None


def _serialize_weapons(ws: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for w in ws:
        out.append(
            {
                "name": w.name,
                "projectile_name": w.projectile_name,
                "fire_rate": _roundf(w.fire_rate, 6),
                "cooldown": _roundf(w.cooldown, 6),
            }
        )
    return out


def _apply_weapons(g: Any, rows: List[Dict[str, Any]]) -> None:
    import demo_game as dg

    by_pn: Dict[str, List[dg.RuntimeWeapon]] = {}
    for w in g.weapons:
        by_pn.setdefault(w.projectile_name, []).append(w)
    used: Set[int] = set()
    for row in rows:
        pn = row.get("projectile_name")
        name = row.get("name")
        pool = by_pn.get(pn) or []
        cand = None
        for w in pool:
            wid = id(w)
            if wid in used:
                continue
            if w.name == name:
                cand = w
                break
        if cand is None:
            for w in pool:
                wid = id(w)
                if wid not in used:
                    cand = w
                    break
        if cand is not None:
            cand.cooldown = float(row.get("cooldown", 0.0))
            used.add(id(cand))


def snapshot_state(
    *,
    tick: int,
    round_idx: int,
    mission: Any,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    ballistics: List[Any],
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    supplies: List[float],
    pd_rof_mult: List[float],
    cg_weapons_free: List[bool],
    control_groups: List[Any],
    fog: Any,
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    seeker_ghosts: List[Any],
    ping_ghost_anchor_labels: Set[str],
    ping_ready_at_ms: int,
    outcome: Optional[str],
    phase: str,
    salvage: float,
    run_total_score: int,
    last_salvage_gain: int,
    store_selected: Optional[str],
    store_hover: Optional[str],
) -> Dict[str, Any]:
    gl = []
    for g in sorted(groups, key=lambda x: (x.side, x.label)):
        gl.append(
            {
                "side": g.side,
                "owner_id": getattr(g, "owner_id", "player"),
                "color_id": int(getattr(g, "color_id", 0)),
                "label": g.label,
                "class_name": g.class_name,
                "x": _roundf(g.x),
                "y": _roundf(g.y),
                "z": _roundf(g.z),
                "max_hp": _roundf(g.max_hp),
                "hp": _roundf(g.hp),
                "speed": _roundf(g.speed),
                "max_range": _roundf(g.max_range),
                "dead": bool(g.dead),
                "waypoint": [ _roundf(g.waypoint[0]), _roundf(g.waypoint[1]) ] if g.waypoint else None,
                "move_pace_key": g.move_pace_key,
                "strike_rally": [ _roundf(g.strike_rally[0]), _roundf(g.strike_rally[1]) ] if g.strike_rally else None,
                "strike_rally_wings": [
                    [ _roundf(t[0]), _roundf(t[1]) ] if t else None for t in g.strike_rally_wings
                ],
                "attack_move": bool(g.attack_move),
                "pd_overheat_streak": _roundf(g.pd_overheat_streak, 6),
                "engagement_timer": _roundf(g.engagement_timer, 6),
                "attack_target": _attack_target_ref(g.attack_target, mission, missiles),
                "strike_focus_target": _attack_target_ref(
                    getattr(g, "strike_focus_target", None), mission, missiles
                ),
                "render_capital": bool(g.render_capital),
                "hangar_loadout_choice": int(g.hangar_loadout_choice),
                "weapons": _serialize_weapons(g.weapons),
            }
        )
    cl = []
    for c in sorted(crafts, key=lambda x: (x.parent.label, x.label)):
        cl.append(
            {
                "side": c.side,
                "owner_id": getattr(c, "owner_id", getattr(c.parent, "owner_id", "player")),
                "color_id": int(getattr(c, "color_id", getattr(c.parent, "color_id", 0))),
                "label": c.label,
                "parent_label": c.parent.label,
                "class_name": c.class_name,
                "slot_index": int(c.slot_index),
                "squadron_index": int(c.squadron_index),
                "x": _roundf(c.x),
                "y": _roundf(c.y),
                "z": _roundf(c.z),
                "max_hp": _roundf(c.max_hp),
                "hp": _roundf(c.hp),
                "speed": _roundf(c.speed),
                "max_range": _roundf(c.max_range),
                "dead": bool(c.dead),
                "orbit_phase": _roundf(c.orbit_phase, 6),
                "heading": _roundf(c.heading, 6),
                "pd_overheat_streak": _roundf(c.pd_overheat_streak, 6),
                "engagement_timer": _roundf(c.engagement_timer, 6),
                "weapons": _serialize_weapons(c.weapons),
            }
        )
    ml = []
    for m in missiles:
        ml.append(
            {
                "x": _roundf(m.x),
                "y": _roundf(m.y),
                "vx": _roundf(m.vx),
                "vy": _roundf(m.vy),
                "speed": _roundf(m.speed),
                "damage": _roundf(m.damage),
                "turn_rate_rad": _roundf(m.turn_rate_rad, 6),
                "ttl": _roundf(m.ttl, 6),
                "side": m.side,
                "color": [int(m.color[0]), int(m.color[1]), int(m.color[2])],
                "proj_name": m.proj_name,
                "z": _roundf(m.z),
                "target": _attack_target_ref(m.target, mission, missiles),
                "anim_t": _roundf(m.anim_t, 6),
                "launch_speed": _roundf(m.launch_speed, 6),
                "boost_elapsed": _roundf(m.boost_elapsed, 6),
                "intercept_hp": _roundf(m.intercept_hp, 6),
            }
        )
    bl = []
    for s in ballistics:
        bl.append(
            {
                "x": _roundf(s.x),
                "y": _roundf(s.y),
                "z": _roundf(s.z),
                "vx": _roundf(s.vx),
                "vy": _roundf(s.vy),
                "vz": _roundf(s.vz),
                "damage": _roundf(s.damage),
                "side": s.side,
                "proj_name": s.proj_name,
                "age": _roundf(s.age, 6),
            }
        )
    vxs = []
    for s in vfx_sparks:
        vxs.append(
            {
                "x": _roundf(s.x),
                "y": _roundf(s.y),
                "vx": _roundf(s.vx),
                "vy": _roundf(s.vy),
                "ttl": _roundf(s.ttl, 6),
                "max_ttl": _roundf(s.max_ttl, 6),
                "radius": int(s.radius),
                "color": [int(s.color[0]), int(s.color[1]), int(s.color[2])],
            }
        )
    vxb = []
    for b in vfx_beams:
        vxb.append(
            {
                "x0": _roundf(b.x0),
                "y0": _roundf(b.y0),
                "x1": _roundf(b.x1),
                "y1": _roundf(b.y1),
                "ttl": _roundf(b.ttl, 6),
                "max_ttl": _roundf(b.max_ttl, 6),
                "color": [int(b.color[0]), int(b.color[1]), int(b.color[2])],
                "width": int(b.width),
            }
        )
    obj = None
    if mission.objective:
        o = mission.objective
        obj = {
            "x": _roundf(o.x),
            "y": _roundf(o.y),
            "z": _roundf(o.z),
            "hp": _roundf(o.hp),
            "max_hp": _roundf(o.max_hp),
            "radius": _roundf(o.radius),
            "dead": bool(o.dead),
        }
    pods = [
        {
            "x": _roundf(p.x),
            "y": _roundf(p.y),
            "value": int(p.value),
            "collected": bool(p.collected),
        }
        for p in mission.pods
    ]
    obs = [{"x": _roundf(o.x), "y": _roundf(o.y), "r": _roundf(o.r)} for o in mission.obstacles]
    n = FOG_CW * FOG_CH
    ex = "".join("1" if fog.explored[i] else "0" for i in range(min(n, len(fog.explored))))
    vis = "".join("1" if fog.visible[i] else "0" for i in range(min(n, len(fog.visible))))
    pings = [{"x": _roundf(p.x), "y": _roundf(p.y), "ttl": _roundf(p.ttl, 6), "radius": _roundf(p.radius)} for p in active_pings]
    ghosts = [
        {
            "x": _roundf(g.x),
            "y": _roundf(g.y),
            "ttl": _roundf(g.ttl, 6),
            "label": g.label,
            "quality": _roundf(g.quality, 6),
        }
        for g in sensor_ghosts
    ]
    sk = [
        {
            "x": _roundf(g.x),
            "y": _roundf(g.y),
            "ttl": _roundf(g.ttl, 6),
            "label": g.label,
            "quality": _roundf(g.quality, 6),
        }
        for g in seeker_ghosts
    ]
    cg = []
    for row in control_groups:
        if row is None:
            cg.append(None)
        else:
            cg.append(list(row))
    return {
        "snap_version": SNAP_VERSION,
        "tick": int(tick),
        "round_idx": int(round_idx),
        "mission": {
            "kind": mission.kind,
            "mp_pvp": bool(getattr(mission, "mp_pvp", False)),
            "pvp_scrap": {
                str(k): int(v)
                for k, v in (getattr(mission, "pvp_scrap", {}) or {}).items()
                if str(k).strip()
            },
            "pvp_territory": {
                str(k): str(v)
                for k, v in (getattr(mission, "pvp_territory", {}) or {}).items()
                if str(k).strip()
            },
            "pvp_battlegroups": {
                str(k): list(v) if isinstance(v, list) else []
                for k, v in (getattr(mission, "pvp_battlegroups", {}) or {}).items()
                if str(k).strip()
            },
            "objective": obj,
            "pods": pods,
            "reinf_remaining": int(mission.reinf_remaining),
            "reinf_timer": _roundf(mission.reinf_timer, 6),
            "pods_collected": int(mission.pods_collected),
            "pods_required": int(mission.pods_required),
            "enemy_label_serial": int(mission.enemy_label_serial),
            "initial_enemies_spawned": int(mission.initial_enemies_spawned),
            "obstacles": obs,
        },
        "groups": gl,
        "crafts": cl,
        "missiles": ml,
        "ballistics": bl,
        "vfx_sparks": vxs,
        "vfx_beams": vxb,
        "supplies": _roundf(supplies[0], 6) if supplies else 0.0,
        "pd_rof_mult": _roundf(pd_rof_mult[0], 6) if pd_rof_mult else 1.0,
        "cg_weapons_free": [bool(x) for x in cg_weapons_free],
        "control_groups": cg,
        "fog_explored_bits": ex,
        "fog_visible_bits": vis,
        "active_pings": pings,
        "sensor_ghosts": ghosts,
        "seeker_ghosts": sk,
        "ping_anchor_labels": sorted(ping_ghost_anchor_labels),
        "ping_ready_at_ms": int(ping_ready_at_ms),
        "outcome": outcome,
        "phase": phase,
        "salvage": _roundf(salvage, 6),
        "run_total_score": int(run_total_score),
        "last_salvage_gain": int(last_salvage_gain),
        "store_selected": store_selected,
        "store_hover": store_hover,
    }


def apply_snapshot_state(
    *,
    data: dict,
    state: Dict[str, Any],
    mission: Any,
    groups: List[Any],
    crafts: List[Any],
    missiles: List[Any],
    ballistics: List[Any],
    vfx_sparks: List[Any],
    vfx_beams: List[Any],
    supplies: List[float],
    pd_rof_mult: List[float],
    cg_weapons_free: List[bool],
    control_groups: List[Any],
    fog: Any,
    active_pings: List[Any],
    sensor_ghosts: List[Any],
    seeker_ghosts: List[Any],
    ping_ghost_anchor_labels: Set[str],
) -> Tuple[int, Optional[str], str, int, float, int, int, Optional[str], Optional[str]]:
    """Returns tick, outcome, phase, ping_ready_at_ms, salvage, run_total_score, last_salvage_gain, store_sel, store_hov."""
    import demo_game as dg

    if int(state.get("snap_version", 0)) != SNAP_VERSION:
        raise ValueError(f"unsupported snap_version {state.get('snap_version')}")
    tick = int(state["tick"])
    if supplies:
        supplies[0] = float(state.get("supplies", 0.0))
    if pd_rof_mult:
        pd_rof_mult[0] = float(state.get("pd_rof_mult", 1.0))
    cw = state.get("cg_weapons_free") or []
    for i in range(min(len(cg_weapons_free), len(cw))):
        cg_weapons_free[i] = bool(cw[i])
    cg = state.get("control_groups") or []
    slots = dg.CONTROL_GROUP_SLOTS
    while len(control_groups) < slots:
        control_groups.append(None)
    control_groups[:] = control_groups[:slots]
    for i in range(slots):
        row = cg[i] if i < len(cg) else None
        control_groups[i] = None if row is None else list(row)

    ms = state["mission"]
    mission.kind = str(ms["kind"])
    mission.mp_pvp = bool(ms.get("mp_pvp", False))
    mission.pvp_scrap = {
        str(k): int(v)
        for k, v in (ms.get("pvp_scrap") or {}).items()
        if str(k).strip()
    }
    mission.pvp_territory = {
        str(k): str(v)
        for k, v in (ms.get("pvp_territory") or {}).items()
        if str(k).strip()
    }
    mission.pvp_battlegroups = {
        str(k): list(v) if isinstance(v, list) else []
        for k, v in (ms.get("pvp_battlegroups") or {}).items()
        if str(k).strip()
    }
    mission.reinf_remaining = int(ms["reinf_remaining"])
    mission.reinf_timer = float(ms["reinf_timer"])
    mission.pods_collected = int(ms["pods_collected"])
    mission.pods_required = int(ms["pods_required"])
    mission.enemy_label_serial = int(ms["enemy_label_serial"])
    mission.initial_enemies_spawned = int(ms["initial_enemies_spawned"])
    if mission.objective and ms.get("objective"):
        o = ms["objective"]
        ob = mission.objective
        ob.x, ob.y, ob.z = float(o["x"]), float(o["y"]), float(o["z"])
        ob.hp, ob.max_hp = float(o["hp"]), float(o["max_hp"])
        ob.radius = float(o["radius"])
        ob.dead = bool(o["dead"])
    mission.pods.clear()
    for p in ms.get("pods") or []:
        mission.pods.append(
            dg.SalvagePod(
                x=float(p["x"]),
                y=float(p["y"]),
                value=int(p.get("value", dg.SALVAGE_POD_VALUE)),
                collected=bool(p.get("collected")),
            )
        )
    mission.obstacles.clear()
    for o in ms.get("obstacles") or []:
        mission.obstacles.append(dg.Asteroid(float(o["x"]), float(o["y"]), float(o["r"])))

    n = FOG_CW * FOG_CH
    ex = state.get("fog_explored_bits") or ""
    vis = state.get("fog_visible_bits") or ""
    for i in range(min(n, len(ex))):
        fog.explored[i] = ex[i] == "1"
    for i in range(min(n, len(vis))):
        fog.visible[i] = vis[i] == "1"

    ping_ghost_anchor_labels.clear()
    ping_ghost_anchor_labels.update(str(x) for x in (state.get("ping_anchor_labels") or []))

    label_group: Dict[str, Any] = {g.label: g for g in groups}

    g_rows = state.get("groups") or []
    seen_g: Set[str] = set()
    for gd in g_rows:
        lab = gd["label"]
        seen_g.add(lab)
        g = label_group.get(lab)
        if g is None:
            g = dg.make_group(
                data,
                gd["side"],
                lab,
                gd["class_name"],
                float(gd["x"]),
                float(gd["y"]),
                owner_id=str(gd.get("owner_id") or "player"),
                color_id=int(gd.get("color_id", 0)),
            )
            groups.append(g)
            label_group[lab] = g
        g.side = gd["side"]
        g.owner_id = str(gd.get("owner_id") or getattr(g, "owner_id", "player"))
        g.color_id = int(max(0, min(int(gd.get("color_id", getattr(g, "color_id", 0))), 5)))
        g.class_name = gd["class_name"]
        g.x, g.y, g.z = float(gd["x"]), float(gd["y"]), float(gd["z"])
        g.max_hp, g.hp = float(gd["max_hp"]), float(gd["hp"])
        g.speed, g.max_range = float(gd["speed"]), float(gd["max_range"])
        g.dead = bool(gd["dead"])
        wp = gd.get("waypoint")
        g.waypoint = (float(wp[0]), float(wp[1])) if wp else None
        g.move_pace_key = gd.get("move_pace_key")
        sr = gd.get("strike_rally")
        g.strike_rally = (float(sr[0]), float(sr[1])) if sr else None
        wings = gd.get("strike_rally_wings") or []
        while len(g.strike_rally_wings) < len(wings):
            g.strike_rally_wings.append(None)
        g.strike_rally_wings[:] = g.strike_rally_wings[: len(wings)]
        for i, t in enumerate(wings):
            g.strike_rally_wings[i] = (float(t[0]), float(t[1])) if t else None
        g.attack_move = bool(gd.get("attack_move"))
        g.pd_overheat_streak = float(gd.get("pd_overheat_streak", 0.0))
        g.engagement_timer = float(gd.get("engagement_timer", 0.0))
        g.render_capital = bool(gd.get("render_capital"))
        g.hangar_loadout_choice = int(gd.get("hangar_loadout_choice", 0))
        _apply_weapons(g, gd.get("weapons") or [])

    groups[:] = [g for g in groups if g.label in seen_g]
    label_group = {g.label: g for g in groups}

    label_craft: Dict[str, Any] = {c.label: c for c in crafts}
    c_rows = state.get("crafts") or []
    seen_c: Set[str] = set()
    for cd in c_rows:
        lab = cd["label"]
        seen_c.add(lab)
        parent = label_group.get(cd["parent_label"])
        if parent is None:
            continue
        c = label_craft.get(lab)
        if c is None:
            csc = dg.ship_class_by_name(data, cd["class_name"])
            spd = (22.0 + (float(csc["speed"]) / 100.0) * 95.0) * dg.SPEED_SCALE
            mr = dg.class_max_weapon_range(data, csc)
            c = dg.Craft(
                side=cd["side"],
                owner_id=str(cd.get("owner_id") or getattr(parent, "owner_id", "player")),
                color_id=int(cd.get("color_id", getattr(parent, "color_id", 0))),
                label=lab,
                class_name=cd["class_name"],
                parent=parent,
                slot_index=int(cd["slot_index"]),
                squadron_index=int(cd["squadron_index"]),
                x=float(cd["x"]),
                y=float(cd["y"]),
                max_hp=float(cd["max_hp"]),
                hp=float(cd["hp"]),
                speed=spd,
                max_range=mr,
                weapons=dg.build_runtime_weapons(data, csc),
                z=float(cd["z"]),
            )
            crafts.append(c)
            label_craft[lab] = c
        c.parent = parent
        c.side = cd["side"]
        c.owner_id = str(cd.get("owner_id") or getattr(parent, "owner_id", "player"))
        c.color_id = int(max(0, min(int(cd.get("color_id", getattr(parent, "color_id", 0))), 5)))
        c.class_name = cd["class_name"]
        c.slot_index = int(cd["slot_index"])
        c.squadron_index = int(cd["squadron_index"])
        c.x, c.y, c.z = float(cd["x"]), float(cd["y"]), float(cd["z"])
        c.max_hp, c.hp = float(cd["max_hp"]), float(cd["hp"])
        c.speed = float(cd["speed"])
        c.max_range = float(cd["max_range"])
        c.dead = bool(cd["dead"])
        c.orbit_phase = float(cd.get("orbit_phase", 0.0))
        c.heading = float(cd.get("heading", 0.0))
        c.pd_overheat_streak = float(cd.get("pd_overheat_streak", 0.0))
        c.engagement_timer = float(cd.get("engagement_timer", 0.0))
        _apply_weapons(c, cd.get("weapons") or [])

    crafts[:] = [c for c in crafts if c.label in seen_c]

    label_group = {g.label: g for g in groups}
    label_craft = {c.label: c for c in crafts}

    missiles.clear()
    m_rows = state.get("missiles") or []
    for md in m_rows:
        col = md["color"]
        missiles.append(
            dg.Missile(
                x=float(md["x"]),
                y=float(md["y"]),
                vx=float(md["vx"]),
                vy=float(md["vy"]),
                speed=float(md["speed"]),
                damage=float(md["damage"]),
                turn_rate_rad=float(md["turn_rate_rad"]),
                ttl=float(md["ttl"]),
                side=md["side"],
                color=(int(col[0]), int(col[1]), int(col[2])),
                proj_name=md["proj_name"],
                z=float(md["z"]),
                target=None,
                anim_t=float(md.get("anim_t", 0.0)),
                launch_speed=float(md.get("launch_speed", -1.0)),
                boost_elapsed=float(md.get("boost_elapsed", 0.0)),
                intercept_hp=float(md.get("intercept_hp", 1.0)),
            )
        )
    for md, m in zip(m_rows, missiles):
        m.target = _resolve_attack_target(md.get("target"), mission, label_group, label_craft, missiles)

    ballistics.clear()
    for bd in state.get("ballistics") or []:
        ballistics.append(
            dg.BallisticSlug(
                x=float(bd["x"]),
                y=float(bd["y"]),
                z=float(bd["z"]),
                vx=float(bd["vx"]),
                vy=float(bd["vy"]),
                vz=float(bd["vz"]),
                damage=float(bd["damage"]),
                side=bd["side"],
                proj_name=bd["proj_name"],
                age=float(bd.get("age", 0.0)),
            )
        )

    vfx_sparks.clear()
    for s in state.get("vfx_sparks") or []:
        col = s["color"]
        vfx_sparks.append(
            dg.VFXSpark(
                float(s["x"]),
                float(s["y"]),
                float(s["vx"]),
                float(s["vy"]),
                float(s["ttl"]),
                float(s["max_ttl"]),
                int(s["radius"]),
                (int(col[0]), int(col[1]), int(col[2])),
            )
        )
    vfx_beams.clear()
    for b in state.get("vfx_beams") or []:
        col = b["color"]
        vfx_beams.append(
            dg.VFXBeam(
                float(b["x0"]),
                float(b["y0"]),
                float(b["x1"]),
                float(b["y1"]),
                float(b["ttl"]),
                float(b["max_ttl"]),
                (int(col[0]), int(col[1]), int(col[2])),
                int(b["width"]),
            )
        )

    for g in groups:
        g.attack_target = None
        g.strike_focus_target = None
    for gd in g_rows:
        g = label_group.get(gd["label"])
        if g:
            g.attack_target = _resolve_attack_target(gd.get("attack_target"), mission, label_group, label_craft, missiles)
            g.strike_focus_target = _resolve_attack_target(
                gd.get("strike_focus_target"), mission, label_group, label_craft, missiles
            )

    active_pings.clear()
    for p in state.get("active_pings") or []:
        active_pings.append(
            dg.ActivePing(
                x=float(p["x"]),
                y=float(p["y"]),
                ttl=float(p["ttl"]),
                radius=float(p["radius"]),
            )
        )
    sensor_ghosts.clear()
    for g in state.get("sensor_ghosts") or []:
        sensor_ghosts.append(
            dg.SensorGhost(
                x=float(g["x"]),
                y=float(g["y"]),
                ttl=float(g["ttl"]),
                label=str(g.get("label", "")),
                quality=float(g.get("quality", 0.5)),
            )
        )
    seeker_ghosts.clear()
    for g in state.get("seeker_ghosts") or []:
        seeker_ghosts.append(
            dg.SensorGhost(
                x=float(g["x"]),
                y=float(g["y"]),
                ttl=float(g["ttl"]),
                label=str(g.get("label", "")),
                quality=float(g.get("quality", 0.5)),
            )
        )

    return (
        tick,
        state.get("outcome"),
        str(state.get("phase", "combat")),
        int(state.get("ping_ready_at_ms", 0)),
        float(state.get("salvage", 0.0)),
        int(state.get("run_total_score", 0)),
        int(state.get("last_salvage_gain", 0)),
        state.get("store_selected"),
        state.get("store_hover"),
    )
