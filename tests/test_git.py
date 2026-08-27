"""Git decorations: status letters in the explorer, change bars in the gutter."""

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
from tide.git import Git

COMMITTED = 'one\ntwo\nthree\nfour\n'


def git(repo, *args):
    return subprocess.check_output(
        ['git', '-C', repo] + list(args),
        stderr=subprocess.DEVNULL).decode('utf-8', 'replace')


def make_repo(prefix='tide-git-'):
    tmp = tempfile.mkdtemp(prefix=prefix)
    git(tmp, 'init', '-q', '-b', 'main')
    git(tmp, 'config', 'user.email', 'test@example.com')
    git(tmp, 'config', 'user.name', 'Test')
    with open(os.path.join(tmp, 'tracked.txt'), 'w') as f:
        f.write(COMMITTED)
    os.mkdir(os.path.join(tmp, 'sub'))
    with open(os.path.join(tmp, 'sub', 'nested.txt'), 'w') as f:
        f.write('nested\n')
    git(tmp, 'add', '-A')
    git(tmp, 'commit', '-q', '-m', 'init')
    return tmp


class TestGitQueries(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()
        self.g = Git(self.repo)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.repo, name)

    def write(self, name, text):
        with open(self.path(name), 'w') as f:
            f.write(text)

    def test_clean_repo_has_no_marks(self):
        self.g.refresh(force=True)
        self.assertTrue(self.g.enabled)
        self.assertEqual(self.g.statuses, {})
        self.assertEqual(self.g.line_status(self.path('tracked.txt'), 1), {})

    def test_untracked_file(self):
        self.write('fresh.txt', 'a\nb\nc\n')
        self.g.refresh(force=True)
        self.assertEqual(self.g.status_for(self.path('fresh.txt')), 'U')
        marks = self.g.line_status(self.path('fresh.txt'), 1)
        self.assertEqual(set(marks.values()), {'added'})
        self.assertEqual(len(marks), 4)          # three lines plus the last empty one

    def test_modified_file_marks_only_the_changed_lines(self):
        self.write('tracked.txt', 'one\nTWO CHANGED\nthree\nfour\n')
        self.g.refresh(force=True)
        self.assertEqual(self.g.status_for(self.path('tracked.txt')), 'M')
        marks = self.g.line_status(self.path('tracked.txt'), 1)
        self.assertEqual(marks, {1: 'modified'})

    def test_added_lines_are_green_not_blue(self):
        self.write('tracked.txt', 'one\ntwo\nEXTRA\nthree\nfour\n')
        self.g.refresh(force=True)
        self.assertEqual(self.g.line_status(self.path('tracked.txt'), 1), {2: 'added'})

    def test_deleted_lines_leave_a_mark(self):
        self.write('tracked.txt', 'one\nfour\n')
        self.g.refresh(force=True)
        marks = self.g.line_status(self.path('tracked.txt'), 1)
        self.assertIn('deleted', marks.values())

    def test_staged_file_reads_as_added(self):
        self.write('staged.txt', 'x\n')
        git(self.repo, 'add', 'staged.txt')
        self.g.refresh(force=True)
        self.assertEqual(self.g.status_for(self.path('staged.txt')), 'A')

    def test_deleted_file(self):
        os.remove(self.path('tracked.txt'))
        self.g.refresh(force=True)
        self.assertEqual(self.g.status_for(self.path('tracked.txt')), 'D')

    def test_directories_inherit_a_mark(self):
        self.write('sub/nested.txt', 'changed\n')
        self.g.refresh(force=True)
        self.assertEqual(self.g.status_for(self.path('sub'), is_dir=True), 'M')
        self.assertIsNone(self.g.status_for(self.path('sub'), is_dir=False))

    def test_untracked_only_directory_reads_as_untracked(self):
        os.mkdir(self.path('brand'))
        self.write('brand/new.txt', 'x\n')
        self.g.refresh(force=True)
        self.assertEqual(self.g.status_for(self.path('brand'), is_dir=True), 'U')

    def test_line_marks_are_cached_by_stamp(self):
        self.write('tracked.txt', 'one\nCHANGED\nthree\nfour\n')
        self.g.refresh(force=True)
        first = self.g.line_status(self.path('tracked.txt'), 'stamp-1')
        again = self.g.line_status(self.path('tracked.txt'), 'stamp-1')
        self.assertIs(first, again, 'the diff should not be recomputed')
        self.write('tracked.txt', 'one\ntwo\nthree\nfour\nFIVE\n')
        fresh = self.g.line_status(self.path('tracked.txt'), 'stamp-2')
        self.assertIsNot(first, fresh)
        self.assertEqual(fresh, {4: 'added'})

    def test_a_directory_outside_any_repo_is_disabled(self):
        plain = tempfile.mkdtemp(prefix='tide-nogit-')
        try:
            g = Git(plain)
            self.assertFalse(g.enabled)
            self.assertIsNone(g.status_for(os.path.join(plain, 'x')))
            self.assertEqual(g.line_status(os.path.join(plain, 'x'), 1), {})
        finally:
            shutil.rmtree(plain, ignore_errors=True)


class TestGitInTheUI(unittest.TestCase):
    cols, rows = 92, 22

    def setUp(self):
        self.repo = make_repo('tide-git-ui-')
        with open(os.path.join(self.repo, 'untracked.txt'), 'w') as f:
            f.write('brand new\nlines here\n')
        with open(os.path.join(self.repo, 'tracked.txt'), 'w') as f:
            f.write('one\nCHANGED\nthree\nfour\n')
        self.s = Session(['tracked.txt', self.repo], cols=self.cols, rows=self.rows,
                         cwd=self.repo)
        self.s.pump(1.2)                     # the first git refresh

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.repo, ignore_errors=True)

    def tree_row(self, name):
        """Screen row of an explorer entry (columns 0-23; 24 holds the letter)."""
        for y, line in enumerate(self.s.text()):
            if name in line[:24]:
                return y
        return None

    def bar(self, y):
        """(glyph, colour name) of the change bar column for a screen row."""
        cell = self.s.cell(26, y)
        return cell[0], {114: 'green', 39: 'blue', 203: 'red'}.get(cell[1], 'none')

    def test_explorer_letters_and_colours(self):
        y = self.tree_row('untracked.txt')
        self.assertIsNotNone(y, 'untracked.txt missing from the explorer')
        self.assertEqual(self.s.cell(self.s.line(y).index('U'), y)[0], 'U')
        self.assertEqual(self.s.cell(3, y)[1], 114, 'untracked should be green')
        y = self.tree_row('tracked.txt')
        self.assertIn('M', self.s.line(y))
        self.assertEqual(self.s.cell(3, y)[1], 179, 'modified should be orange')

    def test_unchanged_files_are_left_alone(self):
        y = self.tree_row('sub')
        self.assertEqual(self.s.cell(24, y)[0], ' ', 'directories get no letter')
        row = self.s.line(self.tree_row('LICENSE') or 0) if self.tree_row('LICENSE') else ''
        self.assertNotIn(' M ', row)

    def test_gutter_bar_is_blue_for_a_modified_line(self):
        glyph, colour = self.bar(3)          # line 2 of the file, the changed one
        self.assertEqual(colour, 'blue', 'expected a blue bar on the edited line')
        self.assertEqual(glyph, '▌')
        self.assertEqual(self.bar(2)[1], 'none', 'unchanged lines get no bar')

    def test_gutter_bar_is_green_for_a_new_file(self):
        self.s.key(CTRL('p'))
        self.s.type('untracked')
        self.s.key(ENTER)
        self.s.pump(1.4)
        self.assertEqual(self.bar(2)[1], 'green')
        self.assertEqual(self.bar(3)[1], 'green')

    def test_typing_makes_a_bar_appear(self):
        self.assertEqual(self.bar(4)[1], 'none')
        pos = self.s.find('three')
        self.s.click(pos[0], pos[1])
        self.s.key('\x1b[F')                 # end of the line
        self.s.type(' EDITED')
        deadline = time.time() + 6
        while time.time() < deadline:
            if self.bar(4)[1] == 'blue':
                break
            self.s.pump(0.4)
        self.assertEqual(self.bar(4)[1], 'blue', 'the new edit never got a bar')

    def test_committing_from_the_terminal_clears_the_marks(self):
        self.assertEqual(self.bar(3)[1], 'blue')
        self.s.key(CTRL('j'))
        self.s.type('git add -A && git commit -q -m sync' + ENTER)
        deadline = time.time() + 8
        while time.time() < deadline:
            if self.bar(3)[1] == 'none':
                break
            self.s.pump(0.5)
        self.assertEqual(self.bar(3)[1], 'none', 'bars survived a commit')
        self.assertNotIn(' M ', self.s.line(self.tree_row('tracked.txt') or 0))

    def test_no_gutter_column_outside_a_repo(self):
        plain = tempfile.mkdtemp(prefix='tide-nogit-ui-')
        try:
            with open(os.path.join(plain, 'a.txt'), 'w') as f:
                f.write('hello\nworld\n')
            s = Session(['a.txt', plain], cols=self.cols, rows=self.rows, cwd=plain)
            s.pump(1.0)
            self.assertIn('1 hello', s.screen())
            self.assertEqual(s.cell(26, 2)[0], ' ')
            s.close()
        finally:
            shutil.rmtree(plain, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
