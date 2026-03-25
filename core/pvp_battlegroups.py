"""PvP battlegroup preset schema and JSON helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class BattlegroupPreset:
    """Serializable PvP battlegroup entry used by future menu/editor flows."""

    preset_id: str
    name: str
    deploy_cost: int
    design_rows: List[Dict[str, str]] = field(default_factory=list)
    entry_tag: str = "spawn_edge"


def normalize_preset(raw: Dict[str, Any]) -> Optional[BattlegroupPreset]:
    pid = str(raw.get("preset_id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not pid or not name:
        return None
    rows_raw = raw.get("design_rows")
    rows: List[Dict[str, str]] = []
    if isinstance(rows_raw, list):
        for r in rows_raw:
            if not isinstance(r, dict):
                continue
            cls = str(r.get("class_name") or "").strip()
            if not cls:
                continue
            row: Dict[str, Any] = {
                "class_name": cls,
                "label": str(r.get("label") or "").strip(),
            }
            if "hangar_loadout_choice" in r:
                try:
                    row["hangar_loadout_choice"] = int(r["hangar_loadout_choice"])
                except (TypeError, ValueError):
                    pass
            rows.append(row)
    return BattlegroupPreset(
        preset_id=pid,
        name=name,
        deploy_cost=max(0, int(raw.get("deploy_cost", 0))),
        design_rows=rows,
        entry_tag=str(raw.get("entry_tag") or "spawn_edge"),
    )


def load_battlegroups(path: str) -> List[BattlegroupPreset]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: List[BattlegroupPreset] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pr = normalize_preset(item)
        if pr is not None:
            out.append(pr)
    return out


def save_battlegroups(path: str, presets: List[BattlegroupPreset]) -> None:
    payload = [
        {
            "preset_id": p.preset_id,
            "name": p.name,
            "deploy_cost": int(max(0, p.deploy_cost)),
            "design_rows": list(p.design_rows),
            "entry_tag": p.entry_tag,
        }
        for p in presets
    ]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_battlegroups_path() -> str:
    """User-writable JSON path (override with FLEETRTS_BATTLEGROUPS_PATH)."""
    override = os.environ.get("FLEETRTS_BATTLEGROUPS_PATH", "").strip()
    if override:
        return override
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            d = Path(appdata) / "FleetRTS"
            d.mkdir(parents=True, exist_ok=True)
            return str(d / "battlegroups.json")
    d = Path.home() / ".fleetrts"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "battlegroups.json")
