# -*- coding: utf-8 -*-
"""
✦ Aurora — современный музыкальный плеер на Python.

Источники музыки:
  • YouTube (через yt-dlp) — ПОЛНЫЕ песни любых артистов (личное использование).
  • Audius (api.audius.co) — открытый API без ключей, полные треки инди-сцены.

Запуск:
  pip install -r requirements.txt
  python aurora_music.py

Горячие клавиши:  Space — пауза/плей,  Ctrl+F — фокус на поиск.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import random
import sys
import tempfile
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import requests
import pygame
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps

APP_NAME = "AURORA_PLAYER"
UA = {"User-Agent": "AuroraMusicPlayer/1.0"}

APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
DATA_FILE = APP_DIR / "aurora_data.json"
CACHE_DIR = Path(tempfile.gettempdir()) / "aurora_music"

# ─────────────────────────── палитра ───────────────────────────
C_BG        = "#0B0B10"   # фон
C_SIDEBAR   = "#0E0E15"   # боковая панель
C_SURFACE   = "#12121A"   # плеер/верхняя панель
C_CARD      = "#15151E"   # карточка
C_CARD_HV   = "#1B1B27"   # карточка под курсором
C_INPUT     = "#171720"   # поля ввода
C_BORDER    = "#23232F"
C_TEXT      = "#F4F4F7"
C_MUTED     = "#9494A3"
C_FAINT     = "#5E5E6E"
C_ACCENT    = "#8B5CF6"   # фиолетовый неон
C_ACCENT_H  = "#7A4EF0"
C_LIKE      = "#FF5C8A"

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


def rounded_square(pil: "Image.Image", size: int, radius: int) -> "Image.Image":
    img = ImageOps.fit(pil.convert("RGB"), (size, size))
    k = 4
    mask = Image.new("L", (size * k, size * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * k - 1, size * k - 1), radius * k, fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


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
            return Track(**d)
        except TypeError:
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


# ─────────────────────────── YouTube (полные песни) ───────────────────────────
ytdlp_mod = None      # ленивый импорт, чтобы не тормозить старт приложения
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
    """Скачивает полную аудиодорожку и конвертирует в mp3 (ffmpeg из imageio-ffmpeg)."""
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
            track.duration = dur  # точная длительность после полной загрузки метаданных
    except Exception:
        pass
    return dest


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


def search_tracks(query: str, client: AudiusClient) -> list[Track]:
    """Ищем параллельно: YouTube (полные песни) + Audius (открытая сцена)."""
    res: dict = {}

    def yt():
        try:
            res["yt"] = youtube_search(query, 25)
        except Exception:
            res["yt"] = []

    def au():
        try:
            res["au"] = client.search(query, 20)
        except Exception:
            res["au"] = []

    th1 = threading.Thread(target=yt, daemon=True)
    th2 = threading.Thread(target=au, daemon=True)
    th1.start()
    th2.start()
    th1.join(25)
    th2.join(25)

    out: list[Track] = list(res.get("yt") or [])
    seen = {(t.title.lower(), t.artist.lower()) for t in out}
    for t in res.get("au") or []:
        key = (t.title.lower(), t.artist.lower())
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


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
    """Единая точка скачивания: YouTube — полный трек, Audius/Deezer — стрим."""
    if track.kind == "youtube":
        return youtube_fetch_audio(track, dest, progress, cancelled)
    return download_audio(track, dest, progress, cancelled)


audius = AudiusClient()


# ─────────────────────────── плеер ───────────────────────────
class Player:
    IDLE, LOADING, PLAYING, PAUSED = "idle", "loading", "playing", "paused"

    def __init__(self, emit, ensure_audio) -> None:
        self.emit = emit
        self.ensure_audio = ensure_audio
        self.state = self.IDLE
        self.current: Track | None = None
        self.duration = 0
        self.elapsed = 0.0
        self.volume = 0.8
        self._gen = 0
        self._file: Path | None = None
        self.started_at = 0.0

    @property
    def busy(self) -> bool:
        try:
            return bool(pygame.mixer.music.get_busy())
        except Exception:
            return False

    def play(self, track: Track) -> None:
        self._gen += 1
        gen = self._gen
        self._stop()
        self.state = self.LOADING
        self.current = track
        self.duration = track.duration
        self.elapsed = 0.0
        self._file = None
        self.emit("loading", track=track)
        threading.Thread(target=self._worker, args=(track, gen), daemon=True).start()

    def _stop(self) -> None:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass

    def _worker(self, track: Track, gen: int) -> None:
        cancelled = lambda: gen != self._gen  # noqa: E731
        last_pct = -1

        def progress(done: int, total: int) -> None:
            nonlocal last_pct
            pct = int(done * 100 / max(total, 1))
            if pct != last_pct and pct % 5 == 0:
                last_pct = pct
                self.emit("progress", track=track, pct=pct, gen=gen)

        try:
            if not self.ensure_audio():
                raise RuntimeError("Нет аудиоустройства")
            fname = (track.ref + ".mp3") if track.kind == "youtube" \
                else hashlib.md5(track.id.encode()).hexdigest() + ".mp3"
            dest = CACHE_DIR / "audio" / fname
            if not (dest.exists() and dest.stat().st_size > 10_000):
                fetch_audio(track, dest, progress, cancelled)
            if cancelled():
                return
            self._file = dest
            try:
                pygame.mixer.music.load(str(dest))
            except Exception:
                try:
                    dest.unlink()
                except OSError:
                    pass
                fetch_audio(track, dest, progress, cancelled)
                if cancelled():
                    return
                pygame.mixer.music.load(str(dest))
            if cancelled():
                return
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play()
            if cancelled():
                self._stop()
                return
            self.state = self.PLAYING
            self.started_at = time.monotonic()
            self.elapsed = 0.0
            self.emit("playing", track=track)
        except Cancelled:
            return
        except Exception as e:
            if gen == self._gen:
                self.state = self.IDLE
                self.emit("error", track=track, msg=str(e) or e.__class__.__name__)

    def toggle(self) -> None:
        if self.state == self.PLAYING:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass
            self.state = self.PAUSED
            self.emit("paused", track=self.current)
        elif self.state == self.PAUSED:
            try:
                pygame.mixer.music.unpause()
            except Exception:
                pass
            self.state = self.PLAYING
            self.started_at = time.monotonic()
            self.emit("resumed", track=self.current)

    def seek(self, sec: float) -> None:
        if self.state == self.LOADING or not self.current or not self._file:
            return
        sec = max(0.0, min(sec, float(self.duration or 1) - 0.5))
        was_playing = self.state == self.PLAYING
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(str(self._file))
            try:
                pygame.mixer.music.play(start=sec)
            except Exception:
                sec = 0.0
                pygame.mixer.music.play()
            if not was_playing:
                pygame.mixer.music.pause()
            self.elapsed = sec
            self.started_at = time.monotonic()
        except Exception as e:
            self.emit("error", track=self.current, msg="Ошибка перемотки: " + str(e))

    def replay(self) -> None:
        if self.state == self.PAUSED:
            self.toggle()
        self.seek(0.0)

    def stop(self) -> None:
        self._gen += 1
        self._stop()
        self.state = self.IDLE
        self.current = None
        self.elapsed = 0.0
        self.emit("stopped", track=None)

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, float(v)))
        try:
            pygame.mixer.music.set_volume(self.volume)
        except Exception:
            pass


# ─────────────────────────── приложение ───────────────────────────
class App(ctk.CTk):
    def __init__(self, smoke: bool = False) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("✦ Aurora — музыка")
        self.geometry("1280x800")
        self.minsize(1020, 660)
        self.configure(fg_color=C_BG)

        self.smoke = smoke
        self._load_data()

        # состояние
        self.pool = ThreadPoolExecutor(max_workers=10)
        self.ui_q: "queue.Queue" = queue.Queue()
        self.audio_ok = self._init_audio()
        self.player = Player(self.emit, self.ensure_audio)
        self.player.volume = self.vol

        self.queue_tracks: list[Track] = []
        self.q_index = -1
        self.shuffle = False
        self.repeat = "off"            # off | all | one

        self._img_cache: dict = {}
        self._placeholders: dict = {}
        self._cards: list = []
        self._grid_frame = None
        self._grid_cols = 0
        self._row_refs: dict = {}
        self._like_btns: dict = {}
        self._visible_tracks: list[Track] = []
        self._trending_cache: dict = {}
        self._last_search: "tuple | None" = None
        self._search_query = ""
        self._home_gen = 0
        self._search_gen = 0
        self._home_genre = "Все"
        self._seeking = False
        self._busy_off_since = 0.0
        self._consec_err = 0
        self._toast_job = None
        self._spin_i = 0
        self._load_lbl = None
        self._load_prefix = "Загрузка"
        self._last_tick = time.monotonic()
        self.page = None
        self._SPIN = "◐◓◑◒"

        self._build()
        self._make_icon()
        self._pump()
        self._tick()

        self.bind("<space>", self._on_space)
        self.bind("<Control-f>", self._on_ctrl_f)
        self.bind("<Control-F>", self._on_ctrl_f)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        if not smoke:
            self.after(1500, lambda: self.attributes("-topmost", False))
        self.after(150, lambda: self.show_page("home"))

    # ── аудио ──
    def _init_audio(self) -> bool:
        try:
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.init()
            pygame.mixer.init()
            return True
        except Exception:
            return False

    def ensure_audio(self) -> bool:
        if self.audio_ok:
            return True
        try:
            pygame.mixer.quit()
            pygame.mixer.init(44100, -16, 2, 512)
            self.audio_ok = True
        except Exception:
            self.audio_ok = False
        return self.audio_ok

    # ── потокобезопасность ──
    def emit(self, kind: str, **kw) -> None:
        self.ui_q.put(lambda: self._handle_event(kind, kw))

    def _pump(self) -> None:
        try:
            while True:
                fn = self.ui_q.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    pass
                except Exception:
                    import traceback
                    traceback.print_exc()
        except queue.Empty:
            pass
        finally:
            self.after(60, self._pump)

    # ── данные ──
    def _load_data(self) -> None:
        try:
            raw = json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            raw = {}
        try:
            self.vol = float(raw.get("volume", 0.8))
        except (TypeError, ValueError):
            self.vol = 0.8
        self.liked: dict = {}
        for k, v in (raw.get("liked") or {}).items():
            t = Track.from_dict(v)
            if t:
                self.liked[k] = t.to_dict()

    def _save_data(self) -> None:
        try:
            DATA_FILE.write_text(
                json.dumps({"volume": self.vol, "liked": self.liked}, ensure_ascii=False, indent=1),
                "utf-8",
            )
        except Exception:
            pass

    # ── построение интерфейса ──
    def _build(self) -> None:
        self.f_logo   = ctk.CTkFont("Segoe UI", 20, "bold")
        self.f_logosub = ctk.CTkFont("Segoe UI", 11)
        self.f_nav    = ctk.CTkFont("Segoe UI", 13)
        self.f_h1     = ctk.CTkFont("Segoe UI", 22, "bold")
        self.f_sub    = ctk.CTkFont("Segoe UI", 12)
        self.f_card_t = ctk.CTkFont("Segoe UI", 13, "bold")
        self.f_card_s = ctk.CTkFont("Segoe UI", 12)
        self.f_row_t  = ctk.CTkFont("Segoe UI", 13, "bold")
        self.f_small  = ctk.CTkFont("Segoe UI", 11)
        self.f_bar_t  = ctk.CTkFont("Segoe UI", 13, "bold")
        self.f_time   = ctk.CTkFont("Consolas", 10)
        self.f_tiny   = ctk.CTkFont("Segoe UI", 10)

        def g(size: int) -> ctk.CTkFont:
            return ctk.CTkFont("Segoe UI Symbol", size)

        self.g = g

        # верхняя акцентная полоска
        ctk.CTkFrame(self, height=3, corner_radius=0, fg_color=C_ACCENT)\
            .place(x=0, y=0, relwidth=1)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── сайдбар ──
        side = ctk.CTkFrame(self, width=224, corner_radius=0, fg_color=C_SIDEBAR)
        side.grid(row=0, column=0, sticky="nsw")
        side.pack_propagate(False)

        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.pack(anchor="w", padx=20, pady=(24, 2))
        ctk.CTkLabel(logo, text="✦", font=self.g(20), text_color=C_ACCENT).pack(side="left")
        ctk.CTkLabel(logo, text=" AURORA", font=self.f_logo, text_color=C_TEXT).pack(side="left")
        ctk.CTkLabel(side, text="онлайн-музыка", font=self.f_logosub, text_color=C_FAINT)\
            .pack(anchor="w", padx=38, pady=(0, 14))

        ctk.CTkFrame(side, height=1, corner_radius=0, fg_color=C_BORDER).pack(fill="x", padx=18, pady=(0, 14))

        self.nav_btns: dict = {}
        for name, key in (("🏠  Главная", "home"), ("🔍  Поиск", "search"), ("♡  Избранное", "favorites")):
            b = ctk.CTkButton(side, text=name, height=40, corner_radius=10, anchor="w",
                              font=self.f_nav, fg_color="transparent", hover_color=C_CARD_HV,
                              text_color=C_MUTED, command=lambda k=key: self.show_page(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav_btns[key] = b

        spacer = ctk.CTkFrame(side, fg_color="transparent")
        spacer.pack(fill="both", expand=True)
        ctk.CTkLabel(side, text="YouTube — полные песни\nAudius — открытая сцена",
                     font=self.f_tiny, text_color=C_FAINT, justify="left")\
            .pack(anchor="w", padx=20, pady=(0, 16))

        # ── основная область ──
        main = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(main, height=62, fg_color=C_BG, corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        ctk.CTkFrame(main, height=1, corner_radius=0, fg_color=C_BORDER).grid(row=1, column=0, sticky="ew")

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            top, width=340, height=38, corner_radius=19, font=self.f_sub,
            fg_color=C_INPUT, border_color=C_BORDER, border_width=1,
            text_color=C_TEXT, placeholder_text_color=C_MUTED,
            placeholder_text="🔍  Найди любую песню — YouTube + Audius…", textvariable=self.search_var)
        self.search_entry.pack(side="right", padx=(8, 20), pady=12)
        self.search_entry.bind("<Return>", lambda e: self.do_search())

        ctk.CTkButton(top, text="🔍", width=38, height=38, corner_radius=19,
                      font=self.g(14), fg_color=C_ACCENT, hover_color=C_ACCENT_H,
                      text_color="white", command=self.do_search)\
            .pack(side="right", padx=(0, 6), pady=12)

        refresh = ctk.CTkButton(top, text="↻", width=38, height=38, corner_radius=19,
                                font=self.g(15), fg_color=C_INPUT, hover_color=C_CARD_HV,
                                text_color=C_MUTED, border_width=1, border_color=C_BORDER,
                                command=self._on_refresh)
        refresh.pack(side="right", padx=(0, 4), pady=12)

        self.content = ctk.CTkScrollableFrame(
            main, fg_color=C_BG, corner_radius=0,
            scrollbar_button_color=C_BORDER, scrollbar_button_hover_color=C_CARD_HV)
        self.content.grid(row=2, column=0, sticky="nsew")

        # ── разделитель + плеер ──
        ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=C_BORDER)\
            .grid(row=1, column=0, columnspan=2, sticky="ew")

        self._build_player()

        # тост-уведомление
        self.toast_label = ctk.CTkLabel(
            self, text="", font=self.f_sub, text_color=C_TEXT, fg_color="#1D1D2A",
            corner_radius=10, height=36)
        self.toast_label.place_forget()

    def _build_player(self) -> None:
        bar = ctk.CTkFrame(self, height=92, corner_radius=0, fg_color=C_SURFACE)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        # левая часть: обложка + названия + лайк
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=16, pady=10)

        self.bar_cover = ctk.CTkLabel(left, text="♪", width=54, height=54,
                                      font=self.g(20), text_color=C_FAINT, fg_color=C_CARD,
                                      corner_radius=10)
        self.bar_cover.pack(side="left")

        info = ctk.CTkFrame(left, fg_color="transparent")
        info.pack(side="left", padx=12)
        self.bar_title = ctk.CTkLabel(info, text="Ничего не играет", font=self.f_bar_t,
                                      text_color=C_TEXT, anchor="w", width=210)
        self.bar_title.pack(anchor="w")
        self.bar_artist = ctk.CTkLabel(info, text="выбери трек из списка", font=self.f_small,
                                       text_color=C_MUTED, anchor="w", width=210)
        self.bar_artist.pack(anchor="w")

        self.bar_like = ctk.CTkButton(left, text="♡", width=30, height=30, corner_radius=15,
                                      fg_color="transparent", hover_color=C_CARD_HV,
                                      text_color=C_MUTED, font=self.g(15),
                                      command=self._toggle_like_current)
        self.bar_like.pack(side="left", padx=(4, 0))

        # центр: кнопки + перемотка
        center = ctk.CTkFrame(bar, fg_color="transparent")
        center.grid(row=0, column=1, sticky="ew")

        ctr = ctk.CTkFrame(center, fg_color="transparent")
        ctr.pack(pady=(10, 0))

        self.btn_shuffle = ctk.CTkButton(ctr, text="⇄", width=32, height=32, corner_radius=16,
                                         fg_color="transparent", hover_color=C_CARD_HV,
                                         text_color=C_FAINT, font=self.g(14),
                                         command=self._toggle_shuffle)
        self.btn_shuffle.pack(side="left", padx=5)
        self.btn_shuffle.configure(command=self._toggle_shuffle)

        ctk.CTkButton(ctr, text="⏮", width=38, height=38, corner_radius=19,
                      fg_color="transparent", hover_color=C_CARD_HV, text_color=C_MUTED,
                      font=self.g(15), command=self._prev).pack(side="left", padx=5)

        self.play_btn = ctk.CTkButton(ctr, text="▶", width=48, height=48, corner_radius=24,
                                      fg_color=C_ACCENT, hover_color=C_ACCENT_H,
                                      text_color="white", font=self.g(19),
                                      command=self._on_play_btn)
        self.play_btn.pack(side="left", padx=8)

        ctk.CTkButton(ctr, text="⏭", width=38, height=38, corner_radius=19,
                      fg_color="transparent", hover_color=C_CARD_HV, text_color=C_MUTED,
                      font=self.g(15), command=lambda: self._next(False)).pack(side="left", padx=5)

        self.btn_repeat = ctk.CTkButton(ctr, text="↻", width=32, height=32, corner_radius=16,
                                        fg_color="transparent", hover_color=C_CARD_HV,
                                        text_color=C_FAINT, font=self.g(14),
                                        command=self._cycle_repeat)
        self.btn_repeat.pack(side="left", padx=5)

        seek = ctk.CTkFrame(center, fg_color="transparent")
        seek.pack(fill="x", padx=30, pady=(4, 8))
        self.time_elapsed = ctk.CTkLabel(seek, text="0:00", font=self.f_time, text_color=C_MUTED, width=42)
        self.time_elapsed.pack(side="left")
        self.seek_slider = ctk.CTkSlider(
            seek, from_=0, to=100, height=16, button_length=12,
            fg_color="#26262F", progress_color=C_ACCENT,
            button_color="#D8D8E0", button_hover_color="white")
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=8)
        self.seek_slider.set(0)  # CTkSlider по умолчанию стартует с 0.5
        self.time_total = ctk.CTkLabel(seek, text="0:00", font=self.f_time, text_color=C_MUTED, width=42)
        self.time_total.pack(side="left")
        self.seek_slider.bind("<ButtonPress-1>", self._on_seek_press)
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)

        # правая часть: громкость
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=18, pady=10)
        self.vol_btn = ctk.CTkButton(right, text="🔊", width=30, height=30, corner_radius=15,
                                     fg_color="transparent", hover_color=C_CARD_HV,
                                     text_color=C_MUTED, font=self.g(13),
                                     command=self._toggle_mute)
        self.vol_btn.pack(side="left", padx=(0, 6))
        self.vol_slider = ctk.CTkSlider(
            right, from_=0, to=1, width=110, height=16, button_length=12,
            fg_color="#26262F", progress_color=C_ACCENT,
            button_color="#D8D8E0", button_hover_color="white",
            command=self._on_volume)
        self.vol_slider.set(self.vol)
        self.vol_slider.pack(side="left")
        self.vol_slider.bind("<ButtonRelease-1>", lambda e: self._save_data())
        self._last_vol = self.vol if self.vol > 0 else 0.8

    # ── служебные виджеты ──
    def _make_icon(self) -> None:
        """Иконка окна и таскбара: фиолетовый квадрат с белой звездой."""
        try:
            from PIL import ImageTk
            s = 64
            img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((2, 2, s - 3, s - 3), 16, fill=(139, 92, 246, 255))
            cx, cy = s / 2, s / 2
            pts = []
            for i in range(8):
                ang = -math.pi / 2 + i * math.pi / 4
                r = s * 0.30 if i % 2 == 0 else s * 0.12
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            d.polygon(pts, fill=(255, 255, 255, 255))
            self.iconphoto(True, ImageTk.PhotoImage(img))
        except Exception:
            pass

    def _placeholder(self, size: int):
        p = self._placeholders.get(size)
        if p:
            return p
        img = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, size * 2 - 1, size * 2 - 1), size // 3, fill=(28, 28, 40, 255))
        p = ctk.CTkImage(light_image=img.resize((size, size), Image.LANCZOS), size=(size, size))
        self._placeholders[size] = p
        return p

    def _cover(self, url: str, size: int, radius: int, apply) -> None:
        key = (url, size)
        img = self._img_cache.get(key)
        if img:
            apply(img)
            return
        if not url:
            apply(self._placeholder(size))
            return

        def work():
            try:
                f = CACHE_DIR / "covers" / (hashlib.md5(url.encode()).hexdigest() + ".img")
                if not f.exists():
                    f.parent.mkdir(parents=True, exist_ok=True)
                    r = requests.get(url, timeout=(6, 20), headers=UA)
                    r.raise_for_status()
                    f.write_bytes(r.content)
                pil = Image.open(f)
                pil.load()
            except Exception:
                self.ui_q.put(lambda: apply(self._placeholder(size)))
                return
            out = rounded_square(pil, size, radius)
            self.ui_q.put(lambda: self._cover_done(url, size, out, apply))

        self.pool.submit(work)

    def _cover_done(self, url: str, size: int, pil, apply) -> None:
        try:
            img = ctk.CTkImage(light_image=pil, size=(size, size))
        except Exception:
            return
        self._img_cache[(url, size)] = img
        apply(img)

    def _hoverify(self, w, normal: str, hovered: str,
                  normal_border: "str | None" = None, hover_border: "str | None" = None) -> None:
        def set_state(hover: bool) -> None:
            try:
                if normal_border is not None:
                    w.configure(fg_color=hovered if hover else normal,
                                border_color=hover_border if hover else normal_border)
                else:
                    w.configure(fg_color=hovered if hover else normal)
            except Exception:
                pass

        def check():
            try:
                if not w.winfo_exists():
                    return
                under = w.winfo_containing(w.winfo_pointerx(), w.winfo_pointery())
                while under is not None and under is not w:
                    under = getattr(under, "master", None)
                set_state(under is w)
            except Exception:
                pass

        def leave(e=None):
            w.after(70, check)

        targets = [w] + [c for c in w.winfo_children()
                         if not isinstance(c, (ctk.CTkButton, ctk.CTkSlider))]
        for t in targets:
            try:
                t.bind("<Enter>", lambda e: set_state(True), add="+")
                t.bind("<Leave>", leave, add="+")
            except Exception:
                pass

    def _bind_tree(self, w, seq: str, fn) -> None:
        try:
            w.bind(seq, fn)
        except Exception:
            pass
        for c in w.winfo_children():
            if isinstance(c, (ctk.CTkButton, ctk.CTkSlider)):
                continue
            self._bind_tree(c, seq, fn)

    def _toast(self, text: str) -> None:
        try:
            self.toast_label.configure(text=text)
            self.toast_label.place(relx=1.0, rely=1.0, x=-18, y=-110, anchor="se")
            if self._toast_job:
                self.after_cancel(self._toast_job)
            self._toast_job = self.after(2600, self.toast_label.place_forget)
        except Exception:
            pass

    # ── страницы ──
    def _clear_content(self) -> None:
        for w in self.content.winfo_children():
            w.destroy()
        self._cards = []
        self._grid_frame = None
        self._grid_cols = 0
        self._row_refs = {}
        self._like_btns = {}
        self._load_lbl = None

    def show_page(self, name: str, **kw) -> None:
        self.page = name
        for key, b in self.nav_btns.items():
            active = key == name
            b.configure(fg_color=C_CARD_HV if active else "transparent",
                        text_color=C_TEXT if active else C_MUTED)
        if name == "home":
            self._page_home(kw.get("genre", self._home_genre))
        elif name == "search":
            self._page_search()
        elif name == "favorites":
            self._page_favorites()

    def _page_header(self, title: str, sub: str) -> None:
        ctk.CTkLabel(self.content, text=title, font=self.f_h1, text_color=C_TEXT, anchor="w")\
            .pack(anchor="w", padx=24, pady=(18, 0))
        ctk.CTkLabel(self.content, text=sub, font=self.f_sub, text_color=C_MUTED, anchor="w")\
            .pack(anchor="w", padx=24, pady=(2, 8))

    def _state_label(self, text: str, glyph: str = "♪") -> None:
        box = ctk.CTkFrame(self.content, fg_color="transparent")
        box.pack(fill="both", expand=True, pady=(120, 0))
        ctk.CTkLabel(box, text=glyph, font=self.g(44), text_color="#2E2E3C").pack()
        ctk.CTkLabel(box, text=text, font=self.f_sub, text_color=C_MUTED).pack(pady=(8, 12))

    def _loading_label(self, prefix: str) -> None:
        """Анимированная надпись «Загрузка ···» (оживляется в _tick)."""
        self._load_prefix = prefix
        lbl = ctk.CTkLabel(self.content, text=prefix + "…", font=self.f_sub, text_color=C_MUTED)
        lbl.pack(pady=(70, 0))
        self._load_lbl = lbl

    def _drop_loading_label(self) -> None:
        lbl = self._load_lbl
        self._load_lbl = None
        if lbl is not None:
            try:
                lbl.destroy()
            except Exception:
                pass

    def _error_state(self, retry: "callable") -> None:
        box = ctk.CTkFrame(self.content, fg_color="transparent")
        box.pack(fill="both", expand=True, pady=(120, 0))
        ctk.CTkLabel(box, text="⚠", font=self.g(40), text_color="#3A2E3C").pack()
        ctk.CTkLabel(box, text="Не удалось загрузить. Проверь интернет.",
                     font=self.f_sub, text_color=C_MUTED).pack(pady=(8, 12))
        ctk.CTkButton(box, text="Повторить", width=120, height=34, corner_radius=17,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_H, font=self.f_sub,
                      command=retry).pack()

    # ── главная (тренды) ──
    def _page_home(self, genre: str = "Все") -> None:
        self._home_genre = genre
        self._home_gen += 1
        gen = self._home_gen
        self._clear_content()
        self._page_header("Популярное сейчас",
                          f"Audius · {'все жанры' if genre == 'Все' else genre} · неделя")

        chips = ctk.CTkFrame(self.content, fg_color="transparent")
        chips.pack(fill="x", padx=24, pady=(4, 8))
        for gname in GENRES:
            active = gname == genre
            b = ctk.CTkButton(
                chips, text=gname, height=30, corner_radius=15, font=self.f_sub,
                fg_color=C_ACCENT if active else C_CARD,
                hover_color=C_ACCENT_H if active else C_CARD_HV,
                text_color="white" if active else C_MUTED,
                border_width=0 if active else 1,
                border_color=None if active else C_BORDER,
                command=lambda gg=gname: self.show_page("home", genre=gg))
            b.pack(side="left", padx=(0, 8))

        cached = self._trending_cache.get(genre)
        if cached is not None:
            self._render_grid(cached)
            return

        self._loading_label("Загрузка")

        def work():
            try:
                tracks = audius.trending(genre)
            except Exception as e:
                self.emit("page_error", page="home", gen=gen, msg=str(e))
                return
            self.ui_q.put(lambda: self._home_loaded(gen, genre, tracks))

        self.pool.submit(work)

    def _home_loaded(self, gen: int, genre: str, tracks: list) -> None:
        if gen != self._home_gen or self.page != "home":
            return
        self._trending_cache[genre] = tracks
        self._drop_loading_label()
        self._render_grid(tracks)

    def _render_grid(self, tracks: list) -> None:
        self._visible_tracks = list(tracks)
        if not tracks:
            self._state_label("Здесь пока пусто")
            return
        self._grid_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self._grid_frame.pack(fill="x", padx=16, pady=(2, 20))
        self._grid_frame.bind("<Configure>", lambda e: self._relayout_grid())
        for idx, t in enumerate(tracks):
            self._make_card(self._grid_frame, t, idx)
        self._relayout_grid(force=True)
        self._refresh_rows()
        self._refresh_like_buttons()

    def _relayout_grid(self, force: bool = False) -> None:
        if not self._grid_frame or not self._cards:
            return
        try:
            w = self._grid_frame.winfo_width() or 900
        except Exception:
            w = 900
        cols = max(2, min(5, int(w // 238)))
        if cols == self._grid_cols and not force:
            return
        self._grid_cols = cols
        for i, card in enumerate(self._cards):
            card.grid(row=i // cols, column=i % cols, padx=7, pady=7, sticky="nsew")
        for c in range(cols):
            self._grid_frame.grid_columnconfigure(c, weight=1, uniform="cards")

    def _make_card(self, parent, t: Track, idx: int) -> None:
        card = ctk.CTkFrame(parent, corner_radius=14, fg_color=C_CARD,
                            border_width=1, border_color=C_BORDER, cursor="hand2")
        art = ctk.CTkLabel(card, text="♪", width=160, height=160,
                           font=self.g(30), text_color="#4A4A6E", fg_color="#12121B",
                           corner_radius=12)
        art.pack(padx=12, pady=(12, 8))
        title = ctk.CTkLabel(card, text=clip(t.title, 26), font=self.f_card_t,
                             text_color=C_TEXT, anchor="w")
        title.pack(fill="x", padx=14)
        sub = ctk.CTkFrame(card, fg_color="transparent")
        sub.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(sub, text=clip(t.artist, 20), font=self.f_card_s,
                     text_color=C_MUTED, anchor="w")\
            .pack(side="left", fill="x", expand=True)
        like = ctk.CTkButton(sub, text="♡", width=30, height=30, corner_radius=15,
                             fg_color="transparent", hover_color=C_CARD_HV,
                             text_color=C_MUTED, font=self.g(13),
                             command=lambda tt=t: self.toggle_like(tt))
        like.pack(side="right", padx=(0, 6))
        ctk.CTkButton(sub, text="▶", width=34, height=34, corner_radius=17,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_H, text_color="white",
                      font=self.g(13),
                      command=lambda: self._play_from(self._visible_tracks, idx)).pack(side="right")
        self._like_btns.setdefault(t.id, []).append(like)

        self._hoverify(card, C_CARD, C_CARD_HV, C_BORDER, C_ACCENT)
        self._bind_tree(card, "<Button-1>", lambda e: self._play_from(self._visible_tracks, idx))
        self._cards.append(card)
        self._row_refs.setdefault(t.id, []).append((card, title, t.title))
        if t.art_big:
            self._cover(t.art_big, 160, 12, self._img_into(art, 160))

    def _img_into(self, widget, size: int):
        def apply(img):
            try:
                if widget.winfo_exists():
                    widget.configure(image=img or self._placeholder(size), text="",
                                     fg_color="transparent" if img else "#101018")
            except Exception:
                pass
        return apply

    # ── поиск ──
    def do_search(self) -> None:
        q = self.search_var.get().strip()
        if not q:
            return
        self._search_query = q
        self._search_gen += 1
        self.show_page("search")

    def _page_search(self) -> None:
        self._clear_content()
        q = self._search_query
        if not q:
            self._page_header("Поиск", "найди треки, артистов или жанры")
            self._state_label("Введи запрос в строке поиска сверху", "🔍")
            return
        if self._last_search and self._last_search[0] == q:
            self._render_search_page(q, self._last_search[1])
            return

        self._page_header("Поиск", f"запрос: «{q}»")
        gen = self._search_gen
        self._loading_label("Ищу")

        def work():
            try:
                tracks = search_tracks(q, audius)
            except Exception as e:
                self.emit("page_error", page="search", gen=gen, msg=str(e))
                return
            self.ui_q.put(lambda: self._search_loaded(gen, q, tracks))

        self.pool.submit(work)

    def _search_loaded(self, gen: int, q: str, tracks: list) -> None:
        if gen != self._search_gen or self.page != "search":
            return
        self._last_search = (q, tracks)
        self._page_search()

    def _render_search_page(self, q: str, tracks: list) -> None:
        self._clear_content()
        self._page_header("Результаты: «%s»" % clip(q, 34), f"найдено треков: {len(tracks)}")
        if not tracks:
            self._state_label("Ничего не нашлось — попробуй другой запрос")
            return
        self._render_list(tracks)

    # ── избранное ──
    def _page_favorites(self) -> None:
        self._clear_content()
        tracks = [t for t in (Track.from_dict(v) for v in self.liked.values()) if t]
        self._page_header("Избранное", f"треков: {len(tracks)}")
        if not tracks:
            self._state_label("Нажимай ♡ у трека — он появится здесь")
            return
        self._render_list(tracks)

    # ── список треков ──
    def _render_list(self, tracks: list) -> None:
        self._visible_tracks = list(tracks)
        for idx, t in enumerate(tracks):
            self._make_row(self.content, t, idx)
        self._refresh_rows()
        self._refresh_like_buttons()

    def _make_row(self, parent, t: Track, idx: int) -> None:
        row = ctk.CTkFrame(parent, corner_radius=10, fg_color="transparent", height=56)
        row.pack(fill="x", padx=14, pady=2)
        row.pack_propagate(False)

        art = ctk.CTkLabel(row, text="♪", width=42, height=42, font=self.g(15),
                           text_color="#2E2E3C", fg_color="#101018", corner_radius=9)
        art.pack(side="left", padx=(8, 10), pady=6)

        mid = ctk.CTkFrame(row, fg_color="transparent")
        mid.pack(side="left", fill="x", expand=True)
        title = ctk.CTkLabel(mid, text=t.title, font=self.f_row_t, text_color=C_TEXT, anchor="w")
        title.pack(anchor="w")
        artist_text = clip(t.artist, 46)
        ctk.CTkLabel(mid, text=artist_text, font=self.f_small, text_color=C_MUTED, anchor="w")\
            .pack(anchor="w")

        like = ctk.CTkButton(row, width=30, height=30, corner_radius=15,
                             fg_color="transparent", hover_color=C_CARD_HV,
                             text_color=C_MUTED, font=self.g(14),
                             command=lambda tt=t: self.toggle_like(tt))
        like.pack(side="left", padx=4)
        self._like_btns.setdefault(t.id, []).append(like)

        ctk.CTkLabel(row, text=mmss(t.duration) if t.duration else "—",
                     font=self.f_small, text_color=C_FAINT, width=44)\
            .pack(side="left", padx=(4, 12))

        self._hoverify(row, "transparent", C_CARD)
        self._bind_tree(row, "<Button-1>", lambda e: self._play_from(self._visible_tracks, idx))
        self._row_refs.setdefault(t.id, []).append((row, title, t.title))
        if t.art_small:
            self._cover(t.art_small, 42, 9, self._img_into(art, 42))

    # ── воспроизведение ──
    def _play_from(self, tracks: list, idx: int) -> None:
        if not tracks or not (0 <= idx < len(tracks)):
            return
        t = tracks[idx]
        cur = self.player.current
        if cur and cur.id == t.id:
            if self.player.state == Player.LOADING:
                return  # уже качается — не перезапускаем
            if self.player.state in (Player.PLAYING, Player.PAUSED):
                self.player.toggle()  # повторный клик по играющему — пауза/продолжить
                return
        self.queue_tracks = list(tracks)
        self.q_index = idx
        self._play_current()

    def _play_current(self) -> None:
        if not self.queue_tracks or not (0 <= self.q_index < len(self.queue_tracks)):
            return
        self.player.play(self.queue_tracks[self.q_index])

    def _on_play_btn(self) -> None:
        p = self.player
        if p.state == Player.LOADING:
            return
        if p.state == Player.IDLE:
            if self.queue_tracks:
                self._play_current()
            return
        p.toggle()

    def _prev(self) -> None:
        if not self.queue_tracks:
            return
        if self.player.elapsed > 3.0 or len(self.queue_tracks) == 1:
            self.player.replay()
            return
        self.q_index = max(0, self.q_index - 1)
        self._play_current()

    def _next(self, auto: bool = False) -> None:
        if not self.queue_tracks:
            return
        if self.shuffle and len(self.queue_tracks) > 1:
            i = self.q_index
            while True:
                n = random.randrange(len(self.queue_tracks))
                if n != i:
                    break
            self.q_index = n
        else:
            if self.q_index + 1 < len(self.queue_tracks):
                self.q_index += 1
            elif self.repeat == "all" and auto:
                self.q_index = 0
            else:
                self.player.stop()
                self._toast("Очередь закончилась")
                return
        self._play_current()

    def _on_track_end(self) -> None:
        if self.repeat == "one":
            self.player.replay()
            return
        self._next(auto=True)

    def _toggle_shuffle(self) -> None:
        self.shuffle = not self.shuffle
        self.btn_shuffle.configure(text_color=C_ACCENT if self.shuffle else C_FAINT,
                                   fg_color=C_CARD_HV if self.shuffle else "transparent")
        self._toast("Перемешивание: " + ("вкл" if self.shuffle else "выкл"))

    def _cycle_repeat(self) -> None:
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        self.btn_repeat.configure(
            text="↻¹" if self.repeat == "one" else "↻",
            text_color=C_ACCENT if self.repeat != "off" else C_FAINT,
            fg_color=C_CARD_HV if self.repeat != "off" else "transparent")
        self._toast("Повтор: " + {"off": "выкл", "all": "всё", "one": "один трек"}[self.repeat])

    # ── громкость / перемотка ──
    def _on_volume(self, v: float) -> None:
        self.vol = float(v)
        self.player.set_volume(self.vol)
        if self.vol > 0:
            self._last_vol = self.vol
        self.vol_btn.configure(text="🔊" if self.vol > 0.5 else ("🔉" if self.vol > 0 else "🔇"))

    def _toggle_mute(self) -> None:
        target = 0.0 if self.vol > 0 else (self._last_vol or 0.8)
        self.vol_slider.set(target)
        self._on_volume(target)

    def _on_seek_press(self, e=None) -> None:
        self._seeking = True

    def _on_seek_release(self, e=None) -> None:
        if not self._seeking:
            return
        self._seeking = False
        val = float(self.seek_slider.get())
        if self.player.state in (Player.PLAYING, Player.PAUSED):
            self.player.seek(val)
            self.player.elapsed = val
            self.time_elapsed.configure(text=mmss(val))
        else:
            self.seek_slider.set(self.player.elapsed)

    # ── избранное ──
    def toggle_like(self, t: Track) -> None:
        if t.id in self.liked:
            del self.liked[t.id]
            self._toast("Удалено из избранного")
        else:
            self.liked[t.id] = t.to_dict()
            self._toast("Добавлено в избранное ♥")
        self._save_data()
        self._refresh_like_buttons()
        if self.page == "favorites":
            self.show_page("favorites")

    def _toggle_like_current(self) -> None:
        if self.player.current:
            self.toggle_like(self.player.current)

    def _refresh_like_buttons(self) -> None:
        for tid, btns in self._like_btns.items():
            liked = tid in self.liked
            for b in btns:
                try:
                    if b.winfo_exists():
                        b.configure(text="♥" if liked else "♡",
                                    text_color=C_LIKE if liked else C_MUTED)
                except Exception:
                    pass
        if self.player.current:
            liked = self.player.current.id in self.liked
            self.bar_like.configure(text="♥" if liked else "♡",
                                    text_color=C_LIKE if liked else C_MUTED)

    # ── события плеера (выполняются в UI-потоке) ──
    def _handle_event(self, kind: str, kw: dict) -> None:
        t = kw.get("track")
        if kind == "page_error":
            if kw.get("page") == self.page and kw.get("gen") in (self._home_gen, self._search_gen):
                self._drop_loading_label()
                self._error_state(lambda: self.show_page(self.page))
            return
        if t is None and kind not in ("stopped",):
            return
        if kw.get("gen") is not None and kw.get("gen") != self.player._gen:
            return

        if kind == "loading":
            self._bar_set_track(t, loading=True)
        elif kind == "progress":
            if self.player.state == Player.LOADING:
                self.bar_artist.configure(text=f"загрузка… {kw.get('pct', 0)}%")
        elif kind == "playing":
            self._consec_err = 0
            self._bar_set_track(t, loading=False)
            self.play_btn.configure(text="❚❚")
            self._refresh_rows()
            self._refresh_like_buttons()
            if t.art_small:
                self._cover(t.art_small, 54, 10,
                            self._img_into(self.bar_cover, 54))
        elif kind == "paused":
            self.play_btn.configure(text="▶")
        elif kind == "resumed":
            self.play_btn.configure(text="❚❚")
        elif kind == "stopped":
            self._reset_bar()
        elif kind == "error":
            self._toast("⚠ " + clip(kw.get("msg") or "Ошибка воспроизведения", 60))
            if self.player.state == Player.IDLE and self.queue_tracks:
                self._consec_err += 1
                if self._consec_err < 3:
                    self.after(500, lambda: self._next(auto=True))
                else:
                    self._consec_err = 0
                    self._reset_bar()

    def _bar_set_track(self, t: Track, loading: bool) -> None:
        self.bar_title.configure(text=clip(t.title, 34))
        self.bar_artist.configure(text="загрузка…" if loading else clip(t.artist, 46))
        self.time_total.configure(text=mmss(t.duration) if t.duration else "—")
        self.seek_slider.configure(to=max(t.duration, 1))
        self.seek_slider.set(0)
        self.time_elapsed.configure(text="0:00")
        self.bar_cover.configure(image=self._placeholder(54), text="", fg_color="transparent")

    def _reset_bar(self) -> None:
        self.bar_title.configure(text="Ничего не играет")
        self.bar_artist.configure(text="выбери трек из списка")
        self.bar_cover.configure(image=self._placeholder(54), text="")
        self.play_btn.configure(text="▶")
        self.seek_slider.set(0)
        self.time_elapsed.configure(text="0:00")
        self.time_total.configure(text="0:00")
        self.bar_like.configure(text="♡", text_color=C_MUTED)
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        cur = self.player.current.id if self.player.current else None
        for tid, refs in self._row_refs.items():
            playing = tid == cur
            for _, lbl, base in refs:
                try:
                    if lbl.winfo_exists():
                        lbl.configure(text=("♪ " + base) if playing else base,
                                      text_color=C_ACCENT if playing else C_TEXT)
                except Exception:
                    pass

    # ── цикл тика: прогресс, конец трека, спиннер ──
    def _tick(self) -> None:
        try:
            now = time.monotonic()
            dt = min(now - self._last_tick, 1.0)
            self._last_tick = now
            p = self.player
            if p.state == Player.PLAYING:
                p.elapsed = min(p.elapsed + dt, float(p.duration or 0))
                if not self._seeking and p.duration:
                    self.seek_slider.set(p.elapsed)
                    self.time_elapsed.configure(text=mmss(p.elapsed))
                busy = p.busy
                if busy:
                    self._busy_off_since = 0.0
                else:
                    if self._busy_off_since == 0.0:
                        self._busy_off_since = now
                    elif now - self._busy_off_since > 0.8 and p.elapsed >= 1.0:
                        self._busy_off_since = 0.0
                        self._on_track_end()
            elif p.state == Player.LOADING:
                self.play_btn.configure(text=self._SPIN[self._spin_i % len(self._SPIN)])
                self._spin_i += 1
            lbl = self._load_lbl
            if lbl is not None:
                if lbl.winfo_exists():
                    self._spin_i += 1
                    lbl.configure(text=self._load_prefix + " " + "·" * (1 + self._spin_i % 3))
                else:
                    self._load_lbl = None
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            self.after(200, self._tick)

    # ── клавиши / закрытие ──
    def _on_space(self, e=None) -> None:
        try:
            cls = self.focus_get().winfo_class()
        except Exception:
            cls = ""
        if cls in ("Entry", "TEntry", "Text", "TText", "TSpinbox", "TCombobox"):
            return
        self._on_play_btn()
        return "break"

    def _on_ctrl_f(self, e=None) -> None:
        self.search_entry.focus_set()
        return "break"

    def _on_refresh(self) -> None:
        if self.page == "home":
            self._trending_cache.pop(self._home_genre, None)
        elif self.page == "search":
            self._last_search = None
        self.show_page(self.page or "home")

    def _smoke_autoplay(self) -> None:
        """Тестовый прогон: играем полную песню с YouTube (или тренд Audius)."""
        if self.player.state != Player.IDLE:
            return

        def work():
            try:
                yts = youtube_search("daft punk one more time", 3)
            except Exception:
                yts = []
            if yts:
                self.ui_q.put(lambda: self._play_from(yts, 0))
            elif self._visible_tracks:
                self.ui_q.put(lambda: self._play_from(self._visible_tracks, 0))

        threading.Thread(target=work, daemon=True).start()

    def _on_close(self) -> None:
        self._save_data()
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        self.destroy()


# ─────────────────────────── запуск ───────────────────────────
def main() -> None:
    smoke = "--smoke" in sys.argv
    try:
        app = App(smoke=smoke)
    except Exception:
        import traceback
        traceback.print_exc()
        raise
    if smoke:
        if "--autoplay" in sys.argv:
            app.after(6000, app._smoke_autoplay)
        app.after(22000, app.destroy)
    app.mainloop()
    if smoke:
        print("SMOKE_DONE")


if __name__ == "__main__":
    main()
