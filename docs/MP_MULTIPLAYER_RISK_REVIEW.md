# FleetRTS multiplayer risk review

This document is the deliverable for the MP architecture audit (2025). It traces the command/snapshot pipeline, compares authority modes, maps spawn entry points, audits snapshot coverage, records snap-delivery policy, and ends with a **ranked risk register**.

---

## 1. Trace: `combat_cmd` → relay → host → `combat_snap`

### 1.1 Client send

- **Location:** [`core/demo_game.py`](core/demo_game.py) — `mp_send_client()`
- **Behavior:** Sends `combat_cmd(tick=0, seq=mp_client_cmd_seq, kind=..., payload=...)` via `mp_relay.send_payload()`.
- **Gate:** Only when `mp_net_combat_active()` and not `mp_local_runs_authoritative_sim()` (i.e. net client in combat with no local authoritative step).

**Finding:** The `tick` field is **always 0**. The host does not use it to align commands with `mp_combat_tick`. Ordering is entirely **relay delivery order** + **single FIFO queue** `mp_host_cmd_queue` drained once per host sim step.

### 1.2 Wire format

- **Location:** [`core/net/combat_net.py`](core/net/combat_net.py)
- Messages are JSON inside `RelayClient` lines (`{"t":"client_msg","body":{...}}`).

### 1.3 Relay

- **Location:** [`core/net/relay_client.py`](core/net/relay_client.py)
- Reader thread pushes parsed dicts into a `queue.Queue`; `poll()` drains in FIFO order. **Per connection, TCP preserves byte order**, so lines usually arrive in send order; reordering across rapid sends is still logically FIFO for one peer.

### 1.4 Host receive (player-hosted sim)

- **Location:** [`core/mp_session.py`](core/mp_session.py) — `poll_relay()` / `_dispatch_relay_message()` (called from [`core/demo_game.py`](core/demo_game.py) `handle_mp_relay_events()`).
- **Condition:** `COMBAT_CMD` is appended to `mp_host_cmd_queue` only if:
  - `mp_lobby_host` and authority is not `"dedicated"`
  - `mp_sync_match_active()`
  - `phase == "combat"` and `outcome is None`
- **`_sender`:** Set from relay message `from` field and passed into `apply_combat_command` for PvP ownership checks.

### 1.5 Host apply + step + snap

- **Location:** [`core/demo_game.py`](core/demo_game.py) — main loop
- Each frame (when authoritative): drain `mp_host_cmd_queue` → `apply_combat_command()` ([`core/combat_mp.py`](core/combat_mp.py)) → `step_combat_frame()` → every ~50ms `snapshot_state()` + `combat_snap`.

### 1.6 Dedicated headless path

- **Location:** [`server/headless_combat_host.py`](server/headless_combat_host.py)
- `_relay_dispatch` appends `COMBAT_CMD` to `cmd_queue` when `combat_holder[0] == "running"`.
- Inner loop: poll relay → apply all commands in `cmd_queue` → `step_combat_frame` → snapshot on timer (same pattern, fixed `dt`).

---

## 2. Snapshot field audit (`snapshot_state` / `apply_snapshot_state`)

### 2.1 `Group` ([`core/world_entities.py`](core/world_entities.py))

| Field | In snapshot? | Notes |
|-------|----------------|-------|
| side, owner_id, color_id, label, class_name | Yes | |
| x, y, z, max_hp, hp, speed, max_range, dead | Yes | |
| waypoint, move_pace_key | Yes | |
| strike_rally, strike_rally_wings | Yes | |
| attack_move, pd_overheat_streak, engagement_timer | Yes | |
| attack_target | Yes | Via ref resolver |
| render_capital, hangar_loadout_choice | Yes | |
| weapons | Yes | Cooldown restored; see below |
| **selected** | **No** | Client UI selection is local; orders carry explicit labels |

### 2.2 `Craft`

| Field | In snapshot? | Notes |
|-------|----------------|-------|
| Core kinematics / hp / weapons | Yes | |
| **selected** | **No** | Same as Group |

### 2.3 `Missile`

Serialized fields include position, velocity, target ref, anim, intercept_hp, etc. **Target refs** use `_attack_target_ref` including `{"k":"missile","i": index}` — **ordering-dependent** if missile list order ever diverges from host before serialize (should not on clients who only apply snaps).

### 2.4 `MissionState`

Mission block includes kind, mp_pvp, PvP dicts, objective, pods, reinf, obstacles, etc. — aligned with [`MissionState`](core/world_entities.py) dataclass for co-op/PvP paths audited.

### 2.5 Not in snapshot (client can diverge from host truth)

| Item | Risk |
|------|------|
| **`formation_mode` (HUD / move payload)** | Host updates shared `formation_mode_holder` on `formation_cycle` from **any** sender without per-player state. Net clients never receive formation from snapshot; their **local** `formation_mode` can disagree with the value host uses for moves that omit `formation_mode` in payload or when interpreting UI. **High UX / “wrong rules” risk.** |
| **Per-unit `selected`** | Selection highlights can disagree with what the host last applied until the player issues another command with explicit labels. Usually acceptable. |
| **Weapon `fire_rate` in `_apply_weapons`** | Only `cooldown` is reapplied from snapshot; if runtime mutates `fire_rate`, client could drift (low likelihood). |

### 2.6 Determinism in `apply_combat_command`

- **`sensor_ping`:** Uses `random.Random(seed % 100003)` with `rng_seed` from client payload (`nowp % 100003` on send). **Deterministic given shared `seed` and shared `now_ms` path** on host — but host uses **host** `now_ms` at apply time; if two clients ping different frames, behavior is still host-authoritative and consistent on host; clients see result via snap only. OK.

---

## 3. Authority modes: player host vs dedicated headless

| Aspect | Player host (`demo_game`) | Dedicated (`headless_combat_host`) |
|--------|---------------------------|-------------------------------------|
| Fleet bootstrap | `launch_mp_combat()` with `player_setup` from `start_match` | `bootstrap_mp_combat_match()` with same `player_setup` from relay `start_match` |
| Designs / roster | Full designs when `player_setup` present | **Same** when hub sends `player_setup` (docstring “default fleet” is the fallback when setup missing) |
| Sim clock | Pygame frame dt + 50ms snap throttle | Fixed `step_dt = 1/sim_hz`, up to 8 steps per outer loop |
| Relay role | Host sends snaps; clients receive | Headless sends snaps; all pygame clients receive |
| `demo_game` branches | `mp_snapshot_broadcast_authority`, `_client_snap`, `mp_lobby_authoritative` | “Host” in lobby may still be **client** for snaps when `authoritative == dedicated` |

**Finding:** Logic is intended to be parallel; **regressions often affect only one branch**. Any future fix should be tested in **both** modes.

---

## 4. Spawn path map (who builds `groups` / positions)

| # | Path | When | Player order / anchors |
|---|------|------|-------------------------|
| A | `launch_mp_combat(..., player_setup)` | Host clicks Start; client receives `start_match` | `normalize_mp_player_order` + `coop_player_spawn_anchor` / `pvp_player_spawn_anchor` ([`core/mp_spawn_layout.py`](core/mp_spawn_layout.py)) |
| B | `launch_mp_combat()` without `player_setup` | Offline / stub Start | Copies `mp_fleet_groups` / `mp_fleet_crafts` — **no** per-match PvP anchor pass |
| C | `bootstrap_mp_combat_match(..., player_setup)` | Headless after `start_match` | Same normalization + anchors as shared bootstrap ([`core/mp_combat_bootstrap.py`](core/mp_combat_bootstrap.py)) |
| D | Client during combat | N/A (no local build) | **Only** `apply_snapshot_state` — positions are entirely host-driven |
| E | `reset_mp_fleets_for_lobby` | After PvP debrief → SPACE to lobby | Re-stages by owner using same anchor helpers + relay roster when online |

**Finding:** “Everyone same place” usually means **path B** used without setup, **mismatched `player_setup`** between peers before snap, or **first frame** before first snap. After match start, **D** is source of truth for clients.

---

## 5. Snap delivery semantics and policy

### 5.1 Previous behavior

- `mp_pending_snap = dict(body)` **always overwrote** the pending snapshot. If multiple `combat_snap` messages were processed in one `poll()` batch, **last line wins** — usually newest. If relay/thread timing ever surfaced an **older** tick after a **newer** one in the same queue drain, the client could **apply a stale world**.

### 5.2 Host cadence

- ~**50 ms** between snaps ≈ 20 Hz, independent of display FPS. Clients are always at least one snap behind; large frame hitches can make that worse.

### 5.3 Policy (implemented)

**Buffer only the newest unapplied snap:**

- Ignore incoming snaps with `tick <= mp_client_last_snap_tick` (already applied).
- If keeping a pending snap, replace only when `t_new >= t_pending` (do not replace with an older tick).

**Code:** [`core/demo_game.py`](core/demo_game.py) — `handle_mp_relay_events()` branch for `COMBAT_SNAP`.

### 5.4 Recommended follow-ups (not all implemented)

- Put **host `mp_combat_tick`** on `combat_cmd` and drop/queue commands for stale ticks (optional hardening).
- Serialize **`formation_mode`** (or send per-player formation) to remove shared-formation ambiguity.

---

## 6. Ranked risk register

| Rank | Component | Failure mode | Symptoms you reported | Severity | Mitigation idea |
|------|-----------|--------------|------------------------|----------|----------------|
| 1 | **Shared `formation_mode` + no snap field** | Any player’s `formation_cycle` mutates host holder; clients keep local HUD mode | Late-match “no rules” / moves feel wrong | **High** | Serialize formation on snap **or** per-sender formation map **or** always embed formation in move payloads and ignore host holder for display |
| 2 | **Snapshot buffer overwrite** | Stale snap could replace newer pending | Rubber-band, teleport, incoherent state | **High** (was) | **Done:** newest-tick pending policy in relay handler |
| 3 | **`combat_cmd` tick=0** | No explicit sim-tick correlation | Burst inputs / latency → subtle intent mismatch | **Medium** | Send host tick from snap to client; tag commands; host ignores late commands |
| 4 | **Missile target by index** | List order mismatch breaks targeting | Rare hash OK but odd misses | **Medium** | Prefer stable missile IDs or label-based refs |
| 5 | **Dual authority code paths** | Fix in player-host only | Dedicated PvP diverges | **Medium** | Test matrix: both modes for each MP change |
| 6 | **Spawn path B vs A** | Start without `player_setup` | All fleets same anchor | **Medium** | Ensure online always sends and applies `start_match.player_setup` |
| 7 | **Monolithic `demo_game.py`** | Regressions in unrelated systems | General instability | **Medium** | Extract `mp_sync.py` / relay handlers |
| 8 | **Selection not in snap** | Local `selected` flags stale | Wrong highlight, not wrong sim if labels OK | **Low** | Optional: sync selection subset for polish |
| 9 | **50ms snap vs FPS** | Visual interpolation mismatch | “Smooth then messy” feel | **Low** | Client interp or higher snap rate (bandwidth cost) |

---

## 7. Todo completion checklist

| Plan todo | Evidence in this doc |
|-----------|----------------------|
| trace-cmd-snap-path | Section 1 |
| audit-snapshot-fields | Section 2 |
| compare-authority-modes | Section 3 |
| map-spawn-paths | Section 4 |
| snap-delivery-semantics | Section 5 + code change in `demo_game.py` |
| risk-register | Section 6 |
