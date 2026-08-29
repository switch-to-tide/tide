"""Do edits survive the window closing, a signal, or an instant quit?

Every test types into a real IDE on a pty and then ends the session in some
abrupt way, with no pause for auto-save's timer, then checks the file on disk.
"""

import os
import shutil
import signal
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import CTRL, ENTER, ESC, F2, F4, Session

ORIGINAL = 'line one\nline two\nline three\n'


class DurabilityTest(unittest.TestCase):
    args = ()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-durable-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        with open(self.path, 'w') as f:
            f.write(ORIGINAL)
        self.other = os.path.join(self.tmp, 'other.txt')
        with open(self.other, 'w') as f:
            f.write('second file\n')
        self.s = Session(list(self.args) + [self.path, self.tmp],
                         cols=90, rows=24, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, path=None):
        with open(path or self.path) as f:
            return f.read()

    def type_marker(self, text='EDITED '):
        """Type at the very start of the file, without pausing afterwards."""
        self.s.send_raw(text)
        return text


class TestQuickExits(DurabilityTest):
    def test_quit_immediately_after_typing(self):
        self.type_marker()
        self.s.send_raw(CTRL('q'))          # no pause at all
        self.assertTrue(self.s.wait_exit(), 'the app did not exit')
        self.assertEqual(self.read(), 'EDITED ' + ORIGINAL)

    def test_window_closed_sends_sighup(self):
        self.type_marker('HUP ')
        time.sleep(0.15)                    # the keystrokes land, timer has not
        self.s.signal(signal.SIGHUP)
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), 'HUP ' + ORIGINAL)

    def test_sigterm(self):
        self.type_marker('TERM ')
        time.sleep(0.15)
        self.s.signal(signal.SIGTERM)
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), 'TERM ' + ORIGINAL)

    def test_terminal_destroyed_gives_stdin_eof(self):
        self.type_marker('EOF ')
        time.sleep(0.15)
        self.s.close_master()               # the terminal window is gone
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), 'EOF ' + ORIGINAL)

    def test_sigkill_loses_the_edit(self):
        """The honest boundary: nothing survives SIGKILL before the timer."""
        self.type_marker('KILLED ')
        time.sleep(0.15)
        self.s.signal(signal.SIGKILL)
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), ORIGINAL)

    def test_burst_of_typing_then_instant_quit(self):
        burst = ''.join('x%d ' % i for i in range(60))
        self.s.send_raw(burst)
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), burst + ORIGINAL)

    def test_paste_then_instant_quit(self):
        pasted = 'pasted line A\npasted line B\n'
        self.s.send_raw(ESC + '[200~' + pasted + ESC + '[201~')
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), pasted + ORIGINAL)

    def test_two_files_edited_then_instant_quit(self):
        self.type_marker('FIRST ')
        self.s.key(CTRL('p'), settle=0.3)
        self.s.type('other', settle=0.3)
        self.s.key(ENTER, settle=0.4)
        self.s.send_raw('SECOND ')
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), 'FIRST ' + ORIGINAL)
        self.assertEqual(self.read(self.other), 'SECOND second file\n')

    def test_edit_then_close_tab_then_quit(self):
        self.type_marker('CLOSED ')
        self.s.send_raw(CTRL('w'))          # close the tab straight away
        time.sleep(0.4)
        self.assertEqual(self.read(), 'CLOSED ' + ORIGINAL)
        self.assertNotIn('before closing?', self.s.pump(0.3) and self.s.screen())

    def test_edit_then_switch_to_terminal_and_quit(self):
        self.type_marker('SWITCHED ')
        self.s.key(F2, settle=0.6)          # full-size terminal takes over
        self.s.type('exit' + ENTER, settle=0.8)   # closes it, back to the editor
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), 'SWITCHED ' + ORIGINAL)

    def test_undo_before_quitting_is_what_gets_saved(self):
        self.type_marker('OOPS')            # one typing run = one undo step
        time.sleep(1.1)                     # auto-saved with the typo
        self.assertEqual(self.read(), 'OOPS' + ORIGINAL)
        self.s.send_raw(CTRL('z'))
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), ORIGINAL, 'the undo must reach disk too')


class TestUndoAcrossAutoSave(DurabilityTest):
    """Auto-save must not cost you your undo history."""

    def test_undo_still_works_after_several_saves(self):
        self.s.send_raw('FIRST')
        time.sleep(1.1)                      # auto-saved
        self.s.pump(0.3)
        self.s.send_raw('SECOND')
        time.sleep(1.1)                      # auto-saved again
        self.s.pump(0.3)
        self.assertEqual(self.read(), 'FIRSTSECOND' + ORIGINAL)
        self.s.key(CTRL('z'))                # undoes the second typing run
        self.assertIn('FIRSTline one', self.s.screen())
        self.assertNotIn('SECOND', self.s.screen())
        self.s.key(CTRL('z'))
        time.sleep(1.1)
        self.s.pump(0.3)
        self.assertEqual(self.read(), ORIGINAL, 'undo did not reach back past the saves')

    def test_redo_after_undo(self):
        self.s.send_raw('ADDED')
        time.sleep(1.1)
        self.s.pump(0.3)
        self.s.key(CTRL('z'))
        self.s.key(CTRL('y'))
        time.sleep(1.1)
        self.s.pump(0.3)
        self.assertEqual(self.read(), 'ADDED' + ORIGINAL)

    def test_copy_and_paste_with_autosave_on(self):
        self.s.key(CTRL('c'))                # no selection: the whole line
        self.s.key('\x1b[F')                 # end of line
        self.s.key(ENTER)
        self.s.key(CTRL('v'))
        time.sleep(1.1)
        self.s.pump(0.3)
        self.assertEqual(self.read().count('line one'), 2)


class TestManualSaveDurability(DurabilityTest):
    args = ('--no-autosave',)

    def test_quit_warns_and_saving_works(self):
        self.type_marker('MANUAL ')
        self.s.key(CTRL('q'), settle=0.4)
        screen = self.s.screen()
        self.assertIn('Unsaved changes', screen)
        self.assertIn('loses them', screen)
        self.s.send_raw('s')
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), 'MANUAL ' + ORIGINAL)

    def test_quitting_anyway_keeps_the_file_as_it_was(self):
        self.type_marker('DISCARD ')
        self.s.key(CTRL('q'), settle=0.4)
        self.s.send_raw('q')
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), ORIGINAL)

    def test_cancelling_stays_in_tide(self):
        self.type_marker('STAY ')
        self.s.key(CTRL('q'), settle=0.4)
        self.s.send_raw('c')
        self.s.pump(0.5)
        self.assertTrue(self.s.alive(), 'cancel quit anyway')
        self.assertNotIn('Unsaved changes', self.s.screen())

    def test_sighup_does_not_write_when_autosave_is_off(self):
        self.type_marker('NOPE ')
        time.sleep(0.2)
        self.s.signal(signal.SIGHUP)
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(self.read(), ORIGINAL)


class TestWhatLandsOnDisk(DurabilityTest):
    """The bytes written must be exactly the buffer, nothing rounded off."""

    def test_edits_are_written_verbatim(self):
        self.s.key(ESC + '[F')                          # end of line 1
        self.s.type('  trailing spaces here   ')        # trailing blanks are kept
        self.s.send_raw(ENTER + 'second')
        time.sleep(1.2)
        self.s.pump(0.3)
        self.assertEqual(
            self.read(),
            'line one  trailing spaces here   \nsecond\nline two\nline three\n')

    def test_tab_key_inserts_the_indent_unit(self):
        self.s.key(ESC + '[F')
        self.s.send_raw(ENTER)
        self.s.send_raw('\tindented')                   # tab -> spaces, as configured
        time.sleep(1.2)
        self.s.pump(0.3)
        self.assertIn('\n    indented\n', self.read())

    def test_unicode_survives_the_round_trip(self):
        text = u'café 漢字 \U0001f600'
        self.s.send_raw(text)
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        with open(self.path, 'rb') as f:
            raw = f.read()
        self.assertEqual(raw.decode('utf-8'), text + ORIGINAL)

    def test_file_mode_is_kept(self):
        os.chmod(self.path, 0o750)
        self.type_marker('MODE ')
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        import stat as _stat
        self.assertEqual(_stat.S_IMODE(os.stat(self.path).st_mode), 0o750)
        self.assertEqual(self.read(), 'MODE ' + ORIGINAL)

    def test_no_temp_files_are_left(self):
        self.type_marker('TMP ')
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual([f for f in os.listdir(self.tmp) if 'tide-tmp' in f], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
