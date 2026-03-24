# Multiplayer invariants (SP vs MP)

Short reference for who runs what in online play. For the full pipeline and risk register, see [MP_MULTIPLAYER_RISK_REVIEW.md](MP_MULTIPLAYER_RISK_REVIEW.md).

## Phases (game loop)

- **Single-player campaign:** `post_combat_phase` is not `"mp_lobby"`. Combat is started from loadout / mission flow; debrief advances rounds with local `begin_combat_round`. No relay snapshots apply to world state.
- **Multiplayer lobby + match:** `post_combat_phase == "mp_lobby"` while an HTTP lobby id is active and the TCP relay is connected. Combat and debrief are still part of the same "online match" for sync purposes until the player leaves that flow.

## Authority

- **Player host (default):** The lobby host runs `step_combat_frame` / `combat_engine` locally, drains `mp_host_cmd_queue`, and broadcasts `combat_snap` on a timer. In the new engine this happens inside [`core/scene_combat.py`](../core/scene_combat.py).
- **Net client:** Does not step authoritative combat. It receives `COMBAT_SNAP` via the relay, which is applied through [`core/combat_snapshot.py`](../core/combat_snapshot.py) and updates run scalars (phase, outcome, salvage, store selection, desync flags).
- **Dedicated authority:** When `mp_lobby_authoritative == "dedicated"`, the player host does not run the sim; clients still use the same snapshot receive path. Command routing follows the existing `combat_mp` / relay rules.

## Relay orchestration

- TCP relay connection is managed by [`core/scene_mp_lobby.py`](../core/scene_mp_lobby.py), which auto-connects a `RelayClient` from [`core/net/relay_client.py`](../core/net/relay_client.py) when entering the lobby. Lobby browser and HTTP operations are in [`core/scene_mp_hub.py`](../core/scene_mp_hub.py).

## Simulation ownership

- **Only** [`core/combat_sim.py`](../core/combat_sim.py) / [`core/combat_engine.py`](../core/combat_engine.py) (via the host's per-frame step) advance physics and combat for authoritative games. Clients applying snapshots reconstruct state from serialized fields; they do not run an independent sim in parallel with the host.
