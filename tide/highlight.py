"""Small dependency-free syntax highlighter.

Each language is either a `Lang` (a real tokenizer: comments, strings, numbers,
identifiers) or a list of regex rules for markup-ish formats.  `tokens()`
returns spans for one line plus the state to carry into the next line, so
multi-line strings and block comments survive scrolling.
"""

import re

IDENT = re.compile(r'[A-Za-z_$][A-Za-z_$0-9]*')
NUMBER = re.compile(
    r'0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|'
    r'\d[\d_]*\.?[\d_]*(?:[eE][-+]?\d+)?[a-zA-Z_]*')
OPCHARS = set('+-*/%=<>!&|^~?:.,;')
PUNCT = set('()[]{}')

# state encoding: 0 = normal, 1 = block comment, 2 + i = inside string #i
ST_NORMAL = 0
ST_BLOCK = 1
ST_STR = 2


class Lang(object):
    def __init__(self, name, line_comment=(), block=None, strings=(),
                 keywords=(), controls=(), types=(), builtins=(), constants=(),
                 preproc=None, decorator=None, tab_width=4, comment_token=None):
        self.name = name
        self.line_comment = tuple(line_comment)
        self.block = block                # (open, close)
        # strings: list of (open, close, escape_char, multiline)
        self.strings = list(strings)
        self.keywords = set(keywords)
        self.controls = set(controls)
        self.types = set(types)
        self.builtins = set(builtins)
        self.constants = set(constants)
        self.preproc = preproc            # regex for whole-line preprocessor
        self.decorator = decorator        # regex for decorators/attributes
        self.tab_width = tab_width
        self.comment_token = comment_token or (
            self.line_comment[0] if self.line_comment else None)


def _kw(s):
    return s.split()

PY = Lang(
    'Python', line_comment=('#',),
    strings=[('"""', '"""', '\\', True), ("'''", "'''", '\\', True),
             ('"', '"', '\\', False), ("'", "'", '\\', False)],
    keywords=_kw('def class lambda import from as global nonlocal del assert '
                 'with async await yield pass in is not and or None True False self cls'),
    controls=_kw('if elif else for while try except finally return break continue raise match case'),
    types=_kw('int float str bool bytes list dict set tuple frozenset object type complex'),
    builtins=_kw('print len range enumerate zip map filter open isinstance super '
                 'getattr setattr hasattr sorted sum min max abs any all repr format '
                 'staticmethod classmethod property Exception ValueError TypeError KeyError'),
    constants=_kw('None True False __name__ __file__'),
    decorator=re.compile(r'@[A-Za-z_][\w.]*'))

JS = Lang(
    'JavaScript', line_comment=('//',), block=('/*', '*/'),
    strings=[('`', '`', '\\', True), ('"', '"', '\\', False), ("'", "'", '\\', False)],
    keywords=_kw('function var let const class extends new delete typeof instanceof '
                 'in of this super import export from as default async await yield '
                 'static get set void interface type enum implements declare namespace public '
                 'private protected readonly abstract'),
    controls=_kw('if else for while do switch case break continue return try catch finally throw'),
    types=_kw('string number boolean any unknown never object symbol bigint Array Promise Map Set '
              'Record Partial Readonly Date RegExp Error'),
    builtins=_kw('console document window JSON Math Object require module exports process'),
    constants=_kw('true false null undefined NaN Infinity'), tab_width=2)

RUST = Lang(
    'Rust', line_comment=('//',), block=('/*', '*/'),
    strings=[('"', '"', '\\', True), ("'", "'", '\\', False)],
    keywords=_kw('fn let mut const static struct enum impl trait type use mod pub crate '
                 'self super as where dyn ref move async await unsafe extern'),
    controls=_kw('if else match loop while for break continue return'),
    types=_kw('i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64 bool char str '
              'String Vec Option Result Box Rc Arc HashMap HashSet Self'),
    builtins=_kw('println print format vec panic write writeln assert assert_eq derive'),
    constants=_kw('true false None Some Ok Err'),
    decorator=re.compile(r'#!?\[[^\]]*\]'))

C = Lang(
    'C', line_comment=('//',), block=('/*', '*/'),
    strings=[('"', '"', '\\', False), ("'", "'", '\\', False)],
    keywords=_kw('auto extern register static const volatile inline struct union enum typedef '
                 'sizeof class public private protected virtual template typename namespace using '
                 'new delete this operator friend explicit constexpr nullptr'),
    controls=_kw('if else for while do switch case default break continue return goto try catch throw'),
    types=_kw('void char short int long float double signed unsigned bool size_t uint8_t uint16_t '
              'uint32_t uint64_t int8_t int16_t int32_t int64_t FILE std string vector map'),
    constants=_kw('true false NULL'),
    preproc=re.compile(r'^\s*#\s*\w+'))

GO = Lang(
    'Go', line_comment=('//',), block=('/*', '*/'),
    strings=[('`', '`', None, True), ('"', '"', '\\', False), ("'", "'", '\\', False)],
    keywords=_kw('package import func var const type struct interface map chan go defer '
                 'range select fallthrough'),
    controls=_kw('if else for switch case default break continue return goto'),
    types=_kw('string int int8 int16 int32 int64 uint uint8 uint16 uint32 uint64 byte rune '
              'float32 float64 bool error any'),
    builtins=_kw('make new len cap append copy delete panic recover print println close'),
    constants=_kw('true false nil iota'), tab_width=4)

JAVA = Lang(
    'Java', line_comment=('//',), block=('/*', '*/'),
    strings=[('"', '"', '\\', False), ("'", "'", '\\', False)],
    keywords=_kw('class interface enum extends implements public private protected static final '
                 'abstract synchronized volatile transient native package import new this super '
                 'instanceof throws record var'),
    controls=_kw('if else for while do switch case default break continue return try catch finally throw'),
    types=_kw('void boolean byte char short int long float double String Object List Map Set Integer'),
    constants=_kw('true false null'),
    decorator=re.compile(r'@[A-Za-z_]\w*'))

SH = Lang(
    'Shell', line_comment=('#',),
    strings=[('"', '"', '\\', False), ("'", "'", None, False)],
    keywords=_kw('function local export readonly declare source alias unset set shift eval exec trap'),
    controls=_kw('if then elif else fi for while until do done case esac in return break continue select time'),
    builtins=_kw('echo printf cd ls cat grep sed awk cut sort uniq head tail find xargs test '
                 'mkdir rm cp mv touch chmod chown kill ps pwd read exit sleep git python python3 npm node make'),
    constants=_kw('true false'))

SQL = Lang(
    'SQL', line_comment=('--',), block=('/*', '*/'),
    strings=[("'", "'", "'", False), ('"', '"', '"', False)],
    keywords=_kw('SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE DROP ALTER '
                 'INDEX VIEW JOIN LEFT RIGHT INNER OUTER ON GROUP BY ORDER HAVING LIMIT OFFSET '
                 'AS DISTINCT UNION ALL AND OR NOT IN EXISTS BETWEEN LIKE IS PRIMARY KEY FOREIGN '
                 'REFERENCES DEFAULT'),
    types=_kw('INT INTEGER TEXT VARCHAR CHAR BOOLEAN DATE TIMESTAMP FLOAT DOUBLE DECIMAL SERIAL BLOB'),
    constants=_kw('NULL TRUE FALSE'))

CSS = Lang(
    'CSS', block=('/*', '*/'),
    strings=[('"', '"', '\\', False), ("'", "'", '\\', False)],
    keywords=_kw('important inherit initial unset auto none flex grid block inline absolute '
                 'relative fixed sticky hidden visible bold italic center'),
    decorator=re.compile(r'@[A-Za-z-]+|[.#][A-Za-z_-][\w-]*|:{1,2}[a-z-]+'))

JSON_L = Lang(
    'JSON', strings=[('"', '"', '\\', False)],
    constants=_kw('true false null'))

TOML = Lang(
    'TOML', line_comment=('#',),
    strings=[('"""', '"""', '\\', True), ('"', '"', '\\', False), ("'", "'", None, False)],
    constants=_kw('true false'),
    decorator=re.compile(r'^\s*\[\[?[^\]]*\]\]?'))

LANGS = {}


def _reg(lang, *exts):
    for e in exts:
        LANGS[e] = lang


_reg(PY, '.py', '.pyi', '.pyw')
_reg(JS, '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx')
_reg(RUST, '.rs')
_reg(C, '.c', '.h', '.cc', '.cpp', '.cxx', '.hpp', '.hh', '.m', '.mm')
_reg(GO, '.go')
_reg(JAVA, '.java', '.kt', '.kts', '.scala', '.cs', '.swift')
_reg(SH, '.sh', '.bash', '.zsh', '.fish', '.env', '.bashrc', '.zshrc')
_reg(SQL, '.sql')
_reg(CSS, '.css', '.scss', '.less')
_reg(JSON_L, '.json', '.jsonc', '.ipynb')
_reg(TOML, '.toml')

# --- regex-rule languages -------------------------------------------------

MD_RULES = [
    (re.compile(r'^\s{0,3}#{1,6}\s.*$'), 'heading'),
    (re.compile(r'^\s{0,3}(?:```|~~~).*$'), 'string'),
    (re.compile(r'^\s{0,3}>\s?.*$'), 'comment'),
    (re.compile(r'`[^`]*`'), 'string'),
    (re.compile(r'\*\*[^*]+\*\*|__[^_]+__'), 'strong'),
    (re.compile(r'\*[^*]+\*|_[^_]+_'), 'emph'),
    (re.compile(r'!?\[[^\]]*\]\([^)]*\)'), 'link'),
    (re.compile(r'^\s*(?:[-*+]|\d+\.)\s'), 'keyword'),
    (re.compile(r'^\s*(?:---+|===+|\*\*\*+)\s*$'), 'punct'),
]

YAML_RULES = [
    (re.compile(r'#.*$'), 'comment'),
    (re.compile(r'^\s*-?\s*[\w.\-/ ]+:(?=\s|$)'), 'property'),
    (re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''), 'string'),
    (re.compile(r'\b(?:true|false|null|yes|no|on|off)\b', re.I), 'constant'),
    (re.compile(r'\b\d+(?:\.\d+)?\b'), 'number'),
    (re.compile(r'^\s*-\s'), 'punct'),
    (re.compile(r'[&*][\w-]+|<<:'), 'keyword'),
]

HTML_RULES = [
    (re.compile(r'<!--.*?-->'), 'comment'),
    (re.compile(r'</?[A-Za-z][\w:-]*'), 'tag'),
    (re.compile(r'/?>'), 'tag'),
    (re.compile(r'\b[A-Za-z-]+(?==)'), 'attr'),
    (re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''), 'string'),
    (re.compile(r'&\w+;'), 'constant'),
]

INI_RULES = [
    (re.compile(r'[#;].*$'), 'comment'),
    (re.compile(r'^\s*\[[^\]]*\]'), 'type'),
    (re.compile(r'^\s*[\w.\-]+(?=\s*=)'), 'property'),
    (re.compile(r'"(?:[^"\\]|\\.)*"'), 'string'),
]

DIFF_RULES = [
    (re.compile(r'^\+.*$'), 'number'),
    (re.compile(r'^-.*$'), 'invalid'),
    (re.compile(r'^@@.*$'), 'control'),
    (re.compile(r'^(?:diff|index|---|\+\+\+).*$'), 'keyword'),
]

RULE_LANGS = {
    '.md': ('Markdown', MD_RULES, '<!--'),
    '.markdown': ('Markdown', MD_RULES, '<!--'),
    '.yml': ('YAML', YAML_RULES, '#'),
    '.yaml': ('YAML', YAML_RULES, '#'),
    '.html': ('HTML', HTML_RULES, '<!--'),
    '.htm': ('HTML', HTML_RULES, '<!--'),
    '.xml': ('XML', HTML_RULES, '<!--'),
    '.svg': ('XML', HTML_RULES, '<!--'),
    '.vue': ('HTML', HTML_RULES, '<!--'),
    '.ini': ('INI', INI_RULES, '#'),
    '.cfg': ('INI', INI_RULES, '#'),
    '.conf': ('INI', INI_RULES, '#'),
    '.diff': ('Diff', DIFF_RULES, '#'),
    '.patch': ('Diff', DIFF_RULES, '#'),
}

BASENAMES = {
    'Makefile': SH, 'makefile': SH, 'Dockerfile': SH, 'Gemfile': SH,
    '.gitignore': SH, '.envrc': SH, 'CMakeLists.txt': SH,
}


class Highlighter(object):
    """Highlighter for one file type."""

    def __init__(self, lang=None, rules=None, name='Plain', comment_token=None):
        self.lang = lang
        self.rules = rules
        self.name = lang.name if lang else name
        self.comment_token = (lang.comment_token if lang else comment_token)
        self.tab_width = lang.tab_width if lang else 4

    @classmethod
    def for_path(cls, path):
        import os
        base = os.path.basename(path or '')
        _, ext = os.path.splitext(base)
        ext = ext.lower()
        if base in BASENAMES:
            return cls(lang=BASENAMES[base])
        if ext in LANGS:
            return cls(lang=LANGS[ext])
        if ext in RULE_LANGS:
            name, rules, ctok = RULE_LANGS[ext]
            return cls(rules=rules, name=name, comment_token=ctok)
        return cls(name='Plain', comment_token='#')

    def tokens(self, line, state=ST_NORMAL):
        """-> (spans, next_state); spans is a list of (start, end, kind)."""
        if self.rules is not None:
            return self._rule_tokens(line), ST_NORMAL
        if self.lang is None:
            return [], ST_NORMAL
        return self._code_tokens(line, state)

    # -- regex rule languages
    def _rule_tokens(self, line):
        spans = []
        taken = [False] * (len(line) + 1)
        for rx, kind in self.rules:
            for m in rx.finditer(line):
                s, e = m.start(), m.end()
                if e <= s or any(taken[s:e]):
                    continue
                for i in range(s, e):
                    taken[i] = True
                spans.append((s, e, kind))
        spans.sort()
        return spans

    # -- real tokenizer
    def _code_tokens(self, line, state):
        lang = self.lang
        spans = []
        n = len(line)
        i = 0
        if state == ST_BLOCK and lang.block:
            close = lang.block[1]
            idx = line.find(close)
            if idx < 0:
                return [(0, n, 'comment')], ST_BLOCK
            spans.append((0, idx + len(close), 'comment'))
            i = idx + len(close)
            state = ST_NORMAL
        elif state >= ST_STR:
            si = state - ST_STR
            if si < len(lang.strings):
                _o, close, esc, _ml = lang.strings[si]
                end = self._find_close(line, 0, close, esc)
                if end < 0:
                    return [(0, n, 'string')], state
                spans.append((0, end, 'string'))
                i = end
                state = ST_NORMAL
        if state == ST_NORMAL and i == 0:
            if lang.preproc:
                m = lang.preproc.match(line)
                if m:
                    spans.append((0, m.end(), 'preproc'))
                    i = m.end()

        while i < n:
            ch = line[i]
            if ch in ' \t':
                i += 1
                continue
            # line comment
            hit = False
            for lc in lang.line_comment:
                if line.startswith(lc, i):
                    spans.append((i, n, 'comment'))
                    return spans, ST_NORMAL
            # block comment
            if lang.block and line.startswith(lang.block[0], i):
                close = lang.block[1]
                idx = line.find(close, i + len(lang.block[0]))
                if idx < 0:
                    spans.append((i, n, 'comment'))
                    return spans, ST_BLOCK
                spans.append((i, idx + len(close), 'comment'))
                i = idx + len(close)
                continue
            # strings
            for si, (op, close, esc, ml) in enumerate(lang.strings):
                if line.startswith(op, i):
                    end = self._find_close(line, i + len(op), close, esc)
                    if end < 0:
                        spans.append((i, n, 'string'))
                        return spans, (ST_STR + si) if ml else ST_NORMAL
                    spans.append((i, end, 'string'))
                    i = end
                    hit = True
                    break
            if hit:
                continue
            # decorators / attributes
            if lang.decorator:
                m = lang.decorator.match(line, i)
                if m and m.end() > m.start():
                    spans.append((m.start(), m.end(), 'attr'))
                    i = m.end()
                    continue
            # numbers
            if ch.isdigit() or (ch == '.' and i + 1 < n and line[i + 1].isdigit()):
                m = NUMBER.match(line, i)
                if m:
                    spans.append((i, m.end(), 'number'))
                    i = m.end()
                    continue
            # identifiers
            m = IDENT.match(line, i)
            if m:
                word = m.group(0)
                end = m.end()
                if word in lang.controls:
                    kind = 'control'
                elif word in lang.constants:
                    kind = 'constant'
                elif word in lang.keywords:
                    kind = 'keyword'
                elif word in lang.types:
                    kind = 'type'
                elif word in lang.builtins:
                    kind = 'builtin'
                elif end < n and line[end] == '(':
                    kind = 'function'
                elif word.upper() in lang.keywords and lang is SQL:
                    kind = 'keyword'
                elif word[:1].isupper() and any(c.islower() for c in word):
                    kind = 'type'
                else:
                    kind = 'text'
                if kind != 'text':
                    spans.append((i, end, kind))
                i = end
                continue
            if ch in PUNCT:
                spans.append((i, i + 1, 'punct'))
            elif ch in OPCHARS:
                j = i
                while j < n and line[j] in OPCHARS:
                    j += 1
                spans.append((i, j, 'operator'))
                i = j
                continue
            i += 1
        return spans, ST_NORMAL

    @staticmethod
    def _find_close(line, start, close, esc):
        i = start
        n = len(line)
        while i < n:
            if esc and line[i] == esc and esc != close:
                i += 2
                continue
            if line.startswith(close, i):
                if esc and esc == close and line.startswith(close * 2, i):
                    i += 2 * len(close)  # doubled quote escape (SQL)
                    continue
                return i + len(close)
            i += 1
        return -1


class LineStates(object):
    """Caches the highlighter state at the start of each line of a buffer."""

    def __init__(self, highlighter):
        self.hl = highlighter
        self.states = [ST_NORMAL]

    def invalidate_from(self, line_no):
        del self.states[max(1, line_no + 1):]

    def state_for(self, lines, line_no):
        while len(self.states) <= line_no:
            i = len(self.states) - 1
            if i >= len(lines):
                self.states.append(ST_NORMAL)
                continue
            _, st = self.hl.tokens(lines[i], self.states[i])
            self.states.append(st)
        return self.states[line_no]
