"""The menus along the top: Tide, View and Help.

The bar itself is three words in the top row. Clicking one opens a dropdown
under it, which is an overlay like any other - it takes the keyboard while it
is up, and every item it offers does exactly what the key for that item does,
so nothing here is a second way of doing anything.
"""

from . import theme
from .term import BOLD, DIM, Rect

NAMES = ('Tide', 'File', 'View', 'Help')
SEPARATOR = None


class MenuBar(object):
    """Three words at the top left, and where they are."""

    @staticmethod
    def render(screen, rect, open_name=None):
        """Draw the bar; returns [(x1, x2, name)] for hit testing."""
        spans = []
        x = rect.x + 1
        for name in NAMES:
            label = ' %s ' % name
            if x + len(label) > rect.x2:
                break
            active = name == open_name
            bg = theme.STATUS_ACC if active else theme.PANEL
            fg = theme.STATUS_FG if active else theme.FG
            screen.fill(x, rect.y, len(label), 1, bg=bg)
            screen.put(x, rect.y, label, fg=fg, bg=bg,
                       attr=BOLD if active else 0, max_x=rect.x2)
            spans.append((x, x + len(label), name))
            x += len(label) + 1
        return spans, x


class Dropdown(object):
    """One menu, open under its name."""

    is_list = False

    def __init__(self, app, name, x, y, items, width=0):
        self.app = app
        self.name = name
        self.x = x
        self.y = y
        self.width = width            # the same for every menu on the bar
        self.items = items            # (label, hint, action) or SEPARATOR
                                      # an item with no action is greyed out
        self.index = self._first()
        self.rect = Rect(0, 0, 1, 1)

    def _first(self):
        for i, item in enumerate(self.items):
            if self.pickable(i):
                return i
        return 0

    def pickable(self, i):
        """A separator, or something greyed out, is not to be landed on."""
        item = self.items[i] if 0 <= i < len(self.items) else SEPARATOR
        return item is not SEPARATOR and item[2] is not None

    def close(self):
        self.app.menu_open = None
        self.app.overlay = None
        self.app.need_render = True

    def choose(self, index):
        if not 0 <= index < len(self.items):
            return
        if not self.pickable(index):
            return
        self.close()
        self.items[index][2]()

    def move(self, delta):
        i = self.index
        for _ in range(len(self.items)):
            i = (i + delta) % len(self.items)
            if self.pickable(i):
                self.index = i
                return

    # ---------------- keys ----------------
    def on_key(self, key):
        name = key.name
        if name == 'escape':
            self.close()
            return None
        if name == 'up':
            self.move(-1)
        elif name == 'down':
            self.move(1)
        elif name in ('enter', 'right'):
            self.choose(self.index)
        elif name == 'left':
            self.app.open_menu_beside(self.name, -1)
        elif name == 'tab':
            self.app.open_menu_beside(self.name, 1)
        else:
            self.close()
            return None
        self.app.need_render = True
        return None

    def on_paste(self, _text):
        pass

    def on_mouse(self, ev):
        if ev.kind == 'move':
            if ev.y == self.y - 1:
                # along the bar with a menu down: the one under the pointer
                for x1, x2, name in self.app.menu_spans:
                    if x1 <= ev.x < x2 and name != self.name and \
                            self.app.menu_items(name) is not None:
                        self.app.open_menu(name, x1)   # a menu, not a button
                        return True
                return True
            index = self.y_to_index(ev.y)
            if self.rect.contains(ev.x, ev.y) and self.pickable(index) \
                    and index != self.index:
                self.index = index
                self.app.need_render = True
            return True
        if ev.kind not in ('press', 'release'):
            return True
        if not self.rect.contains(ev.x, ev.y):
            if ev.kind == 'press':
                self.close()
                return False          # the click belongs to whatever is under it
            return True
        if ev.kind == 'press':
            self.choose(self.y_to_index(ev.y))
        return True

    def y_to_index(self, y):
        return y - self.rect.y - 1

    # ---------------- painting ----------------
    def render(self, screen, area):
        width = self.width or item_width(self.items)
        width = min(max(width, 18), area.w - 2)
        height = len(self.items) + 2
        x = min(self.x, area.x2 - width - 1)
        y = self.y
        if y + height > area.y2:
            height = max(3, area.y2 - y)
        self.rect = Rect(x, y, width, height)
        screen.fill(x, y, width, height, bg=theme.PANEL_ALT)
        border = theme.BORDER
        screen.put(x, y, '╭' + '─' * (width - 2) + '╮',
                   fg=border, bg=theme.PANEL_ALT, max_x=x + width)
        screen.put(x, y + height - 1, '╰' + '─' * (width - 2) + '╯',
                   fg=border, bg=theme.PANEL_ALT, max_x=x + width)
        for row in range(y + 1, y + height - 1):
            screen.put(x, row, '│', fg=border, bg=theme.PANEL_ALT)
            screen.put(x + width - 1, row, '│', fg=border, bg=theme.PANEL_ALT)
        for i, item in enumerate(self.items):
            row = y + 1 + i
            if row >= y + height - 1:
                break
            if item is SEPARATOR:
                screen.put(x + 1, row, '─' * (width - 2), fg=border,
                           bg=theme.PANEL_ALT, attr=DIM)
                continue
            label, hint, action = item[0], item[1], item[2]
            own = item[3] if len(item) > 3 else 0     # italic, struck through
            chosen = i == self.index
            off = action is None                    # there, but not for now
            bg = theme.TREE_SEL_BG if chosen else theme.PANEL_ALT
            screen.fill(x + 1, row, width - 2, 1, bg=bg)
            screen.put(x + 2, row, label, fg=theme.FG_DIM if off else theme.FG,
                       bg=bg, attr=own | (DIM if off else (BOLD if chosen else 0)),
                       max_x=x + width - 2 - (len(hint) + 1 if hint else 0))
            if hint:
                screen.put(x + width - 2 - len(hint), row, hint,
                           fg=theme.FG_DIM, bg=bg, max_x=x + width - 1)
        return None


def item_width(items):
    """How wide a menu has to be to hold its longest line."""
    return max([len('%s%s' % (item[0], item[1])) + 6
                for item in items if item is not SEPARATOR] or [18])


def tick(on):
    """The mark beside something that is showing."""
    return '✓ ' if on else '  '
