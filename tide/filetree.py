"""Sidebar file explorer."""

import os

from . import theme
from .term import BOLD, Rect

IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.mypy_cache',
               '.pytest_cache', 'target', 'dist', 'build', '.idea', '.tide-tmp'}
IGNORE_FILES = {'.DS_Store'}


class Entry(object):
    __slots__ = ('path', 'name', 'is_dir', 'depth')

    def __init__(self, path, name, is_dir, depth):
        self.path = path
        self.name = name
        self.is_dir = is_dir
        self.depth = depth


class FileTree(object):
    def __init__(self, app, root):
        self.app = app
        self.root = os.path.abspath(root)
        self.expanded = {self.root}
        self.entries = []
        self.index = 0
        self.top = 0
        self.rect = Rect(0, 0, 1, 1)
        self.refresh()

    def refresh(self):
        keep = self.entries[self.index].path if 0 <= self.index < len(self.entries) else None
        self.entries = []
        self._walk(self.root, 0)
        git = getattr(self.app, 'git', None)
        if git is not None and git.enabled:
            git.mark_ignored([e.path for e in self.entries])
        if keep:
            for i, e in enumerate(self.entries):
                if e.path == keep:
                    self.index = i
                    break

    def _walk(self, directory, depth):
        try:
            names = sorted(os.listdir(directory), key=lambda n: (not os.path.isdir(
                os.path.join(directory, n)), n.lower()))
        except OSError:
            return
        for name in names:
            if name in IGNORE_FILES or name in IGNORE_DIRS:
                continue
            path = os.path.join(directory, name)
            is_dir = os.path.isdir(path)
            self.entries.append(Entry(path, name, is_dir, depth))
            if is_dir and path in self.expanded:
                self._walk(path, depth + 1)

    def current(self):
        if 0 <= self.index < len(self.entries):
            return self.entries[self.index]
        return None

    def reveal(self, path):
        """Expand parents so `path` is visible, then select it."""
        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        chain = []
        while parent.startswith(self.root) and parent != self.root:
            chain.append(parent)
            parent = os.path.dirname(parent)
        self.expanded.update(chain)
        self.refresh()
        for i, e in enumerate(self.entries):
            if e.path == path:
                self.index = i
                self._scroll_into_view()
                return True
        return False

    def toggle(self, entry=None):
        entry = entry or self.current()
        if not entry or not entry.is_dir:
            return False
        if entry.path in self.expanded:
            self.expanded.discard(entry.path)
        else:
            self.expanded.add(entry.path)
        self.refresh()
        return True

    def activate(self):
        entry = self.current()
        if not entry:
            return
        if entry.is_dir:
            self.toggle(entry)
        else:
            self.app.open_file(entry.path)

    def _scroll_into_view(self):
        h = max(1, self.rect.h - 1)
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + h:
            self.top = self.index - h + 1

    def move(self, delta):
        if not self.entries:
            return
        self.index = max(0, min(len(self.entries) - 1, self.index + delta))
        self._scroll_into_view()

    def on_key(self, key):
        name = key.name
        if name == 'up':
            self.move(-1)
        elif name == 'down':
            self.move(1)
        elif name == 'pageup':
            self.move(-(self.rect.h - 2))
        elif name == 'pagedown':
            self.move(self.rect.h - 2)
        elif name == 'home':
            self.index = 0
            self._scroll_into_view()
        elif name == 'end':
            self.index = len(self.entries) - 1
            self._scroll_into_view()
        elif name in ('enter', 'right'):
            entry = self.current()
            if name == 'right' and entry and entry.is_dir and entry.path in self.expanded:
                self.move(1)
            else:
                self.activate()
        elif name == 'left':
            entry = self.current()
            if entry and entry.is_dir and entry.path in self.expanded:
                self.toggle(entry)
            else:
                parent = os.path.dirname(entry.path) if entry else None
                for i, e in enumerate(self.entries):
                    if e.path == parent:
                        self.index = i
                        self._scroll_into_view()
                        break
        elif name == 'char' and key.char == 'r' and key.ctrl:
            self.refresh()
        else:
            return False
        return True

    def on_mouse(self, ev):
        if ev.kind == 'wheel_up':
            self.top = max(0, self.top - 3)
            return True
        if ev.kind == 'wheel_down':
            self.top = min(max(0, len(self.entries) - 1), self.top + 3)
            return True
        if ev.kind != 'press':
            return False
        row = ev.y - self.rect.y - 1 + self.top  # -1 for the header
        if ev.y == self.rect.y:
            return True
        if 0 <= row < len(self.entries):
            self.index = row
            self.activate()
        return True

    def render(self, screen, rect, focused):
        self.rect = rect
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.PANEL)
        head = ' EXPLORER'
        screen.fill(rect.x, rect.y, rect.w, 1, bg=theme.PANEL_ALT)
        screen.put(rect.x, rect.y, head[:rect.w], fg=theme.FG if focused else theme.FG_DIM,
                   bg=theme.PANEL_ALT, attr=BOLD)
        name = os.path.basename(self.root) or self.root
        avail = rect.w - len(head) - 1
        if avail > 3:
            screen.put(rect.x + len(head) + 1, rect.y, name[:avail], fg=theme.FG_DIM,
                       bg=theme.PANEL_ALT)
        h = rect.h - 1
        self.top = max(0, min(self.top, max(0, len(self.entries) - 1)))
        for i in range(h):
            idx = self.top + i
            if idx >= len(self.entries):
                break
            e = self.entries[idx]
            y = rect.y + 1 + i
            selected = idx == self.index
            bg = theme.TREE_SEL_BG if (selected and focused) else (
                theme.PANEL_ALT if selected else theme.PANEL)
            screen.fill(rect.x, y, rect.w, 1, bg=bg)
            prefix = ' ' * (e.depth + 1)
            if e.is_dir:
                mark = '- ' if e.path in self.expanded else '+ '
                fg = theme.TREE_DIR
            else:
                mark = '  '
                fg = theme.TREE_FILE
            git = self.app.git.status_for(e.path, e.is_dir) if self.app else None
            ignored = self.app.git.is_ignored(e.path) if self.app else False
            if ignored:
                fg = theme.GIT_IGNORED          # git is not watching this one
                git = None
            elif git:
                fg = theme.git_colour(git)
            label = prefix + mark + e.name
            screen.put(rect.x, y, label[:rect.w], fg=fg, bg=bg,
                       attr=0 if ignored else (BOLD if e.is_dir else 0),
                       max_x=rect.x2 - 2)
            if git and not e.is_dir:
                screen.put(rect.x2 - 2, y, git, fg=fg, bg=bg, attr=BOLD)
