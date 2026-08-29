"""Named sessions: a folder, the files open in it, and how the panes were set.

A session is one small JSON file in the config directory. It holds where you
were working and which documents were open - never the shells, which belong to
the machine they were started on and are not worth pretending to restore.

While a session is open its file has a lock beside it naming the process that
holds it, so the same session cannot be opened twice and end up with two
different ideas of what was open.
"""

import errno
import io
import json
import os
import re
import socket

NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def folder():
    from .settings import config_path
    return os.path.join(os.path.dirname(config_path()), 'sessions')


def path(name):
    return os.path.join(folder(), '%s.json' % name)


def lock_path(name):
    return os.path.join(folder(), '%s.lock' % name)


def why_not(name):
    """Why this name will not do, or '' if it will."""
    name = (name or '').strip()
    if not name:
        return 'a session needs a name'
    if not NAME.match(name):
        return 'letters, digits, dot, dash and underscore only'
    return ''


def names():
    try:
        found = os.listdir(folder())
    except OSError:
        return []
    return sorted(f[:-5] for f in found if f.endswith('.json'))


def exists(name):
    return os.path.isfile(path(name))


def load(name):
    try:
        with io.open(path(name), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def save(name, data):
    """Write it out whole, so a session file is never half a session."""
    target = path(name)
    try:
        if not os.path.isdir(folder()):
            os.makedirs(folder())
        tmp = target + '.tmp'
        with io.open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(dict(data, name=name), indent=2, sort_keys=True))
            f.write(u'\n')
        os.replace(tmp, target)
        return True
    except Exception:
        return False


def remove(name):
    ok = False
    for p in (path(name), lock_path(name)):
        try:
            os.remove(p)
            ok = ok or p.endswith('.json')
        except OSError:
            pass
    return ok


def remove_all():
    return len([n for n in names() if remove(n)])


def rename(old, new):
    if not exists(old) or exists(new):
        return False
    data = load(old) or {}
    if not save(new, data):
        return False
    held = holder(old)
    remove(old)
    if held and held[0] == os.getpid():
        claim(new)
    return True


# ---------------- one at a time ----------------
def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH   # EPERM means someone else's, alive
    return True


def holder(name):
    """(pid, host) of the tide that has this session open, or None."""
    try:
        with io.open(lock_path(name), 'r', encoding='utf-8') as f:
            pid, _, host = f.read().strip().partition(' ')
        pid = int(pid)
    except Exception:
        return None
    if host and host != socket.gethostname():
        return (pid, host)          # another machine: not ours to judge
    if not _alive(pid):
        return None                 # it is gone; the lock is stale
    return (pid, host or socket.gethostname())


def busy(name):
    """Where this session is already open, or '' if it is free."""
    held = holder(name)
    if not held or held[0] == os.getpid():
        return ''
    pid, host = held
    if host and host != socket.gethostname():
        return 'open on %s (pid %d)' % (host, pid)
    return 'open in another tide (pid %d)' % pid


def claim(name):
    """Take the session, unless someone else has it."""
    if busy(name):
        return False
    try:
        if not os.path.isdir(folder()):
            os.makedirs(folder())
        with io.open(lock_path(name), 'w', encoding='utf-8') as f:
            f.write(u'%d %s' % (os.getpid(), socket.gethostname()))
        return True
    except Exception:
        return False


def release(name):
    held = holder(name)
    if held and held[0] != os.getpid():
        return                       # not ours to let go of
    try:
        os.remove(lock_path(name))
    except OSError:
        pass
