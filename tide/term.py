"""Raw terminal control and a diffing screen buffer.

Everything the IDE draws goes into a Screen (a grid of cells).  Each frame we
diff against the previously flushed grid and emit only the runs that changed,
which keeps redraws flicker-free and cheap enough for pure Python.
"""

import os
import sys
import termios
import tty
import unicodedata

# Cell attribute bits.
BOLD = 1
DIM = 2
ITALIC = 4
UNDERLINE = 8
REVERSE = 16
STRIKE = 32

DEFAULT = -1  # "terminal default" colour

# A cell is a tuple: (char, fg, bg, attr).  A char of '' marks the second
# column of a double-width character and is never emitted on its own.
BLANK = (' ', DEFAULT, DEFAULT, 0)
CONT = ('', DEFAULT, DEFAULT, 0)

_WIDE = ('W', 'F')


def char_width(ch):
    """Columns occupied by a single character."""
    o = ord(ch)
    if o < 32 or 0x7F <= o < 0xA0:
        return 0
    if o < 0x1100:
        return 1
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in _WIDE else 1


def text_width(s):
    return sum(char_width(c) for c in s)


def _sgr(fg, bg, attr):
    parts = ['0']
    if attr & BOLD:
        parts.append('1')
    if attr & DIM:
        parts.append('2')
    if attr & ITALIC:
        parts.append('3')
    if attr & UNDERLINE:
        parts.append('4')
    if attr & REVERSE:
        parts.append('7')
    if attr & STRIKE:
        parts.append('9')
    if fg == DEFAULT:
        parts.append('39')
    elif fg < 256:
        parts.append('38;5;%d' % fg)
    else:  # packed 24-bit as 0x1000000 | rgb
        rgb = fg & 0xFFFFFF
        parts.append('38;2;%d;%d;%d' % (rgb >> 16, (rgb >> 8) & 255, rgb & 255))
    if bg == DEFAULT:
        parts.append('49')
    elif bg < 256:
        parts.append('48;5;%d' % bg)
    else:
        rgb = bg & 0xFFFFFF
        parts.append('48;2;%d;%d;%d' % (rgb >> 16, (rgb >> 8) & 255, rgb & 255))
    return '\x1b[' + ';'.join(parts) + 'm'


class Screen(object):
    """An addressable grid of cells with a diffing flush."""

    def __init__(self, width, height):
        self.width = 0
        self.height = 0
        self.resize(width, height)

    def resize(self, width, height):
        self.width = max(1, width)
        self.height = max(1, height)
        self.cells = [[BLANK] * self.width for _ in range(self.height)]
        self.prev = None  # force a full repaint

    def clear(self, bg=DEFAULT):
        blank = (' ', DEFAULT, bg, 0)
        for row in self.cells:
            for x in range(self.width):
                row[x] = blank

    def fill(self, x, y, w, h, bg=DEFAULT, ch=' ', fg=DEFAULT, attr=0):
        cell = (ch, fg, bg, attr)
        for yy in range(max(0, y), min(self.height, y + h)):
            row = self.cells[yy]
            for xx in range(max(0, x), min(self.width, x + w)):
                row[xx] = cell

    def put(self, x, y, text, fg=DEFAULT, bg=DEFAULT, attr=0, max_x=None, min_x=None):
        """Draw text at (x, y), clipped to [min_x, max_x); returns the x after it."""
        if y < 0 or y >= self.height:
            return x
        limit = self.width if max_x is None else min(self.width, max_x)
        left = 0 if min_x is None else max(0, min_x)
        row = self.cells[y]
        for ch in text:
            if x >= limit:
                break
            w = char_width(ch)
            if w == 0:
                continue
            if x >= left:
                if w == 2 and x + 1 >= limit:
                    row[x] = (' ', fg, bg, attr)  # no room for the wide half
                    x += 1
                    break
                row[x] = (ch, fg, bg, attr)
                if w == 2:
                    row[x + 1] = ('', fg, bg, attr)
            x += w
        return x

    def set_cell(self, x, y, cell):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cells[y][x] = cell

    def flush(self, out, cursor=None):
        """Emit the minimal escape sequences to bring the terminal up to date."""
        buf = ['\x1b[?25l']
        prev = self.prev
        full = prev is None
        cur_fg = cur_bg = None
        cur_attr = None
        for y in range(self.height):
            row = self.cells[y]
            prow = None if full else prev[y]
            if not full and prow == row:
                continue
            if full:
                first, last = 0, self.width - 1
            else:
                first = 0
                while first < self.width and row[first] == prow[first]:
                    first += 1
                if first >= self.width:
                    continue
                last = self.width - 1
                while last > first and row[last] == prow[last]:
                    last -= 1
            if row[first][0] == '' and first > 0:
                first -= 1  # never start mid double-width char
            buf.append('\x1b[%d;%dH' % (y + 1, first + 1))
            cur_fg = cur_bg = cur_attr = None
            x = first
            while x <= last:
                ch, fg, bg, attr = row[x]
                if ch == '':
                    x += 1
                    continue
                if fg != cur_fg or bg != cur_bg or attr != cur_attr:
                    buf.append(_sgr(fg, bg, attr))
                    cur_fg, cur_bg, cur_attr = fg, bg, attr
                buf.append(ch)
                x += 1
            buf.append('\x1b[0m')
        if cursor is not None:
            cx, cy = cursor
            if 0 <= cx < self.width and 0 <= cy < self.height:
                buf.append('\x1b[%d;%dH\x1b[?25h' % (cy + 1, cx + 1))
        self.prev = [row[:] for row in self.cells]
        data = ''.join(buf)
        out.write(data)
        out.flush()


class RawTerminal(object):
    """Puts the real terminal into raw mode with mouse + paste reporting."""

    def __init__(self, fd=None, out=None):
        self.fd = fd if fd is not None else sys.stdin.fileno()
        self.out = out or sys.stdout
        self.saved = None

    def size(self):
        try:
            cols, rows = os.get_terminal_size(self.out.fileno())
        except Exception:
            cols, rows = 80, 24
        return cols, rows

    def __enter__(self):
        try:
            self.saved = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        except termios.error:
            self.saved = None
        # alt screen, hide cursor, SGR mouse (press/drag/release), bracketed paste
        # 1003l: any-motion reporting is never wanted, and an older tide or
        # another program may have left it on
        self.out.write('\x1b[?1049h\x1b[?25l\x1b[?1003l\x1b[?1000h'
                       '\x1b[?1002h\x1b[?1006h\x1b[?2004h')
        self.out.flush()
        return self

    def __exit__(self, *exc):
        self.out.write('\x1b[?2004l\x1b[?1006l\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[0m\x1b[?25h\x1b[?1049l')
        self.out.flush()
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        return False


class Rect(object):
    __slots__ = ('x', 'y', 'w', 'h')

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, max(0, w), max(0, h)

    @property
    def x2(self):
        return self.x + self.w

    @property
    def y2(self):
        return self.y + self.h

    def contains(self, px, py):
        return self.x <= px < self.x2 and self.y <= py < self.y2

    def __repr__(self):
        return 'Rect(%d,%d,%d,%d)' % (self.x, self.y, self.w, self.h)
