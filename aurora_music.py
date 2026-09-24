# -*- coding: utf-8 -*-
"""
Aurora — музыкальный плеер.

Интерфейс: HTML/CSS/JS в окне pywebview (Edge WebView2).
Источники музыки: YouTube и Audius.

При закрытии главного окна музыка продолжает играть, а компактный плеер
остаётся на рабочем столе для управления воспроизведением.

Запуск:
  pip install -r requirements.txt
  python aurora_music.py
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import requests
import pygame
from PIL import Image, ImageDraw

try:
    import webview  # pywebview
except Exception:
    webview = None

try:
    import pystray
except Exception:
    pystray = None

APP_NAME = "AURORA_PLAYER"
UA = {"User-Agent": "AuroraMusicPlayer/1.0"}

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UI_DIR = BASE / "ui"
DATA_FILE = (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
             / "AuroraMusic" / "aurora_data.json") if getattr(sys, "frozen", False) else BASE / "aurora_data.json"
CACHE_DIR = Path(tempfile.gettempdir()) / "aurora_music"

GENRES = ["Все", "Electronic", "Hip-Hop/Rap", "House", "Pop", "Techno", "Lo-Fi", "Rock"]


# ─────────────────────────── утилиты ───────────────────────────
def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def mmss(sec) -> str:
    try:
        sec = int(sec or 0)
    except (TypeError, ValueError):
        sec = 0
    return f"{sec // 60}:{sec % 60:02d}"


def make_tray_icon() -> "Image.Image":
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, s - 3, s - 3), 16, fill=(24, 24, 24, 255))
    for x, top in ((18, 25), (29, 15), (40, 21)):
        d.rounded_rectangle((x, top, x + 5, 48), 2, fill="white")
    return img


# ─────────────────────────── трек ───────────────────────────
@dataclass
class Track:
    id: str
    kind: str          # "youtube" | "audius" (| "deezer" — только legacy избранного)
    ref: str           # id видео YouTube / id трека Audius
    title: str
    artist: str
    duration: int
    art_small: str = ""
    art_big: str = ""
    source: str = ""
    play_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Track | None":
        try:
            if not isinstance(d, dict):
                return None
            track = Track(**d)
            if not all(isinstance(v, str) and v for v in (track.id, track.ref, track.title, track.artist)):
                return None
            if track.kind not in ("youtube", "audius", "deezer"):
                return None
            track.duration = max(0, int(track.duration or 0))
            return track
        except (TypeError, ValueError, OverflowError):
            return None


def _norm_audius(t: dict) -> "Track | None":
    try:
        if t.get("is_delete"):
            return None
        if t.get("stream_conditions"):
            return None  # платный/закрытый трек — не сможем стримить
        art = t.get("artwork") or {}
        small = art.get("150x150") or art.get("480x480") or art.get("1000x1000") or ""
        big = art.get("480x480") or art.get("150x150") or art.get("1000x1000") or ""
        user = t.get("user") or {}
        return Track(
            id="audius:" + str(t.get("id")),
            kind="audius",
            ref=str(t.get("id")),
            title=(t.get("title") or "Без названия").strip(),
            artist=(user.get("name") or "Неизвестный артист").strip(),
            duration=int(t.get("duration") or 0),
            art_small=small, art_big=big,
            source="Audius",
            play_count=int(t.get("play_count") or 0),
        )
    except Exception:
        return None


# ─────────────────────────── Audius API ───────────────────────────
class AudiusClient:
    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.host: str | None = None
        self._lock = threading.Lock()

    def ensure(self) -> None:
        with self._lock:
            if self.host:
                return
        r = requests.get("https://api.audius.co", timeout=8, headers=UA)
        r.raise_for_status()
        hosts = list(r.json().get("data") or [])
        if not hosts:
            hosts = ["https://discoveryprovider.audius.co"]
        with self._lock:
            self.hosts = hosts
            self.host = hosts[0]

    def _rotate(self) -> None:
        with self._lock:
            if self.hosts and self.host in self.hosts:
                i = self.hosts.index(self.host)
                self.host = self.hosts[(i + 1) % len(self.hosts)]

    def _get(self, path: str, params: dict | None = None, tries: int = 3) -> dict:
        last: Exception | None = None
        for _ in range(tries):
            self.ensure()
            p = dict(params or {})
            p["app_name"] = APP_NAME
            try:
                r = requests.get(self.host + path, params=p, timeout=(6, 25), headers=UA)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
                self._rotate()
        raise RuntimeError(f"Audius недоступен: {last}")

    def trending(self, genre: str = "Все", limit: int = 50) -> list[Track]:
        params: dict = {"limit": limit, "time": "week"}
        if genre and genre != "Все":
            params["genre"] = genre
        data = self._get("/v1/tracks/trending", params).get("data") or []
        return [n for n in (_norm_audius(t) for t in data) if n]

    def search(self, query: str, limit: int = 50) -> list[Track]:
        data = self._get("/v1/tracks/search", {"query": query, "limit": limit}).get("data") or []
        return [n for n in (_norm_audius(t) for t in data) if n]


# ─────────────────────────── YouTube (полные песни) ───────────────────────────
ytdlp_mod = None
ffmpeg_path = ""


def ensure_ytdlp() -> bool:
    global ytdlp_mod, ffmpeg_path
    if ytdlp_mod is not None:
        return ytdlp_mod is not False
    try:
        import yt_dlp as m
        import imageio_ffmpeg
        ytdlp_mod = m
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        return True
    except Exception:
        ytdlp_mod = False
        return False


def youtube_search(query: str, limit: int = 25) -> list[Track]:
    """Быстрый поиск по YouTube (без скачивания): только метаданные."""
    if not ensure_ytdlp():
        return []
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "extract_flat": "in_playlist", "skip_download": True,
        "socket_timeout": 15, "retries": 2,
    }
    with ytdlp_mod.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("ytsearch%d:%s" % (limit, query), download=False)
    out: list[Track] = []
    for e in (info or {}).get("entries") or []:
        try:
            vid = (e or {}).get("id")
            if not vid:
                continue
            out.append(Track(
                id="yt:" + vid,
                kind="youtube",
                ref=vid,
                title=(e.get("title") or "Без названия").strip(),
                artist=(e.get("uploader") or e.get("channel") or "YouTube").strip(),
                duration=int(e.get("duration") or 0),
                art_small="https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid,
                art_big="https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid,
                source="YouTube",
            ))
        except Exception:
            continue
    return out


def youtube_fetch_audio(track: Track, dest: Path, progress=None, cancelled=None) -> Path:
    """Скачивает полную аудиодорожку и конвертирует в mp3."""
    if not ensure_ytdlp():
        raise RuntimeError("Не установлен yt-dlp: pip install yt-dlp imageio-ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest.parent / (track.ref + ".%(ext)s"))

    def hook(d):
        if cancelled and cancelled():
            exc = getattr(ytdlp_mod.utils, "DownloadCancelled", RuntimeError)
            raise exc("cancelled")
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress(done, total)

    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": outtmpl,
        "ffmpeg_location": ffmpeg_path or "",
        "progress_hooks": [hook],
        "socket_timeout": 15,
        "retries": 3,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
    }
    with ytdlp_mod.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("https://www.youtube.com/watch?v=" + track.ref, download=True)
    if not dest.exists():
        for cand in dest.parent.glob(track.ref + ".*"):
            if cand.suffix.lower() == ".mp3":
                cand.replace(dest)
                break
    if not dest.exists():
        raise RuntimeError("YouTube: не удалось получить аудио")
    try:
        dur = int((info or {}).get("duration") or 0)
        if dur:
            track.duration = dur
    except Exception:
        pass
    return dest


# ─────────────────────────── загрузка аудио ───────────────────────────
class Cancelled(Exception):
    pass


def audio_urls(track: Track, client: AudiusClient) -> list[str]:
    if track.kind == "deezer":  # legacy: избранное из старых версий
        return [track.ref]
    hosts = list(client.hosts) or ["https://discoveryprovider.audius.co"]
    return [h.rstrip("/") + f"/v1/tracks/{track.ref}/stream?app_name={APP_NAME}" for h in hosts]


def download_audio(track: Track, dest: Path, progress=None, cancelled=None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    last_err: Exception | None = None
    for url in audio_urls(track, audius):
        try:
            done = 0
            total = 0
            with requests.get(url, stream=True, timeout=(6, 30), headers=UA, allow_redirects=True) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                with open(part, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if cancelled and cancelled():
                            raise Cancelled()
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if progress and total:
                                progress(done, total)
            part.replace(dest)
            return dest
        except Cancelled:
            raise
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Не удалось скачать аудио: {last_err}")


def fetch_audio(track: Track, dest: Path, progress=None, cancelled=None) -> Path:
    """Единая точка скачивания: YouTube — полный трек, Audius — стрим."""
    if track.kind == "youtube":
        return youtube_fetch_audio(track, dest, progress, cancelled)
    return download_audio(track, dest, progress, cancelled)


audius = AudiusClient()


def search_tracks(query: str, client: AudiusClient) -> list[Track]:
    """Ищем параллельно: YouTube (полные песни) + Audius (открытая сцена)."""
    res: dict = {}

    def yt():
        try:
            if not ensure_ytdlp():
                raise RuntimeError("YouTube недоступен")
            res["yt"] = youtube_search(query, 25)
        except Exception:
            res["yt"] = []
            res["yt_error"] = True

    def au():
        try:
            res["au"] = client.search(query, 20)
        except Exception:
            res["au"] = []
            res["au_error"] = True

    th1 = threading.Thread(target=yt, daemon=True)
    th2 = threading.Thread(target=au, daemon=True)
    th1.start()
    th2.start()
    deadline = time.monotonic() + 30
    th1.join(max(0, deadline - time.monotonic()))
    th2.join(max(0, deadline - time.monotonic()))
    if (res.get("yt_error") or "yt" not in res) and (res.get("au_error") or "au" not in res):
        raise RuntimeError("Не удалось загрузить музыку. Проверьте соединение и повторите поиск.")

    out: list[Track] = list(res.get("yt") or [])
    seen = {(t.title.lower(), t.artist.lower()) for t in out}
    for t in res.get("au") or []:
        key = (t.title.lower(), t.artist.lower())
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


from playback import Player


# ─────────────────────────── приложение ───────────────────────────
class AuroraApp:
    def __init__(self, smoke: bool = False) -> None:
        self.smoke = smoke
        self.tracks: dict[str, Track] = {}
        self.queue_ids: list[str] = []
        self.q_index = -1
        self.shuffle = False
        self.repeat = "off"
        self.pool = ThreadPoolExecutor(max_workers=10)

        self._data_lock = threading.RLock()
        self._load_data()
        self.audio_ok = self._init_audio()
        self.player = Player(self._on_player_event, self._ensure_audio, fetch_audio, CACHE_DIR / "audio")
        self.player.volume = self.vol

        self._home_cache: dict = {}
        self._home_gen = 0
        self._home_genre = "Все"
        self._search_gen = 0
        self._search_query = ""
        self.ui = {"page": "home", "genre": "Все", "query": ""}

        self._main_win = None
        self._tail_win = None
        self._quit = False
        self._tray = None
        self._busy_off = 0.0
        self._consec_err = 0

    # ── данные ──
    def _load_data(self) -> None:
        try:
            raw = json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        try:
            self.vol = max(0.0, min(1.0, float(raw.get("volume", 0.8))))
        except (TypeError, ValueError):
            self.vol = 0.8
        self.liked: dict = {}
        self.shuffle = raw.get("shuffle") is True
        self.repeat = raw.get("repeat") if raw.get("repeat") in ("off", "all", "one") else "off"
        saved = raw.get("liked")
        for k, v in (saved if isinstance(saved, dict) else {}).items():
            t = Track.from_dict(v)
            if t:
                self.liked[t.id] = t.to_dict()
                if t.id not in self.tracks:
                    self.tracks[t.id] = t

        self.history = []
        for value in (raw.get("history") if isinstance(raw.get("history"), list) else [])[:100]:
            track = Track.from_dict(value)
            if track:
                self.history.append(track.id)
                self.tracks[track.id] = track

    def _save_data(self) -> None:
        with self._data_lock:
            try:
                data = {"volume": self.vol, "liked": self.liked,
                        "shuffle": self.shuffle, "repeat": self.repeat,
                        "history": [self.tracks[i].to_dict() for i in self.history if i in self.tracks]}
                DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
                temp = DATA_FILE.with_suffix(".tmp")
                temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
                temp.replace(DATA_FILE)
            except OSError:
                self._push_main("toast", {"text": "Не удалось сохранить настройки на диск"})

    # ── аудио ──
    def _init_audio(self) -> bool:
        try:
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.init()
            pygame.mixer.init()
            return True
        except Exception:
            return False

    def _ensure_audio(self) -> bool:
        if self.audio_ok:
            return True
        try:
            pygame.mixer.quit()
            pygame.mixer.init(44100, -16, 2, 512)
            self.audio_ok = True
        except Exception:
            self.audio_ok = False
        return self.audio_ok

    # ── отправка событий в интерфейс ──
    def _push(self, win, event: str, data: dict) -> None:
        if win is None or self._quit:
            return
        try:
            native = win.native
            if not native.Visible or str(native.WindowState) == "Minimized":
                return
            win.evaluate_js(
                "window.__emit(%s, %s); true" % (json.dumps(event), json.dumps(data, ensure_ascii=False)))
        except Exception:
            pass

    def _push_main(self, event: str, data: dict) -> None:
        self._push(self._main_win, event, data)

    def _push_all(self, event: str, data: dict) -> None:
        self._push(self._main_win, event, data)
        self._push(self._tail_win, event, data)

    def _td(self, t: "Track | None") -> "dict | None":
        return t.to_dict() if t else None

    # ── события плеера ──
    def _on_player_event(self, kind: str, **kw) -> None:
        t = kw.get("track")
        if kind == "loading":
            self._push_all("status", {"state": "loading", "track": self._td(t)})
        elif kind == "progress":
            if kw.get("gen") == self.player._gen:
                self._push_all("status", {"state": "loading", "track": self._td(t),
                                          "pct": kw.get("pct", 0)})
        elif kind == "playing":
            self._consec_err = 0
            self._busy_off = 0.0
            with self._data_lock:
                self.history = [t.id] + [i for i in self.history if i != t.id][:99]
                self._save_data()
            self._push_main("history", {"tracks": [self.tracks[i].to_dict() for i in self.history]})
            self._push_all("status", {"state": "playing", "track": self._td(t)})
        elif kind == "paused":
            self._push_all("status", {"state": "paused", "track": self._td(t)})
        elif kind == "resumed":
            self._push_all("status", {"state": "playing", "track": self._td(t)})
        elif kind == "stopped":
            self._push_all("status", {"state": "idle", "track": None})
        elif kind == "seeked":
            self._push_all("position", {"elapsed": self.player.elapsed, "duration": self.player.duration})
        elif kind == "error":
            self._push_all("status", {"state": self.player.state, "track": self._td(t)})
            self._push_main("toast", {"text": clip(str(kw.get("msg") or "Ошибка воспроизведения"), 70)})
            if self.player.state == Player.IDLE and self.queue_ids:
                self._consec_err += 1
                if self._consec_err < 3:
                    gen = self.player._gen
                    timer = threading.Timer(0.6, lambda: self.next_track(True)
                                            if not self._quit and gen == self.player._gen else None)
                    timer.daemon = True
                    timer.start()
                else:
                    self._consec_err = 0

    # ── цикл позиции / конец трека ──
    def _position_loop(self) -> None:
        while not self._quit:
            try:
                now = time.monotonic()
                p = self.player
                with p._lock:
                    if p.state == Player.PLAYING:
                        p.tick()
                        if p.busy:
                            self._busy_off = 0.0
                        elif self._busy_off == 0.0:
                            self._busy_off = now
                        elif now - self._busy_off > 0.8:
                            self._busy_off = 0.0
                            self._on_track_end()
                        self._push_all("position", {"elapsed": p.elapsed, "duration": p.duration})
                    else:
                        self._busy_off = 0.0
            except Exception:
                pass
            time.sleep(0.4)

    def _on_track_end(self) -> None:
        if self.repeat == "one":
            self.player.replay()
            return
        self.next_track(auto=True)

    # ── окна ──
    def run(self) -> None:
        if webview is None:
            print("pywebview не установлен: pip install pywebview")
            sys.exit(1)
        self._start_tray()
        self._create_main()
        self._create_tail()
        webview.start(func=self._after_start)
        self._stop_tray()

    def _create_main(self) -> None:
        title = "Aurora smoke" if self.smoke else "Aurora — музыка"
        webview.create_window(
            title, str(UI_DIR / "index.html"), js_api=self,
            width=1200, height=800, min_size=(1000, 660),
            background_color="#101010")
        self._main_win = webview.windows[-1]
        self._main_win.events.closed += lambda *a: self._on_main_closed()
        self._main_win.events.minimized += lambda *a: self._on_main_minimized()
        self._main_win.events.restored += lambda *a: self._on_main_restored()

    def _create_tail(self) -> None:
        webview.create_window(
            "Aurora — мини-плеер", str(UI_DIR / "tail.html"), js_api=self,
            width=378, height=180, min_size=(378, 180),
            frameless=True, on_top=True, hidden=True,
            background_color="#141414")
        self._tail_win = webview.windows[-1]
        self._tail_win.events.closed += lambda *a: self._on_widget_closed()

    def _on_widget_closed(self) -> None:
        self._tail_win = None
        if not self._quit:
            self.quit_app()

    # ── Win32-оформление хвостика (скругление, скрытие из панели задач) ──
    def _tail_hwnd(self) -> "int | None":
        try:
            return int(self._tail_win.native.Handle.ToInt64())
        except Exception:
            return None

    def _tail_toolwindow(self) -> None:
        import ctypes
        hwnd = self._tail_hwnd()
        if not hwnd:
            return
        try:
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x80
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def _apply_tail_shape(self) -> None:
        import ctypes
        from ctypes import wintypes
        hwnd = self._tail_hwnd()
        if not hwnd:
            return
        try:
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            rad = max(18, int(32 * self._tail_win.native.Size.Width / 378))
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, rad, rad)
            ctypes.windll.user32.SetWindowRgn(wintypes.HWND(hwnd), rgn, True)
        except Exception:
            pass

    def _after_start(self) -> None:
        self._tail_toolwindow()
        threading.Thread(target=self._position_loop, daemon=True).start()
        if self.smoke:
            threading.Thread(target=self._smoke_seq, daemon=True).start()

    # ── закрытие главного окна / мини-плеер ──
    def _on_main_closed(self) -> None:
        self._main_win = None
        if not self._quit:
            self._show_tail()

    def _on_main_minimized(self) -> None:
        if not self._quit and self._main_win is not None:
            self._show_tail()

    def _on_main_restored(self) -> None:
        if not self._quit and self._main_win is not None:
            self._hide_tail()

    def close_to_tray(self) -> None:
        self._show_tail(hide_main=True)

    def _show_tail(self, hide_main: bool = False) -> None:
        try:
            if self._tail_win is None:
                self._create_tail()
            self._place_tail()
            self._apply_tail_shape()
            if hide_main and self._main_win is not None:
                self._main_win.hide()
            self._tail_win.show()
        except Exception:
            pass

    def _hide_tail(self) -> None:
        try:
            if self._tail_win is not None:
                self._tail_win.hide()
        except Exception:
            pass

    def restore(self) -> None:
        self._hide_tail()
        try:
            if self._main_win is not None:
                self._main_win.show()
                self._main_win.restore()
            else:
                self._create_main()
        except Exception:
            try:
                self._create_main()
            except Exception:
                pass

    def _place_tail(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = self._tail_hwnd()
            if not hwnd:
                return
            # WebView2 reports its actual pixel ratio. pywebview's WinForms
            # scale can be 1 on a scaled display, making its logical size too
            # small and causing the controls to overlap.
            ratio = float(self._tail_win.evaluate_js("window.devicePixelRatio") or 1)
            ratio = min(3, max(1, ratio))
            width, height = round(378 * ratio), round(180 * ratio)

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),
                            ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
            user32.MonitorFromWindow.restype = wintypes.HMONITOR
            user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND,
                                            ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT)
            user32.SetWindowPos.restype = wintypes.BOOL
            source = self._main_win or self._tail_win
            source_hwnd = int(source.native.Handle.ToInt64())
            monitor = user32.MonitorFromWindow(wintypes.HWND(source_hwnd), 2)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work_area = info.rcWork
            else:
                work_area = wintypes.RECT()
                if not user32.SystemParametersInfoW(48, 0, ctypes.byref(work_area), 0):
                    return
            margin = round(18 * ratio)
            x = max(work_area.left, work_area.right - width - margin)
            y = max(work_area.top, work_area.bottom - height - margin)
            # Keep the window hidden while sizing and positioning it. The
            # pywebview move method uses SWP_SHOWWINDOW, causing a visible jump.
            user32.SetWindowPos(wintypes.HWND(hwnd), None, x, y, width, height,
                                0x0004 | 0x0010)
        except Exception:
            pass

    def stop_playback(self) -> str:
        self.player.stop()
        return "ok"

    def quit_app(self) -> None:
        self._quit = True
        self.player.stop()
        self._save_data()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self._stop_tray()
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        for w in (self._tail_win, self._main_win):
            try:
                if w is not None:
                    w.destroy()
            except Exception:
                pass

    # ── трей ──
    def _start_tray(self) -> None:
        if pystray is None:
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Открыть Aurora", lambda *a: self.restore(), default=True),
                pystray.MenuItem("Пауза / Плей", lambda *a: self.player.toggle()),
                pystray.MenuItem("Следующий", lambda *a: self.next_track()),
                pystray.MenuItem("Выход", lambda *a: self.quit_app()),
            )
            self._tray = pystray.Icon("aurora", make_tray_icon(), "Aurora — музыка", menu)
            self._tray.run_detached()
        except Exception:
            self._tray = None

    def _stop_tray(self) -> None:
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception:
            pass

    # ── методы, вызываемые из JS ──
    def get_state(self) -> dict:
        p = self.player
        return {
            "track": self._td(p.current),
            "state": p.state,
            "elapsed": p.elapsed,
            "duration": p.duration,
            "volume": self.vol,
            "shuffle": self.shuffle,
            "repeat": self.repeat,
            "liked": list(self.liked.keys()),
            "ui": dict(self.ui),
            "queue": [self.tracks[i].to_dict() for i in self.queue_ids],
            "history": [self.tracks[i].to_dict() for i in self.history],
        }

    def page_home(self, genre: str = "Все", force: int = 0) -> str:
        genre = genre or "Все"
        self.ui = {"page": "home", "genre": genre, "query": self.ui.get("query", "")}
        self._home_genre = genre
        self._home_gen += 1
        gen = self._home_gen
        cached = self._home_cache.get(genre)
        if cached is not None and not force:
            self._register(cached)
            self._push_main("tracks", {"page": "home", "genre": genre,
                                       "tracks": [t.to_dict() for t in cached]})
            return "cached"
        self._push_main("loading", {"page": "home", "genre": genre})

        def work():
            try:
                tracks = audius.trending(genre)
            except Exception as e:
                if gen == self._home_gen:
                    self._push_main("page_error", {"page": "home", "genre": genre,
                                                   "msg": "Не удалось загрузить подборку. Проверьте соединение."})
                return
            if gen != self._home_gen:
                return
            self._home_cache[genre] = tracks
            self._register(tracks)
            self._push_main("tracks", {"page": "home", "genre": genre,
                                       "tracks": [t.to_dict() for t in tracks]})

        self.pool.submit(work)
        return "fetching"

    def page_search(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "empty"
        self.ui = {"page": "search", "genre": self.ui.get("genre", "Все"), "query": query}
        self._search_query = query
        self._search_gen += 1
        gen = self._search_gen
        self._push_main("loading", {"page": "search", "query": query})

        def work():
            try:
                tracks = search_tracks(query, audius)
            except Exception as e:
                if gen == self._search_gen:
                    self._push_main("page_error", {"page": "search", "query": query, "msg": str(e)})
                return
            if gen != self._search_gen:
                return
            self._register(tracks)
            self._push_main("tracks", {"page": "search", "query": query,
                                       "tracks": [t.to_dict() for t in tracks]})

        self.pool.submit(work)
        return "ok"

    def page_favorites(self) -> str:
        self.ui = {"page": "fav", "genre": self.ui.get("genre", "Все"),
                   "query": self.ui.get("query", "")}
        tracks = [t for t in (Track.from_dict(v) for v in self.liked.values()) if t]
        self._register(tracks)
        self._push_main("tracks", {"page": "fav", "tracks": [t.to_dict() for t in tracks]})
        return "ok"

    def _push_queue(self):
        self._push_main("queue", {"tracks": [self.tracks[i].to_dict() for i in self.queue_ids]})

    def queue_add(self, track_id: str) -> str:
        if track_id not in self.tracks:
            return "no track"
        if track_id not in self.queue_ids:
            self.queue_ids.append(track_id)
            self._push_queue()
            self._push_main("toast", {"text": "Добавлено в очередь"})
        else:
            self._push_main("toast", {"text": "Трек уже в очереди"})
        return "ok"

    def queue_remove(self, track_id: str) -> str:
        if track_id not in self.queue_ids:
            return "missing"
        index = self.queue_ids.index(track_id)
        self.queue_ids.pop(index)
        if index <= self.q_index:
            self.q_index -= 1
        self._push_queue()
        return "ok"

    def page_library(self, page: str) -> str:
        if page not in ("queue", "history"):
            return "invalid"
        self.ui["page"] = page
        ids = self.queue_ids if page == "queue" else self.history
        self._push_main("tracks", {"page": page, "tracks": [self.tracks[i].to_dict() for i in ids]})
        return "ok"

    def _register(self, tracks: list) -> None:
        for t in tracks:
            self.tracks[t.id] = t

    def play(self, track_id: str, list_ids=None) -> str:
        t = self.tracks.get(track_id)
        if not t:
            return "no track"
        if list_ids:
            ids = [i for i in list_ids if i in self.tracks]
            if track_id in ids:
                self.queue_ids = ids
        if track_id not in self.queue_ids:
            self.queue_ids.append(track_id)
        self.q_index = self.queue_ids.index(track_id)
        self._push_queue()
        cur = self.player.current
        if cur is not None and cur.id == track_id:
            if self.player.state == Player.LOADING:
                return "loading"
            if self.player.state in (Player.PLAYING, Player.PAUSED):
                self.player.toggle()
                return "toggled"
        self._consec_err = 0
        self.player.play(t)
        return "ok"

    def toggle(self) -> str:
        p = self.player
        if p.state == Player.LOADING:
            return "loading"
        if p.state == Player.IDLE:
            if self.queue_ids:
                self.q_index = max(0, min(self.q_index, len(self.queue_ids) - 1))
                self.player.play(self.tracks[self.queue_ids[self.q_index]])
            return "idle"
        p.toggle()
        return "ok"

    def next_track(self, auto: bool = False) -> str:
        if not self.queue_ids:
            if auto:
                self.player.stop()
            return "empty"
        if self.shuffle and len(self.queue_ids) > 1:
            i = self.q_index
            while True:
                n = random.randrange(len(self.queue_ids))
                if n != i:
                    break
            self.q_index = n
        else:
            if self.q_index + 1 < len(self.queue_ids):
                self.q_index += 1
            elif self.repeat == "all":
                self.q_index = 0
            else:
                self.player.stop()
                self._push_main("toast", {"text": "Очередь закончилась"})
                return "end"
        self.player.play(self.tracks[self.queue_ids[self.q_index]])
        return "ok"

    def prev_track(self) -> str:
        if not self.queue_ids:
            return "empty"
        if self.player.current and (self.player.elapsed > 3.0 or len(self.queue_ids) == 1):
            self.player.replay()
            return "replay"
        self.q_index = max(0, self.q_index - 1)
        self.player.play(self.tracks[self.queue_ids[self.q_index]])
        return "ok"

    def seek(self, pos: float) -> str:
        self.player.seek(float(pos))
        return "ok"

    def set_volume(self, v: float) -> str:
        self.vol = max(0.0, min(1.0, float(v)))
        self.player.set_volume(self.vol)
        return "ok"

    def save_prefs(self) -> str:
        self._save_data()
        return "ok"

    def shuffle_toggle(self) -> str:
        self.shuffle = not self.shuffle
        self._save_data()
        self._push_main("prefs", {"shuffle": self.shuffle, "repeat": self.repeat})
        self._push_main("toast", {"text": "Перемешивание: " + ("вкл" if self.shuffle else "выкл")})
        return "ok"

    def repeat_cycle(self) -> str:
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        self._save_data()
        self._push_main("prefs", {"shuffle": self.shuffle, "repeat": self.repeat})
        self._push_main("toast", {"text": "Повтор: " +
                                  {"off": "выкл", "all": "всё", "one": "один трек"}[self.repeat]})
        return "ok"

    def like(self, track_id: str) -> str:
        t = self.tracks.get(track_id)
        if not t:
            return "no track"
        with self._data_lock:
            if track_id in self.liked:
                del self.liked[track_id]
                message = "Удалено из избранного"
            else:
                self.liked[track_id] = t.to_dict()
                message = "Добавлено в избранное"
            self._save_data()
        self._push_main("toast", {"text": message})
        self._push_all("liked", {"liked": list(self.liked.keys())})
        if self.ui["page"] == "fav":
            self.page_favorites()
        return "ok"

    # ── смок-тест ──
    def _smoke_seq(self) -> None:
        try:
            time.sleep(4)
            self.close_to_tray()
            time.sleep(3)
            time.sleep(1)
            self.restore()
            time.sleep(4)
        finally:
            self.quit_app()


def main() -> None:
    smoke = "--smoke" in sys.argv
    app = AuroraApp(smoke=smoke)
    app.run()
    if smoke:
        print("SMOKE_DONE")


if __name__ == "__main__":
    main()
