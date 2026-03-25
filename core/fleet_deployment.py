"""
Fleet preview / deployment rules (scrap, hull add/remove, weapon loadout choices).

Used by LoadoutsScene and re-exported from demo_game for the legacy run() path.
Does not import demo_game at module load; uses lazy imports where ship factories are required.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    from combat_constants import WORLD_H, WORLD_W
    from combat_engine import weapon_range
except ImportError:
    from core.combat_constants import WORLD_H, WORLD_W
    from core.combat_engine import weapon_range

# Mirror demo_game pre-mission designer + store capital list.
DEPLOYMENT_STARTING_SCRAP = 420
DEPLOYMENT_MIN_CAPITALS = 1
MAX_PLAYER_CAPITALS = 14
HULL_CLASSES_DEPLOYABLE = ("Frigate", "Destroyer", "Cruiser", "Battleship", "Carrier")

RECRUIT_LABEL_PREFIX = {
    "Frigate": "FF",
    "Destroyer": "DD",
    "Cruiser": "CG",
    "Battleship": "BB",
    "Carrier": "CV",
}


def ship_class_by_name(data: dict, name: str) -> dict:
    for sc in data["ship_classes"]:
        if sc["name"] == name:
            return sc
    raise KeyError(name)


def deploy_anchor_xy() -> Tuple[float, float]:
    return WORLD_W * 0.5, WORLD_H * 0.86


def weapon_loadout_slot_choices(data: dict, slot: dict) -> List[dict]:
    cset = slot.get("choice_set")
    if cset:
        sets = data.get("weapon_loadout_choice_sets") or {}
        row = sets.get(str(cset))
        if row is None:
            raise KeyError(f"weapon_loadout_choice_sets[{cset!r}] missing")
        return [dict(x) for x in row]
    return [dict(x) for x in (slot.get("choices") or [])]


def weapon_loadout_options_expanded(data: dict, sc: dict) -> List[dict]:
    out: List[dict] = []
    for slot in sc.get("weapon_loadout_options") or []:
        e = dict(slot)
        e["choices"] = weapon_loadout_slot_choices(data, slot)
        out.append(e)
    return out


def resolve_weapon_entry(data: dict, entry: dict) -> Tuple[str, str, float]:
    if "module_id" in entry:
        mid = str(entry["module_id"])
        mods = data.get("weapon_modules") or {}
        if mid not in mods:
            raise KeyError(f"weapon_modules[{mid!r}] missing")
        m = mods[mid]
        return str(m["name"]), str(m["projectile"]), float(m["fire_rate"])
    return str(entry["name"]), str(entry["projectile"]), float(entry["fire_rate"])


def class_max_weapon_range(data: dict, sc: dict) -> float:
    weapons = sc.get("weapons") or []
    if not weapons:
        return 120.0
    return max(
        weapon_range(data, {"projectile": pn, "fire_rate": fr})
        for _, pn, fr in (resolve_weapon_entry(data, w) for w in weapons)
    )


def group_max_range_from_weapons(data: dict, weapons: List[Any]) -> float:
    if not weapons:
        return 120.0
    return max(weapon_range(data, {"projectile": w.projectile_name}) for w in weapons)


def deployment_cost_for_class(data: dict, class_name: str) -> int:
    sc = ship_class_by_name(data, class_name)
    v = sc.get("deployment_cost")
    if v is not None:
        return int(v)
    if sc.get("render") == "capital":
        return 72
    return 0


def purge_loadout_choices_for_label(choice_map: Dict[Tuple[str, int], int], label: str) -> None:
    for k in list(choice_map.keys()):
        if k[0] == label:
            del choice_map[k]


def sync_loadout_choice_map_for_group(
    data: dict, g: Any, choice_map: Dict[Tuple[str, int], int]
) -> None:
    sc = ship_class_by_name(data, g.class_name)
    opts = weapon_loadout_options_expanded(data, sc)
    for si, slot in enumerate(opts):
        wi = int(slot["weapon_index"])
        if wi < 0 or wi >= len(g.weapons):
            continue
        rw = g.weapons[wi]
        choices = slot["choices"]
        best_i = 0
        for ci, ch in enumerate(choices):
            name, pn, fr = resolve_weapon_entry(data, ch)
            if (
                pn == rw.projectile_name
                and abs(fr - rw.fire_rate) < 1e-4
                and name == rw.name
            ):
                best_i = ci
                break
        else:
            for ci, ch in enumerate(choices):
                name, pn, fr = resolve_weapon_entry(data, ch)
                if pn == rw.projectile_name and abs(fr - rw.fire_rate) < 1e-4:
                    best_i = ci
                    break
        choice_map[(g.label, si)] = best_i


def apply_deployment_weapon_choice(
    data: dict,
    g: Any,
    loadout_slot_i: int,
    new_choice_i: int,
    choice_map: Dict[Tuple[str, int], int],
    deployment_scrap: List[int],
) -> bool:
    try:
        from core.demo_game import RuntimeWeapon
    except ImportError:
        from demo_game import RuntimeWeapon

    sc = ship_class_by_name(data, g.class_name)
    opts = weapon_loadout_options_expanded(data, sc)
    if loadout_slot_i < 0 or loadout_slot_i >= len(opts):
        return False
    slot = opts[loadout_slot_i]
    choices = slot["choices"]
    if new_choice_i < 0 or new_choice_i >= len(choices):
        return False
    key = (g.label, loadout_slot_i)
    cur_i = choice_map.get(key, 0)
    if new_choice_i == cur_i:
        return True
    old_c = int(choices[cur_i].get("scrap_cost", 0))
    new_c = int(choices[new_choice_i].get("scrap_cost", 0))
    net_scrap = new_c - old_c
    if net_scrap > 0 and deployment_scrap[0] < net_scrap:
        return False
    wi = int(slot["weapon_index"])
    if wi < 0 or wi >= len(g.weapons):
        return False
    deployment_scrap[0] -= net_scrap
    choice_map[key] = new_choice_i
    ch = choices[new_choice_i]
    wn, pn, fr = resolve_weapon_entry(data, ch)
    g.weapons[wi] = RuntimeWeapon(
        name=wn,
        projectile_name=pn,
        fire_rate=float(fr),
        cooldown=0.0,
    )
    g.max_range = group_max_range_from_weapons(data, g.weapons)
    return True


def player_capital_count(groups: List[Any]) -> int:
    return sum(1 for g in groups if g.side == "player" and not g.dead and g.render_capital)


def next_recruit_label(groups: List[Any], class_name: str) -> str:
    prefix = RECRUIT_LABEL_PREFIX[class_name]
    nums: List[int] = []
    for g in groups:
        if g.side != "player" or g.class_name != class_name:
            continue
        if g.label.startswith(prefix + "-"):
            try:
                nums.append(int(g.label.split("-", 1)[1]))
            except ValueError:
                pass
    n = max(nums) + 1 if nums else 1
    return f"{prefix}-{n}"


def recruit_spawn_xy(groups: List[Any]) -> Tuple[float, float]:
    ax, ay = deploy_anchor_xy()
    n = sum(1 for g in groups if g.side == "player" and not g.dead and g.render_capital)
    x = ax - 420 + (n % 6) * 150.0
    y = ay + 36 + (n // 6) * 48.0
    return x, y


def loadout_try_add_capital(
    data: dict,
    preview_groups: List[Any],
    preview_crafts: List[Any],
    class_name: str,
    deployment_scrap: List[int],
    choice_map: Dict[Tuple[str, int], int],
) -> bool:
    try:
        from core.demo_game import recruit_player_capital
    except ImportError:
        from demo_game import recruit_player_capital

    if player_capital_count(preview_groups) >= MAX_PLAYER_CAPITALS:
        return False
    cost = deployment_cost_for_class(data, class_name)
    if deployment_scrap[0] < cost:
        return False
    deployment_scrap[0] -= cost
    recruit_player_capital(
        data,
        preview_groups,
        preview_crafts,
        class_name,
        control_groups=None,
        loadout_choice_map=choice_map,
    )
    return True


def loadout_try_remove_capital(
    data: dict,
    preview_groups: List[Any],
    preview_crafts: List[Any],
    g: Any,
    deployment_scrap: List[int],
    choice_map: Dict[Tuple[str, int], int],
) -> bool:
    if player_capital_count(preview_groups) <= DEPLOYMENT_MIN_CAPITALS:
        return False
    if g not in preview_groups:
        return False
    deployment_scrap[0] += deployment_cost_for_class(data, g.class_name)
    purge_loadout_choices_for_label(choice_map, g.label)
    preview_groups[:] = [x for x in preview_groups if x is not g]
    preview_crafts[:] = [c for c in preview_crafts if c.parent is not g]
    return True
