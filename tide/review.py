"""Git review: every change in the working tree, read only, in one long page.

The review takes over what is on screen and nothing else. Editors keep their
buffers, terminals keep running, the layout you had comes back untouched when
you leave - the app simply draws this instead until you press escape.

The page reads the way a commit does on a forge: a tree of the files that
changed down the left, and one scrollable diff on the right that runs from the
first file to the last with a rule between them.
"""

import hashlib
import io
import os
import time

from . import theme
from . import names
from .diff import GAP, DiffView, TEXT_X, _expand, align, trim
from .keys import SHIFT
from .term import BOLD, DIM, Rect

HEAD = 'head'          # a file's heading inside the page
RULE = 'rule'          # the line between two files
SCAN_EVERY = 2.0       # seconds between asking git for the list again

STATUS_ORDER = {'U': 0, 'A': 1, 'M': 2, 'D': 3}


def _decode(out):
    """git's -z output: NUL separated bytes, as text."""
    if not out:
        return []
    if isinstance(out, bytes):
        out = out.decode('utf-8', 'replace')
    return out.split('\0')


def changed_files(git):
    """[(path, letter)] for everything that differs from the last commit.

    Renames where nothing was edited are left out - git scores them at 100%
    and there is nothing to review.
    """
    if not git.enabled:
        return []
    found = []
    out = git._run(['diff', '--name-status', '-M', '-z', 'HEAD'])
    fields = [f for f in _decode(out) if f != '']
    i = 0
    while i < len(fields):
        code = fields[i]
        letter = code[0]
        if letter in ('R', 'C'):
            if i + 2 >= len(fields):
                break
            old, new = fields[i + 1], fields[i + 2]
            i += 3
            if code[1:] == '100':
                continue                      # moved, not touched
            found.append((new, 'M' if old != new else 'M'))
            continue
        if i + 1 >= len(fields):
            break
        path = fields[i + 1]
        i += 2
        if letter == 'A':
            found.append((path, 'A'))
        elif letter == 'D':
            found.append((path, 'D'))
        elif letter in ('M', 'T'):
            found.append((path, 'M'))
    out = git._run(['ls-files', '--others', '--exclude-standard', '-z'])
    for path in _decode(out):
        if path:
            found.append((path, 'U'))
    seen = {}
    for path, letter in found:
        seen.setdefault(path, letter)
    return _without_pure_moves(git, sorted(seen.items(),
                                           key=lambda pair: pair[0].lower()))


def _without_pure_moves(git, files):
    """Drop a delete and an add that are the same bytes under two names.

    git's own rename detection only reaches things it has in the index, so a
    file moved in the working tree looks like a delete plus an untracked file.
    Hashing the two candidates costs nothing and catches that case too.
    """
    gone = [p for p, letter in files if letter == 'D']
    fresh = [p for p, letter in files if letter in ('A', 'U')]
    if not gone or not fresh:
        return files
    def digest(text):
        return hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()
    old_hashes = {}
    for path in gone:
        text = git.file_at_rev(os.path.join(git.root, path), 'HEAD')
        if text is not None:
            old_hashes.setdefault(digest(text), []).append(path)
    dropped = set()
    for path in fresh:
        lines = _read(os.path.join(git.root, path))
        if lines is None:
            continue
        match = old_hashes.get(digest('\n'.join(lines)))
        if match:
            dropped.add(path)
            dropped.add(match.pop(0))
    return [pair for pair in files if pair[0] not in dropped]


def _read(path):
    try:
        with io.open(path, 'r', encoding='utf-8', errors='replace',
                     newline='') as f:
            text = f.read()
    except (OSError, IOError):
        return None
    return text.replace('\r\n', '\n').split('\n')


def _stat(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)), st.st_size)


class Node(object):
    """One line of the review's tree: a folder, or a file that changed."""

    __slots__ = ('name', 'depth', 'is_dir', 'path', 'letter', 'index')

    def __init__(self, name, depth, is_dir, path=None, letter=None, index=None):
        self.name = name
        self.depth = depth
        self.is_dir = is_dir
        self.path = path
        self.letter = letter
        self.index = index          # where this file starts in the page


class Review(object):
    """The whole review: the files, the page, and where we are looking."""

    is_review = True

    def __init__(self, app):
        self.app = app
        self.git = app.git
        self.root = app.root
        self.files = []             # [(path, letter)]
        self.rows = []              # the page: heads, rules and diff rows
        self.starts = {}            # path -> first row of its section
        self.nodes = []             # the tree down the left
        self.index = 0              # selected node
        self.collapsed = set()      # files folded away in the page
        self._seen = set()
        self.tree_top = 0
        self.top = 0
        self.cols = {'left': 0, 'right': 0}
        self.widest = {'left': 0, 'right': 0}
        self.side = 'left'
        self.rect = Rect(0, 0, 1, 1)
        self.tree_rect = Rect(0, 0, 1, 1)
        self.close_span = None
        self._order = []
        self._stamp = None
        self._last_scan = 0.0
        self.refresh(force=True)

    # ---------------- content ----------------
    def stamp(self):
        """Cheap: the repository's state, plus the files we are showing."""
        return (self.git.state_token(),
                tuple((p, _stat(os.path.join(self.root, p))) for p, _l in self.files))

    def refresh(self, force=False):
        """Rebuild when the files, or what is in them, have moved.

        The stamp covers edits to the files we know about; a brand new change
        needs git asked again, which is worth doing about as often as the
        explorer refreshes its own letters.
        """
        now = time.time()
        rescan = force or now - self._last_scan >= SCAN_EVERY
        if not rescan and self.stamp() == self._stamp:
            return False
        files = changed_files(self.git) if rescan else self.files
        if not force and files == self.files and self.stamp() == self._stamp:
            self._last_scan = now
            return False
        if rescan:
            self._last_scan = now
        self.files = files
        self._build()
        self._stamp = self.stamp()
        return True

    def _build(self):
        rows = []
        starts = {}
        for path, letter in self.files:
            full = os.path.join(self.root, path)
            if path not in self._seen:
                self._seen.add(path)
                if not self._opens(letter):
                    self.collapsed.add(path)
            shut = path in self.collapsed
            starts[path] = len(rows)
            rows.append((HEAD, path, letter, shut, None))
            if not shut:
                left = [] if letter in ('A', 'U') else \
                    (self.git.file_at_rev(full, 'HEAD') or '').split('\n')
                right = [] if letter == 'D' else (_read(full) or [])
                body = trim(align(left, right))
                if not body:
                    body = [(None, '', None, 'no textual changes', GAP)]
                rows.extend(body)
            rows.append((RULE, '', '', None, None))
        if not rows:
            rows = [(None, '', None, 'nothing has changed', GAP)]
        self.rows = rows
        self.starts = starts
        self.nodes = self._tree()
        body_rows = [r for r in rows if r[0] not in (HEAD, RULE)]
        self.widest = {
            'left': max([len(_expand(r[1])) for r in body_rows] or [0]),
            'right': max([len(_expand(r[3])) for r in body_rows
                          if r[4] != GAP] or [0]),
        }
        self._order = sorted(self.starts.items(), key=lambda kv: kv[1])
        self.top = max(0, min(self.top, self.max_top()))
        self.index = max(0, min(self.index, max(0, len(self.nodes) - 1)))

    def _tree(self):
        """Folders and files, in the shape the working tree has them."""
        nodes = []
        shown = set()
        for path, letter in self.files:
            parts = path.split('/')
            for depth in range(len(parts) - 1):
                folder = '/'.join(parts[:depth + 1])
                if folder not in shown:
                    shown.add(folder)
                    nodes.append(Node(parts[depth], depth, True))
            nodes.append(Node(parts[-1], len(parts) - 1, False, path, letter,
                              self.starts.get(path, 0)))
        return nodes

    def count(self):
        return len(self.files)

    # ---------------- moving about ----------------
    def body_height(self):
        return max(1, self.rect.h - 1)

    def max_top(self):
        return max(0, len(self.rows) - self.body_height())

    def scroll(self, delta):
        self.top = max(0, min(self.max_top(), self.top + delta))
        self._follow_page()

    def pane_width(self):
        return max(1, self.rect.w // 2 - TEXT_X - 1)

    def max_col(self, side):
        return max(0, self.widest[side] - self.pane_width())

    def scroll_across(self, side, delta):
        self.side = side
        self.cols[side] = max(0, min(self.max_col(side), self.cols[side] + delta))

    def file_at(self, row):
        """Which file the page is showing at this row."""
        current = None
        for path, start in self._order:
            if start > row:
                break
            current = path
        return current

    def _follow_page(self):
        """Keep the tree's highlight on whatever the page is showing."""
        path = self.file_at(self.top)
        if path is None:
            return
        for i, node in enumerate(self.nodes):
            if node.path == path:
                self.index = i
                self._tree_into_view()
                return

    def _tree_into_view(self):
        height = max(1, self.tree_rect.h - 1)
        if self.index < self.tree_top:
            self.tree_top = self.index
        elif self.index >= self.tree_top + height:
            self.tree_top = self.index - height + 1
        self.tree_top = max(0, min(self.tree_top, max(0, len(self.nodes) - height)))

    def show(self, path):
        """Put a file's diff at the top of the page."""
        if path in self.starts:
            self.top = max(0, min(self.max_top(), self.starts[path]))
            for i, node in enumerate(self.nodes):
                if node.path == path:
                    self.index = i
                    break
            self._tree_into_view()
            return True
        return False

    def jump_file(self, direction):
        paths = [p for p, _l in self.files]
        if not paths:
            return
        here = self.file_at(self.top)
        i = paths.index(here) if here in paths else 0
        if here is not None and self.top == self.starts[here] and direction < 0:
            i -= 1
        elif direction > 0:
            i += 1
        self.show(paths[max(0, min(len(paths) - 1, i))])

    def _opens(self, letter):
        """Whether a file of this kind starts open, from the settings."""
        key = {'M': 'review_open_modified', 'A': 'review_open_added',
               'U': 'review_open_added', 'D': 'review_open_deleted'}.get(letter)
        settings = getattr(self.app, 'settings', None) or {}
        return bool(settings.get(key, letter == 'M')) if key else True

    def reset_folds(self):
        """Fold everything the way the settings now say, keeping our place."""
        here = self.file_at(self.top)
        self.collapsed = set()
        self._seen = set()
        self._build()
        if here:
            self.show(here)

    def toggle(self, path):
        """Fold a file's diff away, or open it again."""
        if path not in self.starts:
            return False
        if path in self.collapsed:
            self.collapsed.discard(path)
        else:
            self.collapsed.add(path)
        self._build()
        self.show(path)
        return True

    def toggle_here(self):
        path = self.file_at(self.top)
        return self.toggle(path) if path else False

    def select(self, index):
        if 0 <= index < len(self.nodes):
            self.index = index
            node = self.nodes[index]
            if node.path:
                self.show(node.path)

    def move(self, delta):
        if not self.nodes:
            return
        i = max(0, min(len(self.nodes) - 1, self.index + delta))
        self.index = i
        self._tree_into_view()
        node = self.nodes[i]
        if node.path:
            self.show(node.path)

    # ---------------- keys and mouse ----------------
    def on_key(self, key):
        name = key.name
        page = max(1, self.body_height() - 1)
        if name == 'up':
            self.scroll(-1)
        elif name == 'down':
            self.scroll(1)
        elif name == 'pageup':
            self.scroll(-page)
        elif name == 'pagedown':
            self.scroll(page)
        elif name == 'home':
            self.top = 0
            self._follow_page()
        elif name == 'end':
            self.top = self.max_top()
            self._follow_page()
        elif name == 'left':
            self.scroll_across(self.side, -8)
        elif name == 'right':
            self.scroll_across(self.side, 8)
        elif name == 'tab':
            self.side = 'right' if self.side == 'left' else 'left'
        elif name == 'enter' or (name == 'char' and key.char == ' '):
            self.toggle_here()
        elif name == 'char' and key.char.lower() == 'n' and not key.ctrl:
            self.jump_file(1)
        elif name == 'char' and key.char.lower() == 'p' and not key.ctrl:
            self.jump_file(-1)
        else:
            return False
        return True

    def on_tree_key(self, key):
        if key.name == 'up':
            self.move(-1)
        elif key.name == 'down':
            self.move(1)
        elif key.name in ('enter', 'right'):
            self.select(self.index)
        else:
            return False
        return True

    def side_at(self, x):
        return 'left' if x < self.rect.x + self.rect.w // 2 else 'right'

    def on_mouse(self, ev):
        side = self.side_at(ev.x)
        if ev.kind in ('wheel_left', 'wheel_right'):
            self.scroll_across(side, -8 if ev.kind == 'wheel_left' else 8)
        elif ev.kind in ('wheel_up', 'wheel_down'):
            if ev.mods & SHIFT:
                self.scroll_across(side, -8 if ev.kind == 'wheel_up' else 8)
            else:
                self.scroll(-3 if ev.kind == 'wheel_up' else 3)
        elif ev.kind == 'press':
            self.side = side
            index = self.top + (ev.y - self.rect.y - 1)
            if 0 <= index < len(self.rows) and self.rows[index][0] == HEAD:
                self.toggle(self.rows[index][1])
        else:
            return False
        return True

    def on_tree_mouse(self, ev):
        if ev.kind == 'wheel_up':
            self.tree_top = max(0, self.tree_top - 3)
            return True
        if ev.kind == 'wheel_down':
            height = max(1, self.tree_rect.h - 1)
            self.tree_top = max(0, min(self.tree_top + 3,
                                       max(0, len(self.nodes) - height)))
            return True
        if ev.kind != 'press':
            return False
        row = ev.y - self.tree_rect.y - 1 + self.tree_top
        if 0 <= row < len(self.nodes):
            self.select(row)
        return True

    # ---------------- painting ----------------
    def render_tree(self, screen, rect, focused):
        self.tree_rect = rect
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.PANEL)
        screen.fill(rect.x, rect.y, rect.w, 1, bg=theme.PANEL_ALT)
        head = ' CHANGES'
        screen.put(rect.x, rect.y, head, fg=theme.FG if focused else theme.FG_DIM,
                   bg=theme.PANEL_ALT, attr=BOLD)
        note = '%d file%s' % (self.count(), '' if self.count() == 1 else 's')
        if rect.w > len(head) + len(note) + 2:
            screen.put(rect.x2 - len(note) - 1, rect.y, note, fg=theme.FG_DIM,
                       bg=theme.PANEL_ALT)
        height = max(1, rect.h - 1)
        self.tree_top = max(0, min(self.tree_top, max(0, len(self.nodes) - height)))
        edge = rect.x2 - 1
        for i in range(height):
            idx = self.tree_top + i
            if idx >= len(self.nodes):
                break
            node = self.nodes[idx]
            y = rect.y + 1 + i
            selected = idx == self.index
            bg = theme.TREE_SEL_BG if (selected and focused) else (
                theme.PANEL_ALT if selected else theme.PANEL)
            screen.fill(rect.x, y, rect.w, 1, bg=bg)
            fg = theme.TREE_DIR if node.is_dir else theme.git_colour(node.letter)
            mark = '▾ ' if node.is_dir else '  '
            room = max(1, edge - 1 - rect.x - node.depth - 1 - len(mark) -
                       (0 if node.is_dir else 2))
            label = ' ' * (node.depth + 1) + mark + names.crop(node.name, room)
            screen.put(rect.x, y, label, fg=fg, bg=bg,
                       attr=BOLD if node.is_dir else 0, max_x=edge - 1)
            for level in range(node.depth):
                gx = rect.x + 1 + level
                if gx < edge - 1:
                    screen.put(gx, y, '│', fg=theme.TREE_GUIDE, bg=bg)
            if node.letter and not node.is_dir:
                screen.put(edge - 1, y, node.letter, fg=fg, bg=bg, attr=BOLD)
        for y in range(rect.y, rect.y2):
            behind = screen.cells[y][edge][2]
            screen.put(edge, y, '│', fg=theme.BORDER, bg=behind)

    def render(self, screen, rect, focused):
        self.rect = rect
        self.top = max(0, min(self.top, self.max_top()))
        for side in ('left', 'right'):
            self.cols[side] = max(0, min(self.cols[side], self.max_col(side)))
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.BG)
        half = rect.w // 2
        screen.fill(rect.x, rect.y, rect.w, 1, bg=theme.PANEL_ALT)
        screen.put(rect.x + 1, rect.y, 'last commit', fg=theme.FG,
                   bg=theme.PANEL_ALT, attr=BOLD, max_x=rect.x + half - 1)
        screen.put(rect.x + half + 1, rect.y, 'working tree', fg=theme.FG,
                   bg=theme.PANEL_ALT, attr=BOLD, max_x=rect.x2 - 10)
        hint = 'n/p file  esc close '
        if rect.w > len(hint) + 30:
            screen.put(rect.x2 - len(hint), rect.y, hint, fg=theme.FG_DIM,
                       bg=theme.PANEL_ALT)
        for i in range(self.body_height()):
            index = self.top + i
            y = rect.y + 1 + i
            if index >= len(self.rows):
                break
            row = self.rows[index]
            kind = row[0]
            if kind == HEAD:
                self._file_head(screen, rect, y, row[1], row[2], row[3])
                continue
            if kind == RULE:
                screen.fill(rect.x, y, rect.w, 1, bg=theme.BG)
                screen.put(rect.x, y, '─' * rect.w, fg=theme.BORDER, bg=theme.BG,
                           max_x=rect.x2)
                continue
            ln_l, text_l, ln_r, text_r, row_kind = row
            if row_kind == GAP:
                screen.fill(rect.x, y, rect.w, 1, bg=theme.PANEL)
                screen.put(rect.x, y, '  ... %s ...' % text_r, fg=theme.FG_DIM,
                           bg=theme.PANEL, attr=DIM, max_x=rect.x2)
                continue
            DiffView._row(screen, rect.x, y, half, ln_l, text_l, row_kind,
                          self.cols['left'])
            DiffView._row(screen, rect.x + half, y, rect.w - half, ln_r, text_r,
                          row_kind, self.cols['right'])
            screen.put(rect.x + half - 1, y, '|', fg=theme.BORDER, bg=theme.BG)
        self._scrollbar(screen, rect, focused)

    @staticmethod
    def _file_head(screen, rect, y, path, letter, shut):
        screen.fill(rect.x, y, rect.w, 1, bg=theme.PANEL_ALT)
        colour = theme.git_colour(letter)
        screen.put(rect.x + 1, y, '▸' if shut else '▾', fg=theme.FG,
                   bg=theme.PANEL_ALT, attr=BOLD)
        screen.put(rect.x + 3, y, letter or ' ', fg=colour, bg=theme.PANEL_ALT,
                   attr=BOLD)
        screen.put(rect.x + 5, y, path, fg=theme.FG, bg=theme.PANEL_ALT,
                   attr=BOLD, max_x=rect.x2)
        if shut:
            note = 'folded '
            if rect.w > len(path) + len(note) + 10:
                screen.put(rect.x2 - len(note), y, note, fg=theme.FG_DIM,
                           bg=theme.PANEL_ALT)

    def _scrollbar(self, screen, rect, focused):
        h = self.body_height()
        total = len(self.rows)
        if h < 2 or total <= h or rect.w < 10:
            return
        x = rect.x2 - 1
        thumb = max(1, int(round(h * h / float(total))))
        thumb = min(thumb, h - 1)
        span = self.max_top()
        offset = 0 if span == 0 else int(round((h - thumb) * self.top / float(span)))
        offset = max(0, min(h - thumb, offset))
        screen.fill(x, rect.y + 1, 1, h, bg=theme.SCROLL_TRACK)
        screen.fill(x, rect.y + 1 + offset, 1, thumb,
                    bg=theme.SCROLL_THUMB_HL if focused else theme.SCROLL_THUMB)
