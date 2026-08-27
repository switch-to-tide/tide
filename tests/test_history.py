"""Edit history: the model, the grouping, the dirty state, and its lifetime.

The model is the mainstream one - a linear undo stack with a redo stack in the
command-pattern sense (each edit knows how to reverse itself), a new edit ends
the redo branch, and consecutive typing is grouped into one step.  Dirty state
is tracked by a version id that returns to its old value when you undo, the way
VS Code / Monaco does it, rather than by counting entries.
"""

import gc
import io
import os
import random
import shutil
import sys
import tempfile
import time
import unittest
import weakref

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import CTRL, ENTER, Session
from tide.app import App
from tide.buffer import Document
from tide.editor import Editor


class FakeApp(object):
    def status(self, msg):
        pass


def editor(text):
    from tide.term import Rect
    ed = Editor(FakeApp(), Document(text=text))
    ed.text_rect = Rect(0, 0, 80, 20)
    return ed


class TestUndoRedoModel(unittest.TestCase):
    def test_undo_and_redo_restore_the_text_exactly(self):
        d = Document(text='one\ntwo\n')
        d.cursor = (0, 3)
        d.insert(' AND A HALF')
        after = d.text()
        self.assertTrue(d.undo())
        self.assertEqual(d.text(), 'one\ntwo\n')
        self.assertTrue(d.redo())
        self.assertEqual(d.text(), after)

    def test_a_new_edit_ends_the_redo_branch(self):
        d = Document(text='a')
        d.cursor = (0, 1)
        d.insert('B')
        d.undo()
        self.assertEqual(len(d.redo_stack), 1)
        d.insert('C')                       # diverging from the undone branch
        self.assertEqual(d.redo_stack, [])
        self.assertFalse(d.redo())
        self.assertEqual(d.text(), 'aC')

    def test_undo_past_the_start_and_redo_past_the_end_are_no_ops(self):
        d = Document(text='x')
        self.assertFalse(d.undo())
        self.assertFalse(d.redo())
        d.insert('y')
        self.assertTrue(d.undo())
        self.assertFalse(d.undo())
        self.assertEqual(d.text(), 'x')
        self.assertTrue(d.redo())
        self.assertFalse(d.redo())

    def test_undo_puts_the_cursor_back_where_the_edit_started(self):
        d = Document(text='alpha\nbeta\n')
        d.cursor = (1, 2)
        d.insert('XYZ')
        self.assertEqual(d.cursor, (1, 5))
        d.undo()
        self.assertEqual(d.cursor, (1, 2))
        d.redo()
        self.assertEqual(d.cursor, (1, 5))

    def test_undo_clears_the_selection(self):
        d = Document(text='hello world')
        d.anchor, d.cursor = (0, 0), (0, 5)
        d.insert('bye')
        d.undo()
        self.assertIsNone(d.anchor)
        self.assertEqual(d.text(), 'hello world')

    def test_a_long_session_unwinds_and_rewinds(self):
        rng = random.Random(7)
        d = Document(text='start\n')
        states = [d.text()]
        for _ in range(200):
            text = d.text()
            offset = rng.randrange(len(text) + 1)
            row = text[:offset].count('\n')
            col = offset - (text[:offset].rfind('\n') + 1)
            d.cursor = d.clamp((row, col))
            d.insert(rng.choice(['q', 'word ', '\n', 'xy']))
            states.append(d.text())
        while d.undo():
            states.pop()
            self.assertEqual(d.text(), states[-1])
        self.assertEqual(d.text(), 'start\n')
        while d.redo():
            pass
        self.assertEqual(len(d.undo_stack) > 0, True)


class TestGrouping(unittest.TestCase):
    """Consecutive typing collapses into one step; other things break the run."""

    def typed(self, ed, text):
        for ch in text:
            ed.doc.insert(ch, coalesce=(ch not in ' \t'))

    def test_a_word_is_one_undo_step(self):
        ed = editor('')
        self.typed(ed, 'hello')
        self.assertEqual(len(ed.doc.undo_stack), 1)
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), '')

    def test_a_very_long_run_of_typing_splits_up(self):
        # Emacs starts a new undo step every twentieth self-inserted character
        ed = editor('')
        self.typed(ed, 'abcdefghijklmnopqrstuvwxyz0123456789')
        self.assertEqual(len(ed.doc.undo_stack), 2)
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'abcdefghijklmnopqrst')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), '')

    def test_a_short_word_is_still_one_step(self):
        ed = editor('')
        self.typed(ed, 'short')
        self.assertEqual(len(ed.doc.undo_stack), 1)

    def test_a_space_starts_a_new_step(self):
        ed = editor('')
        self.typed(ed, 'two words')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'two ')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'two')

    def test_moving_the_cursor_starts_a_new_step(self):
        ed = editor('ab')
        ed.doc.cursor = (0, 2)
        self.typed(ed, 'XY')
        ed.set_cursor((0, 0))               # a deliberate move
        self.typed(ed, 'Z')
        self.assertEqual(ed.doc.text(), 'ZabXY')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'abXY')

    def test_a_newline_is_its_own_step(self):
        ed = editor('')
        self.typed(ed, 'line')
        ed.newline()
        self.typed(ed, 'next')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'line\n')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'line')

    def test_deleting_is_not_merged_into_typing(self):
        ed = editor('')
        self.typed(ed, 'abcd')
        ed.backspace()
        self.assertEqual(ed.doc.text(), 'abc')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'abcd')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), '')

    def test_a_paste_is_a_single_step(self):
        ed = editor('x')
        ed.doc.cursor = (0, 1)
        ed.paste('a lot\nof pasted\ntext\n')
        self.assertEqual(len(ed.doc.undo_stack), 1)
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'x')

    def test_indenting_a_block_undoes_line_by_line_but_completely(self):
        ed = editor('a\nb\nc')
        ed.doc.anchor, ed.doc.cursor = (0, 0), (2, 1)
        ed.indent_selection()
        self.assertEqual(ed.doc.text(), '    a\n    b\n    c')
        for _ in range(3):
            ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'a\nb\nc')


class TestDirtyTracking(unittest.TestCase):
    """The failure modes that made version tracking necessary."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-hist-')
        self.path = os.path.join(self.tmp, 'f.txt')
        with open(self.path, 'w') as f:
            f.write('x\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def test_undo_then_a_different_edit_is_dirty(self):
        # the stack is the same height as at save time, but the text is not
        d = Document(self.path)
        d.cursor = (0, 0)
        d.insert('A')
        d.save()
        d.undo()
        d.cursor = (0, 0)
        d.insert('B')
        self.assertEqual(d.text(), 'Bx\n')
        self.assertTrue(d.dirty, 'a buffer that differs from disk must be dirty')

    def test_undoing_back_to_the_saved_state_is_clean_again(self):
        d = Document(self.path)
        d.cursor = (0, 0)
        d.insert('A')
        self.assertTrue(d.dirty)
        d.undo()
        self.assertFalse(d.dirty, 'back at the saved text, so nothing to write')
        d.redo()
        self.assertTrue(d.dirty)

    def test_typing_on_after_a_save_is_dirty(self):
        d = Document(self.path)
        d.cursor = (0, 0)
        d.insert('A', coalesce=True)
        d.save()
        d.insert('B', coalesce=True)        # continues the same typing run
        self.assertTrue(d.dirty, 'characters typed after a save must still be saved')
        d.save()
        self.assertEqual(self.read(), 'ABx\n')

    def test_save_undo_save_writes_the_undone_text(self):
        d = Document(self.path)
        d.cursor = (0, 0)
        d.insert('TYPO')
        d.save()
        self.assertEqual(self.read(), 'TYPOx\n')
        d.undo()
        self.assertTrue(d.dirty)
        d.save()
        self.assertEqual(self.read(), 'x\n')

    def test_reload_resets_the_history_and_the_marker(self):
        d = Document(self.path)
        d.insert('one')
        d.save()
        with open(self.path, 'w') as f:
            f.write('from elsewhere\n')
        d.reload()
        self.assertEqual(d.undo_stack, [])
        self.assertEqual(d.redo_stack, [])
        self.assertFalse(d.dirty)
        d.insert('Z')                       # the first edit after a reload counts
        self.assertTrue(d.dirty)

    def test_history_is_bounded_and_still_correct(self):
        d = Document(text='')
        for i in range(5000):
            d.cursor = (0, 0)
            d.insert('%d ' % i)
        self.assertLessEqual(len(d.undo_stack), 4000, 'history should be capped')
        text = d.text()
        self.assertTrue(d.undo())
        self.assertNotEqual(d.text(), text)
        self.assertTrue(d.dirty)


class TestHistoryLifetime(unittest.TestCase):
    """History lives in memory only, and goes away with the buffer."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-life-')
        self.path = os.path.join(self.tmp, 'f.txt')
        with open(self.path, 'w') as f:
            f.write('hello\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_editing_writes_no_history_file(self):
        before = set(os.listdir(self.tmp))
        d = Document(self.path)
        for i in range(50):
            d.cursor = (0, 0)
            d.insert('edit %d ' % i)
            if i % 10 == 0:
                d.save()
        d.undo()
        d.save()
        self.assertEqual(set(os.listdir(self.tmp)), before,
                         'editing should leave no undo files behind')

    def test_closing_a_tab_frees_the_history(self):
        app = App(root=self.tmp, paths=[self.path], out=io.StringIO())
        doc = app.editor.doc
        for i in range(100):
            doc.cursor = (0, 0)
            doc.insert('x%d ' % i)
        self.assertGreater(len(doc.undo_stack), 10)
        doc.save()
        from tide.buffer import Edit
        ref = weakref.ref(doc)
        before = sum(1 for o in gc.get_objects() if isinstance(o, Edit))
        app.close_tab(0)
        del doc
        gc.collect()
        after = sum(1 for o in gc.get_objects() if isinstance(o, Edit))
        self.assertIsNone(ref(), 'the closed buffer is still alive')
        self.assertLess(after, before - 50, 'its edit history was not released')

    def test_history_does_not_grow_without_bound(self):
        d = Document(text='seed\n')
        for i in range(9000):
            d.cursor = (0, 0)
            d.insert('%d ' % i)
        self.assertLessEqual(len(d.undo_stack), 4000)


class TestHistoryInTheUI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-hist-ui-')
        self.path = os.path.join(self.tmp, 'doc.txt')
        with open(self.path, 'w') as f:
            f.write('first\nsecond\n')
        self.s = Session(['doc.txt', self.tmp], cols=86, rows=18, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dirty_marker_clears_when_you_undo_back(self):
        self.s.type('EDIT')
        self.assertIn('doc.txt*', self.s.screen())
        self.s.key(CTRL('z'))
        self.s.pump(0.4)
        self.assertNotIn('doc.txt*', self.s.screen())
        self.assertNotIn('EDIT', self.s.screen())

    def test_undo_then_retype_still_saves(self):
        self.s.type('AAA')
        time.sleep(1.2)                      # auto-save runs on a timer
        self.s.pump(0.4)
        self.s.key(CTRL('z'))
        time.sleep(1.2)
        self.s.pump(0.4)
        self.s.type('BBB')
        time.sleep(1.2)
        self.s.pump(0.4)
        with open(self.path) as f:
            self.assertEqual(f.read(), 'BBBfirst\nsecond\n')

    def test_nothing_is_left_on_disk_after_quitting(self):
        for chunk in ('one ', 'two ', 'three '):
            self.s.type(chunk)
            time.sleep(0.9)
            self.s.pump(0.3)
        for _ in range(3):
            self.s.key(CTRL('z'))
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(sorted(os.listdir(self.tmp)), ['doc.txt'],
                         'the session left files behind')


if __name__ == '__main__':
    unittest.main(verbosity=2)
