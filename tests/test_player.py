"""Run with: python -m unittest discover -s tests -v."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

os.environ['SDL_AUDIODRIVER'] = 'dummy'
import aurora_music as app
from playback import Player


def track(name='one', duration=60):
    return app.Track(name, 'audius', name, name, 'Artist', duration)


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mixer = MagicMock()
        self.patch = patch('playback.pygame.mixer.music', self.mixer)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.events = []

    def player(self, fetch=None):
        def download(t, dest, *_):
            dest.write_bytes(b'audio')
        return Player(lambda event, **data: self.events.append((event, data)),
                      lambda: True, fetch or download, self.temp.name)

    def wait_playing(self, player):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if player.state == Player.PLAYING:
                return
            time.sleep(.01)
        self.fail(f'Playback did not start: {self.events}')

    def test_play_pause_seek_resume_and_stop(self):
        p = self.player()
        p.play(track())
        self.wait_playing(p)
        p.toggle()
        self.assertEqual(p.state, Player.PAUSED)
        p.seek(25)
        self.assertEqual(p.elapsed, 25)
        self.assertEqual(p.state, Player.PAUSED)
        p.toggle()
        self.assertEqual(p.state, Player.PLAYING)
        p.stop()
        self.assertIsNone(p.current)
        self.assertEqual((p.elapsed, p.duration), (0, 0))

    def test_late_download_cannot_replace_new_track(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def fetch(t, dest, *_):
            if t.id == 'old':
                entered.set()
                release.wait(3)
            dest.write_bytes(b'audio')
            if t.id == 'old':
                finished.set()
        p = self.player(fetch)
        p.play(track('old'))
        self.assertTrue(entered.wait(2))
        p.play(track('new'))
        self.wait_playing(p)
        release.set()
        self.assertTrue(finished.wait(2))
        time.sleep(.05)
        self.assertEqual(p.current.id, 'new')
        played = [d['track'].id for e,d in self.events if e == 'playing']
        self.assertEqual(played, ['new'])
        self.assertEqual(self.mixer.play.call_count, 1)

    def test_unknown_duration_advances_and_download_updates_duration(self):
        p = self.player()
        p.state = Player.PLAYING
        p.duration = 0
        p.started_at = 100
        with patch('playback.time.monotonic', return_value=105):
            self.assertEqual(p.tick(), 5)
        def fetch(t, dest, *_):
            t.duration = 180
            dest.write_bytes(b'audio')
        p = self.player(fetch)
        p.play(track(duration=0))
        self.wait_playing(p)
        self.assertEqual(p.duration, 180)

    def test_failed_download_reports_idle(self):
        finished = threading.Event()
        def fail(*args):
            raise RuntimeError('offline')
        p = self.player(fail)
        original = p.emit
        def emit(event, **data):
            original(event, **data)
            if event == 'error':
                finished.set()
        p.emit = emit
        p.play(track())
        self.assertTrue(finished.wait(2))
        self.assertEqual(p.state, Player.IDLE)
        self.assertEqual(self.events[-1][1]['msg'], 'offline')

    def test_unknown_duration_can_repeat(self):
        p = self.player()
        p.play(track(duration=0))
        self.wait_playing(p)
        p.elapsed = 10
        p.replay()
        self.assertEqual(p.elapsed, 0)
        self.mixer.play.assert_called_with(start=0.0)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'data.json'
        self.path_patch = patch.object(app, 'DATA_FILE', self.data)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        with patch.object(app.AuroraApp, '_init_audio', return_value=False):
            self.a = app.AuroraApp()
        self.addCleanup(self.a.pool.shutdown, wait=True)
        self.a._push_main = MagicMock()
        self.a._push_all = MagicMock()
        self.a._register([track('a'), track('b'), track('c')])

    def test_event_signature_history_and_persistence(self):
        self.a.player.emit('playing', track=track('a'))
        self.a.player.emit('playing', track=track('b'))
        self.a.player.emit('playing', track=track('a'))
        self.assertEqual(self.a.history, ['a', 'b'])
        self.a.shuffle_toggle()
        self.a.repeat_cycle()
        self.a.like('a')
        saved = json.loads(self.data.read_text('utf-8'))
        self.assertTrue(saved['shuffle'])
        self.assertEqual(saved['repeat'], 'all')
        self.assertIn('a', saved['liked'])
        self.a._load_data()
        self.assertEqual(self.a.history, ['a', 'b'])

    def test_malformed_settings_are_tolerated(self):
        for value in ([], {'liked': []}, {'liked': {'bad': None}}, {'volume': 'bad', 'history': [None]}):
            self.data.write_text(json.dumps(value), 'utf-8')
            self.a._load_data()
            self.assertIsInstance(self.a.liked, dict)
        self.assertIsNone(app.Track.from_dict({'id': 'invalid'}))

    def test_removing_current_queue_item_keeps_next(self):
        self.a.queue_ids = ['a', 'b', 'c']
        self.a.q_index = 1
        self.a.player.play = MagicMock()
        self.a.queue_remove('b')
        self.a.next_track()
        self.assertEqual(self.a.player.play.call_args.args[0].id, 'c')

    def test_repeat_all_wraps_manual_next(self):
        self.a.queue_ids = ['a', 'b']
        self.a.q_index = 1
        self.a.repeat = 'all'
        self.a.player.play = MagicMock()
        self.a.next_track()
        self.assertEqual(self.a.player.play.call_args.args[0].id, 'a')

    def test_removed_last_track_stops_at_end(self):
        self.a.queue_ids = ['a']
        self.a.q_index = 0
        self.a.queue_remove('a')
        self.a.player.stop = MagicMock()
        self.a._on_track_end()
        self.a.player.stop.assert_called_once()

    def test_same_track_in_new_list_updates_queue_index(self):
        self.a.player.current = self.a.tracks['b']
        self.a.player.state = Player.PLAYING
        self.a.player.toggle = MagicMock()
        self.a.play('b', ['a', 'b', 'c'])
        self.assertEqual(self.a.q_index, 1)
        self.a.player.toggle.assert_called_once()

    def test_queue_deduplicates_and_rejects_missing_track(self):
        self.a.queue_add('a')
        self.a.queue_add('a')
        self.a.queue_add('missing')
        self.assertEqual(self.a.queue_ids, ['a'])

    def test_search_all_sources_failed_vs_empty(self):
        with patch.object(app, 'ensure_ytdlp', return_value=True), patch.object(app, 'youtube_search', side_effect=RuntimeError('offline')):
            client = MagicMock()
            client.search.side_effect = RuntimeError('offline')
            with self.assertRaises(RuntimeError):
                app.search_tracks('test', client)
        with patch.object(app, 'ensure_ytdlp', return_value=True), patch.object(app, 'youtube_search', return_value=[]):
            client = MagicMock()
            client.search.return_value = []
            self.assertEqual(app.search_tracks('test', client), [])


if __name__ == '__main__':
    unittest.main()
