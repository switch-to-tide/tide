"""Audio tabs: the player, the tab it lives in, and the setting that removes it.

No test here makes a sound. A fake `ffplay` on PATH stands in for the real
one - it is a shell script that sleeps - so the process handling, the signals
and the timing are all exercised for real while the speakers stay quiet.
"""

import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import ENTER, Session
from tide import audio
from tide.app import App
from tide.audio import player as player_mod, probe
from tide.keys import Key, Mouse
from tide.term import Screen

TONE_SECONDS = 6


def write_tone(path, seconds=TONE_SECONDS, rate=8000):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b''.join(
            struct.pack('<h', int(2000 * math.sin(2 * math.pi * 440 * t / rate)))
            for t in range(int(rate * seconds))))
    return path


def fake_player(folder, sleep='30'):
    """A stand-in for ffplay: takes the same arguments, makes no sound."""
    path = os.path.join(folder, 'ffplay')
    with open(path, 'w') as f:
        f.write('#!/bin/sh\nexec /bin/sleep %s\n' % sleep)
    os.chmod(path, 0o755)
    return path


class AudioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-audio-')
        self.cfg = tempfile.mkdtemp(prefix='tide-audio-cfg-')
        self.bin = tempfile.mkdtemp(prefix='tide-audio-bin-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.was_path = os.environ.get('PATH', '')
        os.environ['PATH'] = self.bin                  # only our fake player
        fake_player(self.bin)
        player_mod.forget()
        self.tone = write_tone(os.path.join(self.tmp, 'tone.wav'))
        with open(os.path.join(self.tmp, 'notes.txt'), 'w') as f:
            f.write('hello\n')

    def tearDown(self):
        os.environ['PATH'] = self.was_path
        os.environ.pop('TIDE_CONFIG_HOME', None)
        player_mod.forget()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.bin, ignore_errors=True)

    def app(self, cols=96, rows=24, sound=True):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(cols, rows)
        app.show_term = False
        app.settings['audio'] = sound
        return app

    def painted(self, app):
        return '\n'.join(''.join(c[0] or ' ' for c in row)
                         for row in app.screen.cells)


class TestWhatCountsAsAudio(unittest.TestCase):
    def test_the_usual_extensions(self):
        for name in ('song.mp3', 'a.WAV', 'x.flac', 'y.m4a', 'z.ogg', 'v.aiff'):
            self.assertTrue(audio.is_audio(name), name)

    def test_and_nothing_else(self):
        for name in ('main.py', 'clip.mp4', 'photo.png', 'notes', 'a.mov'):
            self.assertFalse(audio.is_audio(name), name)


class TestProbing(AudioTest):
    def test_a_wav_measures_itself(self):
        self.assertAlmostEqual(probe.duration(self.tone), TONE_SECONDS, places=2)

    def test_something_unreadable_is_simply_unknown(self):
        path = os.path.join(self.tmp, 'mystery.opus')
        with open(path, 'wb') as f:
            f.write(b'not really an opus file')
        self.assertIsNone(probe.duration(path))

    def test_trimming_makes_a_shorter_copy(self):
        cut = probe.trim(self.tone, 2.0)
        self.assertIsNotNone(cut)
        try:
            self.assertAlmostEqual(probe.duration(cut), TONE_SECONDS - 2, places=1)
        finally:
            os.remove(cut)

    def test_a_format_it_cannot_rewrite_is_left_alone(self):
        path = os.path.join(self.tmp, 'song.mp3')
        with open(path, 'wb') as f:
            f.write(b'\xff\xfb\x90\x00' + b'\0' * 4096)
        self.assertIsNone(probe.trim(path, 1.0))


class TestThePlayer(AudioTest):
    def player(self):
        return player_mod.Player(self.tone)

    def test_it_finds_a_backend_and_the_length(self):
        p = self.player()
        self.assertIsNotNone(p.backend)
        self.assertAlmostEqual(p.duration, TONE_SECONDS, places=2)

    def test_play_pause_and_resume(self):
        p = self.player()
        try:
            self.assertTrue(p.play(0.0))
            self.assertTrue(p.playing)
            time.sleep(0.4)
            moving = p.position()
            self.assertGreater(moving, 0.2)
            p.pause()
            self.assertTrue(p.paused)
            held = p.position()
            time.sleep(0.4)
            self.assertAlmostEqual(p.position(), held, places=2,
                                   msg='the clock ran on while paused')
            p.resume()
            time.sleep(0.3)
            self.assertGreater(p.position(), held)
        finally:
            p.stop()

    def test_seeking_moves_the_position(self):
        p = self.player()
        try:
            p.play(0.0)
            p.seek(4.0)
            self.assertAlmostEqual(p.position(), 4.0, places=1)
            self.assertTrue(p.playing, 'seeking stopped the sound')
            p.nudge(-2.0)
            self.assertAlmostEqual(p.position(), 2.0, places=1)
            p.nudge(-100)
            self.assertAlmostEqual(p.position(), 0.0, delta=0.2,
                                   msg='it went past the start')
        finally:
            p.stop()

    def test_the_speed_carries_the_position_with_it(self):
        p = self.player()
        try:
            p.play(0.0)
            time.sleep(0.3)
            at = p.position()
            p.set_rate(2.0)
            self.assertAlmostEqual(p.position(), at, places=1)
            time.sleep(0.4)
            self.assertGreater(p.position() - at, 0.6, 'it did not speed up')
        finally:
            p.stop()

    def test_stopping_ends_the_process_and_tidies_up(self):
        p = self.player()
        p.play(0.0)
        process = p._process
        p.stop()
        time.sleep(0.2)
        self.assertIsNotNone(process.poll(), 'the player is still running')
        self.assertIsNone(p._temp, 'a temporary file was left behind')
        self.assertFalse(p.playing)

    def test_it_notices_when_the_file_runs_out(self):
        fake_player(self.bin, sleep='0.2')
        p = player_mod.Player(self.tone)
        try:
            p.play(0.0)
            for _ in range(30):
                if p.finished():
                    break
                time.sleep(0.1)
            self.assertTrue(p.finished(), 'it never noticed the end')
            self.assertFalse(p.playing)
        finally:
            p.stop()

    def test_with_no_player_at_all_it_says_so(self):
        os.remove(os.path.join(self.bin, 'ffplay'))
        player_mod.forget()
        p = player_mod.Player(self.tone)
        self.assertIsNone(p.backend)
        self.assertFalse(p.play(0.0))
        self.assertIn('no audio player', p.error)

    def test_a_player_that_cannot_seek_gets_a_trimmed_copy(self):
        p = self.player()
        p.backend = player_mod.Backend('ffplay', p.backend.build)   # seek=False
        try:
            p.play(3.0)
            self.assertIsNotNone(p._temp, 'no stand-in file was made')
            self.assertAlmostEqual(probe.duration(p._temp), TONE_SECONDS - 3,
                                   places=1)
            temp = p._temp
            p.stop()
            self.assertFalse(os.path.exists(temp), 'the copy was left behind')
        finally:
            p.stop()


class TestTheTab(AudioTest):
    def open(self, sound=True):
        app = self.app(sound=sound)
        view = app.open_file(self.tone)
        app.render()
        return app, view

    def test_a_sound_file_opens_as_a_player_not_as_text(self):
        app, view = self.open()
        self.assertTrue(getattr(view, 'is_audio', False))
        self.assertIsNone(app.overlay, 'it asked before opening')
        painted = self.painted(app)
        self.assertIn('tone.wav', painted)
        self.assertIn('play', painted)
        self.assertIn('0:06', painted)

    def test_the_tab_looks_like_any_other(self):
        app, _view = self.open()
        self.assertIn('tone.wav', ''.join(c[0] or ' '
                                          for c in app.screen.cells[1]))

    def test_text_files_are_unaffected(self):
        app = self.app()
        ed = app.open_file(os.path.join(self.tmp, 'notes.txt'))
        self.assertFalse(getattr(ed, 'is_audio', False))
        self.assertEqual(ed.doc.text(), 'hello\n')

    def test_clicking_play_starts_it_and_clicking_again_stops(self):
        app, view = self.open()
        x1, _x2, y = view.play_span
        app.handle_mouse(Mouse('press', x1 + 2, y))
        self.assertTrue(view.player.playing)
        app.render()
        self.assertIn('pause', self.painted(app))
        app.handle_mouse(Mouse('press', x1 + 2, y))
        self.assertTrue(view.player.paused)
        view.close()

    def test_the_bar_seeks_where_it_is_clicked(self):
        app, view = self.open()
        x1, x2, y = view.bar_span
        app.handle_mouse(Mouse('press', x1 + (x2 - x1) // 2, y))
        self.assertAlmostEqual(view.player.position(), TONE_SECONDS / 2.0,
                               delta=0.4)
        app.handle_mouse(Mouse('press', x1, y))
        self.assertAlmostEqual(view.player.position(), 0.0, delta=0.2)
        view.close()

    def test_dragging_along_the_bar_scrubs(self):
        app, view = self.open()
        x1, x2, y = view.bar_span
        app.handle_mouse(Mouse('press', x1, y))
        app.handle_mouse(Mouse('drag', x1 + (x2 - x1) // 4, y))
        self.assertGreater(view.player.position(), 0.5)
        app.handle_mouse(Mouse('release', x1 + (x2 - x1) // 4, y))
        self.assertFalse(view.dragging)
        view.close()

    def test_the_speed_button_goes_round_the_five(self):
        app, view = self.open()
        x1, _x2, y = view.speed_span
        seen = [view.player.rate]
        for _ in range(5):
            app.handle_mouse(Mouse('press', x1 + 2, y))
            seen.append(view.player.rate)
        self.assertEqual(seen, [1.0, 1.25, 1.5, 2.0, 0.5, 1.0])
        view.close()

    def test_the_keys_work_too(self):
        app, view = self.open()
        app.handle_key(Key('char', char=' '))
        self.assertTrue(view.player.playing)
        app.handle_key(Key('char', char=' '))
        self.assertTrue(view.player.paused)
        app.handle_key(Key('right'))
        self.assertAlmostEqual(view.player.position(), 5.0, delta=0.5)
        app.handle_key(Key('char', char='s'))
        self.assertEqual(view.player.rate, 1.25)
        app.handle_key(Key('home'))
        self.assertAlmostEqual(view.player.position(), 0.0, delta=0.2)
        view.close()

    def test_it_cannot_be_typed_into_or_saved(self):
        app, view = self.open()
        before = open(self.tone, 'rb').read()
        for ch in 'XYZ':
            app.handle_key(Key('char', char=ch))
        self.assertFalse(app.save())
        self.assertIn('not text', app.message)
        self.assertEqual(open(self.tone, 'rb').read(), before,
                         'the sound file was written to')
        view.close()

    def test_opening_it_twice_reuses_the_tab(self):
        app, view = self.open()
        again = app.open_file(self.tone)
        self.assertIs(again, view)
        self.assertEqual(len(app.editors), 1)
        view.close()

    def test_closing_the_tab_stops_the_sound(self):
        app, view = self.open()
        view.player.play(0.0)
        process = view.player._process
        app.close_tab(app.active)
        time.sleep(0.2)
        self.assertIsNotNone(process.poll(), 'it kept playing after the close')

    def test_nothing_is_asked_of_the_app_when_nothing_is_playing(self):
        app, view = self.open()
        self.assertFalse(app._audio_busy())
        view.player.play(0.0)
        self.assertTrue(app._audio_busy())
        view.player.pause()
        self.assertFalse(app._audio_busy())
        view.close()

    def test_a_text_only_session_never_asks_about_audio(self):
        app = self.app()
        app.open_file(os.path.join(self.tmp, 'notes.txt'))
        self.assertFalse(app._audio_busy())

    def test_with_no_player_the_tab_says_what_to_install(self):
        os.remove(os.path.join(self.bin, 'ffplay'))
        player_mod.forget()
        app, _view = self.open()
        painted = self.painted(app)
        self.assertIn('no audio player', painted)
        self.assertIn('ffmpeg', painted)


class TestTheSetting(AudioTest):
    def test_it_is_on_by_default_and_in_the_panel(self):
        from tide import settings as store
        self.assertTrue(store.DEFAULTS['audio'])
        self.assertIn('audio', [key for key, _l, _v in store.FIELDS])

    def test_turned_off_a_sound_file_is_just_a_file_again(self):
        app = self.app(sound=False)
        view = app.open_file(self.tone)
        self.assertIsNone(view, 'it opened anyway')
        self.assertIsNotNone(app.overlay, 'no question about a binary file')

    def test_turned_off_nothing_audio_is_reached(self):
        app = self.app(sound=False)
        app.open_file(os.path.join(self.tmp, 'notes.txt'))
        self.assertFalse(any(getattr(tab, 'is_audio', False)
                             for tab in app.editors))


class TestInASession(unittest.TestCase):
    """Through a pty, with the fake player on the session's PATH."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-audio-live-')
        self.bin = tempfile.mkdtemp(prefix='tide-audio-live-bin-')
        fake_player(self.bin)
        for name in ('sh', 'sleep', 'env'):        # the shell still needs these
            for folder in ('/bin', '/usr/bin'):
                source = os.path.join(folder, name)
                link = os.path.join(self.bin, name)
                if os.path.exists(source) and not os.path.exists(link):
                    os.symlink(source, link)
        self.tone = write_tone(os.path.join(self.tmp, 'tone.wav'))
        self.s = Session([self.tone, self.tmp], cols=90, rows=22, cwd=self.tmp,
                         env={'PATH': self.bin})

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.bin, ignore_errors=True)

    def test_it_opens_playing_nothing_and_then_plays(self):
        painted = self.s.screen()
        self.assertIn('tone.wav', painted)
        self.assertIn('play', painted)
        self.s.type(' ')
        self.s.pump(0.6)
        self.assertIn('pause', self.s.screen(), 'space did not start it')
        self.assertIn('playing', self.s.screen())

    def test_the_bar_moves_while_it_plays(self):
        self.s.type(' ')
        self.s.pump(0.5)
        time.sleep(1.2)
        self.s.pump(0.5)
        self.assertIn('0:0', self.s.screen())
        self.assertNotIn('Traceback', self.s.screen())

    def test_the_editor_still_works_beside_it(self):
        s = self.s
        with open(os.path.join(self.tmp, 'notes.txt'), 'w') as f:
            f.write('hello\n')
        s.key('\x10')                       # ctrl+p
        s.type('notes')
        s.key(ENTER)
        s.pump(0.8)
        s.type('X')
        s.pump(0.6)
        self.assertIn('Xhello', s.screen(), 'the editor stopped working')
        self.assertNotIn('Traceback', s.screen())


if __name__ == '__main__':
    unittest.main(verbosity=2)
