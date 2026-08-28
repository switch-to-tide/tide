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
import shlex
import tempfile
import signal
import subprocess
import time

from . import probe

ANY = None                       # a backend that plays whatever it is given
WAVE_ONLY = {'.wav', '.aiff', '.aif', '.au', '.snd', '.flac', '.ogg'}


def _short(line, limit=70):
    return line[:limit] + ('…' if len(line) > limit else '')


# a sound library complaining about its own configuration, ten lines at a
# time, is not the thing worth showing
NOISE = ('ALSA lib', 'snd_func', 'snd_config', 'snd_pcm', 'Evaluate error',
         'no such file or directory: /usr/share/alsa')


def _noise(line):
    return any(part in line for part in NOISE)


# what it usually means when a player will not start on a machine like this
NO_DEVICE = ('audio open failed', 'no such audio device', 'cannot find card',
             'connection refused', 'no soundcards', 'device or resource busy',
             'unable to open slave', 'cannot open audio device',
             'failed to open file', 'no such device')


def no_sound_card(message):
    """Whether this looks like a machine with nowhere to send sound."""
    low = (message or '').lower()
    return any(part in low for part in NO_DEVICE)


class Backend(object):
    """One player, and what it can be asked to do."""

    def __init__(self, name, build, seek=False, rate=False, formats=ANY,
                 needs=None):
        self.name = name
        self.build = build
        self.seek = seek
        self.rate = rate
        self.formats = formats
        self.needs = needs or [name.split()[0]]

    def plays(self, path):
        if self.formats is ANY:
            return True
        return os.path.splitext(path)[1].lower() in self.formats


def _ffplay(path, start, rate):
    # 'error', not 'quiet': when it will not play we want to know why
    args = ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'error']
    if start:
        args += ['-ss', '%.3f' % start]
    if rate != 1.0:
        args += ['-af', 'atempo=%.3f' % rate]      # 0.5 to 2.0, our whole range
    return args + [path]


def _mpv(path, start, rate):
    args = ['mpv', '--no-video', '--no-terminal', '--msg-level=all=error']
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


RATE, CHANNELS = 48000, 2        # what the decoder hands the sound server


def _decode(path, start, rate, out_format='s16le'):
    """ffmpeg, decoding to plain samples at a rate everything understands."""
    parts = ['ffmpeg', '-v', 'error', '-nostdin']
    if start:
        parts += ['-ss', '%.3f' % start]
    parts += ['-i', path]
    if rate != 1.0:
        parts += ['-af', 'atempo=%.3f' % rate]
    return parts + ['-f', out_format, '-ar', str(RATE), '-ac', str(CHANNELS), '-']


def _pipe(sink):
    """ffmpeg decodes; the sink plays what comes down the pipe.

    Raw samples, not a wav: a wav written to a pipe has no length in its
    header, which some players read as an empty file and exit happily on
    without making a sound. The two run as two children of ours rather than
    through a shell, so a failure can be attributed to one of them.
    """
    def build(path, start, rate):
        return [_decode(path, start, rate), shlex.split(sink)]
    return build


def _pipe_wav(sink):
    """The same, for a player that insists on a container."""
    def build(path, start, rate):
        parts = ['ffmpeg', '-v', 'error', '-nostdin']
        if start:
            parts += ['-ss', '%.3f' % start]
        parts += ['-i', path]
        if rate != 1.0:
            parts += ['-af', 'atempo=%.3f' % rate]
        return [parts + ['-f', 'wav', '-'], shlex.split(sink)]
    return build


def _plain(command):
    def build(path, _start, _rate):
        return [command, path]
    return build


BACKENDS = [
    # first the players that can do everything themselves
    Backend('ffplay', _ffplay, seek=True, rate=True),
    Backend('mpv', _mpv, seek=True, rate=True),
    Backend('play', _sox, seek=True, rate=True),          # sox
    # then ffmpeg, which is on far more machines than ffplay is, decoding into
    # anything that can play a wav on its standard input
    Backend('ffmpeg|pacat',
            _pipe('pacat --playback --raw --format=s16le --rate=%d --channels=%d'
                  % (RATE, CHANNELS)),
            seek=True, rate=True, needs=['ffmpeg', 'pacat']),
    Backend('ffmpeg|pw-cat',
            _pipe('pw-cat --playback --raw --format s16 --rate %d --channels %d -'
                  % (RATE, CHANNELS)),
            seek=True, rate=True, needs=['ffmpeg', 'pw-cat']),
    Backend('ffmpeg|aplay',
            _pipe('aplay -q -t raw -f S16_LE -r %d -c %d -' % (RATE, CHANNELS)),
            seek=True, rate=True, needs=['ffmpeg', 'aplay']),
    Backend('ffmpeg|afplay', _pipe_wav('afplay /dev/stdin'), seek=True,
            rate=True, needs=['ffmpeg', 'afplay']),
    Backend('cvlc', _vlc, seek=True, rate=True),
    # and last the ones that only play: afplay is on every Mac, and the rest
    # are whatever the sound server on this Linux happens to be
    Backend('afplay', _afplay, rate=True),
    Backend('paplay', _plain('paplay'), formats=WAVE_ONLY),
    Backend('pw-play', _plain('pw-play'), formats=WAVE_ONLY),
    Backend('aplay', _plain('aplay'), formats={'.wav'}),
]

INSTALL_HINT = 'install ffmpeg, mpv or sox to play this'

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
        if all(_have(need) for need in entry.needs) and \
                (path is None or entry.plays(path)):
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
        self._feeder = None         # ffmpeg, when something is decoding for us
        self._notes = None          # what the players had to say for themselves
        self._expected = None       # how much audio this run should produce
        self.command = None         # what we actually ran, for diagnosis

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
        ran = time.time() - (self._since or time.time())
        said = self._said()
        self._reap()
        self._done = True
        self._since = None
        # a player that stopped long before the end has failed, whatever its
        # exit status was: a sink fed by a decoder that died exits happily
        early = self._expected is not None and ran < self._expected - 0.5
        if code in (-9, -15):
            self._base = at                   # we killed it ourselves
        elif code or early:
            self.error = said or ('%s stopped without playing it'
                                  % self.backend.name)
            self._base = at
        else:
            self._base = self.duration or at
        return True

    def _said(self):
        """The last useful line the player wrote, if it wrote one."""
        notes = self._notes
        if notes is None:
            return None
        try:
            notes.seek(0)
            text = notes.read().decode('utf-8', 'replace')
        except Exception:
            return None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        useful = [line for line in lines if not _noise(line)]
        if not useful:
            return _short(lines[0]) if lines else None
        # the first real complaint is the cause; anything after it is usually
        # the other half of the pipe reacting to it
        return _short(useful[0])

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
        self.command = args
        try:
            self._spawn(args)
        except OSError as exc:
            self.error = 'could not start %s (%s)' % (self.backend.name, exc)
            self._process = None
            return False
        self.error = None
        self._done = False
        self._base = start
        self._since = time.time()
        self._expected = self.duration - start if self.duration else None
        return True

    def _spawn(self, args):
        """One player, or a decoder feeding one, with their words kept."""
        self._notes = tempfile.TemporaryFile()
        if args and isinstance(args[0], list):
            feeder, sink = args
            self._feeder = subprocess.Popen(
                feeder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=self._notes, start_new_session=True)
            try:
                self._process = subprocess.Popen(
                    sink, stdin=self._feeder.stdout, stdout=subprocess.DEVNULL,
                    stderr=self._notes, start_new_session=True)
            finally:
                self._feeder.stdout.close()      # only the sink holds it now
            return
        self._process = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=self._notes, start_new_session=True)

    def use_source(self, path):
        """Play from somewhere else from now on - a copy of a deleted file."""
        self.path = path

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
        self._signal(signal.SIGSTOP)
        return True

    def resume(self):
        if not self.paused:
            return False
        if self.finished():
            return self.play(0.0)
        if not self._signal(signal.SIGCONT):
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
        self._signal(signal.SIGCONT)      # a stopped child ignores
        self._signal(signal.SIGKILL)      # anything but SIGKILL
        for name in ('_process', '_feeder'):
            process = getattr(self, name)
            setattr(self, name, None)
            if process is None:
                continue
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass
        self._drop_temp()

    def _signal(self, sig):
        """Signal the player, its decoder, and anything they started."""
        sent = False
        for process in (self._process, self._feeder):
            if process is None or process.poll() is not None:
                continue
            try:
                os.killpg(os.getpgid(process.pid), sig)
                sent = True
                continue
            except Exception:
                pass
            try:
                process.send_signal(sig)
                sent = True
            except Exception:
                pass
        return sent

    def _reap(self):
        for name in ('_process', '_feeder'):
            process = getattr(self, name)
            setattr(self, name, None)
            if process is None:
                continue
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
