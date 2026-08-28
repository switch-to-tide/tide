"""Playing a file, by asking whatever player the machine already has.

Nothing here decodes audio. A command line player runs as a child process and
we drive it with signals: SIGSTOP to pause, SIGCONT to carry on, and a restart
to seek or to change speed. Where the player cannot seek by itself and the
format is one the standard library can rewrite, a trimmed temporary copy
stands in for seeking.

macOS always has afplay. Linux distributions vary, so several are tried in
turn, best first: the ones that can seek and change speed come before the ones
that can only play.
"""

import os
import signal
import subprocess
import time

from . import probe

ANY = None                       # a backend that plays whatever it is given
WAVE_ONLY = {'.wav', '.aiff', '.aif', '.au', '.snd', '.flac', '.ogg'}


class Backend(object):
    """One player, and what it can be asked to do."""

    def __init__(self, name, build, seek=False, rate=False, formats=ANY):
        self.name = name
        self.build = build
        self.seek = seek
        self.rate = rate
        self.formats = formats

    def plays(self, path):
        if self.formats is ANY:
            return True
        return os.path.splitext(path)[1].lower() in self.formats


def _ffplay(path, start, rate):
    args = ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet']
    if start:
        args += ['-ss', '%.3f' % start]
    if rate != 1.0:
        args += ['-af', 'atempo=%.3f' % rate]      # 0.5 to 2.0, our whole range
    return args + [path]


def _mpv(path, start, rate):
    args = ['mpv', '--no-video', '--really-quiet', '--no-terminal']
    if start:
        args.append('--start=%.3f' % start)
    if rate != 1.0:
        args.append('--speed=%.3f' % rate)
    return args + [path]


def _afplay(path, start, rate):
    args = ['afplay']
    if rate != 1.0:
        args += ['--rate', '%.3f' % rate, '--rQuality', '1']
    return args + [path]


def _sox(path, start, rate):
    args = ['play', '-q', path]
    if start:
        args += ['trim', '%.3f' % start]
    if rate != 1.0:
        args += ['tempo', '%.3f' % rate]           # tempo keeps the pitch
    return args


def _vlc(path, start, rate):
    args = ['cvlc', '--intf', 'dummy', '--play-and-exit', '--quiet']
    if start:
        args.append('--start-time=%.3f' % start)
    if rate != 1.0:
        args.append('--rate=%.3f' % rate)
    return args + [path]


def _plain(command):
    def build(path, _start, _rate):
        return [command, path]
    return build


BACKENDS = [
    Backend('ffplay', _ffplay, seek=True, rate=True),
    Backend('mpv', _mpv, seek=True, rate=True),
    Backend('afplay', _afplay, rate=True),         # macOS, always there
    Backend('play', _sox, seek=True, rate=True),   # sox
    Backend('cvlc', _vlc, seek=True, rate=True),
    Backend('paplay', _plain('paplay'), formats=WAVE_ONLY),
    Backend('pw-play', _plain('pw-play'), formats=WAVE_ONLY),
    Backend('aplay', _plain('aplay'), formats={'.wav'}),
]

_found = {}


def _have(command):
    if command not in _found:
        _found[command] = _which(command)
    return _found[command]


def _which(command):
    for folder in os.environ.get('PATH', '').split(os.pathsep):
        candidate = os.path.join(folder, command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def backend(path=None):
    """The best player on this machine for this file, or None."""
    for entry in BACKENDS:
        if _have(entry.name) and (path is None or entry.plays(path)):
            return entry
    return None


def forget():
    """Drop what we know about the machine; only the tests need this."""
    _found.clear()


class Player(object):
    """One file, playing or not, and where it has got to."""

    def __init__(self, path):
        self.path = path
        self.backend = backend(path)
        self.duration = probe.duration(path)
        self.rate = 1.0
        self.error = None
        self._process = None
        self._temp = None
        self._base = 0.0            # where this run started, in the file
        self._since = None          # when it started, on the wall clock
        self._done = False

    # ---------------- state ----------------
    @property
    def playing(self):
        return self._process is not None and self._since is not None

    @property
    def paused(self):
        return self._process is not None and self._since is None

    def can_seek(self):
        if self.backend is None:
            return False
        return self.backend.seek or probe.trim is not None and self._trimmable()

    def _trimmable(self):
        return os.path.splitext(self.path)[1].lower() in probe.STDLIB

    def position(self):
        """Where we are in the file, in seconds."""
        at = self._base
        if self._since is not None:
            at += (time.time() - self._since) * self.rate
        if self.duration:
            at = min(at, self.duration)
        return max(0.0, at)

    def finished(self):
        """True once the player has run out of file - or given up on it."""
        if self._process is None:
            return self._done
        code = self._process.poll()
        if code is None:
            return False
        at = self.position()
        self._reap()
        self._done = True
        self._since = None
        short = self.duration and at < self.duration - 0.5
        if code not in (0, -9, -15) and short:
            self.error = '%s could not play this file' % self.backend.name
            self._base = at                   # leave the bar where it stopped
        else:
            self._base = self.duration or at
        return True

    # ---------------- doing things ----------------
    def play(self, at=None):
        """Start (or restart) at a position. Returns True if sound is coming."""
        if self.backend is None:
            self.error = 'no audio player found'
            return False
        start = self.position() if at is None else max(0.0, at)
        if self.duration and start >= self.duration - 0.05:
            start = 0.0
        self.stop(keep_position=True)
        source, offset = self._source_for(start)
        args = self.backend.build(source, offset, self.rate)
        try:
            self._process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.error = 'could not start %s (%s)' % (self.backend.name, exc)
            self._process = None
            return False
        self.error = None
        self._done = False
        self._base = start
        self._since = time.time()
        return True

    def _source_for(self, start):
        """What to hand the player, and the offset it should be told about."""
        self._drop_temp()
        if not start or self.backend.seek:
            return self.path, start
        cut = probe.trim(self.path, start)          # the player cannot seek
        if cut is None:
            return self.path, 0.0
        self._temp = cut
        return cut, 0.0

    def pause(self):
        if not self.playing:
            return False
        self._base = self.position()
        self._since = None
        try:
            self._process.send_signal(signal.SIGSTOP)
        except Exception:
            pass
        return True

    def resume(self):
        if not self.paused:
            return False
        if self.finished():
            return self.play(0.0)
        try:
            self._process.send_signal(signal.SIGCONT)
        except Exception:
            return self.play(self._base)
        self._since = time.time()
        return True

    def toggle(self):
        if self.playing:
            return self.pause()
        if self.paused:
            return self.resume()
        return self.play()

    def seek(self, seconds):
        """Move to a position, playing on if we were playing."""
        was_playing = self.playing
        seconds = max(0.0, seconds)
        if self.duration:
            seconds = min(seconds, max(0.0, self.duration - 0.05))
        if was_playing or self.paused:
            self.stop(keep_position=True)
        self._base = seconds
        self._done = False
        if was_playing:
            return self.play(seconds)
        return True

    def nudge(self, delta):
        return self.seek(self.position() + delta)

    def set_rate(self, rate):
        """Change speed, carrying on from where we are."""
        if rate == self.rate:
            return False
        at = self.position()
        was_playing = self.playing
        self.rate = rate
        if was_playing:
            return self.play(at)
        self._base = at
        return True

    def stop(self, keep_position=False):
        """Silence, and let the child go."""
        if not keep_position:
            self._base = 0.0
        elif self._since is not None:
            self._base = self.position()
        self._since = None
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGCONT)   # a stopped child ignores
            except Exception:                         # anything but SIGKILL
                pass
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass
        self._drop_temp()

    def _reap(self):
        process = self._process
        self._process = None
        if process is not None:
            try:
                process.wait(timeout=0.1)
            except Exception:
                pass
        self._drop_temp()

    def _drop_temp(self):
        if self._temp:
            try:
                os.remove(self._temp)
            except OSError:
                pass
            self._temp = None
