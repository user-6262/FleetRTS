FleetRTS — droplet server stub
==============================

What this is
------------
  server/droplet_http_stub.py is a tiny HTTP service using only Python’s standard
  library. It does NOT run the pygame client or the real RTS sim yet. It exists so
  you can:

    - Open firewall / DNS / systemd around a fixed port and path early
    - Point a future game client at http://YOUR_DROPLET:8765/api/v1/...
    - Replace the JSON file / in-memory store with Redis/Postgres + a real session broker

  server/tcp_relay.py is a separate TCP process (default port 8766) that broadcasts
  newline-delimited JSON per lobby room. The pygame client (when FLEETRTS_HTTP is
  set) creates/joins lobbies over HTTP, then connects to the relay using the host
  and port returned in the lobby JSON.

  Optional dedicated authoritative combat: server/headless_combat_host.py connects
  to the same relay, runs step_combat_frame, and sends combat_snap. Use when the
  HTTP lobby JSON has authoritative: "dedicated" (Multiplayer hub: F4 toggles this
  for the next “Create online lobby”). Pygame peers then behave as snapshot clients.

Architecture note (avoiding a “rewrite the whole game”)
-------------------------------------------------------
  demo_game.py is large because UI, input, and sim are still in one place. A future
  dedicated server does not have to throw that away: extract a headless “step sim”
  module (same rules as single-player) and keep pygame as a thin view/controller.
  The HTTP stub + relay are placeholders; authoritative multiplayer means the server
  runs that sim API and clients send commands / receive state — not re-implementing
  7k lines of ad hoc logic on the server.

Upload to droplet (example)
---------------------------
  From your PC (replace USER and IP):

    scp server/droplet_http_stub.py server/tcp_relay.py server/headless_combat_host.py USER@YOUR_DROPLET_IP:~/fleetrts-server/

  On the droplet:

    sudo apt update && sudo apt install -y python3
    cd ~/fleetrts-server
    python3 droplet_http_stub.py --host 0.0.0.0 --port 8765

  Run the relay in a second shell (or a second systemd unit):

    python3 tcp_relay.py --host 0.0.0.0 --port 8766

  Firewall (UFW example):

    sudo ufw allow 8765/tcp
    sudo ufw allow 8766/tcp
    sudo ufw enable   # if not already

  Production: put Caddy or nginx in front of the HTTP stub for TLS (Let’s Encrypt).
  The TCP relay is harder to TLS terminate; for now treat it as LAN/VPN-only or plan
  a WebSocket/TLS relay later.

start_fleetrts.sh / stop_fleetrts.sh (git clone on droplet)
------------------------------------------------------------
  One command starts stub + relay in the background; logs go to ~/fleetrts-logs/.

    cd ~/FleetRTS
    cp server/fleetrts.env.example server/fleetrts.env
    nano server/fleetrts.env    # set FLEETRTS_RELAY_HOST to this droplet's public IP

    chmod +x server/start_fleetrts.sh server/stop_fleetrts.sh
    ./server/start_fleetrts.sh

  Stop:

    ./server/stop_fleetrts.sh

  server/fleetrts.env is gitignored (local only). Optional short names — add to ~/.bashrc:

    alias start_server='$HOME/FleetRTS/server/start_fleetrts.sh'
    alias stop_server='$HOME/FleetRTS/server/stop_fleetrts.sh'

systemd (optional)
------------------
  Two units are provided:

    server/fleetrts-stub.service   — HTTP lobby API (port 8765)
    server/fleetrts-relay.service — TCP JSON relay (port 8766)

  Copy into /etc/systemd/system/, adjust User= and paths (e.g. /opt/fleetrts-server),
  then:

    sudo systemctl daemon-reload
    sudo systemctl enable --now fleetrts-stub fleetrts-relay

Environment (HTTP stub)
-----------------------
  FLEETRTS_LOBBY_STORE=/var/lib/fleetrts/lobbies.json
      Persist lobbies to disk (JSON). Parent dirs are created on write. Empty = in-memory only.

  FLEETRTS_API_KEY=your-long-random-secret
      If set, POST /api/v1/lobbies and POST .../join require header:
        X-FleetRTS-API-Key: your-long-random-secret
      or Authorization: Bearer your-long-random-secret

  FLEETRTS_POST_RATE_PER_MIN=120
      Rolling per-minute cap per client IP for all POST requests (0 = disable).

  FLEETRTS_RELAY_HOST / FLEETRTS_RELAY_PORT
      Host and port embedded in each lobby’s "relay" object (defaults 127.0.0.1:8766).
      On a VPS, set RELAY_HOST to the public hostname or IP clients use to reach the relay.

  Game clients: only if you set FLEETRTS_API_KEY on the stub, set the same value on
  each machine running the pygame client so create/join/quick-join include
  X-FleetRTS-API-Key (see core/net/http_client.py).

  FLEETRTS_LOBBY_TTL_SEC=3600
      If set and greater than zero: delete a lobby when nothing has touched it (no
      new create/join on that lobby) for this many seconds. "updated_at" is refreshed
      on create and each successful join. Omit or set to 0 for no time limit.

  FLEETRTS_LOBBY_MAX_PLAYERS=8
      If set and greater than zero: cap how many names may be in "players" (host +
      joiners). Join returns HTTP 403 lobby_full when full. Omit or 0 for unlimited.

Example create lobby with API key (curl):

  curl -s -X POST http://127.0.0.1:8765/api/v1/lobbies \
    -H "Content-Type: application/json" \
    -H "X-FleetRTS-API-Key: your-long-random-secret" \
    -d '{"name":"Friday","player":"Alice"}'

Reconnect / desync (current stub)
---------------------------------
  Lobbies include "updated_at" when created or joined; clients can compare with a
  cached copy to detect stale state. Full reconnect (re-join relay room, resync
  in-progress combat) is not implemented — that belongs with the authoritative sim.
  Until then, prefer “return to lobby and host starts a new match” after disconnect.

Two testers, no API key (informal droplet or LAN)
-------------------------------------------------
  Leave FLEETRTS_API_KEY unset on the stub unless you want mutating requests locked.

  On the machine running the stub (e.g. your droplet), set FLEETRTS_RELAY_HOST to the
  public hostname or IP that *other* players use to reach tcp_relay.py (not 127.0.0.1),
  and FLEETRTS_RELAY_PORT if not 8766. Each game client sets FLEETRTS_HTTP to the stub
  base URL, e.g. http://YOUR_DROPLET:8765

  Discovery: GET /api/v1/lobbies lists open lobbies; the pygame Multiplayer hub shows
  a browser and “Quick join (matchmaking)” (POST /api/v1/lobbies/quick-join).

Two-process coop combat test (player-host authoritative + hash)
----------------------------------------------------------------
  The pygame client can run a shared combat session over the HTTP stub + TCP relay:
  one peer is HOST (lobby creator), the other is CLIENT (joiner). The host steps the
  combat sim and broadcasts periodic JSON snapshots; the client applies snapshots and
  may send combat_cmd messages for fleet orders. Set FLEETRTS_HTTP to your stub base
  URL on both machines; ensure tcp_relay.py is running and FLEETRTS_RELAY_HOST /
  FLEETRTS_RELAY_PORT on the stub match what every client can reach.

  On one PC (or two terminals):

    1) Terminal A:  python server/droplet_http_stub.py
    2) Terminal B:  python server/tcp_relay.py
    3) Client 1:     set FLEETRTS_HTTP=http://127.0.0.1:8765
                     run the game, Multiplayer → Create online lobby (default: player host) → ready → Start battle.
    4) Client 2:     same env, Quick join / browser row / join code → ready → wait for start_match.

  Expect: status bar “MP HOST” or “MP CLIENT”; fleet motion follows the stepping host.

Dedicated authoritative sim (droplet headless process)
-------------------------------------------------------
  1) Create the HTTP lobby with authoritative dedicated: in the Multiplayer hub press
     F4 (or click the authority strip) until it shows “Dedicated”, then Create online lobby.
  2) On the droplet (or same LAN as the relay), after stub + relay are up:

       set SDL_VIDEODRIVER=dummy
       python server/headless_combat_host.py --lobby-id <uuid from HTTP JSON>

     Use the same relay as in the lobby (FLEETRTS_RELAY_HOST / FLEETRTS_RELAY_PORT).
  3) Human players join the lobby as usual; the first HTTP player still presses
     Start battle — that start_match is processed by the headless host and by every
     pygame peer. Pygame clients apply combat_snap only (status bar: “MP dedicated sim”).

  MVP limitation: the headless host boots the default starter fleet, not per-player
  fleet designs from the lobby.

  If snapshot apply/hash diverges, the client logs “[FleetRTS MP] DESYNC …” and shows
  a red banner for several seconds.

API (stub)
----------
  GET  /health
  GET  /api/v1/version
  GET  /api/v1/lobbies              — sanitized list for the in-game browser (no full relay object)
  POST /api/v1/lobbies/quick-join   body optional: {"name":"Alice"} — join first open lobby or create public_queue
  POST /api/v1/lobbies              body optional: {"name":"My game","player":"Alice",
                                                    "match_type":"custom"|"public_queue",
                                                    "authoritative":"player"|"dedicated"}
  POST /api/v1/lobbies/{id}/join    body optional: {"name":"Alice"}
                                    response includes joined_as if name was deduped (e.g. Player -> Player (2))
                                    403 if lobby_full (when max players set); 410 if lobby expired (TTL)
  GET  /api/v1/lobbies/{id}
  GET  /api/v1/lobbies/by-short/{8char}

Client install (developer machine)
----------------------------------
  From the repo root:

    pip install -e .

  Then run:

    fleetrts

  Or: python -m core.main

Dependencies
------------
  Stub servers: Python 3.9+ stdlib only.

  Game client: pygame (see pyproject.toml).

Next steps (when you implement real multiplayer)
----------------------------------------------
  - TLS termination (Caddy / nginx reverse proxy + Let’s Encrypt) for HTTP
  - Stronger auth (Steam, signed JWT) instead of a shared API key
  - Lobby caps, idle expiry, garbage-collect stale lobbies
  - Per-lobby fleet sync into headless_combat_host (today: default fleet only)
