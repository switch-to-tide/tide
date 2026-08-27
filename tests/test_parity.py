"""Save and history behaviour, checked against what VS Code documents doing.

Each test names the behaviour it mirrors.  Where we deliberately differ, the
test says so, so the difference is a decision on record rather than a bug.
"""

import io
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import CTRL, ENTER, Session
from tide.app import App
from tide.buffer import Document, StaleFileError

ORIGINAL = 'one\ntwo\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-parity-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        with open(self.path, 'w') as f:
            f.write(ORIGINAL)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, path=None):
        with open(path or self.path, 'rb') as f:
            return f.read()

    def app(self, **kw):
        app = App(root=self.tmp, paths=[self.path], out=io.StringIO())
        for key, value in kw.items():
            setattr(app, key, value)
        return app


class TestAutoSaveSemantics(Base):
    """files.autoSave = afterDelay."""

    def test_it_waits_for_quiet_rather_than_saving_each_keystroke(self):
        app = self.app(autosave_delay=60.0)
        app.editor.doc.insert('a')
        app.autosave_tick()
        self.assertEqual(self.read(), ORIGINAL.encode(), 'saved before the delay')
        app.autosave_delay = 0.0
        app.autosave_tick()
        self.assertEqual(self.read(), b'aone\ntwo\n')

    def test_untitled_buffers_are_never_auto_saved(self):
        app = self.app(autosave_delay=0.0)
        app.new_file()
        app.editor.doc.insert('scratch')
        app.autosave_tick()
        self.assertTrue(app.editor.doc.dirty)
        self.assertEqual(sorted(os.listdir(self.tmp)), ['doc.txt'])

    def test_with_auto_save_off_only_an_explicit_save_writes(self):
        app = self.app(autosave=False, autosave_delay=0.0)
        app.editor.doc.insert('x')
        app.autosave_tick()
        self.assertEqual(self.read(), ORIGINAL.encode())
        app.save()
        self.assertEqual(self.read(), b'xone\ntwo\n')

    def test_saving_an_unchanged_file_does_not_rewrite_it(self):
        # VS Code does nothing when you save an editor that is not dirty
        app = self.app()
        before = os.stat(self.path).st_mtime_ns
        time.sleep(0.01)
        app.save()
        self.assertEqual(os.stat(self.path).st_mtime_ns, before,
                         'a clean save touched the file')


class TestDirtyState(Base):
    """The dot on the tab, and what clears it."""

    def test_typing_marks_dirty_and_saving_clears_it(self):
        app = self.app(autosave=False)
        self.assertFalse(app.editor.doc.dirty)
        app.editor.doc.insert('x')
        self.assertTrue(app.editor.doc.dirty)
        app.save()
        self.assertFalse(app.editor.doc.dirty)

    def test_undoing_back_to_the_saved_state_clears_it(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('x')
        app.editor.doc.undo()
        self.assertFalse(app.editor.doc.dirty)

    def test_undo_then_a_different_edit_stays_dirty(self):
        app = self.app(autosave=False)
        doc = app.editor.doc
        doc.insert('A')
        app.save()
        doc.undo()
        doc.insert('B')
        self.assertTrue(doc.dirty)
        app.save()
        self.assertEqual(self.read(), b'Bone\ntwo\n')


class TestSaveConflicts(Base):
    """VS Code: "the content on disk is newer" - it refuses and offers Compare."""

    def outside_write(self, text='THEIRS\n'):
        time.sleep(0.01)
        with open(self.path, 'w') as f:
            f.write(text)

    def test_a_stale_save_is_refused(self):
        doc = Document(self.path)
        doc.insert('mine ')
        self.outside_write()
        with self.assertRaises(StaleFileError):
            doc.save()
        self.assertEqual(self.read(), b'THEIRS\n')

    def test_the_user_can_still_overwrite(self):
        doc = Document(self.path)
        doc.insert('mine ')
        self.outside_write()
        doc.save(force=True)
        self.assertEqual(self.read(), b'mine one\ntwo\n')

    def test_manual_save_asks_before_overwriting(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        self.outside_write()
        app.save()
        self.assertIsNotNone(app.overlay, 'no question asked before clobbering')
        self.assertEqual(self.read(), b'THEIRS\n')
        app.overlay.on_yes()
        self.assertEqual(self.read(), b'mine one\ntwo\n')

    def test_auto_save_never_clobbers_an_external_change(self):
        app = self.app(autosave_delay=0.0)
        app.editor.doc.insert('mine ')
        self.outside_write()
        app.autosave_tick()
        self.assertEqual(self.read(), b'THEIRS\n')
        self.assertTrue(app.editor.doc.autosave_blocked)

    def test_our_own_save_is_not_mistaken_for_an_external_change(self):
        app = self.app(autosave_delay=0.0)
        for i in range(5):
            app.editor.doc.insert('%d ' % i)
            app.autosave_tick()
        self.assertFalse(app.editor.doc.autosave_blocked)
        self.assertEqual(self.read(), b'0 1 2 3 4 one\ntwo\n')

    def test_reloading_clears_the_conflict(self):
        app = self.app(autosave_delay=0.0)
        app.editor.doc.insert('mine ')
        self.outside_write()
        app.autosave_tick()
        app.editor.doc.reload()
        app.editor.doc.autosave_blocked = False
        self.assertEqual(app.editor.doc.text(), 'THEIRS\n')
        app.editor.doc.cursor = (0, 0)
        app.editor.doc.insert('now mine ')
        app.autosave_tick()
        self.assertEqual(self.read(), b'now mine THEIRS\n')


class TestContentIsUntouched(Base):
    """VS Code adds nothing on save unless you ask (insertFinalNewline etc. off)."""

    def test_no_trailing_newline_is_added(self):
        with open(self.path, 'w') as f:
            f.write('no newline at the end')
        doc = Document(self.path)
        doc.insert('x')
        doc.save()
        self.assertEqual(self.read(), b'xno newline at the end')

    def test_trailing_whitespace_is_kept(self):
        with open(self.path, 'w') as f:
            f.write('trailing   \nspaces\t\n')
        doc = Document(self.path)
        doc.cursor = doc.end_pos()
        doc.insert('end')
        doc.save()
        self.assertEqual(self.read(), b'trailing   \nspaces\t\nend')

    def test_line_endings_are_preserved(self):
        with open(self.path, 'wb') as f:
            f.write(b'one\r\ntwo\r\n')
        doc = Document(self.path)
        doc.cursor = (1, 3)
        doc.insert('\nthree')
        doc.save()
        self.assertEqual(self.read(), b'one\r\ntwo\r\nthree\r\n')


class TestUndoParity(Base):
    """Linear undo/redo, grouped typing, history unaffected by saving."""

    def test_history_survives_any_number_of_saves(self):
        app = self.app(autosave=False)
        doc = app.editor.doc
        for word in ('alpha ', 'beta ', 'gamma '):
            for ch in word:
                doc.insert(ch, coalesce=(ch != ' '))
            app.save()
        self.assertEqual(self.read(), b'alpha beta gamma one\ntwo\n')
        while doc.undo():
            pass
        self.assertEqual(doc.text(), ORIGINAL)
        app.save()
        self.assertEqual(self.read(), ORIGINAL.encode())

    def test_redo_is_dropped_by_a_new_edit(self):
        doc = Document(self.path)
        doc.insert('A')
        doc.undo()
        doc.insert('B')
        self.assertFalse(doc.redo())
        self.assertEqual(doc.text(), 'Bone\ntwo\n')


class TestQuitAndExternalChanges(Base):
    """Closing, and files that move under us."""

    def test_quit_saves_what_auto_save_owns(self):
        app = self.app(autosave_delay=60.0)
        app.editor.doc.insert('unsaved ')
        app.quit()
        self.assertFalse(app.running)
        self.assertEqual(self.read(), b'unsaved one\ntwo\n')

    def test_quit_asks_when_auto_save_is_off(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('unsaved ')
        app.quit()
        self.assertTrue(app.running, 'it should wait for an answer')
        self.assertIsNotNone(app.overlay)

    def test_a_clean_buffer_follows_the_file(self):
        app = self.app()
        with open(self.path, 'w') as f:
            f.write('changed outside\n')
        app.check_disk_changes(force=True)
        self.assertEqual(app.editor.doc.text(), 'changed outside\n')
        self.assertIsNone(app.overlay, 'no question needed for a clean buffer')

    def test_a_dirty_buffer_is_never_replaced_silently(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        with open(self.path, 'w') as f:
            f.write('changed outside\n')
        app.check_disk_changes(force=True)
        self.assertIn('mine ', app.editor.doc.text())
        self.assertIsNotNone(app.overlay)


class TestDeliberateDifferences(Base):
    """Where we knowingly do not match VS Code."""

    def test_no_hot_exit_unsaved_untitled_work_is_not_restored(self):
        # VS Code restores unsaved buffers on next launch; we drop history at
        # exit on purpose, so quitting must not leave state behind on disk
        app = self.app()
        app.new_file()
        app.editor.doc.insert('scratch')
        app.autosave_tick()
        self.assertEqual(sorted(os.listdir(self.tmp)), ['doc.txt'])

    def test_reload_drops_undo_history(self):
        # VS Code can undo past an external reload; we clear it, which is
        # simpler and never resurrects someone else's overwritten content
        doc = Document(self.path)
        doc.insert('mine ')
        with open(self.path, 'w') as f:
            f.write('theirs\n')
        doc.reload()
        self.assertEqual(doc.undo_stack, [])
        self.assertFalse(doc.undo())
        self.assertEqual(doc.text(), 'theirs\n')

    def test_non_utf8_files_open_read_only(self):
        # VS Code guesses an encoding; we refuse to guess and cannot corrupt
        blob = os.path.join(self.tmp, 'blob.bin')
        with open(blob, 'wb') as f:
            f.write(b'\xff\xfe binary \x00\x01')
        doc = Document(blob)
        self.assertTrue(doc.readonly)
        with self.assertRaises(Exception):
            doc.save()


class TestInTheApp(unittest.TestCase):
    """The same guarantees through the real UI."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-parity-ui-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        with open(self.path, 'w') as f:
            f.write(ORIGINAL)
        self.s = Session(['--no-autosave', 'doc.txt', self.tmp],
                         cols=88, rows=20, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_stale_save_is_warned_about_not_performed(self):
        self.s.type('mine ')                        # the buffer is now dirty
        self.s.key(CTRL('j'))
        self.s.type('printf "theirs\\n" > doc.txt' + ENTER)
        self.s.pump(0.6)
        pos = self.s.find('mine ')                  # click back into the editor
        self.assertIsNotNone(pos)
        self.s.click(pos[0], pos[1])
        self.s.key(CTRL('s'))
        self.s.pump(0.6)
        self.assertIn('changed on disk', self.s.screen(),
                      'no warning before overwriting someone else s work')
        with open(self.path) as f:
            self.assertEqual(f.read(), 'theirs\n', 'their content was clobbered')

    def test_typing_and_saving_normally_still_works(self):
        self.s.type('hello ')
        self.s.key(CTRL('s'))
        self.assertTrue(self.s.wait_for('Saved'))
        with open(self.path) as f:
            self.assertEqual(f.read(), 'hello one\ntwo\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
