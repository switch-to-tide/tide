"""`tide --update`, including running it from a terminal inside tide."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness
from harness import ENTER, Session
from tide import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class UpdateTest(unittest.TestCase):
    """A copy of the source, a bare 'remote', and an install cloned from it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='tide-update-')
        source = os.path.join(cls.tmp, 'source')
        os.makedirs(source)
        # tracked files, plus anything new that is not ignored - otherwise a
        # feature still in the working tree is missing from the copy
        tracked = subprocess.check_output(
            ['git', '-C', ROOT, 'ls-files']).decode().split()
        tracked += subprocess.check_output(
            ['git', '-C', ROOT, 'ls-files', '--others',
             '--exclude-standard']).decode().split()
        for rel in tracked:
            target = os.path.join(source, rel)
            directory = os.path.dirname(target)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            shutil.copy(os.path.join(ROOT, rel), target)
        init = os.path.join(source, 'tide', '__init__.py')

        def stamp(number):
            with open(init) as f:
                text = f.read()
            with open(init, 'w') as f:
                f.write(re.sub(r"__version__ = '[^']+'",
                               "__version__ = '%s'" % number, text))

        stamp('9.9.1')
        for cmd in (['init', '-q', '-b', 'main'],
                    ['config', 'user.email', 'crew@harbour'],
                    ['config', 'user.name', 'Crew'],
                    ['add', '-A'], ['commit', '-q', '-m', 'one']):
            git(source, *cmd)
        git(source, 'tag', 'v9.9.1')
        stamp('9.9.2')                       # what 'the newest code' will be
        git(source, 'add', '-A')
        git(source, 'commit', '-q', '-m', 'two')

        cls.remote = os.path.join(cls.tmp, 'remote.git')
        git(source, 'init', '-q', '--bare', cls.remote)
        git(source, 'remote', 'add', 'origin', cls.remote)
        git(source, 'push', '-q', '--all', 'origin')
        git(source, 'push', '-q', '--tags', 'origin')
        cls.install = os.path.join(cls.tmp, 'install')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.install, ignore_errors=True)
        git(self.tmp, 'clone', '-q', '--branch', 'v9.9.1', self.remote, self.install)

    def update(self, *args):
        """Run `tide --update` in the installed copy, capturing what it says."""
        proc = subprocess.Popen(
            [sys.executable, os.path.join(self.install, 'main.py'), '--update'] +
            [a for a in args if a is not None],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.communicate()[0].decode()
        return proc.returncode, out

    def installed(self):
        return cli.installed_version(self.install)


class TestUpdating(UpdateTest):
    def test_it_pulls_the_newest_commit(self):
        self.assertEqual(self.installed(), '9.9.1')
        code, out = self.update()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.installed(), '9.9.2', out)
        self.assertIn('9.9.1 -> 9.9.2', out)

    def test_it_says_when_there_is_nothing_to_do(self):
        self.update()
        code, out = self.update()
        self.assertEqual(code, 0, out)
        self.assertIn('already what you have', out)

    def test_it_can_go_back_to_a_version(self):
        self.update()
        self.assertEqual(self.installed(), '9.9.2')
        code, out = self.update('9.9.1')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.installed(), '9.9.1', 'it did not go back')

    def test_a_missing_version_does_not_move_the_remote(self):
        before = git(self.install, 'remote', 'get-url', 'origin').strip()
        self.update('4.5.6')
        self.assertEqual(git(self.install, 'remote', 'get-url', 'origin').strip(),
                         before, 'a missing version repointed the remote')

    def test_a_version_that_does_not_exist_changes_nothing(self):
        code, out = self.update('4.5.6')
        self.assertEqual(code, 1)
        self.assertIn("could not fetch 'v4.5.6'", out)
        self.assertIn('git said', out)
        self.assertEqual(self.installed(), '9.9.1', 'a failed update moved it')

    def test_it_always_says_to_reopen(self):
        _code, out = self.update()
        self.assertIn('open a new one', out)

    def test_it_declines_when_there_is_no_clone(self):
        shutil.rmtree(os.path.join(self.install, '.git'))
        code, out = self.update()
        self.assertEqual(code, 1)
        self.assertIn('pip', out, 'no advice for a pip install')

    def test_it_refuses_when_local_work_is_in_the_way(self):
        # __init__.py is what the newer commit touches, so this one collides
        path = os.path.join(self.install, 'tide', '__init__.py')
        with open(path, 'a') as f:
            f.write('\n# mine\n')
        code, out = self.update()
        self.assertEqual(code, 1, out)
        self.assertIn('changes of its own', out)
        with open(path) as f:
            self.assertIn('# mine', f.read(), 'it threw away local work')
        self.assertEqual(self.installed(), '9.9.1', 'it moved anyway')

    def test_local_work_it_can_carry_across_is_kept(self):
        path = os.path.join(self.install, 'tide', 'theme.py')
        with open(path, 'a') as f:
            f.write('\n# mine\n')
        code, out = self.update()                 # theme.py is untouched upstream
        self.assertEqual(code, 0, out)
        self.assertEqual(self.installed(), '9.9.2')
        with open(path) as f:
            self.assertIn('# mine', f.read(), 'it threw away local work')


class TestUpdatingFromInside(UpdateTest):
    """The one that matters: updating tide from a shell inside tide."""

    def setUp(self):
        UpdateTest.setUp(self)
        self.work = tempfile.mkdtemp(prefix='tide-inside-')
        self.path = os.path.join(self.work, 'notes.txt')
        with open(self.path, 'w') as f:
            f.write('one\ntwo\n')
        with open(os.path.join(self.work, 'other.py'), 'w') as f:
            f.write('print(1)\n')
        self.was = harness.ROOT
        harness.ROOT = self.install          # run the installed copy
        self.s = Session([self.path, self.work], cols=100, rows=28, cwd=self.work)

    def tearDown(self):
        self.s.close()
        harness.ROOT = self.was
        shutil.rmtree(self.work, ignore_errors=True)

    def screen(self):
        return '\n'.join(''.join(c[0] or ' ' for c in row) for row in self.s.vt.grid)

    def test_the_session_carries_on_with_the_version_it_started_with(self):
        s = self.s
        s.type('hello ')
        s.pump(0.5)
        s.click(50, 20)                       # into the docked shell
        s.type('python3 %s --update' % os.path.join(self.install, 'main.py') + ENTER)
        s.pump(3.0)
        time.sleep(1.5)
        s.pump(1.5)
        self.assertEqual(self.installed(), '9.9.2', 'the update did not happen')
        self.assertIn('open a new one', self.screen().replace('\n', ''))

        s.click(50, 5)                        # back into the editor
        s.type('AFTER ')
        s.pump(0.5)
        s.key(harness.CTRL('s'))
        s.pump(0.8)
        painted = self.screen()
        self.assertNotIn('Traceback', painted, 'the running session fell over')
        self.assertIn('notes.txt', painted, 'it stopped painting')
        with open(self.path) as f:
            text = f.read()
        self.assertIn('hello', text, 'what was typed before the update was lost')
        self.assertIn('AFTER', text, 'edits after the update did not land')

    def test_it_can_still_open_files_and_split_after_an_update(self):
        s = self.s
        s.click(50, 20)
        s.type('python3 %s --update' % os.path.join(self.install, 'main.py') + ENTER)
        s.pump(3.0)
        time.sleep(1.0)
        s.pump(1.0)
        s.click(50, 5)
        s.key(harness.CTRL('p'))
        s.type('other')
        s.key(ENTER)
        s.pump(1.0)
        painted = self.screen()
        self.assertIn('print(1)', painted, 'could not open a file after the update')
        self.assertNotIn('Traceback', painted)


class TestWhenTheRemoteIsWrong(UpdateTest):
    """The commonest way an update fails: it is following the wrong place."""

    def setUp(self):
        UpdateTest.setUp(self)
        os.environ['TIDE_REPO'] = self.remote      # 'where tide comes from'

    def tearDown(self):
        os.environ.pop('TIDE_REPO', None)

    def test_a_checkout_left_behind_by_the_old_repository_is_repaired(self):
        git(self.install, 'remote', 'set-url', 'origin',
            'https://github.com/somebody/gone.git')
        code, out = self.update()
        self.assertEqual(code, 0, out)
        self.assertIn('was following', out)
        self.assertEqual(git(self.install, 'remote', 'get-url', 'origin').strip(),
                         self.remote)
        self.assertEqual(self.installed(), '9.9.2', 'it did not update after all')

    def test_a_remote_that_is_simply_gone_says_what_git_said(self):
        os.environ['TIDE_REPO'] = os.path.join(self.tmp, 'not-a-repo')
        git(self.install, 'remote', 'set-url', 'origin',
            os.path.join(self.tmp, 'also-not-a-repo'))
        code, out = self.update()
        self.assertEqual(code, 1)
        self.assertIn('could not fetch', out)
        self.assertIn('git said', out, 'it swallowed the reason again')

    def test_a_version_that_is_not_there_lists_the_ones_that_are(self):
        code, out = self.update('4.5.6')
        self.assertEqual(code, 1)
        self.assertIn('could not fetch', out)
        self.assertIn('versions there', out)
        self.assertIn('9.9.1', out, 'it did not say what does exist')

    def test_it_does_not_repoint_a_checkout_that_is_already_right(self):
        before = git(self.install, 'remote', 'get-url', 'origin').strip()
        code, out = self.update()
        self.assertEqual(code, 0, out)
        self.assertNotIn('was following', out, 'it moved a remote for no reason')
        self.assertEqual(git(self.install, 'remote', 'get-url', 'origin').strip(),
                         before)


class TestATagThatMoved(UpdateTest):
    """A version tag repointed on the remote must not stop an update.

    git refuses to overwrite a tag it already has - 'would clobber existing
    tag' - and the whole fetch fails with it, which once left every install
    stuck on the version it had.
    """

    def setUp(self):
        UpdateTest.setUp(self)
        self.source = os.path.join(self.tmp, 'source')
        self.was = git(self.source, 'rev-parse', 'v9.9.1').strip()

    def tearDown(self):
        # the remote is shared by the whole class; put the tag back
        git(self.source, 'tag', '-f', 'v9.9.1', self.was)
        git(self.source, 'push', '-q', '--force', 'origin', 'v9.9.1')

    def move_the_tag(self):
        git(self.source, 'tag', '-f', 'v9.9.1')     # now on the newer commit
        git(self.source, 'push', '-q', '--force', 'origin', 'v9.9.1')

    def test_the_update_still_works(self):
        self.assertEqual(self.installed(), '9.9.1')
        self.move_the_tag()
        code, out = self.update()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.installed(), '9.9.2', out)

    def test_the_tag_is_taken_as_it_now_stands(self):
        self.move_the_tag()
        self.update()
        code, out = self.update('9.9.1')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.installed(), '9.9.2',
                         'v9.9.1 now points at the newer commit')

    def test_the_installer_gets_past_it_too(self):
        self.move_the_tag()
        installer = os.path.join(ROOT, 'install.sh')
        home = os.path.join(self.tmp, 'installed')
        shutil.copytree(self.install, home)
        env = dict(os.environ, TIDE_HOME=home,
                   TIDE_BIN=os.path.join(self.tmp, 'bin'),
                   TIDE_REPO=self.remote)
        proc = subprocess.Popen(['sh', installer], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.communicate()[0].decode()
        self.assertEqual(proc.returncode, 0, out)
        self.assertEqual(cli.installed_version(home), '9.9.2', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
