"""Thread-safe playback, independent of the window and music catalogue."""
from pathlib import Path
import hashlib
import tempfile
import threading
import time

import pygame


class Player:
    IDLE, LOADING, PLAYING, PAUSED = "idle", "loading", "playing", "paused"

    def __init__(self, emit, ensure_audio, fetch_audio, cache_dir):
        self.emit, self.ensure_audio, self.fetch_audio = emit, ensure_audio, fetch_audio
        self.cache_dir = Path(cache_dir)
        self.state, self.current = self.IDLE, None
        self.duration, self.elapsed, self.volume = 0, 0.0, 0.8
        self._gen, self._file = 0, None
        self._lock = threading.RLock()
        self.started_at = time.monotonic()

    @property
    def busy(self):
        with self._lock:
            return bool(pygame.mixer.music.get_busy())

    def _stop(self):
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except pygame.error:
            pass

    def play(self, track):
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._stop()
            self.state, self.current = self.LOADING, track
            self.duration, self.elapsed, self._file = track.duration, 0.0, None
            self.emit("loading", track=track)
        threading.Thread(target=self._worker, args=(track, gen), daemon=True).start()

    def _worker(self, track, gen):
        cancelled = lambda: gen != self._gen
        last_pct = -1

        def progress(done, total):
            nonlocal last_pct
            pct = min(100, int(done * 100 / max(total, 1)))
            if not cancelled() and pct // 5 != last_pct // 5:
                last_pct = pct
                self.emit("progress", track=track, pct=pct, gen=gen)

        try:
            with self._lock:
                if cancelled():
                    return
                if not self.ensure_audio():
                    raise RuntimeError("Нет аудиоустройства")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            dest = self.cache_dir / (hashlib.sha256(track.id.encode()).hexdigest() + ".mp3")
            for attempt in range(2):
                if not dest.exists() or dest.stat().st_size == 0:
                    # Each request owns its partial files, including repeated clicks on one song.
                    with tempfile.TemporaryDirectory(dir=self.cache_dir) as folder:
                        downloaded = Path(folder) / "audio.mp3"
                        self.fetch_audio(track, downloaded, progress, cancelled)
                        with self._lock:
                            if cancelled():
                                return
                            downloaded.replace(dest)
                with self._lock:
                    if cancelled():
                        return
                    try:
                        pygame.mixer.music.load(str(dest))
                    except pygame.error:
                        dest.unlink(missing_ok=True)
                        if attempt == 0:
                            continue
                        raise
                    self._file = dest
                    self.duration = track.duration
                    pygame.mixer.music.set_volume(self.volume)
                    pygame.mixer.music.play()
                    self.state, self.elapsed = self.PLAYING, 0.0
                    self.started_at = time.monotonic()
                    self.emit("playing", track=track)
                    return
        except Exception as error:
            with self._lock:
                if not cancelled():
                    self.state = self.IDLE
                    self.emit("error", track=track, msg=str(error) or type(error).__name__)

    def tick(self):
        with self._lock:
            now = time.monotonic()
            if self.state == self.PLAYING:
                self.elapsed += max(0, now - self.started_at)
                if self.duration:
                    self.elapsed = min(self.elapsed, self.duration)
            self.started_at = now
            return self.elapsed

    def toggle(self):
        with self._lock:
            if self.state == self.PLAYING:
                self.tick()
                pygame.mixer.music.pause()
                self.state = self.PAUSED
                self.emit("paused", track=self.current)
            elif self.state == self.PAUSED:
                pygame.mixer.music.unpause()
                self.state, self.started_at = self.PLAYING, time.monotonic()
                self.emit("resumed", track=self.current)

    def seek(self, sec):
        with self._lock:
            if self.state not in (self.PLAYING, self.PAUSED) or not self._file:
                return
            sec = max(0.0, min(float(sec), max(0.0, self.duration - 0.5))) if self.duration else 0.0
            try:
                pygame.mixer.music.play(start=sec)
                if self.state == self.PAUSED:
                    pygame.mixer.music.pause()
                self.elapsed, self.started_at = sec, time.monotonic()
                self.emit("seeked", track=self.current)
            except pygame.error as error:
                self.emit("error", track=self.current, msg="Ошибка перемотки: " + str(error))

    def replay(self):
        with self._lock:
            if self.current and self.state == self.IDLE:
                self.play(self.current)
                return
            self.seek(0)
            if self.state == self.PAUSED:
                self.toggle()

    def stop(self):
        with self._lock:
            self._gen += 1
            self._stop()
            self.state, self.current, self._file = self.IDLE, None, None
            self.elapsed, self.duration = 0.0, 0
            self.emit("stopped", track=None)

    def set_volume(self, volume):
        with self._lock:
            self.volume = max(0.0, min(1.0, float(volume)))
            try:
                pygame.mixer.music.set_volume(self.volume)
            except pygame.error:
                pass
