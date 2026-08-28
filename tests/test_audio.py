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


if __name__ == '__main__':
    unittest.main(verbosity=2)
