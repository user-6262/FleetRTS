#!/usr/bin/env python3
"""
FleetRTS TCP relay — newline-delimited JSON broadcast per lobby room.

Pairs with droplet_http_stub.py: clients obtain lobby_id via HTTP, then connect here
so peers in the same lobby can exchange messages (chat, future lockstep / state).

Run locally (second terminal after HTTP stub):
  python tcp_relay.py
  python tcp_relay.py --host 0.0.0.0 --port 8766

Protocol (v1)
-------------
Client -> server (first line on connection):
  {"t":"join","lobby_id":"<uuid>","player":"<name>","protocol":1}

Client -> server (after join):
  {"t":"client_msg","body":{...}}

Server -> client:
  {"t":"joined","lobby_id":"...","players":["a","b"]}
  {"t":"relay","from":"alice","body":{...}}
  {"t":"peer_left","player":"bob","players":[...]}
  {"t":"error","code":"...","message":"..."}
"""
from __future__ import annotations

import argparse
import json
import socket
import threading
import uuid
from typing import Any, Dict, List

RELAY_PROTOCOL_V1 = 1


def _relay_unique_display_name(existing: List[str], base: str) -> str:
    base = (base or "player").strip()[:64] or "player"
    if base not in existing:
        return base
    n = 2
    while n < 5000:
        suffix = f" ({n})"
        max_base = max(1, 64 - len(suffix))
        cand = (base[:max_base] + suffix)[:64]
        if cand not in existing:
            return cand
        n += 1
    return f"{base[:48]}_{uuid.uuid4().hex[:8]}"[:64]

_lock = threading.Lock()
# lobby_id -> list of ClientHandler (append under lock)
_rooms: Dict[str, List["ClientHandler"]] = {}


class ClientHandler(threading.Thread):
    daemon = True

    def __init__(self, sock: socket.socket, addr: Any) -> None:
        super().__init__(name=f"relay-{addr}")
        self.sock = sock
        self.addr = addr
        self.player = "?"
        self.lobby_id: str = ""
        self._buf = bytearray()

    def send_obj(self, obj: Dict[str, Any]) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self.sock.sendall(data)
        except OSError:
            pass

    def broadcast(self, obj: Dict[str, Any], skip_self: bool = False) -> None:
        with _lock:
            peers = list(_rooms.get(self.lobby_id, []))
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
        for h in peers:
            if skip_self and h is self:
                continue
            try:
                h.sock.sendall(data)
            except OSError:
                pass

    def remove_from_room(self) -> None:
        if not self.lobby_id:
            return
        with _lock:
            room = _rooms.get(self.lobby_id)
            if not room:
                return
            room[:] = [h for h in room if h is not self]
            players = [h.player for h in room]
            if not room:
                del _rooms[self.lobby_id]
        left = {"t": "peer_left", "player": self.player, "players": players}
        self.broadcast(left, skip_self=True)

    def run(self) -> None:
        try:
            self.sock.settimeout(300.0)
            while True:
                chunk = self.sock.recv(8192)
                if not chunk:
                    break
                self._buf.extend(chunk)
                while True:
                    i = self._buf.find(b"\n")
                    if i < 0:
                        break
                    line = bytes(self._buf[:i]).decode("utf-8", errors="replace")
                    del self._buf[: i + 1]
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        self.send_obj({"t": "error", "code": "bad_json", "message": "invalid JSON line"})
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if not self.lobby_id:
                        self._handle_join(msg)
                    else:
                        self._handle_client_msg(msg)
        except OSError:
            pass
        finally:
            self.remove_from_room()
            try:
                self.sock.close()
            except OSError:
                pass

    def _handle_join(self, msg: Dict[str, Any]) -> None:
        if msg.get("t") != "join":
            self.send_obj({"t": "error", "code": "expected_join", "message": "first message must be join"})
            self.lobby_id = ""  # prevent remove_from_room side effects
            try:
                self.sock.close()
            except OSError:
                pass
            return
        lid = str(msg.get("lobby_id") or "").strip()
        player = str(msg.get("player") or "player")[:64]
        proto = int(msg.get("protocol") or 0)
        if proto != RELAY_PROTOCOL_V1:
            self.send_obj({"t": "error", "code": "bad_protocol", "message": f"need protocol {RELAY_PROTOCOL_V1}"})
            return
        if len(lid) < 8:
            self.send_obj({"t": "error", "code": "bad_lobby", "message": "lobby_id required"})
            return
        self.lobby_id = lid
        with _lock:
            room = _rooms.setdefault(lid, [])
            taken = [h.player for h in room]
            self.player = _relay_unique_display_name(taken, player or "?")
            room.append(self)
            players = [h.player for h in room]
        joined = {"t": "joined", "lobby_id": lid, "players": players}
        self.broadcast(joined, skip_self=False)

    def _handle_client_msg(self, msg: Dict[str, Any]) -> None:
        if msg.get("t") != "client_msg":
            return
        body = msg.get("body")
        if not isinstance(body, dict):
            body = {}
        self.broadcast({"t": "relay", "from": self.player, "body": body}, skip_self=True)


def serve(host: str, port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(64)
    print(f"FleetRTS tcp_relay listening on {host}:{port}")
    try:
        while True:
            sock, addr = listener.accept()
            ClientHandler(sock, addr).start()
    except KeyboardInterrupt:
        print("\nShutting down relay.")
    finally:
        listener.close()


def main() -> None:
    p = argparse.ArgumentParser(description="FleetRTS TCP relay (lobby broadcast).")
    p.add_argument("--host", default="127.0.0.1", help="Bind address (0.0.0.0 on droplet)")
    p.add_argument("--port", type=int, default=8766, help="TCP port")
    args = p.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
