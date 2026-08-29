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

    def strip_x(self):
        """Where the tab strip starts, past the explorer and the pane's frame."""
        line = self.s.line(self.s.TAB_ROW)
        x = 26
        while x < len(line) and line[x] in '│ ':
            x += 1
        return x

    def tabs(self):
        return self.s.line(self.s.TAB_ROW)[self.strip_x():].rstrip().rstrip('│ ')

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
        self.s.click(self.strip_x(), self.s.TAB_ROW)   # the '<' at the left
        self.assertNotEqual(self.tabs(), before)

    def test_scrolling_does_not_change_the_active_file(self):
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=10)
        self.assertIn('inside theta_extra.py', self.s.screen(),
                      'the active file changed while scrolling')

    def test_a_visible_tab_can_still_be_clicked(self):
        self.s.wheel(60, self.s.TAB_ROW, up=True, times=14)
        strip = self.tabs()
        self.assertIn('beta_helpers.py', strip)
        self.s.click(self.strip_x() + strip.index('beta_helpers.py') + 1,
                     self.s.TAB_ROW)
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
        self.assertTrue(self.tabs().startswith('sh  x '),
                        'the terminal strip did not scroll')
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


class TestSwitchingBack(unittest.TestCase):
    """ctrl+t: the tab before this one, inside its own group."""

    def setUp(self):
        import io
        from tide.term import Screen
        self.tmp = tempfile.mkdtemp(prefix='tide-back-')
        self.cfg = tempfile.mkdtemp(prefix='tide-back-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        for name in ('a.py', 'b.py', 'c.py'):
            with open(os.path.join(self.tmp, name), 'w') as f:
                f.write('# %s\n' % name)
        self.app = App(root=self.tmp, paths=[], out=io.StringIO())
        self.app.screen = Screen(90, 20)
        self.app.show_term = False
        for name in ('a.py', 'b.py', 'c.py'):
            self.app.open_file(os.path.join(self.tmp, name))
            self.app.render()

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def press(self):
        from tide.keys import CTRL, Key
        self.app.handle_key(Key('char', 't', CTRL))
        self.app.render()

    def here(self):
        return self.app.editors[self.app.active].title

    def test_it_goes_back_and_forth_between_two(self):
        self.assertEqual(self.here(), 'c.py')
        self.press()
        self.assertEqual(self.here(), 'b.py')
        self.press()
        self.assertEqual(self.here(), 'c.py')
        self.press()
        self.assertEqual(self.here(), 'b.py')

    def test_it_follows_wherever_you_were_last(self):
        self.app.active = 0                      # as if clicked
        self.app.render()
        self.press()
        self.assertEqual(self.here(), 'c.py', 'it did not remember the last one')

    def test_closing_the_other_one_leaves_nothing_to_go_back_to(self):
        self.press()                             # c -> b, so c is the partner
        self.app.close_tab(self.app.editors.index(
            [e for e in self.app.editors if e.title == 'c.py'][0]))
        self.app.render()
        where = self.here()
        self.press()
        self.assertEqual(self.here(), where, 'it jumped somewhere unasked')

    def test_one_tab_alone_does_nothing(self):
        while len(self.app.editors) > 1:
            self.app.close_tab(0)
            self.app.render()
        where = self.here()
        self.press()
        self.assertEqual(self.here(), where)

    def test_it_no_longer_opens_the_settings(self):
        from tide.overlay import SettingsPanel
        self.press()
        self.assertNotIsInstance(self.app.overlay, SettingsPanel,
                                 'ctrl+t still opens the settings')

    def test_f9_still_opens_the_settings(self):
        from tide.keys import Key
        self.app.handle_key(Key('f9'))
        from tide.overlay import SettingsPanel
        self.assertIsInstance(self.app.overlay, SettingsPanel)

    def test_shells_swap_with_shells(self):
        self.app.new_big_terminal()
        self.app.render()
        self.app.new_big_terminal()
        self.app.render()
        self.assertEqual(self.app.main_view, 'terminal')
        first = self.app.big_active
        self.press()
        self.assertNotEqual(self.app.big_active, first, 'the shells did not swap')
        self.assertEqual(self.here(), 'c.py', 'it moved a file tab as well')
        for term in self.app.big_terms:
            term.stop()


class TestTheMenus(unittest.TestCase):
    """Tide, View and Help across the top, and what they do."""

    def setUp(self):
        import io
        from tide.term import Screen
        self.tmp = tempfile.mkdtemp(prefix='tide-menu-')
        self.cfg = tempfile.mkdtemp(prefix='tide-menu-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        os.makedirs(os.path.join(self.tmp, 'sub'))
        for rel in ('a.py', 'sub/deep.py'):
            with open(os.path.join(self.tmp, *rel.split('/')), 'w') as f:
                f.write('x = 1\n')
        self.app = App(root=self.tmp, paths=[], out=io.StringIO())
        self.app.screen = Screen(100, 24)
        self.app.show_term = True
        self.app.open_file(os.path.join(self.tmp, 'a.py'))
        self.app.render()

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def press(self, x, y):
        from tide.keys import Mouse
        self.app.handle_mouse(Mouse('press', x, y))
        self.app.render()

    def open_menu(self, name):
        span = next(s for s in self.app.menu_spans if s[2] == name)
        self.press(span[0] + 1, 0)
        return self.app.overlay

    def pick(self, label):
        menu = self.app.overlay
        for i, item in enumerate(menu.items):
            if item and label in item[0]:
                self.press(menu.rect.x + 2, menu.rect.y + 1 + i)
                return
        raise AssertionError('no %r in the menu' % label)

    def painted(self):
        return '\n'.join(''.join(c[0] or ' ' for c in row)
                          for row in self.app.screen.cells)

    def test_the_three_names_are_at_the_top_left(self):
        top = ''.join(c[0] or ' ' for c in self.app.screen.cells[0])
        self.assertLess(top.index('Tide'), top.index('View'))
        self.assertLess(top.index('View'), top.index('Help'))
        self.assertLess(top.index('Tide'), 4, 'the menus are not at the left')

    def test_the_old_buttons_are_gone_from_the_right(self):
        top = ''.join(c[0] or ' ' for c in self.app.screen.cells[0])
        self.assertNotIn('settings', top, 'settings should be in the Tide menu')
        self.assertNotIn('review', top, 'review should be in the View menu')

    def test_tide_offers_settings_open_and_quit(self):
        menu = self.open_menu('Tide')
        labels = [item[0] for item in menu.items if item]
        self.assertIn('Settings', labels[0])
        self.assertIn('session', ' '.join(labels))
        self.assertIn('Quit', labels[-1])
        self.assertNotIn('Open File', ' '.join(labels), 'that lives in File now')

    def test_view_offers_the_panes_and_the_review(self):
        menu = self.open_menu('View')
        labels = [item[0] for item in menu.items if item]
        self.assertTrue(any('Terminal' in l for l in labels))
        self.assertTrue(any('Split' in l for l in labels))
        self.assertTrue(any('Explorer' in l for l in labels))
        self.assertTrue(any('Git review' in l for l in labels))

    def test_the_ticks_follow_what_is_showing(self):
        menu = self.open_menu('View')
        showing = [item[0] for item in menu.items if item and '✓' in item[0]]
        self.assertTrue(any('Terminal' in l for l in showing))
        self.assertTrue(any('Explorer' in l for l in showing))
        self.assertFalse(any('Split' in l for l in showing))

    def test_settings_opens_from_the_menu(self):
        from tide.overlay import SettingsPanel
        self.open_menu('Tide')
        self.pick('Settings')
        self.assertIsInstance(self.app.overlay, SettingsPanel)

    def test_help_is_the_shortcut_list_itself(self):
        from tide.overlay import Help
        self.open_menu('Help')
        self.assertIsInstance(self.app.overlay, Help)

    def test_the_view_items_toggle_what_they_say(self):
        self.open_menu('View')
        self.pick('Terminal panel')
        self.assertFalse(self.app.show_term)
        self.open_menu('View')
        self.pick('Terminal panel')
        self.assertTrue(self.app.show_term)
        self.open_menu('View')
        self.pick('Explorer')
        self.assertFalse(self.app.show_tree)

    def test_clicking_the_name_again_closes_it(self):
        self.open_menu('Tide')
        self.assertIsNotNone(self.app.overlay)
        self.open_menu('Tide')
        self.assertIsNone(self.app.overlay)
        self.assertIsNone(self.app.menu_open)

    def test_escape_closes_it(self):
        from tide.keys import Key
        self.open_menu('View')
        self.app.handle_key(Key('escape'))
        self.assertIsNone(self.app.overlay)

    def test_the_keyboard_walks_the_items(self):
        from tide.keys import Key
        menu = self.open_menu('View')
        first = menu.index
        self.app.handle_key(Key('down'))
        self.assertNotEqual(menu.index, first)
        self.app.handle_key(Key('up'))
        self.assertEqual(menu.index, first)

    def test_the_highlight_follows_the_pointer_inside_the_menu(self):
        from tide.keys import Mouse
        menu = self.open_menu('View')
        rows = [i for i, item in enumerate(menu.items) if item is not None]
        for target in (rows[2], rows[0], rows[-1]):
            self.app.handle_mouse(Mouse('move', menu.rect.x + 3,
                                        menu.rect.y + 1 + target))
            self.assertEqual(menu.index, target)

    def test_split_view_never_offers_the_editor_terminal_switch(self):
        self.app.split = True
        self.app.big_terms = []
        self.app.render()
        top = ''.join(c[0] or ' ' for c in self.app.screen.cells[0])
        self.assertNotIn('Editor', top)

    def test_the_menus_stay_put_with_the_explorer_closed(self):
        before = list(self.app.menu_spans)
        self.app.show_tree = False
        self.app.render()
        self.assertEqual(self.app.menu_spans, before,
                         'the menus moved when the explorer closed')
        menu = self.open_menu('View')
        self.assertIsNotNone(menu, 'the menus stopped opening')
        row = ''.join(c[0] or ' ' for c in self.app.screen.cells[0])
        self.assertIn('Tide', row)
        for x1, x2, _name in self.app.menu_spans:
            for start, end, _view in self.app.toggle_spans:
                self.assertFalse(start < x2 and x1 < end,
                                 'a tab sits under a menu name')

    def test_every_menu_is_the_same_width(self):
        from tide.keys import Key
        widths = set()
        for name in ('Tide', 'File', 'View'):
            menu = self.open_menu(name)
            widths.add(menu.rect.w)
            self.app.handle_key(Key('escape'))
        self.assertEqual(len(widths), 1, 'the menus were %s wide' % sorted(widths))

    def test_one_click_moves_to_another_menu(self):
        self.open_menu('Tide')
        span = next(s for s in self.app.menu_spans if s[2] == 'View')
        self.press(span[0] + 1, 0)
        self.assertEqual(self.app.menu_open, 'View')
        self.assertEqual(self.app.overlay.name, 'View')

    def test_the_pointer_never_opens_another_menu(self):
        """Hover belongs inside the open menu; only a click moves along."""
        from tide.keys import Mouse
        self.open_menu('Tide')
        for name in ('View', 'Help', 'File'):
            span = next(s for s in self.app.menu_spans if s[2] == name)
            for kind in ('move', 'drag'):
                self.app.handle_mouse(Mouse(kind, span[0] + 1, 0))
                self.assertEqual(self.app.menu_open, 'Tide',
                                 '%s over %s opened it' % (kind, name))

    def test_a_storm_of_reports_costs_the_hover_not_the_session(self):
        from tide.keys import Mouse
        menu = self.open_menu('View')
        for i in range(600):
            self.app.handle_mouse(Mouse('move', menu.rect.x + 3,
                                        menu.rect.y + 1 + (i % 3)))
        self.assertFalse(self.app.hover, 'a storm was not noticed')
        self.assertIsNotNone(self.app.overlay, 'the menu was lost with it')
        self.assertIn('hover off', self.app.message)
        self.app.render()
        self.assertEqual(self.app.out.getvalue().rsplit('[?1003', 1)[-1][:1],
                         'l', 'the reports were not turned off')

    def test_the_file_menu_goes_to_a_document(self):
        self.app.open_file(os.path.join(self.tmp, 'sub', 'deep.py'))
        self.app.active = 0
        self.app.render()
        self.open_menu('File')
        self.pick('deep.py')
        self.assertEqual(self.app.editor.title, 'deep.py')
        self.assertIsNone(self.app.overlay)

    def test_file_offers_opening_and_going_to_a_line(self):
        items = self.app.menu_items('File')
        self.assertIn('Open File', items[0][0])
        self.assertIn('Go to line', items[1][0])
        self.assertIsNone(items[2], 'no separator above the documents')
        self.assertIsNotNone(items[1][2])

    def test_a_long_file_menu_stops_and_scrolls(self):
        from tide.keys import Mouse
        for i in range(30):
            path = os.path.join(self.tmp, 'many%02d.py' % i)
            with open(path, 'w') as f:
                f.write('x = 1\n')
            self.app.open_file(path)
        self.app.render()
        menu = self.open_menu('File')
        self.assertLess(menu.rect.h, self.app.screen.height * 0.85,
                        'the menu filled the screen')
        self.assertLess(menu.rect.h, len(menu.items) + 2, 'nothing was cut off')
        rows = menu.rect.h - 2
        thumb = [y for y in range(menu.rect.y, menu.rect.y + menu.rect.h)
                 if self.app.screen.cells[y][menu.rect.x2 - 1][0] == '\u2503']
        self.assertTrue(thumb, 'no scrollbar on a menu that does not fit')
        self.app.handle_mouse(Mouse('wheel_down', menu.rect.x + 3, menu.rect.y + 3))
        self.app.render()
        self.assertGreater(menu.top, 0, 'the wheel did not scroll it')
        self.assertTrue(menu.top <= menu.index < menu.top + rows,
                        'the highlight was left off screen')
        # a click still lands on the row it is over
        before = menu.top
        self.app.handle_mouse(Mouse('press', menu.rect.x + 3, menu.rect.y + 2))
        self.assertEqual(self.app.editor.title,
                         menu.items[before + 1][0].strip(' \u2713*'))

    def test_the_pointer_is_only_reported_while_a_menu_is_down(self):
        """Motion reports flood a slow link, so they are asked for narrowly."""
        import re
        from tide.keys import Key

        def state():
            found = re.findall(r'\[\?1003([hl])', self.app.out.getvalue())
            return found[-1] if found else 'l'
        self.assertEqual(state(), 'l', 'reports were asked for at rest')
        self.open_menu('View')
        self.assertEqual(state(), 'h', 'the menu cannot hear the pointer')
        self.app.handle_key(Key('escape'))
        self.assertEqual(state(), 'l', 'escape left the reports running')
        menu = self.open_menu('View')
        self.press(menu.rect.x + 3, menu.rect.y + 1)          # choose an item
        self.assertEqual(state(), 'l', 'choosing left the reports running')
        menu = self.open_menu('View')
        self.press(2, menu.rect.y2 + 2)                       # a click outside
        self.assertEqual(state(), 'l', 'clicking away left the reports running')

    def test_the_hover_setting_turns_the_reports_off(self):
        import re
        self.app.settings['menu_hover'] = False
        self.open_menu('View')
        self.assertNotIn('[?1003h', self.app.out.getvalue())
        self.assertIsNotNone(self.app.overlay, 'the menu stopped opening')

    def test_it_skips_the_separators(self):
        menu = self.open_menu('Tide')
        seen = set()
        for _ in range(6):
            seen.add(menu.index)
            menu.move(1)
        self.assertTrue(all(menu.items[i] is not None for i in seen),
                        'the keyboard landed on a separator')


class TestOpenFileBrowser(unittest.TestCase):
    """Open File...: a look around, ending in a file opened as any other."""

    def setUp(self):
        import io
        from tide.term import Screen
        self.project = tempfile.mkdtemp(prefix='tide-browse-')
        self.elsewhere = tempfile.mkdtemp(prefix='tide-outside-')
        os.makedirs(os.path.join(self.project, 'sub'))
        for path, text in ((('a.py',), 'inside = 1\n'),
                           (('sub', 'deep.py'), 'deep = 1\n')):
            with open(os.path.join(self.project, *path), 'w') as f:
                f.write(text)
        with open(os.path.join(self.elsewhere, 'far.py'), 'w') as f:
            f.write('far = 1\n')
        self.cfg = tempfile.mkdtemp(prefix='tide-browse-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.app = App(root=self.project, paths=[], out=io.StringIO())
        self.app.screen = Screen(100, 24)
        self.app.show_term = False
        self.app.render()

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        for folder in (self.project, self.elsewhere, self.cfg):
            shutil.rmtree(folder, ignore_errors=True)

    def browser(self):
        self.app.browse_files()
        self.app.render()
        return self.app.overlay

    def names(self, browser):
        return [name for name, _is_dir in browser.entries]

    def test_it_lists_folders_first_and_offers_the_way_up(self):
        b = self.browser()
        self.assertEqual(self.names(b)[:2], ['..', 'sub'])
        self.assertIn('a.py', self.names(b))

    def test_it_goes_in_and_out_of_folders(self):
        b = self.browser()
        b.index = self.names(b).index('sub')
        b.enter()
        self.assertIn('deep.py', self.names(b))
        b.index = 0                                  # ..
        b.enter()
        self.assertIn('a.py', self.names(b))

    def test_opening_a_file_closes_it_and_opens_the_file(self):
        b = self.browser()
        b.index = self.names(b).index('a.py')
        b.enter()
        self.assertIsNone(self.app.overlay)
        self.assertEqual(self.app.editors[self.app.active].title, 'a.py')

    def test_a_file_from_anywhere_behaves_like_any_other(self):
        b = self.browser()
        b.folder = self.elsewhere
        b.read()
        b.index = self.names(b).index('far.py')
        b.enter()
        editor = self.app.editors[self.app.active]
        self.assertEqual(editor.doc.text(), 'far = 1\n')
        # it is watched, saved and guarded exactly as anything else is
        editor.doc.cursor = (0, 0)
        editor.doc.insert('X')
        editor.doc.save()
        with open(os.path.join(self.elsewhere, 'far.py')) as f:
            self.assertEqual(f.read(), 'Xfar = 1\n')
        with open(os.path.join(self.elsewhere, 'far.py'), 'w') as f:
            f.write('changed underneath\n')
        self.app.check_disk_changes(force=True)
        self.assertEqual(editor.doc.text(), 'changed underneath\n',
                         'a file from outside is not being watched')

    def test_a_file_from_outside_the_project_is_named_in_italics(self):
        from tide.term import ITALIC
        b = self.browser()
        b.folder = self.elsewhere
        b.read()
        b.index = self.names(b).index('far.py')
        b.enter()
        self.app.open_file(os.path.join(self.project, 'a.py'))
        self.app.render()
        row = self.app.screen.cells[self.app.rects['tabs'].y]
        line = ''.join(c[0] or ' ' for c in row)
        self.assertTrue(row[line.index('far.py')][3] & ITALIC,
                        'a file from elsewhere should be in italics')
        self.assertFalse(row[line.index('a.py')][3] & ITALIC,
                         'a file in the project should not be')

    def test_escape_leaves_everything_alone(self):
        from tide.keys import Key
        before = len(self.app.editors)
        b = self.browser()
        b.on_key(Key('escape'))
        self.assertIsNone(self.app.overlay)
        self.assertEqual(len(self.app.editors), before)

    def test_a_folder_it_cannot_read_says_so(self):
        locked = os.path.join(self.project, 'locked')
        os.makedirs(locked)
        os.chmod(locked, 0o000)
        try:
            b = self.browser()
            b.folder = locked
            b.read()
            self.assertIn('cannot read', b.note)
            self.app.render()
        finally:
            os.chmod(locked, 0o755)


if __name__ == '__main__':
    unittest.main(verbosity=2)
