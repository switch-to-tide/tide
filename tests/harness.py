"""Drive the IDE inside a pty and read back what it painted.

The IDE's own VT emulator doubles as the test's screen scraper, so assertions
can look at real rendered characters and colours.
"""

import os
import pty
import select
import signal
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tide.vt import VT  # noqa: E402

ESC = '\x1b'


class Session(object):
    def __init__(self, args=(), cols=100, rows=30, cwd=None, env=None):
        self.cols, self.rows = cols, rows
        # never let a test write to the real ~/.config/tide/settings.json
        env = dict(env or {})
        self._config_home = None
        if 'TIDE_CONFIG_HOME' not in env:
            import tempfile
            self._config_home = tempfile.mkdtemp(prefix='tide-cfg-')
            env['TIDE_CONFIG_HOME'] = self._config_home
        self.vt = VT(cols, rows)
        argv = [sys.executable, os.path.join(ROOT, 'main.py')] + list(args)
        pid, fd = pty.fork()
        if pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            os.environ['SHELL'] = '/bin/sh'
            os.environ['PS1'] = '$ '
            os.environ['TIDE_NO_SYSTEM_CLIPBOARD'] = '1'
            os.environ.update(env or {})
            if cwd:
                os.chdir(cwd)
            os.execv(argv[0], argv)
        self.pid, self.fd = pid, fd
        import fcntl
        import struct
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        self.pump(0.8)
        self.wait_for_paint()

    def wait_for_paint(self, timeout=5.0):
        """Wait for a complete first frame.

        A busy machine can leave the initial pump holding half of one, and a
        test that looks at the screen then sees rows that are not there yet.
        """
        end = time.time() + timeout
        while time.time() < end:
            if any(line.strip() for line in self.text()):
                self.pump(0.3, quiet=0.15)      # let the rest of the frame land
                return True
            self.pump(0.3)
        return False

    # -- io
    def pump(self, timeout=0.35, quiet=0.08):
        """Read output until nothing new arrives for `quiet` seconds."""
        end = time.time() + timeout
        last = time.time()
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.02)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.vt.feed(data)
                last = time.time()
            elif time.time() - last > quiet:
                break
        return self.text()

    def send(self, data, settle=0.25):
        if isinstance(data, str):
            data = data.encode('utf-8')
        os.write(self.fd, data)
        self.pump(settle)

    def type(self, text, settle=0.25):
        self.send(text, settle)

    def key(self, seq, settle=0.25):
        self.send(seq, settle)

    def click(self, x, y, button=0, count=1, settle=0.25):
        for _ in range(count):
            self.send('%s[<%d;%d;%dM' % (ESC, button, x + 1, y + 1), 0.05)
            self.send('%s[<%d;%d;%dm' % (ESC, button, x + 1, y + 1), settle)

    def drag(self, x1, y1, x2, y2, settle=0.3):
        self.send('%s[<0;%d;%dM' % (ESC, x1 + 1, y1 + 1), 0.05)
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for i in range(1, steps + 1):
            x = x1 + (x2 - x1) * i // steps
            y = y1 + (y2 - y1) * i // steps
            self.send('%s[<32;%d;%dM' % (ESC, x + 1, y + 1), 0.02)
        self.send('%s[<0;%d;%dm' % (ESC, x2 + 1, y2 + 1), settle)

    def hwheel(self, x, y, right=True, times=1):
        """A sideways wheel, as terminals report it (buttons 6 and 7)."""
        code = 67 if right else 66
        for _ in range(times):
            self.send('%s[<%d;%d;%dM' % (ESC, code, x + 1, y + 1), 0.05)
        self.pump(0.2)

    def wheel(self, x, y, up=True, times=1):
        code = 64 if up else 65
        for _ in range(times):
            self.send('%s[<%d;%d;%dM' % (ESC, code, x + 1, y + 1), 0.05)
        self.pump(0.2)

    # -- screen
    def text(self):
        return [''.join(c[0] or ' ' for c in row).rstrip() for row in self.vt.grid]

    def screen(self):
        return '\n'.join(self.text())

    def line(self, y):
        return self.text()[y]

    def cell(self, x, y):
        return self.vt.grid[y][x]

    # -- header rows (the view switch sits above the tab row)
    SWITCH_ROW = 0
    TAB_ROW = 1

    def tab_pos(self, label):
        """x of a tab label in the tab row (rightmost match clears the sidebar)."""
        return self.line(self.TAB_ROW).rfind(label)

    def click_tab(self, label, button=0):
        x = self.tab_pos(label)
        assert x >= 0, 'no tab %r in %r' % (label, self.line(self.TAB_ROW))
        self.click(x + 1, self.TAB_ROW, button=button)

    def click_tab_close(self, label):
        row = self.line(self.TAB_ROW)
        x = row.rfind(label)
        assert x >= 0, 'no tab %r in %r' % (label, row)
        self.click(row.index('x', x + len(label)), self.TAB_ROW)

    def click_plus(self):
        row = self.line(self.TAB_ROW)
        self.click(row.rindex('+'), self.TAB_ROW)

    def click_switch(self, label):
        x = self.line(self.SWITCH_ROW).rfind(label)
        assert x >= 0, 'no switch %r in %r' % (label, self.line(self.SWITCH_ROW))
        self.click(x + 1, self.SWITCH_ROW)

    def find(self, needle):
        """-> (x, y) of the first occurrence on screen, else None."""
        for y, line in enumerate(self.text()):
            x = line.find(needle)
            if x >= 0:
                return (x, y)
        return None

    def wait_for(self, needle, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.screen():
                return True
            self.pump(0.15)
        return False

    # -- abrupt endings
    def send_raw(self, data):
        """Write straight to the pty without waiting for the app to react."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        os.write(self.fd, data)

    def signal(self, sig):
        os.kill(self.pid, sig)

    def close_master(self):
        """Destroy the terminal: the app's stdin hits EOF."""
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = -1

    def wait_exit(self, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                pid, _status = os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                return True
            if pid == self.pid:
                self.pid = -1
                return True
            if self.fd >= 0:
                try:
                    r, _, _ = select.select([self.fd], [], [], 0.05)
                    if r:
                        data = os.read(self.fd, 65536)
                        if data:
                            self.vt.feed(data)
                except OSError:
                    pass
            else:
                time.sleep(0.05)
        return False

    def alive(self):
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except OSError:
            return False

    def close(self):
        if self.pid > 0:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        if self.pid > 0:
            try:
                os.waitpid(self.pid, 0)
            except OSError:
                pass
            self.pid = -1
        if self._config_home:
            import shutil
            shutil.rmtree(self._config_home, ignore_errors=True)
            self._config_home = None


# common key sequences
CTRL = lambda c: chr(ord(c.lower()) - 96)  # noqa: E731
ENTER = '\r'
TAB = '\t'
BACKSPACE = '\x7f'
DELETE = ESC + '[3~'
ESCAPE = ESC
UP, DOWN, RIGHT, LEFT = ESC + '[A', ESC + '[B', ESC + '[C', ESC + '[D'
SHIFT_RIGHT = ESC + '[1;2C'
SHIFT_DOWN = ESC + '[1;2B'
CTRL_RIGHT = ESC + '[1;5C'
ALT_UP = ESC + '[1;3A'
HOME, END = ESC + '[H', ESC + '[F'
F1, F2, F4, F6 = ESC + 'OP', ESC + 'OQ', ESC + 'OS', ESC + '[17~'
ALT_LEFT, ALT_RIGHT = ESC + '[1;3D', ESC + '[1;3C'
ALT_A = ESC + 'a'
PY = 'python3'
