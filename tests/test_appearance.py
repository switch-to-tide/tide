"""Two appearances over one layout: classic panes, and modern boxes."""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import ESC, Session
from tide import chrome, settings as store, theme
from tide.app import App, MIN_SIDEBAR_W
from tide.keys import Mouse
from tide.term import Screen

F5 = ESC + '[15~'
CORNERS = '╭╮╰╯'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class LookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-look-')
        self.cfg = tempfile.mkdtemp(prefix='tide-look-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        os.makedirs(os.path.join(self.tmp, 'src'))
        with open(os.path.join(self.tmp, 'src', 'app.py'), 'w') as f:
            f.write('def main():\n    return 1\n')
        with open(os.path.join(self.tmp, 'README.md'), 'w') as f:
            f.write('# demo\n')

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        theme.apply('dark', 'classic')
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def app(self, look='classic', name='dark', cols=100, rows=24, terminal=True):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(cols, rows)
        app.show_term = terminal
        app.open_file(os.path.join(self.tmp, 'src', 'app.py'))
        app.settings['appearance'] = look
        app.settings['theme'] = name
        theme.apply(name, look)
        app.render()
        return app

    def screen(self, app):
        return '\n'.join(''.join(c[0] or ' ' for c in row)
                         for row in app.screen.cells)


class TestPalettes(LookTest):
    def test_each_appearance_offers_its_own_palettes(self):
        self.assertEqual(theme.names_for('classic'),
                         ['dark', 'midnight', 'ember', 'light'])
        self.assertEqual(theme.names_for('modern'),
                         ['dark', 'alien', 'forest', 'parchment', 'octopus',
                          'light'])

    def test_the_classic_palettes_are_untouched(self):
        for name in theme.names_for('classic'):
            theme.apply(name, 'classic')
            self.assertEqual(theme.current, name)
            self.assertFalse(theme.BOXED, '%s should be flush' % name)
        theme.apply('dark', 'classic')
        self.assertEqual(theme.BG, theme.DARK['BG'])
        self.assertEqual(theme.PANEL, theme.DARK['PANEL'])

    def test_the_modern_palettes_are_boxed(self):
        for name in theme.names_for('modern'):
            theme.apply(name, 'modern')
            self.assertTrue(theme.BOXED, '%s should be boxed' % name)

    def test_the_dark_ones_are_dark_and_the_light_one_is_light(self):
        theme.apply('alien', 'modern')
        alien = theme.BG
        theme.apply('forest', 'modern')
        forest = theme.BG
        theme.apply('light', 'modern')
        light = theme.BG
        self.assertLess(alien, 240, 'alien is not a dark background')
        self.assertLess(forest, 240, 'forest is not a dark background')
        self.assertGreater(light, 240, 'the light one is not light')
        self.assertNotEqual(alien, forest, 'the two dark ones are the same')

    def test_every_palette_defines_every_colour(self):
        keys = set(theme.DARK)
        for look in ('classic', 'modern'):
            for name in theme.names_for(look):
                palette = theme.APPEARANCES[look][name]
                self.assertEqual(set(palette), keys,
                                 '%s/%s has the wrong keys' % (look, name))

    def test_an_unknown_palette_falls_back_inside_its_appearance(self):
        self.assertEqual(theme.apply('midnight', 'modern'), 'dark')
        self.assertEqual(theme.apply('forest', 'classic'), 'dark')

    def test_a_palette_brings_its_appearance_along(self):
        self.assertEqual(theme.appearance_for('forest', 'classic'), 'modern')
        self.assertEqual(theme.appearance_for('ember', 'modern'), 'classic')
        self.assertEqual(theme.appearance_for('dark', 'modern'), 'modern')


class TestTheSettings(LookTest):
    def test_the_panel_does_not_offer_the_appearance_any_more(self):
        # classic is deprecated: --appearance still reaches it, the settings
        # do not
        self.assertEqual(store.DEFAULTS['appearance'], 'modern')
        self.assertNotIn('appearance', [key for key, _l, _v in store.FIELDS])

    def test_a_session_is_modern_whatever_is_written_down(self):
        import io
        from tide.term import Screen
        folder = os.path.dirname(store.config_path())
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(store.config_path(), 'w') as f:
            f.write('{"appearance": "classic", "theme": "midnight"}')
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(90, 20)
        self.assertEqual(app.settings['appearance'], 'modern')
        self.assertEqual(app.settings['theme'], 'dark',
                         'midnight is a classic palette; it should fall back')
        self.assertTrue(theme.BOXED)

    def test_the_themes_on_offer_follow_the_appearance(self):
        self.assertEqual(store.choices('theme', {'appearance': 'modern'}),
                         ['dark', 'alien', 'forest', 'parchment', 'octopus',
                          'light'])
        self.assertEqual(store.choices('theme', {'appearance': 'classic'}),
                         ['dark', 'midnight', 'ember', 'light'])

    def test_switching_appearance_keeps_a_palette_both_of_them_have(self):
        app = self.app('classic', 'light')
        app.set_setting('appearance', 'modern')
        self.assertEqual(app.settings['theme'], 'light')
        self.assertTrue(theme.BOXED)

    def test_switching_appearance_drops_one_it_does_not_have(self):
        app = self.app('classic', 'ember')
        app.set_setting('appearance', 'modern')
        self.assertEqual(app.settings['theme'], 'dark',
                         'ember does not exist in modern')

    def test_it_is_written_down_and_read_back(self):
        app = self.app('classic', 'dark')
        app.set_setting('appearance', 'modern')
        app.set_setting('theme', 'forest')
        stored = store.load()
        self.assertEqual(stored['appearance'], 'modern')
        self.assertEqual(stored['theme'], 'forest')

    def test_a_nonsense_file_falls_back(self):
        path = store.config_path()
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, 'w') as f:
            f.write('{"appearance": "sideways", "theme": "puce"}')
        values = store.load()
        self.assertEqual(values['appearance'], 'modern')
        self.assertEqual(values['theme'], 'dark')


class TestClassicIsUnchanged(LookTest):
    def test_no_boxes_anywhere(self):
        app = self.app('classic', 'dark')
        painted = self.screen(app)
        for corner in CORNERS:
            self.assertNotIn(corner, painted, 'classic grew a box')

    def test_the_panes_are_where_they_always_were(self):
        app = self.app('classic', 'dark')
        r = app.rects
        self.assertEqual(r['sidebar'].x, 0)
        self.assertEqual(r['tabs'].y, 1)
        self.assertEqual(r['editor'].y, 2)
        self.assertIsNone(r.get('editor_box'))
        self.assertEqual(r['editor'].x2, app.screen.width)


class TestModernBoxes(LookTest):
    def test_every_pane_gets_a_box(self):
        app = self.app('modern', 'forest')
        r = app.rects
        for key in ('sidebar_box', 'editor_box', 'terminal_box'):
            self.assertIn(key, r, '%s has no box' % key)
        painted = self.screen(app)
        for corner in CORNERS:
            self.assertIn(corner, painted, 'no %s drawn' % corner)

    def test_the_boxes_do_not_touch(self):
        app = self.app('modern', 'forest')
        r = app.rects
        side, main = r['sidebar_box'], r['editor_box']
        self.assertGreater(main.x, side.x2, 'the side and main boxes touch')
        self.assertGreater(side.x, 0, 'no margin on the left')
        # on the right the boxes reach the edge: the scrollbar and the change
        # ruler take enough room over there as it is
        self.assertEqual(main.x2, app.screen.width,
                         'the main box no longer reaches the right edge')
        # above and below they meet on adjacent rows: a blank row reads as
        # twice the gap a blank column does, cells being taller than wide
        self.assertEqual(r['terminal_box'].y, main.y2,
                         'the editor and terminal boxes have drifted apart')

    def test_the_tabs_moved_inside_the_pane(self):
        app = self.app('modern', 'forest')
        box, tabs = app.rects['editor_box'], app.rects['tabs']
        self.assertTrue(box.contains(tabs.x, tabs.y), 'the tabs are outside')
        self.assertIn('app.py', self.screen(app))

    def test_the_open_tab_stands_out(self):
        for name in theme.names_for('modern'):
            app = self.app('modern', name)
            app.open_file(os.path.join(self.tmp, 'README.md'))
            app.render()
            row = app.screen.cells[app.rects['tabs'].y]
            active = [x for x, cell in enumerate(row)
                      if cell[2] == theme.TAB_ACTIVE_BG]
            self.assertNotEqual(theme.TAB_ACTIVE_BG, theme.TAB_BG,
                                '%s cannot show which tab is open' % name)
            self.assertTrue(active, 'nothing is drawn as the open tab')
            painted = ''.join(row[x][0] or ' ' for x in active)
            self.assertIn('README', painted, 'the wrong tab looks open')

    def test_the_tabs_have_room_to_breathe(self):
        app = self.app('modern', 'forest')
        box, tabs, editor = (app.rects['editor_box'], app.rects['tabs'],
                             app.rects['editor'])
        self.assertGreater(tabs.x, box.x + 1, 'the tabs sit on the border')
        self.assertEqual(editor.y, tabs.y + 2, 'no blank row under the tabs')
        blank = ''.join(c[0] or ' ' for c in app.screen.cells[tabs.y + 1]
                        [box.x + 1:box.x2 - 1])
        self.assertEqual(blank.strip(), '', 'the row under the tabs is not clear')

    def test_the_contents_are_the_same_as_ever(self):
        app = self.app('modern', 'forest')
        painted = self.screen(app)
        for expected in ('EXPLORER', 'app.py', 'def main():', 'TERMINAL'):
            self.assertIn(expected, painted, '%s is missing' % expected)

    def test_split_view_makes_two_boxes(self):
        app = self.app('modern', 'alien')
        app.split = True
        app.new_big_terminal()
        app.render()
        r = app.rects
        self.assertIn('split_box', r)
        self.assertGreater(r['split_box'].x, r['editor_box'].x2,
                           'the two halves touch')
        painted = self.screen(app)
        self.assertIn('app.py', painted)
        self.assertNotIn('│|│', painted, 'the old divider is still drawn')

    def test_switching_back_and_forth_restores_the_layout(self):
        app = self.app('modern', 'forest')
        boxed = (app.rects['editor'].x, app.rects['editor'].w)
        app.set_setting('appearance', 'classic')
        app.render()
        flush = (app.rects['editor'].x, app.rects['editor'].w)
        self.assertNotEqual(boxed, flush)
        self.assertNotIn('╭', self.screen(app))
        app.set_setting('appearance', 'modern')
        app.render()
        self.assertEqual((app.rects['editor'].x, app.rects['editor'].w), boxed)

    def test_a_narrow_window_still_draws_something_sensible(self):
        app = self.app('modern', 'forest', cols=44, rows=14)
        painted = self.screen(app)
        self.assertIn('app.py', painted)
        self.assertLessEqual(max(len(line) for line in painted.split('\n')), 44)


class TestDraggingStillWorks(LookTest):
    def press(self, app, x, y):
        app.handle_mouse(Mouse('press', x, y))

    def test_the_side_divider_still_drags(self):
        app = self.app('modern', 'forest')
        column = chrome.grab_column(app.rects)
        self.assertIsNotNone(column)
        self.press(app, column, 6)
        self.assertEqual(app.mouse_capture, 'vsplitter')
        app.handle_mouse(Mouse('drag', column + 10, 6))
        app.render()
        self.assertEqual(app.sidebar_w, column + 11)
        app.handle_mouse(Mouse('release', column + 10, 6))

    def test_the_side_panel_still_has_a_floor(self):
        app = self.app('modern', 'forest')
        self.press(app, chrome.grab_column(app.rects), 6)
        app.handle_mouse(Mouse('drag', 0, 6))
        app.render()
        self.assertGreaterEqual(app.sidebar_w, MIN_SIDEBAR_W)

    def test_the_bottom_divider_still_drags(self):
        app = self.app('modern', 'forest')
        row = chrome.grab_row(app.rects)
        self.assertIsNotNone(row)
        before = app.rects['terminal'].h
        self.press(app, 50, row)
        self.assertEqual(app.mouse_capture, 'splitter')
        app.handle_mouse(Mouse('drag', 50, row - 4))
        app.render()
        self.assertGreater(app.rects['terminal'].h, before)

    def test_clicking_inside_a_pane_still_focuses_it(self):
        app = self.app('modern', 'forest')
        self.press(app, app.rects['terminal'].x + 3, app.rects['terminal'].y + 1)
        self.assertEqual(app.focus, 'terminal')
        self.press(app, app.rects['editor'].x + 3, app.rects['editor'].y + 1)
        self.assertEqual(app.focus, 'editor')


class TestModernInAReview(LookTest):
    def test_the_review_is_boxed_too(self):
        for cmd in (['init', '-q', '-b', 'main'],
                    ['config', 'user.email', 'crew@harbour'],
                    ['config', 'user.name', 'Crew'],
                    ['add', '-A'], ['commit', '-q', '-m', 'first']):
            git(self.tmp, *cmd)
        with open(os.path.join(self.tmp, 'src', 'app.py'), 'w') as f:
            f.write('def main():\n    return 2\n')
        app = self.app('modern', 'forest')
        app.git.refresh(force=True)
        self.assertTrue(app.open_review())
        app.render()
        painted = self.screen(app)
        self.assertIn('GIT REVIEW', painted)
        self.assertIn('╭', painted, 'the review lost the boxes')
        self.assertIn('CHANGES', painted)


class TestModernInASession(unittest.TestCase):
    """Through a pty, so the flags and the real terminal are in it too."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-look-live-')
        with open(os.path.join(self.tmp, 'code.py'), 'w') as f:
            f.write('def greet():\n    return 1\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_flag_starts_it_in_the_modern_look(self):
        s = Session(['--appearance', 'modern', os.path.join(self.tmp, 'code.py'),
                     self.tmp], cols=90, rows=22, cwd=self.tmp)
        try:
            painted = s.screen()
            self.assertIn('╭', painted, 'no boxes with --appearance modern')
            self.assertIn('def greet', painted)
            s.type('X')
            s.pump(0.5)
            self.assertIn('Xdef greet', s.screen(), 'editing broke in the boxes')
        finally:
            s.close()

    def test_a_modern_palette_brings_the_modern_look_with_it(self):
        s = Session(['--theme', 'alien', self.tmp], cols=90, rows=22, cwd=self.tmp)
        try:
            self.assertIn('╭', s.screen(), 'alien did not bring its appearance')
        finally:
            s.close()

    def test_classic_is_still_there_behind_the_flag(self):
        s = Session(['--appearance', 'classic',
                     os.path.join(self.tmp, 'code.py'), self.tmp],
                    cols=90, rows=22, cwd=self.tmp)
        try:
            painted = s.screen()
            self.assertNotIn('╭', painted)
            self.assertIn('EXPLORER', painted)
        finally:
            s.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
