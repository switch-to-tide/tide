"""Clipboard that prefers the system clipboard and falls back to an internal one."""

import os
import subprocess
import sys

_internal = ['']


def _system_enabled():
    """Tests (and headless use) can opt out of touching the real clipboard."""
    return os.environ.get('TIDE_NO_SYSTEM_CLIPBOARD') != '1' 


def _cmds():
    if sys.platform == 'darwin':
        return ['pbcopy'], ['pbpaste']
    return ['xclip', '-selection', 'clipboard'], ['xclip', '-selection', 'clipboard', '-o']


def copy(text):
    _internal[0] = text
    if not _system_enabled():
        return
    cmd, _ = _cmds()
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        p.communicate(text.encode('utf-8'), timeout=2)
    except Exception:
        pass


def paste():
    if not _system_enabled():
        return _internal[0]
    _, cmd = _cmds()
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2)
        text = out.decode('utf-8', 'replace')
        if text or not _internal[0]:
            return text
    except Exception:
        pass
    return _internal[0]
