"""The chrome around the panes: the branch label, and scrollable tab strips."""

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

from harness import ALT_LEFT, ALT_RIGHT, CTRL, ENTER, ESC, Session
from tide.app import App
from tide.git import Git

F4, F5 = ESC + 'OS', ESC + '[15~'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class TestBranchName(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix='tide-branch-')
        self.path = os.path.join(self.repo, 'f.txt')
        with open(self.path, 'w') as f:
            f.write('one\n')
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 't@e.com')
        git(self.repo, 'config', 'user.name', 'T')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'first')

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_it_reads_the_current_branch(self):
        self.assertEqual(Git(self.repo).branch, 'main')

    def test_it_follows_a_checkout(self):
        g = Git(self.repo)
        git(self.repo, 'checkout', '-q', '-b', 'feature/login')
        self.assertEqual(g.read_branch(), 'feature/login')
        g.refresh(force=True)
        self.assertEqual(g.branch, 'feature/login')

    def test_a_detached_head_shows_a_commit(self):
        sha = git(self.repo, 'rev-parse', 'HEAD').strip()
        git(self.repo, 'checkout', '-q', '--detach', 'HEAD')
        name = Git(self.repo).read_branch()
        self.assertTrue(name.startswith(sha[:7]), '%r does not name the commit' % name)

    def test_reading_it_costs_no_subprocess(self):
        g = Git(self.repo)
        calls = []
        real = g._run
        g._run = lambda args, timeout=3.0: (calls.append(args[0]), real(args, timeout))[1]
        for _ in range(50):
            g.read_branch()
        self.assertEqual(calls, [], 'the branch name should come from .git/HEAD')

    def test_outside_a_repository_there_is_none(self):
        plain = tempfile.mkdtemp(prefix='tide-nobranch-')
        try:
            self.assertIsNone(Git(plain).branch)
        finally:
            shutil.rmtree(plain, ignore_errors=True)


class TestStatusBar(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix='tide-bar-')
        self.path = os.path.join(self.repo, 'f.txt')
        with open(self.path, 'w') as f:
            f.write('one\n')
        git(self.repo, 'init', '-q', '-b', 'trunk')
        git(self.repo, 'config', 'user.email', 't@e.com')
        git(self.repo, 'config', 'user.name', 'T')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'first')
        self.s = Session(['f.txt', self.repo], cols=96, rows=16, cwd=self.repo,
                         env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
        self.s.pump(1.6)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.repo, ignore_errors=True)

    def bar(self):
        return self.s.line(self.s.rows - 1)

    def test_the_branch_sits_at_the_bottom_left(self):
        self.assertTrue(self.bar().startswith(' trunk'), repr(self.bar()))

    def test_a_dirty_tree_is_marked(self):
        self.assertNotIn('trunk*', self.bar())
        self.s.type('edited ')
        deadline = time.time() + 6
        while time.time() < deadline and 'trunk*' not in self.bar():
            self.s.pump(0.4)
        self.assertIn('trunk*', self.bar(), 'the dirty marker never appeared')

    def test_it_follows_a_checkout_in_the_terminal(self):
        self.s.key(CTRL('j'))
        self.s.type('git checkout -q -b sidebranch' + ENTER)
        deadline = time.time() + 8
        while time.time() < deadline and 'sidebranch' not in self.bar():
            self.s.pump(0.5)
        self.assertIn('sidebranch', self.bar())

    def test_the_rest_of_the_bar_is_still_there(self):
        self.assertIn('Ln 1, Col 1', self.bar())
        self.assertIn('f1 help', self.bar())

    def test_no_branch_outside_a_repository(self):
        plain = tempfile.mkdtemp(prefix='tide-bar-plain-')
        try:
            with open(os.path.join(plain, 'a.txt'), 'w') as f:
                f.write('x\n')
            s = Session(['a.txt', plain], cols=96, rows=16, cwd=plain,
                        env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
            s.pump(1.4)
            self.assertIn('Ln 1', s.line(15))
            self.assertNotIn('*', s.line(15).split('Ln')[0])
            s.close()
        finally:
            shutil.rmtree(plain, ignore_errors=True)


class TestTabStrip(unittest.TestCase):
    NAMES = ['alpha_module.py', 'beta_helpers.py', 'gamma_utils.py',
             'delta_config.py', 'epsilon_tests.py', 'zeta_main.py',
             'eta_readme.md', 'theta_extra.py']

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-tabs-')
        for name in self.NAMES:
            with open(os.path.join(self.tmp, name), 'w') as f:
                f.write('inside %s\n' % name)
        self.s = Session([os.path.join(self.tmp, n) for n in self.NAMES] + [self.tmp],
                         cols=100, rows=18, cwd=self.tmp,
                         env={'TIDE_CONFIG_HOME': tempfile.mkdtemp()})
        self.s.pump(1.0)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tabs(self):
        return self.s.line(self.s.TAB_ROW)[26:]

    def test_too_many_tabs_are_cropped_with_an_arrow(self):
        strip = self.tabs()
        self.assertTrue(strip.startswith('<'), 'no arrow for the hidden tabs')
        self.assertNotIn('alpha_module.py', strip, 'everything fitted after all')
        self.assertIn('theta_extra.py', strip, 'the open tab is not in view')

    def test_the_wheel_scrolls_the_strip(self):
        before = self.tabs()
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=4)
        self.assertNotEqual(self.tabs(), before, 'the strip did not move')
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=8)
        self.assertIn('alpha_module.py', self.tabs(), 'cannot reach the first tab')
        self.assertTrue(self.tabs().rstrip().endswith('>'), 'no arrow for the rest')

    def test_a_sideways_wheel_does_the_same(self):
        before = self.tabs()
        self.s.hwheel(60, self.s.TAB_ROW, right=False, times=4)
        self.assertNotEqual(self.tabs(), before, 'a sideways wheel did nothing')
        self.s.hwheel(60, self.s.TAB_ROW, right=False, times=12)
        self.assertIn('alpha_module.py', self.tabs())

    def test_the_arrows_are_clickable(self):
        before = self.tabs()
        self.s.click(26, self.s.TAB_ROW)          # the '<' at the left edge
        self.assertNotEqual(self.tabs(), before)

    def test_scrolling_does_not_change_the_active_file(self):
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=10)
        self.assertIn('inside theta_extra.py', self.s.screen(),
                      'the active file changed while scrolling')

    def test_a_visible_tab_can_still_be_clicked(self):
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=14)
        strip = self.tabs()
        self.assertIn('beta_helpers.py', strip)
        self.s.click(26 + strip.index('beta_helpers.py') + 1, self.s.TAB_ROW)
        self.s.pump(0.5)
        self.assertIn('inside beta_helpers.py', self.s.screen())

    def test_switching_tabs_brings_the_new_one_into_view(self):
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=12)   # away from the active
        self.s.key(ALT_RIGHT)
        self.s.pump(0.4)
        self.assertIn('alpha_module.py', self.tabs(), 'the new tab was left off screen')

    def test_each_strip_scrolls_on_its_own(self):
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=14)   # files to the start
        files_scrolled = self.tabs()
        self.assertIn('alpha_module.py', files_scrolled)
        self.s.key(F4)                       # a terminal strip of its own
        self.s.pump(1.0)
        for _ in range(5):
            self.s.key(F4)
        self.s.pump(1.2)
        self.assertIn('sh 6', self.tabs(), 'the terminals are not all there')
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=4)
        self.assertIn(' sh  x ', self.tabs(), 'the terminal strip did not scroll')
        self.s.key(ESC + 'OQ')               # f2, back to the file tabs
        self.s.pump(0.5)
        self.assertNotIn(' sh  x ', self.tabs(), 'the strips share an offset')
        self.assertIn('.py', self.tabs())

    def test_it_works_in_split_view_too(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(F4)
        self.s.pump(1.2)
        self.s.key(ESC + 'OQ')               # look at the file tabs
        self.s.pump(0.5)
        before = self.tabs()
        self.s.wheel(45, self.s.TAB_ROW, up=True, times=6)
        self.assertNotEqual(self.tabs(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
