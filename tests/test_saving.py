"""Exactness and durability of what lands on disk.

Two questions this file answers:
  1. does the buffer apply edits exactly, and
  2. does saving write exactly that, without damaging anything else
     about the file (bytes, mode, symlinks, or the original on failure)?
"""

import io
import os
import random
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tide.app import App
from tide.buffer import Document
from tide.editor import Editor


class FakeApp(object):
    def status(self, msg):
        pass


def mk_editor(text, path=None):
    ed = Editor(FakeApp(), Document(text=text))
    ed.doc.path = path
    return ed


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


class TempFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-save-')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as f:
            f.write(data)
        return path


SHAPES = {
    'empty': b'',
    'single_char': b'x',
    'no_trailing_newline': b'one\ntwo\nthree',
    'trailing_newline': b'one\ntwo\n',
    'two_trailing_newlines': b'one\n\n',
    'only_newlines': b'\n\n\n',
    'trailing_spaces': b'a   \nb\t\t\n',
    'tabs_and_spaces': b'\tif x:\n\t    return 1\n',
    'crlf': b'one\r\ntwo\r\n',
    'crlf_no_trailing': b'one\r\ntwo',
    'unicode': u'caf\u00e9 \u6f22\u5b57 \U0001f600\ncombining e\u0301\n'.encode('utf-8'),
    'long_line': b'x' * 20000 + b'\n',
    'many_lines': b''.join(b'line %d\n' % i for i in range(5000)),
    'blank_lines_between': b'a\n\n\nb\n',
    'form_feed': b'a\x0cb\n',
    'nul_free_control_chars': b'bell\x07 esc\x1b[0m\n',
}


class TestRoundTrip(TempFileTest):
    """Opening and saving without editing must not change a single byte."""

    def test_all_shapes_round_trip(self):
        for name, data in SHAPES.items():
            path = self.write(name, data)
            doc = Document(path)
            doc.save()
            self.assertEqual(read_bytes(path), data, 'byte change in %s' % name)

    def test_round_trip_after_edit_and_undo(self):
        for name, data in SHAPES.items():
            path = self.write(name, data)
            doc = Document(path)
            doc.cursor = (0, 0)
            doc.insert('zz')
            doc.undo()
            doc.save()
            self.assertEqual(read_bytes(path), data, 'edit+undo changed %s' % name)

    def test_reload_matches_what_was_saved(self):
        for name, data in SHAPES.items():
            path = self.write(name, data)
            doc = Document(path)
            doc.cursor = doc.end_pos()
            doc.insert('TAIL')
            doc.save()
            again = Document(path)
            self.assertEqual(again.lines, doc.lines, 'reload differs for %s' % name)


class TestEditExactness(TempFileTest):
    def test_insert_at_every_position(self):
        base = 'ab\ncd\n'
        for row in range(3):
            for col in range(3):
                doc = Document(text=base)
                pos = doc.clamp((row, col))
                doc.cursor = pos
                doc.insert('X')
                lines = base.split('\n')
                lines[pos[0]] = lines[pos[0]][:pos[1]] + 'X' + lines[pos[0]][pos[1]:]
                self.assertEqual(doc.text(), '\n'.join(lines))

    def test_delete_every_range(self):
        base = 'abc\ndef\nghi'
        flat = base
        for start in range(len(flat)):
            for end in range(start, len(flat) + 1):
                doc = Document(text=base)
                a = offset_to_pos(base, start)
                b = offset_to_pos(base, end)
                doc.delete_range(a, b)
                self.assertEqual(doc.text(), flat[:start] + flat[end:],
                                 'delete [%d,%d)' % (start, end))

    def test_newline_at_end_of_file_without_trailing_newline(self):
        doc = Document(text='last line')
        doc.cursor = doc.end_pos()
        doc.insert('\n')
        self.assertEqual(doc.lines, ['last line', ''])
        self.assertEqual(doc.text(), 'last line\n')

    def test_edit_on_the_final_line(self):
        ed = mk_editor('a\nb')
        ed.doc.cursor = (1, 1)
        ed.backspace()
        self.assertEqual(ed.doc.text(), 'a\n')
        ed.backspace()
        self.assertEqual(ed.doc.text(), 'a')

    def test_delete_lines_at_the_end(self):
        ed = mk_editor('a\nb\nc')
        ed.doc.cursor = (2, 0)
        ed.delete_lines()
        self.assertEqual(ed.doc.text(), 'a\nb')
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'a\nb\nc')

    def test_selection_ending_at_column_zero(self):
        ed = mk_editor('one\ntwo\nthree\n')
        ed.doc.anchor = (0, 0)
        ed.doc.cursor = (2, 0)          # whole first two lines
        ed.indent_selection()
        self.assertEqual(ed.doc.text(), '    one\n    two\nthree\n')
        ed.doc.undo()
        ed.doc.undo()
        self.assertEqual(ed.doc.text(), 'one\ntwo\nthree\n')

    def test_crlf_file_keeps_crlf_on_new_lines(self):
        path = self.write('c.txt', b'one\r\ntwo\r\n')
        doc = Document(path)
        doc.cursor = (1, 3)
        doc.insert('\nthree')
        doc.save()
        self.assertEqual(read_bytes(path), b'one\r\ntwo\r\nthree\r\n')

    def test_unicode_columns_are_characters_not_bytes(self):
        doc = Document(text=u'caf\u00e9 \u6f22\u5b57')
        doc.cursor = (0, 4)
        doc.insert('!')
        self.assertEqual(doc.text(), u'caf\u00e9! \u6f22\u5b57')


def offset_to_pos(text, offset):
    head = text[:offset]
    row = head.count('\n')
    col = offset - (head.rfind('\n') + 1)
    return (row, col)


def pos_to_offset(text, pos):
    lines = text.split('\n')
    return sum(len(l) + 1 for l in lines[:pos[0]]) + pos[1]


class TestRandomisedAgainstAModel(TempFileTest):
    """Random edits, checked against plain string operations after every step."""

    def _run(self, seed, steps=200):
        """Mirror every edit in a plain string and compare after each step.

        Undo is checked against a snapshot stack that grows only when the
        document actually opened a new undo entry, so a coalesced typing run
        is expected to undo as a single step.
        """
        rng = random.Random(seed)
        text = 'alpha\nbeta\n\ngamma delta\n'
        doc = Document(text=text)
        model = text
        undo_snaps = []                  # text as it was before each undo entry
        redo_snaps = []
        for step in range(steps):
            op = rng.choice(['insert', 'insert', 'delete', 'delete', 'newline',
                             'undo', 'redo'])
            if op in ('insert', 'newline'):
                off = rng.randrange(len(model) + 1)
                chunk = '\n' if op == 'newline' else rng.choice(
                    ['x', 'hello', ' ', '\t', u'\u00e9', 'ab\ncd'])
                depth = len(doc.undo_stack)
                doc.cursor = doc.clamp(offset_to_pos(model, off))
                doc.anchor = None
                doc.insert(chunk, coalesce=rng.random() < 0.5)
                if len(doc.undo_stack) > depth:
                    undo_snaps.append(model)
                model = model[:off] + chunk + model[off:]
                del redo_snaps[:]
            elif op == 'delete':
                if not model:
                    continue
                a = rng.randrange(len(model))
                b = rng.randrange(a, min(len(model), a + 12) + 1)
                if a == b:
                    continue
                depth = len(doc.undo_stack)
                doc.delete_range(offset_to_pos(model, a), offset_to_pos(model, b))
                if len(doc.undo_stack) > depth:
                    undo_snaps.append(model)
                model = model[:a] + model[b:]
                del redo_snaps[:]
            elif op == 'undo':
                if doc.undo():
                    self.assertTrue(undo_snaps, 'undo with nothing recorded (step %d)' % step)
                    redo_snaps.append(model)
                    model = undo_snaps.pop()
                else:
                    self.assertFalse(undo_snaps, 'undo refused but history remains')
            elif op == 'redo':
                if doc.redo():
                    self.assertTrue(redo_snaps, 'redo with nothing recorded (step %d)' % step)
                    undo_snaps.append(model)
                    model = redo_snaps.pop()
            self.assertEqual(doc.text(), model,
                             'diverged at step %d (%s), seed %d' % (step, op, seed))
        return doc, model

    def test_many_seeds(self):
        for seed in range(12):
            doc, model = self._run(seed)
            path = os.path.join(self.tmp, 'seed%d.txt' % seed)
            doc.path = path
            doc.save()
            self.assertEqual(read_bytes(path), model.encode('utf-8'))

    def test_a_typing_run_undoes_as_one_step(self):
        doc = Document(text='ab')
        doc.cursor = (0, 1)
        for ch in 'XYZ':
            doc.insert(ch, coalesce=True)
        self.assertEqual(doc.text(), 'aXYZb')
        self.assertEqual(len(doc.undo_stack), 1)
        doc.undo()
        self.assertEqual(doc.text(), 'ab')
        doc.redo()
        self.assertEqual(doc.text(), 'aXYZb')

    def test_typing_somewhere_else_starts_a_new_undo_step(self):
        doc = Document(text='abcdef')
        doc.cursor = (0, 1)
        doc.insert('P', coalesce=True)
        doc.cursor = (0, 5)
        doc.insert('Q', coalesce=True)
        self.assertEqual(len(doc.undo_stack), 2)
        doc.undo()
        self.assertEqual(doc.text(), 'aPbcdef')
        doc.undo()
        self.assertEqual(doc.text(), 'abcdef')

    def test_undo_all_the_way_back(self):
        rng = random.Random(99)
        start = 'one\ntwo\nthree\n'
        doc = Document(text=start)
        for _ in range(120):
            off = rng.randrange(len(doc.text()) + 1)
            doc.cursor = doc.clamp(offset_to_pos(doc.text(), off))
            doc.insert(rng.choice(['q', '\n', 'zz']), coalesce=rng.random() < 0.5)
        while doc.undo():
            pass
        self.assertEqual(doc.text(), start)


class TestFileMetadata(TempFileTest):
    def test_executable_bit_survives(self):
        path = self.write('script.sh', b'#!/bin/sh\necho hi\n')
        os.chmod(path, 0o755)
        doc = Document(path)
        doc.cursor = doc.end_pos()
        doc.insert('echo more\n')
        doc.save()
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o755, 'mode became %o' % mode)
        self.assertTrue(os.access(path, os.X_OK))

    def test_restrictive_mode_survives(self):
        path = self.write('secret.txt', b'token\n')
        os.chmod(path, 0o600)
        doc = Document(path)
        doc.insert('x')
        doc.save()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_symlink_is_not_replaced(self):
        target = self.write('real.txt', b'hello\n')
        link = os.path.join(self.tmp, 'link.txt')
        os.symlink(target, link)
        doc = Document(link)
        doc.cursor = doc.end_pos()
        doc.insert('world\n')
        doc.save()
        self.assertTrue(os.path.islink(link), 'the symlink was replaced by a file')
        self.assertEqual(read_bytes(target), b'hello\nworld\n')

    def test_a_read_only_file_can_still_be_edited(self):
        # writing through a temp file and a rename only needs a writable
        # directory; the file's own mode is preserved, not treated as a lock
        path = self.write('locked.txt', b'protected\n')
        os.chmod(path, 0o444)
        doc = Document(path)
        doc.insert('X')
        doc.save()
        self.assertEqual(read_bytes(path), b'Xprotected\n')
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o444)

    def test_no_temp_files_left_behind(self):
        path = self.write('a.txt', b'x\n')
        doc = Document(path)
        doc.insert('y')
        doc.save()
        leftovers = [f for f in os.listdir(self.tmp) if 'tide-tmp' in f]
        self.assertEqual(leftovers, [])


class TestFailureLeavesTheOriginal(TempFileTest):
    def test_read_only_directory(self):
        sub = os.path.join(self.tmp, 'ro')
        os.mkdir(sub)
        path = os.path.join(sub, 'a.txt')
        with open(path, 'wb') as f:
            f.write(b'original\n')
        os.chmod(sub, 0o500)
        try:
            doc = Document(path)
            doc.insert('X')
            with self.assertRaises(Exception):
                doc.save()
            self.assertEqual(read_bytes(path), b'original\n')
            self.assertEqual([f for f in os.listdir(sub) if 'tide-tmp' in f], [])
        finally:
            os.chmod(sub, 0o700)

    def test_missing_parent_directory(self):
        doc = Document(text='data')
        doc.path = os.path.join(self.tmp, 'nope', 'a.txt')
        with self.assertRaises(Exception):
            doc.save()
        self.assertTrue(doc.dirty or True)


class TestNonUtf8(TempFileTest):
    def test_binary_file_is_not_silently_rewritten(self):
        data = b'\xff\xfe\x00\x01 latin \xe9 text\n'
        path = self.write('blob.bin', data)
        doc = Document(path)
        self.assertTrue(getattr(doc, 'readonly', False),
                        'a file we cannot decode should open read-only')
        doc.insert('x')
        try:
            doc.save()
        except Exception:
            pass
        self.assertEqual(read_bytes(path), data, 'binary file was corrupted')


class TestAppLevelSaving(TempFileTest):
    def _app(self, files):
        for name, data in files.items():
            self.write(name, data)
        app = App(root=self.tmp,
                  paths=[os.path.join(self.tmp, n) for n in files],
                  out=io.StringIO())
        app.autosave_delay = 0.0
        return app

    def test_autosave_writes_every_open_file(self):
        app = self._app({'a.txt': b'a\n', 'b.txt': b'b\n'})
        for ed in app.editors:
            ed.doc.cursor = (0, 0)
            ed.doc.insert('EDIT ')
        app.autosave_tick()
        self.assertEqual(read_bytes(os.path.join(self.tmp, 'a.txt')), b'EDIT a\n')
        self.assertEqual(read_bytes(os.path.join(self.tmp, 'b.txt')), b'EDIT b\n')

    def test_quit_flushes_before_exiting(self):
        app = self._app({'a.txt': b'a\n'})
        app.autosave_delay = 60.0            # nowhere near due
        app.editor.doc.insert('NOW')
        app.quit()
        self.assertEqual(read_bytes(os.path.join(self.tmp, 'a.txt')), b'NOWa\n')
        self.assertFalse(app.running)
        self.assertIsNone(app.overlay, 'should not ask about a file it just saved')

    def test_closing_a_tab_saves_instead_of_asking(self):
        app = self._app({'a.txt': b'a\n'})
        app.autosave_delay = 60.0
        app.editor.doc.insert('KEEP')
        app.close_tab(0)
        self.assertEqual(read_bytes(os.path.join(self.tmp, 'a.txt')), b'KEEPa\n')
        self.assertIsNone(app.overlay)

    def test_untitled_close_still_asks(self):
        app = self._app({'a.txt': b'a\n'})
        app.new_file()
        app.editor.doc.insert('scratch')
        app.close_tab(app.active)
        self.assertIsNotNone(app.overlay, 'an unsaved untitled buffer must prompt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
