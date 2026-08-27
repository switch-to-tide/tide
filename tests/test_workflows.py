"""Whole editing sessions, the way they actually happen.

Creating a file, editing and saving it repeatedly, other tools rewriting it,
branches changing underneath, and a randomised run that checks one property
after every step: the editor never lets the file and the buffer differ without
knowing about it.
"""

import io
import os
import random
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
from tide.buffer import Document, StaleFileError


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-flow-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp(prefix='tide-flow-')

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self, *names):
        paths = []
        for name in names:
            path = os.path.join(self.tmp, name)
            if not os.path.exists(path):
                with open(path, 'w') as f:
                    f.write('%s: line one\n%s: line two\n' % (name, name))
            paths.append(path)
        app = App(root=self.tmp, paths=paths, out=io.StringIO())
        app.autosave_delay = 0.0
        return app

    def read(self, name):
        with open(os.path.join(self.tmp, name)) as f:
            return f.read()

    def outside_write(self, name, text):
        time.sleep(0.01)
        with open(os.path.join(self.tmp, name), 'w') as f:
            f.write(text)


class TestMakingAFile(WorkflowTest):
    def test_from_an_empty_buffer_to_a_file_on_disk(self):
        app = self.app()
        app.new_file()
        for ch in 'def main():':
            app.editor.doc.insert(ch, coalesce=(ch != ' '))
        app.editor.newline()                       # auto-indent supplies the four
        for ch in 'return 0':
            app.editor.doc.insert(ch, coalesce=(ch != ' '))
        self.assertTrue(app.editor.doc.dirty)
        app.autosave_tick()
        self.assertTrue(app.editor.doc.dirty, 'an untitled buffer was written somewhere')
        target = os.path.join(self.tmp, 'main.py')
        app.save(app.editor, target)
        self.assertEqual(self.read('main.py'), 'def main():\n    return 0')
        self.assertFalse(app.editor.doc.dirty)
        app.editor.doc.cursor = app.editor.doc.end_pos()
        app.editor.doc.insert(' + 1')
        app.autosave_tick()
        self.assertEqual(self.read('main.py'), 'def main():\n    return 0 + 1')

    def test_a_file_made_in_the_terminal_then_edited(self):
        app = self.app()
        with open(os.path.join(self.tmp, 'made.txt'), 'w') as f:
            f.write('from the shell\n')
        ed = app.open_file(os.path.join(self.tmp, 'made.txt'))
        self.assertEqual(ed.doc.text(), 'from the shell\n')
        ed.doc.cursor = (0, 0)
        ed.doc.insert('edited, ')
        app.autosave_tick()
        self.assertEqual(self.read('made.txt'), 'edited, from the shell\n')

    def test_save_as_asks_before_replacing_something(self):
        app = self.app('keep.txt')
        app.new_file()
        app.editor.doc.insert('new work')
        scratch = app.editor
        app.prompt_save_as(scratch)
        app.overlay.on_accept(os.path.join(self.tmp, 'keep.txt'))
        self.assertIsNotNone(app.overlay)
        self.assertIn('already exists', app.overlay.question)
        self.assertIn('keep.txt: line one', self.read('keep.txt'))
        app.overlay.on_yes()
        self.assertEqual(self.read('keep.txt'), 'new work')

    def test_save_as_to_a_new_name_just_saves(self):
        app = self.app()
        app.new_file()
        app.editor.doc.insert('fresh')
        app.prompt_save_as(app.editor)
        app.overlay.on_accept(os.path.join(self.tmp, 'fresh.txt'))
        self.assertEqual(self.read('fresh.txt'), 'fresh')


class TestOnlyOneBufferPerFile(WorkflowTest):
    def test_a_differently_cased_path_reuses_the_tab(self):
        app = self.app('Notes.txt')
        before = len(app.editors)
        app.open_file(os.path.join(self.tmp, 'notes.txt'))
        if os.path.exists(os.path.join(self.tmp, 'notes.txt')):
            self.assertEqual(len(app.editors), before,
                             'the same file opened in two buffers')

    def test_a_hard_link_reuses_the_tab(self):
        app = self.app('real.txt')
        link = os.path.join(self.tmp, 'linked.txt')
        os.link(os.path.join(self.tmp, 'real.txt'), link)
        before = len(app.editors)
        app.open_file(link)
        self.assertEqual(len(app.editors), before, 'a hard link opened a second buffer')

    def test_a_symlink_reuses_the_tab(self):
        app = self.app('target.txt')
        link = os.path.join(self.tmp, 'alias.txt')
        os.symlink(os.path.join(self.tmp, 'target.txt'), link)
        before = len(app.editors)
        app.open_file(link)
        self.assertEqual(len(app.editors), before)

    def test_genuinely_different_files_still_open_separately(self):
        app = self.app('one.txt')
        app.open_file(os.path.join(self.tmp, 'two.txt')) if os.path.exists(
            os.path.join(self.tmp, 'two.txt')) else None
        with open(os.path.join(self.tmp, 'two.txt'), 'w') as f:
            f.write('two\n')
        app.open_file(os.path.join(self.tmp, 'two.txt'))
        self.assertEqual(len(app.editors), 2)


class TestLongSessions(WorkflowTest):
    def test_many_edit_and_save_rounds(self):
        app = self.app('log.txt')
        ed = app.editors[0]
        expected = self.read('log.txt')
        for i in range(40):
            ed.doc.cursor = (0, 0)
            ed.doc.insert('%d ' % i)
            expected = '%d ' % i + expected
            app.autosave_tick()
            self.assertEqual(self.read('log.txt'), expected, 'round %d' % i)

    def test_two_files_at_once(self):
        app = self.app('a.txt', 'b.txt')
        for i in range(20):
            for ed in app.editors:
                ed.doc.cursor = (0, 0)
                ed.doc.insert('%d ' % i)
            app.autosave_tick()
        self.assertTrue(self.read('a.txt').startswith('19 18 17'))
        self.assertTrue(self.read('b.txt').startswith('19 18 17'))
        self.assertIn('a.txt: line one', self.read('a.txt'))
        self.assertIn('b.txt: line one', self.read('b.txt'))

    def test_a_formatter_rewriting_after_each_save(self):
        app = self.app('code.py')
        ed = app.editors[0]
        for i in range(10):
            ed.doc.cursor = (0, 0)
            ed.doc.insert('x%d=1\n' % i)
            app.autosave_tick()
            # something tidies the file up straight afterwards
            text = self.read('code.py').replace('=', ' = ')
            self.outside_write('code.py', text)
            app.check_disk_changes(force=True)
            self.assertEqual(ed.doc.text(), text, 'round %d did not pick up the tidy' % i)
            self.assertFalse(ed.doc.dirty)

    def test_closing_and_reopening_keeps_everything(self):
        app = self.app('notes.txt')
        app.editors[0].doc.cursor = (0, 0)
        app.editors[0].doc.insert('remember this ')
        app.close_tab(0)
        self.assertIsNone(app.overlay, 'auto-save should have handled it')
        again = self.app('notes.txt')
        self.assertTrue(again.editors[0].doc.text().startswith('remember this '))


class TestBranchesAndTools(WorkflowTest):
    def setUp(self):
        WorkflowTest.setUp(self)
        self.path = os.path.join(self.tmp, 'src.py')
        with open(self.path, 'w') as f:
            f.write('on main\n')
        git(self.tmp, 'init', '-q', '-b', 'main')
        git(self.tmp, 'config', 'user.email', 't@e.com')
        git(self.tmp, 'config', 'user.name', 'T')
        git(self.tmp, 'add', '-A')
        git(self.tmp, 'commit', '-q', '-m', 'first')
        git(self.tmp, 'checkout', '-q', '-b', 'other')
        with open(self.path, 'w') as f:
            f.write('on other\n')
        git(self.tmp, 'commit', '-q', '-am', 'second')

    def test_switching_branches_under_a_clean_buffer(self):
        app = self.app('src.py')
        self.assertEqual(app.editors[0].doc.text(), 'on other\n')
        git(self.tmp, 'checkout', '-q', 'main')
        app.check_disk_changes(force=True)
        self.assertEqual(app.editors[0].doc.text(), 'on main\n')
        self.assertFalse(app.editors[0].doc.dirty)

    def test_switching_branches_under_unsaved_work(self):
        app = self.app('src.py')
        app.autosave = False
        app.editors[0].doc.insert('MINE ')
        git(self.tmp, 'checkout', '-q', 'main')
        app.check_disk_changes(force=True)
        self.assertIsNotNone(app.overlay, 'the branch switch replaced unsaved work')
        self.assertIn('MINE ', app.editors[0].doc.text())

    def test_a_stash_and_pop_round_trip(self):
        app = self.app('src.py')
        app.editors[0].doc.cursor = (0, 0)
        app.editors[0].doc.insert('WIP ')
        app.autosave_tick()
        git(self.tmp, 'stash', '-q')
        app.check_disk_changes(force=True)
        self.assertEqual(app.editors[0].doc.text(), 'on other\n')
        git(self.tmp, 'stash', 'pop', '-q')
        app.check_disk_changes(force=True)
        self.assertEqual(app.editors[0].doc.text(), 'WIP on other\n')


class TestWhenSavingCannotWork(WorkflowTest):
    def test_a_read_only_directory_is_reported_and_recoverable(self):
        app = self.app('locked.txt')
        ed = app.editors[0]
        ed.doc.cursor = (0, 0)
        ed.doc.insert('attempt ')
        os.chmod(self.tmp, 0o500)
        try:
            app.autosave_tick()
            self.assertTrue(ed.doc.autosave_blocked)
            self.assertIn('Auto-save failed', app.message)
            self.assertNotIn('attempt ', self.read('locked.txt'))
            self.assertIn('attempt ', ed.doc.text(), 'the buffer lost the edit')
        finally:
            os.chmod(self.tmp, 0o700)
        app.save(ed)
        self.assertIn('attempt ', self.read('locked.txt'))
        self.assertFalse(ed.doc.dirty)

    def test_no_temp_files_survive_a_failure(self):
        app = self.app('x.txt')
        app.editors[0].doc.insert('y')
        os.chmod(self.tmp, 0o500)
        try:
            app.autosave_tick()
        finally:
            os.chmod(self.tmp, 0o700)
        self.assertEqual([f for f in os.listdir(self.tmp) if 'tide-tmp' in f], [])


class TestNothingIsLostQuietly(WorkflowTest):
    """A randomised session, checking one property after every single step.

    Either the file matches the buffer, or the editor knows they differ - it
    is dirty, or blocked pending an answer, or the file is gone.  What must
    never happen is the two drifting apart with the editor unaware, because
    that is the state where the next write loses somebody's work.
    """

    def check(self, app, name):
        doc = app.editors[0].doc
        app.check_disk_changes(force=True)
        app.autosave_tick()
        try:
            with open(os.path.join(self.tmp, name)) as f:
                disk = f.read()
        except IOError:
            self.assertTrue(doc.disk_missing or doc.autosave_blocked,
                            'the file vanished without the editor noticing')
            return
        if disk == doc.text():
            return
        self.assertTrue(doc.dirty or doc.autosave_blocked or app.overlay is not None,
                        'buffer and file differ with nothing flagged:\n'
                        ' buffer %r\n disk   %r' % (doc.text()[:60], disk[:60]))

    def test_random_editing_against_an_active_writer(self):
        for seed in range(6):
            rng = random.Random(seed)
            name = 'race%d.txt' % seed
            app = self.app(name)
            doc = app.editors[0].doc
            for step in range(60):
                what = rng.choice(['type', 'type', 'delete', 'outside', 'save',
                                   'undo', 'answer'])
                if what == 'type':
                    doc.cursor = doc.clamp((rng.randrange(len(doc.lines)), 0))
                    doc.insert(rng.choice(['a', 'word ', 'x\ny']))
                elif what == 'delete' and len(doc.lines) > 1:
                    doc.delete_range((0, 0), (1, 0))
                elif what == 'outside':
                    self.outside_write(name, 'outside %d\n' % step)
                elif what == 'save':
                    try:
                        app.save(app.editors[0])
                    except StaleFileError:
                        pass
                elif what == 'undo':
                    doc.undo()
                elif what == 'answer' and app.overlay is not None:
                    if rng.random() < 0.5:
                        app.overlay.on_yes()
                    elif app.overlay.on_no:
                        app.overlay.on_no()
                    app.overlay = None
                self.check(app, name)


class TestAWholeSessionInTheUI(unittest.TestCase):
    """One realistic sitting, driven through the real interface."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-sit-cfg-')
        self.tmp = tempfile.mkdtemp(prefix='tide-sit-')
        self.s = Session([self.tmp], cols=100, rows=22, cwd=self.tmp,
                         env={'TIDE_CONFIG_HOME': self.cfg})
        self.s.pump(1.0)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, name):
        with open(os.path.join(self.tmp, name)) as f:
            return f.read()

    def test_write_a_file_run_it_edit_it_again(self):
        # type a small program into the untitled buffer
        self.s.type("print('first run')")
        self.s.key(ESC + 's')                       # alt+s: save as
        self.s.pump(0.4)
        self.s.key(CTRL('u'))                       # clear the suggested path
        self.s.type(os.path.join(self.tmp, 'hello.py'))
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('Saved'))
        self.assertEqual(self.read('hello.py'), "print('first run')")
        # run it in the terminal
        self.s.key(CTRL('j'))
        self.s.type('python3 hello.py' + ENTER)
        self.assertTrue(self.s.wait_for('first run'))
        # a tool rewrites it
        self.s.type("printf \"print('rewritten')\\n\" > hello.py" + ENTER)
        self.assertTrue(self.s.wait_for("1 print('rewritten')"))
        # edit the rewritten file and let auto-save catch up
        pos = self.s.find("print('rewritten')")
        self.s.click(pos[0], pos[1])
        self.s.type('# ')
        time.sleep(1.3)
        self.s.pump(0.5)
        self.assertEqual(self.read('hello.py'), "# print('rewritten')\n")
        # and quit cleanly
        self.s.send_raw(CTRL('q'))
        self.assertTrue(self.s.wait_exit())
        self.assertEqual(sorted(os.listdir(self.tmp)), ['hello.py'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
