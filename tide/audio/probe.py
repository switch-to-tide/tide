"""How long a file is, and how to start one part way through.

Both jobs are done with whatever the machine already has: ffprobe if ffmpeg
is installed, afinfo on macOS, and the standard library for the formats it
can read. Nothing here is required for playback - a file whose length we
cannot work out simply shows elapsed time instead of a bar.
"""

import os
import struct
import subprocess
import tempfile

TRIM_LIMIT = 128 * 1024 * 1024      # do not copy more than this to seek
STDLIB = {'.wav': 'wave', '.aiff': 'aifc', '.aif': 'aifc', '.aifc': 'aifc',
          '.au': 'sunau', '.snd': 'sunau'}


def _reader(path):
    """The standard library module that can open this file, if any."""
    name = STDLIB.get(os.path.splitext(path)[1].lower())
    if name is None:
        return None
    try:
        return __import__(name)
    except ImportError:                 # 3.13 dropped aifc and sunau
        return None


def _run(args, timeout=4.0):
    try:
        out = subprocess.check_output(args, stderr=subprocess.DEVNULL,
                                      timeout=timeout)
    except Exception:
        return None
    return out.decode('utf-8', 'replace')


def duration(path):
    """Seconds of audio, or None if nothing here can say."""
    module = _reader(path)
    if module is not None:
        try:
            with module.open(path, 'rb') as f:
                rate = f.getframerate()
                if rate:
                    return f.getnframes() / float(rate)
        except Exception:
            pass
    out = _run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=nw=1:nk=1', path])
    if out:
        try:
            return float(out.strip().split()[0])
        except (ValueError, IndexError):
            pass
    out = _run(['afinfo', path])         # macOS, and it reads everything
    if out:
        for line in out.splitlines():
            if 'estimated duration' in line:
                try:
                    return float(line.split(':')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
    return _mp3_estimate(path)


def _mp3_estimate(path):
    """A constant-bitrate guess, for when nothing better is installed."""
    if os.path.splitext(path)[1].lower() != '.mp3':
        return None
    bitrates = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256,
                320, 0]
    rates = [44100, 48000, 32000, 0]
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            head = f.read(65536)
    except OSError:
        return None
    start = 0
    if head[:3] == b'ID3' and len(head) > 10:      # skip the tag
        size_bytes = head[6:10]
        start = 10 + sum((b & 0x7F) << (7 * (3 - i))
                         for i, b in enumerate(bytearray(size_bytes)))
    data = bytearray(head)
    for i in range(start, min(len(data) - 4, 60000)):
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            bitrate = bitrates[(data[i + 2] >> 4) & 0xF]
            rate = rates[(data[i + 2] >> 2) & 0x3]
            if bitrate and rate:
                return (size - start) * 8.0 / (bitrate * 1000)
            break
    return None


def trim(path, start):
    """A copy of the file from `start` seconds in, for players that cannot seek.

    Only for the formats the standard library can rewrite, and only when the
    file is a sane size. Returns a temporary path the caller must delete, or
    None if it cannot be done.
    """
    module = _reader(path)
    if module is None or start <= 0:
        return None
    try:
        if os.path.getsize(path) > TRIM_LIMIT:
            return None
        with module.open(path, 'rb') as src:
            rate = src.getframerate()
            frames = src.getnframes()
            skip = min(frames, int(start * rate))
            src.setpos(skip)
            data = src.readframes(frames - skip)
            params = (src.getnchannels(), src.getsampwidth(), rate,
                      frames - skip, src.getcomptype(), src.getcompname())
        handle, out = tempfile.mkstemp(prefix='tide-audio-',
                                       suffix=os.path.splitext(path)[1])
        os.close(handle)
        with module.open(out, 'wb') as dst:
            dst.setparams(params)
            dst.writeframes(data)
        return out
    except Exception:
        return None
