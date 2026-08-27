"""Staying in step with files that something else rewrites.

The motivating case: a tool running in one of the built-in terminals (a code
assistant, a formatter, `git checkout`) edits files that are open in tabs.
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

from harness import ALT_LEFT, ALT_RIGHT, CTRL, ENTER, F2, F4, Session
from tide.app import App
from tide.keys import Key


class AppWatchTest(unittest.TestCase):
    """Drive the watcher directly, without a terminal."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-watch-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        self.write('one\ntwo\n')
        self.app = App(root=self.tmp, paths=[self.path], out=io.StringIO())
        self.app.autosave_delay = 0.0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, path=None):
        # a distinct mtime, whatever the filesystem's resolution
        time.sleep(0.01)
        with open(path or self.path, 'w') as f:
            f.write(text)

    def read(self, path=None):
        with open(path or self.path) as f:
            return f.read()

    def answer(self, ch):
        """Reply to a Confirm the way the key handler would."""
        self.assertIsNotNone(self.app.overlay, 'expected a question')
        if self.app.overlay.on_key(Key('char', ch)) == 'close':
            self.app.overlay = None

    def test_clean_buffer_picks_up_external_edits(self):
        self.write('one\ntwo\nthree from a tool\n')
        self.app.check_disk_changes(force=True)
        self.assertEqual(self.app.editor.doc.lines[2], 'three from a tool')
        self.assertIsNone(self.app.overlay, 'no question needed for a clean buffer')
        self.assertIn('Reloaded', self.app.message)

    def test_reload_keeps_the_cursor_and_clears_dirty(self):
        self.app.editor.doc.cursor = (1, 2)
        self.write('one\ntwo\nthree\nfour\n')
        self.app.check_disk_changes(force=True)
        self.assertEqual(self.app.editor.doc.cursor, (1, 2))
        self.assertFalse(self.app.editor.doc.dirty)

    def test_cursor_past_the_new_end_is_clamped(self):
        self.app.editor.doc.cursor = (1, 3)
        self.write('x\n')
        self.app.check_disk_changes(force=True)
        self.assertEqual(self.app.editor.doc.cursor, (1, 0))

    def test_an_identical_rewrite_is_not_a_reload(self):
        doc = self.app.editor.doc
        doc.cursor = (0, 0)
        doc.insert('EDIT ')
        self.app.autosave_tick()
        undo_depth = len(doc.undo_stack)
        self.write(doc.text())            # same bytes, new mtime
        self.app.check_disk_changes(force=True)
        self.assertEqual(len(doc.undo_stack), undo_depth, 'undo history was thrown away')

    def test_conflict_asks_and_can_take_the_disk_version(self):
        self.app.autosave = False
        self.app.editor.doc.insert('MINE ')
        self.write('theirs\n')
        self.app.check_disk_changes(force=True)
        self.assertIsNotNone(self.app.overlay, 'an unsaved buffer must not be replaced silently')
        self.answer('y')
        self.assertEqual(self.app.editor.doc.text(), 'theirs\n')
        self.assertFalse(self.app.editor.doc.dirty)

    def test_conflict_can_keep_my_version(self):
        self.app.autosave = False
        self.app.editor.doc.insert('MINE ')
        self.write('theirs\n')
        self.app.check_disk_changes(force=True)
        self.answer('n')
        self.assertTrue(self.app.editor.doc.text().startswith('MINE '))
        self.app.check_disk_changes(force=True)
        self.assertIsNone(self.app.overlay, 'it should stop asking once answered')
        self.app.autosave = True
        self.app.autosave_tick()
        self.assertTrue(self.read().startswith('MINE '), 'my version should now win')

    def test_autosave_does_not_clobber_an_unanswered_conflict(self):
        self.app.editor.doc.insert('MINE ')
        self.write('theirs\n')
        self.app.check_disk_changes(force=True)
        self.app.autosave_tick()
        self.assertEqual(self.read(), 'theirs\n', 'auto-save overwrote an external change')

    def test_background_tab_is_not_interrupted_but_updates(self):
        other = os.path.join(self.tmp, 'other.txt')
        self.write('other original\n', other)
        self.app.open_file(other)
        self.assertEqual(self.app.active, 1)
        self.write('one\ntwo\nthree\n')          # the *background* tab's file
        self.app.check_disk_changes(force=True)
        self.assertIsNone(self.app.overlay)
        self.assertEqual(self.app.editors[0].doc.lines[2], 'three')

    def test_deleted_file_is_reported_and_not_recreated(self):
        os.remove(self.path)
        self.app.check_disk_changes(force=True)
        self.assertIn('deleted on disk', self.app.message)
        self.app.editor.doc.insert('X')
        self.app.autosave_tick()
        self.assertFalse(os.path.exists(self.path), 'auto-save resurrected a deleted file')

    def test_ctrl_s_writes_a_deleted_file_back(self):
        os.remove(self.path)
        self.app.check_disk_changes(force=True)
        self.app.save()
        self.assertEqual(self.read(), 'one\ntwo\n')

    def test_undo_after_a_reload_is_harmless(self):
        self.app.editor.doc.insert('typed')
        self.app.autosave_tick()
        self.write('replaced from outside\n')
        self.app.check_disk_changes(force=True)
        self.assertEqual(self.app.editor.doc.text(), 'replaced from outside\n')
        self.assertFalse(self.app.editor.doc.undo(), 'history should be empty')
        self.assertEqual(self.app.editor.doc.text(), 'replaced from outside\n')

    def test_viewport_survives_the_file_shrinking(self):
        self.write(''.join('row %d\n' % i for i in range(500)))
        self.app.check_disk_changes(force=True)
        ed = self.app.editor
        ed.top = 400
        ed.doc.cursor = (450, 2)
        self.write('tiny\n')
        self.app.check_disk_changes(force=True)
        ed.render(__import__('tide.term', fromlist=['Screen']).Screen(80, 20),
                  __import__('tide.term', fromlist=['Rect']).Rect(0, 0, 80, 10), True)
        self.assertLessEqual(ed.top, len(ed.doc.lines) - 1)
        self.assertEqual(ed.doc.cursor, (1, 0))

    def test_file_made_read_only_outside_is_still_saved(self):
        import stat as _stat
        self.app.editor.doc.insert('X')
        os.chmod(self.path, 0o444)
        try:
            self.app.autosave_tick()
            self.assertEqual(self.read(), 'Xone\ntwo\n')
            self.assertEqual(_stat.S_IMODE(os.stat(self.path).st_mode), 0o444)
            self.assertEqual(self.app.message, 'Opened doc.txt')   # no error
        finally:
            os.chmod(self.path, 0o644)

    def test_symlink_and_target_share_one_tab(self):
        link = os.path.join(self.tmp, 'alias.txt')
        os.symlink(self.path, link)
        before = len(self.app.editors)
        self.app.open_file(link)
        self.assertEqual(len(self.app.editors), before,
                         'the symlink opened a second buffer for the same file')

    def test_new_files_reach_the_tree_and_quick_open(self):
        self.app._file_cache = None
        self.app.all_files()
        self.write('brand new\n', os.path.join(self.tmp, 'fresh.py'))
        self.app._last_tree_refresh = 0.0
        self.app.check_disk_changes(force=True)
        self.assertIn('fresh.py', [e.name for e in self.app.tree.entries])
        self.assertIn('fresh.py', self.app.all_files())


ORIGINAL = 'alpha\nbeta\n'


class TerminalWritesTest(unittest.TestCase):
    """The real thing: a shell inside the IDE rewrites an open file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-watch-e2e-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        with open(self.path, 'w') as f:
            f.write(ORIGINAL)
        self.s = Session([self.path, self.tmp], cols=90, rows=24, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bottom_terminal_edit_shows_up_in_the_editor(self):
        self.s.key(CTRL('j'))
        self.s.type('echo "gamma from the shell" >> doc.txt' + ENTER)
        self.assertTrue(self.s.wait_for('3 gamma from the shell'),
                        'the editor never showed the appended line')
        self.assertIn('Reloaded', self.s.screen())

    def test_full_size_terminal_edit_is_visible_after_switching_back(self):
        self.s.key(F2)
        self.s.type("printf 'rewritten\\nby the tool\\n' > doc.txt" + ENTER)
        self.s.pump(0.5)
        self.s.key(F2)                       # back to the editor
        self.assertTrue(self.s.wait_for('2 by the tool'))
        self.assertNotIn('alpha', self.s.screen())

    def test_a_whole_file_replacement_is_picked_up(self):
        self.s.key(CTRL('j'))
        self.s.type('sed -i "" s/alpha/ALPHA/ doc.txt 2>/dev/null || '
                    'sed -i s/alpha/ALPHA/ doc.txt' + ENTER)
        self.assertTrue(self.s.wait_for('1 ALPHA'))

    def test_background_tab_refreshes_when_you_switch_to_it(self):
        other = os.path.join(self.tmp, 'other.txt')
        with open(other, 'w') as f:
            f.write('other file\n')
        self.s.key(CTRL('p'))
        self.s.type('other')
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('other file'))
        self.s.key(CTRL('j'))
        self.s.type('echo "delta appended" >> doc.txt' + ENTER)
        self.s.pump(0.6)
        self.s.click_tab('doc.txt')          # back to doc.txt (the terminal has focus)
        self.assertTrue(self.s.wait_for('3 delta appended'))

    def test_a_file_created_in_the_terminal_appears_in_the_explorer(self):
        self.s.key(CTRL('j'))
        self.s.type('echo hi > brand_new.txt' + ENTER)
        self.s.pump(0.5)
        deadline = time.time() + 5
        while time.time() < deadline:
            if any('brand_new.txt' in line[:26] for line in self.s.text()):
                break                        # it appeared in the explorer column
            self.s.pump(0.3)
        self.assertTrue(any('brand_new.txt' in line[:26] for line in self.s.text()),
                        'the explorer never listed the new file')

    def test_editing_continues_normally_after_a_reload(self):
        self.s.key(CTRL('j'))
        self.s.type('echo "gamma" >> doc.txt' + ENTER)
        self.assertTrue(self.s.wait_for('3 gamma'))
        pos = self.s.find('1 alpha')                 # click into the editor
        self.s.click(pos[0] + 2, pos[1])
        self.s.type('EDIT ')
        time.sleep(1.2)
        self.s.pump(0.4)
        with open(self.path) as f:
            text = f.read()
        self.assertIn('gamma', text)
        self.assertIn('EDIT ', text)


class ConflictTest(unittest.TestCase):
    """With auto-save off there is a real window for a conflict."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-conflict-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        with open(self.path, 'w') as f:
            f.write(ORIGINAL)
        self.s = Session(['--no-autosave', self.path, self.tmp],
                         cols=90, rows=24, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unsaved_edits_trigger_a_question(self):
        self.s.type('MINE ')
        self.s.key(CTRL('j'))
        self.s.type('printf "theirs\\n" > doc.txt' + ENTER)
        self.assertTrue(self.s.wait_for('changed on disk'))
        self.s.send_raw('n')                 # keep mine
        self.s.pump(0.5)
        self.assertIn('MINE ', self.s.screen())
        pos = self.s.find('MINE ')
        self.s.click(pos[0], pos[1])         # focus the editor again
        self.s.key(CTRL('s'))
        self.assertTrue(self.s.wait_for('Saved'))
        with open(self.path) as f:
            self.assertTrue(f.read().startswith('MINE '))

    def test_taking_the_disk_version(self):
        self.s.type('MINE ')
        self.s.key(CTRL('j'))
        self.s.type('printf "theirs\\n" > doc.txt' + ENTER)
        self.assertTrue(self.s.wait_for('changed on disk'))
        self.s.send_raw('y')
        self.s.pump(0.6)
        self.assertIn('theirs', self.s.screen())
        self.assertNotIn('MINE', self.s.screen())


if __name__ == '__main__':
    unittest.main(verbosity=2)
