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
        app.settings['audio'] = sound      # as if it had been turned on
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
        said = app.message
        self.assertFalse(app.save())
        self.assertEqual(app.message, said, 'ctrl+s said something')
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
        self.assertIn('can play sound', painted)
        self.assertIn('ffmpeg', painted)

    def test_over_ssh_it_says_where_the_sound_goes(self):
        os.environ['SSH_CONNECTION'] = '10.0.0.1 22 10.0.0.2 22'
        try:
            app, view = self.open()
            self.assertIn('over ssh', self.painted(app))
            view.close()
        finally:
            os.environ.pop('SSH_CONNECTION', None)


class TestTheSetting(AudioTest):
    def test_it_is_off_until_asked_for_and_is_in_the_panel(self):
        from tide import settings as store
        self.assertFalse(store.DEFAULTS['audio'],
                         'a fresh install should not assume a player')
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
        self.cfg = tempfile.mkdtemp(prefix='tide-audio-live-cfg-')
        os.makedirs(os.path.join(self.cfg, 'tide'))
        with open(os.path.join(self.cfg, 'tide', 'settings.json'), 'w') as f:
            f.write('{"audio": true}')          # switched on, as a user would
        self.s = Session([self.tone, self.tmp], cols=90, rows=22, cwd=self.tmp,
                         env={'PATH': self.bin, 'TIDE_CONFIG_HOME': self.cfg})

    def tearDown(self):
        self.s.close()
        for folder in (self.tmp, self.bin, self.cfg):
            shutil.rmtree(folder, ignore_errors=True)

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


def open_fds():
    """How many files this process has open, for spotting leaks."""
    for folder in ('/proc/self/fd', '/dev/fd'):
        if os.path.isdir(folder):
            try:
                return len(os.listdir(folder))
            except OSError:
                pass
    return 0


class TestWhenTheFileGoesAway(AudioTest):
    def open(self):
        app = self.app()
        view = app.open_file(self.tone)
        app.render()
        return app, view

    def delete(self, view):
        os.remove(self.tone)
        view.check_disk(force=True)

    def test_it_keeps_playing_what_it_had(self):
        app, view = self.open()
        view.player.play(0.0)
        time.sleep(0.3)
        self.delete(view)
        self.assertTrue(view.missing)
        self.assertTrue(view.player.playing, 'the sound stopped with the file')
        app.render()
        self.assertNotIn('Traceback', self.painted(app))
        view.close()

    def test_the_tab_carries_a_red_mark(self):
        app, view = self.open()
        self.delete(view)
        mark = view.tab_mark()
        self.assertEqual(mark[0], '!')
        from tide import theme
        self.assertEqual(mark[1], theme.ERROR)
        app.render()
        strip = ''.join(c[0] or ' ' for c in app.screen.cells[1])
        self.assertIn('!', strip, 'no mark on the tab itself')
        view.close()

    def test_the_tab_says_what_happened(self):
        app, view = self.open()
        self.delete(view)
        app.render()
        self.assertIn('the file has been deleted', self.painted(app))
        view.close()

    def test_it_can_still_be_played_from_the_start(self):
        app, view = self.open()
        self.delete(view)
        self.assertTrue(view.rescued, 'nothing was kept')
        self.assertTrue(view.player.play(0.0), 'it will not play again')
        self.assertTrue(view.player.playing)
        view.close()

    def test_it_can_still_be_paused_resumed_and_seeked(self):
        app, view = self.open()
        view.player.play(0.0)
        time.sleep(0.2)
        self.delete(view)
        view.player.pause()
        self.assertTrue(view.player.paused)
        view.player.resume()
        self.assertTrue(view.player.playing)
        view.player.seek(3.0)
        self.assertAlmostEqual(view.player.position(), 3.0, delta=0.3)
        view.close()

    def test_what_it_kept_goes_when_the_tab_does(self):
        app, view = self.open()
        self.delete(view)
        kept = view.rescued
        self.assertTrue(os.path.exists(kept))
        app.close_tab(app.active)
        self.assertFalse(os.path.exists(kept), 'the copy outlived the tab')

    def test_saving_a_sound_file_does_nothing_whatsoever(self):
        app, view = self.open()
        self.delete(view)
        before = app.message
        self.assertFalse(app.save())
        self.assertFalse(os.path.exists(self.tone), 'ctrl+s put the file back')
        self.assertEqual(app.message, before, 'ctrl+s said something')
        view.close()

    def test_a_file_that_comes_back_clears_the_warning(self):
        app, view = self.open()
        self.delete(view)
        self.assertTrue(view.missing)
        write_tone(self.tone, seconds=3)
        view.check_disk(force=True)
        self.assertFalse(view.missing, 'the warning stayed')
        self.assertIsNone(view.rescued, 'the copy was kept for nothing')
        self.assertAlmostEqual(view.player.duration, 3, places=1,
                               msg='it did not measure the new file')
        self.assertIsNone(view.tab_mark())
        view.close()

    def test_a_file_rewritten_under_us_is_measured_again(self):
        app, view = self.open()
        write_tone(self.tone, seconds=2)
        view.check_disk(force=True)
        self.assertFalse(view.missing)
        self.assertAlmostEqual(view.player.duration, 2, places=1)
        view.close()

    def test_too_big_to_keep_means_no_second_play(self):
        from tide.audio import view as view_mod
        was = view_mod.RESCUE_LIMIT
        view_mod.RESCUE_LIMIT = 10          # anything real is bigger
        try:
            app, view = self.open()
            self.delete(view)
            self.assertTrue(view.missing)
            self.assertIsNone(view.rescued)
            app.render()
            self.assertIn('cannot start again', self.painted(app))
            self.assertTrue(view.lost())
            self.assertFalse(view.toggle(), 'it played a missing file')
            self.assertFalse(view.player.playing)
            view.close()
        finally:
            view_mod.RESCUE_LIMIT = was

    def test_the_directory_going_too_is_survivable(self):
        app, view = self.open()
        view.player.play(0.0)
        shutil.rmtree(self.tmp)
        view.check_disk(force=True)
        app.render()
        self.assertTrue(view.missing)
        self.assertNotIn('Traceback', self.painted(app))
        view.close()

    def test_a_directory_in_its_place_does_not_break_anything(self):
        app, view = self.open()
        os.remove(self.tone)
        os.makedirs(self.tone)
        view.check_disk(force=True)
        app.render()
        self.assertNotIn('Traceback', self.painted(app))
        view.close()


class TestOddFiles(AudioTest):
    def open_named(self, name, data=b''):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as f:
            f.write(data)
        app = self.app()
        view = app.open_file(path)
        app.render()
        return app, view

    def test_an_empty_file(self):
        app, view = self.open_named('empty.wav')
        self.assertTrue(getattr(view, 'is_audio', False))
        self.assertIsNone(view.player.duration)
        self.assertNotIn('Traceback', self.painted(app))
        view.close()

    def test_a_file_that_is_not_really_audio(self):
        app, view = self.open_named('fake.mp3', b'this is text pretending')
        app.handle_key(Key('char', char=' '))
        app.render()
        self.assertNotIn('Traceback', self.painted(app))
        view.close()

    def test_a_name_with_spaces_and_accents(self):
        name = 'a song — with spaces.wav'
        path = os.path.join(self.tmp, name)
        write_tone(path, seconds=2)
        app = self.app()
        view = app.open_file(path)
        app.render()
        self.assertIn('song', self.painted(app))
        self.assertTrue(view.player.play(0.0))
        view.close()

    def test_a_file_we_are_not_allowed_to_read(self):
        path = os.path.join(self.tmp, 'locked.wav')
        write_tone(path, seconds=1)
        os.chmod(path, 0o000)
        try:
            app = self.app()
            view = app.open_file(path)
            app.render()
            self.assertNotIn('Traceback', self.painted(app))
            view.close()
        finally:
            os.chmod(path, 0o644)

    def test_a_symlink_whose_target_disappears(self):
        link = os.path.join(self.tmp, 'link.wav')
        os.symlink(self.tone, link)
        app = self.app()
        view = app.open_file(link)
        view.player.play(0.0)
        os.remove(self.tone)
        view.check_disk(force=True)
        app.render()
        self.assertTrue(view.missing)
        self.assertNotIn('Traceback', self.painted(app))
        view.close()

    def test_seeking_outside_the_file(self):
        app = self.app()
        view = app.open_file(self.tone)
        view.player.seek(-50)
        self.assertEqual(view.player.position(), 0.0)
        view.player.seek(9999)
        self.assertLessEqual(view.player.position(), TONE_SECONDS)
        view.close()


class TestBackends(unittest.TestCase):
    def test_the_ones_that_can_seek_come_first(self):
        from tide.audio.player import BACKENDS
        names = [b.name for b in BACKENDS]
        self.assertLess(names.index('ffplay'), names.index('afplay'))
        self.assertLess(names.index('ffmpeg|aplay'), names.index('aplay'))
        first_plain = min(i for i, b in enumerate(BACKENDS) if not b.seek)
        last_seeking = max(i for i, b in enumerate(BACKENDS) if b.seek)
        self.assertLess(last_seeking, first_plain,
                        'a player that cannot seek is being preferred')

    def test_a_backend_that_needs_two_programs_waits_for_both(self):
        from tide.audio import player as mod
        folder = tempfile.mkdtemp(prefix='tide-audio-needs-')
        was = os.environ.get('PATH', '')
        try:
            os.environ['PATH'] = folder
            for name in ('ffmpeg',):        # ffmpeg alone is not enough
                path = os.path.join(folder, name)
                with open(path, 'w') as f:
                    f.write('#!/bin/sh\nexit 0\n')
                os.chmod(path, 0o755)
            mod.forget()
            self.assertIsNone(mod.backend('x.mp3'))
            path = os.path.join(folder, 'aplay')
            with open(path, 'w') as f:
                f.write('#!/bin/sh\nexit 0\n')
            os.chmod(path, 0o755)
            mod.forget()
            self.assertEqual(mod.backend('x.mp3').name, 'ffmpeg|aplay')
        finally:
            os.environ['PATH'] = was
            mod.forget()
            shutil.rmtree(folder, ignore_errors=True)

    def test_a_pipeline_is_paused_as_a_whole(self):
        """A shell running two programs must stop, not just the shell."""
        from tide.audio import player as mod
        folder = tempfile.mkdtemp(prefix='tide-audio-pipe-')
        was = os.environ.get('PATH', '')
        try:
            os.environ['PATH'] = folder
            for name in ('ffmpeg', 'aplay'):
                path = os.path.join(folder, name)
                with open(path, 'w') as f:
                    f.write('#!/bin/sh\nexec /bin/sleep 20\n')
                os.chmod(path, 0o755)
            mod.forget()
            tone = write_tone(os.path.join(folder, 'x.wav'), seconds=2)
            p = mod.Player(tone)
            self.assertEqual(p.backend.name, 'ffmpeg|aplay')
            p.play(0.0)
            time.sleep(0.3)
            group = os.getpgid(p._process.pid)
            self.assertNotEqual(group, os.getpgid(0), 'not its own group')
            p.pause()
            p.resume()
            self.assertTrue(p.playing)
            child = p._process
            p.stop()
            time.sleep(0.2)
            self.assertIsNotNone(child.poll(), 'the pipeline is still running')
        finally:
            os.environ['PATH'] = was
            mod.forget()
            shutil.rmtree(folder, ignore_errors=True)


class TestThePipeline(unittest.TestCase):
    """What ffmpeg is asked to produce, and what happens when it fails."""

    def setUp(self):
        self.bin = tempfile.mkdtemp(prefix='tide-pipe-bin-')
        self.tmp = tempfile.mkdtemp(prefix='tide-pipe-')
        self.was_path = os.environ.get('PATH', '')
        os.environ['PATH'] = self.bin
        self.tone = write_tone(os.path.join(self.tmp, 'tone.wav'), seconds=4)
        player_mod.forget()

    def tearDown(self):
        os.environ['PATH'] = self.was_path
        player_mod.forget()
        shutil.rmtree(self.bin, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def script(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, 'w') as f:
            f.write('#!/bin/sh\n%s\n' % body)
        os.chmod(path, 0o755)
        player_mod.forget()

    def test_it_pipes_samples_not_a_headerless_wav(self):
        self.script('ffmpeg', 'exec /bin/sleep 20')
        self.script('aplay', 'exec /bin/sleep 20')
        p = player_mod.Player(self.tone)
        self.assertEqual(p.backend.name, 'ffmpeg|aplay')
        feeder, sink = p.backend.build(self.tone, 0, 1.0)
        self.assertIn('s16le', feeder, 'the decoder is not making raw samples')
        self.assertNotIn('wav', feeder, 'a wav down a pipe has no length')
        self.assertIn('-t', sink)
        self.assertIn('raw', sink, 'the sink was not told what it is getting')
        for flag in ('-r', '-c'):
            self.assertIn(flag, sink, 'the sink was not told the format')

    def test_a_sink_that_exits_happily_on_nothing_is_still_a_failure(self):
        # exactly the shape of the bug: the decoder dies, the sink reads an
        # empty pipe and exits 0, and it used to look like a finished file
        self.script('ffmpeg', 'echo "ffmpeg: no such stream" >&2; exit 1')
        self.script('aplay', '/bin/cat > /dev/null; exit 0')
        p = player_mod.Player(self.tone)
        try:
            p.play(0.0)
            for _ in range(30):
                if p.finished():
                    break
                time.sleep(0.05)
            self.assertTrue(p.finished())
            self.assertLess(p.position(), p.duration - 1,
                            'the bar jumped to the end of a file never played')
            self.assertIsNotNone(p.error, 'it failed silently')
            self.assertIn('ffmpeg', p.error, 'it did not say who failed')
        finally:
            p.stop()

    def test_both_halves_are_stopped_together(self):
        self.script('ffmpeg', 'exec /bin/sleep 20')
        self.script('aplay', 'exec /bin/sleep 20')
        p = player_mod.Player(self.tone)
        p.play(0.0)
        time.sleep(0.3)
        feeder, sink = p._feeder, p._process
        self.assertTrue(p.pause())
        self.assertTrue(p.resume())
        p.stop()
        time.sleep(0.3)
        self.assertIsNotNone(feeder.poll(), 'the decoder is still running')
        self.assertIsNotNone(sink.poll(), 'the sink is still running')

    def test_the_check_command_reports_a_broken_setup(self):
        from tide.audio import check
        self.script('ffmpeg', 'echo "ffmpeg: broken" >&2; exit 1')
        self.script('aplay', '/bin/cat > /dev/null; exit 0')
        was, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = check.run(self.tone)
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = was
        self.assertEqual(code, 1, printed)
        self.assertIn('ffmpeg|aplay', printed)
        self.assertIn('it stopped after', printed)
        self.assertIn('broken', printed, 'it did not pass on what was said')

    def test_the_check_command_with_nothing_installed(self):
        from tide.audio import check
        was, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = check.run(None)
            printed = sys.stdout.getvalue()
        finally:
            sys.stdout = was
        self.assertEqual(code, 1)
        self.assertIn('nothing can play sound here', printed)
        self.assertIn('ffmpeg', printed)


class TestStress(AudioTest):
    def test_a_hundred_starts_and_stops_leak_nothing(self):
        app = self.app()
        view = app.open_file(self.tone)
        before = open_fds()
        for i in range(100):
            view.player.play(float(i % 5))
            view.player.pause()
            view.player.resume()
            view.player.seek(float(i % 4))
        view.player.stop()
        time.sleep(0.3)
        self.assertLessEqual(open_fds(), before + 4, 'file handles are leaking')
        leftovers = [f for f in os.listdir(tempfile.gettempdir())
                     if f.startswith('tide-play-') or f.startswith('tide-kept-')]
        view.close()
        self.assertEqual(leftovers, [], 'temporary files are piling up')

    def test_opening_and_closing_many_tabs(self):
        app = self.app()
        before = open_fds()
        for _ in range(30):
            app.open_file(self.tone)
            app.editors[app.active].player.play(0.0)
            app.close_tab(app.active)
        time.sleep(0.3)
        self.assertLessEqual(open_fds(), before + 4, 'file handles are leaking')

    def test_two_tabs_play_without_treading_on_each_other(self):
        other = os.path.join(self.tmp, 'other.wav')
        write_tone(other, seconds=3)
        app = self.app()
        one = app.open_file(self.tone)
        two = app.open_file(other)
        one.player.play(0.0)
        two.player.play(1.0)
        self.assertTrue(one.player.playing and two.player.playing)
        self.assertNotEqual(one.player._process.pid, two.player._process.pid)
        first = one.player._process
        app.close_tab(0)
        time.sleep(0.2)
        self.assertIsNotNone(first.poll(), 'closing one did not stop it')
        self.assertTrue(two.player.playing, 'closing one stopped the other')
        two.close()

    def test_the_player_being_killed_from_outside(self):
        app = self.app()
        view = app.open_file(self.tone)
        view.player.play(0.0)
        os.kill(view.player._process.pid, 9)
        time.sleep(0.3)
        app.render()
        self.assertTrue(view.player.finished())
        self.assertFalse(view.player.playing)
        self.assertNotIn('Traceback', self.painted(app))
        self.assertTrue(view.player.play(0.0), 'it could not be started again')
        view.close()

    def test_the_player_program_disappearing(self):
        app = self.app()
        view = app.open_file(self.tone)
        os.remove(os.path.join(self.bin, 'ffplay'))
        started = view.player.play(0.0)
        app.render()
        self.assertFalse(started)
        self.assertIsNotNone(view.player.error)
        self.assertNotIn('Traceback', self.painted(app))
        view.close()

    def test_hammering_the_buttons(self):
        app = self.app()
        view = app.open_file(self.tone)
        app.render()
        px, _p2, py = view.play_span
        bx1, bx2, by = view.bar_span
        sx, _s2, sy = view.speed_span
        for i in range(60):
            app.handle_mouse(Mouse('press', px + 2, py))
            app.handle_mouse(Mouse('press', bx1 + (i % (bx2 - bx1)), by))
            app.handle_mouse(Mouse('press', sx + 2, sy))
            app.render()
        self.assertNotIn('Traceback', self.painted(app))
        self.assertIn(view.player.rate, SPEEDS_SEEN)
        view.close()

    def test_quitting_while_it_plays(self):
        app = self.app()
        view = app.open_file(self.tone)
        view.player.play(0.0)
        process = view.player._process
        for tab in app.editors:
            if hasattr(tab, 'close'):
                tab.close()
        time.sleep(0.2)
        self.assertIsNotNone(process.poll(), 'the sound outlived the editor')

    def test_deleting_the_file_a_hundred_times_over(self):
        app = self.app()
        view = app.open_file(self.tone)
        for _ in range(25):
            os.remove(self.tone)
            view.check_disk(force=True)
            self.assertTrue(view.missing)
            write_tone(self.tone, seconds=1)
            view.check_disk(force=True)
            self.assertFalse(view.missing)
        app.render()
        self.assertNotIn('Traceback', self.painted(app))
        leftovers = [f for f in os.listdir(tempfile.gettempdir())
                     if f.startswith('tide-kept-')]
        view.close()
        self.assertEqual(leftovers, [], 'kept copies are piling up')


SPEEDS_SEEN = [0.5, 1.0, 1.25, 1.5, 2.0]


class TestTurningItOn(unittest.TestCase):
    """The setting only ever moves because you moved it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-gate-')
        self.cfg = tempfile.mkdtemp(prefix='tide-gate-cfg-')
        self.bin = tempfile.mkdtemp(prefix='tide-gate-bin-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.was_path = os.environ.get('PATH', '')
        os.environ['PATH'] = self.bin
        player_mod.forget()

    def tearDown(self):
        os.environ['PATH'] = self.was_path
        os.environ.pop('TIDE_CONFIG_HOME', None)
        player_mod.forget()
        for folder in (self.tmp, self.cfg, self.bin):
            shutil.rmtree(folder, ignore_errors=True)

    def provide(self, *names):
        for name in names:
            path = os.path.join(self.bin, name)
            with open(path, 'w') as f:
                f.write('#!/bin/sh\nexec /bin/sleep 30\n')
            os.chmod(path, 0o755)
        player_mod.forget()

    def app(self):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(90, 20)
        app.show_term = False
        return app

    def stored(self):
        from tide import settings as store
        return store.load()['audio']

    def turn_on(self, app, where='l'):
        """Ask for sound, and answer the where-should-it-come-out panel."""
        from tide.audio.setup import AudioSetup
        app.set_setting('audio', True)
        if isinstance(app.overlay, AudioSetup):
            panel = app.overlay
            panel.on_key(Key('char', where))
            if app.overlay is panel and where == 'l':
                app.overlay = None
        return app.overlay

    # -- nothing installed
    def test_with_nothing_installed_it_refuses_and_says_what_to_get(self):
        app = self.app()
        self.turn_on(app)
        self.assertFalse(app.settings['audio'])
        self.assertFalse(self.stored())
        self.assertIsNone(app.overlay, 'it asked a question it cannot honour')
        self.assertIn('ffmpeg', app.message)

    # -- the good case
    def test_with_ffplay_it_just_turns_on(self):
        self.provide('ffplay')
        app = self.app()
        self.turn_on(app)
        self.assertTrue(app.settings['audio'])
        self.assertTrue(self.stored())
        self.assertIsNone(app.overlay, 'it asked when it did not need to')
        self.assertIn('ffplay', app.message)

    def test_mpv_counts_as_the_good_case_too(self):
        self.provide('mpv')
        app = self.app()
        self.turn_on(app)
        self.assertTrue(app.settings['audio'])
        self.assertIsNone(app.overlay)

    def test_ffmpeg_with_a_sink_counts_as_the_good_case(self):
        self.provide('ffmpeg', 'aplay')
        app = self.app()
        self.turn_on(app)
        self.assertTrue(app.settings['audio'])
        self.assertIsNone(app.overlay)

    # -- only something plain
    def test_with_only_a_plain_player_it_asks_first(self):
        self.provide('afplay')
        app = self.app()
        self.turn_on(app)
        self.assertIsNotNone(app.overlay, 'it did not ask')
        self.assertFalse(app.settings['audio'], 'it turned on before being told')
        self.assertFalse(self.stored())
        self.assertIn('afplay', app.overlay.question)
        self.assertIn('ffmpeg', app.overlay.question)

    def test_saying_you_will_install_it_leaves_it_off(self):
        self.provide('afplay')
        app = self.app()
        self.turn_on(app)
        app.overlay.on_no()
        self.assertFalse(app.settings['audio'])
        self.assertFalse(self.stored())
        self.assertIn('install', app.message)

    def test_saying_use_it_anyway_turns_it_on(self):
        self.provide('afplay')
        app = self.app()
        self.turn_on(app)
        app.overlay.on_yes()
        self.assertTrue(app.settings['audio'])
        self.assertTrue(self.stored())
        self.assertIn('afplay', app.message)

    def test_escaping_the_question_leaves_it_off(self):
        self.provide('afplay')
        app = self.app()
        self.turn_on(app)
        app.overlay.on_key(Key('escape'))
        self.assertFalse(app.settings['audio'])
        self.assertFalse(self.stored())

    def test_the_question_comes_back_to_the_settings_panel(self):
        from tide.overlay import SettingsPanel
        self.provide('afplay')
        app = self.app()
        app.open_settings()
        self.turn_on(app)
        self.assertNotIsInstance(app.overlay, SettingsPanel)
        app.overlay.on_key(Key('char', char='y'))
        self.assertIsInstance(app.overlay, SettingsPanel,
                              'it did not put the settings back')
        self.assertTrue(app.settings['audio'])

    # -- turning it off, and staying put
    def test_turning_it_off_never_asks(self):
        self.provide('afplay')
        app = self.app()
        self.turn_on(app)
        app.overlay.on_yes()
        app.overlay = None
        app.set_setting('audio', False)
        self.assertIsNone(app.overlay)
        self.assertFalse(app.settings['audio'])
        self.assertFalse(self.stored())

    def test_a_hand_written_setting_is_believed(self):
        from tide import settings as store
        folder = os.path.join(self.cfg, 'tide')
        os.makedirs(folder)
        with open(os.path.join(folder, 'settings.json'), 'w') as f:
            f.write('{"audio": true}')
        self.assertTrue(store.load()['audio'])
        app = self.app()
        self.assertTrue(app.settings['audio'], 'it overrode what was asked for')

    def test_it_does_not_move_when_other_settings_do(self):
        self.provide('ffplay')
        app = self.app()
        for key, value in (('theme', 'light'), ('tab_width', 8),
                           ('autosave', False), ('show_tree', False)):
            app.set_setting(key, value)
        self.assertFalse(app.settings['audio'])
        self.assertFalse(self.stored())

    def test_opening_a_sound_file_does_not_turn_it_on(self):
        self.provide('ffplay')
        app = self.app()
        tone = write_tone(os.path.join(self.tmp, 'tone.wav'), seconds=1)
        app.open_file(tone)
        self.assertFalse(app.settings['audio'])
        self.assertFalse(any(getattr(t, 'is_audio', False) for t in app.editors))

    def test_fifty_goes_and_it_is_still_exactly_what_was_chosen(self):
        self.provide('afplay')                  # the case that asks
        app = self.app()
        want = False
        for i in range(50):
            if i % 3 == 0:
                app.set_setting('audio', False)
                want = False
            else:
                self.turn_on(app)
                if app.overlay is not None:
                    if i % 2:
                        app.overlay.on_yes()
                        want = True
                    else:
                        app.overlay.on_no()
                        want = False
                    app.overlay = None
            self.assertEqual(app.settings['audio'], want, 'drifted at step %d' % i)
            self.assertEqual(self.stored(), want, 'the file drifted at step %d' % i)

    def test_the_same_in_every_kind_of_machine(self):
        for tools, asks, ends_on in ((('ffplay',), False, True),
                                     (('mpv',), False, True),
                                     (('afplay',), True, True),
                                     ((), False, False)):
            shutil.rmtree(self.bin, ignore_errors=True)
            os.makedirs(self.bin)
            self.provide(*tools)
            app = self.app()
            app.settings['audio'] = False
            self.turn_on(app)
            self.assertEqual(app.overlay is not None, asks,
                             'wrong question for %s' % (tools,))
            if app.overlay is not None:
                app.overlay.on_yes()
                app.overlay = None
            self.assertEqual(app.settings['audio'], ends_on,
                             'wrong end state for %s' % (tools,))


class TestSurvey(unittest.TestCase):
    def test_it_sorts_players_into_full_and_plain(self):
        folder = tempfile.mkdtemp(prefix='tide-survey-')
        was = os.environ.get('PATH', '')
        try:
            os.environ['PATH'] = folder
            player_mod.forget()
            self.assertEqual(audio.survey(), (None, None))
            for name, expected in (('aplay', (None, 'aplay')),
                                   ('ffplay', ('ffplay', 'aplay'))):
                path = os.path.join(folder, name)
                with open(path, 'w') as f:
                    f.write('#!/bin/sh\nexit 0\n')
                os.chmod(path, 0o755)
                player_mod.forget()
                self.assertEqual(audio.survey(), expected)
            self.assertTrue(audio.available())
        finally:
            os.environ['PATH'] = was
            player_mod.forget()
            shutil.rmtree(folder, ignore_errors=True)


class TestTheWherePanel(unittest.TestCase):
    """The panel that asks where the sound should come out."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-where-')
        self.cfg = tempfile.mkdtemp(prefix='tide-where-cfg-')
        self.bin = tempfile.mkdtemp(prefix='tide-where-bin-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.was_path = os.environ.get('PATH', '')
        os.environ['PATH'] = self.bin
        player_mod.forget()
        self.sink = None

    def tearDown(self):
        if self.sink is not None:
            self.sink.stop()
        os.environ['PATH'] = self.was_path
        os.environ.pop('TIDE_CONFIG_HOME', None)
        player_mod.forget()
        for folder in (self.tmp, self.cfg, self.bin):
            shutil.rmtree(folder, ignore_errors=True)

    def app(self):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(100, 26)
        app.show_term = False
        return app

    def panel(self, app):
        from tide.audio.setup import AudioSetup
        app.set_setting('audio', True)
        self.assertIsInstance(app.overlay, AudioSetup, 'no panel appeared')
        return app.overlay

    def painted(self, app, panel):
        from tide.term import Rect
        app.screen = Screen(100, 26)
        panel.render(app.screen, Rect(0, 0, 100, 26))
        return '\n'.join(''.join(c[0] or ' ' for c in row)
                          for row in app.screen.cells)

    def start_sink(self, port):
        import threading
        from tide.audio.remote import Sink
        self.sink = _Sink(port)
        self.sink.start()
        for _ in range(50):
            from tide.audio.remote import reachable
            if reachable(port, 0.2)[0]:
                return
            time.sleep(0.05)
        raise AssertionError('the test sink never came up')

    # -- the choice itself
    def test_it_offers_both_places(self):
        panel = self.panel(self.app())
        shown = self.painted(self.app(), panel)
        self.assertIn('Where should the sound come out', shown)
        self.assertIn('this machine', shown)
        self.assertIn('sitting at', shown)

    def test_local_is_exactly_what_it_always_was(self):
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('char', 'l'))
        self.assertFalse(app.settings['audio'], 'nothing here can play')
        self.assertIn('ffmpeg', app.message)
        self.assertEqual(app.settings['audio_sink_port'], 0)

    def test_escape_changes_nothing(self):
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('escape'))
        self.assertFalse(app.settings['audio'])
        self.assertEqual(app.settings['audio_sink_port'], 0)

    # -- the ssh side
    def test_the_ssh_step_says_what_to_run_and_both_ssh_lines(self):
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('char', 's'))
        shown = self.painted(app, panel)
        self.assertIn('tide --audio-sink', shown)
        self.assertIn('you@this-machine', shown)
        self.assertIn('already in your ssh config', shown,
                      'no hint about the bare host name')
        self.assertIn('RemoteForward', shown)
        self.assertIn('port: 47000', shown)

    def test_a_port_nothing_answers_on_leaves_it_off(self):
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('char', 's'))
        panel.port = '47999'
        panel.on_key(Key('enter'))
        self.assertFalse(app.settings['audio'], 'it turned on with no sink')
        self.assertEqual(app.settings['audio_sink_port'], 0)
        self.assertIn('nothing answered', self.painted(app, panel))

    def test_a_port_with_a_sink_on_it_turns_sound_on_and_is_remembered(self):
        from tide import settings as store
        port = 47311
        self.start_sink(port)
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('char', 's'))
        panel.port = ''
        for digit in str(port):
            panel.on_key(Key('char', digit))
        panel.on_key(Key('enter'))
        self.assertTrue(app.settings['audio'], 'it did not turn on')
        self.assertEqual(app.settings['audio_sink_port'], port)
        self.assertEqual(store.load()['audio_sink_port'], port,
                         'the sink was not written down for next time')
        self.assertTrue(store.load()['audio'])

    def test_a_later_session_uses_the_sink_without_asking(self):
        port = 47312
        self.start_sink(port)
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('char', 's'))
        panel.port = str(port)
        panel.on_key(Key('enter'))
        again = self.app()                      # as if tide were started afresh
        self.assertTrue(again.settings['audio'])
        tone = write_tone(os.path.join(self.tmp, 'tone.wav'), seconds=2)
        view = again.open_file(tone)
        from tide.audio.remote import Link
        self.assertIsInstance(view.player, Link,
                              'it went back to playing on this machine')
        view.close()

    def test_forgetting_the_sink(self):
        port = 47313
        self.start_sink(port)
        app = self.app()
        panel = self.panel(app)
        panel.on_key(Key('char', 's'))
        panel.port = str(port)
        panel.on_key(Key('enter'))
        panel = self.panel(app) if not app.settings['audio'] else None
        app.settings['audio'] = False           # turn it on again to reach the panel
        panel = self.panel(app)
        panel.on_key(Key('char', 's'))
        panel.on_key(Key('char', 'f'))
        self.assertFalse(app.settings['audio'])
        self.assertEqual(app.settings['audio_sink_port'], 0)


class _Sink(object):
    """The sink, on a thread, for the tests to talk to."""

    def __init__(self, port):
        self.port = port
        self.thread = None
        self.sink = None

    def start(self):
        import threading
        from tide.audio.remote import Sink
        self.sink = Sink(self.port)
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def _run(self):
        try:
            self.sink.serve()
        except Exception:
            pass

    def stop(self):
        import socket
        try:                                    # nudge it out of select()
            socket.create_connection(('127.0.0.1', self.port), 0.2).close()
        except Exception:
            pass


if __name__ == '__main__':
    unittest.main(verbosity=2)
