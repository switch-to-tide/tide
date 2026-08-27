"""A shell running on a pseudo-terminal, plus key -> byte translation."""

import fcntl
import os
import pty
import signal
import struct
import termios

from . import keys as K

_MOD_PARAM = {0: '', K.SHIFT: ';2', K.ALT: ';3', K.ALT | K.SHIFT: ';4',
              K.CTRL: ';5', K.CTRL | K.SHIFT: ';6', K.CTRL | K.ALT: ';7',
              K.CTRL | K.ALT | K.SHIFT: ';8'}

_ARROW = {'up': 'A', 'down': 'B', 'right': 'C', 'left': 'D',
          'home': 'H', 'end': 'F'}
_TILDE = {'insert': '2', 'delete': '3', 'pageup': '5', 'pagedown': '6',
          'f5': '15', 'f6': '17', 'f7': '18', 'f8': '19', 'f9': '20',
          'f10': '21', 'f11': '23', 'f12': '24'}
_SS3 = {'f1': 'P', 'f2': 'Q', 'f3': 'R', 'f4': 'S'}


def key_to_bytes(key, app_cursor=False):
    """Translate a decoded Key back into what a real terminal would send."""
    name = key.name
    mods = key.mods
    if name == 'char':
        ch = key.char
        if mods & K.CTRL:
            low = ch.lower()
            if low == ' ':
                out = '\x00'
            elif 'a' <= low <= 'z':
                out = chr(ord(low) - 96)
            elif low in '[\\]^_':
                out = chr(ord(low) - 64)
            elif low == '/':
                out = '\x1f'
            else:
                out = ch
        else:
            out = ch
        if mods & K.ALT:
            out = '\x1b' + out
        return out.encode('utf-8')
    if name == 'enter':
        return b'\r'
    if name == 'tab':
        return b'\x1b[Z' if mods & K.SHIFT else b'\t'
    if name == 'backspace':
        if mods & K.CTRL:
            return b'\x17'
        if mods & K.ALT:
            return b'\x1b\x7f'
        return b'\x7f'
    if name == 'escape':
        return b'\x1b'
    if name in _ARROW:
        letter = _ARROW[name]
        if mods:
            return ('\x1b[1%s%s' % (_MOD_PARAM.get(mods, ''), letter)).encode()
        if app_cursor and name in ('up', 'down', 'left', 'right'):
            return ('\x1bO' + letter).encode()
        return ('\x1b[' + letter).encode()
    if name in _TILDE:
        return ('\x1b[%s%s~' % (_TILDE[name], _MOD_PARAM.get(mods, ''))).encode()
    if name in _SS3:
        return ('\x1bO' + _SS3[name]).encode()
    return b''


def mouse_to_bytes(ev, mode, sgr):
    """Encode a mouse event for an app that asked for mouse reporting."""
    if not mode:
        return b''
    if ev.kind == 'drag' and mode < 1002:
        return b''
    if ev.kind.startswith('wheel_'):
        code = 64 + ('up', 'down', 'left', 'right').index(ev.kind[6:])
    else:
        code = ev.button
        if ev.kind == 'drag':
            code += 32
    if ev.mods & K.SHIFT:
        code += 4
    if ev.mods & K.ALT:
        code += 8
    if ev.mods & K.CTRL:
        code += 16
    x, y = ev.x + 1, ev.y + 1
    if sgr:
        return ('\x1b[<%d;%d;%d%s' % (code, x, y, 'm' if ev.kind == 'release' else 'M')).encode()
    if ev.kind == 'release':
        code = 3
    return ('\x1b[M%c%c%c' % (chr(32 + code), chr(32 + x), chr(32 + y))).encode('latin-1', 'replace')


class Shell(object):
    """Fork a shell attached to a pty."""

    def __init__(self, cols=80, rows=24, cwd=None, argv=None):
        self.cols = cols
        self.rows = rows
        self.exited = False
        self.exit_code = None
        env_shell = os.environ.get('SHELL') or '/bin/sh'
        argv = argv or [env_shell]
        pid, fd = pty.fork()
        if pid == 0:  # child
            try:
                if cwd:
                    os.chdir(cwd)
                os.environ['TERM'] = 'xterm-256color'
                os.environ['COLORTERM'] = 'truecolor'
                os.environ['TIDE_TERMINAL'] = '1'
                os.environ.pop('LINES', None)
                os.environ.pop('COLUMNS', None)
                os.execvp(argv[0], argv)
            except Exception:
                os._exit(127)
        self.pid = pid
        self.fd = fd
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.resize(cols, rows)

    def resize(self, cols, rows):
        self.cols, self.rows = max(1, cols), max(1, rows)
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                        struct.pack('HHHH', self.rows, self.cols, 0, 0))
        except OSError:
            pass

    def read(self, size=65536):
        try:
            data = os.read(self.fd, size)
        except (OSError, IOError):
            self.exited = True
            return b''
        if not data:
            self.exited = True
        return data

    def write(self, data):
        if self.exited:
            return
        if isinstance(data, str):
            data = data.encode('utf-8')
        try:
            while data:
                n = os.write(self.fd, data)
                data = data[n:]
        except (OSError, IOError):
            self.exited = True

    def poll(self):
        """Reap the child if it has finished."""
        if self.exit_code is not None:
            return self.exit_code
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except OSError:
            self.exited = True
            self.exit_code = -1
            return self.exit_code
        if pid == self.pid:
            self.exited = True
            self.exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
        return self.exit_code

    def close(self):
        try:
            os.kill(self.pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.exited = True
