"""Long lines: scrolled sideways, or wrapped onto the next row.

A wrapped line is broken at the last space that fits, so words stay whole, and
the editor leaves a blank row after one so you can see where the real newline
is. Nothing here knows about the editor: it works on one line at a time, given
where each character sits once tabs are expanded.
"""

import os

# files that are prose rather than code, where a long line is a paragraph and
# wrapping it is what you want. Something with no extension - README, LICENSE,
# a shell script without one - is treated the same way.
TEXT_EXT = frozenset((
    '.txt', '.text', '.log', '.md', '.markdown', '.mdown', '.rst', '.org',
    '.adoc', '.asciidoc', '.tex', '.me', '.man', '.nfo', '.csv', '.tsv',
    '.srt', '.vtt', '.diff', '.patch', '.note', '.notes',
))

MODES = ('smart', 'on', 'off')


def is_text_like(path):
    """Whether a long line in this file is prose rather than code."""
    if not path:
        return True                     # an untitled buffer is a scratch pad
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if not ext or name.startswith('.') and '.' not in name[1:]:
        return True                     # README, LICENSE, Makefile, .profile
    return ext in TEXT_EXT


def wraps(mode, path):
    """Whether this file's long lines should be wrapped."""
    if mode == 'on':
        return True
    if mode == 'off':
        return False
    return is_text_like(path)


def segments(line, width, xs):
    """Break one line into [(start, end)] column ranges, none wider than width.

    `xs[i]` is where character i starts once tabs are expanded, so the break
    is by what is on screen rather than by how many characters there are.
    """
    if width < 2 or not line:
        return [(0, len(line))]
    segs = []
    start = 0
    space = -1                          # last place a break would keep words
    i = 0
    while i < len(line):
        if xs[i + 1] - xs[start] > width:
            brk = space + 1 if space >= start else i
            if brk <= start:
                brk = start + 1         # one character wider than the pane
            segs.append((start, brk))
            start = brk
            space = -1
            i = brk
            continue
        if line[i] in ' \t':
            space = i
        i += 1
    segs.append((start, len(line)))
    return segs
