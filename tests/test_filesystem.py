"""What the file layer does when the filesystem is unhelpful.

Odd content, odd names, odd file types, and writes that fail halfway.  The
rule everywhere: either the write goes through exactly, or it fails loudly and
the file on disk is exactly as it was.
"""

import io
import os
import threading
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import CTRL, ENTER, ESC, Session
from tide.app import App
from tide.buffer import Document, NEW_FILE_MODE

DARWIN = sys.platform == 'darwin'


class FsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-fs-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp(prefix='tide-fs-')

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def read(self, path):
        with open(path, 'rb') as f:
            return f.read()

    def app(self, *paths):
        app = App(root=self.tmp, paths=list(paths), out=io.StringIO())
        app.autosave_delay = 0.0
        return app


class TestOddContent(FsTest):
    def round_trip(self, name, data):
        path = self.write(name, data)
        doc = Document(path)
        doc.save()
        self.assertEqual(self.read(path), data, 'round trip changed %s' % name)
        return doc

    def test_a_byte_order_mark_is_left_alone(self):
        self.round_trip('bom.txt', b'\xef\xbb\xbfhello\nworld\n')

    def test_a_file_that_is_only_a_byte_order_mark(self):
        self.round_trip('onlybom.txt', b'\xef\xbb\xbf')

    def test_carriage_return_only_line_endings(self):
        self.round_trip('cr.txt', b'one\rtwo\rthree')

    def test_nul_bytes_inside_text(self):
        self.round_trip('nul.txt', b'a\x00b\n')

    def test_form_feeds_and_vertical_tabs(self):
        self.round_trip('ff.txt', b'a\x0cb\x0bc\n')

    def test_emoji_and_combining_marks(self):
        self.round_trip('uni.txt', u'é \U0001f600 漢\n'.encode('utf-8'))

    def test_a_two_megabyte_line_is_not_slow(self):
        path = self.write('huge.txt', b'x' * 2000000 + b'\n')
        started = time.time()
        doc = Document(path)
        doc.insert('y')
        doc.save()
        self.assertLess(time.time() - started, 5.0)
        self.assertTrue(self.read(path).startswith(b'yxxx'))

    def test_editing_keeps_the_bom_where_it_was(self):
        path = self.write('bom2.txt', b'\xef\xbb\xbfline\n')
        doc = Document(path)
        doc.cursor = doc.end_pos()
        doc.insert('more\n')
        doc.save()
        self.assertTrue(self.read(path).startswith(b'\xef\xbb\xbfline'))
        self.assertTrue(self.read(path).endswith(b'more\n'))


class TestOddNames(FsTest):
    def test_spaces_quotes_and_accents(self):
        path = self.write(u"a file 'with' é.txt", b'ok\n')
        doc = Document(path)
        doc.insert('X')
        doc.save()
        self.assertEqual(self.read(path), b'Xok\n')

    def test_a_newline_in_the_file_name(self):
        path = self.write('two\nlines.txt', b'ok\n')
        doc = Document(path)
        doc.insert('X')
        doc.save()
        self.assertEqual(self.read(path), b'Xok\n')

    def test_a_deeply_nested_path(self):
        path = self.write('a/b/c/d/e/f/g/deep.txt', b'ok\n')
        doc = Document(path)
        doc.insert('X')
        doc.save()
        self.assertEqual(self.read(path), b'Xok\n')

    def test_dot_dot_in_the_path_is_the_same_file(self):
        path = self.write('dots/sub/file.txt', b'ok\n')
        app = self.app(path)
        weird = os.path.join(self.tmp, 'dots', 'sub', '..', 'sub', 'file.txt')
        before = len(app.editors)
        app.open_file(weird)
        self.assertEqual(len(app.editors), before, 'the same file opened twice')


class TestOddFileTypes(FsTest):
    def test_a_named_pipe_is_refused_rather_than_read(self):
        path = os.path.join(self.tmp, 'pipe')
        os.mkfifo(path)
        with self.assertRaises(Exception):
            Document(path)                       # reading one would block for ever
        app = self.app()
        self.assertIsNone(app.open_file(path))
        self.assertIn('not a regular file', app.message)

    def test_a_device_node_is_refused(self):
        link = os.path.join(self.tmp, 'devnull.txt')
        os.symlink('/dev/null', link)
        app = self.app()
        self.assertIsNone(app.open_file(link))
        self.assertTrue(stat.S_ISCHR(os.stat('/dev/null').st_mode),
                        '/dev/null stopped being a device')

    def test_saving_over_a_pipe_is_refused(self):
        path = os.path.join(self.tmp, 'pipe2')
        os.mkfifo(path)
        doc = Document()
        doc.path = path
        doc.set_text('nope\n')
        with self.assertRaises(Exception):
            doc.save()
        self.assertTrue(stat.S_ISFIFO(os.stat(path).st_mode), 'the pipe was replaced')

    def test_a_directory_is_refused(self):
        os.makedirs(os.path.join(self.tmp, 'adir'))
        app = self.app()
        self.assertIsNone(app.open_file(os.path.join(self.tmp, 'adir')))

    def test_a_symlink_chain_writes_the_real_file(self):
        target = self.write('target.txt', b'target\n')
        mid = os.path.join(self.tmp, 'mid.txt')
        top = os.path.join(self.tmp, 'top.txt')
        os.symlink(target, mid)
        os.symlink(mid, top)
        doc = Document(top)
        doc.insert('X')
        doc.save()
        self.assertEqual(self.read(target), b'Xtarget\n')
        self.assertTrue(os.path.islink(top) and os.path.islink(mid))

    def test_a_broken_symlink_creates_its_target(self):
        link = os.path.join(self.tmp, 'broken.txt')
        os.symlink(os.path.join(self.tmp, 'missing.txt'), link)
        doc = Document()
        doc.path = link
        doc.set_text('written\n')
        doc.save()
        self.assertEqual(self.read(os.path.join(self.tmp, 'missing.txt')), b'written\n')

    def test_a_symlink_loop_does_not_hang(self):
        a = os.path.join(self.tmp, 'loop_a')
        b = os.path.join(self.tmp, 'loop_b')
        os.symlink(a, b)
        os.symlink(b, a)
        app = self.app()
        app.open_file(a)                          # must return, one way or another


class TestWritesThatFail(FsTest):
    def test_no_space_left_on_device(self):
        path = self.write('full.txt', b'original\n')
        doc = Document(path)
        doc.insert('X')
        real_open = io.open

        def no_space(target, mode='r', *args, **kw):
            handle = real_open(target, mode, *args, **kw)
            if 'w' in mode and isinstance(target, int):   # the temp file's fd
                class Full(object):
                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        handle.close()
                        return False

                    def write(self, _data):
                        raise IOError(28, 'No space left on device')

                    def flush(self):
                        pass

                    def fileno(self):
                        return handle.fileno()
                return Full()
            return handle
        io.open = no_space
        try:
            with self.assertRaises(Exception):
                doc.save()
        finally:
            io.open = real_open
        self.assertEqual(self.read(path), b'original\n', 'the original was damaged')
        self.assertEqual([f for f in os.listdir(self.tmp) if 'tide-tmp' in f], [])
        self.assertTrue(doc.dirty, 'the buffer forgot it still needs saving')

    def test_fsync_failing(self):
        path = self.write('fsync.txt', b'original\n')
        doc = Document(path)
        doc.insert('X')
        real = os.fsync

        def broken(_fd):
            raise OSError(5, 'I/O error')
        os.fsync = broken
        try:
            with self.assertRaises(Exception):
                doc.save()
        finally:
            os.fsync = real
        self.assertEqual(self.read(path), b'original\n')

    @unittest.skipUnless(DARWIN, 'chflags is a BSD thing')
    def test_an_immutable_file(self):
        path = self.write('immutable.txt', b'locked\n')
        subprocess.call(['chflags', 'uchg', path])
        try:
            doc = Document(path)
            doc.insert('X')
            with self.assertRaises(Exception):
                doc.save()
            self.assertEqual(self.read(path), b'locked\n')
        finally:
            subprocess.call(['chflags', 'nouchg', path])

    def test_the_file_disappearing_mid_save(self):
        path = self.write('vanish.txt', b'original\n')
        doc = Document(path)
        doc.insert('X')
        original = Document.__dict__['_copy_metadata']

        def vanish(_target, _tmp):
            os.remove(path)
        Document._copy_metadata = staticmethod(vanish)
        try:
            doc.save()
        finally:
            Document._copy_metadata = original
        self.assertEqual(self.read(path), b'Xoriginal\n', 'the save was lost')

    def test_one_stuck_file_does_not_stop_the_others(self):
        a = self.write('a.txt', b'a\n')
        b = self.write('b.txt', b'b\n')
        app = self.app(a, b)
        app.editors[0].doc.autosave_blocked = True
        for ed in app.editors:
            ed.doc.cursor = (0, 0)
            ed.doc.insert('EDIT ')
        app.autosave_tick()
        self.assertEqual(self.read(a), b'a\n')
        self.assertEqual(self.read(b), b'EDIT b\n')

    def test_auto_save_still_runs_with_a_question_on_screen(self):
        path = self.write('busy.txt', b'x\n')
        app = self.app(path)
        app.editors[0].doc.insert('EDIT ')
        app.quit()
        app.autosave_tick()
        self.assertTrue(self.read(path).startswith(b'EDIT '))

    def test_save_as_onto_a_directory_is_reported(self):
        os.makedirs(os.path.join(self.tmp, 'targetdir'))
        app = self.app()
        app.new_file()
        app.editor.doc.insert('x')
        self.assertFalse(app.save(app.editor, os.path.join(self.tmp, 'targetdir')))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'targetdir')))


class TestHardLinks(FsTest):
    """vim's backupcopy=auto rule: keep the other names pointing at the file."""

    def test_a_hard_linked_file_is_written_in_place(self):
        a = self.write('a.txt', b'shared\n')
        b = os.path.join(self.tmp, 'b.txt')
        os.link(a, b)
        inode = os.stat(a).st_ino
        doc = Document(a)
        doc.insert('X')
        doc.save()
        self.assertEqual(os.stat(a).st_ino, inode, 'the link was broken')
        self.assertEqual(os.stat(b).st_ino, inode)
        self.assertEqual(self.read(b), b'Xshared\n', 'the other name went stale')

    def test_an_ordinary_file_still_gets_the_atomic_write(self):
        path = self.write('solo.txt', b'solo\n')
        inode = os.stat(path).st_ino
        doc = Document(path)
        doc.insert('Y')
        doc.save()
        self.assertNotEqual(os.stat(path).st_ino, inode,
                            'a plain file should be replaced, not overwritten')
        self.assertEqual(self.read(path), b'Ysolo\n')

    def test_a_hard_linked_file_still_refuses_a_stale_write(self):
        from tide.buffer import StaleFileError
        a = self.write('linked.txt', b'ours\n')
        os.link(a, os.path.join(self.tmp, 'other.txt'))
        doc = Document(a)
        doc.insert('X')
        time.sleep(0.01)
        with open(a, 'w') as f:
            f.write('theirs\n')
        with self.assertRaises(StaleFileError):
            doc.save()
        self.assertEqual(self.read(a), b'theirs\n')

    def test_the_mode_survives_an_in_place_write(self):
        a = self.write('modes.txt', b'x\n')
        os.link(a, os.path.join(self.tmp, 'modes2.txt'))
        os.chmod(a, 0o640)
        doc = Document(a)
        doc.insert('Y')
        doc.save()
        self.assertEqual(stat.S_IMODE(os.stat(a).st_mode), 0o640)


class TestAtomicity(FsTest):
    def test_a_reader_never_catches_a_half_written_file(self):
        """Another program reading the file while we save must always see a
        whole version of it - never an empty or truncated one."""
        path = self.write('atomic.txt', b'version -1 ' + b'y' * 4000)
        doc = Document(path)
        valid = set([self.read(path)])
        seen = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    with open(path, 'rb') as f:
                        seen.append(f.read())
                except (IOError, OSError):
                    seen.append(None)

        watcher = threading.Thread(target=reader)
        watcher.start()
        try:
            for i in range(40):
                doc.lines = ['version %d ' % i + 'y' * 4000]
                doc._version = doc._new_version()
                doc.save()
                valid.add(self.read(path))
        finally:
            stop.set()
            watcher.join()
        self.assertGreater(len(seen), 20, 'the reader barely ran')
        for observed in seen:
            self.assertIsNotNone(observed, 'the file was missing for a moment')
            self.assertIn(observed, valid,
                          'a reader saw %d bytes that were never a whole version'
                          % len(observed))


class TestHostileContent(FsTest):
    """A file cannot use the editor to talk to the terminal on its behalf."""

    def painted(self, data):
        from tide.term import Screen
        path = self.write('hostile.txt', data)
        app = self.app(path)
        app.screen = Screen(100, 24)
        app.render()
        return app.out.getvalue()

    def test_escape_sequences_in_a_file_are_never_emitted(self):
        painted = self.painted(
            b'ordinary line\n'
            b'\x1b]0;window title\x07'          # retitle the window
            b'\x1b]52;c;cGF5bG9hZA==\x07'       # write to the clipboard
            b'\x1b[200~rm -rf ~\n\x1b[201~'     # pretend to be a paste
            b'\x1b[2J\x1b[31mcolour\x1b[0m\n')
        for sequence, what in ((b'\x1b]0;', 'a window title'),
                               (b'\x1b]52', 'a clipboard write'),
                               (b'\x1b[200~', 'a bracketed paste'),
                               (b'\x1b[2J', 'a screen clear')):
            self.assertNotIn(sequence.decode('latin-1'), painted,
                             'the file managed to send %s' % what)

    def test_the_text_is_still_shown(self):
        painted = self.painted(b'ordinary line\n\x1b]0;title\x07\n')
        self.assertIn('ordinary line', painted)

    def test_control_characters_do_not_break_the_layout(self):
        # no NUL here: that trips the binary guard, which is a different test
        painted = self.painted(b'a\x07b\x08c\x1bd\n' + b'tail\n')
        self.assertIn('tail', painted)
        self.assertNotIn('\x07', painted, 'a bell from a file reached the terminal')
        self.assertNotIn('\x08', painted)


class TestSomebodyActuallyEditing(unittest.TestCase):
    """Ordinary use, through the real interface, on an awkward file."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-real-cfg-')
        self.tmp = tempfile.mkdtemp(prefix='tide-real-')
        self.name = u"notes for mé (draft).md"
        self.path = os.path.join(self.tmp, self.name)
        with open(self.path, 'w') as f:
            f.write('# Heading\n\nfirst line\nsecond line\n')
        self.s = Session([self.tmp], cols=100, rows=22, cwd=self.tmp,
                         env={'TIDE_CONFIG_HOME': self.cfg})
        self.s.pump(1.0)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def test_open_from_the_explorer_edit_save_reopen(self):
        pos = self.s.find('notes for')
        self.assertIsNotNone(pos, 'the file is not in the explorer')
        self.s.click(pos[0] + 1, pos[1])
        self.assertTrue(self.s.wait_for('first line'))
        target = self.s.find('second line')
        self.s.click(target[0], target[1])
        self.s.key(ESC + '[F')                       # end of the line
        self.s.type(' and a bit more')
        time.sleep(1.3)
        self.s.pump(0.5)
        self.assertEqual(self.read(),
                         '# Heading\n\nfirst line\nsecond line and a bit more\n')
        self.s.key(CTRL('w'))                        # close the tab
        self.s.pump(0.5)
        self.s.key(CTRL('p'))                        # and open it again
        self.s.type('notes')
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('and a bit more'))

    def test_undo_a_mistake_and_let_it_save(self):
        pos = self.s.find('notes for')
        self.s.click(pos[0] + 1, pos[1])
        self.assertTrue(self.s.wait_for('first line'))
        self.s.type('OOPS')
        time.sleep(1.2)
        self.s.pump(0.4)
        self.assertIn('OOPS', self.read())
        self.s.key(CTRL('z'))
        time.sleep(1.2)
        self.s.pump(0.4)
        self.assertNotIn('OOPS', self.read())
        self.assertEqual(self.read(), '# Heading\n\nfirst line\nsecond line\n')


class TestPlantedTempFile(FsTest):
    """Somebody else can write to the directory holding the file we edit."""

    def test_a_symlink_left_at_our_temp_name_is_not_written_through(self):
        victim = self.write('SECRET', b'do not touch\n')
        path = self.write('file.txt', b'hello\n')
        doc = Document(path)
        doc.insert('X')
        planted = ['%s.tide-tmp.%d' % (path, os.getpid())]
        planted += ['%s.tide-tmp.%d.%08x' % (path, os.getpid(), i)
                    for i in range(8)]          # guess a few of the random tails
        for name in planted:
            os.symlink(victim, name)
        doc.save()
        self.assertEqual(self.read(victim), b'do not touch\n',
                         'the save was steered onto another file')
        self.assertEqual(self.read(path), b'Xhello\n', 'the save did not land')
        for name in planted:
            self.assertTrue(os.path.islink(name), 'we wrote onto a planted name')

    def test_a_leftover_temp_file_does_not_block_saving(self):
        path = self.write('file.txt', b'hello\n')
        stale = '%s.tide-tmp.%d' % (path, os.getpid())
        with open(stale, 'wb') as f:
            f.write(b'from a process that died\n')
        doc = Document(path)
        doc.insert('X')
        doc.save()                                # a fresh name, so no clash
        self.assertEqual(self.read(path), b'Xhello\n')

    def test_a_new_file_gets_the_ordinary_mode(self):
        path = os.path.join(self.tmp, 'brand_new.txt')
        doc = Document()
        doc.insert('hi')
        doc.save(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, NEW_FILE_MODE, 'a new file came out %o' % mode)
        self.assertNotEqual(mode, 0o600, 'the temp file mode leaked through')


if __name__ == '__main__':
    unittest.main(verbosity=2)
