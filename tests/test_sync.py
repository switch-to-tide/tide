"""Living alongside other editors: vim, a code assistant, git, a formatter.

These are the cases where an IDE can quietly lose work: something rewrites a
file we have open, and the timing decides who wins.  The rule throughout is
the industry one - never discard the user's unsaved edits without asking, and
never overwrite someone else's newer content without asking.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import CTRL, ENTER, Session
from tide.app import App
from tide.buffer import Document, StaleFileError

START = 'first\nsecond\nthird\n'


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-sync-')
        self.path = os.path.join(self.tmp, 'shared.txt')
        self.write(START)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, path=None):
        """A plain in place write, the way `echo >` does it."""
        time.sleep(0.01)
        with open(path or self.path, 'w') as f:
            f.write(text)

    def rename_write(self, text):
        """How vim, formatters and code assistants usually write: a new file
        moved over the old one, so the path gets a different inode."""
        time.sleep(0.01)
        tmp = self.path + '.other-editor'
        with open(tmp, 'w') as f:
            f.write(text)
        os.replace(tmp, self.path)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def app(self, **kw):
        app = App(root=self.tmp, paths=[self.path], out=io.StringIO())
        app.autosave_delay = 0.0
        for key, value in kw.items():
            setattr(app, key, value)
        return app


class TestOtherEditorsWriting(SyncTest):
    def test_a_rename_style_write_is_noticed(self):
        app = self.app()
        self.rename_write('rewritten by vim\n')
        app.check_disk_changes(force=True)
        self.assertEqual(app.editor.doc.text(), 'rewritten by vim\n')

    def test_a_rename_style_write_over_unsaved_edits_asks(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        self.rename_write('rewritten by vim\n')
        app.check_disk_changes(force=True)
        self.assertIsNotNone(app.overlay, 'unsaved edits were replaced silently')
        self.assertIn('mine ', app.editor.doc.text())
        self.assertEqual(self.read(), 'rewritten by vim\n')

    def test_ten_rapid_writes_land_on_the_final_content(self):
        app = self.app()
        for i in range(10):
            self.rename_write('generation %d\n' % i)
            app.check_disk_changes(force=True)
        self.assertEqual(app.editor.doc.text(), 'generation 9\n')
        self.assertFalse(app.editor.doc.dirty)

    def test_the_leftover_temp_file_is_not_mistaken_for_ours(self):
        app = self.app()
        self.rename_write('done\n')
        app.check_disk_changes(force=True)
        self.assertEqual(sorted(os.listdir(self.tmp)), ['shared.txt'])

    def test_delete_then_recreate(self):
        app = self.app()
        os.remove(self.path)
        app.check_disk_changes(force=True)
        self.assertTrue(app.editor.doc.disk_missing)
        self.write('came back\n')
        app.editor.doc.autosave_blocked = False
        app.check_disk_changes(force=True)
        self.assertEqual(app.editor.doc.text(), 'came back\n')
        self.assertFalse(app.editor.doc.disk_missing)

    def test_git_checkout_style_swap_of_many_files(self):
        others = []
        for i in range(3):
            p = os.path.join(self.tmp, 'f%d.txt' % i)
            with open(p, 'w') as f:
                f.write('branch A %d\n' % i)
            others.append(p)
        app = self.app()
        for p in others:
            app.open_file(p)
        for i, p in enumerate(others):
            self.write('branch B %d\n' % i, p)
        app.check_disk_changes(force=True)
        for i, ed in enumerate(app.editors[1:]):
            self.assertEqual(ed.doc.text(), 'branch B %d\n' % i)


class TestSaveRaces(SyncTest):
    def test_our_edit_never_clobbers_a_newer_file(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        self.write('theirs\n')
        app.save()
        self.assertEqual(self.read(), 'theirs\n', 'their newer content was lost')
        self.assertIsNotNone(app.overlay)

    def test_auto_save_backs_off_until_the_conflict_is_answered(self):
        app = self.app()
        app.editor.doc.insert('mine ')
        self.write('theirs\n')
        for _ in range(5):                       # several auto-save cycles
            app.autosave_tick()
        self.assertEqual(self.read(), 'theirs\n')

    def test_answering_keep_mine_then_saving_wins(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        self.write('theirs\n')
        app.check_disk_changes(force=True)
        app.overlay.on_no()                       # "keep my version"
        app.overlay = None
        app.save()
        self.assertEqual(self.read(), 'mine ' + START)

    def test_answering_reload_takes_their_version(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        self.write('theirs\n')
        app.check_disk_changes(force=True)
        app.overlay.on_yes()                      # "reload"
        app.overlay = None
        self.assertEqual(app.editor.doc.text(), 'theirs\n')
        self.assertFalse(app.editor.doc.dirty)

    def test_two_editors_of_the_same_file(self):
        first = self.app(autosave=False)
        second = self.app(autosave=False)
        first.editor.doc.insert('from one ')
        first.save()
        second.editor.doc.insert('from two ')
        second.save()                             # its view of the file is stale
        self.assertEqual(self.read(), 'from one ' + START)
        self.assertIsNotNone(second.overlay, 'the second writer clobbered the first')

    def test_a_save_after_reloading_is_allowed_again(self):
        app = self.app(autosave=False)
        app.editor.doc.insert('mine ')
        self.write('theirs\n')
        with self.assertRaises(StaleFileError):
            app.editor.doc.save()
        app.editor.doc.reload()
        app.editor.doc.cursor = (0, 0)
        app.editor.doc.insert('after reload ')
        app.editor.doc.save()
        self.assertEqual(self.read(), 'after reload theirs\n')


class TestWriteRaces(SyncTest):
    """The narrow windows: another writer landing mid save, or mid read."""

    def test_the_temp_file_is_per_process(self):
        # two editors saving the same file must not share a scratch name
        doc = Document(self.path)
        doc.insert('x')
        seen = {}
        real = os.replace

        def spy(src, dst):
            seen['tmp'] = src
            return real(src, dst)
        os.replace = spy
        try:
            doc.save()
        finally:
            os.replace = real
        self.assertIn('.tide-tmp.%d' % os.getpid(), seen['tmp'])

    def test_a_write_that_lands_while_we_save_is_caught(self):
        doc = Document(self.path)
        doc.cursor = (0, 0)
        doc.insert('mine ')
        original = Document.__dict__['_copy_metadata']   # keep the descriptor

        def sneak(_target, _tmp):
            time.sleep(0.01)
            with open(self.path, 'w') as f:   # another program, mid save
                f.write('snuck in\n')
        Document._copy_metadata = staticmethod(sneak)
        try:
            with self.assertRaises(StaleFileError):
                doc.save()
        finally:
            Document._copy_metadata = original
        self.assertEqual(self.read(), 'snuck in\n')
        self.assertEqual([f for f in os.listdir(self.tmp) if 'tide-tmp' in f], [])

    def test_a_file_still_being_written_is_left_alone(self):
        doc = Document(self.path)
        moving = iter([(10, 100), (11, 250)])    # the stamp changes mid read

        def unsettled():
            try:
                return next(moving)
            except StopIteration:
                return (11, 250)
        doc.disk_state = unsettled
        self.assertEqual(doc.disk_status(), 'same',
                         'reloaded a file that was still being written')

    def test_a_rewrite_that_restores_the_timestamp_is_noticed(self):
        # `cp -p`, `touch -r` and some build tools put the mtime back
        doc = Document(self.path)
        before = os.stat(self.path)
        with open(self.path, 'w') as f:
            f.write('replaced but backdated\n'.ljust(len(START)))
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(os.stat(self.path).st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(doc.disk_status(), 'changed',
                         'a backdated rewrite slipped past')

    def test_a_permission_change_alone_is_not_a_content_change(self):
        doc = Document(self.path)
        os.chmod(self.path, 0o640)
        try:
            self.assertEqual(doc.disk_status(), 'same',
                             'chmod looked like an edit')
        finally:
            os.chmod(self.path, 0o644)

    def test_a_settled_change_is_picked_up(self):
        doc = Document(self.path)
        self.write('finished writing\n')
        self.assertEqual(doc.disk_status(), 'changed')
        doc.reload()
        self.assertEqual(doc.text(), 'finished writing\n')

    def test_a_partially_written_file_is_reloaded_once_it_settles(self):
        app = self.app()
        chunks = ['line %d\n' % i for i in range(50)]
        with open(self.path, 'w') as f:          # a slow, non atomic writer
            for chunk in chunks[:10]:
                f.write(chunk)
            f.flush()
            app.check_disk_changes(force=True)   # mid write
            for chunk in chunks[10:]:
                f.write(chunk)
        app.check_disk_changes(force=True)       # after it finished
        self.assertEqual(app.editor.doc.lines[49], 'line 49')


class TestHostileFiles(SyncTest):
    """Nothing here may crash the editor."""

    def check(self, app):
        app.check_disk_changes(force=True)
        app.autosave_tick()
        app.refresh_git()

    def test_replaced_by_a_directory(self):
        app = self.app()
        os.remove(self.path)
        os.mkdir(self.path)
        self.check(app)
        self.assertTrue(app.editor.doc.disk_missing)
        os.rmdir(self.path)

    def test_replaced_by_binary_content(self):
        app = self.app()
        with open(self.path, 'wb') as f:
            f.write(b'\x00\xff\xfe not text at all')
        self.check(app)
        self.assertTrue(app.editor.doc.readonly)
        app.editor.doc.insert('x')
        app.autosave_tick()
        with open(self.path, 'rb') as f:
            self.assertTrue(f.read().startswith(b'\x00\xff\xfe'))

    def test_permissions_taken_away(self):
        app = self.app()
        os.chmod(self.path, 0o000)
        try:
            self.check(app)
            app.editor.doc.insert('x')
            app.autosave_tick()
        finally:
            os.chmod(self.path, 0o644)

    def test_file_grows_beyond_the_limit(self):
        app = self.app(max_file_bytes=1024)
        self.write('y' * 20000 + '\n')
        started = time.time()
        self.check(app)
        self.assertLess(time.time() - started, 2.0)
        self.assertNotIn('yyyy', app.editor.doc.text())
        self.assertTrue(app.editor.doc.autosave_blocked)

    def test_the_whole_directory_disappears(self):
        app = self.app()
        shutil.rmtree(self.tmp)
        self.check(app)
        os.makedirs(self.tmp)
        self.write(START)

    def test_a_symlink_target_is_swapped(self):
        target = os.path.join(self.tmp, 'real.txt')
        link = os.path.join(self.tmp, 'link.txt')
        with open(target, 'w') as f:
            f.write('through the link\n')
        os.symlink(target, link)
        app = self.app()
        ed = app.open_file(link)
        self.write('changed through the target\n', target)
        app.check_disk_changes(force=True)
        self.assertEqual(ed.doc.text(), 'changed through the target\n')
        ed.doc.cursor = (0, 0)
        ed.doc.insert('and back ')
        ed.doc.save()
        self.assertTrue(os.path.islink(link), 'the link was replaced by a file')
        with open(target) as f:
            self.assertEqual(f.read(), 'and back changed through the target\n')


class TestAlongsideARealShell(unittest.TestCase):
    """The actual scenario: something in the built-in terminal edits our file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-sync-ui-')
        self.path = os.path.join(self.tmp, 'shared.txt')
        with open(self.path, 'w') as f:
            f.write(START)
        self.s = Session(['shared.txt', self.tmp], cols=88, rows=20, cwd=self.tmp)
        self.s.pump(0.8)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def test_a_rename_style_rewrite_shows_up_in_the_editor(self):
        self.s.key(CTRL('j'))
        self.s.type('printf "tool wrote this\\n" > t.txt && mv t.txt shared.txt' + ENTER)
        self.assertTrue(self.s.wait_for('1 tool wrote this'),
                        'the editor never picked up the rewrite')

    def test_a_loop_of_rewrites_does_not_break_anything(self):
        self.s.key(CTRL('j'))
        self.s.type('for i in $(seq 1 12); do printf "round $i\\n" > shared.txt; '
                    'sleep 0.15; done' + ENTER)
        self.assertTrue(self.s.wait_for('round 12'))
        time.sleep(1.0)
        self.s.pump(0.6)
        self.assertIn('1 round 12', self.s.screen())
        self.assertTrue(self.s.alive(), 'the editor died')

    def test_unsaved_edits_are_not_lost_to_an_outside_write(self):
        self.s.type('MY UNSAVED WORK ')          # dirty, auto-save will follow
        self.s.key(CTRL('j'))
        self.s.type('printf "outside\\n" > shared.txt' + ENTER)
        time.sleep(1.5)
        self.s.pump(0.8)
        screen = self.s.screen()
        self.assertTrue('MY UNSAVED WORK' in screen or 'changed on disk' in screen,
                        'the edits vanished without a word: %r' % screen[-300:])
        self.assertTrue(self.s.alive())

    def test_editing_continues_after_the_file_is_replaced(self):
        self.s.key(CTRL('j'))
        self.s.type('printf "brand new\\n" > shared.txt' + ENTER)
        self.assertTrue(self.s.wait_for('1 brand new'))
        pos = self.s.find('brand new')
        self.s.click(pos[0], pos[1])
        self.s.type('EDITED ')
        time.sleep(1.3)
        self.s.pump(0.5)
        self.assertEqual(self.read(), 'EDITED brand new\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
