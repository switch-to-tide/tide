"""The git review: one long read-only page of everything that changed."""

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
from tide import review as review_mod
from tide.app import App
from tide.keys import Key, Mouse
from tide.term import Screen

F5, F10 = ESC + '[15~', ESC + '[21~'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-review-')
        self.cfg = tempfile.mkdtemp(prefix='tide-review-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.write('README.md', 'hello\nworld\n')
        self.write('src/core/engine.py',
                   '\n'.join('line %d' % i for i in range(1, 41)) + '\n')
        self.write('src/old.py', 'moved but not touched\n')
        self.write('doomed.txt', 'delete me\n')
        for cmd in (['init', '-q', '-b', 'main'],
                    ['config', 'user.email', 'crew@harbour'],
                    ['config', 'user.name', 'Crew'],
                    ['add', '-A'], ['commit', '-q', '-m', 'first']):
            git(self.tmp, *cmd)

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, 'w') as f:
            f.write(text)
        return path

    def change_everything(self):
        self.write('README.md', 'hello\nthere\nworld\n')          # modified
        lines = ['line %d' % i for i in range(1, 41)]
        lines[20] = 'line 21 CHANGED'
        self.write('src/core/engine.py', '\n'.join(lines) + '\n')  # modified
        self.write('brand_new.py', 'print(1)\nprint(2)\n')         # untracked
        os.remove(os.path.join(self.tmp, 'doomed.txt'))            # deleted
        os.rename(os.path.join(self.tmp, 'src/old.py'),
                  os.path.join(self.tmp, 'src/moved.py'))          # a pure move

    def app(self, cols=120, rows=30, terminal=False):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(cols, rows)
        app.show_term = terminal
        app.render()
        return app

    def page(self, app, y):
        row = ''.join(c[0] or ' ' for c in app.screen.cells[y])
        return row[app.rects['editor'].x:].rstrip()

    def side(self, app, y):
        row = ''.join(c[0] or ' ' for c in app.screen.cells[y])
        return row[:app.rects['sidebar'].w].rstrip()

    def heading_row(self, name):
        rect = self.a.rects['editor']
        for y in range(rect.y, rect.y2):
            if ('M %s' % name) in self.page(self.a, y) or \
               ('U %s' % name) in self.page(self.a, y):
                return y
        raise AssertionError('no heading for %s on screen' % name)

    def whole(self, app):
        return '\n'.join(''.join(c[0] or ' ' for c in row)
                         for row in app.screen.cells)


class TestWhatCounts(ReviewTest):
    def test_it_finds_every_kind_of_change(self):
        self.change_everything()
        app = self.app()
        files = dict(review_mod.changed_files(app.git))
        self.assertEqual(files.get('README.md'), 'M')
        self.assertEqual(files.get('src/core/engine.py'), 'M')
        self.assertEqual(files.get('brand_new.py'), 'U')
        self.assertEqual(files.get('doomed.txt'), 'D')

    def test_a_file_only_moved_is_left_out(self):
        self.change_everything()
        app = self.app()
        files = dict(review_mod.changed_files(app.git))
        self.assertNotIn('src/moved.py', files, 'a pure move is not a change')
        self.assertNotIn('src/old.py', files, 'nor is the name it left behind')

    def test_a_file_moved_and_edited_is_kept(self):
        os.rename(os.path.join(self.tmp, 'src/old.py'),
                  os.path.join(self.tmp, 'src/renamed.py'))
        self.write('src/renamed.py', 'moved but not touched\nand edited\n')
        app = self.app()
        files = dict(review_mod.changed_files(app.git))
        self.assertIn('src/renamed.py', files, 'an edited move is a change')

    def test_a_staged_change_counts_too(self):
        self.write('README.md', 'hello\nstaged\nworld\n')
        git(self.tmp, 'add', 'README.md')
        app = self.app()
        self.assertEqual(dict(review_mod.changed_files(app.git)).get('README.md'), 'M')

    def test_nothing_changed_means_nothing_to_review(self):
        app = self.app()
        self.assertEqual(review_mod.changed_files(app.git), [])
        self.assertFalse(app.open_review(), 'it opened with nothing to show')
        self.assertIsNone(app.review)
        self.assertIn('nothing has changed', app.message)


class TestThePage(ReviewTest):
    def setUp(self):
        ReviewTest.setUp(self)
        self.change_everything()
        self.a = self.app()
        self.assertTrue(self.a.open_review())
        self.a.render()

    def test_each_file_has_a_heading_and_a_rule_after_it(self):
        text = self.whole(self.a)
        for name in ('brand_new.py', 'doomed.txt', 'README.md',
                     'src/core/engine.py'):
            self.assertIn(name, text, '%s is missing from the page' % name)
        self.assertIn('─────', text, 'no rule between files')

    def test_added_and_deleted_files_start_folded(self):
        rv = self.a.review
        self.assertIn('brand_new.py', rv.collapsed)
        self.assertIn('doomed.txt', rv.collapsed)
        self.assertNotIn('README.md', rv.collapsed, 'a modified file should be open')
        self.assertIn('folded', self.whole(self.a))

    def test_a_folded_file_can_be_opened_and_shut_again(self):
        rv = self.a.review
        rv.toggle('brand_new.py')
        self.a.render()
        self.assertIn('print(1)', self.whole(self.a), 'opening it showed nothing')
        rv.toggle('brand_new.py')
        self.a.render()
        self.assertNotIn('print(1)', self.whole(self.a))

    def test_clicking_a_heading_folds_it(self):
        rv = self.a.review
        rect = self.a.rects['editor']
        y = self.heading_row('README.md')
        self.a.handle_mouse(Mouse('press', rect.x + 4, y))
        self.assertIn('README.md', rv.collapsed, 'the click did not fold it')
        self.a.render()
        self.assertIn('▸ M README.md', self.whole(self.a))

    def test_it_shows_the_changes_not_the_whole_file(self):
        text = self.whole(self.a)
        self.assertIn('line 21 CHANGED', text)
        self.assertIn('unchanged lines', text, 'the untouched middle is still there')
        self.assertNotIn('line 3 ', text, 'a far away line was included')

    def test_both_versions_are_side_by_side(self):
        rv = self.a.review
        rv.show('README.md')
        self.a.render()
        rows = [self.page(self.a, y) for y in range(self.a.rects['editor'].y,
                                                    self.a.rects['editor'].y2)]
        joined = '\n'.join(rows)
        self.assertIn('last commit', joined)
        self.assertIn('working tree', joined)
        self.assertIn('|', joined, 'no divider down the middle')

    def test_nothing_in_it_can_be_edited(self):
        text_before = open(os.path.join(self.tmp, 'README.md')).read()
        for ch in 'XYZ':
            self.a.handle_key(Key('char', char=ch))
        self.a.render()
        self.assertEqual(open(os.path.join(self.tmp, 'README.md')).read(),
                         text_before, 'the review wrote to a file')

    def test_it_keeps_up_when_a_file_changes_underneath(self):
        rv = self.a.review
        self.write('README.md', 'hello\nthere\nworld\nand more\n')
        self.assertTrue(rv.refresh(), 'the review did not notice')
        self.a.render()
        self.assertIn('and more', self.whole(self.a))

    def test_a_new_change_appears_in_the_list(self):
        rv = self.a.review
        self.write('later.py', 'x = 1\n')
        self.assertFalse(rv.refresh(), 'it asked git again straight away')
        rv._last_scan = 0.0                      # as if the interval had passed
        self.assertTrue(rv.refresh(), 'the new file was never noticed')
        self.assertIn('later.py', dict(rv.files))
        self.a.render()
        self.assertIn('later.py', self.whole(self.a))


class TestFoldSettings(ReviewTest):
    """Which kinds of file start open is a preference."""

    def open_with(self, **prefs):
        self.change_everything()
        app = self.app()
        for key, value in prefs.items():
            app.settings[key] = value
        app.open_review()
        app.render()
        return app

    def test_added_files_can_start_open(self):
        app = self.open_with(review_open_added=True)
        self.assertNotIn('brand_new.py', app.review.collapsed)
        self.assertIn('print(1)', self.whole(app))

    def test_deleted_files_can_start_open(self):
        app = self.open_with(review_open_deleted=True)
        self.assertNotIn('doomed.txt', app.review.collapsed)
        self.assertIn('delete me', self.whole(app))

    def test_modified_files_can_start_folded(self):
        app = self.open_with(review_open_modified=False)
        self.assertIn('README.md', app.review.collapsed)
        self.assertNotIn('line 21 CHANGED', self.whole(app))

    def test_the_defaults_are_the_github_ones(self):
        from tide import settings as store
        self.assertTrue(store.DEFAULTS['review_open_modified'])
        self.assertFalse(store.DEFAULTS['review_open_added'])
        self.assertFalse(store.DEFAULTS['review_open_deleted'])

    def test_changing_it_while_reviewing_takes_effect(self):
        app = self.open_with()
        self.assertIn('brand_new.py', app.review.collapsed)
        app.set_setting('review_open_added', True)
        app.render()
        self.assertNotIn('brand_new.py', app.review.collapsed,
                         'the review did not follow the setting')
        self.assertIn('print(1)', self.whole(app))

    def test_it_is_one_of_the_settings_you_can_click(self):
        from tide import settings as store
        keys = [key for key, _label, _values in store.FIELDS]
        for key in ('review_open_modified', 'review_open_added',
                    'review_open_deleted'):
            self.assertIn(key, keys, '%s is not in the settings panel' % key)


class TestTheFileList(ReviewTest):
    def setUp(self):
        ReviewTest.setUp(self)
        self.change_everything()
        self.a = self.app()
        self.a.open_review()
        self.a.render()

    def test_it_shows_the_folders_the_files_are_in(self):
        rows = [self.side(self.a, y) for y in range(1, 8)]
        joined = '\n'.join(rows)
        self.assertIn('src', joined)
        self.assertIn('core', joined)
        self.assertIn('engine.py', joined)

    def test_it_shows_only_the_files_that_changed(self):
        rows = '\n'.join(self.side(self.a, y) for y in range(1, 10))
        self.assertNotIn('moved.py', rows, 'a pure move is in the list')

    def test_each_file_carries_its_letter(self):
        rows = '\n'.join(self.side(self.a, y) for y in range(1, 10))
        for letter in ('U', 'D', 'M'):
            self.assertIn(letter, rows)

    def test_clicking_a_file_moves_the_page_to_it(self):
        rv = self.a.review
        rv.rect = self.a.rects['editor']
        target = 'src/core/engine.py'
        self.assertTrue(rv.show(target))
        self.assertEqual(rv.nodes[rv.index].path, target)
        self.assertTrue(rv.top == rv.starts[target] or rv.top == rv.max_top(),
                        'the page did not move as far as it could')

    def test_the_list_follows_the_page(self):
        rv = self.a.review
        rv.show('README.md')
        self.assertEqual(rv.nodes[rv.index].path, 'README.md')


class TestGettingInAndOut(ReviewTest):
    def test_it_will_not_open_outside_a_repository(self):
        plain = tempfile.mkdtemp(prefix='tide-plain-')
        try:
            with open(os.path.join(plain, 'a.txt'), 'w') as f:
                f.write('x\n')
            app = App(root=plain, paths=[], out=io.StringIO())
            app.screen = Screen(100, 24)
            app.render()
            self.assertFalse(app.open_review())
            self.assertIsNone(app.review)
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_escape_puts_back_exactly_what_was_there(self):
        self.change_everything()
        app = self.app()
        app.open_file(os.path.join(self.tmp, 'README.md'))
        app.open_file(os.path.join(self.tmp, 'src/core/engine.py'))
        app.editor.top = 12
        before = ([e.title for e in app.editors], app.active, app.main_view,
                  app.split, app.editor.top)
        app.open_review()
        app.render()
        app.handle_key(Key('escape'))
        app.render()
        after = ([e.title for e in app.editors], app.active, app.main_view,
                 app.split, app.editor.top)
        self.assertIsNone(app.review)
        self.assertEqual(before, after, 'the editor came back different')
        self.assertIn('engine.py', self.whole(app))

    def test_the_x_button_closes_it_too(self):
        self.change_everything()
        app = self.app()
        app.open_review()
        app.render()
        span = app.review_close_span
        app.handle_mouse(Mouse('press', span[0] + 1, app.rects['switch'].y))
        self.assertIsNone(app.review)

    def test_the_button_in_the_top_bar_opens_it(self):
        self.change_everything()
        app = self.app()
        app.render()
        self.assertIsNotNone(app.review_span, 'no review button in a repository')
        app.handle_mouse(Mouse('press', app.review_span[0] + 1,
                               app.rects['switch'].y))
        self.assertIsNotNone(app.review)

    def test_split_view_is_put_aside_and_given_back(self):
        self.change_everything()
        app = self.app()
        app.open_file(os.path.join(self.tmp, 'README.md'))
        app.split = True
        app.render()
        app.open_review()
        app.render()
        self.assertIsNone(app.rects['split'], 'the split survived into the review')
        self.assertIn('GIT REVIEW', self.whole(app))
        app.handle_key(Key('escape'))
        app.render()
        self.assertTrue(app.split, 'split view was not given back')


class TestReviewInASession(unittest.TestCase):
    """Through a pty: the shell below keeps running, and the editor comes back."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-review-live-')
        with open(os.path.join(self.tmp, 'code.py'), 'w') as f:
            f.write('def greet():\n    return 1\n')
        for cmd in (['init', '-q', '-b', 'main'],
                    ['config', 'user.email', 'crew@harbour'],
                    ['config', 'user.name', 'Crew'],
                    ['add', '-A'], ['commit', '-q', '-m', 'first']):
            git(self.tmp, *cmd)
        with open(os.path.join(self.tmp, 'code.py'), 'w') as f:
            f.write('def greet():\n    return 2\n')
        self.s = Session([os.path.join(self.tmp, 'code.py'), self.tmp],
                         cols=110, rows=28, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_review_opens_over_everything_and_leaves_it_alone(self):
        s = self.s
        s.click(60, 20)                            # into the docked shell
        s.type('echo MARKER_ONE' + ENTER)
        self.assertTrue(s.wait_for('MARKER_ONE'))
        s.key(F10)
        s.pump(1.0)
        screen = s.screen()
        self.assertIn('GIT REVIEW', screen)
        self.assertIn('CHANGES', screen, 'the changed-file list is missing')
        self.assertIn('code.py', screen)
        self.assertIn('MARKER_ONE', screen, 'the docked shell was thrown away')

        s.type('echo MARKER_TWO' + ENTER)          # still a live shell
        self.assertTrue(s.wait_for('MARKER_TWO'))

        s.key(ESC)
        s.pump(0.8)
        back = s.screen()
        self.assertNotIn('GIT REVIEW', back)
        self.assertIn('def greet', back, 'the editor did not come back')
        self.assertIn('EXPLORER', back, 'the file tree did not come back')

    def test_a_full_size_terminal_survives_a_review(self):
        s = self.s
        s.key(ESC + 'OQ')                          # f2: full-size terminals
        s.pump(0.8)
        s.type('echo BEFORE_REVIEW' + ENTER)
        self.assertTrue(s.wait_for('BEFORE_REVIEW'))
        s.key(F10)
        s.pump(1.0)
        self.assertIn('GIT REVIEW', s.screen())
        self.assertNotIn('BEFORE_REVIEW', s.screen(), 'the terminal is still drawn')
        s.key(ESC)
        s.pump(0.8)
        self.assertIn('BEFORE_REVIEW', s.screen(),
                      'the terminal did not come back as it was')
        s.type('echo AFTER_REVIEW' + ENTER)
        self.assertTrue(s.wait_for('AFTER_REVIEW'), 'the shell stopped running')

    def test_typing_in_the_review_changes_no_file(self):
        s = self.s
        s.key(F10)
        s.pump(1.0)
        s.type('these keys should go nowhere')
        s.pump(0.6)
        s.key(ESC)
        s.pump(0.8)
        with open(os.path.join(self.tmp, 'code.py')) as f:
            self.assertEqual(f.read(), 'def greet():\n    return 2\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
