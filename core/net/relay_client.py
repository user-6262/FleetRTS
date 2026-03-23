from __future__ import annotations

import json
import queue
import socket
import threading
from typing import Any, Dict, List, Optional

from net.protocol import RELAY_PROTOCOL_V1


class RelayClient:
    """
    Non-blocking-ish relay: background thread reads \\n-delimited JSON lines into a queue.
    Main thread calls poll() each frame.
    """

    def __init__(self, host: str, port: int, lobby_id: str, player: str) -> None:
        self._host = host
        self._port = int(port)
        self._lobby_id = lobby_id
        self._player = player
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._err: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def error(self) -> Optional[str]:
        return self._err

    def connect(self) -> None:
        self.close()
        self._stop.clear()
        self._err = None
        try:
            s = socket.create_connection((self._host, self._port), timeout=8)
            s.settimeout(30.0)
            self._sock = s
        except OSError as e:
            self._err = str(e)
            self._sock = None
            return

        hello = {
            "t": "join",
            "lobby_id": self._lobby_id,
            "player": self._player,
            "protocol": RELAY_PROTOCOL_V1,
        }
        try:
            self._sock.sendall((json.dumps(hello, separators=(",", ":")) + "\n").encode("utf-8"))
        except OSError as e:
            self._err = str(e)
            self._close_sock()
            return

        self._thread = threading.Thread(target=self._reader_loop, name="fleetrts-relay", daemon=True)
        self._thread.start()

    def _close_sock(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self) -> None:
        self._stop.set()
        self._close_sock()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._buf.clear()

    def _reader_loop(self) -> None:
        assert self._sock is not None
        s = self._sock
        try:
            while not self._stop.is_set():
                chunk = s.recv(8192)
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
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        self._q.put(obj)
        except OSError as e:
            if not self._stop.is_set():
                self._err = str(e)
        finally:
            self._close_sock()

    def poll(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out

    def send_payload(self, body: Dict[str, Any]) -> None:
        if self._sock is None:
            return
        msg = json.dumps({"t": "client_msg", "body": body}, separators=(",", ":")) + "\n"
        try:
            self._sock.sendall(msg.encode("utf-8"))
        except OSError as e:
            self._err = str(e)
            self._close_sock()
