"""A compact VT100/xterm emulator used by the built-in terminal panel.

Enough of the protocol for interactive shells and ordinary CLI tools:
cursor motion, erases, insert/delete lines and characters, scroll regions,
SGR colour (16/256/true colour), alternate screen and scrollback.
"""

import re

from .term import DEFAULT, BOLD, DIM, ITALIC, UNDERLINE, REVERSE, char_width

BLANK = (' ', DEFAULT, DEFAULT, 0)
MAX_SCROLLBACK = 5000

_CSI_RE = re.compile(r'([\x30-\x3f]*)([\x20-\x2f]*)([\x40-\x7e])')

_BASIC = {30: 0, 31: 1, 32: 2, 33: 3, 34: 4, 35: 5, 36: 6, 37: 7}


class VT(object):
    def __init__(self, cols=80, rows=24):
        self.cols = max(1, cols)
        self.rows = max(1, rows)
        self.grid = self._blank_grid()
        self.alt_grid = None
        self.scrollback = []
        self.pushed = 0            # lines that have scrolled off into scrollback
        self.cx = 0
        self.cy = 0
        self.fg = DEFAULT
        self.bg = DEFAULT
        self.attr = 0
        self.top = 0
        self.bot = self.rows - 1
        self.saved = None
        self.cursor_visible = True
        self.autowrap = True
        self.wrap_pending = False
        self.mouse_mode = 0
        self.mouse_modes = set()        # 0 off, 1000 click, 1002 drag, 1003 any
        self.mouse_sgr = False
        self.bracketed_paste = False
        self.app_cursor_keys = False
        self.alt_screen = False
        self.title = ''
        self.pending = b''
        self.responses = []        # replies the app expects on stdin
        self.bell = False
        self._state = 'text'
        self._buf = ''

    # ---------------- geometry ----------------
    def _blank_grid(self):
        return [[BLANK] * self.cols for _ in range(self.rows)]

    def resize(self, cols, rows):
        cols = max(1, cols)
        rows = max(1, rows)
        if cols == self.cols and rows == self.rows:
            return
        old = self.grid
        self.cols, self.rows = cols, rows
        grid = self._blank_grid()
        # keep the bottom of the old screen (what the user is looking at)
        keep = min(len(old), rows)
        src = old[len(old) - keep:]
        for y in range(keep):
            row = src[y][:cols]
            row += [BLANK] * (cols - len(row))
            grid[y] = row
        self.grid = grid
        if self.alt_grid is not None:
            self.alt_grid = [[BLANK] * cols for _ in range(rows)]
        self.top, self.bot = 0, rows - 1
        self.cy = min(self.cy, rows - 1)
        self.cx = min(self.cx, cols - 1)

    # ---------------- feeding ----------------
    def feed(self, data):
        if isinstance(data, bytes):
            data = self.pending + data
            try:
                text = data.decode('utf-8')
                self.pending = b''
            except UnicodeDecodeError as e:
                text = data[:e.start].decode('utf-8', 'replace')
                # keep a short tail that may be an incomplete multi-byte char
                if len(data) - e.start <= 4:
                    self.pending = data[e.start:]
                else:
                    text += data[e.start:].decode('utf-8', 'replace')
                    self.pending = b''
        else:
            text = data
        self._buf += text
        self._parse()

    def _parse(self):
        s = self._buf
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c == '\x1b':
                consumed = self._escape(s, i)
                if consumed == 0:
                    break  # incomplete
                i += consumed
                continue
            o = ord(c)
            if o < 32 or o == 127:
                self._control(c)
                i += 1
                continue
            # fast path: run of printable characters
            j = i
            while j < n:
                cj = s[j]
                oj = ord(cj)
                if oj < 32 or oj == 127 or cj == '\x1b':
                    break
                j += 1
            self._print(s[i:j])
            i = j
        self._buf = s[i:]

    def _control(self, c):
        if c == '\n' or c == '\x0b' or c == '\x0c':
            self._linefeed()
        elif c == '\r':
            self.cx = 0
            self.wrap_pending = False
        elif c == '\x08':
            self.cx = max(0, self.cx - 1)
            self.wrap_pending = False
        elif c == '\t':
            self.cx = min(self.cols - 1, ((self.cx // 8) + 1) * 8)
        elif c == '\x07':
            self.bell = True

    @staticmethod
    def _string_end(s, start, bel):
        """Where a control string ends: ST, its one-byte form, or BEL."""
        ends = []
        for needle, width in (('\x1b\\', 2), ('\x9c', 1)):
            at = s.find(needle, start)
            if at >= 0:
                ends.append((at, width))
        if bel:
            at = s.find('\x07', start)
            if at >= 0:
                ends.append((at, 1))
        return min(ends) if ends else None

    def _escape(self, s, i):
        if i + 1 >= len(s):
            return 0
        c = s[i + 1]
        if c == '[':
            m = _CSI_RE.match(s, i + 2)
            if not m:
                return 0 if len(s) - i < 32 else 2
            self._csi(m.group(1), m.group(3))
            return m.end() - i
        if c == ']':
            # OSC ... terminated by BEL or ST
            found = self._string_end(s, i + 2, bel=True)
            if found is None:
                return 0 if len(s) - i < 512 else 2
            end, term = found
            body = s[i + 2:end]
            if body.startswith('0;') or body.startswith('2;'):
                self.title = body[2:]
            return end + term - i
        if c in 'P^_X':
            # DCS, PM, APC, SOS: a string for the terminal, ended by ST and
            # never shown. Claude Code wraps its progress reports in a DCS,
            # and tmux passes sequences through the same way; without this the
            # payload spills into the pane as text.
            found = self._string_end(s, i + 2, bel=False)
            if found is None:
                return 0 if len(s) - i < 4096 else 2
            end, term = found
            return end + term - i
        if c in '()*+':
            return 3 if i + 2 < len(s) else 0
        if c == 'M':
            self._reverse_index()
            return 2
        if c in 'DE':
            if c == 'E':
                self.cx = 0
            self._linefeed()
            return 2
        if c == '7':
            self._save_cursor()
            return 2
        if c == '8':
            self._restore_cursor()
            return 2
        if c == 'c':
            self.reset()
            return 2
        if c in '=>':
            return 2
        return 2

    # ---------------- drawing ----------------
    def _print(self, text):
        grid = self.grid
        for ch in text:
            w = char_width(ch)
            if w == 0:
                continue
            if self.wrap_pending:
                self.cx = 0
                self._linefeed()
                self.wrap_pending = False
            if self.cx + w > self.cols:
                if self.autowrap:
                    self.cx = 0
                    self._linefeed()
                else:
                    self.cx = self.cols - w
            row = grid[self.cy]
            row[self.cx] = (ch, self.fg, self.bg, self.attr)
            if w == 2 and self.cx + 1 < self.cols:
                row[self.cx + 1] = ('', self.fg, self.bg, self.attr)
            self.cx += w
            if self.cx >= self.cols:
                self.cx = self.cols - 1
                self.wrap_pending = self.autowrap

    def _linefeed(self):
        self.wrap_pending = False
        if self.cy == self.bot:
            self._scroll_up(1)
        elif self.cy < self.rows - 1:
            self.cy += 1

    def _reverse_index(self):
        if self.cy == self.top:
            self._scroll_down(1)
        elif self.cy > 0:
            self.cy -= 1

    def _scroll_up(self, n):
        for _ in range(n):
            line = self.grid.pop(self.top)
            if not self.alt_screen and self.top == 0:
                self.scrollback.append(line)
                self.pushed += 1
                if len(self.scrollback) > MAX_SCROLLBACK:
                    del self.scrollback[:len(self.scrollback) - MAX_SCROLLBACK]
            self.grid.insert(self.bot, self._blank_row())

    def _scroll_down(self, n):
        for _ in range(n):
            self.grid.pop(self.bot)
            self.grid.insert(self.top, self._blank_row())

    def _blank_row(self):
        return [(' ', DEFAULT, self.bg, 0)] * self.cols

    def _blank_cell(self):
        return (' ', DEFAULT, self.bg, 0)

    def _save_cursor(self):
        self.saved = (self.cx, self.cy, self.fg, self.bg, self.attr)

    def _restore_cursor(self):
        if self.saved:
            self.cx, self.cy, self.fg, self.bg, self.attr = self.saved

    def reset(self):
        self.grid = self._blank_grid()
        self.cx = self.cy = 0
        self.fg = self.bg = DEFAULT
        self.attr = 0
        self.top, self.bot = 0, self.rows - 1

    # ---------------- CSI ----------------
    def _csi(self, params, final):
        private = params.startswith('?')
        if private:
            params = params[1:]
        nums = []
        for p in params.split(';'):
            nums.append(int(p) if p.isdigit() else 0)
        if not nums:
            nums = [0]

        def arg(i, default=1):
            v = nums[i] if i < len(nums) else 0
            return v if v else default

        if private:
            if final in 'hl':
                self._mode(nums, final == 'h')
            return

        if final == 'm':
            self._sgr(nums)
        elif final in 'Hf':
            self.cy = min(self.rows - 1, max(0, arg(0) - 1))
            self.cx = min(self.cols - 1, max(0, arg(1) - 1))
            self.wrap_pending = False
        elif final == 'A':
            self.cy = max(self.top, self.cy - arg(0))
        elif final == 'B':
            self.cy = min(self.bot, self.cy + arg(0))
        elif final == 'C':
            self.cx = min(self.cols - 1, self.cx + arg(0))
            self.wrap_pending = False
        elif final == 'D':
            self.cx = max(0, self.cx - arg(0))
            self.wrap_pending = False
        elif final == 'E':
            self.cy = min(self.bot, self.cy + arg(0))
            self.cx = 0
        elif final == 'F':
            self.cy = max(self.top, self.cy - arg(0))
            self.cx = 0
        elif final in 'G`':
            self.cx = min(self.cols - 1, max(0, arg(0) - 1))
        elif final == 'd':
            self.cy = min(self.rows - 1, max(0, arg(0) - 1))
        elif final == 'J':
            self._erase_display(nums[0] if nums else 0)
        elif final == 'K':
            self._erase_line(nums[0] if nums else 0)
        elif final == 'L':
            self._insert_lines(arg(0))
        elif final == 'M':
            self._delete_lines(arg(0))
        elif final == 'P':
            self._delete_chars(arg(0))
        elif final == '@':
            self._insert_chars(arg(0))
        elif final == 'X':
            n = arg(0)
            row = self.grid[self.cy]
            for x in range(self.cx, min(self.cols, self.cx + n)):
                row[x] = self._blank_cell()
        elif final == 'S':
            self._scroll_up(arg(0))
        elif final == 'T':
            self._scroll_down(arg(0))
        elif final == 'r':
            top = max(0, arg(0) - 1)
            bot = min(self.rows - 1, (nums[1] - 1) if len(nums) > 1 and nums[1] else self.rows - 1)
            if top < bot:
                self.top, self.bot = top, bot
                self.cx = self.cy = 0
        elif final == 's':
            self._save_cursor()
        elif final == 'u':
            self._restore_cursor()
        elif final == 'Z':
            self.cx = max(0, ((self.cx - 1) // 8) * 8)
        elif final == 'b':
            pass
        elif final == 'n':
            if nums and nums[0] == 6:
                self.responses.append('\x1b[%d;%dR' % (self.cy + 1, self.cx + 1))
        elif final == 'c':
            self.responses.append('\x1b[?6c')

    def _mode(self, nums, on):
        for n in nums:
            if n == 25:
                self.cursor_visible = on
            elif n == 7:
                self.autowrap = on
            elif n == 1:
                self.app_cursor_keys = on
            elif n in (1049, 1047, 47):
                self._set_alt(on)
            elif n in (1000, 1002, 1003):
                # these are three ways of asking for the same thing, and a
                # program turning one off still wants the others: keep them
                # apart and report the most detailed one still asked for
                if on:
                    self.mouse_modes.add(n)
                else:
                    self.mouse_modes.discard(n)
                self.mouse_mode = max(self.mouse_modes) if self.mouse_modes else 0
            elif n == 1006:
                self.mouse_sgr = on
            elif n == 2004:
                self.bracketed_paste = on

    def _set_alt(self, on):
        if on and not self.alt_screen:
            self.alt_grid = self.grid
            self.grid = self._blank_grid()
            self.alt_screen = True
            self._save_cursor()
            self.cx = self.cy = 0
        elif not on and self.alt_screen:
            self.grid = self.alt_grid or self._blank_grid()
            self.alt_grid = None
            self.alt_screen = False
            self._restore_cursor()

    def _erase_display(self, mode):
        if mode == 0:
            self._erase_line(0)
            for y in range(self.cy + 1, self.rows):
                self.grid[y] = self._blank_row()
        elif mode == 1:
            self._erase_line(1)
            for y in range(0, self.cy):
                self.grid[y] = self._blank_row()
        else:
            for y in range(self.rows):
                self.grid[y] = self._blank_row()
            if mode == 3:
                self.scrollback = []
        self.pushed = 0            # lines that have scrolled off into scrollback

    def _erase_line(self, mode):
        row = self.grid[self.cy]
        blank = self._blank_cell()
        if mode == 0:
            for x in range(self.cx, self.cols):
                row[x] = blank
        elif mode == 1:
            for x in range(0, min(self.cx + 1, self.cols)):
                row[x] = blank
        else:
            self.grid[self.cy] = self._blank_row()

    def _insert_lines(self, n):
        if not (self.top <= self.cy <= self.bot):
            return
        for _ in range(n):
            self.grid.pop(self.bot)
            self.grid.insert(self.cy, self._blank_row())

    def _delete_lines(self, n):
        if not (self.top <= self.cy <= self.bot):
            return
        for _ in range(n):
            self.grid.pop(self.cy)
            self.grid.insert(self.bot, self._blank_row())

    def _delete_chars(self, n):
        row = self.grid[self.cy]
        del row[self.cx:self.cx + n]
        row.extend([self._blank_cell()] * (self.cols - len(row)))

    def _insert_chars(self, n):
        row = self.grid[self.cy]
        for _ in range(n):
            row.insert(self.cx, self._blank_cell())
        del row[self.cols:]

    def _sgr(self, nums):
        i = 0
        if not nums:
            nums = [0]
        while i < len(nums):
            n = nums[i]
            if n == 0:
                self.fg = self.bg = DEFAULT
                self.attr = 0
            elif n == 1:
                self.attr |= BOLD
            elif n == 2:
                self.attr |= DIM
            elif n == 3:
                self.attr |= ITALIC
            elif n == 4:
                self.attr |= UNDERLINE
            elif n == 7:
                self.attr |= REVERSE
            elif n == 22:
                self.attr &= ~(BOLD | DIM)
            elif n == 23:
                self.attr &= ~ITALIC
            elif n == 24:
                self.attr &= ~UNDERLINE
            elif n == 27:
                self.attr &= ~REVERSE
            elif 30 <= n <= 37:
                self.fg = n - 30
            elif n == 39:
                self.fg = DEFAULT
            elif 40 <= n <= 47:
                self.bg = n - 40
            elif n == 49:
                self.bg = DEFAULT
            elif 90 <= n <= 97:
                self.fg = n - 90 + 8
            elif 100 <= n <= 107:
                self.bg = n - 100 + 8
            elif n in (38, 48):
                if i + 1 < len(nums) and nums[i + 1] == 5 and i + 2 < len(nums):
                    val = nums[i + 2]
                    i += 2
                elif i + 1 < len(nums) and nums[i + 1] == 2 and i + 4 < len(nums):
                    val = 0x1000000 | (nums[i + 2] << 16) | (nums[i + 3] << 8) | nums[i + 4]
                    i += 4
                else:
                    i += 1
                    continue
                if n == 38:
                    self.fg = val
                else:
                    self.bg = val
            i += 1

    # ---------------- viewing ----------------
    def total_lines(self):
        return len(self.scrollback) + self.rows

    def view(self, scroll_offset=0):
        """Rows to display; scroll_offset counts lines back into scrollback."""
        if scroll_offset <= 0 or self.alt_screen:
            return self.grid
        off = min(scroll_offset, len(self.scrollback))
        take = self.scrollback[len(self.scrollback) - off:]
        rows = take + self.grid[:self.rows - len(take)]
        return rows[:self.rows]

    def text_lines(self):
        """Plain text of scrollback + screen (used for copy / tests)."""
        out = []
        for row in self.scrollback + self.grid:
            out.append(''.join(c[0] for c in row).rstrip())
        return out
