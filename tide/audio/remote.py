"""Sound from a machine you are not sitting at.

tide over ssh runs on the far machine, and whatever it plays comes out of that
machine's speakers - which is usually a server with none at all. No terminal
can carry audio back the other way (the protocols for that are drafts), so the
only way to hear it where you are is to have something listening there.

That something is tide itself. On the machine in front of you:

    tide --audio-sink

and an ssh tunnel back to it, either as a flag

    ssh -R 47000:127.0.0.1:47000 you@server

or once and for all in ~/.ssh/config:

    Host server
        RemoteForward 47000 127.0.0.1:47000

The far side then talks to 127.0.0.1:47000, which the tunnel carries home. The
file crosses once, when you first press play; after that only short lines go
back and forth - play, pause, seek, speed - so seeking costs nothing. The
progress bar is worked out locally, so a slow link never holds up the screen.

Nothing here is imported unless a sink is configured.
"""

import json
import os
import socket
import tempfile
import time

PORT = 47000
GREETING = 'tide-audio'
VERSION = 1
CHUNK = 1 << 16


# ---------------------------------------------------------------- the wire

def _send(sock, message):
    sock.sendall((json.dumps(message) + '\n').encode('utf-8'))


class Lines(object):
    """One JSON message per line, off a socket."""

    def __init__(self, sock):
        self.sock = sock
        self.rest = b''

    def read(self, timeout=None):
        self.sock.settimeout(timeout)
        while b'\n' not in self.rest:
            more = self.sock.recv(CHUNK)
            if not more:
                return None
            self.rest += more
        line, self.rest = self.rest.split(b'\n', 1)
        try:
            return json.loads(line.decode('utf-8'))
        except ValueError:
            return None

    def take(self, count):
        """The next `count` raw bytes, after whatever the line reader has."""
        out, self.rest = self.rest[:count], self.rest[count:]
        while len(out) < count:
            more = self.sock.recv(min(CHUNK, count - len(out)))
            if not more:
                break
            out += more
        return out


# ------------------------------------------------------- the far side (us)

class Link(object):
    """A player, except that the sound comes out somewhere else.

    Same surface as the local Player, so the audio tab cannot tell them apart.
    """

    def __init__(self, path, port=PORT, duration=None):
        self.path = path
        self.port = port
        self.duration = duration
        self.rate = 1.0
        self.error = None
        self.command = None
        self.backend = _Named('sink :%d' % port)
        self.sock = None
        self.lines = None
        self.sent = False
        self._base = 0.0
        self._since = None
        self._done = False

    # -- state
    @property
    def playing(self):
        return self.sock is not None and self._since is not None

    @property
    def paused(self):
        return self.sock is not None and self._since is None and self.sent

    def can_seek(self):
        return True

    def position(self):
        at = self._base
        if self._since is not None:
            at += (time.time() - self._since) * self.rate
        if self.duration:
            at = min(at, self.duration)
        return max(0.0, at)

    def finished(self):
        if self._done:
            return True
        if self.duration and self._since is not None and \
                self.position() >= self.duration - 0.05:
            self._done = True
            self._since = None
            self._base = self.duration
        return self._done

    # -- the connection
    def connect(self):
        if self.sock is not None:
            return True
        try:
            sock = socket.create_connection(('127.0.0.1', self.port), 2.0)
        except (OSError, socket.error) as exc:
            self.error = 'no sink on port %d (%s)' % (self.port, exc.strerror
                                                      or exc)
            return False
        self.sock = sock
        self.lines = Lines(sock)
        return True

    def _tell(self, message, timeout=3.0):
        if not self.connect():
            return None
        try:
            _send(self.sock, message)
            return self.lines.read(timeout)
        except (OSError, socket.error, socket.timeout) as exc:
            self.error = 'the sink went away (%s)' % exc
            self.close_socket()
            return None

    def close_socket(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.lines = None
        self.sent = False

    def _deliver(self):
        """Hand the file over, once."""
        if self.sent:
            return True
        if not self.connect():
            return False
        try:
            size = os.path.getsize(self.path)
            self.sock.settimeout(20.0)     # a stalled tunnel must not hang us
            _send(self.sock, {'tide': VERSION, 'do': 'file', 'size': size,
                              'name': os.path.basename(self.path)})
            with open(self.path, 'rb') as f:
                while True:
                    block = f.read(CHUNK)
                    if not block:
                        break
                    self.sock.sendall(block)
            reply = self.lines.read(30.0)
        except (OSError, socket.error) as exc:
            self.error = 'could not send it to the sink (%s)' % exc
            self.close_socket()
            return False
        if not reply or not reply.get('ok'):
            self.error = (reply or {}).get('error', 'the sink would not take it')
            return False
        self.sent = True
        if reply.get('duration'):
            self.duration = reply['duration']
        if reply.get('backend'):
            self.backend = _Named('%s on your machine' % reply['backend'])
        return True

    # -- doing things
    def play(self, at=None):
        start = self.position() if at is None else max(0.0, at)
        if self.duration and start >= self.duration - 0.05:
            start = 0.0
        if not self._deliver():
            return False
        reply = self._tell({'do': 'play', 'at': start, 'rate': self.rate})
        if not reply or not reply.get('ok'):
            self.error = (reply or {}).get('error', self.error or
                                           'the sink would not play it')
            return False
        self.error = None
        self._done = False
        self._base = start
        self._since = time.time()
        return True

    def pause(self):
        if not self.playing:
            return False
        self._base = self.position()
        self._since = None
        self._tell({'do': 'pause'})
        return True

    def resume(self):
        if not self.paused:
            return False
        reply = self._tell({'do': 'resume'})
        if not reply or not reply.get('ok'):
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
        seconds = max(0.0, seconds)
        if self.duration:
            seconds = min(seconds, max(0.0, self.duration - 0.05))
        if self.playing:
            return self.play(seconds)
        self._base = seconds
        self._done = False
        self._tell({'do': 'stop'})
        return True

    def nudge(self, delta):
        return self.seek(self.position() + delta)

    def set_rate(self, rate):
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
        if not keep_position:
            self._base = 0.0
        elif self._since is not None:
            self._base = self.position()
        self._since = None
        if self.sock is not None:
            self._tell({'do': 'stop'}, timeout=2.0)
            self.close_socket()

    def use_source(self, path):
        """The file changed underneath us; it will have to go over again."""
        self.path = path
        self.sent = False


class _Named(object):
    """Something with a name, where a backend is expected."""

    def __init__(self, name):
        self.name = name
        self.seek = True
        self.rate = True


def reachable(port=PORT, timeout=1.0):
    """(True, what it said) if a sink is listening, else (False, why not)."""
    try:
        sock = socket.create_connection(('127.0.0.1', port), timeout)
    except (OSError, socket.error) as exc:
        return False, (getattr(exc, 'strerror', None) or str(exc))
    try:
        lines = Lines(sock)
        _send(sock, {'tide': VERSION, 'do': 'hello'})
        reply = lines.read(timeout) or {}
        if reply.get('ok') and reply.get('greeting') == GREETING:
            return True, reply.get('backend') or 'a player'
        return False, 'something else is listening on that port'
    except (OSError, socket.error, socket.timeout) as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except Exception:
            pass


# ------------------------------------------------- the near side (the sink)

class Conn(object):
    """One conversation with one audio tab on the far side."""

    def __init__(self, sock, sink):
        self.sock = sock
        self.sink = sink
        self.lines = Lines(sock)
        self.player = None
        self.temp = None
        self.name = '?'

    # -- one message, or False when the far side has gone
    def pump(self):
        try:
            message = self.lines.read(5.0)
        except (OSError, socket.error, socket.timeout):
            return False
        if message is None:
            return False
        try:
            self.answer(message)
        except (OSError, socket.error):
            return False
        return True

    def answer(self, message):
        from .player import backend
        do = message.get('do')
        if do == 'hello':
            here = backend()
            _send(self.sock, {'ok': True, 'greeting': GREETING,
                              'tide': VERSION,
                              'backend': here.name if here else None})
        elif do == 'file':
            _send(self.sock, self.take_file(message))
        elif do == 'play':
            _send(self.sock, self.do_play(message))
        elif do == 'pause':
            _send(self.sock, {'ok': bool(self.player and self.player.pause())})
        elif do == 'resume':
            self.sink.only(self)
            _send(self.sock, {'ok': bool(self.player and self.player.resume())})
        elif do == 'where':
            _send(self.sock, {'ok': True,
                              'at': self.player.position() if self.player else 0,
                              'done': bool(self.player and self.player.finished())})
        elif do == 'stop':
            self.silence()
            _send(self.sock, {'ok': True})
        else:
            _send(self.sock, {'ok': False, 'error': 'unknown request'})

    def take_file(self, message):
        from .player import Player
        size = int(message.get('size') or 0)
        self.name = os.path.basename(message.get('name') or 'sound')
        self.finish(keep_socket=True)
        handle, path = tempfile.mkstemp(prefix='tide-sink-',
                                        suffix=os.path.splitext(self.name)[1])
        try:
            with os.fdopen(handle, 'wb') as f:
                left = size
                while left > 0:
                    block = self.lines.take(min(CHUNK, left))
                    if not block:
                        break
                    f.write(block)
                    left -= len(block)
        except OSError as exc:
            return {'ok': False, 'error': str(exc)}
        self.temp = path
        self.player = Player(path)
        self.sink.say('%s: received (%.1f KB)' % (self.name, size / 1024.0))
        if self.player.backend is None:
            return {'ok': False, 'error': 'nothing here can play that'}
        return {'ok': True, 'duration': self.player.duration,
                'backend': self.player.backend.name}

    def do_play(self, message):
        if self.player is None:
            return {'ok': False, 'error': 'nothing has been sent yet'}
        self.sink.only(self)               # one sound at a time
        rate = float(message.get('rate') or 1.0)
        if rate != self.player.rate:
            self.player.rate = rate
        if not self.player.play(float(message.get('at') or 0.0)):
            return {'ok': False, 'error': self.player.error or
                    'it would not play'}
        self.sink.say('%s: playing' % self.name)
        return {'ok': True}

    def silence(self):
        if self.player is not None:
            self.player.stop()

    def finish(self, keep_socket=False):
        self.silence()
        self.player = None
        if self.temp:
            try:
                os.remove(self.temp)
            except OSError:
                pass
            self.temp = None
        if not keep_socket:
            try:
                self.sock.close()
            except Exception:
                pass


class Sink(object):
    """Runs where you are sitting, and plays what the far side sends.

    Several tabs can be connected at once - one per audio file open over
    there - and only one of them makes a sound at a time. Connections are
    served from a select loop, so a second tab asking to play never waits
    behind the first.
    """

    def __init__(self, port=PORT, out=None):
        self.port = port
        self.out = out
        self.conns = {}

    def say(self, message):
        if self.out is not None:
            self.out.write(message + '\n')
            self.out.flush()

    def only(self, winner):
        """Stop whatever else was playing; one sound at a time."""
        for conn in self.conns.values():
            if conn is not winner:
                conn.silence()

    def serve(self, once=False):
        import select
        from .player import backend
        here = backend()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', self.port))
        server.listen(8)
        self.say('tide audio sink listening on 127.0.0.1:%d' % self.port)
        self.say('playing through %s' % (here.name if here else
                                         'nothing - no player found here'))
        self.say('leave this running; ctrl+c stops it')
        served = 0
        try:
            while True:
                watching = [server] + [c.sock for c in self.conns.values()]
                try:
                    ready, _w, _x = select.select(watching, [], [], 0.5)
                except (OSError, select.error):
                    ready = []
                for sock in ready:
                    if sock is server:
                        conn, _who = server.accept()
                        self.conns[conn] = Conn(conn, self)
                        continue
                    conn = self.conns.get(sock)
                    if conn is None or not conn.pump():
                        self.drop(sock)
                        served += 1
                if once and served and not self.conns:
                    return
        finally:
            for sock in list(self.conns):
                self.drop(sock)
            try:
                server.close()
            except Exception:
                pass

    def drop(self, sock):
        conn = self.conns.pop(sock, None)
        if conn is not None:
            conn.finish()
            self.say('%s: gone' % conn.name)


def serve(port=PORT, out=None, once=False):
    Sink(port, out).serve(once=once)
