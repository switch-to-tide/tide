"""Turning sound on: a panel that asks where it should come out.

It appears over the settings, answers itself away, and leaves the settings
where they were. Choosing the local machine changes nothing at all - the
checks are the ones that were always there. Choosing ssh sets up a sink on the
machine you are sitting at, once, and remembers it for every session after.
"""

import os

from .. import theme
from ..term import BOLD, DIM

PORT = 47000


class AudioSetup(object):
    """Where should the sound come out: here, or where you are sitting?"""

    is_list = False           # the app draws no prompt line for this

    def __init__(self, app, panel=None):
        self.app = app
        self.panel = panel                 # the settings, to go back to
        self.step = 'where'
        self.port = str(app.settings.get('audio_sink_port') or PORT)
        self.note = ''
        self.trouble = False

    # ---------------- what each answer does ----------------
    def choose_local(self):
        """Exactly the behaviour there has always been."""
        self.close()
        self.app.enable_audio_locally()

    def choose_ssh(self):
        self.step = 'ssh'
        self.note = ''
        self.trouble = False

    def try_port(self):
        from . import remote
        try:
            port = int(self.port.strip() or PORT)
        except ValueError:
            self.note, self.trouble = 'that is not a port number', True
            return
        found, said = remote.reachable(port)
        if not found:
            self.note = 'nothing answered on %d: %s' % (port, said)
            self.trouble = True
            return
        self.app.settings['audio_sink_port'] = port
        self.app.force_setting('audio', True,
                               'audio on: playing through the sink on port %d '
                               '(%s)' % (port, said))
        self.close()

    def forget_sink(self):
        self.app.settings['audio_sink_port'] = 0
        self.app.force_setting('audio', False, 'audio off, and the sink '
                               'forgotten')
        self.close()

    def close(self):
        self.app.back_to(self.panel)
        self.app.need_render = True

    # ---------------- keys ----------------
    def on_key(self, key):
        name = key.name
        ch = key.char.lower() if name == 'char' else ''
        if name == 'escape':
            self.close()
            return 'close' if self.panel is None else None
        if self.step == 'where':
            if ch == 'l':
                self.choose_local()
                return 'close' if self.panel is None else None
            if ch == 's':
                self.choose_ssh()
            return None
        # the ssh step: a port to type, and enter to try it
        if name == 'enter':
            self.try_port()
            return 'close' if self.panel is None and not self.trouble else None
        if name == 'backspace':
            self.port = self.port[:-1]
        elif ch == 'f':
            self.forget_sink()
        elif name == 'char' and key.char.isdigit() and len(self.port) < 5:
            self.port += key.char
        return None

    def on_paste(self, text):
        digits = ''.join(c for c in text if c.isdigit())
        self.port = (self.port + digits)[:5]

    def on_mouse(self, ev):
        return True

    # ---------------- painting ----------------
    def render(self, screen, area):
        lines = self._where() if self.step == 'where' else self._ssh()
        w = min(76, max(40, area.w - 6))
        h = min(len(lines) + 2, area.h - 2)
        x = area.x + (area.w - w) // 2
        y = area.y + max(0, (area.h - h) // 2)
        screen.fill(x, y, w, h, bg=theme.PANEL_ALT)
        screen.fill(x, y, w, 1, bg=theme.STATUS_ACC)
        title = ' audio playback '
        screen.put(x + 1, y, title, fg=theme.STATUS_FG, bg=theme.STATUS_ACC,
                   attr=BOLD)
        cursor = None
        for i, (kind, text) in enumerate(lines):
            ry = y + 1 + i
            if ry >= y + h:
                break
            if kind == 'key':
                head, rest = text
                screen.put(x + 2, ry, head, fg=theme.TAB_MARK,
                           bg=theme.PANEL_ALT, attr=BOLD, max_x=x + w - 1)
                screen.put(x + 3 + len(head), ry, rest, fg=theme.FG,
                           bg=theme.PANEL_ALT, max_x=x + w - 1)
            elif kind == 'command':
                screen.put(x + 4, ry, text, fg=theme.OK, bg=theme.PANEL_ALT,
                           max_x=x + w - 1)
            elif kind == 'field':
                screen.put(x + 2, ry, text, fg=theme.FG, bg=theme.PANEL_ALT,
                           attr=BOLD, max_x=x + w - 1)
                cursor = (x + 2 + len(text), ry)
            elif kind == 'bad':
                screen.put(x + 2, ry, text, fg=theme.ERROR, bg=theme.PANEL_ALT,
                           max_x=x + w - 1)
            elif kind == 'dim':
                screen.put(x + 2, ry, text, fg=theme.FG_DIM,
                           bg=theme.PANEL_ALT, attr=DIM, max_x=x + w - 1)
            else:
                screen.put(x + 2, ry, text, fg=theme.FG, bg=theme.PANEL_ALT,
                           max_x=x + w - 1)
        return cursor

    def _where(self):
        over_ssh = bool(os.environ.get('SSH_CONNECTION') or
                        os.environ.get('SSH_TTY'))
        lines = [('', 'Where should the sound come out?'), ('', '')]
        lines += [('key', ('l', 'this machine - the one tide is running on')),
                  ('key', ('s', 'the machine I am sitting at, over ssh')),
                  ('', ''),
                  ('dim', 'esc leaves this alone')]
        if over_ssh:
            lines.insert(1, ('dim', 'you are over ssh, so this looks like s'))
        return lines

    def _ssh(self):
        return [
            ('', 'On the machine you are sitting at - mac or linux - run:'),
            ('', ''),
            ('command', 'tide --audio-sink'),
            ('', ''),
            ('', 'and connect with the port carried back to this machine:'),
            ('', ''),
            ('command', 'ssh -R %s:127.0.0.1:%s  you@this-machine'
             % (self.port or PORT, self.port or PORT)),
            ('', ''),
            ('dim', 'or once and for all, in ~/.ssh/config on that machine:'),
            ('command', 'Host this-machine'),
            ('command', '    RemoteForward %s 127.0.0.1:%s'
             % (self.port or PORT, self.port or PORT)),
            ('', ''),
            ('field', 'port: %s' % self.port),
            ('', ''),
            ('bad' if self.trouble else 'dim',
             self.note or 'enter tries it   f forgets a sink   esc cancels'),
        ]
