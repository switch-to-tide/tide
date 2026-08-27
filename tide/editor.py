"""The editor pane: viewport, painting, mouse and key handling."""

import os
import time

from . import clipboard, theme
from .buffer import Document, is_word_char
from .highlight import Highlighter, LineStates
from .keys import CTRL, ALT, SHIFT
from .term import BOLD, DIM, REVERSE, Rect, char_width


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
        self.top = 0
        self.left = 0
        self.rect = Rect(0, 0, 1, 1)
        self.text_rect = Rect(0, 0, 1, 1)
        self.gutter = 4
        self.git_marks = {}       # line number -> 'added' | 'modified' | 'deleted'
        self.git_gutter = False
        self.sb_x = None
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
        if row < self.top:
            self.top = row
        elif row >= self.top + h:
            self.top = row - h + 1
        self.top = max(0, min(self.top, max(0, len(self.doc.lines) - 1)))
        x = self.col_to_x(row, col)
        if x < self.left:
            self.left = max(0, x - 4)
        elif x >= self.left + w:
            self.left = x - w + 1

    def scroll(self, delta):
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
            step = -4 if ev.kind == 'wheel_left' else 4
            self.left = max(0, self.left + step)
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
        row = self.top + max(0, ev.y - r.y)
        row = max(0, min(len(self.doc.lines) - 1, row))
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
            col = self.x_to_col(row, self.left + max(0, ev.x - r.x))
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
                row = self.top
            elif ev.y >= r.y2:
                self.scroll(1)
                row = min(len(self.doc.lines) - 1, self.top + r.h - 1)
            col = self.x_to_col(row, self.left + max(0, ev.x - r.x))
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

    # ---------------- painting ----------------
    def render(self, screen, rect, focused):
        self.rect = rect
        doc = self.doc
        nlines = len(doc.lines)
        # one extra column on the far left for the git change bar
        self.git_gutter = bool(self.git_marks) or getattr(
            getattr(self.app, 'git', None), 'enabled', False)
        self.gutter = max(3, len(str(nlines))) + (3 if self.git_gutter else 2)
        # a one column scrollbar on the right, but only when there is more
        # document than viewport
        show_bar = nlines > rect.h and rect.w > self.gutter + 4
        self.sb_x = rect.x2 - 1 if show_bar else None
        self.text_rect = Rect(rect.x + self.gutter, rect.y,
                              rect.w - self.gutter - (1 if show_bar else 0), rect.h)
        r = self.text_rect
        self.top = max(0, min(self.top, self.max_top()))
        sel = doc.selection()
        cur_row = doc.cursor[0]
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.BG)
        matches = self.find_matches
        for i in range(r.h):
            row = self.top + i
            y = r.y + i
            if row >= nlines:
                screen.put(rect.x, y, '~'.rjust(self.gutter - 1), fg=theme.BORDER, bg=theme.BG)
                continue
            line = doc.lines[row]
            is_cur = row == cur_row
            # gutter: [change bar] [line number] [space] [text]
            num_x = rect.x + (1 if self.git_gutter else 0)
            num = str(row + 1).rjust(self.gutter - 1 - (1 if self.git_gutter else 0))
            screen.put(num_x, y, num, fg=(theme.LINENO_CUR if is_cur else theme.LINENO),
                       bg=theme.GUTTER_BG, attr=BOLD if is_cur else 0)
            if self.git_gutter:
                mark = self.git_marks.get(row)
                if mark:
                    glyph = '▁' if mark == 'deleted' else '▌'
                    screen.put(rect.x, y, glyph, fg=theme.LINE_COLOUR[mark],
                               bg=theme.GUTTER_BG)
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
            x = 0
            for idx, ch in enumerate(line):
                nx = self._advance(ch, x)
                if nx > self.left and x < self.left + r.w:
                    fg, attr = theme.token_style(kinds[idx] or 'text')
                    bg = base_bg
                    if sel_span and sel_span[0] <= idx < sel_span[1]:
                        bg = theme.SELECTION
                    elif idx in match_map:
                        bg = theme.FIND_CUR if match_map[idx] else theme.FIND_MATCH
                    sx = r.x + x - self.left
                    if ch == '\t':
                        width = nx - x
                        screen.fill(max(r.x, sx), y, min(width, r.x2 - max(r.x, sx)), 1, bg=bg)
                    elif sx >= r.x:
                        screen.put(sx, y, ch, fg=fg, bg=bg, attr=attr, max_x=r.x2)
                x = nx
                if x - self.left > r.w:
                    break
            # selection continues past end of line (multi-line selections)
            if sel_span and sel_span[1] > len(line):
                sx = r.x + x - self.left
                if r.x <= sx < r.x2:
                    screen.fill(sx, y, 1, 1, bg=theme.SELECTION)
        self._render_scrollbar(screen, focused)
        return self.cursor_screen_pos()

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

    def _render_overview(self, screen):
        """Where the changes are, in miniature, down the scrollbar.

        One tick per screen row, so a long file shows its edits at a glance
        without scrolling to find them.
        """
        if not self.git_marks or self.sb_x is None:
            return
        r = self.text_rect
        total = max(1, len(self.doc.lines))
        rank = {'added': 1, 'modified': 2, 'deleted': 3}
        worst = {}
        for line, kind in self.git_marks.items():
            y = r.y + min(r.h - 1, int(line * r.h / total))
            if rank.get(kind, 0) >= rank.get(worst.get(y), 0):
                worst[y] = kind
        for y, kind in worst.items():
            if not (0 <= y < screen.height):
                continue
            behind = screen.cells[y][self.sb_x][2]      # track or thumb
            screen.put(self.sb_x, y, '─', fg=theme.LINE_COLOUR[kind], bg=behind)

    def cursor_screen_pos(self):
        row, col = self.doc.cursor
        r = self.text_rect
        y = r.y + row - self.top
        x = r.x + self.col_to_x(row, col) - self.left
        if r.y <= y < r.y2 and r.x <= x < r.x2:
            return (x, y)
        return None
