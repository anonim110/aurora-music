# -*- coding: utf-8 -*-
"""Быстрая проверка источников музыки (запускать: python check_api.py)."""
import sys


def main() -> None:
    print("1) Разрешаем узлы Audius (api.audius.co)…")
    import requests
    r = requests.get("https://api.audius.co", timeout=10, headers={"User-Agent": "AuroraCheck/1.0"})
    r.raise_for_status()
    hosts = r.json()["data"]
    print("   хостов доступно:", len(hosts), "→ используем", hosts[0])
    host = hosts[0]

    print("2) Тренды Audius…")
    r2 = requests.get(host + "/v1/tracks/trending",
                      params={"app_name": "AURORA_CHECK", "limit": 3, "time": "week"},
                      timeout=15, headers={"User-Agent": "AuroraCheck/1.0"})
    r2.raise_for_status()
    data = r2.json()["data"]
    print("   OK, треков:", len(data))
    for t in data[:3]:
        print("   •", t.get("title"), "—", (t.get("user") or {}).get("name"))

    print("3) Поиск YouTube через yt-dlp (полные песни)…")
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                "extract_flat": "in_playlist", "skip_download": True, "socket_timeout": 15}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("ytsearch3:the weeknd blinding lights", download=False)
        entries = [e for e in (info or {}).get("entries") or [] if e]
        print("   OK, найдено:", len(entries))
        for e in entries[:3]:
            print("   •", e.get("title"), "|", e.get("duration"), "сек")
    except Exception as e:
        print("   YouTube недоступен (плеер продолжит работать через Audius):", e)

    print("\nВСЁ OK — можно запускать плеер: python aurora_music.py")
    sys.exit(0)


if __name__ == "__main__":
    main()
