"""`tide --audio-check`: say exactly what happens when a file is played.

Sound is the one thing tide cannot verify for itself - a player can exit
happily having made no noise at all. This prints everything that leads up to
that: what is installed, which of it was chosen, the command as it was run,
how long it stayed alive, and whatever it said on the way out.
"""

import os
import platform
import sys
import time

from . import EXTENSIONS, PREFERRED, PREFERRED_ALSO, survey
from . import probe
from .player import BACKENDS, Player, _have

WATCH = 4.0             # seconds to let it play before reporting


def _out(line=''):
    sys.stdout.write(line + '\n')


def _command(args):
    if args and isinstance(args[0], list):
        return ['  ' + ' '.join(args[0]), '    | ' + ' '.join(args[1])]
    return ['  ' + ' '.join(args)]


def run(path=None):
    from .. import __version__
    _out('tide %s - audio check' % __version__)
    _out()
    _out('machine   %s %s, python %s' % (platform.system(), platform.machine(),
                                         platform.python_version().strip()))
    found, missing = [], []
    for entry in BACKENDS:
        for need in entry.needs:
            (found if _have(need) else missing).append(need)
    _out('found     %s' % (', '.join(sorted(set(found))) or 'nothing'))
    _out('missing   %s' % (', '.join(sorted(set(missing) - set(found))) or '-'))
    full, plain = survey()
    _out('best      %s' % (full or plain or 'nothing can play sound here'))
    if not full:
        _out('          install %s or %s for seeking and speed'
             % (PREFERRED, PREFERRED_ALSO))
    if path is None:
        _out()
        _out('give it a file to try: tide --audio-check song.mp3')
        return 0 if (full or plain) else 1

    path = os.path.abspath(path)
    _out()
    if not os.path.isfile(path):
        _out('file      %s - not there' % path)
        return 1
    kind = os.path.splitext(path)[1].lower()
    _out('file      %s (%.1f KB)' % (path, os.path.getsize(path) / 1024.0))
    if kind not in EXTENSIONS:
        _out('          %s is not one tide opens as sound' % (kind or 'no suffix'))
    player = Player(path)
    _out('duration  %s' % ('%.1fs' % player.duration if player.duration
                           else 'unknown - the bar will not move'))
    if player.backend is None:
        _out('          nothing here can play it')
        return 1
    _out('backend   %s (seek: %s, speed: %s)'
         % (player.backend.name, 'yes' if player.backend.seek else 'no',
            'yes' if player.backend.rate else 'no'))
    _out()
    _out('playing it for %g seconds - you should hear something' % WATCH)
    started = time.time()
    if not player.play(0.0):
        _out('          it would not start: %s' % player.error)
        return 1
    for line in _command(player.command):
        _out(line)
    _out()
    while time.time() - started < WATCH:
        if player.finished():
            break
        time.sleep(0.1)
    alive = not player.finished()
    ran = time.time() - started
    if alive:
        _out('result    still playing after %.1fs - this looks right' % ran)
        _out('          if you heard nothing, the sound is going somewhere else:')
        _out('          check the output device, and that this machine has one')
    else:
        _out('result    it stopped after %.1fs, well before the end' % ran)
        if player.error:
            _out('said      %s' % player.error)
        else:
            _out('said      nothing at all')
        from .player import no_sound_card
        if no_sound_card(player.error):
            _out('          this machine has no sound output - a server usually')
            _out('          has none, and nothing tide can do will change that')
            if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
                import socket
                _out()
                _out('you are over ssh, so play it where you are sitting:')
                _out("  ssh %s 'cat %s' | afplay -"
                     % (socket.gethostname().split('.')[0], path))
        else:
            _out('          this is the failure - it exited without playing')
    player.stop()
    return 0 if alive else 1
