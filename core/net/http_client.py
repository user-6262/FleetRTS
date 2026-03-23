from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class FleetHttpError(Exception):
    pass


def _post_headers() -> Dict[str, str]:
    h: Dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
    key = os.environ.get("FLEETRTS_API_KEY", "").strip()
    if key:
        h["X-FleetRTS-API-Key"] = key
    return h


def _post_json(url: str, body: Optional[dict], *, timeout: float = 12) -> Any:
    data = json.dumps(body or {}).encode("utf-8")
    req = Request(url, data=data, method="POST", headers=_post_headers())
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except OSError:
            detail = str(e)
        raise FleetHttpError(f"HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise FleetHttpError(str(e.reason or e)) from e


def _get_json(url: str, *, timeout: float = 12) -> Any:
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                raise FleetHttpError(f"invalid JSON from server: {e}") from e
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except OSError:
            detail = str(e)
        raise FleetHttpError(f"HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise FleetHttpError(str(e.reason or e)) from e


def create_lobby(
    base_url: str,
    name: Optional[str] = None,
    as_player: Optional[str] = None,
    *,
    authoritative: Optional[str] = None,
    match_type: Optional[str] = None,
) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if as_player is not None:
        body["player"] = as_player
    if authoritative in ("player", "dedicated"):
        body["authoritative"] = authoritative
    if match_type in ("custom", "public_queue"):
        body["match_type"] = match_type
    out = _post_json(f"{base}/api/v1/lobbies", body)
    if not isinstance(out, dict) or "lobby" not in out:
        raise FleetHttpError("unexpected response from create lobby")
    return out["lobby"]


def join_lobby(base_url: str, lobby_id: str, player_name: str) -> Tuple[Dict[str, Any], str]:
    base = base_url.rstrip("/")
    lid = lobby_id.strip()
    out = _post_json(f"{base}/api/v1/lobbies/{lid}/join", {"name": player_name})
    if not isinstance(out, dict) or "lobby" not in out:
        raise FleetHttpError("unexpected response from join lobby")
    joined_as = str(out.get("joined_as") or player_name)[:64]
    return out["lobby"], joined_as


def leave_lobby(base_url: str, lobby_id: str, display_name: str, *, timeout: float = 5) -> None:
    """Remove display_name from the lobby HTTP player list (best-effort; same string as join returned as joined_as)."""
    base = base_url.rstrip("/")
    lid = lobby_id.strip()
    name = (display_name or "").strip()[:64]
    if not lid or not name:
        return
    out = _post_json(f"{base}/api/v1/lobbies/{lid}/leave", {"name": name}, timeout=timeout)
    if not isinstance(out, dict) or out.get("ok") is not True:
        raise FleetHttpError("unexpected response from leave lobby")


def get_lobby(base_url: str, lobby_id: str) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    lid = lobby_id.strip()
    out = _get_json(f"{base}/api/v1/lobbies/{lid}")
    if not isinstance(out, dict) or "lobby" not in out:
        raise FleetHttpError("unexpected response from get lobby")
    return out["lobby"]


def get_lobby_by_short_id(base_url: str, short_id: str) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    sid = short_id.strip().lower()
    out = _get_json(f"{base}/api/v1/lobbies/by-short/{sid}")
    if not isinstance(out, dict) or "lobby" not in out:
        raise FleetHttpError("unexpected response from get lobby by short id")
    return out["lobby"]


def list_lobbies(base_url: str) -> List[Dict[str, Any]]:
    base = base_url.rstrip("/")
    # Short timeout: this runs on the pygame main thread during MP hub refresh.
    out = _get_json(f"{base}/api/v1/lobbies", timeout=4)
    if not isinstance(out, dict) or "lobbies" not in out:
        raise FleetHttpError("unexpected response from list lobbies")
    rows = out["lobbies"]
    return rows if isinstance(rows, list) else []


def quick_join(base_url: str, player_name: str) -> Tuple[Dict[str, Any], str, str]:
    """Returns (lobby, joined_as, quick_join_action) where action is 'joined' or 'created'."""
    base = base_url.rstrip("/")
    out = _post_json(f"{base}/api/v1/lobbies/quick-join", {"name": player_name})
    if not isinstance(out, dict) or "lobby" not in out:
        raise FleetHttpError("unexpected response from quick join")
    joined_as = str(out.get("joined_as") or player_name)[:64]
    action = str(out.get("quick_join") or "joined")
    return out["lobby"], joined_as, action
