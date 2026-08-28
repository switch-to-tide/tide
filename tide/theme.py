"""Colour palettes (xterm-256 indices) and the live theme.

Modules read `theme.NAME` at draw time, so switching a theme is just a matter
of rewriting these module globals and asking for a repaint.
"""

# ---------------------------------------------------------------- palettes

# "dark" - the default, in the spirit of VS Code's Dark+
DARK = dict(
    BG=235, BG_ALT=236, PANEL=236, PANEL_ALT=238,
    FG=252, FG_DIM=245, BORDER=240, BORDER_HL=39,
    GUTTER_BG=235, LINENO=240, LINENO_CUR=250,
    SELECTION=24, FIND_MATCH=58, FIND_CUR=130,
    SCROLL_TRACK=237, SCROLL_THUMB=243, SCROLL_THUMB_HL=250,
    TAB_ACTIVE_BG=235, TAB_ACTIVE_FG=252, TAB_BG=238, TAB_FG=245, TAB_MARK=214,
    STATUS_BG=25, STATUS_FG=253, STATUS_ACC=39,
    TREE_DIR=117, TREE_GUIDE=239, TREE_FILE=250, TREE_SEL_BG=24,
    ERROR=203, WARN=179, OK=114,
    TERM_BG=234, TERM_FG=252,
    GIT_UNTRACKED=114, GIT_ADDED=114, GIT_MODIFIED=179, GIT_DELETED=203,
    GIT_RENAMED=179, GIT_CONFLICT=168,
    GIT_LINE_ADDED=114, GIT_LINE_MODIFIED=39, GIT_LINE_DELETED=203,
    GIT_IGNORED=241,
    TOK_TEXT=252, TOK_COMMENT=71, TOK_STRING=173, TOK_NUMBER=151,
    TOK_KEYWORD=75, TOK_CONTROL=176, TOK_TYPE=79, TOK_FUNCTION=187,
    TOK_BUILTIN=117, TOK_CONSTANT=75, TOK_OPERATOR=250, TOK_PUNCT=248,
    TOK_PREPROC=176, TOK_ATTR=187, TOK_PROPERTY=117, TOK_HEADING=75,
    TOK_LINK=117, TOK_EMPH=252, TOK_STRONG=252, TOK_TAG=75, TOK_INVALID=203,
)

# "midnight" - darker and cooler, low contrast chrome
MIDNIGHT = dict(
    DARK,
    BG=233, BG_ALT=234, PANEL=234, PANEL_ALT=236,
    FG=251, FG_DIM=243, BORDER=238, BORDER_HL=75,
    GUTTER_BG=233, LINENO=241, LINENO_CUR=250,
    SELECTION=17, FIND_MATCH=23, FIND_CUR=31,
    SCROLL_TRACK=235, SCROLL_THUMB=240, SCROLL_THUMB_HL=248,
    TAB_ACTIVE_BG=233, TAB_ACTIVE_FG=252, TAB_BG=236, TAB_FG=243, TAB_MARK=110,
    STATUS_BG=17, STATUS_FG=252, STATUS_ACC=75,
    TREE_DIR=110, TREE_GUIDE=237, TREE_FILE=248, TREE_SEL_BG=17,
    TERM_BG=232, TERM_FG=251,
    GIT_LINE_MODIFIED=75, GIT_IGNORED=239,
    TOK_TEXT=251, TOK_COMMENT=66, TOK_STRING=150, TOK_NUMBER=180,
    TOK_KEYWORD=111, TOK_CONTROL=140, TOK_TYPE=73, TOK_FUNCTION=110,
    TOK_BUILTIN=109, TOK_CONSTANT=111, TOK_OPERATOR=246, TOK_PUNCT=244,
    TOK_PREPROC=140, TOK_ATTR=110, TOK_PROPERTY=109, TOK_HEADING=111,
    TOK_LINK=109, TOK_EMPH=251, TOK_STRONG=251, TOK_TAG=111,
)

# "ember" - warm dark, in the gruvbox family
EMBER = dict(
    DARK,
    BG=235, BG_ALT=237, PANEL=237, PANEL_ALT=239,
    FG=223, FG_DIM=245, BORDER=241, BORDER_HL=214,
    GUTTER_BG=235, LINENO=241, LINENO_CUR=223,
    SELECTION=239, FIND_MATCH=58, FIND_CUR=136,
    SCROLL_TRACK=237, SCROLL_THUMB=243, SCROLL_THUMB_HL=223,
    TAB_ACTIVE_BG=235, TAB_ACTIVE_FG=223, TAB_BG=239, TAB_FG=245, TAB_MARK=214,
    STATUS_BG=239, STATUS_FG=223, STATUS_ACC=214,
    TREE_DIR=109, TREE_GUIDE=240, TREE_FILE=223, TREE_SEL_BG=239,
    ERROR=167, WARN=214, OK=142,
    TERM_BG=234, TERM_FG=223,
    GIT_UNTRACKED=142, GIT_ADDED=142, GIT_MODIFIED=214, GIT_DELETED=167,
    GIT_RENAMED=214, GIT_CONFLICT=175,
    GIT_LINE_ADDED=142, GIT_LINE_MODIFIED=109, GIT_LINE_DELETED=167,
    GIT_IGNORED=243,
    TOK_TEXT=223, TOK_COMMENT=245, TOK_STRING=142, TOK_NUMBER=175,
    TOK_KEYWORD=214, TOK_CONTROL=167, TOK_TYPE=108, TOK_FUNCTION=214,
    TOK_BUILTIN=109, TOK_CONSTANT=175, TOK_OPERATOR=223, TOK_PUNCT=246,
    TOK_PREPROC=175, TOK_ATTR=208, TOK_PROPERTY=109, TOK_HEADING=214,
    TOK_LINK=109, TOK_EMPH=223, TOK_STRONG=223, TOK_TAG=214, TOK_INVALID=167,
)

# "light" - for a bright terminal
LIGHT = dict(
    DARK,
    BG=255, BG_ALT=254, PANEL=253, PANEL_ALT=251,
    FG=236, FG_DIM=243, BORDER=250, BORDER_HL=32,
    GUTTER_BG=255, LINENO=245, LINENO_CUR=236,
    SELECTION=153, FIND_MATCH=222, FIND_CUR=214,
    SCROLL_TRACK=252, SCROLL_THUMB=247, SCROLL_THUMB_HL=241,
    TAB_ACTIVE_BG=255, TAB_ACTIVE_FG=235, TAB_BG=252, TAB_FG=243, TAB_MARK=166,
    STATUS_BG=32, STATUS_FG=255, STATUS_ACC=26,
    TREE_DIR=26, TREE_GUIDE=251, TREE_FILE=238, TREE_SEL_BG=153,
    ERROR=160, WARN=130, OK=28,
    TERM_BG=255, TERM_FG=236,
    GIT_UNTRACKED=28, GIT_ADDED=28, GIT_MODIFIED=130, GIT_DELETED=160,
    GIT_RENAMED=130, GIT_CONFLICT=125,
    GIT_LINE_ADDED=28, GIT_LINE_MODIFIED=26, GIT_LINE_DELETED=160,
    GIT_IGNORED=250,
    TOK_TEXT=236, TOK_COMMENT=28, TOK_STRING=124, TOK_NUMBER=29,
    TOK_KEYWORD=26, TOK_CONTROL=90, TOK_TYPE=30, TOK_FUNCTION=94,
    TOK_BUILTIN=18, TOK_CONSTANT=26, TOK_OPERATOR=238, TOK_PUNCT=242,
    TOK_PREPROC=90, TOK_ATTR=94, TOK_PROPERTY=18, TOK_HEADING=26,
    TOK_LINK=18, TOK_EMPH=236, TOK_STRONG=236, TOK_TAG=26, TOK_INVALID=160,
)

# ------------------------------------------------------------------ modern
# The modern appearance draws every pane as a floating box. Its palettes are
# flatter for that reason: the panel and the editor share a background, and
# the borders do the separating that block colour does in the classic ones.

M_DARK = dict(
    DARK,
    BG=235, BG_ALT=236, PANEL=235, PANEL_ALT=235,
    BORDER=240, BORDER_HL=39,
    GUTTER_BG=235, SCROLL_TRACK=236, SCROLL_THUMB=240, SCROLL_THUMB_HL=248,
    TAB_ACTIVE_BG=235, TAB_ACTIVE_FG=252, TAB_BG=235, TAB_FG=243,
    STATUS_BG=235, STATUS_FG=250, STATUS_ACC=39,
    TREE_SEL_BG=237, TERM_BG=235,
)

# "alien" - very dark, with the accents turned right up
M_ALIEN = dict(
    M_DARK,
    BG=232, BG_ALT=233, PANEL=232, PANEL_ALT=232, TERM_BG=232,
    FG=251, FG_DIM=243, BORDER=238, BORDER_HL=190,
    GUTTER_BG=232, LINENO=239, LINENO_CUR=190,
    SELECTION=54, FIND_MATCH=100, FIND_CUR=127,
    SCROLL_TRACK=233, SCROLL_THUMB=239, SCROLL_THUMB_HL=190,
    TAB_ACTIVE_BG=232, TAB_ACTIVE_FG=190, TAB_BG=232, TAB_FG=243, TAB_MARK=213,
    STATUS_BG=232, STATUS_FG=190, STATUS_ACC=129,
    TREE_DIR=141, TREE_GUIDE=236, TREE_FILE=250, TREE_SEL_BG=53,
    ERROR=197, WARN=190, OK=118, GIT_IGNORED=238,
    GIT_UNTRACKED=118, GIT_ADDED=118, GIT_MODIFIED=190, GIT_DELETED=197,
    GIT_RENAMED=190, GIT_CONFLICT=201,
    GIT_LINE_ADDED=118, GIT_LINE_MODIFIED=141, GIT_LINE_DELETED=197,
    TOK_COMMENT=240, TOK_STRING=214, TOK_NUMBER=157,
    TOK_KEYWORD=213, TOK_CONTROL=201, TOK_TYPE=87, TOK_FUNCTION=190,
    TOK_BUILTIN=141, TOK_CONSTANT=213, TOK_OPERATOR=248, TOK_PUNCT=245,
    TOK_PREPROC=201, TOK_ATTR=190, TOK_PROPERTY=87, TOK_HEADING=213,
    TOK_LINK=87, TOK_TAG=213, TOK_INVALID=197,
)

# "forest" - the same darkness, calmed down: green, moss and slate
M_FOREST = dict(
    M_DARK,
    BG=233, BG_ALT=234, PANEL=233, PANEL_ALT=233, TERM_BG=233,
    FG=252, FG_DIM=245, BORDER=238, BORDER_HL=72,
    GUTTER_BG=233, LINENO=239, LINENO_CUR=108,
    SELECTION=23, FIND_MATCH=58, FIND_CUR=64,
    SCROLL_TRACK=234, SCROLL_THUMB=239, SCROLL_THUMB_HL=108,
    TAB_ACTIVE_BG=233, TAB_ACTIVE_FG=115, TAB_BG=233, TAB_FG=244, TAB_MARK=180,
    STATUS_BG=233, STATUS_FG=115, STATUS_ACC=72,
    TREE_DIR=109, TREE_GUIDE=236, TREE_FILE=250, TREE_SEL_BG=23,
    ERROR=167, WARN=180, OK=108, GIT_IGNORED=238,
    GIT_UNTRACKED=108, GIT_ADDED=108, GIT_MODIFIED=180, GIT_DELETED=167,
    GIT_RENAMED=180, GIT_CONFLICT=175,
    GIT_LINE_ADDED=108, GIT_LINE_MODIFIED=74, GIT_LINE_DELETED=167,
    TOK_COMMENT=65, TOK_STRING=144, TOK_NUMBER=151,
    TOK_KEYWORD=109, TOK_CONTROL=110, TOK_TYPE=115, TOK_FUNCTION=187,
    TOK_BUILTIN=108, TOK_CONSTANT=109, TOK_OPERATOR=248, TOK_PUNCT=245,
    TOK_PREPROC=110, TOK_ATTR=187, TOK_PROPERTY=115, TOK_HEADING=109,
    TOK_LINK=110, TOK_TAG=109, TOK_INVALID=167,
)

M_LIGHT = dict(
    LIGHT,
    BG=255, BG_ALT=254, PANEL=255, PANEL_ALT=255, TERM_BG=255,
    BORDER=250, BORDER_HL=32,
    GUTTER_BG=255, SCROLL_TRACK=254, SCROLL_THUMB=249, SCROLL_THUMB_HL=240,
    TAB_ACTIVE_BG=255, TAB_ACTIVE_FG=236, TAB_BG=255, TAB_FG=245,
    STATUS_BG=255, STATUS_FG=238, STATUS_ACC=32,
    TREE_SEL_BG=252,
)

APPEARANCES = {
    'classic': {'dark': DARK, 'midnight': MIDNIGHT, 'ember': EMBER,
                'light': LIGHT},
    'modern': {'dark': M_DARK, 'alien': M_ALIEN, 'forest': M_FOREST,
               'light': M_LIGHT},
}

# the panes are drawn as floating boxes in one appearance and flush in the
# other; this is the only thing outside the palette that appearance changes
BOXED = False
appearance = 'classic'

PALETTES = {'dark': DARK, 'midnight': MIDNIGHT, 'ember': EMBER, 'light': LIGHT}
NAMES = ['dark', 'midnight', 'ember', 'light']


def appearance_for(name, preferred=None):
    """Which appearance offers this palette, preferring the one in use."""
    if preferred and name in APPEARANCES.get(preferred, {}):
        return preferred
    for look, palettes in APPEARANCES.items():
        if name in palettes:
            return look
    return preferred or 'classic'


def names_for(look):
    """The four palettes an appearance offers, in the order they are shown."""
    return list(APPEARANCES.get(look, APPEARANCES['classic']).keys())

# token kind -> (palette key, attribute bits); 1 = bold, 4 = underline
_TOKENS = {
    'text': ('TOK_TEXT', 0), 'comment': ('TOK_COMMENT', 0),
    'string': ('TOK_STRING', 0), 'number': ('TOK_NUMBER', 0),
    'keyword': ('TOK_KEYWORD', 0), 'control': ('TOK_CONTROL', 0),
    'type': ('TOK_TYPE', 0), 'function': ('TOK_FUNCTION', 0),
    'builtin': ('TOK_BUILTIN', 0), 'constant': ('TOK_CONSTANT', 0),
    'operator': ('TOK_OPERATOR', 0), 'punct': ('TOK_PUNCT', 0),
    'preproc': ('TOK_PREPROC', 0), 'attr': ('TOK_ATTR', 0),
    'property': ('TOK_PROPERTY', 0), 'heading': ('TOK_HEADING', 1),
    'link': ('TOK_LINK', 8), 'emph': ('TOK_EMPH', 4),
    'strong': ('TOK_STRONG', 1), 'tag': ('TOK_TAG', 0),
    'invalid': ('TOK_INVALID', 0),
}

current = 'dark'
TOKEN = {}
STATUS_COLOUR = {}
LINE_COLOUR = {}


def apply(name, look=None):
    """Switch the live palette; returns the name actually applied.

    `look` is the appearance - which set of four palettes to pick from, and
    whether the panes are drawn as boxes. Everything else about drawing is the
    same either way.
    """
    global current, appearance, BOXED, TOKEN, STATUS_COLOUR, LINE_COLOUR
    if look is None:
        look = appearance
    if look not in APPEARANCES:
        look = 'classic'
    palettes = APPEARANCES[look]
    palette = palettes.get(name)
    if palette is None:
        name = names_for(look)[0]
        palette = palettes[name]
    appearance = look
    BOXED = look == 'modern'
    current = name
    globals().update(palette)
    TOKEN = dict((kind, (palette[key], attr))
                 for kind, (key, attr) in _TOKENS.items())
    STATUS_COLOUR = {
        'U': palette['GIT_UNTRACKED'], 'A': palette['GIT_ADDED'],
        'M': palette['GIT_MODIFIED'], 'D': palette['GIT_DELETED'],
        'R': palette['GIT_RENAMED'], '!': palette['GIT_CONFLICT'],
    }
    LINE_COLOUR = {
        'added': palette['GIT_LINE_ADDED'],
        'modified': palette['GIT_LINE_MODIFIED'],
        'deleted': palette['GIT_LINE_DELETED'],
    }
    return name


def token_style(kind):
    return TOKEN.get(kind, TOKEN['text'])


def git_colour(letter):
    return STATUS_COLOUR.get(letter, FG)


apply('dark')
