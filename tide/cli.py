"""Command line entry point."""

import argparse
import os
import re
import subprocess
import sys
import time

from . import __version__
from . import theme
from .app import App


def checkout_root():
    """The clone tide is running from, if it is running from one."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return root if os.path.isdir(os.path.join(root, '.git')) else None


def installed_version(root):
    try:
        with open(os.path.join(root, 'tide', '__init__.py')) as f:
            found = re.search(r"__version__ = '([^']+)'", f.read())
        return found.group(1) if found else '?'
    except (IOError, OSError):
        return '?'


HOME_REPO = 'github.com/switch-to-tide/tide'

# --force so that a tag which has been moved on the remote does not stop the
# whole fetch with 'would clobber existing tag'
FETCH = ['fetch', '--depth', '1', '--tags', '--force', 'origin']


def home_url():
    """Where tide comes from; TIDE_REPO points a fork or a mirror elsewhere."""
    return os.environ.get('TIDE_REPO') or 'https://%s.git' % HOME_REPO


def _git(root, args):
    """Run git in the checkout: (exit code or None if git is missing, output)."""
    try:
        process = subprocess.Popen(['git', '-C', root] + args,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
    except OSError:
        return None, ''
    out = process.communicate()[0].decode('utf-8', 'replace')
    return process.returncode, out


def _tags(root):
    """Which versions the remote is offering, for when one is asked for wrongly."""
    code, out = _git(root, ['ls-remote', '--tags', '--refs', 'origin'])
    if code:
        return []
    names = [line.rsplit('/', 1)[-1].lstrip('v') for line in out.splitlines()
             if '/tags/' in line]
    return sorted(set(names))[-6:]


def _ref_missing(said):
    """Whether git reached the remote and simply did not find that version.

    Then there is nothing wrong with where we are fetching from, and moving
    the remote would be the wrong thing to do.
    """
    low = (said or '').lower()
    return ("couldn't find remote ref" in low or 'unknown revision' in low
            or 'not our ref' in low)


def _say(message):
    """One stream, in order: the two are interleaved unpredictably in a pipe."""
    sys.stdout.flush()
    sys.stderr.write(message + '\n')
    sys.stderr.flush()


def _explain(root, origin, ref, said):
    """Say what went wrong, rather than guessing that a version is missing."""
    last = said.strip().splitlines()[-1] if said.strip() else ''
    if (not _ref_missing(said) and origin
            and HOME_REPO not in origin.replace(':', '/')
            and origin != home_url()):
        # an install from before the repository moved: it is fetching from
        # somewhere that is not there any more. A version git looked for and
        # did not find says nothing about where we are fetching from.
        _say('This copy of tide is being updated from %s,\n'
             'which is not where tide lives any more.\n\n'
             'Point it at the right place:\n'
             '    git -C %s remote set-url origin https://%s.git\n'
             'or install it again:\n'
             '    curl -fsSL https://raw.githubusercontent.com/'
             'switch-to-tide/tide/main/install.sh | sh'
             % (origin, root, HOME_REPO))
        return
    lines = ["tide could not fetch '%s' from %s." % (ref, origin or 'origin')]
    if last:
        lines.append('git said: %s' % last)
    known = _tags(root)
    if known:
        lines.append('versions there: %s' % ', '.join(known))
    lines.append('the checkout is %s' % root)
    _say('\n'.join(lines))


def update(version):
    """`tide --update`: move the clone to the newest code, or to a version."""
    root = checkout_root()
    if root is None:
        sys.stderr.write(
            'tide was not installed from a clone, so there is nothing to pull.\n'
            'If you installed it with pip, upgrade it the same way:\n'
            '    pip install --upgrade "git+https://github.com/switch-to-tide/tide.git"\n')
        return 1
    if version in ('', None):
        ref = 'main'
    elif re.match(r'^\d', version):
        ref = 'v' + version            # releases are tagged v0.1.0
    else:
        ref = version
    was = installed_version(root)
    origin = (_git(root, ['remote', 'get-url', 'origin'])[1] or '').strip()
    code, said = _git(root, FETCH + [ref])
    if code is None:
        sys.stderr.write('tide --update needs git on PATH.\n')
        return 1
    if code != 0:
        # a checkout from before tide moved, or one using ssh without a key:
        # point it at the canonical place and try once more before giving up
        canonical = home_url()
        following = origin
        if origin != canonical and not _ref_missing(said):
            _git(root, ['remote', 'set-url', 'origin', canonical])
            _say('This copy was following %s.\nFollowing %s from now on.'
                 % (origin or 'nowhere', canonical))
            following = canonical
            code, said = _git(root, FETCH + [ref])
        if code != 0:
            _explain(root, following, ref, said)
            return 1
    code, said = _git(root, ['checkout', '-q', '--detach', 'FETCH_HEAD'])
    if code != 0:
        sys.stderr.write('%s has changes of its own; leaving it alone.\n' % root)
        if said.strip():
            sys.stderr.write('git said: %s\n' % said.strip().splitlines()[-1])
        return 1
    now = installed_version(root)
    if now == was:
        sys.stdout.write('tide %s is already what you have.\n' % now)
    else:
        sys.stdout.write('tide %s -> %s.\n' % (was, now))
    sys.stdout.write('Any tide already running keeps the version it started with;\n'
                     'open a new one to use this.\n')
    return 0


def mouse_check():
    """What this terminal sends when asked to report the pointer moving.

    The menus use that reporting to follow the pointer. Some terminals send
    it far faster than anything can use, and this says so plainly rather than
    finding out in the middle of a session.
    """
    import select
    import termios
    import tty
    if not sys.stdin.isatty():
        sys.stderr.write('--mouse-check needs a terminal.\n')
        return 2
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    counts = {'moves': 0, 'other': 0, 'bytes': 0}
    shapes = set()
    try:
        tty.setraw(fd)
        sys.stdout.write('\x1b[?1000h\x1b[?1002h\x1b[?1006h\x1b[?1003h')
        sys.stdout.write('\r\nMove the pointer around this window for five '
                         'seconds...\r\n')
        sys.stdout.flush()
        end = time.time() + 5
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], max(0, end - time.time()))
            if not ready:
                continue
            data = os.read(fd, 65536)
            counts['bytes'] += len(data)
            for piece in data.split(b'\x1b'):
                if not piece:
                    continue
                if piece.startswith(b'[<'):
                    code = piece[2:].split(b';')[0]
                    shapes.add('SGR')
                    if code.isdigit() and int(code) & 32:
                        counts['moves'] += 1
                    else:
                        counts['other'] += 1
                elif piece.startswith(b'[M'):
                    shapes.add('X10')
                    counts['other'] += 1
    finally:
        sys.stdout.write('\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[?1006l')
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    rate = counts['moves'] / 5.0
    print('')
    print('reports of the pointer moving: %d in five seconds (%.0f a second)'
          % (counts['moves'], rate))
    print('other mouse reports:           %d' % counts['other'])
    print('bytes from the terminal:       %d' % counts['bytes'])
    print('encoding:                      %s'
          % (', '.join(sorted(shapes)) or 'nothing arrived'))
    if not counts['moves'] and not counts['other']:
        print('\nThis terminal sent nothing at all: either the pointer never '
              'moved over\nit, or it does not report the pointer. The menus '
              'will not follow it here.')
    elif rate > 200:
        print('\nThat is a lot - more than tide can use. Turn Menu follows '
              'mouse off in\nthe settings if the menus feel heavy here.')
    else:
        print('\nThat is a normal rate; the menus can follow the pointer here.')
    return 0


def _confirm(question):
    """y/n on the terminal; anything else is no."""
    try:
        answer = input('%s [y/N] ' % question)
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write('\n')
        return False
    return answer.strip().lower() in ('y', 'yes')


def run_session_command(args):
    """--list-sessions, --remove-session and --remove-all-sessions."""
    from . import sessions
    if args.list_sessions:
        names = sessions.names()
        if not names:
            sys.stdout.write('no saved sessions yet - Tide > Save to named '
                             'session, or  tide --new-session NAME\n')
            return 0
        for name in names:
            data = sessions.load(name) or {}
            where = sessions.busy(name)
            sys.stdout.write('%-20s %s%s\n' % (
                name, data.get('root', '?'),
                ('   [%s]' % where) if where else ''))
        return 0
    if args.remove_all_sessions:
        names = sessions.names()
        if not names:
            sys.stdout.write('there are no saved sessions.\n')
            return 0
        if not _confirm('Forget all %d saved sessions?' % len(names)):
            sys.stdout.write('left alone.\n')
            return 0
        sys.stdout.write('forgot %d session(s).\n' % sessions.remove_all())
        return 0
    name = args.remove_session
    if not sessions.exists(name):
        sys.stderr.write('no session called %s.\n' % name)
        return 1
    if not _confirm('Forget the session %s?' % name):
        sys.stdout.write('left alone.\n')
        return 0
    sessions.remove(name)
    sys.stdout.write('forgot %s.\n' % name)
    return 0


def open_saved_session(name):
    """What --resume should open, or an exit code if it cannot."""
    from . import sessions
    data = sessions.load(name)
    if data is None:
        sys.stderr.write('no session called %s.\n' % name)
        known = sessions.names()
        if known:
            sys.stderr.write('there is: %s\n' % ', '.join(known))
        return 1
    where = sessions.busy(name)
    if where:
        sys.stderr.write('the session %s is %s.\n' % (name, where))
        return 1
    root = data.get('root') or os.getcwd()
    if not os.path.isdir(root):
        sys.stderr.write('%s is gone, so %s cannot be opened there.\n'
                         % (root, name))
        return 1
    files = [f for f in data.get('files') or [] if os.path.isfile(f)]
    return {'root': root, 'files': files, 'active': data.get('active', 0),
            'split': bool(data.get('split')),
            'show_term': bool(data.get('show_term', True)),
            'show_tree': bool(data.get('show_tree', True))}


def start_session_here(name):
    """--new-session: a new name for this folder, or an exit code."""
    from . import sessions
    trouble = sessions.why_not(name)
    if not trouble and (sessions.exists(name) or sessions.busy(name)):
        trouble = 'there is already a session called %s' % name
    if trouble:
        sys.stderr.write('%s.\n' % trouble)
        return 1
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(
        prog='tide', description='A small terminal IDE: editor, explorer and shells.')
    ap.add_argument('--version', action='version',
                    version='%(prog)s ' + __version__)
    ap.add_argument('paths', nargs='*', help='files or a directory to open')
    ap.add_argument('--no-terminal', action='store_true', help='start with the terminal hidden')
    ap.add_argument('--no-tree', action='store_true', help='start with the explorer hidden')
    ap.add_argument('--no-autosave', action='store_true',
                    help='do not write files automatically (ctrl+s to save)')
    ap.add_argument('--autosave-delay', type=float, default=None, metavar='SECONDS',
                    help='quiet time before an edited file is written')
    ap.add_argument('--max-lines', type=int, default=None, metavar='N',
                    help='ask before opening a file with more lines')
    ap.add_argument('--max-mb', type=float, default=None, metavar='MB',
                    help='ask before opening a file bigger than this')
    ap.add_argument('--show-audio-pipe', action='store_true',
                    help='print how to connect the audio pipe to this machine')
    ap.add_argument('--audio-sink', nargs='?', const='', metavar='PORT',
                    help='play what a tide over ssh sends here (see --help)')
    ap.add_argument('--audio-check', nargs='?', const='', metavar='FILE',
                    help='say what will happen when a sound file is played')
    ap.add_argument('--update', nargs='?', const='', metavar='VERSION',
                    help='update the installed copy, to the newest code or to '
                         'a version, and exit')
    ap.add_argument('--mouse-check', action='store_true',
                    help='ask this terminal to report the pointer for five '
                         'seconds and say what it sends')
    ap.add_argument('--list-sessions', action='store_true',
                    help='name every saved session, and where it lives')
    ap.add_argument('--resume', metavar='SESSION',
                    help='open a saved session: its folder and its files')
    ap.add_argument('--new-session', metavar='SESSION',
                    help='start a session of that name here, and remember it')
    ap.add_argument('--remove-session', metavar='SESSION',
                    help='forget a saved session (asks first)')
    ap.add_argument('--remove-all-sessions', action='store_true',
                    help='forget every saved session (asks first)')
    ap.add_argument('--appearance', default=None, choices=['classic', 'modern'],
                    help='floating boxes (modern), or the deprecated flush '
                         'panes (classic)')
    ap.add_argument('--theme', default=None,
                    choices=sorted(set(theme.names_for('classic') +
                                       theme.names_for('modern'))),
                    help='colour palette for this session')
    args = ap.parse_args(argv)

    if args.update is not None:
        return update(args.update)
    if args.show_audio_pipe:
        from . import settings as settings_store
        from .audio.remote import describe
        return describe(settings_store.load(), sys.stdout)
    if args.audio_sink is not None:
        from .audio.remote import PORT, serve
        try:
            port = int(args.audio_sink or PORT)
        except ValueError:
            sys.stderr.write('--audio-sink takes a port number.\n')
            return 2
        try:
            serve(port, out=sys.stdout)
        except KeyboardInterrupt:
            sys.stdout.write('\nstopped\n')
        except OSError as exc:
            sys.stderr.write('could not listen on %d: %s\n' % (port, exc))
            return 1
        return 0
    if args.mouse_check:
        return mouse_check()
    if (args.list_sessions or args.remove_all_sessions
            or args.remove_session is not None):
        return run_session_command(args)
    if args.audio_check is not None:
        from .audio.check import run as audio_check
        return audio_check(args.audio_check or None)

    resume = None
    if args.resume is not None:
        resume = open_saved_session(args.resume)
        if isinstance(resume, int):
            return resume
    if args.new_session is not None:
        trouble = start_session_here(args.new_session)
        if trouble:
            return trouble

    root = None
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            root = p
        else:
            files.append(p)
    if root is None:
        root = os.path.dirname(os.path.abspath(files[0])) if files else os.getcwd()

    if not sys.stdout.isatty():
        sys.stderr.write('tide needs an interactive terminal.\n')
        return 2

    if resume:
        root, files = resume['root'], list(resume['files'])

    app = App(root=root, paths=[])
    name = args.resume or args.new_session
    if name:
        app.session = name
    if resume:
        app.show_term = resume['show_term']
        app.show_tree = resume['show_tree']
        app.split = resume['split']
    if args.no_terminal:
        app.show_term = False
    if args.no_tree:
        app.show_tree = False
    # flags win for this session, but are not written to the settings file
    if args.no_autosave:
        app.autosave = False
    if args.autosave_delay is not None:
        app.autosave_delay = max(0.1, args.autosave_delay)
    if args.max_lines is not None:
        app.max_file_lines = max(1, args.max_lines)
    if args.max_mb is not None:
        app.max_file_bytes = int(max(0.01, args.max_mb) * 1024 * 1024)
    if args.appearance:
        app.settings['appearance'] = args.appearance
        theme.apply(app.settings.get('theme'), args.appearance)
    if args.theme:
        # a palette only the other appearance has brings its appearance along
        look = theme.appearance_for(args.theme, app.settings.get('appearance'))
        app.settings['theme'] = args.theme
        app.settings['appearance'] = look
        theme.apply(args.theme, look)
    for f in files:
        app.open_file(f)
    if resume and 0 <= resume.get('active', 0) < len(app.editors):
        app.active = resume['active']
    if name:
        app.enter_session(name)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
