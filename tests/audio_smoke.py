"""Exercise the real pygame mixer with a generated, local MP3 (no network)."""
import os
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import wave

import pygame
import imageio_ffmpeg
from aurora_music import Track
from playback import Player

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    source = root / 'tone.wav'
    with wave.open(str(source), 'wb') as output:
        output.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(i * 440 * math.tau / 44100))) for i in range(44100 * 3)))
    mp3 = root / 'tone.mp3'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-loglevel', 'error', '-i', str(source), str(mp3)], check=True)
    ready = threading.Event()
    errors = []
    def emit(event, **data):
        if event == 'playing':
            ready.set()
        elif event == 'error':
            errors.append(data)
            ready.set()
    def fetch(track, dest, *_):
        dest.write_bytes(mp3.read_bytes())
    pygame.mixer.init()
    try:
        player = Player(emit, lambda: True, fetch, root / 'cache')
        player.play(Track('test', 'audius', 'test', 'Tone', 'Local', 3))
        assert ready.wait(5), 'Playback timeout'
        assert not errors, errors
        assert player.busy
        player.toggle()
        assert player.state == Player.PAUSED
        player.seek(1.5)
        assert player.elapsed == 1.5
        player.toggle()
        assert player.busy
        player.stop()
        assert not player.busy
        assert not errors, errors
        print('PASS: real MP3 decode, pause, seek, resume, stop (dummy audio device).')
    finally:
        pygame.mixer.quit()
