"""Input prompts, the fuzzy file picker, confirmations and the help screen."""

import os

from . import settings as settings_store
from . import theme
from .term import BOLD, DIM, REVERSE, Rect


def fuzzy_score(needle, hay):
    """Subsequence match; higher is better, None when it does not match."""
    if not needle:
        return 0
    n = needle.lower()
    h = hay.lower()
    base = os.path.basename(h)
    if n in base:
        return 1000 - base.index(n) - len(base) * 0.1
    if n in h:
        return 500 - h.index(n) * 0.1
    i = 0
    score = 0
    streak = 0
    for ch in h:
        if i < len(n) and ch == n[i]:
            i += 1
            streak += 1
            score += 5 + streak
        else:
            streak = 0
    if i < len(n):
        return None
    return score - len(h) * 0.05


class Prompt(object):
    """A one-line input, optionally with a filtered result list."""

    def __init__(self, title, text='', items=None, on_accept=None, on_change=None,
                 on_cancel=None, info='', display=None):
        self.title = title
        self.text = text
        self.cursor = len(text)
        self.items = items
        self.filtered = list(items) if items else []
        self.index = 0
        self.top = 0
        self.on_accept = on_accept
        self.on_change = on_change
        self.on_cancel = on_cancel
        self.info = info
        self.display = display or (lambda x: x)
        self.rect = Rect(0, 0, 1, 1)
        self.rows = []
        if items:
            self.filter()

    @property
    def is_list(self):
        return self.items is not None

    def filter(self):
        if self.items is None:
            return
        if not self.text:
            self.filtered = self.items[:200]
        else:
            scored = []
            for it in self.items:
                s = fuzzy_score(self.text, it)
                if s is not None:
                    scored.append((s, it))
            scored.sort(key=lambda p: -p[0])
            self.filtered = [it for _s, it in scored[:200]]
        self.index = 0
        self.top = 0

    def selection(self):
        if self.is_list and 0 <= self.index < len(self.filtered):
            return self.filtered[self.index]
        return None

    def on_key(self, key):
        name = key.name
        if name == 'escape':
            if self.on_cancel:
                self.on_cancel()
            return 'close'
        if name == 'enter':
            value = self.selection() if self.is_list else self.text
            if self.on_accept:
                res = self.on_accept(value)
                if res == 'keep':
                    return 'keep'
            return 'close'
        if name == 'backspace':
            if key.ctrl or key.alt:
                self.text = self.text[:max(0, self.text.rstrip().rfind(' ') + 1)]
                self.cursor = len(self.text)
            elif self.cursor > 0:
                self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
                self.cursor -= 1
            self._changed()
            return 'keep'
        if name == 'delete':
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
            self._changed()
            return 'keep'
        if name == 'left':
            self.cursor = max(0, self.cursor - 1)
            return 'keep'
        if name == 'right':
            self.cursor = min(len(self.text), self.cursor + 1)
            return 'keep'
        if name == 'home':
            self.cursor = 0
            return 'keep'
        if name == 'end':
            self.cursor = len(self.text)
            return 'keep'
        if name == 'up':
            self.move(-1)
            return 'keep'
        if name == 'down':
            self.move(1)
            return 'keep'
        if name == 'pageup':
            self.move(-10)
            return 'keep'
        if name == 'pagedown':
            self.move(10)
            return 'keep'
        if name == 'char':
            if key.ctrl and key.char.lower() == 'u':
                self.text = ''
                self.cursor = 0
                self._changed()
                return 'keep'
            if key.ctrl or key.alt:
                return 'keep'
            self.text = self.text[:self.cursor] + key.char + self.text[self.cursor:]
            self.cursor += 1
            self._changed()
            return 'keep'
        return 'keep'

    def move(self, delta):
        if not self.is_list or not self.filtered:
            return
        self.index = max(0, min(len(self.filtered) - 1, self.index + delta))

    def on_paste(self, text):
        text = text.replace('\n', ' ')
        self.text = self.text[:self.cursor] + text + self.text[self.cursor:]
        self.cursor += len(text)
        self._changed()

    def on_mouse(self, ev):
        if not self.is_list or ev.kind not in ('press', 'wheel_up', 'wheel_down'):
            return False
        if ev.kind == 'wheel_up':
            self.move(-3)
            return True
        if ev.kind == 'wheel_down':
            self.move(3)
            return True
        for i, y in self.rows:
            if ev.y == y:
                self.index = i
                return 'accept'
        return True

    def _changed(self):
        self.filter()
        if self.on_change:
            self.on_change(self.text)

    # ---------------- painting ----------------
    def render(self, screen, area):
        if self.is_list:
            return self._render_box(screen, area)
        return self._render_line(screen, area)

    def _render_line(self, screen, area):
        y = area.y2 - 1
        screen.fill(area.x, y, area.w, 1, bg=theme.PANEL_ALT)
        x = screen.put(area.x, y, ' ' + self.title + ' ', fg=theme.STATUS_FG,
                       bg=theme.STATUS_ACC, attr=BOLD)
        x = screen.put(x + 1, y, self.text, fg=theme.FG, bg=theme.PANEL_ALT, max_x=area.x2 - 12)
        if self.info:
            screen.put(max(x + 2, area.x2 - len(self.info) - 1), y, self.info,
                       fg=theme.FG_DIM, bg=theme.PANEL_ALT)
        cx = area.x + len(self.title) + 3 + self.cursor
        return (min(cx, area.x2 - 1), y)

    def _render_box(self, screen, area):
        w = min(90, max(40, area.w - 8))
        h = min(18, max(6, area.h - 6))
        x = area.x + (area.w - w) // 2
        y = area.y + 1
        self.rect = Rect(x, y, w, h)
        screen.fill(x, y, w, h, bg=theme.PANEL_ALT)
        # title / input row
        screen.fill(x, y, w, 1, bg=theme.STATUS_ACC)
        screen.put(x + 1, y, self.title, fg=theme.STATUS_FG, bg=theme.STATUS_ACC, attr=BOLD)
        tx = x + len(self.title) + 2
        screen.put(tx, y, self.text, fg=theme.STATUS_FG, bg=theme.STATUS_ACC, max_x=x + w - 8)
        count = '%d' % len(self.filtered)
        screen.put(x + w - len(count) - 1, y, count, fg=theme.STATUS_FG, bg=theme.STATUS_ACC)
        self.rows = []
        visible = h - 1
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + visible:
            self.top = self.index - visible + 1
        for i in range(visible):
            idx = self.top + i
            ry = y + 1 + i
            if idx >= len(self.filtered):
                break
            self.rows.append((idx, ry))
            sel = idx == self.index
            bg = theme.TREE_SEL_BG if sel else theme.PANEL_ALT
            screen.fill(x, ry, w, 1, bg=bg)
            label = self.display(self.filtered[idx])
            base = os.path.basename(label)
            parent = label[:len(label) - len(base)]
            px = screen.put(x + 1, ry, base, fg=theme.FG, bg=bg,
                            attr=BOLD if sel else 0, max_x=x + w - 1)
            if parent:
                screen.put(px + 1, ry, parent, fg=theme.FG_DIM, bg=bg, max_x=x + w - 1)
        return (min(tx + self.cursor, x + w - 9), y)


class Confirm(object):
    """A yes/no/cancel question shown on the prompt line.

    `extra` adds a third answer, as ('d', 'diff', callback).
    """

    def __init__(self, question, on_yes, on_no=None, on_cancel=None, extra=None):
        self.question = question
        self.on_yes = on_yes
        self.on_no = on_no
        self.on_cancel = on_cancel
        self.extra = extra

    def keys(self):
        return 'y/n/%s/esc' % self.extra[0] if self.extra else 'y/n/esc'

    def on_key(self, key):
        ch = key.char.lower() if key.name == 'char' else ''
        if self.extra and ch == self.extra[0]:
            self.extra[2]()
            return 'close'
        if key.name == 'escape' or ch == 'c':
            if self.on_cancel:
                self.on_cancel()
            return 'close'
        if ch == 'y' or key.name == 'enter':
            self.on_yes()
            return 'close'
        if ch == 'n':
            if self.on_no:
                self.on_no()
            return 'close'
        return 'keep'

    def on_paste(self, text):
        pass

    def on_mouse(self, ev):
        return False

    def render(self, screen, area):
        y = area.y2 - 1
        screen.fill(area.x, y, area.w, 1, bg=theme.PANEL_ALT)
        hint = self.extra[1] + ', ' if self.extra else ''
        text = ' %s [%s%s] ' % (self.question, hint, self.keys())
        screen.put(area.x, y, text, fg=theme.STATUS_FG, bg=theme.WARN, attr=BOLD)
        return None


class SettingsPanel(object):
    """The preferences dialog: one row per setting, arrows to change them."""

    def __init__(self, app):
        self.app = app
        self.index = 0
        self.rows = []
        self.rect = Rect(0, 0, 1, 1)

    def _cycle(self, delta):
        key, _label, options = settings_store.FIELDS[self.index]
        current = self.app.settings.get(key)
        try:
            i = options.index(current)
        except ValueError:
            i = 0
            delta = 0
        self.app.set_setting(key, options[(i + delta) % len(options)])

    def on_key(self, key):
        name = key.name
        if name in ('escape', 'f9'):
            return 'close'
        if name == 'char' and (key.char in 'q,' or (key.ctrl and key.char == 't')):
            return 'close'
        if name == 'enter':
            self._cycle(1)
        elif name == 'up':
            self.index = (self.index - 1) % len(settings_store.FIELDS)
        elif name == 'down':
            self.index = (self.index + 1) % len(settings_store.FIELDS)
        elif name == 'home':
            self.index = 0
        elif name == 'end':
            self.index = len(settings_store.FIELDS) - 1
        elif name == 'left':
            self._cycle(-1)
        elif name in ('right', 'tab') or (name == 'char' and key.char == ' '):
            self._cycle(1)
        return 'keep'

    def on_paste(self, text):
        pass

    def on_mouse(self, ev):
        if ev.kind != 'press':
            return True
        for i, y in self.rows:
            if ev.y == y:
                self.index = i
                middle = self.rect.x + self.rect.w // 2
                self._cycle(-1 if ev.x < middle else 1)
                return True
        if not self.rect.contains(ev.x, ev.y):
            return 'close'
        return True

    def render(self, screen, area):
        fields = settings_store.FIELDS
        w = min(74, max(46, area.w - 6))
        h = min(len(fields) + 4, area.h - 2)
        x = area.x + (area.w - w) // 2
        y = area.y + max(0, (area.h - h) // 2)
        self.rect = Rect(x, y, w, h)
        screen.fill(x, y, w, h, bg=theme.PANEL_ALT)
        screen.fill(x, y, w, 1, bg=theme.STATUS_ACC)
        screen.put(x + 1, y, ' Settings ', fg=theme.STATUS_FG, bg=theme.STATUS_ACC,
                   attr=BOLD)
        where = settings_store.config_path().replace(os.path.expanduser('~'), '~')
        if w > len(where) + 16:
            screen.put(x + w - len(where) - 1, y, where, fg=theme.STATUS_FG,
                       bg=theme.STATUS_ACC)
        self.rows = []
        value_x = x + 24
        for i, (key, label, _options) in enumerate(fields):
            ry = y + 1 + i
            if ry >= y + h - 1:
                break
            self.rows.append((i, ry))
            chosen = i == self.index
            bg = theme.TREE_SEL_BG if chosen else theme.PANEL_ALT
            screen.fill(x, ry, w, 1, bg=bg)
            screen.put(x + 2, ry, label, fg=theme.FG, bg=bg,
                       attr=BOLD if chosen else 0, max_x=value_x - 1)
            shown = settings_store.show(key, self.app.settings.get(key))
            text = ('< %s >' % shown) if chosen else ('  %s' % shown)
            vx = screen.put(value_x, ry, text, fg=theme.TAB_MARK if chosen else theme.FG,
                            bg=bg, attr=BOLD if chosen else 0, max_x=x + w - 2)
            hint = settings_store.HINTS.get(key, '')
            if hint and vx + 2 < x + w - 2:
                screen.put(max(vx + 2, value_x + 16), ry, hint, fg=theme.FG_DIM, bg=bg,
                           max_x=x + w - 1)
        footer = y + h - 1
        screen.fill(x, footer, w, 1, bg=theme.PANEL_ALT)
        screen.put(x + 2, footer, 'up/down choose   left/right change   esc close',
                   fg=theme.FG_DIM, bg=theme.PANEL_ALT, max_x=x + w - 1)
        return None


HELP_TEXT = [
    ('Files', [
        ('ctrl+p', 'quick open file (fuzzy)'),
        ('ctrl+o', 'open path'),
        ('ctrl+n / ctrl+w', 'new tab / close tab'),
        ('click x on a tab', 'close that tab (middle-click too)'),
        ('wheel over the tabs', 'scroll the strip when there are too many'),
        ('ctrl+s / alt+s', 'save / save as'),
        ('alt+a', 'toggle auto-save (on by default)'),
        ('alt+left / alt+right', 'previous / next tab'),
        ('ctrl+b', 'toggle explorer'),
    ]),
    ('Editing', [
        ('click / drag', 'move cursor / select'),
        ('scrollbar (right edge)', 'drag the thumb, or click the track to jump'),
        ('double / triple click', 'select word / line'),
        ('shift+click, shift+arrows', 'extend selection'),
        ('ctrl+arrows', 'move by word'),
        ('ctrl+c / ctrl+x / ctrl+v', 'copy / cut / paste'),
        ('ctrl+z / ctrl+y', 'undo / redo'),
        ('ctrl+k', 'delete line(s)'),
        ('ctrl+d', 'duplicate line/selection'),
        ('alt+up / alt+down', 'move line(s)'),
        ('tab / shift+tab', 'indent / dedent selection'),
        ('ctrl+/', 'toggle comment'),
        ('ctrl+a', 'select all'),
        ('ctrl+f / f3', 'find / find next'),
        ('ctrl+g', 'go to line'),
    ]),
    ('Bottom terminal panel', [
        ('ctrl+j', 'show/hide the panel (and focus it)'),
        ('drag the TERMINAL bar', 'resize the panel'),
        ('drag in terminal', 'select + copy'),
        ('mouse wheel', 'scrollback (stays put as output arrives)'),
    ]),
    ('Full-size terminals', [
        ('f5', 'split view: a file and a shell side by side'),
        ('f2', 'in split view, move between the two halves'),
        ('Editor / Terminals', 'the switch above the tabs, in single view'),
        ('f4  or  click +', 'new full-size session'),
        ('alt+left / alt+right', 'previous / next session'),
        ('click x, or exit', 'close a session'),
    ]),
    ('Panes', [
        ('f5', 'split view: a file and a shell side by side'),
        ('</> button', 'in split view, start the shell for the right half'),
        ('f6', 'cycle focus: explorer / main / bottom terminal'),
        ('ctrl+b', 'show/hide the explorer'),
    ]),
    ('Git', [
        ('explorer letters', 'U new (green), M modified (orange), D deleted, A staged'),
        ('green bar in the gutter', 'lines added since the last commit'),
        ('blue bar in the gutter', 'lines edited since the last commit'),
        ('red mark in the gutter', 'lines were removed here'),
        ('ticks on the scrollbar', 'where the changes are in the whole file'),
        ('grey names in the tree', 'files git is told to ignore'),
        ('branch name', 'bottom left, with * when there are changes'),
        ('branches, commits, push', 'use the terminal - f2 or ctrl+j'),
    ]),
    ('Diffs (read-only tabs)', [
        ('changes / diff all', 'buttons, top right, for a modified file'),
        ('f7 / f8', 'the same two, from the keyboard'),
        ('d at "changed on disk"', 'compare your version with the file'),
        ('m', 'switch between changes only and the whole file'),
        ('r', 'compare with the upstream branch instead'),
        ('n / p', 'jump to the next or previous change'),
        ('sideways wheel, shift+wheel', 'scroll long lines in one half only'),
        ('left / right, tab', 'the same from the keyboard, tab picks the half'),
    ]),
    ('Files on disk', [
        ('(automatic)', 'edits are saved 0.8s after you stop typing'),
        ('(automatic)', 'open files reload when something else changes them'),
        ('big or binary files', 'the IDE asks before opening them'),
    ]),
    ('Other', [
        ('f9, ctrl+t, alt+,', 'settings (theme, auto-save, size limits)'),
        ('click "settings"', 'the same panel, top right'),
        ('f1', 'this help'),
        ('ctrl+q', 'quit'),
    ]),
]


class Help(object):
    def on_key(self, key):
        return 'close'

    def on_paste(self, text):
        pass

    def on_mouse(self, ev):
        return 'close' if ev.kind == 'press' else True

    def render(self, screen, area):
        lines = []
        for section, items in HELP_TEXT:
            lines.append(('section', section))
            for k, d in items:
                lines.append(('item', (k, d)))
            lines.append(('blank', ''))
        w = min(80, area.w - 4)
        h = min(len(lines) + 2, area.h - 2)
        x = area.x + (area.w - w) // 2
        y = area.y + max(0, (area.h - h) // 2)
        screen.fill(x, y, w, h, bg=theme.PANEL_ALT)
        screen.fill(x, y, w, 1, bg=theme.STATUS_ACC)
        title = ' terminal_ide - keys (any key closes) '
        screen.put(x + 1, y, title[:w - 2], fg=theme.STATUS_FG, bg=theme.STATUS_ACC, attr=BOLD)
        for i, (kind, val) in enumerate(lines):
            ry = y + 1 + i
            if ry >= y + h:
                break
            if kind == 'section':
                screen.put(x + 1, ry, val, fg=theme.STATUS_ACC, bg=theme.PANEL_ALT, attr=BOLD)
            elif kind == 'item':
                k, d = val
                key_w = min(27, max(10, w - 20))
                screen.put(x + 2, ry, k, fg=theme.TAB_MARK, bg=theme.PANEL_ALT,
                           max_x=x + 2 + key_w)
                screen.put(x + 3 + key_w, ry, d, fg=theme.FG, bg=theme.PANEL_ALT,
                           max_x=x + w - 1)
        return None
