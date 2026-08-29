"""Decoding of terminal input bytes into key, mouse and paste events."""

import re

CTRL = 1
ALT = 2
SHIFT = 4


class Key(object):
    __slots__ = ('name', 'char', 'mods')

    def __init__(self, name, char='', mods=0):
        self.name = name      # 'char', 'enter', 'up', 'f5', ...
        self.char = char      # printable character when name == 'char'
        self.mods = mods

    @property
    def ctrl(self):
        return bool(self.mods & CTRL)

    @property
    def alt(self):
        return bool(self.mods & ALT)

    @property
    def shift(self):
        return bool(self.mods & SHIFT)

    def combo(self):
        """Canonical name like 'ctrl+shift+left' or 'ctrl+s'."""
        parts = []
        if self.mods & CTRL:
            parts.append('ctrl')
        if self.mods & ALT:
            parts.append('alt')
        if self.mods & SHIFT:
            parts.append('shift')
        parts.append(self.char.lower() if self.name == 'char' else self.name)
        return '+'.join(parts)

    def __repr__(self):
        return '<Key %s>' % self.combo()


class Mouse(object):
    __slots__ = ('kind', 'x', 'y', 'button', 'mods')

    def __init__(self, kind, x, y, button=0, mods=0):
        self.kind = kind      # press | release | drag | wheel_up | wheel_down
        self.x = x
        self.y = y
        self.button = button  # 0 left, 1 middle, 2 right
        self.mods = mods

    def __repr__(self):
        return '<Mouse %s %d,%d b%d>' % (self.kind, self.x, self.y, self.button)


class Paste(object):
    __slots__ = ('text',)

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return '<Paste %r>' % self.text[:20]


_SPECIAL = {
    'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left',
    'H': 'home', 'F': 'end', 'E': 'begin',
    'P': 'f1', 'Q': 'f2', 'R': 'f3', 'S': 'f4',
    'Z': 'backtab',
}
_TILDE = {
    1: 'home', 2: 'insert', 3: 'delete', 4: 'end', 5: 'pageup', 6: 'pagedown',
    7: 'home', 8: 'end', 11: 'f1', 12: 'f2', 13: 'f3', 14: 'f4', 15: 'f5',
    17: 'f6', 18: 'f7', 19: 'f8', 20: 'f9', 21: 'f10', 23: 'f11', 24: 'f12',
}
# control codes that stand for a symbol rather than a letter
_CTRL_SYMBOL = {28: '\\', 29: ']', 30: '6', 31: '/'}

_MOUSE_RE = re.compile(r'^\x1b\[<(\d+);(\d+);(\d+)([Mm])')
_CSI_RE = re.compile(r'^\x1b\[([\x30-\x3f]*)([\x20-\x2f]*)([\x40-\x7e])')
_PASTE_START = '\x1b[200~'
_PASTE_END = '\x1b[201~'


def _mods_from_param(p):
    p = max(1, p) - 1
    mods = 0
    if p & 1:
        mods |= SHIFT
    if p & 2:
        mods |= ALT
    if p & 4:
        mods |= CTRL
    return mods


class Decoder(object):
    """Incremental decoder: feed it bytes, get back a list of events."""

    def __init__(self):
        self.buf = ''
        self.in_paste = False
        self.paste = []

    def feed(self, data):
        if isinstance(data, bytes):
            data = data.decode('utf-8', 'replace')
        self.buf += data
        events = []
        while self.buf:
            if self.in_paste:
                idx = self.buf.find(_PASTE_END)
                if idx < 0:
                    # keep a tail in case the terminator is split across reads
                    keep = len(_PASTE_END) - 1
                    if len(self.buf) > keep:
                        self.paste.append(self.buf[:-keep])
                        self.buf = self.buf[-keep:]
                    break
                self.paste.append(self.buf[:idx])
                self.buf = self.buf[idx + len(_PASTE_END):]
                self.in_paste = False
                events.append(Paste(''.join(self.paste)))
                self.paste = []
                continue
            ev, consumed = self._one()
            if consumed == 0:
                break  # incomplete sequence, wait for more bytes
            self.buf = self.buf[consumed:]
            if ev is not None:
                events.append(ev)
        return events

    def _one(self):
        b = self.buf
        c = b[0]
        if c != '\x1b':
            o = ord(c)
            if o == 13:
                return Key('enter'), 1
            if o == 9:
                return Key('tab'), 1
            if o == 127:
                return Key('backspace'), 1
            if o == 8:
                return Key('backspace', mods=CTRL), 1
            if o == 0:
                return Key('char', ' ', CTRL), 1
            if o in _CTRL_SYMBOL:
                return Key('char', _CTRL_SYMBOL[o], CTRL), 1
            if o < 32:
                return Key('char', chr(o + 96), CTRL), 1
            return Key('char', c), 1

        # ESC ...
        if len(b) == 1:
            return Key('escape'), 1
        n = b[1]
        if n == '[':
            if b.startswith(_PASTE_START):
                self.in_paste = True
                return None, len(_PASTE_START)
            m = _MOUSE_RE.match(b)
            if m:
                code, x, y, updown = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                mods = 0
                if code & 4:
                    mods |= SHIFT
                if code & 8:
                    mods |= ALT
                if code & 16:
                    mods |= CTRL
                if code & 64:
                    # 64/65 are the vertical wheel, 66/67 the horizontal one
                    kind = ('wheel_up', 'wheel_down', 'wheel_left',
                            'wheel_right')[code & 3]
                    button = 0
                elif code & 32:
                    # 35 is motion with no button held, which the terminal
                    # only reports while something has asked to hear it
                    kind = 'move' if (code & 3) == 3 else 'drag'
                    button = code & 3
                elif updown == 'm':
                    kind, button = 'release', code & 3
                else:
                    kind, button = 'press', code & 3
                return Mouse(kind, x - 1, y - 1, button, mods), m.end()
            m = _CSI_RE.match(b)
            if not m:
                if len(b) > 24:  # junk, drop the ESC
                    return Key('escape'), 1
                return None, 0
            params, _inter, final = m.group(1), m.group(2), m.group(3)
            nums = [int(p) if p.isdigit() else 0 for p in params.split(';')] if params else []
            mods = _mods_from_param(nums[1]) if len(nums) > 1 else 0
            if final == '~':
                name = _TILDE.get(nums[0] if nums else 0)
                if name:
                    return Key(name, mods=mods), m.end()
                return None, m.end()
            name = _SPECIAL.get(final)
            if name == 'backtab':
                return Key('tab', mods=SHIFT), m.end()
            if name:
                return Key(name, mods=mods), m.end()
            return None, m.end()
        if n == 'O' and len(b) >= 3:
            name = _SPECIAL.get(b[2])
            if name:
                return Key(name), 3
            return None, 3
        if n == '\x1b':
            return Key('escape'), 1
        # ESC <char> is Alt+<char>
        o = ord(n)
        if o == 127:
            return Key('backspace', mods=ALT), 2
        if o < 32:
            return Key('char', chr(o + 96), CTRL | ALT), 2
        return Key('char', n, ALT), 2
