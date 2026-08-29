"""Open File…: a small file browser, for when you do not know the path.

Directories first, `..` to go up, enter or a click to open. Typing a letter
jumps to the next thing beginning with it. It opens the file the same way
everything else does, so the size and binary guards still apply.
"""

import os

from . import theme
from .term import BOLD, DIM, Rect


class FileBrowser(object):
    """A read-only look around the filesystem, ending in one open file."""

    is_list = True

    def __init__(self, app, start=None):
        self.app = app
        self.folder = os.path.abspath(start or app.root)
        self.entries = []
        self.index = 0
        self.top = 0
        self.note = ''
        self.rect = Rect(0, 0, 1, 1)
        self.read()

    # ---------------- what is in here ----------------
    def read(self):
        self.entries = [('..', True)]
        try:
            names = sorted(os.listdir(self.folder), key=lambda n: n.lower())
        except OSError as exc:
            self.note = 'cannot read this folder (%s)' % (exc.strerror or exc)
            names = []
        folders, files = [], []
        for name in names:
            if name.startswith('.'):
                continue                      # hidden things stay hidden
            path = os.path.join(self.folder, name)
            (folders if os.path.isdir(path) else files).append(
                (name, os.path.isdir(path)))
        self.entries += folders + files
        self.index = 0
        self.top = 0

    def enter(self, index=None):
        index = self.index if index is None else index
        if not 0 <= index < len(self.entries):
            return
        name, is_dir = self.entries[index]
        if name == '..':
            parent = os.path.dirname(self.folder)
            if parent and parent != self.folder:
                self.folder = parent
                self.read()
            return
        path = os.path.join(self.folder, name)
        if is_dir:
            self.folder = path
            self.note = ''
            self.read()
            return
        self.close()
        self.app.open_file(path)

    def close(self):
        if self.app.overlay is self:
            self.app.overlay = None
        self.app.need_render = True

    def move(self, delta):
        if not self.entries:
            return
        self.index = max(0, min(len(self.entries) - 1, self.index + delta))
        self._into_view()

    def _into_view(self):
        height = max(1, self.rect.h - 2)
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + height:
            self.top = self.index - height + 1

    def jump_to(self, letter):
        letter = letter.lower()
        order = list(range(self.index + 1, len(self.entries))) + \
            list(range(0, self.index + 1))
        for i in order:
            if self.entries[i][0].lower().startswith(letter):
                self.index = i
                self._into_view()
                return

    # ---------------- keys and mouse ----------------
    def on_key(self, key):
        name = key.name
        if name == 'escape':
            self.close()
            return 'close'
        if name == 'up':
            self.move(-1)
        elif name == 'down':
            self.move(1)
        elif name == 'pageup':
            self.move(-(max(1, self.rect.h - 3)))
        elif name == 'pagedown':
            self.move(max(1, self.rect.h - 3))
        elif name == 'home':
            self.index = self.top = 0
        elif name == 'end':
            self.index = len(self.entries) - 1
            self._into_view()
        elif name in ('enter', 'right'):
            self.enter()
        elif name in ('left', 'backspace'):
            self.enter(0)                      # ..
        elif name == 'char' and key.char.strip():
            self.jump_to(key.char)
        self.app.need_render = True
        return None

    def on_paste(self, text):
        text = text.strip()
        if text and os.path.isdir(text):
            self.folder = os.path.abspath(text)
            self.read()
        elif text and os.path.isfile(text):
            self.close()
            self.app.open_file(text)

    def on_mouse(self, ev):
        if ev.kind == 'wheel_up':
            self.top = max(0, self.top - 3)
            return True
        if ev.kind == 'wheel_down':
            self.top = max(0, min(self.top + 3, max(0, len(self.entries) - 1)))
            return True
        if ev.kind != 'press':
            return True
        if not self.rect.contains(ev.x, ev.y):
            self.close()
            return True
        row = ev.y - self.rect.y - 1 + self.top
        if 0 <= row < len(self.entries):
            if row == self.index:
                self.enter(row)
            else:
                self.index = row
        return True

    # ---------------- painting ----------------
    def render(self, screen, area):
        width = min(72, max(40, area.w - 8))
        height = min(len(self.entries) + 2, max(6, area.h - 4))
        x = area.x + (area.w - width) // 2
        y = area.y + max(0, (area.h - height) // 2)
        self.rect = Rect(x, y, width, height)
        screen.fill(x, y, width, height, bg=theme.PANEL_ALT)
        screen.fill(x, y, width, 1, bg=theme.STATUS_ACC)
        title = ' %s ' % self.app.rel_folder(self.folder)
        screen.put(x + 1, y, title[-(width - 2):], fg=theme.STATUS_FG,
                   bg=theme.STATUS_ACC, attr=BOLD, max_x=x + width - 1)
        rows = height - 2
        self.top = max(0, min(self.top, max(0, len(self.entries) - rows)))
        for i in range(rows):
            index = self.top + i
            if index >= len(self.entries):
                break
            name, is_dir = self.entries[index]
            row = y + 1 + i
            chosen = index == self.index
            bg = theme.TREE_SEL_BG if chosen else theme.PANEL_ALT
            fg = theme.TREE_DIR if is_dir else theme.TREE_FILE
            screen.fill(x + 1, row, width - 2, 1, bg=bg)
            label = ('▸ ' if is_dir else '  ') + name + ('/' if is_dir and
                                                         name != '..' else '')
            screen.put(x + 2, row, label, fg=fg, bg=bg,
                       attr=BOLD if is_dir else 0, max_x=x + width - 2)
        foot = self.note or 'enter opens   .. goes up   esc closes'
        screen.put(x + 2, y + height - 1, foot[:width - 4],
                   fg=theme.ERROR if self.note else theme.FG_DIM,
                   bg=theme.PANEL_ALT, attr=0 if self.note else DIM)
        return None
