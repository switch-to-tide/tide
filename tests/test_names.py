"""What tabs are called: duplicates, long names, and running programs."""

import io
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import ENTER, ESC, Session
from tide import names
from tide.app import App
from tide.term import Screen

F2, F4 = ESC + 'OQ', ESC + 'OS'


class TestTitles(unittest.TestCase):
    def test_a_name_on_its_own_is_left_alone(self):
        self.assertEqual(names.titles(['/p/a.py', '/p/b.py']), ['a.py', 'b.py'])

    def test_two_of_the_same_name_get_the_folder_that_differs(self):
        got = names.titles(['/p/alpha/models/s.py', '/p/beta/models/s.py'])
        self.assertEqual(got, ['alpha/models/s.py', 'beta/models/s.py'])

    def test_only_as_much_path_as_it_takes(self):
        got = names.titles(['/p/alpha/s.py', '/p/beta/s.py'])
        self.assertEqual(got, ['alpha/s.py', 'beta/s.py'])

    def test_three_of_them(self):
        got = names.titles(['/a/x/s.py', '/a/y/s.py', '/b/x/s.py'])
        self.assertEqual(len(set(got)), 3, got)
        self.assertTrue(all(g.endswith('s.py') for g in got), got)

    def test_a_buffer_with_no_path_is_the_caller_s_business(self):
        self.assertEqual(names.titles([None, '/p/a.py']), [None, 'a.py'])

    def test_duplicates_do_not_disturb_their_neighbours(self):
        got = names.titles(['/a/s.py', '/b/s.py', '/c/other.py'])
        self.assertEqual(got[2], 'other.py')


class TestCropping(unittest.TestCase):
    def test_a_short_name_is_untouched(self):
        self.assertEqual(names.crop('main.py', 20), 'main.py')

    def test_a_long_name_keeps_its_start(self):
        got = names.crop('a_very_long_module_name_here.py', 12)
        self.assertEqual(got, 'a_very_long…')
        self.assertEqual(len(got), 12)

    def test_a_long_path_keeps_its_end(self):
        got = names.crop('alpha/models/schema.py', 14)
        self.assertEqual(got, '…els/schema.py')
        self.assertEqual(len(got), 14)


class TestProgramNames(unittest.TestCase):
    def test_what_each_command_is_called(self):
        cases = [
            ('/bin/sh', 'sh'),
            ('-zsh', 'zsh'),                        # a login shell
            ('claude', 'claude'),
            ('uv run dev', 'uv run'),
            ('git log --oneline', 'git log'),
            ('python3 app.py', 'python3 app.py'),
            ('python3 -c import time', 'python3'),  # the code is not a name
            ('node /long/path/server.js', 'node server.js'),
            ('vim notes.txt', 'vim'),
            ('sudo apt update', 'apt'),        # sudo is not the program
        ]
        for command, want in cases:
            self.assertEqual(names.program_name(command), want, command)

    def test_a_very_long_command_is_cropped(self):
        got = names.program_name('python3 some_extremely_long_script_name.py')
        self.assertLessEqual(len(got), names.MAX_PROGRAM)
        self.assertTrue(got.endswith('…'), got)

    def test_nothing_at_all(self):
        self.assertEqual(names.program_name('   '), '')


class TestTabsInTheApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-names-')
        self.cfg = tempfile.mkdtemp(prefix='tide-names-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        for folder in ('alpha/models', 'beta/models'):
            os.makedirs(os.path.join(self.tmp, folder))
            with open(os.path.join(self.tmp, folder, 'schema.py'), 'w') as f:
                f.write('x = 1\n')
        self.long = 'a_very_long_module_name_for_testing_truncation.py'
        with open(os.path.join(self.tmp, self.long), 'w') as f:
            f.write('y = 2\n')

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def app(self, *paths):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(100, 24)
        app.show_term = False
        for p in paths:
            app.open_file(os.path.join(self.tmp, p))
        app.render()
        return app

    def tab_row(self, app):
        y = app.rects['tabs'].y
        return ''.join(c[0] or ' ' for c in app.screen.cells[y])

    def test_two_files_with_one_name_are_told_apart(self):
        app = self.app('alpha/models/schema.py', 'beta/models/schema.py')
        titles = app.editor_titles()
        self.assertEqual(titles, ['alpha/models/schema.py', 'beta/models/schema.py'])
        self.assertEqual(len(app.editors), 2, 'they should be two buffers')

    def test_and_they_still_open_and_edit_separately(self):
        app = self.app('alpha/models/schema.py', 'beta/models/schema.py')
        app.editors[0].doc.cursor = (0, 0)
        app.editors[0].doc.insert('first ')
        self.assertNotEqual(app.editors[0].doc.text(), app.editors[1].doc.text())
        self.assertNotEqual(app.editors[0].path, app.editors[1].path)

    def test_one_of_them_alone_is_just_its_name(self):
        app = self.app('alpha/models/schema.py')
        self.assertEqual(app.editor_titles(), ['schema.py'])

    def test_a_long_file_name_is_cropped_in_the_tab(self):
        app = self.app(self.long)
        title = app.editor_titles()[0]
        self.assertLessEqual(len(title), names.MAX_TAB)
        self.assertTrue(title.endswith('…'), title)
        self.assertIn(title, self.tab_row(app), 'the cropped name is not painted')

    def test_a_long_name_does_not_swallow_the_tab_strip(self):
        app = self.app(self.long, 'alpha/models/schema.py')
        row = self.tab_row(app)
        self.assertIn('schema.py', row, 'the second tab was pushed off screen')

    def test_a_long_name_is_cropped_in_the_explorer_too(self):
        app = self.app()
        side = app.rects['sidebar']
        row = ''.join(c[0] or ' ' for c in
                      app.screen.cells[side.y + 3][side.x:side.x2])
        self.assertIn('…', row, 'the explorer cut the name with no sign of it')
        self.assertNotIn(self.long, row)
        # the name must not run past the pane, whatever draws its edge
        edge = app.rects['sidebar'].x2
        self.assertIn(app.screen.cells[side.y + 3][edge][0], ('│', ' '),
                      'the name ran over the edge of the pane')


class TestTerminalTabNames(unittest.TestCase):
    """Through a pty: the tab follows whatever the shell is running."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-termnames-')
        with open(os.path.join(self.tmp, 'a.py'), 'w') as f:
            f.write('x = 1\n')
        self.s = Session([self.tmp], cols=100, rows=24, cwd=self.tmp)
        self.s.pump(0.8)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tabs(self):
        row = self.s.vt.grid[self.s.TAB_ROW]
        return ''.join(c[0] or ' ' for c in row).rstrip()

    def settle(self, seconds=1.2):
        self.s.pump(0.8)
        time.sleep(seconds)
        self.s.pump(0.8)

    def test_a_new_terminal_is_named_after_its_shell(self):
        self.s.key(F2)
        self.settle()
        self.assertIn(' sh ', self.tabs(), self.tabs())
        self.assertNotIn('terminal 1', self.tabs())

    def test_it_follows_the_program_and_comes_back(self):
        self.s.key(F2)
        self.settle()
        self.s.type('sleep 20' + ENTER)
        self.settle()
        self.assertIn('sleep', self.tabs(), self.tabs())
        self.s.key('\x03')                      # ctrl+c
        self.settle()
        self.assertIn(' sh ', self.tabs(), self.tabs())

    def test_each_session_is_named_for_itself(self):
        self.s.key(F2)
        self.settle()
        self.s.type('sleep 20' + ENTER)
        self.settle()
        self.s.key(F4)                          # a second session, idle
        self.settle()
        row = self.tabs()
        self.assertIn('sleep', row, row)
        self.assertIn('sh', row, row)


if __name__ == '__main__':
    unittest.main(verbosity=2)
