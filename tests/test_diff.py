"""The two diff views: a conflict diff, and a git diff of a modified file."""

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

from harness import CTRL, ENTER, ESC, Session
from tide.app import App
from tide.diff import (ADDED, CHANGED, EQUAL, GAP, REMOVED, DiffView, align,
                       buffer_source, disk_source, trim)
from tide.keys import Key, Mouse, SHIFT
from tide.term import Rect

F7, F8 = ESC + '[18~', ESC + '[19~'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class TestAlignment(unittest.TestCase):
    def kinds(self, left, right):
        return [row[4] for row in align(left, right)]

    def test_identical_files(self):
        self.assertEqual(self.kinds(['a', 'b'], ['a', 'b']), [EQUAL, EQUAL])

    def test_an_inserted_line(self):
        rows = align(['a', 'b'], ['a', 'NEW', 'b'])
        self.assertEqual([r[4] for r in rows], [EQUAL, ADDED, EQUAL])
        self.assertIsNone(rows[1][0], 'the left side has nothing there')
        self.assertEqual(rows[1][2], 2)

    def test_a_deleted_line(self):
        rows = align(['a', 'gone', 'b'], ['a', 'b'])
        self.assertEqual([r[4] for r in rows], [EQUAL, REMOVED, EQUAL])
        self.assertIsNone(rows[1][2])

    def test_a_changed_line_pairs_up(self):
        rows = align(['a', 'old', 'b'], ['a', 'new', 'b'])
        self.assertEqual([r[4] for r in rows], [EQUAL, CHANGED, EQUAL])
        self.assertEqual((rows[1][1], rows[1][3]), ('old', 'new'))

    def test_line_numbers_follow_each_side(self):
        rows = align(['a', 'b', 'c'], ['a', 'x', 'y', 'b', 'c'])
        pairs = [(r[0], r[2]) for r in rows]
        self.assertEqual(pairs, [(1, 1), (None, 2), (None, 3), (2, 4), (3, 5)])

    def test_empty_against_content(self):
        rows = align([''], ['one', 'two'])
        self.assertTrue(any(r[4] != EQUAL for r in rows))


class TestTrimming(unittest.TestCase):
    def test_only_changes_and_context_are_kept(self):
        left = ['l%d' % i for i in range(40)]
        right = list(left)
        right[20] = 'CHANGED'
        rows = trim(align(left, right), context=2)
        kinds = [r[4] for r in rows]
        self.assertIn(CHANGED, kinds)
        self.assertIn(GAP, kinds)
        self.assertLess(len(rows), 12, 'the trimmed view is not much smaller')

    def test_a_gap_says_how_much_was_hidden(self):
        left = ['x'] * 30
        right = ['x'] * 30
        right[15] = 'y'
        rows = trim(align(left, right), context=1)
        gaps = [r[3] for r in rows if r[4] == GAP]
        self.assertTrue(any('unchanged lines' in g for g in gaps))

    def test_identical_files_trim_to_nothing(self):
        self.assertEqual(trim(align(['a', 'b'], ['a', 'b'])), [])


class DiffAppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-diff-')
        self.path = os.path.join(self.tmp, 'f.txt')
        with open(self.path, 'w') as f:
            f.write('one\ntwo\nthree\n')
        self.app = App(root=self.tmp, paths=[self.path], out=io.StringIO())
        self.app.autosave_delay = 0.0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestConflictDiff(DiffAppTest):
    def test_it_shows_both_sides(self):
        ed = self.app.editor
        ed.doc.cursor = (0, 0)
        ed.doc.insert('MINE ')
        with open(self.path, 'w') as f:
            f.write('THEIRS\ntwo\nthree\n')
        view = self.app.open_conflict_diff(ed)
        texts = [(r[1], r[3]) for r in view.rows]
        self.assertIn(('MINE one', 'THEIRS'), texts)
        self.assertEqual(self.app.editor, view, 'the diff did not become the tab')
        self.assertTrue(view.is_diff)

    def test_it_follows_the_buffer(self):
        ed = self.app.editor
        view = self.app.open_conflict_diff(ed)
        self.assertEqual(view.changes, 0)
        ed.doc.cursor = (0, 0)
        ed.doc.insert('CHANGED ')
        self.assertTrue(view.refresh(), 'the diff did not notice the edit')
        self.assertTrue(any('CHANGED ' in r[1] for r in view.rows))

    def test_it_follows_the_file(self):
        ed = self.app.editor
        view = self.app.open_conflict_diff(ed)
        time.sleep(0.01)
        with open(self.path, 'w') as f:
            f.write('one\nREWRITTEN\nthree\n')
        self.assertTrue(view.refresh())
        self.assertTrue(any('REWRITTEN' in r[3] for r in view.rows))

    def test_it_rebuilds_only_when_something_changed(self):
        view = self.app.open_conflict_diff(self.app.editor)
        self.assertFalse(view.refresh(), 'rebuilt with nothing to do')

    def test_reopening_reuses_the_same_tab(self):
        ed = self.app.editors[0]
        self.app.open_conflict_diff(ed)
        self.app.open_conflict_diff(ed)
        self.assertEqual(len(self.app.editors), 2, 'a second diff tab was opened')


class TestDiffTabsAreInert(DiffAppTest):
    def setUp(self):
        DiffAppTest.setUp(self)
        self.view = self.app.open_conflict_diff(self.app.editors[0])

    def test_it_is_never_saved(self):
        self.assertFalse(self.app.save())
        self.assertIn('read-only', self.app.message)

    def test_auto_save_and_the_watcher_ignore_it(self):
        self.app.autosave_tick()
        self.app.check_disk_changes(force=True)
        self.app.refresh_git()

    def test_editor_only_commands_do_not_reach_it(self):
        self.app.prompt_find()
        self.app.prompt_goto()
        self.app.prompt_replace()
        self.app.prompt_save_as()

    def test_closing_it_asks_nothing(self):
        self.app.close_tab(self.app.active)
        self.assertIsNone(self.app.overlay)
        self.assertEqual(len(self.app.editors), 1)

    def test_the_file_tab_is_untouched_by_it(self):
        ed = self.app.editors[0]
        ed.doc.cursor = (0, 0)
        ed.doc.insert('still editable')
        self.app.autosave_tick()
        with open(self.path) as f:
            self.assertTrue(f.read().startswith('still editable'))


class TestGitDiff(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix='tide-gitdiff-')
        self.path = os.path.join(self.repo, 'tracked.py')
        with open(self.path, 'w') as f:
            f.write(''.join('line %d\n' % i for i in range(20)))
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 't@e.com')
        git(self.repo, 'config', 'user.name', 'T')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'first')
        self.app = App(root=self.repo, paths=[self.path], out=io.StringIO())
        self.app.autosave_delay = 0.0
        self.app.git.refresh(force=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def modify(self):
        ed = self.app.editors[0]
        ed.doc.cursor = (5, 0)
        ed.doc.insert('CHANGED ')
        self.app.save(ed)
        self.app.git.refresh(force=True)
        return ed

    def test_a_clean_file_offers_no_diff(self):
        self.assertFalse(self.app.git.has_diff(self.path))
        self.assertIsNone(self.app.open_git_diff(minimal=True))
        self.assertEqual(len(self.app.editors), 1)

    def test_an_untracked_file_offers_no_diff(self):
        fresh = os.path.join(self.repo, 'new.py')
        with open(fresh, 'w') as f:
            f.write('brand new\n')
        self.app.git.refresh(force=True)
        ed = self.app.open_file(fresh)
        self.assertEqual(self.app.git.status_for(fresh), 'U')
        self.assertFalse(self.app.git.has_diff(fresh))
        self.assertIsNone(self.app.open_git_diff(ed, minimal=True))

    def test_a_modified_file_diffs_against_the_last_commit(self):
        ed = self.modify()
        view = self.app.open_git_diff(ed, minimal=True)
        self.assertIsNotNone(view)
        self.assertTrue(any(r[4] == CHANGED and 'CHANGED ' in r[3] for r in view.rows))
        self.assertTrue(any(r[4] == GAP for r in view.rows), 'nothing was trimmed')

    def test_the_full_view_shows_every_line(self):
        ed = self.modify()
        view = self.app.open_git_diff(ed, minimal=False)
        self.assertEqual(len(view.rows), 21)          # 20 lines plus the last empty
        self.assertFalse(any(r[4] == GAP for r in view.rows))

    def test_toggling_between_the_two_modes(self):
        ed = self.modify()
        view = self.app.open_git_diff(ed, minimal=False)
        full = len(view.rows)
        view.toggle_minimal()
        self.assertLess(len(view.rows), full)
        view.toggle_minimal()
        self.assertEqual(len(view.rows), full)

    def test_the_two_modes_are_separate_tabs(self):
        ed = self.modify()
        self.app.open_git_diff(ed, minimal=True)
        self.app.open_git_diff(ed, minimal=False)
        self.assertEqual(len(self.app.editors), 3)

    def test_it_follows_further_edits(self):
        ed = self.modify()
        view = self.app.open_git_diff(ed, minimal=True)
        before = view.changes
        ed.doc.cursor = (0, 0)
        ed.doc.insert('MORE ')
        self.assertTrue(view.refresh())
        self.assertGreater(view.changes, before)

    def test_committing_makes_the_diff_empty(self):
        ed = self.modify()
        view = self.app.open_git_diff(ed, minimal=True)
        self.assertGreater(view.changes, 0)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'second')
        self.app.git.refresh(force=True)
        view.refresh(force=True)
        self.assertEqual(view.changes, 0)

    def test_outside_a_repository_there_is_no_diff(self):
        plain = tempfile.mkdtemp(prefix='tide-nogit-diff-')
        try:
            path = os.path.join(plain, 'a.txt')
            with open(path, 'w') as f:
                f.write('x\n')
            app = App(root=plain, paths=[path], out=io.StringIO())
            self.assertIsNone(app.open_git_diff(minimal=True))
            self.assertIn('git', app.message)
        finally:
            shutil.rmtree(plain, ignore_errors=True)


class TestScrolling(DiffAppTest):
    """Vertical in lockstep, horizontal one half at a time."""

    def setUp(self):
        # a conflict diff: the buffer on the left, the file on disk on the right
        DiffAppTest.setUp(self)
        body = ['short', 'L' + 'a' * 200] + ['line %d' % i for i in range(40)]
        with open(self.path, 'w') as f:
            f.write('\n'.join(body) + '\n')
        self.app.editors[0].doc.reload()
        self.view = self.app.open_conflict_diff(self.app.editors[0])
        time.sleep(0.01)
        body[1] = 'R' + 'b' * 400          # the file grows a much longer line
        with open(self.path, 'w') as f:
            f.write('\n'.join(body) + '\n')
        self.view.refresh(force=True)
        self.view.rect = Rect(0, 0, 100, 20)

    def test_each_side_knows_its_widest_line(self):
        self.assertGreater(self.view.widest['right'], self.view.widest['left'])
        self.assertGreater(self.view.max_col('right'), self.view.max_col('left'))

    def test_scrolling_one_side_leaves_the_other_alone(self):
        self.view.scroll_across('left', 24)
        self.assertEqual(self.view.cols['left'], 24)
        self.assertEqual(self.view.cols['right'], 0)
        self.view.scroll_across('right', 40)
        self.assertEqual(self.view.cols['left'], 24)
        self.assertEqual(self.view.cols['right'], 40)

    def test_horizontal_scroll_is_clamped(self):
        self.view.scroll_across('left', -100)
        self.assertEqual(self.view.cols['left'], 0)
        self.view.scroll_across('left', 10000)
        self.assertEqual(self.view.cols['left'], self.view.max_col('left'))

    def test_vertical_scrolling_is_shared(self):
        self.view.scroll_across('left', 30)
        self.view.scroll(5)
        self.assertEqual(self.view.top, 5)          # one viewport for both halves
        self.view.scroll_across('right', 60)
        self.view.scroll(2)
        self.assertEqual(self.view.top, 7)
        self.assertEqual((self.view.cols['left'], self.view.cols['right']), (30, 60))

    def test_the_wheel_picks_the_half_under_the_pointer(self):
        self.view.on_mouse(Mouse('wheel_right', 10, 5))
        self.assertGreater(self.view.cols['left'], 0)
        self.assertEqual(self.view.cols['right'], 0)
        self.view.on_mouse(Mouse('wheel_right', 80, 5))
        self.assertGreater(self.view.cols['right'], 0)

    def test_shift_and_the_wheel_also_scroll_sideways(self):
        self.view.on_mouse(Mouse('wheel_down', 80, 5, mods=SHIFT))
        self.assertGreater(self.view.cols['right'], 0)
        self.assertEqual(self.view.top, 0, 'shift+wheel should not scroll down')

    def test_the_plain_wheel_still_scrolls_down(self):
        self.view.on_mouse(Mouse('wheel_down', 80, 5))
        self.assertEqual(self.view.top, 3)
        self.assertEqual(self.view.cols['right'], 0)

    def test_arrows_scroll_the_half_you_clicked(self):
        self.view.on_mouse(Mouse('press', 80, 6))
        self.view.on_key(Key('right'))
        self.assertGreater(self.view.cols['right'], 0)
        self.assertEqual(self.view.cols['left'], 0)
        self.view.on_mouse(Mouse('press', 10, 6))
        self.view.on_key(Key('right'))
        self.assertGreater(self.view.cols['left'], 0)

    def test_tab_swaps_which_half_the_arrows_move(self):
        self.assertEqual(self.view.side, 'left')
        self.view.on_key(Key('tab'))
        self.assertEqual(self.view.side, 'right')

    def test_a_rebuild_keeps_the_offsets_but_clamps_them(self):
        self.view.scroll_across('right', 300)
        kept = self.view.cols['right']
        time.sleep(0.01)
        with open(self.path, 'w') as f:
            f.write('short\nR short again\nline 0\n')
        self.view.refresh(force=True)
        self.assertLess(self.view.cols['right'], kept, 'offset outlived its line')
        self.assertEqual(self.view.cols['right'], self.view.max_col('right'))


class TestRefreshCost(unittest.TestCase):
    """An open diff that is up to date must be nearly free."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix='tide-diffcost-')
        self.path = os.path.join(self.repo, 'f.py')
        with open(self.path, 'w') as f:
            f.write('one\ntwo\nthree\n')
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 't@e.com')
        git(self.repo, 'config', 'user.name', 'T')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'first')
        with open(self.path, 'w') as f:
            f.write('one\nCHANGED\nthree\n')
        self.app = App(root=self.repo, paths=[self.path], out=io.StringIO())
        self.app.git.refresh(force=True)
        self.view = self.app.open_git_diff(self.app.editors[0], minimal=True)
        self.calls = []
        real = self.app.git._run
        self.app.git._run = lambda args, timeout=3.0: (
            self.calls.append(args[0]), real(args, timeout))[1]

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_an_idle_diff_runs_no_git_at_all(self):
        for _ in range(50):
            self.view.refresh()
        self.assertEqual(self.calls, [], 'git was run with nothing to do')

    def test_an_edit_rebuilds_it_once(self):
        for _ in range(10):
            self.view.refresh()
        self.app.editors[0].doc.insert('X')
        self.assertTrue(self.view.refresh())
        for _ in range(10):
            self.assertFalse(self.view.refresh())
        self.assertEqual(len(self.calls), 1, 'the rebuild cost more than one git call')

    def test_a_commit_rebuilds_it(self):
        self.view.refresh()
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'second')
        self.assertTrue(self.view.refresh(), 'the commit went unnoticed')

    def test_the_state_token_ignores_ordinary_edits(self):
        token = self.app.git.state_token()
        with open(self.path, 'a') as f:
            f.write('more\n')
        self.assertEqual(self.app.git.state_token(), token,
                         'a plain file edit should not look like a repository change')

    def test_the_upstream_lookup_is_cached(self):
        self.app.git.upstream_ref()
        before = len(self.calls)
        for _ in range(20):
            self.app.git.upstream_ref()
        self.assertEqual(len(self.calls), before, 'upstream was looked up repeatedly')


class TestAgainstTheRemote(unittest.TestCase):
    """Comparing with the tracking branch, refreshed by the user's own fetch."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='tide-remote-')
        self.bare = os.path.join(self.base, 'origin.git')
        self.work = os.path.join(self.base, 'work')
        self.other = os.path.join(self.base, 'other')
        subprocess.check_call(['git', 'init', '-q', '--bare', self.bare])
        subprocess.check_call(['git', 'clone', '-q', self.bare, self.work],
                              stderr=subprocess.DEVNULL)
        git(self.work, 'config', 'user.email', 't@e.com')
        git(self.work, 'config', 'user.name', 'T')
        self.path = os.path.join(self.work, 'f.py')
        with open(self.path, 'w') as f:
            f.write('one\ntwo\nthree\n')
        git(self.work, 'add', '-A')
        git(self.work, 'commit', '-q', '-m', 'first')
        git(self.work, 'push', '-q', 'origin', 'HEAD:main')
        git(self.work, 'branch', '--set-upstream-to=origin/main', 'main')
        self.app = App(root=self.work, paths=[self.path], out=io.StringIO())
        self.app.git.refresh(force=True)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def push_from_elsewhere(self, text):
        if not os.path.exists(self.other):
            subprocess.check_call(['git', 'clone', '-q', self.bare, self.other],
                                  stderr=subprocess.DEVNULL)
            git(self.other, 'config', 'user.email', 'o@e.com')
            git(self.other, 'config', 'user.name', 'O')
        with open(os.path.join(self.other, 'f.py'), 'w') as f:
            f.write(text)
        git(self.other, 'add', '-A')
        git(self.other, 'commit', '-q', '-m', 'from elsewhere')
        git(self.other, 'push', '-q', 'origin', 'main')

    def test_the_upstream_branch_is_offered_as_the_other_side(self):
        ed = self.app.editors[0]
        ed.doc.insert('local ')
        self.app.save(ed)
        self.app.git.refresh(force=True)
        view = self.app.open_git_diff(ed, minimal=False)
        self.assertEqual(self.app.git.upstream_ref(), 'origin/main')
        self.assertIsNotNone(view.alt_left)
        self.assertEqual(view.alt_left.label, 'origin/main')
        self.assertTrue(view.swap_left())
        self.assertEqual(view.left.label, 'origin/main')

    def test_a_fetch_updates_the_remote_side(self):
        ed = self.app.editors[0]
        ed.doc.cursor = (1, 0)
        ed.doc.insert('MY EDIT ')
        self.app.save(ed)
        self.app.git.refresh(force=True)
        view = self.app.open_git_diff(ed, minimal=False)
        view.swap_left()
        self.assertNotIn('FROM THE REMOTE', [r[1] for r in view.rows])
        self.push_from_elsewhere('one\nFROM THE REMOTE\nthree\n')
        self.assertFalse(view.refresh(), 'a push alone should change nothing here')
        git(self.work, 'fetch', '-q', 'origin')      # the user fetches
        time.sleep(0.02)
        self.assertTrue(view.refresh(), 'the fetch went unnoticed')
        self.assertIn('FROM THE REMOTE', [r[1] for r in view.rows])
        self.assertTrue(any('MY EDIT ' in r[3] for r in view.rows))

    def test_we_never_reach_the_network_ourselves(self):
        ed = self.app.editors[0]
        ed.doc.insert('edited ')
        self.app.save(ed)
        self.app.git.refresh(force=True)
        calls = []
        real = self.app.git._run
        self.app.git._run = lambda args, timeout=3.0: (
            calls.append(args[0]), real(args, timeout))[1]
        view = self.app.open_git_diff(ed, minimal=False)
        for _ in range(20):
            view.refresh()
            self.app.git.refresh(force=True)
        self.assertNotIn('fetch', calls)
        self.assertNotIn('pull', calls)
        self.assertNotIn('remote', calls)


class TestDiffInTheUI(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix='tide-diff-ui-')
        self.path = os.path.join(self.repo, 'code.py')
        with open(self.path, 'w') as f:
            f.write(''.join('line %d\n' % i for i in range(12)))
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 't@e.com')
        git(self.repo, 'config', 'user.name', 'T')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'first')
        with open(self.path, 'w') as f:
            f.write(''.join(('CHANGED %d\n' % i) if i == 4 else ('line %d\n' % i)
                            for i in range(12)))
        self.s = Session(['code.py', self.repo], cols=100, rows=24, cwd=self.repo)
        self.s.pump(1.4)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_the_buttons_appear_for_a_modified_file(self):
        top = self.s.text()[0]
        self.assertIn('changes', top)
        self.assertIn('diff all', top)

    def test_f7_opens_the_trimmed_diff(self):
        self.s.key(F7)
        self.s.pump(0.8)
        self.assertIn('diff code.py (changes)', self.s.line(self.s.TAB_ROW))
        self.assertIn('last commit', self.s.screen())
        self.assertIn('CHANGED 4', self.s.screen())
        self.assertIn('unchanged lines', self.s.screen())

    def test_f8_opens_the_whole_file_diff(self):
        self.s.key(F8)
        self.s.pump(0.8)
        self.assertIn('diff code.py (all)', self.s.line(self.s.TAB_ROW))
        self.assertIn('line 0', self.s.screen())
        self.assertNotIn('unchanged lines', self.s.screen())

    def test_clicking_the_button_opens_it_too(self):
        top = self.s.text()[0]
        self.s.click(top.index('changes') + 2, 0)
        self.s.pump(0.8)
        self.assertIn('diff code.py', self.s.line(self.s.TAB_ROW))

    def test_the_diff_is_read_only_and_the_file_tab_still_edits(self):
        self.s.key(F7)
        self.s.pump(0.6)
        self.s.type('SHOULD NOT APPEAR')
        self.s.pump(0.4)
        self.assertNotIn('SHOULD NOT APPEAR', self.s.screen())
        row = self.s.line(self.s.TAB_ROW)
        self.s.click(row.index('code.py') + 1, self.s.TAB_ROW)
        self.s.pump(0.4)
        self.s.type('typed ')
        self.s.pump(0.5)
        self.assertIn('typed ', self.s.screen())

    def test_the_diff_updates_when_the_file_is_edited(self):
        self.s.key(F7)
        self.s.pump(0.6)
        row = self.s.line(self.s.TAB_ROW)
        self.s.click(row.index('code.py') + 1, self.s.TAB_ROW)
        self.s.pump(0.3)
        self.s.type('BRAND NEW ')
        time.sleep(1.2)
        self.s.pump(0.4)
        self.s.click(row.index('diff code.py') + 2, self.s.TAB_ROW)
        self.s.pump(1.2)
        self.assertIn('BRAND NEW', self.s.screen(), 'the diff did not follow the edit')

    def test_scrolling_sideways_moves_one_half_only(self):
        with open(self.path, 'w') as f:                # a very long working line
            f.write('line 0\n' + 'X' * 200 + '\n'
                    + ''.join('line %d\n' % i for i in range(2, 12)))
        time.sleep(1.2)
        self.s.pump(0.6)
        self.s.key(F8)
        self.s.pump(0.8)
        rows = [y for y, line in enumerate(self.s.text()) if 'XXXX' in line[63:]]
        self.assertTrue(rows, 'the long line is not on the right hand side')
        row = rows[0]
        before_left = self.s.line(row)[26:60]
        before_right = self.s.line(row)[63:]
        self.s.hwheel(80, row, right=True, times=3)    # over the right half
        self.assertNotEqual(self.s.line(row)[63:], before_right,
                            'the right half did not scroll')
        self.assertEqual(self.s.line(row)[26:60], before_left,
                         'the left half moved too')
        self.assertIn('col ', self.s.screen())

    def numbers(self, row):
        """The line number each half is showing on a row."""
        halves = self.s.line(row).split('|')
        out = []
        for half in halves[:2]:
            digits = [w for w in half.replace('│', ' ').split() if w.isdigit()]
            out.append(digits[0] if digits else '')
        return (out + ['', ''])[:2]

    def test_vertical_scrolling_keeps_the_halves_together(self):
        self.s.key(F8)
        self.s.pump(0.8)
        top_row = self.s.BODY_ROW + 1        # past the two halves' headings
        left, right = self.numbers(top_row)
        self.assertEqual(left, right,
                         'the two halves start on different lines')
        self.s.hwheel(35, top_row, right=True, times=2)   # offset one half
        self.s.wheel(50, top_row, up=False, times=2)      # then scroll down
        left, right = self.numbers(top_row)
        self.assertEqual(left, right,
                         'the halves drifted apart vertically')

    def test_the_conflict_prompt_offers_a_diff(self):
        s = Session(['--no-autosave', 'code.py', self.repo], cols=100, rows=24,
                    cwd=self.repo)
        try:
            s.pump(0.8)
            s.type('MINE ')
            s.key(CTRL('j'))
            s.type('printf "outside\\n" > code.py' + ENTER)
            self.assertTrue(s.wait_for('changed on disk'))
            self.assertIn('d to diff', s.screen())
            s.send_raw('d')
            s.pump(1.0)
            self.assertIn('yours (unsaved)', s.screen())
            self.assertIn('on disk (newer)', s.screen())
            self.assertIn('MINE ', s.screen())
            self.assertIn('outside', s.screen())
        finally:
            s.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
