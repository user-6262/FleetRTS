"""
Render announcer lines to WAV under assets/sound/voice/.

Run from repo root:
  python tools/generate_announcer_voice.py

Windows: uses System.Speech (no playback device needed). Other platforms: pyttsx3.
Re-run after changing CLIP_TEXT.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_OUT = _REPO / "assets" / "sound" / "voice"

# stem -> exact phrase spoken (must match line_id passed to GameAudio.speak_voice)
CLIP_TEXT: dict[str, str] = {
    "capital_lost": "Capital ship lost.",
    "enemy_destroyed": "Enemy ship destroyed.",
    "voice_link_test": "Voice link test.",
    "moving": "Moving.",
    "orders_received_moving": "Orders received. Moving.",
    "orders_received_striking": "Orders received. Striking.",
    "focus_fire": "Focus fire.",
    "bombers_acknowledge": "Bombers acknowledge.",
    "fighters_acknowledge": "Fighters acknowledge.",
    "orders_query": "Orders?",
    "hull_integrity_low": "Commander, hull integrity critical. Awaiting orders.",
}

_PS_RENDER = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 1
$p = [string]$env:_ANNOUNCE_OUT
$t = [string]$env:_ANNOUNCE_TEXT
$s.SetOutputToWaveFile($p)
$s.Speak($t)
$s.Dispose()
"""


def _render_one_windows_speech(path: Path, text: str) -> None:
    env = os.environ.copy()
    env["_ANNOUNCE_OUT"] = str(path.resolve())
    env["_ANNOUNCE_TEXT"] = text
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _PS_RENDER,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        raise RuntimeError(err)


def _make_pyttsx3_engine():
    import pyttsx3

    engine = None
    for factory in (lambda: pyttsx3.init("sapi5"), lambda: pyttsx3.init()):
        try:
            engine = factory()
            break
        except Exception:
            engine = None
    if engine is None:
        return None
    try:
        engine.setProperty("rate", 175)
        v = engine.getProperty("volume")
        if v is not None:
            engine.setProperty("volume", min(1.0, float(v)))
    except Exception:
        pass
    return engine


def _render_one_pyttsx3(path: Path, text: str) -> None:
    engine = _make_pyttsx3_engine()
    if engine is None:
        raise RuntimeError("pyttsx3.init failed")
    try:
        try:
            engine.save_to_file(text, str(path))
            engine.runAndWait()
        finally:
            try:
                engine.stop()
            except Exception:
                pass
    except Exception:
        raise


def _main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    use_ps = sys.platform == "win32"

    for stem, text in CLIP_TEXT.items():
        path = _OUT / f"{stem}.wav"
        try:
            if use_ps:
                _render_one_windows_speech(path, text)
            else:
                _render_one_pyttsx3(path, text)
            print(path)
        except Exception as e:
            print(f"{path}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
