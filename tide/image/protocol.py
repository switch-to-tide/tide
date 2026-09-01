"""Real pixels, where the terminal can draw them.

Cells hold two pixels each, which is fine for seeing what a picture is and
useless for reading anything in it. Terminals that speak the kitty graphics
protocol will draw the actual image instead, at whatever resolution the
window has - the same picture, fifty times the detail.

Nothing here is required: a terminal that does not answer the query keeps the
half blocks, and a terminal that ignores the protocol entirely sees only an
APC string, which every conformant terminal discards in silence.
"""

import os
import select
import time

CHUNK = 4096                       # the protocol's limit, in base64 characters
FIRST_ID = 1729                    # ours, and unlikely to be anyone else's


def _wrap(sequence):
    """tmux hides APC strings from the terminal unless they are wrapped."""
    if not os.environ.get('TMUX'):
        return sequence
    return '\x1bPtmux;' + sequence.replace('\x1b', '\x1b\x1b') + '\x1b\\'


def known_terminal():
    """Terminals that say what they are, and can draw pictures."""
    if os.environ.get('TMUX') or 'screen' in os.environ.get('TERM', ''):
        return False                   # a multiplexer in the way: do not guess
    if os.environ.get('KITTY_WINDOW_ID') or os.environ.get('GHOSTTY_RESOURCES_DIR'):
        return True
    if os.environ.get('TERM', '') in ('xterm-kitty', 'xterm-ghostty'):
        return True
    return os.environ.get('TERM_PROGRAM', '') in ('WezTerm', 'ghostty')


def query(out, in_fd, timeout=2.0, patience=None):
    """See the docstring below; `patience` is how long silence is allowed."""
    """Ask the terminal whether it can draw images. Returns (yes, leftover).

    The graphics question is followed by one every terminal answers, so there
    is something definite to read up to: if the second answer arrives without
    the first, this terminal cannot draw images. Whatever the user typed while
    we waited comes back as `leftover`, to be dealt with as ordinary input.
    """
    ask = '\x1b_Gi=%d,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\\x1b[c' % FIRST_ID
    try:
        out.write(_wrap(ask))
        out.flush()
    except Exception:
        return False, b''
    # a terminal that can do this answers at once; one that cannot answers
    # the second question only. Silence means neither - give up quickly, but
    # allow for a slow link where every answer takes a round trip
    if patience is None:
        patience = 1.5 if os.environ.get('SSH_CONNECTION') else 0.25
    end = time.time() + timeout
    quiet_until = time.time() + patience
    buf = b''
    while time.time() < min(end, quiet_until if not buf else end):
        wait = (end if buf else quiet_until) - time.time()
        try:
            ready = select.select([in_fd], [], [], max(0.0, wait))[0]
        except (OSError, ValueError):
            break
        if not ready:
            break
        try:
            chunk = os.read(in_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        if b'c' in buf.split(b'\x1b[?')[-1] and b'\x1b[?' in buf:
            break                       # the answer everything gives has come
    ok = b'_G' in buf and b';OK' in buf
    # hand back anything that was not part of the two answers
    leftover = buf
    for reply in (b'\x1b_Gi=%d;OK\x1b\\' % FIRST_ID,):
        leftover = leftover.replace(reply, b'')
    if b'\x1b[?' in leftover:
        head, _, rest = leftover.partition(b'\x1b[?')
        _da, _, after = rest.partition(b'c')
        leftover = head + after
    return ok, leftover


class ITerm2(object):
    """The other way a terminal draws a picture: iTerm2's own escape.

    There is no way to place an image the terminal is already holding, so the
    file goes over every time it moves - which is why it is only sent when it
    has to be. Nor is there a way to delete one: the cells underneath are
    repainted, and the picture goes with them.
    """

    name = 'iterm2'
    LIMIT = 8 << 20                # bigger than this and the blocks are kinder

    def __init__(self, out):
        self.out = out
        self.next_id = FIRST_ID + 1
        self.showing = set()
        self.files = {}

    def hold(self, data):
        if len(data) > self.LIMIT:
            return None
        image_id = self.next_id
        self.next_id += 1
        self.files[image_id] = data
        return image_id

    def place(self, image_id, x, y, cols, rows):
        import base64
        data = self.files.get(image_id)
        if data is None or cols < 1 or rows < 1:
            return
        payload = base64.b64encode(data).decode('ascii')
        self.out.write('\x1b7\x1b[%d;%dH' % (y + 1, x + 1))      # keep our place
        self.out.write(_wrap(
            '\x1b]1337;File=inline=1;width=%d;height=%d;'
            'preserveAspectRatio=1;size=%d:%s\x07'
            % (cols, rows, len(data), payload)))
        self.out.write('\x1b8')
        self.showing.add(image_id)

    def unplace(self, image_id):
        # nothing to undo: the cells under it are repainted by the frame that
        # took it away, and the picture goes with them
        self.showing.discard(image_id)

    def forget(self, image_id):
        self.files.pop(image_id, None)
        self.showing.discard(image_id)

    def clear(self):
        self.showing.clear()


def for_terminal(out, in_fd, settings=None):
    """Whichever way this terminal can draw a picture, or None for blocks."""
    mode = (settings or {}).get('images', 'auto')
    if mode != 'auto':
        return None, b''               # blocks, by the settings' say-so
    if known_terminal():
        return Kitty(out), b''             # it says what it is; no need to ask
    ok, leftover = query(out, in_fd)
    if ok:
        return Kitty(out), leftover        # the better of the two: cheaper
    if os.environ.get('TERM_PROGRAM') in ('iTerm.app', 'WezTerm', 'vscode'):
        return ITerm2(out), leftover
    return None, leftover


class Kitty(object):
    """Pictures held by the terminal, placed where the pane is.

    The file is handed over once and kept by its id; after that a frame costs
    one short line - which is what makes it cheap enough to do on every
    repaint, and repainting every frame is what keeps it in the right place
    when panes move.
    """

    name = 'kitty'

    def __init__(self, out):
        self.out = out
        self.next_id = FIRST_ID + 1
        self.showing = set()          # ids with a placement on screen

    def _send(self, control, payload=''):
        self.out.write(_wrap('\x1b_G%s;%s\x1b\\' % (control, payload)))

    def hold(self, data):
        """Give the terminal a PNG to keep. Returns its id."""
        import base64
        image_id = self.next_id
        self.next_id += 1
        encoded = base64.b64encode(data).decode('ascii')
        pieces = [encoded[i:i + CHUNK] for i in range(0, len(encoded), CHUNK)]
        if not pieces:
            return None
        first = 'i=%d,f=100,t=d,a=t,q=2,m=%d' % (image_id,
                                                 1 if len(pieces) > 1 else 0)
        self._send(first, pieces[0])
        for i, piece in enumerate(pieces[1:], start=1):
            self._send('m=%d,q=2' % (0 if i == len(pieces) - 1 else 1), piece)
        return image_id

    def place(self, image_id, x, y, cols, rows):
        """Draw it in that rectangle of cells, without moving the cursor."""
        if image_id is None or cols < 1 or rows < 1:
            return
        self.out.write('\x1b[%d;%dH' % (y + 1, x + 1))
        self._send('a=p,i=%d,c=%d,r=%d,C=1,q=2' % (image_id, cols, rows))
        self.showing.add(image_id)

    def unplace(self, image_id):
        """Take it off the screen, keeping the pixels for next time."""
        if image_id is None:
            return
        self._send('a=d,d=i,i=%d,q=2' % image_id)
        self.showing.discard(image_id)

    def forget(self, image_id):
        """Take it off the screen and let the terminal free it."""
        if image_id is None:
            return
        self._send('a=d,d=I,i=%d,q=2' % image_id)
        self.showing.discard(image_id)

    def clear(self):
        for image_id in list(self.showing):
            self.unplace(image_id)
