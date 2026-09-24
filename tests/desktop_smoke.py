"""Launch the real WebView2 bridge with isolated data and an offline catalogue."""
import os
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import ctypes
from ctypes import wintypes
import tempfile
import threading
import time
from pathlib import Path

import aurora_music as module

errors = []
with tempfile.TemporaryDirectory() as directory:
    module.DATA_FILE = Path(directory) / 'settings.json'
    module.audius.trending = lambda genre: []
    app = module.AuroraApp()
    app._start_tray = lambda: None
    original_start = app._after_start
    def checks():
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if app._main_win.evaluate_js("document.querySelector('.state h2')?.textContent") == 'Пока нет треков':
                    break
                time.sleep(.2)
            else:
                raise AssertionError('WebView bridge or initial catalogue failed')
            app._main_win.evaluate_js("document.querySelector('[data-page=queue]').click()")
            time.sleep(.5)
            assert app._main_win.evaluate_js("document.querySelector('h1').textContent") == 'Очередь'
            app.player.current = module.Track('test', 'audius', 'test', 'Тихий вечер', 'Лев Берг', 120)
            app.player.state = app.player.PAUSED
            app.player.elapsed = 33
            app.player.duration = 120
            app._main_win.minimize()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not app._tail_win.native.Visible:
                time.sleep(.1)
            assert app._tail_win.native.Visible, 'Desktop player did not appear on minimize'
            geometry = app._tail_win.evaluate_js("""(() => {
                const rect = selector => document.querySelector(selector).getBoundingClientRect();
                return {width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
                    artBottom: rect('.artwork').bottom,
                    timelineTop: rect('.timeline').top,
                    timelineBottom: rect('.timeline').bottom,
                    controlsTop: rect('.widget-controls').top};
            })()""")
            assert geometry['width'] >= 376 and geometry['height'] >= 178, geometry
            assert geometry['artBottom'] < geometry['timelineTop'], geometry
            assert geometry['timelineBottom'] <= geometry['controlsTop'], geometry
            native = app._tail_win.native
            assert abs(native.Size.Width - 378 * geometry['dpr']) <= 2
            assert abs(native.Size.Height - 180 * geometry['dpr']) <= 2
            before = (native.Location.X, native.Location.Y)
            cursor = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
            try:
                # A physical click on the card must not recenter the WinForms window.
                ctypes.windll.user32.SetCursorPos(before[0] + round(35 * geometry['dpr']),
                                                    before[1] + round(62 * geometry['dpr']))
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(.2)
            finally:
                ctypes.windll.user32.SetCursorPos(cursor.x, cursor.y)
            assert (native.Location.X, native.Location.Y) == before, 'Desktop player jumped after click'
            assert app._tail_win.evaluate_js("document.querySelector('#t').textContent") == 'Тихий вечер'
            app._main_win.restore()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and app._tail_win.native.Visible:
                time.sleep(.1)
            assert not app._tail_win.native.Visible, 'Desktop player did not hide on restore'
            app.close_to_tray()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not app._tail_win.native.Visible:
                time.sleep(.1)
            assert app._tail_win.native.Visible and not app._main_win.native.Visible, \
                'Desktop player did not replace hidden main window'
            app.player.stop()
            assert app.player.state == app.player.IDLE, 'Playback stop blocked by hidden main window'
            app.restore()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and (not app._main_win.native.Visible or app._tail_win.native.Visible):
                time.sleep(.1)
            assert app._main_win.native.Visible and not app._tail_win.native.Visible, \
                'Main window did not return from desktop player'
            app.player.current = module.Track('test', 'audius', 'test', 'Тихий вечер', 'Лев Берг', 120)
            app.player.state = app.player.PAUSED
            app.player.elapsed = 33
            app.player.duration = 120
            # Closing the actual main window must keep the small desktop window alive.
            app._main_win.destroy()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and app._main_win is not None:
                time.sleep(.1)
            assert app._main_win is None, 'Main window did not close'
            while time.monotonic() < deadline:
                if app._tail_win.native.Visible and app._tail_win.evaluate_js("document.querySelector('#t').textContent") == 'Тихий вечер':
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Desktop player did not appear after close')
            assert app._tail_win.native.Visible, 'Desktop player is hidden after main window closed'
            assert (app._tail_win.native.Location.X, app._tail_win.native.Location.Y) == before, \
                'Desktop player changed position after closing main window'
            assert app._tail_win.evaluate_js("document.querySelector('#elapsed').textContent") == '0:33'
            stop = app._tail_win.evaluate_js("""(() => {
                const r = document.querySelector('#stop').getBoundingClientRect();
                return {x: r.left + r.width / 2, y: r.top + r.height / 2};
            })()""")
            ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
            try:
                ctypes.windll.user32.SetCursorPos(before[0] + round(stop['x'] * geometry['dpr']),
                                                    before[1] + round(stop['y'] * geometry['dpr']))
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            finally:
                ctypes.windll.user32.SetCursorPos(cursor.x, cursor.y)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and app.player.state != app.player.IDLE:
                time.sleep(.1)
            assert app.player.state == app.player.IDLE, 'Stop control failed'
            assert (app._tail_win.native.Location.X, app._tail_win.native.Location.Y) == before, \
                'Desktop player jumped after pressing stop'
            app.restore()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if app._main_win and app._main_win.evaluate_js("typeof window.pywebview?.api?.get_state") == 'function':
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Main window did not restore')
            print('PASS: WebView2, minimize/restore, actual close, desktop player metadata and stop.')
        except Exception as error:
            errors.append(error)
        finally:
            app.quit_app()
    def after_start():
        original_start()
        threading.Thread(target=checks, daemon=True).start()
    app._after_start = after_start
    app.run()
if errors:
    raise errors[0]
