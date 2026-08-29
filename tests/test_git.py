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


class TestIgnoredFiles(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo('tide-ignored-')
        with open(os.path.join(self.repo, '.gitignore'), 'w') as f:
            f.write('*.log\nscratch/\n')
        with open(os.path.join(self.repo, 'debug.log'), 'w') as f:
            f.write('noise\n')
        os.mkdir(os.path.join(self.repo, 'scratch'))
        with open(os.path.join(self.repo, 'scratch', 'note.txt'), 'w') as f:
            f.write('x\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'ignore rules')
        self.g = Git(self.repo)
        self.g.refresh(force=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.repo, name)

    def test_it_knows_what_git_ignores(self):
        paths = [self.path(n) for n in ('tracked.txt', 'debug.log', 'scratch',
                                        '.gitignore')]
        self.g.mark_ignored(paths)
        self.assertTrue(self.g.is_ignored(self.path('debug.log')))
        self.assertTrue(self.g.is_ignored(self.path('scratch')))
        self.assertFalse(self.g.is_ignored(self.path('tracked.txt')))
        self.assertFalse(self.g.is_ignored(self.path('.gitignore')))

    def test_the_answer_is_cached(self):
        paths = [self.path('debug.log'), self.path('tracked.txt')]
        self.g.mark_ignored(paths)
        calls = []
        real = self.g._run
        self.g._run = lambda a, timeout=3.0, stdin=None: (
            calls.append(a[0]), real(a, timeout, stdin))[1]
        for _ in range(20):
            self.g.mark_ignored(paths)
        self.assertEqual(calls, [], 'git was asked again for the same paths')

    def test_an_ignored_file_has_no_status(self):
        self.assertIsNone(self.g.status_for(self.path('debug.log')))

    def test_they_are_greyed_in_the_explorer(self):
        s = Session([self.repo], cols=90, rows=20, cwd=self.repo,
                    env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
        try:
            s.pump(1.8)
            rows = {}
            for y, line in enumerate(s.text()):
                name = line[:26].strip().strip('│ ')
                if name:
                    rows[name] = s.cell(5, y)[1]
            self.assertIn('debug.log', rows, 'the ignored file is not listed')
            self.assertIn('tracked.txt', rows)
            from tide import theme
            theme.apply('dark', 'modern')
            self.assertEqual(rows['debug.log'], theme.GIT_IGNORED,
                             'it should be greyed out')
            self.assertNotEqual(rows['tracked.txt'], 241)
            row = [l for l in s.text() if 'debug.log' in l[:24]][0]
            self.assertNotIn('U', row[:26], 'an ignored file got a status letter')
        finally:
            s.close()


class TestOverviewRuler(unittest.TestCase):
    """Ticks down the scrollbar showing where the changes are."""

    def setUp(self):
        self.repo = make_repo('tide-ruler-')
        self.path = os.path.join(self.repo, 'long.py')
        self.lines = ['line %d' % i for i in range(200)]
        self.write(self.lines)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'long file')

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def write(self, lines):
        with open(self.path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def column(self, session, width=90, top=None, bottom=14):
        """The ruler as a picture, wherever the frame put the scrollbar."""
        from tide import theme
        theme.apply('dark', 'modern')
        names = {theme.GIT_LINE_ADDED: 'G', theme.GIT_LINE_MODIFIED: 'B',
                 theme.GIT_LINE_DELETED: 'R'}
        top = session.BODY_ROW if top is None else top
        bar = (theme.SCROLL_TRACK, theme.SCROLL_THUMB, theme.SCROLL_THUMB_HL)
        for x in range(width - 1, width - 5, -1):
            column = [session.cell(x, y) for y in range(top, bottom)]
            if not any(cell[2] in bar for cell in column):
                continue                      # not the scrollbar's column
            return ''.join(names.get(cell[1], '.') for cell in column)
        return '.' * (bottom - top)

    def test_changes_show_up_at_their_position_in_the_file(self):
        lines = list(self.lines)
        lines[5] = 'line 5 CHANGED'
        lines[100] = 'line 100 CHANGED'
        lines.insert(150, 'brand new')
        del lines[190]
        self.write(lines)
        s = Session(['long.py', self.repo], cols=90, rows=24, cwd=self.repo,
                    env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
        try:
            s.pump(2.0)
            marks = self.column(s)
            self.assertGreaterEqual(len(marks.replace('.', '')), 3,
                                    'the ruler is empty: %r' % marks)
            self.assertIn('B', marks, 'no mark for the edited lines')
            self.assertIn('G', marks, 'no mark for the added line')
            first = marks.index([c for c in marks if c != '.'][0])
            last = len(marks) - 1 - marks[::-1].index(
                [c for c in reversed(marks) if c != '.'][0])
            self.assertLess(first, 3, 'the early change is not near the top')
            self.assertGreater(last, len(marks) - 4,
                               'the late change is not near the bottom')
        finally:
            s.close()

    def test_the_thumb_is_still_there(self):
        lines = list(self.lines)
        lines[3] = 'changed'
        self.write(lines)
        s = Session(['long.py', self.repo], cols=90, rows=24, cwd=self.repo,
                    env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
        try:
            s.pump(2.0)
            from tide import theme
            theme.apply('dark', 'modern')
            found = set()
            for x in range(89, 85, -1):
                found |= set(s.cell(x, y)[2] for y in range(s.BODY_ROW, 14))
            self.assertTrue(theme.SCROLL_THUMB in found
                            or theme.SCROLL_THUMB_HL in found,
                            'the scrollbar thumb was painted over')
            self.assertIn(theme.SCROLL_TRACK, found, 'no track')
        finally:
            s.close()

    def test_a_short_file_has_no_scrollbar_and_no_ruler(self):
        short = os.path.join(self.repo, 'short.py')
        with open(short, 'w') as f:
            f.write('one\ntwo\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'short')
        with open(short, 'w') as f:
            f.write('one\nTWO CHANGED\n')
        s = Session(['short.py', self.repo], cols=90, rows=24, cwd=self.repo,
                    env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
        try:
            s.pump(2.0)
            self.assertEqual(self.column(s).strip('.'), '',
                             'a file that fits should have no ruler')
            self.assertNotIn(237, [s.cell(89, y)[2] for y in range(2, 14)])
        finally:
            s.close()


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

    @staticmethod
    def bar_in(session, y):
        """The change-bar glyph on a row of another session, if there is one."""
        for x in range(20, 40):
            if session.cell(x, y)[0] in ('▌', '▁'):
                return session.cell(x, y)[0]
        return ' '

    def bar(self, y):
        """(glyph, colour name) of the change bar on a screen row.

        Found rather than assumed: which column the editor's gutter starts in
        depends on how the pane is framed.
        """
        names = {114: 'green', 39: 'blue', 203: 'red',
                 108: 'green', 74: 'blue', 167: 'red',
                 118: 'green', 141: 'blue', 197: 'red'}
        for x in range(20, 40):
            glyph, fg, _bg, _attr = self.s.cell(x, y)
            if glyph in ('▌', '▁'):
                return glyph, names.get(fg, 'none')
        return ' ', 'none'

    def test_explorer_letters_and_colours(self):
        y = self.tree_row('untracked.txt')
        self.assertIsNotNone(y, 'untracked.txt missing from the explorer')
        self.assertEqual(self.s.cell(self.s.line(y).index('U'), y)[0], 'U')
        self.assertEqual(self.s.cell(5, y)[1], 114, 'untracked should be green')
        y = self.tree_row('tracked.txt')
        self.assertIn('M', self.s.line(y))
        self.assertEqual(self.s.cell(5, y)[1], 179, 'modified should be orange')

    def test_unchanged_files_are_left_alone(self):
        # 'sub' holds nothing that changed, so it carries no letter - a folder
        # that does hold something gets one, which TestFolderColours covers
        row = self.s.line(self.tree_row('sub'))
        self.assertNotIn('M', row.split('sub')[1], 'an untouched folder got a letter')
        self.assertNotIn('U', row.split('sub')[1])

    def test_gutter_bar_is_blue_for_a_modified_line(self):
        glyph, colour = self.bar(self.s.BODY_ROW + 1)          # line 2 of the file, the changed one
        self.assertEqual(colour, 'blue', 'expected a blue bar on the edited line')
        self.assertEqual(glyph, '▌')
        self.assertEqual(self.bar(self.s.BODY_ROW + 0)[1], 'none', 'unchanged lines get no bar')

    def test_gutter_bar_is_green_for_a_new_file(self):
        self.s.key(CTRL('p'))
        self.s.type('untracked')
        self.s.key(ENTER)
        self.s.pump(1.4)
        self.assertEqual(self.bar(self.s.BODY_ROW + 0)[1], 'green')
        self.assertEqual(self.bar(self.s.BODY_ROW + 1)[1], 'green')

    def test_typing_makes_a_bar_appear(self):
        self.assertEqual(self.bar(self.s.BODY_ROW + 2)[1], 'none')
        pos = self.s.find('three')
        self.s.click(pos[0], pos[1])
        self.s.key('\x1b[F')                 # end of the line
        self.s.type(' EDITED')
        deadline = time.time() + 6
        while time.time() < deadline:
            if self.bar(self.s.BODY_ROW + 2)[1] == 'blue':
                break
            self.s.pump(0.4)
        self.assertEqual(self.bar(self.s.BODY_ROW + 2)[1], 'blue', 'the new edit never got a bar')

    def test_committing_from_the_terminal_clears_the_marks(self):
        self.assertEqual(self.bar(self.s.BODY_ROW + 1)[1], 'blue')
        self.s.key(CTRL('j'))
        self.s.type('git add -A && git commit -q -m sync' + ENTER)
        deadline = time.time() + 8
        while time.time() < deadline:
            if self.bar(self.s.BODY_ROW + 1)[1] == 'none':
                break
            self.s.pump(0.5)
        self.assertEqual(self.bar(self.s.BODY_ROW + 1)[1], 'none', 'bars survived a commit')
        self.assertNotIn(' M ', self.s.line(self.tree_row('tracked.txt') or 0))

    def test_no_gutter_column_outside_a_repo(self):
        plain = tempfile.mkdtemp(prefix='tide-nogit-ui-')
        try:
            with open(os.path.join(plain, 'a.txt'), 'w') as f:
                f.write('hello\nworld\n')
            s = Session(['a.txt', plain], cols=self.cols, rows=self.rows, cwd=plain)
            s.pump(1.0)
            self.assertIn('1 hello', s.screen())
            self.assertEqual(self.bar_in(s, s.BODY_ROW), ' ',
                             'a gutter bar outside a repository')
            s.close()
        finally:
            shutil.rmtree(plain, ignore_errors=True)


class TestTabDecorations(unittest.TestCase):
    """File tabs carry the same letter and colour as the explorer."""

    def setUp(self):
        import io
        from tide.app import App
        from tide.term import Screen
        self.repo = make_repo()
        with open(os.path.join(self.repo, '.gitignore'), 'w') as f:
            f.write('*.log\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'ignore logs')
        with open(os.path.join(self.repo, 'tracked.txt'), 'w') as f:
            f.write(COMMITTED + 'five\n')                 # modified
        for name, text in (('fresh.txt', 'new\n'), ('noise.log', 'x\n')):
            with open(os.path.join(self.repo, name), 'w') as f:
                f.write(text)
        self.cfg = tempfile.mkdtemp(prefix='tide-tabgit-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.app = App(root=self.repo, paths=[], out=io.StringIO())
        self.app.screen = Screen(110, 24)
        self.app.show_term = False
        for name in ('tracked.txt', 'fresh.txt', 'noise.log', 'sub/nested.txt'):
            self.app.open_file(os.path.join(self.repo, name))
        self.app.git.refresh(force=True)
        self.app.tree.refresh()
        self.app.render()

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def tab_row(self):
        y = self.app.rects['tabs'].y
        return ''.join(c[0] or ' ' for c in self.app.screen.cells[y])

    def tab_colour(self, name):
        row = self.tab_row()
        y = self.app.rects['tabs'].y
        return self.app.screen.cells[y][row.index(name)][1]

    def tree_colour(self, name):
        side = self.app.rects['sidebar']
        for y in range(side.y, side.y2):
            cells = self.app.screen.cells[y]
            if name in ''.join(c[0] or ' ' for c in cells[side.x:side.x2]):
                return cells[side.x + 3][1]
        return None

    def test_the_letters_are_on_the_tabs(self):
        row = self.tab_row()
        self.assertIn('tracked.txt  M ', row, row)
        self.assertIn('fresh.txt  U ', row, row)

    def test_the_colours_match_the_explorer(self):
        for name in ('tracked.txt', 'fresh.txt'):
            self.assertEqual(self.tab_colour(name), self.tree_colour(name),
                             '%s is a different colour in the two places' % name)

    def test_an_unchanged_file_gets_no_letter(self):
        row = self.tab_row()
        self.assertIn('nested.txt   ', row, row)
        self.assertNotEqual(self.tab_colour('nested.txt'),
                            self.tab_colour('tracked.txt'))

    def test_an_ignored_file_is_greyed_with_no_letter(self):
        from tide import theme
        row = self.tab_row()
        self.assertIn('noise.log   ', row, row)
        self.assertEqual(self.tab_colour('noise.log'), theme.GIT_IGNORED)
        self.assertEqual(self.tab_colour('noise.log'), self.tree_colour('noise.log'))

    def test_the_letter_follows_the_file(self):
        with open(os.path.join(self.repo, 'tracked.txt'), 'w') as f:
            f.write(COMMITTED)                            # put it back
        self.app.git.refresh(force=True)
        self.app.render()
        self.assertNotIn('tracked.txt  M ', self.tab_row())

    def test_the_unsaved_marker_still_has_its_own_slot(self):
        editor = self.app.editors[0]
        editor.doc.cursor = (0, 0)
        editor.doc.insert('x')
        self.app.render()
        self.assertIn('tracked.txt* M ', self.tab_row(), self.tab_row())


class TestRulerRuns(unittest.TestCase):
    """A run of changed lines is a bar of its own height, not a tick."""

    def setUp(self):
        import io
        from tide.app import App
        from tide.term import Screen
        self.repo = make_repo(prefix='tide-runs-')
        self.path = os.path.join(self.repo, 'long.py')
        self.lines = ['line %d' % i for i in range(200)]
        with open(self.path, 'w') as f:
            f.write('\n'.join(self.lines) + '\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'long')
        self.cfg = tempfile.mkdtemp(prefix='tide-runs-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.app = App(root=self.repo, paths=[], out=io.StringIO())
        self.app.screen = Screen(90, 26)
        self.app.show_term = False

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def ruler(self, lines):
        from tide import theme
        with open(self.path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        editor = self.app.open_file(self.path)
        self.app.git.refresh(force=True)
        for _ in range(3):
            time.sleep(0.4)
            self.app.refresh_git()
        self.app.render()
        names = {theme.GIT_LINE_ADDED: 'G', theme.GIT_LINE_MODIFIED: 'B',
                 theme.GIT_LINE_DELETED: 'R'}
        return ''.join(names.get(self.app.screen.cells[y][editor.sb_x][1], '.')
                       for y in range(editor.text_rect.y, editor.text_rect.y2))

    def test_half_the_file_changing_marks_half_the_ruler(self):
        changed = self.lines[:100] + ['new %d' % i for i in range(100)]
        picture = self.ruler(changed)
        marked = len(picture.replace('.', ''))
        self.assertGreaterEqual(marked, len(picture) // 3,
                                'half a file changed should mark a good part '
                                'of the ruler: %r' % picture)
        self.assertNotIn('.', picture[-marked:].rstrip('.'),
                         'the run is broken up: %r' % picture)

    def test_one_changed_line_is_one_mark(self):
        changed = list(self.lines)
        changed[5] = 'line 5 CHANGED'
        picture = self.ruler(changed)
        self.assertEqual(len(picture.replace('.', '')), 1,
                         'one line should be one mark: %r' % picture)


class TestFolderColours(unittest.TestCase):
    """A folder is bold; only git gives it a colour."""

    def setUp(self):
        import io
        from tide.app import App
        from tide.term import Screen
        self.repo = make_repo(prefix='tide-folders-')
        os.makedirs(os.path.join(self.repo, 'quiet'))
        with open(os.path.join(self.repo, 'quiet', 'y.txt'), 'w') as f:
            f.write('y\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'more')
        with open(os.path.join(self.repo, 'sub', 'nested.txt'), 'w') as f:
            f.write('changed\n')                     # sub/ now has a change
        self.cfg = tempfile.mkdtemp(prefix='tide-folders-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.app = App(root=self.repo, paths=[], out=io.StringIO())
        self.app.screen = Screen(80, 16)
        self.app.show_term = False
        self.app.git.refresh(force=True)
        self.app.tree.refresh()
        self.app.render()

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def row_for(self, name):
        for y in range(1, self.app.rects['sidebar'].y2):
            cells = self.app.screen.cells[y]
            text = ''.join(c[0] or ' ' for c in cells[:26])
            if name in text:
                return cells
        raise AssertionError('%s is not in the explorer' % name)

    def test_an_untouched_folder_is_the_plain_colour_in_bold(self):
        from tide import theme
        from tide.term import BOLD
        cells = self.row_for('quiet')
        self.assertEqual(cells[3][1], theme.TREE_FILE,
                         'an untouched folder is still coloured')
        self.assertTrue(cells[3][3] & BOLD, 'it is not bold')

    def test_a_folder_with_changes_keeps_its_git_colour(self):
        from tide import theme
        cells = self.row_for('sub')
        self.assertEqual(cells[3][1], theme.git_colour('M'),
                         'a changed folder lost its colour')

    def test_files_are_not_bold(self):
        from tide.term import BOLD
        cells = self.row_for('tracked.txt')
        self.assertFalse(cells[3][3] & BOLD)


if __name__ == '__main__':
    unittest.main(verbosity=2)
