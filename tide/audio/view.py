"""The tab an audio file opens into: a play button, a bar, and a speed.

It looks like an editor to the rest of the app - same tab, same close button,
same place on screen - but there is no document behind it and nothing about it
can be edited. All it owns is a `Player`, which it asks for a position when it
paints and tells to stop when the tab closes.
"""

import os
import shutil
import tempfile
import time

from .. import theme
from ..term import BOLD, DIM, Rect
from . import probe
from .player import Player

SPEEDS = [0.5, 1.0, 1.25, 1.5, 2.0]
STEP = 5.0                       # seconds an arrow key moves
CHECK_EVERY = 0.8                # how often the file is looked for
RESCUE_LIMIT = 512 * 1024 * 1024  # do not copy more than this to save a file


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

    # the app never watches or saves a sound tab, but a document is asked
    # these things in enough places that answering plainly is safer than
    # trusting every caller to check first
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
        raise IOError('a sound file is not text')


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
        self.player = self._make_player()
        self.play_span = None
        self.bar_span = None
        self.speed_span = None
        self.dragging = False
        self.missing = False
        self.rescued = None          # our own copy, once the file is deleted
        self._checked = 0.0
        self._stamp = self._disk_stamp()
        # an open handle keeps the bytes alive on disk even if the file is
        # unlinked, which is what lets a deleted file go on playing
        try:
            self._fd = os.open(self.path, os.O_RDONLY)
        except OSError:
            self._fd = None

    def _make_player(self):
        """A player here, or a link to the sink where you are sitting."""
        port = 0
        try:
            port = int(self.app.settings.get('audio_sink_port') or 0)
        except (TypeError, ValueError):
            port = 0
        if port:
            from .remote import Link
            return Link(self.path, port, duration=probe.duration(self.path))
        return Player(self.path)

    # ---------------- the file underneath ----------------
    def _disk_stamp(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_ino, st.st_size,
                getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))

    def check_disk(self, force=False):
        """Notice the file going away, or coming back as something else."""
        now = time.time()
        if not force and now - self._checked < CHECK_EVERY:
            return False
        self._checked = now
        stamp = self._disk_stamp()
        if stamp is None:
            return self._went_missing()
        if self.missing or stamp != self._stamp:
            return self._came_back(stamp)
        return False

    def _went_missing(self):
        if self.missing:
            return False
        self.missing = True
        self._rescue()               # so it can still be played and replayed
        return True

    def _came_back(self, stamp):
        """The file is there again - the same one, or a new one in its place."""
        was_missing = self.missing
        self._stamp = stamp
        self.missing = False
        self._drop_rescue()
        try:
            if self._fd is not None:
                os.close(self._fd)
        except OSError:
            pass
        try:
            self._fd = os.open(self.path, os.O_RDONLY)
        except OSError:
            self._fd = None
        self.player.use_source(self.path)
        self.player.duration = probe.duration(self.path)
        if not was_missing and self.player.playing:
            return True              # it was rewritten under us; carry on
        return True

    def _rescue(self):
        """Copy what is still open into a file of our own, while we can."""
        if self._fd is None or self.rescued:
            return
        try:
            size = os.fstat(self._fd).st_size
            if size > RESCUE_LIMIT:
                return
            handle, out = tempfile.mkstemp(prefix='tide-kept-',
                                           suffix=os.path.splitext(self.path)[1])
            os.lseek(self._fd, 0, os.SEEK_SET)
            with os.fdopen(handle, 'wb') as target:
                while True:
                    chunk = os.read(self._fd, 1 << 20)
                    if not chunk:
                        break
                    target.write(chunk)
        except Exception:
            self._drop_rescue()
            return
        self.rescued = out
        self.player.use_source(out)   # everything from here plays the copy

    def _drop_rescue(self):
        if self.rescued:
            try:
                os.remove(self.rescued)
            except OSError:
                pass
            self.rescued = None
        self.player.use_source(self.path)

    def tab_mark(self):
        """What the tab strip should show beside the name."""
        self.check_disk()
        return ('!', theme.ERROR) if self.missing else None

    # ---------------- what the app asks of a tab ----------------
    def refresh(self, force=False):
        return False

    def close(self):
        self.player.stop()
        self._drop_rescue()
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def busy(self):
        """Whether this tab wants the screen repainted a few times a second."""
        return self.player.playing

    # ---------------- doing things ----------------
    def lost(self):
        """Deleted, with no copy of our own: there is nothing left to play."""
        return self.missing and not self.rescued

    def toggle(self):
        if self.lost():
            if self.player.playing:
                return self.player.pause()     # let what is playing be stopped
            self.app.status('%s has been deleted' % self.title)
            return False
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
        if self.lost() or not self.player.duration:
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
        elif name in ('left', 'right', 'home') and self.lost():
            self.app.status('%s has been deleted' % self.title)
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

        self.check_disk()
        self._centre(screen, rect, top, self.title, theme.FG, BOLD)
        kind = os.path.splitext(self.path)[1].lstrip('.').lower() or 'audio'
        note = '%s · %s' % (kind, _clock(player.duration))
        if player.backend is not None:
            note += ' · %s' % player.backend.name
        self._centre(screen, rect, top + 1, note, theme.FG_DIM, DIM)

        if player.backend is None:
            self._centre(screen, rect, top + 4,
                         'nothing on this machine can play sound', theme.WARN,
                         BOLD)
            self._centre(screen, rect, top + 5,
                         'install ffmpeg (or mpv, or sox) and open it again',
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
        if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
            self._centre(screen, rect, top + 9,
                         'over ssh: the sound comes out of the machine tide is '
                         'running on', theme.FG_DIM, DIM)
        if self.missing:
            kept = 'this copy is gone when the tab closes' if self.rescued \
                else 'it will play to the end, but cannot start again'
            self._centre(screen, rect, top + 10,
                         '!  the file has been deleted', theme.ERROR, BOLD)
            self._centre(screen, rect, top + 11, kept, theme.FG_DIM, DIM)
        elif player.error:
            from .player import no_sound_card
            self._centre(screen, rect, top + 10, player.error, theme.ERROR, 0)
            if no_sound_card(player.error):
                self._centre(screen, rect, top + 11,
                             'this machine has no sound output - a server '
                             'usually has none', theme.FG_DIM, DIM)
                if self.remote():
                    self._centre(screen, rect, top + 12,
                                 'to hear it where you are sitting, run this '
                                 'on your own machine:', theme.FG_DIM, DIM)
                    self._centre(screen, rect, top + 13, self.local_hint(),
                                 theme.FG, 0)
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
    def remote():
        return bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'))

    def local_hint(self):
        """How to hear this file on the machine you are sitting at."""
        import socket
        try:
            host = socket.gethostname().split('.')[0]
        except Exception:
            host = 'this-host'
        return "ssh %s 'cat %s' | afplay -" % (host, self.path)

    @staticmethod
    def _centre(screen, rect, y, text, fg, attr):
        if y < rect.y or y >= rect.y2:
            return
        x = rect.x + max(0, (rect.w - len(text)) // 2)
        screen.put(x, y, text, fg=fg, bg=theme.BG, attr=attr, max_x=rect.x2)
