"""Short, readable names for tabs: files, duplicates, and running programs."""

import os
import subprocess

ELLIPSIS = '…'
MAX_TAB = 24              # characters of tab label before it gets cropped
MAX_PROGRAM = 16          # characters of a terminal's program name

# programs whose first argument is the interesting part: `uv run`, `git log`
SUBCOMMAND_FIRST = {'uv', 'npx', 'npm', 'yarn', 'pnpm', 'poetry', 'pipx',
                    'cargo', 'go', 'git', 'docker', 'make', 'brew', 'pip',
                    'pip3', 'python', 'python3', 'node', 'deno', 'bun'}


def crop(name, limit):
    """Shorten a label, keeping the end of a path and the start of a name."""
    if len(name) <= limit or limit <= 1:
        return name
    if '/' in name:                       # a path: the file at the end matters
        return ELLIPSIS + name[-(limit - 1):]
    return name[:limit - 1] + ELLIPSIS


def tab_label(name):
    return crop(name, MAX_TAB)


def _parts(path):
    parent = os.path.dirname(os.path.abspath(path))
    return [p for p in parent.split(os.sep) if p]


def titles(paths):
    """A name per path: the file, plus enough folders to tell duplicates apart.

    The same rule VS Code uses - the shortest tail of the folders that makes
    every one of them different. A path of None (an unsaved buffer, a diff)
    comes back as None for the caller to name however it likes.
    """
    names = [os.path.basename(p) or p if p else None for p in paths]
    out = list(names)
    seen = {}
    for i, name in enumerate(names):
        if name is not None:
            seen.setdefault(name, []).append(i)
    for name, group in seen.items():
        if len(group) < 2:
            continue
        parts = [_parts(paths[i]) for i in group]
        depth = max(len(p) for p in parts)
        for take in range(1, depth + 1):
            tails = ['/'.join(p[-take:]) for p in parts]
            if len(set(tails)) == len(tails):
                break
        for i, tail in zip(group, tails):
            out[i] = '%s/%s' % (tail, name) if tail else name
    return out


def program_name(command):
    """'uv run dev' -> 'uv run', '/usr/bin/python3 x.py' -> 'python3 x.py'."""
    words = [w for w in command.split() if w]
    if not words:
        return ''
    base = os.path.basename(words[0]).lstrip('-')     # login shells say -zsh
    if base in ('sudo', 'env', 'time') and len(words) > 1:
        words = words[1:]
        base = os.path.basename(words[0]).lstrip('-')
    # only the first argument, and only when it is not a flag: `python3 -c ...`
    # is just python3, while `python3 app.py` and `uv run` say more
    if base in SUBCOMMAND_FIRST and len(words) > 1 and not words[1].startswith('-'):
        return crop('%s %s' % (base, os.path.basename(words[1])), MAX_PROGRAM)
    return crop(base, MAX_PROGRAM)


def foreground(fd, shell_pid, cache):
    """What the terminal on `fd` is running now, or None to keep the old name.

    The foreground process group changes with every command, so the answer is
    cached against it and `ps` runs once per command rather than once a frame.
    """
    try:
        pgid = os.tcgetpgrp(fd)
    except (OSError, AttributeError):
        return None
    if pgid <= 0:
        return None
    if pgid in cache:
        return cache[pgid]
    if pgid == shell_pid:
        name = os.path.basename(os.environ.get('SHELL', 'sh'))
    else:
        name = _ask_ps(pgid)
    if name:
        if len(cache) > 64:
            cache.clear()
        cache[pgid] = name
    return name


def _ask_ps(pgid):
    try:
        out = subprocess.check_output(['ps', '-o', 'args=', '-p', str(pgid)],
                                      stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    line = out.decode('utf-8', 'replace').strip().splitlines()
    return program_name(line[0]) if line else None
