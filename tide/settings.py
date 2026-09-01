"""Global preferences, kept in one JSON file so they follow you between repos."""

import io
import json
import os

DEFAULTS = {
    'appearance': 'modern',
    'theme': 'dark',
    'autosave': True,
    'autosave_delay': 0.8,
    'max_lines': 20000,
    'max_mb': 2.0,
    'show_terminal': True,
    'split_view': False,
    'show_tree': True,
    'tab_width': 4,
    'wrap': 'smart',
    'menu_hover': True,
    'images': 'auto',
    'audio': False,
    'audio_sink_port': 0,
    'sidebar_width': 26,
    'split_ratio': 0.5,
    'terminal_height': 0,
    'review_open_modified': True,
    'review_open_added': False,
    'review_open_deleted': False,
}

# key, label, the values it cycles through
# 'appearance' is deliberately not here: the modern one is what tide looks
# like now, and classic is kept only for the --appearance flag (see theme.py)
FIELDS = [
    ('theme', 'Theme', ['dark', 'midnight', 'ember', 'light']),
    ('autosave', 'Auto-save', [True, False]),
    ('autosave_delay', 'Auto-save after', [0.3, 0.5, 0.8, 1.0, 2.0, 5.0]),
    ('max_lines', 'Ask above lines', [2000, 5000, 20000, 100000]),
    ('max_mb', 'Ask above size', [0.5, 1.0, 2.0, 5.0, 20.0]),
    ('show_terminal', 'Terminal panel', [True, False]),
    ('split_view', 'Split view', [True, False]),
    ('show_tree', 'Explorer', [True, False]),
    ('tab_width', 'Indent width', [2, 4, 8]),
    ('wrap', 'Long lines', ['smart', 'on', 'off']),
    ('menu_hover', 'Menu follows mouse', [True, False]),
    ('images', 'Pictures', ['auto', 'blocks']),
    ('audio', 'Audio playback', [True, False]),
    ('review_open_modified', 'Review: modified files', [True, False]),
    ('review_open_added', 'Review: added files', [True, False]),
    ('review_open_deleted', 'Review: deleted files', [True, False]),
]

HINTS = {
    'theme': 'colours for the whole app',
    'autosave': 'save shortly after you type',
    'autosave_delay': 'seconds of quiet before saving',
    'max_lines': 'longer files ask first',
    'max_mb': 'bigger files ask first',
    'show_terminal': 'bottom panel, at startup',
    'split_view': 'editor and terminal side by side',
    'show_tree': 'file explorer, at startup',
    'tab_width': 'when a file has none to copy',
    'wrap': 'wrap them, or scroll sideways',
    'menu_hover': 'off if your terminal dislikes it',
    'images': 'real pixels where the terminal can, else blocks',
    'audio': 'needs ffmpeg or mpv; off until it is there',
    'review_open_modified': 'open, or folded to one line',
    'review_open_added': 'open, or folded to one line',
    'review_open_deleted': 'open, or folded to one line',
}


def config_path():
    base = os.environ.get('TIDE_CONFIG_HOME') or os.environ.get('XDG_CONFIG_HOME')
    if not base:
        base = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'tide', 'settings.json')


CHOICES = dict((key, options) for key, _label, options in FIELDS)
# not a field any more, but a hand-edited file still has to make sense
CHOICES['appearance'] = ['classic', 'modern']


def choices(key, values=None):
    """What a field can be set to, given what everything else is set to.

    Only the theme depends on anything: each appearance brings its own four
    palettes, and nothing else about it changes.
    """
    if key == 'theme':
        from . import theme as theme_mod
        look = (values or {}).get('appearance', DEFAULTS['appearance'])
        return theme_mod.names_for(look)
    return CHOICES.get(key, [])

# hand-edited values do not have to be one of the offered choices, but they
# do have to be sane
LIMITS = {
    'audio_sink_port': (0, 65535),
    'sidebar_width': (8, 400),
    'split_ratio': (0.15, 0.85),
    'terminal_height': (0, 400),
    'autosave_delay': (0.1, 30.0),
    'max_lines': (100, 10000000),
    'max_mb': (0.01, 2000.0),
    'tab_width': (1, 16),
}


def _coerce(key, value):
    """Keep a hand-edited file from breaking the app."""
    default = DEFAULTS[key]
    try:
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, float):
            value = float(value)
        elif isinstance(default, int):
            value = int(value)
        else:
            value = str(value)
    except (TypeError, ValueError):
        return default
    if isinstance(default, str):
        allowed = CHOICES.get(key, [value])
        if key == 'theme':
            allowed = choices('theme', {'appearance': 'classic'}) + \
                choices('theme', {'appearance': 'modern'})
        return value if value in allowed else default
    low, high = LIMITS.get(key, (None, None))
    if low is not None:
        value = max(low, min(high, value))
    return value


def load(path=None):
    values = dict(DEFAULTS)
    path = path or config_path()
    try:
        with io.open(path, 'r', encoding='utf-8') as f:
            stored = json.load(f)
    except Exception:
        return values                      # missing or malformed: use defaults
    if not isinstance(stored, dict):
        return values
    for key in DEFAULTS:
        if key in stored:
            values[key] = _coerce(key, stored[key])
    return values


def save(values, path=None):
    path = path or config_path()
    keep = dict((k, values[k]) for k in DEFAULTS if k in values)
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        tmp = path + '.tmp'
        with io.open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(keep, indent=2, sort_keys=True))
            f.write(u'\n')
        os.replace(tmp, path)
        return True
    except Exception:
        return False


WRAP_WORDS = {'smart': 'wrap text files', 'on': 'wrap all', 'off': 'scroll all'}


def show(key, value):
    """How a value is written in the settings panel."""
    if key == 'wrap':
        return WRAP_WORDS.get(value, value)
    if isinstance(value, bool):
        return 'on' if value else 'off'
    if key == 'max_mb':
        return ('%g MB' % value)
    if key == 'autosave_delay':
        return ('%gs' % value)
    if key == 'max_lines':
        return '{:,}'.format(value).replace(',', ' ')
    return str(value)
