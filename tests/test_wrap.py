"""Long lines: wrapped onto the next row, or scrolled sideways."""

import io
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tide import wrap                                          # noqa: E402
from tide.app import App                                       # noqa: E402
from tide.keys import Mouse                                    # noqa: E402
from tide.term import Screen                                   # noqa: E402

LONG = ('The quick brown fox jumps over the lazy dog and keeps on running '
        'well past the edge of any pane you care to give it.')


class TestBreakingALine(unittest.TestCase):
    def segs(self, line, width):
        xs = list(range(len(line) + 1))       # no tabs: one column each
        return [line[a:b] for a, b in wrap.segments(line, width, xs)]

    def test_it_breaks_at_spaces_and_keeps_every_character(self):
        pieces = self.segs(LONG, 20)
        self.assertEqual(''.join(pieces), LONG)
        self.assertTrue(all(len(p) <= 20 for p in pieces), pieces)
        self.assertTrue(all(not p.startswith(' ') for p in pieces[1:]), pieces)

    def test_a_word_longer_than_the_pane_is_broken_anyway(self):
        pieces = self.segs('x' * 25, 10)
        self.assertEqual(pieces, ['x' * 10, 'x' * 10, 'x' * 5])

    def test_which_files_wrap(self):
        self.assertTrue(wrap.wraps('smart', 'notes.md'))
        self.assertTrue(wrap.wraps('smart', 'README'))
        self.assertFalse(wrap.wraps('smart', 'app.py'))
        self.assertTrue(wrap.wraps('on', 'app.py'))
        self.assertFalse(wrap.wraps('off', 'notes.md'))


class TestInTheEditor(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, 'notes.md'), 'w') as f:
            f.write(LONG + '\nshort\n')
        with open(os.path.join(self.tmp, 'code.py'), 'w') as f:
            f.write('x = "' + 'y' * 200 + '"\n')

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open(self, name, mode='smart'):
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(80, 20)
        app.settings['wrap'] = mode
        app.show_term = False
        app.show_tree = False
        app.open_file(os.path.join(self.tmp, name))
        app.render()
        return app

    def rows(self, app):
        """What the editor pane itself is showing, gutter included."""
        ed = app.editor
        r = ed.text_rect
        return [''.join(c[0] or ' ' for c in app.screen.cells[y][ed.rect.x:r.x2])
                for y in range(r.y, r.y2)]

    def test_code_scrolls_and_prose_wraps(self):
        self.assertFalse(self.open('code.py').editor.wrapping())
        self.assertTrue(self.open('notes.md').editor.wrapping())

    def test_the_setting_overrules_the_filename(self):
        self.assertTrue(self.open('code.py', 'on').editor.wrapping())
        self.assertFalse(self.open('notes.md', 'off').editor.wrapping())

    def test_a_wrapped_line_carries_on_without_a_number(self):
        app = self.open('notes.md')
        rows = self.rows(app)
        self.assertIn('1 The quick', rows[0])
        self.assertNotIn('2', rows[1][:6], 'the carried-on row was numbered')
        self.assertTrue(rows[1].strip(), 'nothing carried on')

    def test_a_blank_row_shows_where_the_line_really_ends(self):
        app = self.open('notes.md')
        rows = [row.strip() for row in self.rows(app)]
        wrapped = app.editor.vrows(0)
        self.assertGreater(wrapped, 2)
        self.assertEqual(rows[wrapped - 1], '', 'no breather after the wrap')
        self.assertIn('short', rows[wrapped])

    def test_nothing_runs_off_the_side_while_wrapping(self):
        app = self.open('notes.md')
        self.assertEqual(app.editor.max_left(), 0)
        self.assertIsNone(app.editor.hbar())

    def test_clicking_a_carried_on_row_lands_in_that_line(self):
        app = self.open('notes.md')
        ed = app.editor
        r = ed.text_rect
        app.handle_mouse(Mouse('press', r.x + 6, r.y + 1))
        row, col = ed.doc.cursor
        self.assertEqual(row, 0)
        start = ed.segments(0)[1][0]
        self.assertEqual(col, start + 6)
        self.assertEqual(ed.cursor_screen_pos(), (r.x + 6, r.y + 1))

    def test_the_end_of_a_long_line_is_on_screen(self):
        from tide.keys import Key
        app = self.open('notes.md')
        ed = app.editor
        app.handle_key(Key('end'))
        app.render()
        self.assertEqual(ed.doc.cursor[1], len(LONG))
        self.assertIsNotNone(ed.cursor_screen_pos(),
                             'the cursor left the screen at the end of a line')


if __name__ == '__main__':
    unittest.main()
