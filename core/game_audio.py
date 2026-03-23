"""
Loads MP3s from assets/sound and plays combat feedback.
Low-HP alarm: short bursts (capped at LOW_HP_ALARM_MAX_MS) so long files stay tolerable — trim the asset to ~2s for best results.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import List, Optional

import pygame

try:
    from bundle_paths import assets_sound_dir
except ImportError:
    from core.bundle_paths import assets_sound_dir

from runtime_tts import RuntimeTTS

ASSETS_SOUND = assets_sound_dir()

LOW_HP_FRACTION = 0.28
LOW_HP_ALARM_MAX_MS = 2000
LOW_HP_REPEAT_GAP_MS = 350


class GameAudio:
    def __init__(self) -> None:
        self.ok = False
        # Multiplier 0..1 applied to SFX channels (set in apply_master_volume).
        self.master_volume: float = 1.0
        self.tts_voice_enabled: bool = True
        self._tts: Optional[RuntimeTTS] = None
        self.warning_low_hp: Optional[pygame.mixer.Sound] = None
        self.ship_destroyed: List[pygame.mixer.Sound] = []
        self.positive_tone: Optional[pygame.mixer.Sound] = None
        self.negative_tone: Optional[pygame.mixer.Sound] = None
        self._fx_ch = pygame.mixer.Channel(0)
        self._warn_ch = pygame.mixer.Channel(1)
        self._ui_ch = pygame.mixer.Channel(2)
        self._last_warn_burst_end: int = -999999
        self._warn_burst_start: int = 0

    def init(self) -> None:
        self._tts = RuntimeTTS()
        self._tts.start()
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        except pygame.error:
            self.ok = False
            return

        self.ok = True
        self.apply_master_volume()
        warn_path = ASSETS_SOUND / "warning_low_health.mp3"
        if warn_path.is_file():
            try:
                self.warning_low_hp = pygame.mixer.Sound(str(warn_path))
                self.warning_low_hp.set_volume(0.42)
            except Exception:
                self.warning_low_hp = None

        for i in range(1, 4):
            p = ASSETS_SOUND / f"shipdestroyed{i}.mp3"
            if not p.is_file():
                continue
            try:
                s = pygame.mixer.Sound(str(p))
                s.set_volume(0.55)
                self.ship_destroyed.append(s)
            except Exception:
                pass

        for fname, attr, vol in (
            ("positivetone.mp3", "positive_tone", 0.5),
            ("negativetone.mp3", "negative_tone", 0.45),
        ):
            p = ASSETS_SOUND / fname
            if not p.is_file():
                continue
            try:
                s = pygame.mixer.Sound(str(p))
                s.set_volume(vol)
                setattr(self, attr, s)
            except Exception:
                pass

    def apply_master_volume(self) -> None:
        """Apply master_volume to reserved mixer channels (call after init or when the slider changes)."""
        if not self.ok:
            return
        v = max(0.0, min(1.0, float(self.master_volume)))
        try:
            self._fx_ch.set_volume(v)
            self._warn_ch.set_volume(v)
            self._ui_ch.set_volume(v)
        except Exception:
            pass

    def shutdown(self) -> None:
        if self._tts is not None:
            self._tts.shutdown()
            self._tts = None
        if self.ok:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            self.ok = False

    def speak_voice(self, text: str) -> None:
        if not self.tts_voice_enabled:
            return
        if self._tts is not None:
            self._tts.speak(text)

    def play_ship_destroyed(self) -> None:
        if not self.ok or not self.ship_destroyed:
            return
        snd = random.choice(self.ship_destroyed)
        if not self._fx_ch.get_busy():
            self._fx_ch.play(snd)

    def play_positive(self) -> None:
        if not self.ok or not self.positive_tone:
            return
        self._ui_ch.play(self.positive_tone)

    def play_negative(self) -> None:
        if not self.ok or not self.negative_tone:
            return
        self._ui_ch.play(self.negative_tone)

    def tick_low_hp_alarm(self, any_player_low_hp: bool) -> None:
        """Call each frame during combat. Bursts alarm when fleet is hurt; brightness/volume falloff via short play cap."""
        if not self.ok or not self.warning_low_hp:
            return
        now = pygame.time.get_ticks()

        if not any_player_low_hp:
            self._warn_ch.stop()
            return

        if self._warn_ch.get_busy():
            if now - self._warn_burst_start >= LOW_HP_ALARM_MAX_MS:
                self._warn_ch.stop()
                self._last_warn_burst_end = now
            return

        if now - self._last_warn_burst_end >= LOW_HP_REPEAT_GAP_MS:
            self._warn_ch.play(self.warning_low_hp)
            self._warn_burst_start = now


def player_fleet_low_hp(groups, crafts) -> bool:
    for g in groups:
        if g.side == "player" and not g.dead and g.max_hp > 0 and g.hp < g.max_hp * LOW_HP_FRACTION:
            return True
    for c in crafts:
        if c.side == "player" and not c.dead and c.max_hp > 0 and c.hp < c.max_hp * LOW_HP_FRACTION:
            return True
    return False
