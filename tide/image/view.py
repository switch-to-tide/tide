"""A read-only tab that shows a picture.

Every cell is two pixels: the upper half block, painted in the colour of the
pixel above with the pixel below behind it. That makes an image ordinary
coloured text, which is the whole point - it scrolls, splits, redraws and
travels down an ssh connection exactly as the rest of tide does, with no
terminal doing anything special, and it looks the same everywhere.
"""

import os
import time

from .. import theme
from ..term import BOLD, DIM, Rect
from .png import Unsupported, read

BLOCK = '▀'                  # upper half block
CHECK_EVERY = 1.0
ZOOMS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)


def _packed(rgb):
    """A colour the screen understands: 24 bit, as the renderer packs them."""
    return 0x1000000 | (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


class _ImageDoc(object):
    """Just enough of a document for the parts of the app that ask."""

    dirty = False
    readonly = True
    disk_stamp = None
    autosave_blocked = True
    disk_missing = False

    def __init__(self, path):
        self.path = path
        self.cursor = (0, 0)
        self.lines = ['']

    def selection(self):
        return None

    def disk_status(self):
        return 'same' if os.path.exists(self.path) else 'missing'

    def text(self):
        return ''

    def file_key(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    def save(self, path=None, force=False):
        raise IOError('an image is not text')


class _Lang(object):
    name = 'Image'
    tab_width = 4


class ImageView(object):
    """A picture in a tab, fitted to the pane and read only."""

    is_diff = False
    is_image = True

    def __init__(self, app, path):
        self.app = app
        self.path = os.path.abspath(path)
        self.title = os.path.basename(self.path)
        self.doc = _ImageDoc(self.path)
        self.hl = _Lang()
        self.use_spaces = True
        self.tab_width = 4
        self.indent_detected = True
        self.git_marks = {}
        self.top = 0
        self.left = 0
        self.rect = Rect(0, 0, 1, 1)
        self.text_rect = self.rect
        self.image = None
        self.trouble = ''
        self.zoom = None              # None means fit the pane
        self.pan = (0.5, 0.5)         # what sits in the middle, 0..1
        self.missing = False
        self._checked = 0.0
        self._stamp = self._disk_stamp()
        self._grid = None             # the last cell grid, and what made it
        self.load()

    # ---------------- the file underneath ----------------
    def load(self):
        started = time.time()
        try:
            self.image = read(self.path)
            self.trouble = ''
        except Unsupported as exc:
            self.image, self.trouble = None, str(exc)
        except (IOError, OSError) as exc:
            self.image, self.trouble = None, exc.strerror or str(exc)
        except Exception as exc:                # a malformed file, whatever it is
            self.image, self.trouble = None, 'could not be read (%s)' % exc
        self._grid = None
        if self.image is not None and time.time() - started > 0.4:
            self.app.status('%s: %d by %d' % (self.title, self.image.width,
                                              self.image.height))

    def _disk_stamp(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_ino, st.st_size,
                getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))

    def check_disk(self, force=False):
        """Notice the file going away, or being written again."""
        now = time.time()
        if not force and now - self._checked < CHECK_EVERY:
            return False
        self._checked = now
        stamp = self._disk_stamp()
        if stamp is None:
            if self.missing:
                return False
            self.missing = True             # what was decoded stays on screen
            return True
        if self.missing or stamp != self._stamp:
            self._stamp = stamp
            self.missing = False
            self.load()
            return True
        return False

    def tab_mark(self):
        self.check_disk()
        return ('!', theme.ERROR) if self.missing else None

    # ---------------- what the app asks of a tab ----------------
    def refresh(self, force=False):
        return False

    def close(self):
        self.image = None
        self._grid = None

    def busy(self):
        return False

    # ---------------- looking at it ----------------
    def step_zoom(self, direction):
        """In and out, from wherever the fit happens to be."""
        here = self.zoom if self.zoom is not None else self._fit_scale()
        if direction > 0:
            nxt = [z for z in ZOOMS if z > here * 1.01]
            self.zoom = nxt[0] if nxt else ZOOMS[-1]
        else:
            nxt = [z for z in ZOOMS if z < here * 0.99]
            self.zoom = nxt[-1] if nxt else ZOOMS[0]
        self._grid = None

    def fit(self):
        self.zoom = None
        self.pan = (0.5, 0.5)
        self._grid = None

    def move(self, dx, dy):
        x, y = self.pan
        self.pan = (min(1.0, max(0.0, x + dx)), min(1.0, max(0.0, y + dy)))
        self._grid = None

    def _fit_scale(self):
        """The scale that puts the whole picture in the pane."""
        if self.image is None:
            return 1.0
        r = self._picture_rect()
        return min(r.w / float(self.image.width),
                   (r.h * 2) / float(self.image.height))

    def _picture_rect(self):
        """The pane, less the line that says what this is."""
        r = self.rect
        return Rect(r.x, r.y, max(1, r.w), max(1, r.h - 1))

    def on_key(self, key):
        name = key.name
        ch = key.char if name == 'char' else ''
        if ch in ('+', '='):
            self.step_zoom(1)
        elif ch in ('-', '_'):
            self.step_zoom(-1)
        elif ch in ('f', '0'):
            self.fit()
        elif ch == 'r':
            self.load()
        elif name == 'left':
            self.move(-0.1, 0)
        elif name == 'right':
            self.move(0.1, 0)
        elif name == 'up':
            self.move(0, -0.1)
        elif name == 'down':
            self.move(0, 0.1)
        else:
            return False
        return True

    def on_mouse(self, ev):
        if ev.kind == 'wheel_up':
            self.step_zoom(1)
            return True
        if ev.kind == 'wheel_down':
            self.step_zoom(-1)
            return True
        return ev.kind in ('press', 'drag', 'release')

    # ---------------- painting ----------------
    def _cells(self, cols, rows):
        """The picture as (top, bottom) colours, one pair per cell.

        Nearest neighbour, which is all a terminal's worth of pixels needs,
        and cheap enough to redo whenever the pane changes shape.
        """
        image = self.image
        scale = self.zoom if self.zoom is not None else self._fit_scale()
        wide = max(1, min(cols, int(image.width * scale)))
        tall = max(2, min(rows * 2, int(image.height * scale)))
        # which part of the picture is on screen, when it does not all fit:
        # as many pixels as the cells can hold, put where the panning says
        seen_w = min(image.width, max(1, int(wide / scale)))
        seen_h = min(image.height, max(1, int(tall / scale)))
        off_x = int((image.width - seen_w) * self.pan[0])
        off_y = int((image.height - seen_h) * self.pan[1])
        xs = [off_x + min(image.width - 1, int(x / scale)) for x in range(wide)]
        xs = [min(image.width - 1, x) * 3 for x in xs]
        grid = []
        for line in range(0, tall - 1, 2):
            top_y = min(image.height - 1, off_y + int(line / scale))
            low_y = min(image.height - 1, off_y + int((line + 1) / scale))
            top_row, low_row = image.rows[top_y], image.rows[low_y]
            grid.append([(top_row[x:x + 3], low_row[x:x + 3]) for x in xs])
        return grid

    def render(self, screen, rect, focused):
        self.rect = rect
        self.text_rect = rect
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.BG)
        self.check_disk()
        area = self._picture_rect()
        if self.image is None:
            self._say(screen, area, self.trouble or 'nothing to show')
            self._footer(screen, rect)
            return None
        key = (area.w, area.h, self.zoom, self.pan)
        if self._grid is None or self._grid[0] != key:
            self._grid = (key, self._cells(area.w, area.h))
        grid = self._grid[1]
        top = area.y + max(0, (area.h - len(grid)) // 2)
        for i, line in enumerate(grid):
            y = top + i
            if y >= area.y2:
                break
            x0 = area.x + max(0, (area.w - len(line)) // 2)
            for j, (upper, lower) in enumerate(line):
                screen.set_cell(x0 + j, y,
                                (BLOCK, _packed(upper), _packed(lower), 0))
        self._footer(screen, rect)
        return None

    def _say(self, screen, area, text):
        y = area.y + area.h // 2
        message = text[:max(0, area.w - 2)]
        screen.put(area.x + max(0, (area.w - len(message)) // 2), y, message,
                   fg=theme.ERROR, bg=theme.BG, max_x=area.x2)

    def _footer(self, screen, rect):
        y = rect.y2 - 1
        screen.fill(rect.x, y, rect.w, 1, bg=theme.BG)
        if self.image is None:
            left = self.title
        else:
            scale = self.zoom if self.zoom is not None else self._fit_scale()
            left = '%s   %d × %d   %s   %d%%' % (
                self.title, self.image.width, self.image.height,
                self.image.kind, round(scale * 100))
        if self.missing:
            left += '   deleted on disk'
        hint = '+ - zoom   f fit   ↑↓←→ pan '
        room = rect.w > len(left) + len(hint) + 4
        screen.put(rect.x + 1, y, left, fg=theme.FG_DIM, bg=theme.BG, attr=DIM,
                   max_x=rect.x2 - (len(hint) + 1 if room else 1))
        if room:
            screen.put(rect.x2 - len(hint), y, hint, fg=theme.FG_DIM,
                       bg=theme.BG, attr=DIM, max_x=rect.x2)
