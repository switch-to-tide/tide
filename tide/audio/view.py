"""The tab an audio file opens into: a play button, a bar, and a speed.

It looks like an editor to the rest of the app - same tab, same close button,
same place on screen - but there is no document behind it and nothing about it
can be edited. All it owns is a `Player`, which it asks for a position when it
paints and tells to stop when the tab closes.
"""

import os

from .. import theme
from ..term import BOLD, DIM, Rect
from .player import Player

SPEEDS = [0.5, 1.0, 1.25, 1.5, 2.0]
STEP = 5.0                       # seconds an arrow key moves


def _clock(seconds):
    if seconds is None:
        return '--:--'
    seconds = max(0, int(seconds))
    return '%d:%02d' % (seconds // 60, seconds % 60)


class _AudioDoc(object):
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


class _Lang(object):
    name = 'Audio'
    tab_width = 4


class AudioView(object):
    """A read-only tab that plays a file."""

    is_diff = False
    is_audio = True

    def __init__(self, app, path):
        self.app = app
        self.path = os.path.abspath(path)
        self.title = os.path.basename(self.path)
        self.doc = _AudioDoc(self.path)
        self.hl = _Lang()
        self.use_spaces = True
        self.tab_width = 4
        self.indent_detected = True
        self.git_marks = {}
        self.top = 0
        self.rect = Rect(0, 0, 1, 1)
        self.text_rect = self.rect
        self.player = Player(self.path)
        self.play_span = None
        self.bar_span = None
        self.speed_span = None
        self.dragging = False

    # ---------------- what the app asks of a tab ----------------
    def refresh(self, force=False):
        return False

    def close(self):
        self.player.stop()

    def busy(self):
        """Whether this tab wants the screen repainted a few times a second."""
        return self.player.playing

    # ---------------- doing things ----------------
    def toggle(self):
        if self.player.finished():
            return self.player.play(0.0)
        return self.player.toggle()

    def cycle_speed(self, step=1):
        try:
            i = SPEEDS.index(self.player.rate)
        except ValueError:
            i = 1
        self.player.set_rate(SPEEDS[(i + step) % len(SPEEDS)])

    def seek_to_fraction(self, fraction):
        if not self.player.duration:
            return False
        if not self.player.can_seek():
            self.app.status('%s cannot seek; install ffmpeg or mpv for that'
                            % self.player.backend.name)
            return False
        return self.player.seek(max(0.0, min(1.0, fraction)) *
                                self.player.duration)

    # ---------------- keys and mouse ----------------
    def on_key(self, key):
        name = key.name
        if name == 'char' and key.char == ' ' and not key.ctrl:
            self.toggle()
        elif name == 'enter':
            self.toggle()
        elif name == 'left':
            self.player.nudge(-STEP)
        elif name == 'right':
            self.player.nudge(STEP)
        elif name == 'home':
            self.player.seek(0.0)
        elif name == 'char' and key.char.lower() == 's' and not key.ctrl:
            self.cycle_speed()
        else:
            return False
        return True

    def on_mouse(self, ev):
        on_bar = self._in(self.bar_span, ev)
        if (on_bar and ev.kind == 'press') or (self.dragging and ev.kind == 'drag'):
            x1, x2, _y = self.bar_span
            self.dragging = True
            self.seek_to_fraction((ev.x - x1) / float(max(1, x2 - x1 - 1)))
            return True
        if ev.kind == 'release':
            self.dragging = False
            return True
        if ev.kind != 'press':
            return False
        if self._in(self.play_span, ev):
            self.toggle()
            return True
        if self._in(self.speed_span, ev):
            self.cycle_speed()
            return True
        return True

    @staticmethod
    def _in(span, ev):
        return bool(span) and span[2] == ev.y and span[0] <= ev.x < span[1]

    # ---------------- painting ----------------
    def render(self, screen, rect, focused):
        self.rect = rect
        self.text_rect = rect
        player = self.player
        player.finished()                   # notice the end, and reap the child
        screen.fill(rect.x, rect.y, rect.w, rect.h, bg=theme.BG)
        width = min(60, max(20, rect.w - 8))
        left = rect.x + (rect.w - width) // 2
        top = rect.y + max(0, (rect.h - 9) // 2)

        self._centre(screen, rect, top, self.title, theme.FG, BOLD)
        kind = os.path.splitext(self.path)[1].lstrip('.').lower() or 'audio'
        note = '%s · %s' % (kind, _clock(player.duration))
        if player.backend is not None:
            note += ' · %s' % player.backend.name
        self._centre(screen, rect, top + 1, note, theme.FG_DIM, DIM)

        if player.backend is None:
            self._centre(screen, rect, top + 4,
                         'no audio player on this machine', theme.WARN, BOLD)
            self._centre(screen, rect, top + 5,
                         'install ffmpeg, mpv or sox to play this',
                         theme.FG_DIM, DIM)
            self.play_span = self.bar_span = self.speed_span = None
            return None

        label = '  ‖  pause  ' if player.playing else '  ▶  play  '
        bx = rect.x + (rect.w - len(label)) // 2
        by = top + 3
        screen.fill(bx, by, len(label), 1, bg=theme.PANEL_ALT)
        screen.put(bx, by, label, fg=theme.OK if not player.playing
                   else theme.TAB_MARK, bg=theme.PANEL_ALT, attr=BOLD)
        self.play_span = (bx, bx + len(label), by)

        self._bar(screen, left, top + 5, width, player)

        speed = ' speed  %g× ' % player.rate
        sx = rect.x + (rect.w - len(speed)) // 2
        sy = top + 7
        screen.fill(sx, sy, len(speed), 1, bg=theme.PANEL_ALT)
        screen.put(sx, sy, speed, fg=theme.STATUS_ACC, bg=theme.PANEL_ALT,
                   attr=BOLD)
        self.speed_span = (sx, sx + len(speed), sy)

        hint = 'space play/pause   ←/→ %ds   s speed' % int(STEP)
        self._centre(screen, rect, top + 8, hint, theme.FG_DIM, DIM)
        if player.error:
            self._centre(screen, rect, top + 9, player.error, theme.ERROR, 0)
        return None

    def _bar(self, screen, left, y, width, player):
        at = player.position()
        total = player.duration
        done = int(round(width * (at / total))) if total else 0
        done = max(0, min(width - 1, done))
        for i in range(width):
            char, colour = ('━', theme.STATUS_ACC) if i < done else \
                ('─', theme.BORDER)
            screen.put(left + i, y, char, fg=colour, bg=theme.BG)
        if total:
            screen.put(left + done, y, '●', fg=theme.FG, bg=theme.BG, attr=BOLD)
        self.bar_span = (left, left + width, y)
        screen.put(left, y + 1, _clock(at), fg=theme.FG_DIM, bg=theme.BG)
        end = _clock(total)
        screen.put(left + width - len(end), y + 1, end, fg=theme.FG_DIM,
                   bg=theme.BG)

    @staticmethod
    def _centre(screen, rect, y, text, fg, attr):
        if y < rect.y or y >= rect.y2:
            return
        x = rect.x + max(0, (rect.w - len(text)) // 2)
        screen.put(x, y, text, fg=fg, bg=theme.BG, attr=attr, max_x=rect.x2)
