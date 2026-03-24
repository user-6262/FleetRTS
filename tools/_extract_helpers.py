"""Extract inner functions from run() to module level, adding gs parameter.

Run once:  python tools/_extract_helpers.py
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "core" / "demo_game.py"

INNER_FUNC_START = 4250   # first `    def to_internal`
INNER_FUNC_END   = 4912   # last line of `exit_battlegroup_editor`  (inclusive)
RUN_DEF_LINE     = 4226   # `def run() -> None:`

# Variables/constants set inside run() before the inner functions that we must
# also hoist to module level.  (line number, dedented replacement text)
HOIST_VARS = {
    4811: "HUB_DEBUG_LOG = os.environ.get(\"FLEETRTS_DEBUG_LOG\", \"\").strip()",
    4812: "HUB_HTTP_DISABLED = os.environ.get(\"FLEETRTS_HUB_DISABLE_HTTP\", \"\").strip().lower() in (\"1\", \"true\", \"yes\")",
}

# Functions that do NOT use gs at all (pure / only use module-level names).
NO_GS_FUNCS = {
    "to_internal",      # uses win_w, win_h -> moved to RunContext
    "_bg_entry_idx_from_tag",
}


def extract_inner_functions(lines: list[str]) -> tuple[list[dict], set[int]]:
    """Return a list of {name, start, end, body_lines} and the set of consumed line indices."""
    funcs = []
    consumed: set[int] = set()
    i = INNER_FUNC_START - 1  # 0-based
    end = INNER_FUNC_END       # 1-based inclusive -> 0-based exclusive = end
    while i < end:
        raw = lines[i]
        if raw.startswith("    def "):
            fname_match = re.match(r"    def (\w+)\(", raw)
            if not fname_match:
                i += 1
                continue
            fname = fname_match.group(1)
            start = i
            # Collect until next same-indent def or end of block.
            j = i + 1
            while j < end:
                if lines[j].startswith("    def ") and not lines[j].startswith("        "):
                    break
                j += 1
            # Trim trailing blank lines from this function.
            while j > start + 1 and lines[j - 1].strip() == "":
                j -= 1
            body = lines[start:j]
            funcs.append({"name": fname, "start": start, "end": j, "body": body})
            for k in range(start, j):
                consumed.add(k)
            i = j
        else:
            i += 1
    return funcs, consumed


def transform_func(func: dict) -> list[str]:
    """Dedent 4 spaces and inject gs parameter."""
    name = func["name"]
    out = []
    for idx, raw in enumerate(func["body"]):
        # Dedent by 4.
        if raw.startswith("    "):
            line = raw[4:]
        else:
            line = raw

        # For the def line, inject gs as first param (unless in NO_GS_FUNCS).
        if idx == 0 and line.startswith("def "):
            if name == "to_internal":
                # Skip to_internal entirely; it moves to RunContext.
                return []
            if name not in NO_GS_FUNCS:
                # Insert gs before existing params.
                line = re.sub(r"def (\w+)\(", r"def \1(gs, ", line)
                # Fix empty-params case: def foo(gs, ) -> def foo(gs)
                line = line.replace("(gs, )", "(gs)")
        out.append(line)
    # Ensure trailing newline.
    if out and out[-1].strip() != "":
        out.append("")
    return out


# Map of inner function calls where we need to inject gs as first arg.
# These are calls made INSIDE other inner functions or inside the main loop.
CALL_INJECT = [
    "disconnect_mp_session",
    "sync_mp_player_name_from_field",
    "connect_relay",
    "send_host_config_if_online",
    "on_player_hull_hit",
    "enter_ship_loadouts",
    "finish_mp_ship_loadouts_to_lobby",
    "launch_mp_combat",
    "launch_mission_combat",
    "handle_mp_relay_events",
    "mp_sync_match_active",
    "mp_net_combat_active",
    "mp_local_runs_authoritative_sim",
    "mp_is_net_client",
    "mp_snapshot_broadcast_authority",
    "mp_receives_combat_snapshots",
    "_mp_apply_pending_snapshot",
    "mp_send_client",
    "mp_sel_player_group_labels",
    "mp_sel_capital_labels",
    "mp_sel_craft_labels",
    "_mp_owned_pick_owner",
    "_mp_pick_hostile_kwargs",
    "_mp_hub_can_use_http",
    "_bg_sync_from_selection",
    "_bg_sync_to_selection",
    "enter_battlegroup_editor",
    "exit_battlegroup_editor",
]


def inject_gs_calls(line: str) -> str:
    """For each known inner-function call, add gs as first argument."""
    for fname in CALL_INJECT:
        # Match fname( but not preceded by . (to avoid method calls like gs.mp.relay.xxx)
        pattern = re.compile(r"(?<![.\w])" + re.escape(fname) + r"\(")
        if pattern.search(line):
            # Replace fname( with fname(gs,  (or fname(gs) if currently fname())
            def _repl(m):
                pos = m.end()
                # Check if next non-space char is ) (empty args)
                rest = line[pos:]
                if rest.lstrip().startswith(")"):
                    return m.group(0).replace(fname + "(", fname + "(gs")
                return m.group(0).replace(fname + "(", fname + "(gs, ")
            line = pattern.sub(_repl, line)
    return line


def transform(text: str) -> str:
    lines = text.split("\n")

    # Extract inner functions.
    funcs, consumed = extract_inner_functions(lines)
    print(f"  Extracted {len(funcs)} inner functions")

    # Build module-level versions.
    mod_funcs: list[str] = [
        "",
        "# ---------------------------------------------------------------------------",
        "# Helpers (extracted from run() closures; gs passed explicitly)",
        "# ---------------------------------------------------------------------------",
        "",
    ]
    for f in funcs:
        transformed = transform_func(f)
        if transformed:
            mod_funcs.extend(transformed)
            mod_funcs.append("")

    # Insert module-level functions right before run().
    run_line_0 = RUN_DEF_LINE - 1  # 0-based

    # Build new file.
    out: list[str] = []

    # Everything before run().
    out.extend(lines[:run_line_0])

    # Hoisted variable declarations.
    for _ln, replacement in sorted(HOIST_VARS.items()):
        out.append(replacement)
    out.append("")

    # Module-level helper functions.
    out.extend(mod_funcs)

    # run() itself, but with inner functions removed and calls updated.
    for i in range(run_line_0, len(lines)):
        if i in consumed:
            continue
        # Also skip the old hoisted-variable lines.
        line_1based = i + 1
        if line_1based in HOIST_VARS:
            continue

        line = lines[i]
        # Rename _hub_http_disabled -> HUB_HTTP_DISABLED, _hub_debug_log -> HUB_DEBUG_LOG
        line = line.replace("_hub_http_disabled", "HUB_HTTP_DISABLED")
        line = line.replace("_hub_debug_log", "HUB_DEBUG_LOG")
        # Inject gs into function calls.
        line = inject_gs_calls(line)
        out.append(line)

    return "\n".join(out)


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    result = transform(text)
    SRC.write_text(result, encoding="utf-8")
    print(f"OK  ({len(text)} -> {len(result)} chars)")

    import py_compile
    try:
        py_compile.compile(str(SRC), doraise=True)
        print("  py_compile OK")
    except py_compile.PyCompileError as e:
        print(f"  py_compile FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
