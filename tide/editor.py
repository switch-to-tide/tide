"""The editor pane: viewport, painting, mouse and key handling."""

import os
import time

from . import clipboard, theme
from .buffer import Document, is_word_char
from .highlight import Highlighter, LineStates
from .keys import CTRL, ALT, SHIFT
from . import wrap
from .term import BOLD, DIM, REVERSE, Rect, char_width

HSCROLL_FADE = 1.6       # seconds the sideways bar stays after you stop


class Editor(object):
    is_diff = False

    def __init__(self, app, doc=None, path=None):
        self.app = app
        self.doc = doc or Document(path)
        self.hl = Highlighter.for_path(self.doc.path or '')
        self.states = LineStates(self.hl)
        self.doc.on_change = self._on_change
        self.tab_width = getattr(app, 'default_tab_width', None) or self.hl.tab_width
        self.use_spaces = True
        self.indent_detected = False
        self._top = 0             # first document row on screen
        self.top_seg = 0          # which of its wrapped pieces is at the top
        self._wrap_key = None
        self._wrap_cache = {}
        self.left = 0
        self._widest = 0
        self._widest_key = None
        self.hscroll_at = 0.0             # when the sideways bar last woke up
        self.rect = Rect(0, 0, 1, 1)
        self.text_rect = Rect(0, 0, 1, 1)
        self.gutter = 4
        self.git_marks = {}       # line number -> 'added' | 'modified' | 'deleted'
        self.git_gutter = False
        self.sb_x = None
        self.ov_x = None
        self.sb_grab = 0
        self.find_query = ''
        self.find_matches = []
        self.find_index = 0
        self.last_click = (0, None)
        self.click_count = 0
        self.drag_mode = None
        self._detect_indent()

    # ---------------- setup ----------------
    def _detect_indent(self):
        for line in self.doc.lines[:200]:
            stripped = line.lstrip()
            if not stripped or stripped == line:
                continue
            lead = line[:len(line) - len(stripped)]
            if lead.startswith('\t'):
                self.use_spaces = False
                self.indent_detected = True
                return
            if len(lead) in (2, 4, 8):
                self.tab_width = len(lead)
                self.indent_detected = True
                return

    def _on_change(self, row):
        self.states.invalidate_from(row)
        if self.find_query:
            self.refresh_find()

    @property
    def path(self):
        return self.doc.path

    @property
    def title(self):
        return self.doc.name

    # ---------------- display geometry ----------------
    @property
    def top(self):
        return self._top

    @top.setter
    def top(self, row):
        # setting a row outright means the top of that row, wrapped or not
        self._top = row
        self.top_seg = 0

    def wrapping(self):
        """Whether this file's long lines are wrapped rather than scrolled."""
        settings = getattr(self.app, 'settings', None) or {}
        return wrap.wraps(settings.get('wrap', 'smart'), self.doc.path)

    def _xs(self, row):
        """Where each character of a row sits once tabs are expanded."""
        line = self.doc.line(row)
        xs = [0] * (len(line) + 1)
        x = 0
        for i, ch in enumerate(line):
            x = self._advance(ch, x)
            xs[i + 1] = x
        return xs

    def segments(self, row):
        """The (start, end) pieces a row is drawn in - one unless wrapped."""
        line = self.doc.line(row)
        if not self.wrapping():
            return [(0, len(line))]
        key = (self.text_rect.w, self.tab_width)
        if self._wrap_key != key or len(self._wrap_cache) > 4000:
            self._wrap_key, self._wrap_cache = key, {}
        # kept against the line itself: an edit or a reload from disk makes a
        # new string, so there is no stale answer to give
        cached = self._wrap_cache.get(row)
        if cached is not None and cached[0] is line:
            return cached[1]
        segs = wrap.segments(line, max(2, self.text_rect.w), self._xs(row))
        self._wrap_cache[row] = (line, segs)
        return segs

    def vrows(self, row):
        """Screen rows a document row takes, including the blank after a wrap."""
        count = len(self.segments(row))
        return count + 1 if count > 1 else 1

    def seg_of_col(self, row, col):
        for i, (start, end) in enumerate(self.segments(row)):
            if col < end:
                return i
        return len(self.segments(row)) - 1

    def vstep(self, pos, delta):
        """Move a (row, piece) position by that many screen rows."""
        row, seg = pos
        last = len(self.doc.lines) - 1
        while delta > 0:
            if seg + 1 < self.vrows(row):
                seg += 1
            elif row < last:
                row, seg = row + 1, 0
            else:
                break
            delta -= 1
        while delta < 0:
            if seg > 0:
                seg -= 1
            elif row > 0:
                row -= 1
                seg = self.vrows(row) - 1
            else:
                break
            delta += 1
        return (row, seg)

    def visible(self, height=None):
        """[(row, piece)] from the top of the pane down, as far as it goes."""
        height = self.text_rect.h if height is None else height
        rows = []
        pos = (max(0, min(self._top, len(self.doc.lines) - 1)), self.top_seg)
        last = len(self.doc.lines) - 1
        for _ in range(max(0, height)):
            rows.append(pos)
            nxt = self.vstep(pos, 1)
            if nxt == pos:
                break
            pos = nxt
        return rows

    def _clamp_top(self):
        """Never scroll past the last screenful."""
        last = len(self.doc.lines) - 1
        self._top = max(0, min(self._top, last))
        self.top_seg = max(0, min(self.top_seg, self.vrows(self._top) - 1))
        end = (last, self.vrows(last) - 1)
        limit = self.vstep(end, -(max(1, self.text_rect.h) - 1))
        if (self._top, self.top_seg) > limit:
            self._top, self.top_seg = limit

    def _advance(self, ch, x):
        if ch == '\t':
            return x + (self.tab_width - x % self.tab_width)
        return x + max(1, char_width(ch))

    def col_to_x(self, row, col):
        line = self.doc.line(row)
        x = 0
        for ch in line[:col]:
            x = self._advance(ch, x)
        return x

    def x_to_col(self, row, target):
        line = self.doc.line(row)
        x = 0
        for i, ch in enumerate(line):
            nx = self._advance(ch, x)
            if target < nx:
                return i if target - x <= nx - target - 1 else i + 1
            x = nx
        return len(line)

    def line_width(self, row):
        return self.col_to_x(row, len(self.doc.line(row)))

    # ---------------- cursor & scrolling ----------------
    def set_cursor(self, pos, extend=False, keep_goal=False):
        doc = self.doc
        pos = doc.clamp(pos)
        if extend:
            if doc.anchor is None:
                doc.anchor = doc.cursor
        else:
            doc.anchor = None
        doc.cursor = pos
        doc.break_undo_group()
        if not keep_goal:
            doc.goal_col = None
        self.ensure_visible()

    def move_vertical(self, delta, extend=False):
        doc = self.doc
        row, col = doc.cursor
        if doc.goal_col is None:
            doc.goal_col = self.col_to_x(row, col)
        new_row = max(0, min(len(doc.lines) - 1, row + delta))
        new_col = self.x_to_col(new_row, doc.goal_col)
        self.set_cursor((new_row, new_col), extend, keep_goal=True)

    def max_left(self):
        """Furthest left column: the widest line, less one screenful."""
        if self.wrapping():
            return 0                        # nothing runs off the side
        key = (self.doc._version, self.tab_width)
        if self._widest_key != key:
            lines = self.doc.lines
            longest = sorted(range(len(lines)), key=lambda i: len(lines[i]),
                             reverse=True)[:8]        # tabs can beat raw length
            self._widest = max([self.col_to_x(i, len(lines[i])) for i in longest] or [0])
            self._widest_key = key
        return max(0, self._widest - max(1, self.text_rect.w))

    def scroll_x(self, delta):
        left = max(0, min(self.max_left(), self.left + delta))
        if left != self.left:
            self.left = left
            self.hscroll_at = time.time()

    def hbar(self):
        """(thumb_width, thumb_offset) for the sideways bar, or None."""
        r = self.text_rect
        span = self.max_left()
        if r.w < 4 or span <= 0:
            return None                     # every line fits: no bar
        total = span + r.w
        thumb = max(2, int(round(r.w * r.w / float(total))))
        thumb = min(thumb, r.w - 1)
        offset = int(round((r.w - thumb) * min(self.left, span) / float(span)))
        return thumb, max(0, min(r.w - thumb, offset))

    def hbar_showing(self):
        return (time.time() - self.hscroll_at < HSCROLL_FADE
                and self.hbar() is not None)

    def max_top(self):
        """Highest first-visible line: the last screenful of the document."""
        return max(0, len(self.doc.lines) - max(1, self.text_rect.h))

    def scrollbar(self):
        """(thumb_height, thumb_offset) for the current viewport, or None."""
        h = self.text_rect.h
        total = len(self.doc.lines)
        if h < 2 or total <= h:
            return None                     # everything fits: no bar
        thumb = max(1, int(round(h * h / float(total))))
        thumb = min(thumb, h - 1)           # always leave room to move
        top = max(0, min(self.top, self.max_top()))
        span = self.max_top()
        offset = 0 if span == 0 else int(round((h - thumb) * top / float(span)))
        return thumb, max(0, min(h - thumb, offset))

    def ensure_visible(self):
        row, col = self.doc.cursor
        h = max(1, self.text_rect.h)
        w = max(1, self.text_rect.w)
        if self.wrapping():
            self.left = 0
            here = (row, self.seg_of_col(row, col))
            if here < (self._top, self.top_seg):
                self._top, self.top_seg = here
            elif here not in self.visible(h):
                self._top, self.top_seg = self.vstep(here, -(h - 1))
            self._clamp_top()
            return
        if row < self.top:
            self.top = row
        elif row >= self.top + h:
            self.top = row - h + 1
        self._top = max(0, min(self._top, max(0, len(self.doc.lines) - 1)))
        x = self.col_to_x(row, col)
        if x < self.left:
            self.left = max(0, x - 4)
        elif x >= self.left + w:
            self.left = x - w + 1

    def scroll(self, delta):
        if self.wrapping():
            self._top, self.top_seg = self.vstep((self._top, self.top_seg), delta)
            self._clamp_top()
            return
        self.top = max(0, min(self.max_top(), self.top + delta))

    def sb_press(self, y):
        """Grab the thumb where it was clicked, or jump the thumb to the click."""
        bar = self.scrollbar()
        if not bar:
            return
        thumb, offset = bar
        rel = y - self.text_rect.y
        if offset <= rel < offset + thumb:
            self.sb_grab = rel - offset          # keep the grab point steady
        else:
            self.sb_grab = thumb // 2            # centre it under the pointer
            self.sb_drag_to(y)
        self.drag_mode = 'scrollbar'

    def sb_drag_to(self, y):
        bar = self.scrollbar()
        if not bar:
            return
        thumb, _offset = bar
        room = max(1, self.text_rect.h - thumb)
        offset = max(0, min(room, (y - self.text_rect.y) - self.sb_grab))
        self.top = int(round(offset / float(room) * self.max_top()))

    # ---------------- editing ----------------
    def insert_text(self, text, coalesce=False):
        self.doc.insert(text, coalesce=coalesce)
        self.ensure_visible()

    def _indent_unit(self):
        return ' ' * self.tab_width if self.use_spaces else '\t'

    def newline(self):
        doc = self.doc
        sel = doc.selection()
        if sel:
            doc.delete_range(*sel)
        row, col = doc.cursor
        line = doc.line(row)
        indent = doc.indent_of(row)
        before = line[:col].rstrip()
        extra = ''
        if before.endswith((':', '{', '[', '(')):
            extra = self._indent_unit()
        after = line[col:].lstrip()
        closing = after[:1] in ('}', ']', ')') and extra
        text = '\n' + indent + extra
        if closing:
            text += '\n' + indent
        pos = doc.replace(doc.cursor, doc.cursor, text)
        if closing:
            doc.cursor = (row + 1, len(indent + extra))
        else:
            doc.cursor = pos
        doc.break_undo_group()
        self.ensure_visible()

    def indent_selection(self, dedent=False):
        doc = self.doc
        sel = doc.selection()
        unit = self._indent_unit()
        if sel is None:
            if dedent:
                row, col = doc.cursor
                line = doc.line(row)
                lead = len(line) - len(line.lstrip())
                if lead:
                    cut = min(len(unit), lead)
                    doc.replace((row, 0), (row, cut), '')
                    doc.cursor = (row, max(0, col - cut))
                return
            row, col = doc.cursor
            x = self.col_to_x(row, col)
            pad = self.tab_width - x % self.tab_width
            self.insert_text(' ' * pad if self.use_spaces else '\t')
            return
        (r1, c1), (r2, c2) = sel
        if c2 == 0 and r2 > r1:
            r2 -= 1
        for row in range(r1, r2 + 1):
            line = doc.line(row)
            if dedent:
                if line.startswith('\t'):
                    doc.replace((row, 0), (row, 1), '')
                    cut = 1
                else:
                    lead = len(line) - len(line.lstrip(' '))
                    cut = min(len(unit), lead)
                    if cut:
                        doc.replace((row, 0), (row, cut), '')
                if row == r1:
                    c1 = max(0, c1 - cut)
                if row == sel[1][0]:
                    c2 = max(0, c2 - cut)
            else:
                if line.strip() or row == r1:
                    doc.replace((row, 0), (row, 0), unit)
                    if row == r1:
                        c1 += len(unit)
                    if row == sel[1][0]:
                        c2 += len(unit)
        doc.anchor = (r1, c1)
        doc.cursor = (sel[1][0], c2)
        doc.break_undo_group()

    def toggle_comment(self):
        doc = self.doc
        token = self.hl.comment_token
        if not token:
            return
        sel = doc.selection()
        if sel:
            r1, r2 = sel[0][0], sel[1][0]
            if sel[1][1] == 0 and r2 > r1:
                r2 -= 1
        else:
            r1 = r2 = doc.cursor[0]
        rows = [r for r in range(r1, r2 + 1) if doc.line(r).strip()]
        if not rows:
            return
        all_commented = all(doc.line(r).lstrip().startswith(token) for r in rows)
        indent = min(len(doc.line(r)) - len(doc.line(r).lstrip()) for r in rows)
        row, col = doc.cursor
        anchor = doc.anchor
        for r in rows:
            line = doc.line(r)
            if all_commented:
                i = line.index(token)
                cut = len(token) + (1 if line[i + len(token):i + len(token) + 1] == ' ' else 0)
                doc.replace((r, i), (r, i + cut), '')
                delta = -cut
            else:
                doc.replace((r, indent), (r, indent), token + ' ')
                delta = len(token) + 1
            if r == row:
                col = max(0, col + delta)
            if anchor and r == anchor[0]:
                anchor = (anchor[0], max(0, anchor[1] + delta))
        doc.cursor = doc.clamp((row, col))
        doc.anchor = doc.clamp(anchor) if anchor else None
        doc.break_undo_group()

    def duplicate(self):
        doc = self.doc
        sel = doc.selection()
        if sel:
            text = doc.get_range(*sel)
            doc.replace(sel[1], sel[1], text)
        else:
            row = doc.cursor[0]
            line = doc.line(row)
            doc.replace((row, len(line)), (row, len(line)), '\n' + line)
            doc.cursor = (row + 1, doc.cursor[1])
        doc.break_undo_group()
        self.ensure_visible()

    def delete_lines(self):
        doc = self.doc
        sel = doc.selection()
        r1 = sel[0][0] if sel else doc.cursor[0]
        r2 = sel[1][0] if sel else doc.cursor[0]
        if r2 + 1 < len(doc.lines):
            doc.replace((r1, 0), (r2 + 1, 0), '')
        else:
            start = (r1 - 1, len(doc.line(r1 - 1))) if r1 > 0 else (0, 0)
            doc.replace(start, (r2, len(doc.line(r2))), '')
        doc.break_undo_group()
        self.ensure_visible()

    def move_lines(self, delta):
        """Move the current line (or selected lines) up or down."""
        doc = self.doc
        sel = doc.selection()
        r1 = sel[0][0] if sel else doc.cursor[0]
        r2 = sel[1][0] if sel else doc.cursor[0]
        if sel and sel[1][1] == 0 and r2 > r1:
            r2 -= 1
        if delta < 0 and r1 == 0:
            return
        if delta > 0 and r2 >= len(doc.lines) - 1:
            return
        lo, hi = (r1 - 1, r2) if delta < 0 else (r1, r2 + 1)
        block = doc.lines[r1:r2 + 1]
        if delta < 0:
            new_lines = block + [doc.lines[r1 - 1]]
        else:
            new_lines = [doc.lines[r2 + 1]] + block
        cur = doc.cursor
        anc = doc.anchor
        doc.replace((lo, 0), (hi, len(doc.line(hi))), '\n'.join(new_lines))
        doc.cursor = doc.clamp((cur[0] + delta, cur[1]))
        doc.anchor = doc.clamp((anc[0] + delta, anc[1])) if anc else None
        doc.break_undo_group()
        self.ensure_visible()

    def delete_word(self, forward):
        doc = self.doc
        sel = doc.selection()
        if sel:
            doc.delete_range(*sel)
            return
        pos = doc.word_right(doc.cursor) if forward else doc.word_left(doc.cursor)
        if pos != doc.cursor:
            doc.delete_range(doc.cursor, pos)
        doc.break_undo_group()

    def backspace(self):
        doc = self.doc
        sel = doc.selection()
        if sel:
            doc.delete_range(*sel)
            self.ensure_visible()
            return
        row, col = doc.cursor
        line = doc.line(row)
        if col > 0 and self.use_spaces and line[:col].strip() == '':
            x = self.col_to_x(row, col)
            back = x % self.tab_width or self.tab_width
            back = min(back, col)
            doc.replace((row, col - back), (row, col), '')
        else:
            prev = doc.move_left(doc.cursor)
            if prev != doc.cursor:
                doc.replace(prev, doc.cursor, '')
        self.ensure_visible()

    def delete_forward(self):
        doc = self.doc
        sel = doc.selection()
        if sel:
            doc.delete_range(*sel)
        else:
            nxt = doc.move_right(doc.cursor)
            if nxt != doc.cursor:
                doc.replace(doc.cursor, nxt, '')
        self.ensure_visible()

    def copy(self, cut=False):
        doc = self.doc
        sel = doc.selection()
        if sel:
            text = doc.get_range(*sel)
            clipboard.copy(text)
            if cut:
                doc.delete_range(*sel)
        else:
            row = doc.cursor[0]
            clipboard.copy(doc.line(row) + '\n')
            if cut:
                self.delete_lines()
        self.ensure_visible()

    def paste(self, text=None):
        text = clipboard.paste() if text is None else text
        if not text:
            return
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        self.doc.insert(text)
        self.doc.break_undo_group()
        self.ensure_visible()

    def select_all(self):
        self.doc.anchor = (0, 0)
        self.doc.cursor = self.doc.end_pos()
        self.ensure_visible()

    def select_word_at(self, pos):
        span = self.doc.word_at(pos)
        if span:
            self.doc.anchor, self.doc.cursor = span
        else:
            self.set_cursor(pos)

    def select_line_at(self, row):
        doc = self.doc
        doc.anchor = (row, 0)
        doc.cursor = (row + 1, 0) if row + 1 < len(doc.lines) else (row, len(doc.line(row)))

    # ---------------- find ----------------
    def set_find(self, query):
        self.find_query = query
        self.refresh_find()

    def refresh_find(self):
        self.find_matches = self.doc.find_all(self.find_query)
        cur = self.doc.cursor
        self.find_index = 0
        for i, (s, _e) in enumerate(self.find_matches):
            if s >= cur:
                self.find_index = i
                break

    def find_next(self, back=False):
        if not self.find_matches:
            return False
        cur = self.doc.cursor
        if back:
            cands = [i for i, (s, _e) in enumerate(self.find_matches) if s < cur]
            self.find_index = cands[-1] if cands else len(self.find_matches) - 1
        else:
            cands = [i for i, (s, _e) in enumerate(self.find_matches) if s > cur]
            self.find_index = cands[0] if cands else 0
        s, e = self.find_matches[self.find_index]
        self.doc.anchor = s
        self.doc.cursor = e
        self.ensure_visible()
        return True

    # ---------------- input ----------------
    def on_key(self, key):
        doc = self.doc
        name = key.name
        mods = key.mods
        shift = bool(mods & SHIFT)
        ctrl = bool(mods & CTRL)
        alt = bool(mods & ALT)

        if name == 'char':
            ch = key.char
            if ctrl or alt:
                return self._control_key(key)
            self.doc.insert(ch, coalesce=(ch not in ' \t'))
            self.ensure_visible()
            return True
        if name == 'enter':
            self.newline()
            return True
        if name == 'tab':
            self.indent_selection(dedent=shift)
            return True
        if name == 'backspace':
            if ctrl or alt:
                self.delete_word(False)
            else:
                self.backspace()
            return True
        if name == 'delete':
            if ctrl or alt:
                self.delete_word(True)
            elif shift:
                self.delete_lines()
            else:
                self.delete_forward()
            return True
        if name == 'left':
            pos = doc.word_left(doc.cursor) if (ctrl or alt) else (
                doc.selection()[0] if (doc.selection() and not shift) else doc.move_left(doc.cursor))
            self.set_cursor(pos, shift)
            return True
        if name == 'right':
            pos = doc.word_right(doc.cursor) if (ctrl or alt) else (
                doc.selection()[1] if (doc.selection() and not shift) else doc.move_right(doc.cursor))
            self.set_cursor(pos, shift)
            return True
        if name == 'up':
            if alt:
                self.move_lines(-1)
            elif ctrl:
                self.scroll(-1)
            else:
                self.move_vertical(-1, shift)
            return True
        if name == 'down':
            if alt:
                self.move_lines(1)
            elif ctrl:
                self.scroll(1)
            else:
                self.move_vertical(1, shift)
            return True
        if name == 'home':
            if ctrl:
                self.set_cursor((0, 0), shift)
            else:
                row, col = doc.cursor
                first = doc.first_nonblank(row)
                self.set_cursor((row, 0 if col == first else first), shift)
            return True
        if name == 'end':
            if ctrl:
                self.set_cursor(doc.end_pos(), shift)
            else:
                row = doc.cursor[0]
                self.set_cursor((row, len(doc.line(row))), shift)
            return True
        if name == 'pageup':
            self.move_vertical(-max(1, self.text_rect.h - 1), shift)
            self.top = max(0, self.top - max(1, self.text_rect.h - 1))
            return True
        if name == 'pagedown':
            self.move_vertical(max(1, self.text_rect.h - 1), shift)
            self.top = min(self.max_top(), self.top + max(1, self.text_rect.h - 1))
            return True
        if name == 'f3':
            self.find_next(back=shift)
            return True
        return False

    def _control_key(self, key):
        ch = key.char.lower()
        alt = bool(key.mods & ALT)
        ctrl = bool(key.mods & CTRL)
        shift = bool(key.mods & SHIFT)
        if alt and not ctrl:
            return False
        if ch == 'a':
            self.select_all()
        elif ch == 'c':
            self.copy()
            self.app.status('Copied')
        elif ch == 'x':
            self.copy(cut=True)
        elif ch == 'v':
            self.paste()
        elif ch == 'z':
            if shift:
                self.doc.redo()
            else:
                self.doc.undo()
            self.ensure_visible()
        elif ch == 'y':
            self.doc.redo()
            self.ensure_visible()
        elif ch == 'd':
            self.duplicate()
        elif ch == 'k':
            self.delete_lines()
        elif ch == '/':
            self.toggle_comment()
        elif ch == 'l':
            self.select_line_at(self.doc.cursor[0])
        else:
            return False
        return True

    def on_mouse(self, ev):
        r = self.text_rect
        if ev.kind == 'wheel_up':
            self.scroll(-3)
            return True
        if ev.kind == 'wheel_down':
            self.scroll(3)
            return True
        if ev.kind in ('wheel_left', 'wheel_right'):
            self.scroll_x(-4 if ev.kind == 'wheel_left' else 4)
            return True
        if self.drag_mode == 'scrollbar':
            if ev.kind == 'drag':
                self.sb_drag_to(ev.y)
                return True
            if ev.kind == 'release':
                self.drag_mode = None
                return True
        if (ev.kind == 'press' and self.sb_x is not None and ev.x == self.sb_x
                and self.rect.contains(ev.x, ev.y)):
            self.sb_press(ev.y)
            return True
        in_gutter = self.rect.contains(ev.x, ev.y) and ev.x < r.x
        row, seg = self.row_at(ev.y)
        if ev.kind == 'press':
            now = time.time()
            last_t, last_pos = self.last_click
            near = last_pos is not None and abs(last_pos[0] - ev.x) < 2 and last_pos[1] == ev.y
            self.click_count = (self.click_count + 1) if (now - last_t < 0.45 and near) else 1
            self.last_click = (now, (ev.x, ev.y))
            if in_gutter:
                self.select_line_at(row)
                self.drag_mode = 'line'
                return True
            col = self.col_at(row, seg, ev.x)
            if self.click_count >= 3:
                self.select_line_at(row)
                self.drag_mode = 'line'
            elif self.click_count == 2:
                self.select_word_at((row, col))
                self.drag_mode = 'word'
            else:
                self.set_cursor((row, col), extend=bool(ev.mods & SHIFT))
                self.drag_mode = 'char'
            return True
        if ev.kind == 'drag':
            if self.drag_mode is None:
                return False
            if ev.y < r.y:
                self.scroll(-1)
                row, seg = self._top, self.top_seg
            elif ev.y >= r.y2:
                self.scroll(1)
                row, seg = self.row_at(r.y2 - 1)
            col = self.col_at(row, seg, ev.x)
            if self.doc.anchor is None:
                self.doc.anchor = self.doc.cursor
            if self.drag_mode == 'line':
                self.doc.cursor = self.doc.clamp((row + 1, 0))
            else:
                self.doc.cursor = self.doc.clamp((row, col))
            self.ensure_visible()
            return True
        if ev.kind == 'release':
            self.drag_mode = None
            return True
        return False

    def row_at(self, y):
        """Which (row, piece) is painted on that screen row."""
        rows = self.visible()
        i = max(0, y - self.text_rect.y)
        if not rows:
            return (0, 0)
        return rows[min(i, len(rows) - 1)]

    def col_at(self, row, seg, x):
        """Which character a click at that column is nearest."""
        segs = self.segments(row)
        seg = max(0, min(seg, len(segs) - 1))
        start = segs[seg][0]
        origin = self._xs(row)[start] if self.wrapping() else self.left
        return self.x_to_col(row, origin + max(0, x - self.text_rect.x))

    # ---------------- painting ----------------
    def render(self, screen, rect, focused):
        self.rect = rect
        doc = self.doc
        nlines = len(doc.lines)
        # one extra column on the far left for the git change bar
        self.git_gutter = bool(self.git_marks) or getattr(
            getattr(self.app, 'git', None), 'enabled', False)
        self.gutter = max(3, len(str(nlines))) + (3 if self.git_gutter else 2)
        # the whole file squeezed into one column at the far right, showing
        # where git says it has changed, and beside it a one column scrollbar
        # - that one only when there is more document than viewport
        self.ov_x = (rect.x2 - 1 if self.git_marks and rect.w > self.gutter + 6
                     else None)
        # a blank column between the two, so the ruler is still readable
        # where the scrollbar's thumb happens to be beside it
        edge = 2 if self.ov_x is not None else 0
        show_bar = nlines > rect.h and rect.w > self.gutter + 4 + edge
        self.sb_x = rect.x2 - 1 - edge if show_bar else None
        self.text_rect = Rect(rect.x + self.gutter, rect.y,
                              rect.w - self.gutter - edge - (1 if show_bar else 0),
                              rect.h)
        r = self.text_rect
        if not self.wrapping():
            self.top = max(0, min(self.top, self.max_top()))
        sel = doc.selection()
        cur_row = doc.cursor[0]
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.BG)
        matches = self.find_matches
        wrapped = self.wrapping()
        if wrapped:
            self.left = 0
            self._clamp_top()
        painted = self.visible(r.h) if wrapped else \
            [(self.top + i, 0) for i in range(r.h)]
        for i in range(r.h):
            y = r.y + i
            row, seg = painted[i] if i < len(painted) else (nlines, 0)
            if row >= nlines:
                screen.put(rect.x, y, '~'.rjust(self.gutter - 1), fg=theme.BORDER, bg=theme.BG)
                continue
            line = doc.lines[row]
            is_cur = row == cur_row
            segs = self.segments(row)
            blank = seg >= len(segs)     # the breather after a wrapped line
            start, end = (len(line), len(line)) if blank else segs[seg]
            start, end = min(start, len(line)), min(end, len(line))
            xs = self._xs(row) if wrapped else None
            origin = xs[start] if wrapped else self.left
            # gutter: [change bar] [line number] [space] [text]. A line that
            # carried on from the row above says so by having no number.
            num_x = rect.x + (1 if self.git_gutter else 0)
            num = (str(row + 1) if seg == 0 else '').rjust(
                self.gutter - 1 - (1 if self.git_gutter else 0))
            screen.put(num_x, y, num, fg=(theme.LINENO_CUR if is_cur else theme.LINENO),
                       bg=theme.GUTTER_BG, attr=BOLD if is_cur else 0)
            if self.git_gutter:
                mark = self.git_marks.get(row)
                if mark and seg == 0:
                    glyph = '▁' if mark == 'deleted' else '▌'
                    screen.put(rect.x, y, glyph, fg=theme.LINE_COLOUR[mark],
                               bg=theme.GUTTER_BG)
                elif mark:
                    screen.put(rect.x, y, '▌', fg=theme.LINE_COLOUR[mark],
                               bg=theme.GUTTER_BG, attr=DIM)
            if blank:
                continue
            base_bg = theme.BG_ALT if (is_cur and sel is None and focused) else theme.BG
            if base_bg != theme.BG:
                screen.fill(r.x, y, r.w, 1, bg=base_bg)
            # selection range for this row (character indices)
            sel_span = None
            if sel:
                (sr, sc), (er, ec) = sel
                if sr <= row <= er:
                    a = sc if row == sr else 0
                    b = ec if row == er else len(line) + 1
                    sel_span = (a, b)
            # syntax spans
            state = self.states.state_for(doc.lines, row)
            spans, _ = self.hl.tokens(line, state)
            kinds = [None] * (len(line) + 1)
            for s, e, kind in spans:
                for k in range(s, min(e, len(line))):
                    kinds[k] = kind
            match_cols = set()
            for mi, (ms, me) in enumerate(matches):
                if ms[0] == row:
                    for k in range(ms[1], me[1]):
                        match_cols.add((k, mi == self.find_index))
            match_map = {}
            for k, is_cur_match in match_cols:
                match_map[k] = match_map.get(k, False) or is_cur_match
            # paint characters
            x = xs[start] if wrapped else 0
            for idx in range(start if wrapped else 0, end if wrapped else len(line)):
                ch = line[idx]
                nx = self._advance(ch, x)
                if nx > origin and x < origin + r.w:
                    fg, attr = theme.token_style(kinds[idx] or 'text')
                    bg = base_bg
                    if sel_span and sel_span[0] <= idx < sel_span[1]:
                        bg = theme.SELECTION
                    elif idx in match_map:
                        bg = theme.FIND_CUR if match_map[idx] else theme.FIND_MATCH
                    sx = r.x + x - origin
                    if ch == '\t':
                        width = nx - x
                        screen.fill(max(r.x, sx), y, min(width, r.x2 - max(r.x, sx)), 1, bg=bg)
                    elif sx >= r.x:
                        screen.put(sx, y, ch, fg=fg, bg=bg, attr=attr, max_x=r.x2)
                x = nx
                if x - origin > r.w:
                    break
            # selection continues past end of line (multi-line selections)
            if sel_span and sel_span[1] > len(line) and end >= len(line):
                sx = r.x + x - origin
                if r.x <= sx < r.x2:
                    screen.fill(sx, y, 1, 1, bg=theme.SELECTION)
        self._render_scrollbar(screen, focused)
        self._render_hbar(screen)
        return self.cursor_screen_pos()

    def _render_hbar(self, screen):
        """A sideways bar along the last text row, while you are scrolling."""
        if not self.hbar_showing():
            return
        thumb, offset = self.hbar()
        r = self.text_rect
        y = r.y2 - 1
        for x in range(r.x, r.x2):          # keep the text, tint behind it
            ch, fg, _bg, attr = screen.cells[y][x]
            inside = r.x + offset <= x < r.x + offset + thumb
            screen.put(x, y, ch or ' ', fg=fg, attr=attr,
                       bg=theme.SCROLL_THUMB if inside else theme.SCROLL_TRACK)

    def _render_scrollbar(self, screen, focused):
        if self.sb_x is None:
            return
        bar = self.scrollbar()
        if not bar:
            return
        thumb, offset = bar
        r = self.text_rect
        screen.fill(self.sb_x, r.y, 1, r.h, bg=theme.SCROLL_TRACK)
        colour = theme.SCROLL_THUMB_HL if (focused or self.drag_mode == 'scrollbar') \
            else theme.SCROLL_THUMB
        screen.fill(self.sb_x, r.y + offset, 1, thumb, bg=colour)
        self._render_overview(screen)

    def _runs(self):
        """The changed lines, grouped into runs: [(first, last, kind)]."""
        runs = []
        for line in sorted(self.git_marks):
            kind = self.git_marks[line]
            if runs and runs[-1][2] == kind and runs[-1][1] == line - 1:
                runs[-1][1] = line
            else:
                runs.append([line, line, kind])
        return [(a, b, k) for a, b, k in runs]

    def _render_overview(self, screen):
        """Where the changes are, in miniature, down the scrollbar.

        Each run of changed lines is drawn as a bar of its own height, so a
        long file shows at a glance both where its edits are and how much of
        it they cover.
        """
        if not self.git_marks or self.ov_x is None:
            return
        r = self.text_rect
        total = max(1, len(self.doc.lines))
        rank = {'added': 1, 'modified': 2, 'deleted': 3}
        worst = {}
        for start, end, kind in self._runs():
            # a run of changed lines is a bar as tall as its share of the
            # file, so ten changed lines read as ten times one changed line
            top = r.y + int(start * r.h / total)
            # round the end up, so neighbouring runs meet rather than leaving
            # a gap, and a file changed to its last line is marked to the foot
            bottom = r.y + -(-(end + 1) * r.h // total)
            for y in range(top, max(top + 1, bottom)):
                if rank.get(kind, 0) >= rank.get(worst.get(y), 0):
                    worst[y] = kind
        for y, kind in worst.items():
            if not (0 <= y < screen.height):
                continue
            # a thin unbroken line: next to a run above or below it there is
            # no gap, so a long change reads as one bar, as in the gutter
            screen.put(self.ov_x, y, '▏', fg=theme.LINE_COLOUR[kind],
                       bg=theme.BG)

    def cursor_screen_pos(self):
        row, col = self.doc.cursor
        r = self.text_rect
        if self.wrapping():
            here = (row, self.seg_of_col(row, col))
            rows = self.visible()
            if here not in rows:
                return None
            y = r.y + rows.index(here)
            start = self.segments(row)[here[1]][0]
            x = r.x + self.col_to_x(row, col) - self._xs(row)[start]
            return (x, y) if r.x <= x < r.x2 else None
        y = r.y + row - self.top
        x = r.x + self.col_to_x(row, col) - self.left
        if r.y <= y < r.y2 and r.x <= x < r.x2:
            return (x, y)
        return None
