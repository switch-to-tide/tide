"""Panes you can resize and scroll: the divider, the tree, the sideways bar."""

import io
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import CTRL, Session
from tide.app import App, MIN_SIDEBAR_W, MIN_TERM_H
from tide import chrome, theme
from tide.term import Screen


class PaneTest(unittest.TestCase):
    """An app rendered into a screen we can read, with no pty in the way."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-panes-')
        self.cfg = tempfile.mkdtemp(prefix='tide-panes-cfg-')
        os.environ['TIDE_CONFIG_HOME'] = self.cfg

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfg, ignore_errors=True)

    def files(self, count):
        for i in range(count):
            with open(os.path.join(self.tmp, 'f%03d.txt' % i), 'w') as f:
                f.write('x\n')

    def app(self, cols=100, rows=24, paths=()):
        app = App(root=self.tmp, paths=list(paths), out=io.StringIO())
        app.screen = Screen(cols, rows)
        app.show_term = False              # keep the geometry easy to reason about
        app.render()
        return app

    def cell(self, app, x, y):
        return app.screen.cells[y][x]

    def column(self, app, x, y0, y1):
        return ''.join(app.screen.cells[y][x][0] or ' ' for y in range(y0, y1))

    def row(self, app, n, width=None):
        """The nth row of the explorer, as text."""
        side = app.rects['sidebar']
        cells = app.screen.cells[side.y + n]
        end = side.x2 if width is None else min(side.x + width, side.x2)
        return ''.join(c[0] or ' ' for c in cells[side.x:end]).rstrip()


class TestTreeScrolling(PaneTest):
    def test_the_scroll_stops_at_the_last_entry(self):
        self.files(60)
        app = self.app()
        tree = app.tree
        rows = tree.rows()
        self.assertEqual(tree.max_top(), 60 - rows)
        for _ in range(50):
            tree.scroll_to(tree.top + 3)   # keep going long past the end
        self.assertEqual(tree.top, tree.max_top(), 'scrolled past the end')
        app.render()
        last = self.row(app, app.rects['sidebar'].h - 1, 20)
        self.assertIn('f059.txt', last, 'the last file is not on the last row')

    def test_a_short_tree_does_not_scroll_at_all(self):
        self.files(3)
        app = self.app()
        self.assertEqual(app.tree.max_top(), 0)
        app.tree.scroll_to(10)
        self.assertEqual(app.tree.top, 0)
        self.assertFalse(app.tree.indicator_showing(), 'a bar with nothing to scroll')

    def test_the_indicator_appears_while_scrolling_and_then_fades(self):
        self.files(60)
        app = self.app()
        side = app.rects['sidebar']
        tree, edge = app.tree, side.x2 - 1
        quiet = self.column(app, edge, side.y + 1, side.y + 8)
        self.assertEqual(quiet.strip(), '', 'something is drawn down the edge')
        tree.scroll_to(tree.top + 10)
        app.render()
        thumbs = [y for y in range(side.y, side.y2)
                  if self.cell(app, edge, y)[2] == theme.SCROLL_THUMB]
        self.assertTrue(thumbs, 'no thumb while scrolling')
        tree.scrolled_at -= 5.0            # as if you had stopped a while ago
        self.assertFalse(tree.indicator_showing())
        app.render()
        gone = [y for y in range(side.y, side.y2)
                if self.cell(app, edge, y)[2] == theme.SCROLL_THUMB]
        self.assertEqual(gone, [], 'the thumb outstayed its welcome')

    def test_the_thumb_shrinks_as_the_tree_grows(self):
        self.files(40)
        app = self.app()
        app.tree.scroll_to(5)
        app.render()
        edge = app.rects['sidebar'].x2 - 1
        thumb = theme.SCROLL_THUMB
        side = app.rects['sidebar']
        short = sum(1 for y in range(side.y, side.y2)
                    if self.cell(app, edge, y)[2] == thumb)
        self.files(200)
        app.tree.refresh()
        app.tree.scroll_to(5)
        app.render()
        tall = sum(1 for y in range(side.y, side.y2)
                   if self.cell(app, edge, y)[2] == thumb)
        self.assertLess(tall, short, 'the thumb did not shrink for a longer tree')


class TestTreeShape(PaneTest):
    def setUp(self):
        PaneTest.setUp(self)
        os.makedirs(os.path.join(self.tmp, 'src', 'deep'))
        for rel, text in (('src/a.py', 'a\n'), ('src/deep/c.py', 'c\n')):
            with open(os.path.join(self.tmp, *rel.split('/')), 'w') as f:
                f.write(text)

    def test_folders_are_triangles_and_children_get_a_guide(self):
        app = self.app()
        self.assertIn('▸ src', self.row(app, 1, 20), 'closed folder')
        app.tree.expanded.add(os.path.join(self.tmp, 'src'))
        app.tree.refresh()
        app.render()
        self.assertIn('▾ src', self.row(app, 1, 20), 'open folder')
        self.assertIn('│▸ deep', self.row(app, 2, 20), 'guide beside a child')
        self.assertIn('│  a.py', self.row(app, 3, 20), 'guide beside a file')

    def test_a_guide_for_every_level(self):
        app = self.app()
        app.tree.expanded.add(os.path.join(self.tmp, 'src'))
        app.tree.expanded.add(os.path.join(self.tmp, 'src', 'deep'))
        app.tree.refresh()
        app.render()
        self.assertIn('││  c.py', self.row(app, 3, 20), 'two levels deep')


class TestDividers(PaneTest):
    def test_dragging_the_side_divider_resizes_the_explorer(self):
        self.files(5)
        app = self.app()
        edge = chrome.grab_column(app.rects)
        app.handle_mouse(_press(edge, 6))
        self.assertEqual(app.mouse_capture, 'vsplitter')
        app.handle_mouse(_drag(edge + 12, 6))
        app.render()
        self.assertEqual(app.sidebar_w, edge + 13,
                         'the explorer did not follow the drag')
        app.handle_mouse(_release(edge + 12, 6))
        self.assertIsNone(app.mouse_capture)

    def test_the_explorer_cannot_be_dragged_away_entirely(self):
        self.files(5)
        app = self.app()
        app.handle_mouse(_press(chrome.grab_column(app.rects), 6))
        app.handle_mouse(_drag(0, 6))
        app.render()
        self.assertEqual(app.sidebar_w, MIN_SIDEBAR_W)
        app.handle_mouse(_drag(99, 6))
        app.render()
        self.assertLessEqual(app.sidebar_w, 100 - 30,
                             'the editor was squeezed out')

    def test_clicking_the_divider_does_not_select_a_file(self):
        self.files(5)
        app = self.app()
        before = app.tree.index
        app.handle_mouse(_press(chrome.grab_column(app.rects), 3))
        self.assertEqual(app.tree.index, before)

    def test_dragging_the_terminal_divider_resizes_the_panel(self):
        self.files(3)
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(100, 30)
        app.show_term = True
        app.render()
        header = app.rects['terminal'].y
        before = app.rects['terminal'].h
        app.handle_mouse(_press(50, header))
        self.assertEqual(app.mouse_capture, 'splitter')
        app.handle_mouse(_drag(50, header - 5))
        app.render()
        self.assertEqual(app.rects['terminal'].h, before + 5,
                         'the panel did not follow the drag')
        app.handle_mouse(_drag(50, app.rects['status'].y + 4))   # past the bottom
        app.render()
        self.assertGreaterEqual(app.term_h, MIN_TERM_H)


class TestSidewaysScrolling(PaneTest):
    def open_wide(self, width=200, lines=60):
        path = os.path.join(self.tmp, 'wide.py')
        with open(path, 'w') as f:
            f.write('short = 1\nx = "%s"\n' % ('A' * width))
            f.write(''.join('y%d = %d\n' % (i, i) for i in range(lines)))
        return self.app(paths=[path])

    def test_the_scroll_stops_at_the_widest_line(self):
        app = self.open_wide()
        ed = app.editor
        cap = ed.max_left()
        self.assertGreater(cap, 0)
        for _ in range(200):
            ed.scroll_x(4)
        self.assertEqual(ed.left, cap, 'scrolled past the end of the longest line')
        # the widest line still reaches the right hand edge, and no further
        self.assertEqual(cap + ed.text_rect.w, ed.col_to_x(1, len(ed.doc.line(1))))

    def test_a_narrow_file_does_not_scroll_sideways_at_all(self):
        app = self.open_wide(width=3)
        ed = app.editor
        self.assertEqual(ed.max_left(), 0)
        ed.scroll_x(40)
        self.assertEqual(ed.left, 0)
        self.assertIsNone(ed.hbar())

    def test_the_cap_follows_an_edit(self):
        app = self.open_wide()
        ed = app.editor
        before = ed.max_left()
        ed.doc.cursor = (1, 0)
        ed.doc.insert('B' * 100)
        self.assertEqual(ed.max_left(), before + 100, 'the cap ignored the new text')

    def test_the_bar_appears_while_scrolling_and_then_fades(self):
        app = self.open_wide()
        ed = app.editor
        ed.scroll_x(20)
        app.render()
        y = ed.text_rect.y2 - 1
        thumb = theme.SCROLL_THUMB
        track = theme.SCROLL_TRACK
        row = [self.cell(app, x, y)[2] for x in range(ed.text_rect.x, ed.text_rect.x2)]
        self.assertIn(thumb, row, 'no thumb while scrolling sideways')
        self.assertIn(track, row, 'no track while scrolling sideways')
        ed.hscroll_at -= 5.0
        app.render()
        row = [self.cell(app, x, y)[2] for x in range(ed.text_rect.x, ed.text_rect.x2)]
        self.assertNotIn(thumb, row, 'the sideways bar outstayed its welcome')

    def test_the_text_stays_readable_under_the_bar(self):
        app = self.open_wide()
        ed = app.editor
        ed.scroll_x(4)
        app.render()
        y = ed.text_rect.y2 - 1
        drawn = ''.join(self.cell(app, x, y)[0] or ' '
                        for x in range(ed.text_rect.x, ed.text_rect.x2))
        self.assertIn('=', drawn, 'the bar painted over the line beneath it')

    def test_the_thumb_sits_where_the_view_is(self):
        app = self.open_wide()
        ed = app.editor
        ed.scroll_x(ed.max_left())
        app.render()
        y = ed.text_rect.y2 - 1
        thumb = theme.SCROLL_THUMB
        xs = [x for x in range(ed.text_rect.x, ed.text_rect.x2)
              if self.cell(app, x, y)[2] == thumb]
        self.assertTrue(xs)
        self.assertEqual(xs[-1], ed.text_rect.x2 - 1,
                         'scrolled to the end but the thumb is not at the end')


class TestSidewaysInASession(unittest.TestCase):
    """The same thing, through a pty, with real wheel events."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-hs-')
        self.path = os.path.join(self.tmp, 'wide.py')
        with open(self.path, 'w') as f:
            f.write('short = 1\nx = "%s"\ny = 2\n' % ('A' * 200))
        self.s = Session([self.path, self.tmp], cols=100, rows=24, cwd=self.tmp)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def line(self, y):
        return ''.join(c[0] or ' ' for c in self.s.vt.grid[y])

    def test_the_wheel_cannot_scroll_past_the_text(self):
        for _ in range(60):
            self.s.hwheel(60, 4, right=True, times=1)
        self.s.pump(0.4)
        far = self.line(self.s.BODY_ROW + 1)     # the long line is the second
        for _ in range(20):
            self.s.hwheel(60, 4, right=True, times=1)
        self.s.pump(0.4)
        self.assertEqual(self.line(self.s.BODY_ROW + 1), far,
                         'kept scrolling into empty space')
        self.assertIn('A', far, 'scrolled somewhere with no text at all')


def _mouse(kind, x, y):
    from tide.keys import Mouse
    return Mouse(kind, x, y)


def _press(x, y):
    return _mouse('press', x, y)


def _drag(x, y):
    return _mouse('drag', x, y)


def _release(x, y):
    return _mouse('release', x, y)


class TestSizesAreRemembered(PaneTest):
    """What you drag the panes to is where they are next time."""

    def app_with_terminal(self, cols=100, rows=30):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(cols, rows)
        app.show_term = True
        app.render()
        return app

    def test_the_side_panel_width_survives_a_restart(self):
        from tide import settings as store
        self.files(4)
        app = self.app()
        edge = chrome.grab_column(app.rects)
        app.handle_mouse(_press(edge, 6))
        app.handle_mouse(_drag(edge + 8, 6))
        app.handle_mouse(_release(edge + 8, 6))
        app.render()
        width = app.rects['sidebar'].w
        self.assertEqual(store.load()['sidebar_width'], app.sidebar_w)
        again = self.app()
        self.assertEqual(again.rects['sidebar'].w, width,
                         'it forgot how wide the explorer was')

    def test_the_terminal_height_survives_a_restart(self):
        from tide import settings as store
        self.files(3)
        app = self.app_with_terminal()
        row = app.rects['terminal'].y
        app.handle_mouse(_press(50, row))
        app.handle_mouse(_drag(50, row - 4))
        app.handle_mouse(_release(50, row - 4))
        app.render()
        height = app.rects['terminal'].h
        self.assertEqual(store.load()['terminal_height'], app.term_h)
        again = self.app_with_terminal()
        self.assertEqual(again.rects['terminal'].h, height,
                         'it forgot how tall the terminal was')

    def test_dragging_writes_it_down_once_and_only_when_it_moves(self):
        from tide import settings as store
        self.files(3)
        app = self.app()
        edge = chrome.grab_column(app.rects)
        app.handle_mouse(_press(edge, 6))
        app.handle_mouse(_drag(edge + 5, 6))
        app.handle_mouse(_release(edge + 5, 6))
        first = store.load()['sidebar_width']
        path = store.config_path()
        self.assertTrue(os.path.exists(path), 'the drag was never written down')
        before = os.path.getmtime(path)
        time.sleep(0.05)
        app.handle_mouse(_press(chrome.grab_column(app.rects), 6))
        app.handle_mouse(_release(chrome.grab_column(app.rects), 6))
        self.assertEqual(store.load()['sidebar_width'], first)
        self.assertEqual(os.path.getmtime(path), before,
                         'it wrote the settings again for nothing')

    def test_a_nonsense_width_in_the_file_is_ignored(self):
        from tide import settings as store
        folder = os.path.dirname(store.config_path())
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(store.config_path(), 'w') as f:
            f.write('{"sidebar_width": 2, "terminal_height": -9}')
        app = self.app()
        self.assertGreaterEqual(app.sidebar_w, MIN_SIDEBAR_W)
        self.assertGreater(app.rects['editor'].w, 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
