#!/usr/bin/env python3
"""
FleetRTS droplet stub — HTTP API placeholder for matchmaking / lobby / future headless game.

Uses only the Python standard library. Safe to run on a VPS before the real authoritative
sim and protocol are wired up.

Run locally:
  python droplet_http_stub.py
  python droplet_http_stub.py --host 127.0.0.1 --port 8765

Run on droplet (listen on all interfaces):
  python3 droplet_http_stub.py --host 0.0.0.0 --port 8765

Optional environment:
  FLEETRTS_LOBBY_STORE=/var/lib/fleetrts/lobbies.json  — persist lobbies across restarts
  FLEETRTS_API_KEY=secret                             — require matching header on POST mutating routes
  FLEETRTS_POST_RATE_PER_MIN=120                      — max POSTs per client IP per rolling minute (0=disable)
  FLEETRTS_RELAY_HOST / FLEETRTS_RELAY_PORT           — relay address embedded in lobby JSON
  FLEETRTS_LOBBY_TTL_SEC=3600                         — drop lobby after this many seconds with no create/join (0=off)
  FLEETRTS_LOBBY_MAX_PLAYERS=8                        — cap players per lobby including host (0=unlimited)

Health check:
  curl -s http://127.0.0.1:8765/health

API highlights:
  GET  /api/v1/lobbies           — list sanitized lobbies (browser)
  POST /api/v1/lobbies/quick-join — join first open lobby or create public_queue waiting lobby
  Lobby fields: match_type (custom|public_queue), authoritative (player|dedicated), status (open|in_game)
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

STUB_VERSION = "4-list-quickjoin-schema"
API_PREFIX = "/api/v1"

_lobbies: Dict[str, Dict[str, Any]] = {}
_by_short: Dict[str, str] = {}
_lock = threading.Lock()

STORE_PATH = os.environ.get("FLEETRTS_LOBBY_STORE", "").strip()
API_KEY_REQUIRED = os.environ.get("FLEETRTS_API_KEY", "").strip()

_rate_limit_lock = threading.Lock()
_rate_by_ip: Dict[str, List[float]] = {}
_RATE_WINDOW_SEC = 60.0


def _relay_info() -> Dict[str, Any]:
    return {
        "host": os.environ.get("FLEETRTS_RELAY_HOST", "127.0.0.1"),
        "port": int(os.environ.get("FLEETRTS_RELAY_PORT", "8766")),
    }


def _now_ts() -> float:
    return time.time()


def _lobby_ttl_seconds() -> Optional[float]:
    raw = os.environ.get("FLEETRTS_LOBBY_TTL_SEC", "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


def _lobby_max_players() -> Optional[int]:
    raw = os.environ.get("FLEETRTS_LOBBY_MAX_PLAYERS", "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


def _stale_ref(lobby: Dict[str, Any]) -> float:
    u = lobby.get("updated_at")
    if isinstance(u, (int, float)):
        return float(u)
    c = lobby.get("created_at")
    if isinstance(c, (int, float)):
        return float(c)
    return _now_ts()


def _delete_lobby_locked(lid: str) -> None:
    lobby = _lobbies.pop(lid, None)
    if not lobby:
        return
    sid = lobby.get("short_id")
    if isinstance(sid, str) and sid:
        _by_short.pop(sid.lower(), None)


def _purge_all_expired_locked() -> None:
    ttl = _lobby_ttl_seconds()
    if ttl is None:
        return
    now = _now_ts()
    to_del = [lid for lid, lobby in list(_lobbies.items()) if now - _stale_ref(lobby) >= ttl]
    for lid in to_del:
        _delete_lobby_locked(lid)
    if to_del and STORE_PATH:
        _save_store_locked()


def _get_lobby_resolve_locked(lid: str) -> tuple[Optional[Dict[str, Any]], str]:
    """Return (lobby, status): status is ok | missing | expired."""
    lobby = _lobbies.get(lid)
    if not lobby:
        return None, "missing"
    ttl = _lobby_ttl_seconds()
    if ttl is not None and _now_ts() - _stale_ref(lobby) >= ttl:
        _delete_lobby_locked(lid)
        if STORE_PATH:
            _save_store_locked()
        return None, "expired"
    return lobby, "ok"


def _load_store() -> None:
    global _lobbies, _by_short
    if not STORE_PATH:
        return
    p = Path(STORE_PATH)
    if not p.is_file():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        lob = raw.get("lobbies")
        bs = raw.get("by_short")
        if not isinstance(lob, dict) or not isinstance(bs, dict):
            return
        loaded_lobbies: Dict[str, Dict[str, Any]] = {}
        for k, v in lob.items():
            if isinstance(v, dict):
                loaded_lobbies[str(k)] = v
        loaded_short: Dict[str, str] = {}
        for k, v in bs.items():
            if isinstance(v, str):
                loaded_short[str(k).lower()] = v
        with _lock:
            _lobbies = loaded_lobbies
            _by_short = loaded_short
            _purge_all_expired_locked()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        pass


def _save_store_locked() -> None:
    if not STORE_PATH:
        return
    path = Path(STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"lobbies": _lobbies, "by_short": _by_short}
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    tmp.write_bytes(data)
    tmp.replace(path)


def _post_rate_ok(handler: BaseHTTPRequestHandler) -> bool:
    try:
        max_n = int(os.environ.get("FLEETRTS_POST_RATE_PER_MIN", "120"))
    except ValueError:
        max_n = 120
    if max_n <= 0:
        return True
    ip = handler.client_address[0]
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW_SEC
    with _rate_limit_lock:
        q = _rate_by_ip.setdefault(ip, [])
        q[:] = [t for t in q if t >= cutoff]
        if len(q) >= max_n:
            return False
        q.append(now)
    return True


def _api_key_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not API_KEY_REQUIRED:
        return True
    got = handler.headers.get("X-FleetRTS-API-Key", "").strip()
    auth = handler.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        got = got or auth[7:].strip()
    return got == API_KEY_REQUIRED


def _default_match_type() -> str:
    return "custom"


def _default_authoritative() -> str:
    return "player"


def _lobby_joinable(lobby: Dict[str, Any]) -> bool:
    st = lobby.get("status") or "open"
    if st != "open":
        return False
    mt = lobby.get("match_type") or "custom"
    if mt not in ("custom", "public_queue"):
        return False
    mx = _lobby_max_players()
    n = len(lobby.get("players") or [])
    if mx is not None and n >= mx:
        return False
    return True


def _sanitize_lobby_summary(lobby: Dict[str, Any]) -> Dict[str, Any]:
    players = lobby.get("players") or []
    mx = _lobby_max_players()
    out: Dict[str, Any] = {
        "id": lobby.get("id"),
        "short_id": lobby.get("short_id"),
        "name": lobby.get("name"),
        "status": lobby.get("status") or "open",
        "match_type": lobby.get("match_type") or "custom",
        "authoritative": lobby.get("authoritative") or "player",
        "player_count": len(players),
    }
    if mx is not None:
        out["max_players"] = mx
    out["joinable"] = _lobby_joinable(lobby)
    return out


def _quick_join_locked(player_name: str) -> Tuple[Dict[str, Any], str, str]:
    """Join first joinable lobby or create a public_queue waiting lobby. Caller must hold _lock."""
    _purge_all_expired_locked()
    pname = (player_name or "player").strip()[:64] or "player"
    for lid in list(_lobbies.keys()):
        lobby, st = _get_lobby_resolve_locked(lid)
        if st != "ok" or not lobby or not _lobby_joinable(lobby):
            continue
        pl = lobby.setdefault("players", [])
        joined_as = _unique_display_name(list(pl), pname)
        pl.append(joined_as)
        lobby["updated_at"] = _now_ts()
        _save_store_locked()
        return lobby, joined_as, "joined"
    lid = str(uuid.uuid4())
    short = uuid.uuid4().hex[:8]
    ts = _now_ts()
    creator = _unique_display_name([], pname)
    lobby_n: Dict[str, Any] = {
        "id": lid,
        "short_id": short,
        "name": "public_queue",
        "status": "open",
        "match_type": "public_queue",
        "authoritative": _default_authoritative(),
        "players": [creator],
        "relay": _relay_info(),
        "game_host": None,
        "game_port": None,
        "created_at": ts,
        "updated_at": ts,
        "note": "Waiting for players — quick join / browser.",
    }
    _lobbies[lid] = lobby_n
    _by_short[short] = lid
    _save_store_locked()
    return lobby_n, creator, "created"


def _unique_display_name(players: list, base: str) -> str:
    """Ensure lobby player list has no duplicate display strings (e.g. second 'Player' -> 'Player (2)')."""
    base = (base or "player").strip()[:64] or "player"
    if base not in players:
        return base
    n = 2
    while n < 5000:
        suffix = f" ({n})"
        max_base = max(1, 64 - len(suffix))
        cand = (base[:max_base] + suffix)[:64]
        if cand not in players:
            return cand
        n += 1
    return f"{base[:48]}_{uuid.uuid4().hex[:8]}"[:64]


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: Any) -> None:
    data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Optional[Any]:
    try:
        n = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        n = 0
    if n <= 0:
        return None
    raw = handler.rfile.read(n)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


class DropletStubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Timestamps; tweak or route to file on the droplet if you prefer.
        super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            _json_response(
                self,
                200,
                {"ok": True, "service": "fleetrts-droplet-stub", "version": STUB_VERSION},
            )
            return
        if path == f"{API_PREFIX}/version":
            _json_response(
                self,
                200,
                {"version": STUB_VERSION, "protocol": 1, "note": "replace when game netcode ships"},
            )
            return
        if path == f"{API_PREFIX}/lobbies":
            with _lock:
                _purge_all_expired_locked()
                rows = []
                for lid in list(_lobbies.keys()):
                    lobby, st = _get_lobby_resolve_locked(lid)
                    if st != "ok" or not lobby:
                        continue
                    rows.append(_sanitize_lobby_summary(lobby))
            _json_response(self, 200, {"lobbies": rows})
            return
        if path.startswith(f"{API_PREFIX}/lobbies/by-short/"):
            short = path[len(f"{API_PREFIX}/lobbies/by-short/") :].strip("/").lower()
            if not short:
                _json_response(self, 404, {"error": "not_found"})
                return
            with _lock:
                lid = _by_short.get(short)
                lobby, st = _get_lobby_resolve_locked(lid) if lid else (None, "missing")
            if st == "expired":
                _json_response(self, 410, {"error": "lobby_expired", "short_id": short})
                return
            if not lobby:
                _json_response(self, 404, {"error": "lobby_not_found", "short_id": short})
                return
            _json_response(self, 200, {"lobby": lobby})
            return
        if path.startswith(f"{API_PREFIX}/lobbies/"):
            rest = path[len(f"{API_PREFIX}/lobbies/") :].strip("/")
            if not rest:
                _json_response(self, 404, {"error": "not_found"})
                return
            lobby_id = rest.split("/")[0]
            if lobby_id == "quick-join":
                _json_response(self, 404, {"error": "not_found", "hint": "POST for quick-join"})
                return
            with _lock:
                lobby, st = _get_lobby_resolve_locked(lobby_id)
            if st == "expired":
                _json_response(self, 410, {"error": "lobby_expired", "lobby_id": lobby_id})
                return
            if not lobby:
                _json_response(self, 404, {"error": "lobby_not_found", "lobby_id": lobby_id})
                return
            _json_response(self, 200, {"lobby": lobby})
            return
        _json_response(
            self,
            404,
            {"error": "not_found", "hint": "GET /health or " + f"{API_PREFIX}/version"},
        )

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if not _post_rate_ok(self):
            self.send_response(429)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b'{"error":"rate_limited"}')
            return

        if path == f"{API_PREFIX}/lobbies" or path == f"{API_PREFIX}/lobbies/quick-join" or (
            path.startswith(f"{API_PREFIX}/lobbies/") and path.endswith("/join")
        ):
            if not _api_key_ok(self):
                _json_response(self, 401, {"error": "unauthorized", "hint": "X-FleetRTS-API-Key header"})
                return

        body = _read_json_body(self)

        if path == f"{API_PREFIX}/lobbies/quick-join":
            player_name = "player"
            if isinstance(body, dict) and body.get("name"):
                player_name = str(body["name"])[:64]
            with _lock:
                lobby_q, joined_as_q, action = _quick_join_locked(player_name)
            _json_response(
                self,
                200,
                {"lobby": lobby_q, "joined_as": joined_as_q, "quick_join": action},
            )
            return

        if path == f"{API_PREFIX}/lobbies":
            name = None
            creator = "Host"
            match_type = _default_match_type()
            authoritative = _default_authoritative()
            if isinstance(body, dict):
                name = body.get("name")
                if body.get("player"):
                    creator = str(body["player"])[:64]
                mt = body.get("match_type")
                if mt in ("custom", "public_queue"):
                    match_type = str(mt)
                auth = body.get("authoritative")
                if auth in ("player", "dedicated"):
                    authoritative = str(auth)
            lid = str(uuid.uuid4())
            short = uuid.uuid4().hex[:8]
            ts = _now_ts()
            lobby = {
                "id": lid,
                "short_id": short,
                "name": name or "custom",
                "status": "open",
                "match_type": match_type,
                "authoritative": authoritative,
                "players": [creator],
                "relay": _relay_info(),
                "game_host": None,
                "game_port": None,
                "created_at": ts,
                "updated_at": ts,
                "note": "HTTP stub + tcp_relay — gameplay sync not wired yet.",
            }
            with _lock:
                _lobbies[lid] = lobby
                _by_short[short] = lid
                _save_store_locked()
            _json_response(self, 201, {"lobby": lobby})
            return

        if path.startswith(f"{API_PREFIX}/lobbies/") and path.endswith("/join"):
            prefix = f"{API_PREFIX}/lobbies/"
            mid = path[len(prefix) : -len("/join")]
            lobby_id = mid.strip("/").split("/")[0]
            player_name = "player"
            if isinstance(body, dict) and body.get("name"):
                player_name = str(body["name"])[:64]
            joined_as: Optional[str] = None
            lobby: Optional[Dict[str, Any]] = None
            err: Optional[tuple[int, Dict[str, Any]]] = None
            with _lock:
                lobby, st = _get_lobby_resolve_locked(lobby_id)
                if st == "expired":
                    err = (410, {"error": "lobby_expired", "lobby_id": lobby_id})
                elif not lobby:
                    err = (404, {"error": "lobby_not_found"})
                else:
                    mx = _lobby_max_players()
                    if mx is not None and len(lobby["players"]) >= mx:
                        err = (403, {"error": "lobby_full", "max_players": mx})
                    else:
                        joined_as = _unique_display_name(lobby["players"], player_name)
                        lobby["players"].append(joined_as)
                        lobby["updated_at"] = _now_ts()
                        _save_store_locked()
            if err:
                _json_response(self, err[0], err[1])
                return
            _json_response(self, 200, {"lobby": lobby, "joined_as": joined_as or player_name})
            return

        _json_response(self, 404, {"error": "not_found"})


def main() -> None:
    p = argparse.ArgumentParser(description="FleetRTS droplet HTTP stub (matchmaking placeholder).")
    p.add_argument("--host", default="127.0.0.1", help="Bind address (use 0.0.0.0 on droplet)")
    p.add_argument("--port", type=int, default=8765, help="TCP port")
    args = p.parse_args()
    _load_store()
    with _lock:
        _purge_all_expired_locked()
    server = ThreadingHTTPServer((args.host, args.port), DropletStubHandler)
    extra = []
    if STORE_PATH:
        extra.append(f"store={STORE_PATH}")
    if API_KEY_REQUIRED:
        extra.append("api_key=on")
    suffix = f" ({', '.join(extra)})" if extra else ""
    print(
        f"FleetRTS droplet stub listening on http://{args.host}:{args.port}/ "
        f"(GET /health, {API_PREFIX}/version, GET {API_PREFIX}/lobbies, POST …/quick-join){suffix}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
