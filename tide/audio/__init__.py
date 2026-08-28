"""Audio playback, kept in its own corner.

Importing this package costs a set literal and nothing else: the player and
the view are only pulled in when an audio file is actually opened, so a
session that never touches one never runs a line of this code. The setting
`audio` turns even that off.
"""

import os

# what tide will open as sound rather than refuse as binary
EXTENSIONS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.oga', '.opus',
              '.aiff', '.aif', '.aifc', '.au', '.wma', '.mp4a', '.caf'}


def is_audio(path):
    return os.path.splitext(path or '')[1].lower() in EXTENSIONS


def open_view(app, path):
    """An audio tab for this file.

    Named so it cannot collide with the `view` submodule it imports, which is
    pulled in here on first use and never before.
    """
    from .view import AudioView
    return AudioView(app, path)


# what to tell people to install: one package that can do everything
PREFERRED = 'ffmpeg'
PREFERRED_ALSO = 'mpv'


def survey():
    """What this machine can do: (full, plain).

    `full` is a player that can seek and change speed - the whole feature.
    `plain` is one that can only play from the start. Either may be None.
    Nothing here is imported until something asks.
    """
    from .player import BACKENDS, _have
    full = plain = None
    for entry in BACKENDS:
        if not all(_have(need) for need in entry.needs):
            continue
        if entry.seek and entry.rate:
            full = full or entry.name
        else:
            plain = plain or entry.name
    return full, plain


def available():
    """Whether anything on this machine can play audio at all."""
    return any(survey())
