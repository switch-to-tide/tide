"""Split view: one file editor and one full-size terminal, side by side."""

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

from harness import CTRL, ENTER, ESC, F2, Session
from tide import settings
from tide.app import App

F5 = ESC + '[15~'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', repo] + list(args),
                                   stderr=subprocess.DEVNULL).decode()


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-split-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp(prefix='tide-split-')
        self.paths = []
        for name in ('a.py', 'b.py'):
            path = os.path.join(self.tmp, name)
            with open(path, 'w') as f:
                f.write(''.join('%s line %d\n' % (name[0], i) for i in range(200)))
            self.paths.append(path)
        self.app = App(root=self.tmp, paths=self.paths, out=io.StringIO())
        self.app.screen.resize(120, 30)

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestLayout(SplitTest):
    def test_off_by_default_and_needs_a_terminal(self):
        self.assertFalse(self.app.split_active(120))
        rects = self.app.layout()
        self.assertIsNone(rects['split'])

    def test_turning_it_on_with_no_terminal_leaves_the_editor_whole(self):
        self.app.toggle_split()
        self.assertTrue(self.app.split)
        self.assertEqual(self.app.big_terms, [], 'a terminal appeared uninvited')
        rects = self.app.layout()
        self.assertIsNone(rects['split'])
        self.assertGreaterEqual(rects['editor'].w, 120 - 26 - 4,
                                'the editor did not fill the pane')
        self.assertIsNone(rects['split'], 'there is nothing to split with')

    def test_a_terminal_turns_it_into_two_halves(self):
        self.app.toggle_split()
        self.app.new_big_terminal()
        rects = self.app.layout()
        left, right = rects['editor'], rects['split']
        self.assertIsNotNone(right)
        self.assertEqual(left.y, right.y)
        self.assertEqual(left.h, right.h)
        # the two halves are kept apart: in boxes by their borders, flush by
        # the divider column between them
        self.assertLessEqual(left.x2, rects['divider'])
        self.assertLess(rects['divider'], right.x)
        self.assertLess(abs(left.w - right.w), 2, 'the halves are lopsided')

    def test_closing_the_last_terminal_gives_the_space_back(self):
        self.app.toggle_split()
        self.app.new_big_terminal()
        self.assertIsNotNone(self.app.layout()['split'])
        self.app.close_big_terminal(0)
        self.assertTrue(self.app.split, 'split view switched itself off')
        self.assertIsNone(self.app.layout()['split'])
        self.assertGreaterEqual(self.app.layout()['editor'].w, 120 - 26 - 4,
                                'the editor did not take the space back')

    def test_the_bottom_panel_is_untouched(self):
        self.app.toggle_split()
        self.app.new_big_terminal()
        rects = self.app.layout()
        self.assertIsNotNone(rects['terminal'])
        self.assertGreater(rects['terminal'].y, rects['editor'].y2 - 1,
                           'the panels overlap')
        self.assertGreaterEqual(rects['terminal'].w,
                                rects['editor'].w + rects['split'].w - 2,
                                'the bottom panel lost width to the split')

    def test_a_narrow_window_stays_single(self):
        self.app.toggle_split()
        self.app.new_big_terminal()
        self.assertFalse(self.app.split_active(40))
        self.app.screen.resize(50, 20)
        self.assertIsNone(self.app.layout()['split'])

    def test_it_is_remembered_for_next_time(self):
        self.app.toggle_split()
        self.assertTrue(settings.load(settings.config_path())['split_view'])
        again = App(root=self.tmp, paths=self.paths, out=io.StringIO())
        self.assertTrue(again.split)


class TestTabIdentity(SplitTest):
    def test_every_tab_has_its_own_id(self):
        self.app.new_big_terminal()
        ids = [t.tab_id for t in self.app.editors + self.app.big_terms]
        self.assertEqual(len(ids), len(set(ids)), 'ids are not unique')
        self.assertTrue(all(ids))

    def test_ids_and_order_survive_toggling(self):
        self.app.new_big_terminal()
        before = [t.tab_id for t in self.app.editors]
        terms = [t.tab_id for t in self.app.big_terms]
        active, big_active = self.app.active, self.app.big_active
        self.app.toggle_split()
        self.app.toggle_split()
        self.assertEqual([t.tab_id for t in self.app.editors], before)
        self.assertEqual([t.tab_id for t in self.app.big_terms], terms)
        self.assertEqual((self.app.active, self.app.big_active), (active, big_active))

    def test_a_rebuilt_diff_keeps_its_id(self):
        ed = self.app.editors[0]
        first = self.app.open_conflict_diff(ed)
        first_id = first.tab_id
        second = self.app.open_conflict_diff(ed)
        self.assertEqual(second.tab_id, first_id)
        self.assertEqual(len(self.app.editors), 3)

    def test_new_tabs_do_not_reuse_an_id(self):
        seen = set(t.tab_id for t in self.app.editors)
        self.app.new_file()
        self.app.new_big_terminal()
        for tab in self.app.editors + self.app.big_terms:
            if tab.tab_id in seen:
                continue
            seen.add(tab.tab_id)
        self.assertEqual(len(seen), len(self.app.editors) + len(self.app.big_terms))


class TestViewportMemory(SplitTest):
    def setUp(self):
        SplitTest.setUp(self)
        self.term = self.app.new_big_terminal()
        self.ed = self.app.editors[0]
        self.diff = self.app.open_conflict_diff(self.ed)

    def test_editors_diffs_and_terminals_are_all_put_back(self):
        self.ed.top, self.ed.left = 42, 15
        self.diff.top, self.diff.cols['right'], self.diff.side = 7, 12, 'right'
        self.term.vt.scrollback = [[] for _ in range(50)]
        self.term.scroll = 20
        self.app.toggle_split()                       # into split
        self.ed.top, self.ed.left = 0, 0              # look elsewhere there
        self.diff.top, self.diff.cols['right'] = 0, 0
        self.term.scroll = 0
        self.app.toggle_split()                       # and back
        self.assertEqual((self.ed.top, self.ed.left), (42, 15))
        self.assertEqual((self.diff.top, self.diff.cols['right']), (7, 12))
        self.assertEqual(self.diff.side, 'right')
        self.assertEqual(self.term.scroll, 20)

    def test_each_view_remembers_its_own_position(self):
        self.ed.top = 10
        self.app.toggle_split()
        self.ed.top = 99
        self.app.toggle_split()
        self.assertEqual(self.ed.top, 10, 'single view lost its place')
        self.app.toggle_split()
        self.assertEqual(self.ed.top, 99, 'split view lost its place')

    def test_a_terminal_offset_is_clamped_to_what_exists(self):
        self.term.scroll = 5
        self.app.toggle_split()
        self.term.vt.scrollback = []
        self.app.toggle_split()
        self.assertEqual(self.term.scroll, 0)

    def test_diff_tabs_belong_to_the_editor_half(self):
        self.app.toggle_split()
        self.assertTrue(self.app.editor.is_diff)
        rects = self.app.layout()
        self.assertIsNotNone(rects['split'])
        self.assertIn(self.diff, self.app.editors)
        self.assertNotIn(self.diff, self.app.big_terms)


class TestSplitInTheUI(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-split-ui-cfg-')
        self.tmp = tempfile.mkdtemp(prefix='tide-split-ui-')
        self.path = os.path.join(self.tmp, 'code.py')
        with open(self.path, 'w') as f:
            f.write(''.join('row %d\n' % i for i in range(120)))
        self.s = Session(['code.py', self.tmp], cols=110, rows=24, cwd=self.tmp,
                         env={'TIDE_CONFIG_HOME': self.cfg})
        self.s.pump(0.9)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def right_half_is_a_terminal(self, row=None):
        """The shell's background colour gives the right half away."""
        from tide import theme
        theme.apply('dark', 'modern')
        row = self.s.BODY_ROW if row is None else row
        return self.s.cell(self.s.cols - 20, row)[2] == theme.TERM_BG

    def halves(self, row=None):
        line = self.s.line(self.s.BODY_ROW + 1 if row is None else row)
        middle = self.app_divider()
        return line[26:middle].rstrip(), line[middle:].rstrip()

    def tabs(self):
        """The tab strip alone, past the explorer column."""
        return self.s.line(self.s.TAB_ROW)[26:].strip('│ ')

    def app_divider(self):
        """The column between the two halves: the gap where they meet."""
        row = self.s.line(self.s.TAB_ROW)
        join = row.find('│ │', 26)
        if join >= 0:
            return join + 1
        return row.index('|', 26)

    def new_terminal_button(self):
        line = self.s.line(0)
        return line.index('</>') if '</>' in line else None

    def test_f5_offers_a_shell_and_then_splits(self):
        self.assertIsNone(self.new_terminal_button(), 'button shown in single view')
        self.s.key(F5)
        self.s.pump(0.8)
        self.assertIsNotNone(self.new_terminal_button(),
                             'no </> button with nothing to split')
        self.assertFalse(self.right_half_is_a_terminal())
        self.assertIn('row 0', self.s.screen())
        self.s.click(self.new_terminal_button() + 1, 0)
        self.s.pump(1.4)
        self.assertTrue(self.right_half_is_a_terminal(), 'no terminal on the right')
        self.assertIsNone(self.new_terminal_button(), 'the button should go away')
        self.assertIn('row 0', self.s.screen(), 'the file half was lost')

    def test_closing_the_last_terminal_brings_the_button_back(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.click(self.new_terminal_button() + 1, 0)
        self.s.pump(1.4)
        self.assertTrue(self.right_half_is_a_terminal())
        self.s.type('exit' + ENTER)
        self.s.pump(1.4)
        self.assertFalse(self.right_half_is_a_terminal(),
                         'the editor did not take the space back')
        self.assertIsNotNone(self.new_terminal_button())

    def test_leaving_split_view_hides_the_button(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.assertIsNotNone(self.new_terminal_button())
        self.s.key(F5)
        self.s.pump(0.6)
        self.assertIsNone(self.new_terminal_button())
        self.assertIn('Split view off', self.s.screen())

    def test_the_shell_on_the_right_really_works(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')                    # f4 makes the terminal
        self.s.pump(1.2)
        self.s.key(F2)                            # focus the terminal half
        self.s.type('echo FROM_THE_SPLIT' + ENTER)
        self.assertTrue(self.s.wait_for('FROM_THE_SPLIT'))
        self.assertIn('row 0', self.s.screen(), 'the file half was lost')

    def test_the_settings_panel_toggles_it(self):
        top = self.s.line(0)[26:]          # past the explorer's own heading
        self.assertEqual(top.count('split'), 1, 'the top bar grew a split button')
        self.assertIn('f5 split', top, 'the keyboard hint is gone')
        self.s.key(ESC + '[20~')                  # f9, settings
        self.s.pump(0.5)
        for y, line in enumerate(self.s.text()):
            if 'Split view' in line:           # the panel is centred, so search
                self.s.click(self.s.cols // 2 + 8, y)
                break
        else:
            self.fail('no Split view row in the settings panel')
        self.s.key(ESC)
        self.s.pump(0.8)
        self.assertIn('</>', self.s.line(0), 'no offer of a terminal to split with')
        self.s.click(self.s.line(0).index('</>') + 1, 0)
        self.s.pump(1.4)
        self.assertTrue(self.right_half_is_a_terminal())

    def test_each_half_takes_the_keyboard_when_clicked(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')
        self.s.pump(1.2)
        self.s.click(90, 6)                       # the shell on the right
        self.s.type('echo FROM_THE_RIGHT' + ENTER)
        self.assertTrue(self.s.wait_for('FROM_THE_RIGHT'))
        self.s.click(40, 4)                       # the file on the left
        self.s.type('TYPED ')
        self.s.pump(0.6)
        self.assertIn('TYPED ', self.s.line(4), 'typing did not reach the file')

    def test_both_sets_of_tabs_are_on_screen(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')                    # f4: a shell on the right
        self.s.pump(1.2)
        row = self.tabs()
        self.assertIn('code.py', row, 'the file tabs are missing')
        self.assertIn('sh', row, 'the terminal tabs are missing')
        self.assertLess(row.index('code.py'), row.index('sh'),
                        'the two strips are the wrong way round')
        top = self.s.line(0)[26:]
        self.assertNotIn('Editor', top, 'the switch is still there in split view')
        self.assertNotIn('Terminals', top)

    def test_the_halves_are_kept_apart_all_the_way_down(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')
        self.s.pump(1.2)
        column = self.app_divider()
        rows = [self.s.cell(column, y)[0] for y in
                range(self.s.TAB_ROW, self.s.TAB_ROW + 6)]
        self.assertTrue(all(ch in ('|', '│', ' ', '─', '╭', '╰') for ch in rows),
                        'text is running through the join: %r' % rows)

    def test_clicking_either_strip_moves_the_keyboard(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')
        self.s.pump(1.2)
        column = self.s.line(self.s.TAB_ROW).index('code.py')
        self.s.click(column + 1, self.s.TAB_ROW)
        self.s.pump(0.4)
        self.s.type('TYPED ')
        self.s.pump(0.4)
        self.assertIn('TYPED ', self.s.screen(), 'the file half did not take it')
        column = 26 + self.tabs().index('sh')
        self.s.click(column + 2, self.s.TAB_ROW)
        self.s.pump(0.4)
        self.s.type('echo FROM_THE_TAB' + ENTER)
        self.assertTrue(self.s.wait_for('FROM_THE_TAB'),
                        'the shell half did not take it')

    def test_each_strip_scrolls_inside_its_own_half(self):
        names = ('one_long_name.py', 'two_long_name.py', 'three_long_name.py',
                 'four_long_name.py', 'five_long_name.py')
        for name in names:
            with open(os.path.join(self.tmp, name), 'w') as f:
                f.write('x = 1\n')
        time.sleep(2.2)                     # let quick open notice them
        self.s.pump(0.5)
        for name in names:
            self.s.key(CTRL('p'))
            self.s.type(name.split('_')[0])
            self.s.key(ENTER)
            self.s.pump(0.4)
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')
        self.s.pump(1.2)
        row = self.s.line(self.s.TAB_ROW)
        column = self.app_divider()
        right_before = row[column:]
        self.s.wheel(column - 10, self.s.TAB_ROW, up=False, times=3)
        self.s.pump(0.4)
        after = self.s.line(self.s.TAB_ROW)
        self.assertNotEqual(after[26:column], row[26:column], 'the left strip is stuck')
        self.assertEqual(after[column:], right_before, 'the right strip moved too')

    def test_f2_moves_between_the_halves_without_changing_the_layout(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.key(ESC + 'OS')                    # f4: the new shell takes focus
        self.s.pump(1.2)
        self.assertIn('sh', self.tabs())
        self.assertIn('Terminal 1/1', self.s.screen())
        self.assertIn('row 0', self.s.screen(), 'the file half disappeared')
        self.s.key(F2)                            # back to the file half
        self.s.pump(0.4)
        self.assertIn('code.py', self.tabs())
        self.assertIn('Ln ', self.s.screen())
        self.assertTrue(self.right_half_is_a_terminal(), 'the layout changed')
        self.s.key(F2)
        self.s.pump(0.4)
        self.assertIn('sh', self.tabs())
        self.assertTrue(self.right_half_is_a_terminal())

    def test_the_file_keeps_its_place_across_a_toggle(self):
        self.s.key(F5)
        self.s.pump(0.5)
        self.s.key(ESC + 'OS')                    # a terminal, so it really splits
        self.s.pump(1.2)
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.wheel(50, 6, up=False, times=6)
        before = self.s.line(3)[26:50].strip()
        self.s.key(F5)
        self.s.pump(1.0)
        self.s.key(F5)
        self.s.pump(0.8)
        self.assertEqual(self.s.line(3)[26:50].strip(), before,
                         'the file scrolled away over the toggle')

    def test_it_is_still_split_after_a_restart(self):
        self.s.key(F5)
        self.s.pump(0.6)
        self.s.click(self.s.line(0).index('</>') + 1, 0)
        self.s.pump(1.2)
        self.s.close()
        self.s = Session(['code.py', self.tmp], cols=110, rows=24, cwd=self.tmp,
                         env={'TIDE_CONFIG_HOME': self.cfg})
        self.s.pump(1.4)
        # the layout is remembered; a fresh session starts without a shell and
        # offers one, rather than forking something you did not ask for
        self.assertIn('</>', self.s.line(0), 'split view was not remembered')
        self.assertIn('row 0', self.s.screen())


if __name__ == '__main__':
    unittest.main(verbosity=2)
