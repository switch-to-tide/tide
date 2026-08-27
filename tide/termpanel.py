"""The built-in terminal panel: a real shell rendered inside a pane."""

import os

from . import clipboard, theme
from .keys import CTRL, SHIFT
from .shell import Shell, key_to_bytes, mouse_to_bytes
from .term import BOLD, DEFAULT, Rect
from .vt import VT


class TerminalPanel(object):
    """One shell session in a pane.

    Used both for the small panel docked at the bottom (which draws its own
    header bar and doubles as the splitter) and for the full-size sessions
    that take over the editor area, where the tab bar names them instead.
    """

    def __init__(self, app, cwd=None, header=True, title='TERMINAL'):
        self.app = app
        self.cwd = cwd or os.getcwd()
        self.header = header
        self.title = title
        self.shell = None
        self.vt = VT(80, 10)
        self.rect = Rect(0, 0, 1, 1)
        self.view_rect = Rect(0, 0, 1, 1)
        self.scroll = 0
        self.sel_start = None      # (col, absolute_line)
        self.sel_end = None
        self.dragging = False

    # ---------------- lifecycle ----------------
    def start(self, cols=None, rows=None):
        if self.shell and not self.shell.exited:
            return
        cols = cols or max(20, self.view_rect.w or 80)
        rows = rows or max(2, self.view_rect.h or 10)
        self.vt = VT(cols, rows)
        self.shell = Shell(cols, rows, cwd=self.cwd)

    def stop(self):
        if self.shell:
            self.shell.close()
            self.shell = None

    @property
    def fd(self):
        return self.shell.fd if self.shell and not self.shell.exited else None

    def pump(self):
        """Read whatever the shell produced; returns True if the view changed."""
        if not self.shell:
            return False
        data = self.shell.read()
        if data:
            before = self.vt.pushed
            self.vt.feed(data)
            if self.vt.responses:
                for r in self.vt.responses:
                    self.shell.write(r)
                self.vt.responses = []
            if self.scroll:
                # keep looking at the same lines while output arrives underneath
                pushed = self.vt.pushed - before
                self.scroll = min(len(self.vt.scrollback), self.scroll + pushed)
            return True
        if self.shell.exited:
            self.shell.poll()
            return True
        return False

    def resize(self, cols, rows):
        cols, rows = max(20, cols), max(2, rows)
        if self.vt.cols == cols and self.vt.rows == rows:
            return
        self.vt.resize(cols, rows)
        if self.shell and not self.shell.exited:
            self.shell.resize(cols, rows)

    def send(self, data):
        if not self.shell or self.shell.exited:
            self.start()
        self.shell.write(data)
        self.scroll = 0

    def run_command(self, cmd):
        self.send(cmd.rstrip('\n') + '\n')

    # ---------------- input ----------------
    def on_key(self, key):
        if self.shell is None or self.shell.exited:
            if key.name == 'enter':
                self.start()
                return True
            return True
        self.sel_start = self.sel_end = None
        data = key_to_bytes(key, self.vt.app_cursor_keys)
        if data:
            self.send(data)
        return True

    def on_paste(self, text):
        if self.vt.bracketed_paste:
            self.send(b'\x1b[200~' + text.encode('utf-8') + b'\x1b[201~')
        else:
            self.send(text.encode('utf-8'))

    def on_mouse(self, ev):
        r = self.view_rect
        if ev.kind in ('wheel_left', 'wheel_right'):
            if self.vt.mouse_mode:
                self._forward_mouse(ev)
            return True
        if ev.kind in ('wheel_up', 'wheel_down'):
            if self.vt.mouse_mode:
                self._forward_mouse(ev)
                return True
            if self.vt.alt_screen:
                # emulate arrow keys for pagers that do not track the mouse
                self.send(b'\x1b[A' * 3 if ev.kind == 'wheel_up' else b'\x1b[B' * 3)
                return True
            if ev.kind == 'wheel_up':
                self.scroll = min(len(self.vt.scrollback), self.scroll + 3)
            else:
                self.scroll = max(0, self.scroll - 3)
            return True
        if self.vt.mouse_mode and ev.kind in ('press', 'drag', 'release'):
            self._forward_mouse(ev)
            return True
        col = max(0, min(self.vt.cols - 1, ev.x - r.x))
        line = self._abs_line(ev.y)
        if ev.kind == 'press':
            self.sel_start = (col, line)
            self.sel_end = (col, line)
            self.dragging = True
            return True
        if ev.kind == 'drag' and self.dragging:
            self.sel_end = (col, line)
            return True
        if ev.kind == 'release' and self.dragging:
            self.dragging = False
            self.sel_end = (col, line)
            text = self.selected_text()
            if text.strip():
                clipboard.copy(text)
                self.app.status('Copied %d chars from terminal' % len(text))
            else:
                self.sel_start = self.sel_end = None
            return True
        return False

    def _forward_mouse(self, ev):
        r = self.view_rect
        local = type(ev)(ev.kind, max(0, ev.x - r.x), max(0, ev.y - r.y), ev.button, ev.mods)
        data = mouse_to_bytes(local, self.vt.mouse_mode, self.vt.mouse_sgr)
        if data:
            self.send(data)

    def _abs_line(self, y):
        """Screen row -> index into scrollback + screen."""
        r = self.view_rect
        first = len(self.vt.scrollback) - self.scroll
        return max(0, first + (y - r.y))

    def selected_text(self):
        if not self.sel_start or not self.sel_end:
            return ''
        a, b = sorted([self.sel_start, self.sel_end], key=lambda p: (p[1], p[0]))
        raw = [''.join(c[0] for c in row) for row in (self.vt.scrollback + self.vt.grid)]
        out = []
        for ln in range(a[1], b[1] + 1):
            if ln >= len(raw):
                break
            text = raw[ln]
            s = a[0] if ln == a[1] else 0
            e = (b[0] + 1) if ln == b[1] else len(text)
            out.append(text[s:e].rstrip())
        return '\n'.join(out)

    # ---------------- painting ----------------
    def _render_header(self, screen, rect, focused):
        y = rect.y
        screen.fill(rect.x, y, rect.w, 1, bg=theme.PANEL_ALT)
        label = ' %s ' % self.title
        screen.put(rect.x, y, label, fg=theme.FG if focused else theme.FG_DIM,
                   bg=theme.PANEL_ALT, attr=BOLD)
        info = os.path.basename(os.environ.get('SHELL', 'sh'))
        if self.shell and self.shell.exited:
            info = 'exited - press Enter to restart'
        elif self.scroll:
            info = 'scrolled %d lines back' % self.scroll
        screen.put(rect.x + len(label), y, info[:max(0, rect.w - len(label) - 12)],
                   fg=theme.FG_DIM, bg=theme.PANEL_ALT)
        hint = 'ctrl+j hide '
        if rect.w > len(label) + len(hint) + 2:
            screen.put(rect.x2 - len(hint), y, hint, fg=theme.FG_DIM, bg=theme.PANEL_ALT)

    def render(self, screen, rect, focused):
        self.rect = rect
        self.view_rect = Rect(rect.x, rect.y + 1, rect.w, rect.h - 1) if self.header else rect
        r = self.view_rect
        self.resize(r.w, r.h)
        if self.shell is None:
            self.start(r.w, r.h)
        if self.header:
            self._render_header(screen, rect, focused)

        screen.fill(r.x, r.y, r.w, r.h, bg=theme.TERM_BG)
        rows = self.vt.view(self.scroll)
        sel = None
        if self.sel_start and self.sel_end:
            sel = sorted([self.sel_start, self.sel_end], key=lambda p: (p[1], p[0]))
        first_line = len(self.vt.scrollback) - self.scroll
        for y in range(min(r.h, len(rows))):
            row = rows[y]
            abs_line = first_line + y
            for x in range(min(r.w, len(row))):
                ch, fg, bg, attr = row[x]
                if ch == '':
                    continue
                if fg == DEFAULT:
                    fg = theme.TERM_FG
                if bg == DEFAULT:
                    bg = theme.TERM_BG
                if sel and self._in_sel(sel, x, abs_line):
                    bg = theme.SELECTION
                screen.set_cell(r.x + x, r.y + y, (ch, fg, bg, attr))
        if focused and not self.scroll and self.vt.cursor_visible:
            cx, cy = r.x + self.vt.cx, r.y + self.vt.cy
            if r.contains(cx, cy):
                return (cx, cy)
        return None

    @staticmethod
    def _in_sel(sel, x, line):
        (sx, sl), (ex, el) = sel
        if line < sl or line > el:
            return False
        if sl == el:
            return sx <= x <= ex
        if line == sl:
            return x >= sx
        if line == el:
            return x <= ex
        return True
