"""Side by side diff views, opened as read-only tabs.

Two kinds share everything but where their two sides come from:

  * a conflict diff - the buffer you are editing against the file on disk,
    which is what the "changed on disk" question offers as a third answer;
  * a git diff - the committed version against the working file, either whole
    or trimmed to the changed parts.

Each side is a `Source`: something that can hand over lines and a token that
changes when those lines do, so the view knows when to rebuild itself.
"""

import difflib
import io
import os

from . import theme
from .keys import SHIFT
from .term import BOLD, DIM, Rect, char_width

TEXT_X = 8            # line number and marker sit before the text

EQUAL = 'equal'
ADDED = 'add'
REMOVED = 'del'
CHANGED = 'change'
GAP = 'gap'

CONTEXT = 3          # lines kept either side of a change in the trimmed view


def _expand(text):
    return text.replace('\t', '    ')


class Source(object):
    """One side of a diff: a cheap token, and the lines behind it.

    The token is what gets polled, so a view that is up to date costs a few
    stat calls and nothing else - no file reads, no git processes.
    """

    def __init__(self, label, token, lines):
        self.label = label
        self._token = token
        self._lines = lines

    def token(self):
        try:
            return self._token()
        except Exception:
            return None

    def lines(self):
        try:
            return self._lines()
        except Exception:
            return ['']


def _stat_token(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)),
            getattr(st, 'st_ctime_ns', int(st.st_ctime * 1e9)), st.st_size)


def buffer_source(editor, label=None):
    doc = editor.doc
    return Source(label or ('%s (editing)' % doc.name),
                  lambda: doc._version, lambda: list(doc.lines))


def disk_source(path, label=None):
    def read():
        try:
            with io.open(path, 'r', encoding='utf-8', errors='replace',
                         newline='') as f:
                text = f.read()
        except OSError:
            return ['(the file is not on disk)']
        return text.replace('\r\n', '\n').split('\n')
    return Source(label or ('%s (on disk)' % os.path.basename(path)),
                  lambda: _stat_token(path), read)


def rev_source(git, path, rev='HEAD', label=None):
    """A committed version of the file. Never fetches; the token moves when
    the repository does, so a pull or a fetch refreshes the view."""
    def read():
        text = git.file_at_rev(path, rev)
        if text is None:
            return ['(not in %s)' % rev]
        return text.replace('\r\n', '\n').split('\n')
    return Source(label or rev, lambda: (rev, git.state_token()), read)


def head_source(git, path, label=None):
    return rev_source(git, path, 'HEAD', label or 'last commit')


def align(left, right):
    """Pair the two sides up: [(left_no, left_text, right_no, right_text, kind)].

    A line number of None means that side has nothing there.
    """
    rows = []
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                rows.append((i1 + k + 1, left[i1 + k], j1 + k + 1, right[j1 + k], EQUAL))
        elif tag == 'replace':
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                li = i1 + k if i1 + k < i2 else None
                rj = j1 + k if j1 + k < j2 else None
                rows.append((None if li is None else li + 1,
                             '' if li is None else left[li],
                             None if rj is None else rj + 1,
                             '' if rj is None else right[rj],
                             CHANGED if (li is not None and rj is not None)
                             else (REMOVED if li is not None else ADDED)))
        elif tag == 'delete':
            for k in range(i1, i2):
                rows.append((k + 1, left[k], None, '', REMOVED))
        elif tag == 'insert':
            for k in range(j1, j2):
                rows.append((None, '', k + 1, right[k], ADDED))
    return rows


def trim(rows, context=CONTEXT):
    """Keep only the changed parts, with a little context and gap markers."""
    keep = [False] * len(rows)
    for i, row in enumerate(rows):
        if row[4] != EQUAL:
            for j in range(max(0, i - context), min(len(rows), i + context + 1)):
                keep[j] = True
    out = []
    skipped = 0
    for i, row in enumerate(rows):
        if keep[i]:
            if skipped:
                out.append((None, '', None, '%d unchanged lines' % skipped, GAP))
                skipped = 0
            out.append(row)
        else:
            skipped += 1
    if skipped and out:
        out.append((None, '', None, '%d unchanged lines' % skipped, GAP))
    return out


class _DiffDoc(object):
    """Just enough of a Document for the parts of the app that ask."""

    path = None
    dirty = False
    readonly = True
    disk_stamp = None
    autosave_blocked = False
    disk_missing = False

    def __init__(self):
        self.cursor = (0, 0)
        self.lines = ['']

    def selection(self):
        return None


class _Lang(object):
    name = 'Diff'
    tab_width = 4


class DiffView(object):
    """A read-only tab showing two versions of a file next to each other."""

    is_diff = True

    def __init__(self, app, key, title, left, right, minimal=False, alt_left=None):
        self.app = app
        self.key = key                # identifies the tab, so it is reused
        self.title = title
        self.left = left
        self.alt_left = alt_left      # e.g. the upstream branch, if there is one
        self.right = right
        self.minimal = minimal
        self.path = None
        self.doc = _DiffDoc()
        self.hl = _Lang()
        self.use_spaces = True
        self.tab_width = 4
        self.indent_detected = True
        self.git_marks = {}
        self.top = 0
        self.cols = {'left': 0, 'right': 0}   # horizontal scroll, one per side
        self.widest = {'left': 0, 'right': 0}
        self.side = 'left'                    # what the arrow keys scroll
        self.rows = []
        self.changes = 0
        self.rect = Rect(0, 0, 1, 1)
        self._tokens = None
        self.refresh()

    # ---------------- content ----------------
    def refresh(self, force=False):
        """Rebuild only when one of the two sides has actually moved."""
        tokens = (self.left.token(), self.right.token(), self.minimal,
                  self.left.label)
        if not force and tokens == self._tokens:
            return False
        self._tokens = tokens
        rows = align(self.left.lines(), self.right.lines())
        self.changes = sum(1 for r in rows if r[4] != EQUAL)
        self.rows = trim(rows) if self.minimal else rows
        if not self.rows:
            self.rows = [(None, '', None, 'the two versions are identical', GAP)]
        self.widest = {
            'left': max([len(_expand(r[1])) for r in self.rows] or [0]),
            'right': max([len(_expand(r[3])) for r in self.rows if r[4] != GAP] or [0]),
        }
        self.top = max(0, min(self.top, max(0, len(self.rows) - 1)))
        self._clamp_columns()
        return True

    def swap_left(self):
        """Compare against the other committed side (last commit / upstream)."""
        if self.alt_left is None:
            return False
        self.left, self.alt_left = self.alt_left, self.left
        self.refresh(force=True)
        return True

    def toggle_minimal(self):
        self.minimal = not self.minimal
        self.title = self.title.replace(' (all)', ' (changes)') if self.minimal \
            else self.title.replace(' (changes)', ' (all)')
        self.refresh(force=True)

    # ---------------- viewport ----------------
    def body_height(self):
        return max(1, self.rect.h - 1)

    def pane_width(self):
        """Columns of text visible in one half, after the number and marker."""
        return max(1, self.rect.w // 2 - TEXT_X - 1)

    def max_col(self, side):
        return max(0, self.widest[side] - self.pane_width())

    def _clamp_columns(self):
        for side in ('left', 'right'):
            self.cols[side] = max(0, min(self.cols[side], self.max_col(side)))

    def scroll_across(self, side, delta):
        """Horizontal scroll of one half only; the other stays where it is."""
        self.side = side
        self.cols[side] = max(0, min(self.max_col(side), self.cols[side] + delta))

    def max_top(self):
        return max(0, len(self.rows) - self.body_height())

    def scroll(self, delta):
        self.top = max(0, min(self.max_top(), self.top + delta))

    def ensure_visible(self):
        self.top = max(0, min(self.top, self.max_top()))

    # ---------------- input ----------------
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
            if key.shift:
                self.cols[self.side] = 0
            else:
                self.top = 0
        elif name == 'end':
            self.top = self.max_top()
        elif name == 'left':
            self.scroll_across(self.side, -8)
        elif name == 'right':
            self.scroll_across(self.side, 8)
        elif name == 'tab':
            self.side = 'right' if self.side == 'left' else 'left'
        elif name == 'char' and key.char == 'm' and not key.ctrl and not key.alt:
            self.toggle_minimal()
        elif name == 'char' and key.char == 'r' and not key.ctrl and not key.alt:
            if not self.swap_left():
                return False
        elif name == 'char' and key.char.lower() == 'n' and not key.ctrl:
            self.jump_to_change(1)
        elif name == 'char' and key.char.lower() == 'p' and not key.ctrl:
            self.jump_to_change(-1)
        else:
            return False
        return True

    def jump_to_change(self, direction):
        rows = self.rows
        i = self.top + (1 if direction > 0 else -1)
        while 0 <= i < len(rows):
            if rows[i][4] not in (EQUAL, GAP):
                self.top = max(0, min(self.max_top(), i))
                return
            i += direction

    def side_at(self, x):
        return 'left' if x < self.rect.x + self.rect.w // 2 else 'right'

    def on_mouse(self, ev):
        side = self.side_at(ev.x)
        if ev.kind in ('wheel_left', 'wheel_right'):
            self.scroll_across(side, -8 if ev.kind == 'wheel_left' else 8)
            return True
        if ev.kind in ('wheel_up', 'wheel_down'):
            if ev.mods & SHIFT:            # the usual stand in for a sideways wheel
                self.scroll_across(side, -8 if ev.kind == 'wheel_up' else 8)
            else:
                self.scroll(-3 if ev.kind == 'wheel_up' else 3)
            return True
        if ev.kind == 'press':
            self.side = side               # arrows now scroll this half
            return True
        return False

    # ---------------- painting ----------------
    def render(self, screen, rect, focused):
        self.rect = rect
        self.ensure_visible()
        self._clamp_columns()          # the pane may have changed width
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.BG)
        half = rect.w // 2
        # header
        screen.fill(rect.x, rect.y, rect.w, 1, bg=theme.PANEL_ALT)
        screen.put(rect.x + 1, rect.y, self.left.label, fg=theme.FG,
                   bg=theme.PANEL_ALT, attr=BOLD, max_x=rect.x + half - 1)
        screen.put(rect.x + half + 1, rect.y, self.right.label, fg=theme.FG,
                   bg=theme.PANEL_ALT, attr=BOLD, max_x=rect.x2 - 10)
        shift = ''
        if self.cols['left'] or self.cols['right']:
            shift = 'col %d|%d  ' % (self.cols['left'] + 1, self.cols['right'] + 1)
        note = shift + ('%d changes ' % self.changes if self.changes else 'identical ')
        if rect.w > 30:
            screen.put(rect.x2 - len(note), rect.y, note, fg=theme.FG_DIM,
                       bg=theme.PANEL_ALT)
        for i in range(self.body_height()):
            index = self.top + i
            y = rect.y + 1 + i
            if index >= len(self.rows):
                break
            ln_l, text_l, ln_r, text_r, kind = self.rows[index]
            if kind == GAP:
                screen.fill(rect.x, y, rect.w, 1, bg=theme.PANEL)
                label = '  ... %s ...' % text_r
                screen.put(rect.x, y, label, fg=theme.FG_DIM, bg=theme.PANEL,
                           attr=DIM, max_x=rect.x2)
                continue
            self._row(screen, rect.x, y, half, ln_l, text_l, kind,
                      self.cols['left'])
            self._row(screen, rect.x + half, y, rect.w - half, ln_r, text_r, kind,
                      self.cols['right'])
            screen.put(rect.x + half - 1, y, '|', fg=theme.BORDER, bg=theme.BG)
        return None

    @staticmethod
    def _row(screen, x, y, width, lineno, text, kind, offset):
        if kind == EQUAL:
            fg, mark, bg = theme.FG, ' ', theme.BG
        elif kind == CHANGED:
            fg, mark, bg = theme.GIT_LINE_MODIFIED, '~', theme.BG_ALT
        elif kind == REMOVED:
            fg, mark, bg = theme.GIT_LINE_DELETED, '-', theme.BG_ALT
        else:
            fg, mark, bg = theme.GIT_LINE_ADDED, '+', theme.BG_ALT
        if lineno is None:                 # this side has nothing here
            screen.fill(x, y, max(0, width - 1), 1, bg=theme.PANEL)
            return
        screen.fill(x, y, max(0, width - 1), 1, bg=bg)
        screen.put(x, y, str(lineno).rjust(5), fg=theme.LINENO, bg=bg)
        screen.put(x + 6, y, mark, fg=fg, bg=bg, attr=BOLD)
        body = _expand(text)[offset:]
        if offset and text:
            screen.put(x + TEXT_X - 1, y, '<', fg=theme.FG_DIM, bg=bg)
        screen.put(x + TEXT_X, y, body, fg=fg, bg=bg, max_x=x + width - 1)
