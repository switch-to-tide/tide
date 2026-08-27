"""Unit tests for the editing core (no terminal needed)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tide.buffer import Document
from tide.editor import Editor
from tide.highlight import Highlighter
from tide.keys import Decoder, Key, Mouse, Paste
from tide.shell import key_to_bytes
from tide.term import Rect, Screen, text_width
from tide.vt import VT


class FakeApp(object):
    def __init__(self):
        self.messages = []

    def status(self, msg):
        self.messages.append(msg)


def mk_editor(text, path='t.py'):
    ed = Editor(FakeApp(), Document(text=text))
    ed.hl = Highlighter.for_path(path)
    ed.states.hl = ed.hl
    ed.text_rect = Rect(0, 0, 80, 20)
    return ed


class TestDocument(unittest.TestCase):
    def test_insert_and_undo(self):
        d = Document(text='hello world')
        d.cursor = (0, 5)
        d.insert(',', coalesce=True)
        d.insert('!', coalesce=True)
        self.assertEqual(d.text(), 'hello,! world')
        self.assertEqual(len(d.undo_stack), 1)  # typing coalesces
        d.undo()
        self.assertEqual(d.text(), 'hello world')
        d.redo()
        self.assertEqual(d.text(), 'hello,! world')

    def test_selection_replace(self):
        d = Document(text='one\ntwo\nthree')
        d.anchor = (0, 1)
        d.cursor = (2, 2)
        self.assertEqual(d.selected_text(), 'ne\ntwo\nth')
        d.insert('X')
        self.assertEqual(d.text(), 'oXree')

    def test_multiline_delete_and_undo(self):
        d = Document(text='a\nb\nc\nd')
        d.delete_range((1, 0), (3, 0))
        self.assertEqual(d.lines, ['a', 'd'])
        d.undo()
        self.assertEqual(d.lines, ['a', 'b', 'c', 'd'])

    def test_word_navigation(self):
        d = Document(text='foo bar_baz  qux()')
        self.assertEqual(d.word_right((0, 0)), (0, 4))
        self.assertEqual(d.word_left((0, 4)), (0, 0))
        self.assertEqual(d.word_at((0, 5)), ((0, 4), (0, 11)))

    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'x.txt')
            d = Document(text='line1\nline2')
            d.save(p)
            self.assertEqual(open(p).read(), 'line1\nline2')
            self.assertFalse(d.dirty)
            d2 = Document(p)
            self.assertEqual(d2.lines, ['line1', 'line2'])

    def test_find_all(self):
        d = Document(text='ab AB ab')
        self.assertEqual(len(d.find_all('ab')), 3)
        self.assertEqual(len(d.find_all('ab', ignore_case=False)), 2)


class TestEditor(unittest.TestCase):
    def test_indent_and_dedent_selection(self):
        ed = mk_editor('a\nb\nc')
        ed.doc.anchor = (0, 0)
        ed.doc.cursor = (2, 1)
        ed.indent_selection()
        self.assertEqual(ed.doc.lines, ['    a', '    b', '    c'])
        ed.indent_selection(dedent=True)
        self.assertEqual(ed.doc.lines, ['a', 'b', 'c'])

    def test_toggle_comment(self):
        ed = mk_editor('x = 1\ny = 2')
        ed.doc.anchor = (0, 0)
        ed.doc.cursor = (1, 1)
        ed.toggle_comment()
        self.assertEqual(ed.doc.lines, ['# x = 1', '# y = 2'])
        ed.toggle_comment()
        self.assertEqual(ed.doc.lines, ['x = 1', 'y = 2'])

    def test_move_and_duplicate_lines(self):
        ed = mk_editor('a\nb\nc')
        ed.doc.cursor = (2, 0)
        ed.move_lines(-1)
        self.assertEqual(ed.doc.lines, ['a', 'c', 'b'])
        ed.doc.undo()
        self.assertEqual(ed.doc.lines, ['a', 'b', 'c'])
        ed.doc.cursor = (0, 0)
        ed.duplicate()
        self.assertEqual(ed.doc.lines, ['a', 'a', 'b', 'c'])

    def test_delete_lines(self):
        ed = mk_editor('a\nb\nc')
        ed.doc.cursor = (1, 0)
        ed.delete_lines()
        self.assertEqual(ed.doc.lines, ['a', 'c'])

    def test_autoindent_newline(self):
        ed = mk_editor('def f():\n    pass')
        ed.doc.cursor = (0, 8)
        ed.newline()
        self.assertEqual(ed.doc.lines[1], '    ')
        self.assertEqual(ed.doc.cursor, (1, 4))

    def test_backspace_removes_indent_unit(self):
        ed = mk_editor('        x')
        ed.tab_width = 4
        ed.doc.cursor = (0, 8)
        ed.backspace()
        self.assertEqual(ed.doc.lines, ['    x'])

    def test_tabs_display_columns(self):
        ed = mk_editor('\tab', path='t.go')
        ed.tab_width = 4
        self.assertEqual(ed.col_to_x(0, 1), 4)
        self.assertEqual(ed.x_to_col(0, 5), 2)

    def test_scrollbar_absent_when_everything_fits(self):
        ed = mk_editor('\n'.join('row %d' % i for i in range(5)))
        ed.text_rect = Rect(0, 0, 40, 20)
        self.assertIsNone(ed.scrollbar())

    def test_scrollbar_thumb_shrinks_as_the_document_grows(self):
        sizes = []
        for count in (30, 100, 1000):
            ed = mk_editor('\n'.join('row %d' % i for i in range(count)))
            ed.text_rect = Rect(0, 0, 40, 10)
            sizes.append(ed.scrollbar()[0])
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertGreater(sizes[0], sizes[-1])
        self.assertGreaterEqual(sizes[-1], 1)

    def test_scrollbar_offset_tracks_the_viewport(self):
        ed = mk_editor('\n'.join('row %d' % i for i in range(100)))
        ed.text_rect = Rect(0, 0, 40, 10)
        thumb, offset = ed.scrollbar()
        self.assertEqual(offset, 0)
        ed.top = ed.max_top()
        _thumb, offset = ed.scrollbar()
        self.assertEqual(offset, 10 - thumb, 'thumb should sit at the bottom')
        ed.top = ed.max_top() // 2
        _thumb, offset = ed.scrollbar()
        self.assertTrue(0 < offset < 10 - thumb)

    def test_scrolling_stops_at_the_last_screenful(self):
        ed = mk_editor('\n'.join('row %d' % i for i in range(50)))
        ed.text_rect = Rect(0, 0, 40, 10)
        ed.scroll(1000)
        self.assertEqual(ed.top, ed.max_top())
        self.assertEqual(ed.top, 50 - 10)      # 50 lines, a 10 row viewport
        ed.scroll(-1000)
        self.assertEqual(ed.top, 0)

    def test_dragging_the_thumb_maps_to_the_document(self):
        ed = mk_editor('\n'.join('row %d' % i for i in range(100)))
        ed.text_rect = Rect(0, 0, 40, 10)
        ed.sb_press(0)                      # grab at the very top
        ed.sb_drag_to(9)                    # drag to the last row
        self.assertEqual(ed.top, ed.max_top())
        ed.sb_drag_to(0)
        self.assertEqual(ed.top, 0)

    def test_find_next_wraps(self):
        ed = mk_editor('foo\nbar\nfoo')
        ed.set_find('foo')
        self.assertEqual(len(ed.find_matches), 2)
        ed.doc.cursor = (2, 3)
        ed.find_next()
        self.assertEqual(ed.doc.cursor, (0, 3))


class TestAutoSave(unittest.TestCase):
    def _app(self, tmp, name='a.txt', text='one\n'):
        import io
        from tide.app import App
        path = os.path.join(tmp, name)
        with open(path, 'w') as f:
            f.write(text)
        app = App(root=tmp, paths=[path], out=io.StringIO())
        app.autosave_delay = 0.0
        return app, path

    def test_writes_an_edited_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, path = self._app(tmp)
            app.editor.doc.cursor = (0, 3)
            app.editor.insert_text(' more')
            self.assertTrue(app.editor.doc.dirty)
            app.autosave_tick()
            self.assertFalse(app.editor.doc.dirty)
            self.assertEqual(open(path).read(), 'one more\n')

    def test_keeps_up_with_continued_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, path = self._app(tmp)
            app.editor.doc.cursor = (0, 3)
            app.editor.insert_text('X', coalesce=True)
            app.autosave_tick()
            app.editor.insert_text('Y', coalesce=True)
            app.autosave_tick()
            self.assertEqual(open(path).read(), 'oneXY\n')

    def test_respects_the_delay(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, path = self._app(tmp)
            app.autosave_delay = 30.0
            app.editor.insert_text('Z')
            app.autosave_tick()
            self.assertEqual(open(path).read(), 'one\n')
            self.assertTrue(app.editor.doc.dirty)

    def test_untitled_buffers_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _path = self._app(tmp)
            app.new_file()
            app.editor.insert_text('scratch')
            app.autosave_tick()
            self.assertTrue(app.editor.doc.dirty)   # nowhere to write it yet

    def test_a_failure_is_reported_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, path = self._app(tmp)
            app.editor.doc.path = os.path.join(tmp, 'no-such-dir', 'x.txt')
            app.editor.insert_text('Q')
            app.autosave_tick()
            self.assertTrue(app.editor.doc.autosave_blocked)
            self.assertIn('Auto-save failed', app.message)
            app.message = ''
            app.editor.insert_text('R')
            app.autosave_tick()
            self.assertEqual(app.message, '')       # no repeat every keystroke

    def test_toggle_off_stops_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, path = self._app(tmp)
            app.toggle_autosave()
            self.assertFalse(app.autosave)
            app.editor.insert_text('nope')
            app.autosave_tick()
            self.assertEqual(open(path).read(), 'one\n')
            app.toggle_autosave()                   # turning it back on flushes
            self.assertEqual(open(path).read(), 'nopeone\n')


class TestHighlight(unittest.TestCase):
    def test_python_tokens(self):
        h = Highlighter.for_path('a.py')
        spans, state = h.tokens('def f(x):  # note')
        kinds = {k for _s, _e, k in spans}
        self.assertIn('keyword', kinds)
        self.assertIn('comment', kinds)
        self.assertEqual(state, 0)

    def test_multiline_string_state(self):
        h = Highlighter.for_path('a.py')
        _spans, state = h.tokens('s = """start')
        self.assertNotEqual(state, 0)
        spans, state2 = h.tokens('end""" + x', state)
        self.assertEqual(state2, 0)
        self.assertEqual(spans[0][2], 'string')

    def test_block_comment_state(self):
        h = Highlighter.for_path('a.c')
        _s, st = h.tokens('int x; /* open')
        self.assertEqual(st, 1)
        spans, st2 = h.tokens('still */ int y;', st)
        self.assertEqual(st2, 0)
        self.assertEqual(spans[0][2], 'comment')

    def test_markdown_and_language_names(self):
        self.assertEqual(Highlighter.for_path('a.md').name, 'Markdown')
        self.assertEqual(Highlighter.for_path('a.rs').name, 'Rust')
        self.assertEqual(Highlighter.for_path('Makefile').name, 'Shell')
        self.assertEqual(Highlighter.for_path('a.unknown').name, 'Plain')


class TestKeys(unittest.TestCase):
    def test_decode_mix(self):
        d = Decoder()
        evs = d.feed(b'a\x13\x1b[1;5C\x1b[<0;10;5M\x1b[3~')
        self.assertEqual(evs[0].combo(), 'a')
        self.assertEqual(evs[1].combo(), 'ctrl+s')
        self.assertEqual(evs[2].combo(), 'ctrl+right')
        self.assertIsInstance(evs[3], Mouse)
        self.assertEqual((evs[3].x, evs[3].y), (9, 4))
        self.assertEqual(evs[4].combo(), 'delete')

    def test_split_sequences(self):
        d = Decoder()
        self.assertEqual(d.feed(b'\x1b['), [])
        evs = d.feed(b'A')
        self.assertEqual(evs[0].combo(), 'up')

    def test_horizontal_wheel(self):
        d = Decoder()
        kinds = [e.kind for e in d.feed(b'\x1b[<64;5;5M\x1b[<65;5;5M'
                                        b'\x1b[<66;5;5M\x1b[<67;5;5M')]
        self.assertEqual(kinds, ['wheel_up', 'wheel_down', 'wheel_left', 'wheel_right'])

    def test_bracketed_paste(self):
        d = Decoder()
        evs = d.feed(b'\x1b[200~one\ntwo\x1b[201~')
        self.assertIsInstance(evs[0], Paste)
        self.assertEqual(evs[0].text, 'one\ntwo')

    def test_key_to_bytes_roundtrip(self):
        self.assertEqual(key_to_bytes(Key('char', 'c', 1)), b'\x03')
        self.assertEqual(key_to_bytes(Key('enter')), b'\r')
        self.assertEqual(key_to_bytes(Key('up'), app_cursor=True), b'\x1bOA')


class TestVT(unittest.TestCase):
    def test_basic_output_and_colour(self):
        v = VT(20, 4)
        v.feed(b'hi\r\n\x1b[31mred\x1b[0m')
        self.assertEqual(''.join(c[0] for c in v.grid[0]).rstrip(), 'hi')
        self.assertEqual(v.grid[1][0][1], 1)

    def test_scrollback(self):
        v = VT(10, 3)
        for i in range(6):
            v.feed(('l%d\r\n' % i).encode())
        self.assertEqual(len(v.scrollback), 4)
        self.assertIn('l5', v.text_lines()[-2])

    def test_counts_lines_pushed_into_scrollback(self):
        v = VT(10, 3)
        self.assertEqual(v.pushed, 0)
        for i in range(6):
            v.feed(('l%d\r\n' % i).encode())
        self.assertEqual(v.pushed, len(v.scrollback))

    def test_erase_and_cursor_moves(self):
        v = VT(10, 3)
        v.feed(b'abcdef\x1b[1;3H\x1b[K')
        self.assertEqual(''.join(c[0] for c in v.grid[0]).rstrip(), 'ab')
        v.feed(b'\x1b[2J\x1b[H')
        self.assertEqual(v.text_lines()[0], '')

    def test_alt_screen_and_resize(self):
        v = VT(10, 3)
        v.feed(b'keep\x1b[?1049h')
        self.assertTrue(v.alt_screen)
        v.feed(b'\x1b[?1049l')
        self.assertIn('keep', v.text_lines()[0])
        v.resize(20, 5)
        self.assertEqual((v.cols, v.rows), (20, 5))

    def test_insert_delete_lines(self):
        v = VT(6, 4)
        v.feed(b'a\r\nb\r\nc\x1b[1;1H\x1b[L')
        self.assertEqual(v.text_lines()[0], '')
        self.assertEqual(v.text_lines()[1], 'a')

    def _line(self, v, row=0):
        return ''.join(c[0] or ' ' for c in v.grid[row]).rstrip()

    def test_a_device_control_string_is_swallowed(self):
        v = VT(40, 3)
        v.feed(b'\x1bPsome;payload\x1b\\ok')
        self.assertEqual(self._line(v), 'ok')

    def test_the_progress_report_claude_code_sends(self):
        # ESC P ESC ESC ] 9;4;0; BEL ESC \  - an OSC wrapped in a DCS, which
        # used to spill ']9;4;0;' into the pane
        v = VT(40, 3)
        v.feed(b'\x1bP\x1b\x1b]9;4;0;\x07\x1b\\hello')
        self.assertEqual(self._line(v), 'hello')

    def test_control_strings_survive_being_split(self):
        raw = (b'\x1b]0;title\x07\x1bP\x1b\x1b]9;4;3;\x07\x1b\\'
               b'\x1b_app\x1b\\text')
        for cut in range(1, len(raw)):
            v = VT(40, 3)
            v.feed(raw[:cut])
            v.feed(raw[cut:])
            self.assertEqual(self._line(v), 'text', 'split at %d' % cut)
            self.assertEqual(v.title, 'title')

    def test_an_eight_bit_string_terminator_ends_one(self):
        v = VT(40, 3)
        v.feed(b'\x1b]0;name\xc2\x9cafter')
        self.assertEqual(self._line(v), 'after')
        self.assertEqual(v.title, 'name')


class TestScreen(unittest.TestCase):
    def test_diff_flush_is_minimal(self):
        import io
        s = Screen(20, 3)
        s.put(0, 0, 'hello')
        out = io.StringIO()
        s.flush(out)
        s.put(0, 0, 'hellp')
        out2 = io.StringIO()
        s.flush(out2)
        self.assertIn('p', out2.getvalue())
        self.assertNotIn('hello', out2.getvalue())

    def test_wide_characters(self):
        s = Screen(10, 1)
        wide = '\u6f22\u5b57'   # two double-width characters
        s.put(0, 0, wide)
        self.assertEqual(text_width(wide), 4)
        self.assertEqual(s.cells[0][1][0], '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
