"""
Runtime text-to-speech via pyttsx3 on a dedicated worker thread (non-blocking for pygame).

pyttsx3 should be used from a single thread; the queue serializes speak requests.
On Windows, SAPI/COM must be initialized on the worker thread (CoInitialize).

Windows + pygame: reusing one engine after runAndWait() often deadlocks or silences further
speech (pyttsx3 regression). We create a fresh engine per phrase on Windows.

We do not pause pygame.mixer during TTS — that would mute all SFX; TTS shares the output
device with pygame but should mix with game audio on typical setups.
"""
from __future__ import annotations

import queue
import sys
import threading
from typing import Optional


def _create_engine():
    import pyttsx3

    last_err: Optional[Exception] = None
    engine = None
    for factory in (
        lambda: pyttsx3.init("sapi5"),
        lambda: pyttsx3.init(),
    ):
        try:
            engine = factory()
            break
        except Exception as e:
            last_err = e
            engine = None
    if engine is None:
        raise last_err or RuntimeError("pyttsx3.init returned no engine")
    try:
        engine.setProperty("rate", 175)
        v = engine.getProperty("volume")
        if v is not None:
            engine.setProperty("volume", min(1.0, float(v)))
    except Exception:
        pass
    return engine


def _speak_one_fresh_engine(text: str) -> None:
    """One phrase, one engine — reliable on Windows with pygame."""
    engine = None
    try:
        engine = _create_engine()
        engine.say(text)
        engine.runAndWait()
    finally:
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass


class RuntimeTTS:
    def __init__(self) -> None:
        self._q: queue.Queue[Optional[str]] = queue.Queue(maxsize=20)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="pyttsx3-worker", daemon=True)
        self._started = False
        self._enabled = False
        self._engine_ready = threading.Event()
        self.last_init_error: Optional[str] = None

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def _drain_until_shutdown(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                return

    def _worker(self) -> None:
        coinit = False
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.ole32.CoInitialize(None)
                coinit = True
            except Exception:
                pass

        engine = None
        try:
            try:
                import pyttsx3  # noqa: F401
            except Exception as e:
                self.last_init_error = str(e)
                hint = ""
                if isinstance(e, ModuleNotFoundError) or "No module named" in str(e):
                    hint = f" (interpreter: {sys.executable})"
                print(f"[FleetRTS TTS] Disabled: {e}{hint}", file=sys.stderr)
                self._enabled = False
                self._engine_ready.set()
                self._drain_until_shutdown()
                return

            if sys.platform == "win32":
                try:
                    e = _create_engine()
                    try:
                        e.stop()
                    except Exception:
                        pass
                    del e
                except Exception as e:
                    self.last_init_error = str(e)
                    hint = ""
                    if isinstance(e, ModuleNotFoundError) or "No module named" in str(e):
                        hint = f" (interpreter: {sys.executable})"
                    print(f"[FleetRTS TTS] Disabled: {e}{hint}", file=sys.stderr)
                    self._enabled = False
                    self._engine_ready.set()
                    self._drain_until_shutdown()
                    return

                self._enabled = True
                self._engine_ready.set()
                while not self._stop.is_set():
                    try:
                        text = self._q.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if text is None:
                        break
                    try:
                        _speak_one_fresh_engine(text)
                    except Exception as ex:
                        print(f"[FleetRTS TTS] speak error: {ex}", file=sys.stderr)
                return

            try:
                engine = _create_engine()
            except Exception as e:
                self.last_init_error = str(e)
                hint = ""
                if isinstance(e, ModuleNotFoundError) or "No module named" in str(e):
                    hint = f" (interpreter: {sys.executable})"
                print(f"[FleetRTS TTS] Disabled: {e}{hint}", file=sys.stderr)
                self._enabled = False
                self._engine_ready.set()
                self._drain_until_shutdown()
                return

            self._enabled = True
            self._engine_ready.set()

            while not self._stop.is_set():
                try:
                    text = self._q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if text is None:
                    break
                try:
                    engine.say(text)
                    engine.runAndWait()
                except Exception as ex:
                    print(f"[FleetRTS TTS] speak error: {ex}", file=sys.stderr)
                try:
                    engine.stop()
                except Exception:
                    pass
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception:
                    pass
            if coinit:
                try:
                    import ctypes

                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass

    def speak(self, text: str) -> None:
        if not self._started or not text.strip():
            return
        if self._stop.is_set():
            return
        try:
            self._q.put_nowait(text.strip())
        except queue.Full:
            pass

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except Exception:
            pass
        self._thread.join(timeout=3.0)

    @property
    def active(self) -> bool:
        return self._enabled
