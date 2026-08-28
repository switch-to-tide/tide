"""How panes are framed.

Two appearances, one layout. `classic` draws the panes flush against each
other, the way it always has. `modern` gives each pane a thin rounded box with
a little air around it. Nothing else differs: the same rectangles, the same
dragging, the same panes painting the same contents inside them - this module
only decides where the frame goes and how much room it takes.
"""

from . import theme
from .term import Rect

TOP_LEFT, TOP_RIGHT = '╭', '╮'
BOTTOM_LEFT, BOTTOM_RIGHT = '╰', '╯'
ACROSS, DOWN = '─', '│'


def boxed():
    return theme.BOXED


def inner(rect):
    """The room left inside a box, once its border has taken a cell."""
    if rect is None or not theme.BOXED:
        return rect
    return Rect(rect.x + 1, rect.y + 1, max(1, rect.w - 2), max(1, rect.h - 2))


def frame(screen, rect, focused=False):
    """Draw one box. Returns the rect its contents should paint into."""
    if rect is None or not theme.BOXED or rect.w < 3 or rect.h < 3:
        return inner(rect)
    fg = theme.BORDER_HL if focused else theme.BORDER
    x2, y2 = rect.x2 - 1, rect.y2 - 1
    screen.put(rect.x, rect.y, TOP_LEFT + ACROSS * (rect.w - 2) + TOP_RIGHT,
               fg=fg, bg=theme.BG, max_x=rect.x2)
    screen.put(rect.x, y2, BOTTOM_LEFT + ACROSS * (rect.w - 2) + BOTTOM_RIGHT,
               fg=fg, bg=theme.BG, max_x=rect.x2)
    for y in range(rect.y + 1, y2):
        screen.put(rect.x, y, DOWN, fg=fg, bg=theme.BG)
        screen.put(x2, y, DOWN, fg=fg, bg=theme.BG)
    return inner(rect)


def arrange(rects):
    """Turn the flush layout into floating boxes.

    The panes keep their places and proportions; each simply gives up a cell
    to its border and another to the gap, and the tab strip moves inside the
    box it belongs to. Every box is left under `<name>_box` for the painting
    and for hit testing the edges you drag.
    """
    if not theme.BOXED:
        return rects
    out = dict(rects)
    editor, tabs = rects['editor'], rects['tabs']
    side = rects.get('sidebar')
    if side is not None and side.w > 5:
        # a margin on the outside, a gap on the inside, and a top that lines
        # up with the panes across the way
        box = Rect(side.x + 1, tabs.y, side.w - 2, side.h - tabs.y)
        out['sidebar_box'] = box
        out['sidebar'] = inner(box)
    terminal, split = rects.get('terminal'), rects.get('split')
    top = tabs.y                       # the tabs live inside the pane's box
    # the boxes above and below meet on adjacent rows: a blank row between
    # them looks like twice the gap a blank column does, cells being taller
    # than they are wide
    bottom = terminal.y if terminal else editor.y2
    height = max(3, bottom - top)
    if split is None:
        box = Rect(editor.x, top, max(3, editor.w - 1), height)
        out['editor_box'] = box
        out['tabs'], out['editor'] = _split_tabs(inner(box))
        out['divider'] = None
    else:
        left = Rect(editor.x, top, max(3, editor.w), height)
        right = Rect(split.x, top, max(3, split.w - 1), height)
        out['editor_box'], out['split_box'] = left, right
        left_tabs, out['editor'] = _split_tabs(inner(left))
        right_tabs, out['split'] = _split_tabs(inner(right))
        out['tabs'] = Rect(left_tabs.x, left_tabs.y,
                           right_tabs.x2 - left_tabs.x, 1)
        out['divider'] = right.x - 1
    if terminal is not None:
        box = Rect(terminal.x, terminal.y, max(3, terminal.w - 1), terminal.h)
        out['terminal_box'] = box
        out['terminal'] = inner(box)
    return out


def _split_tabs(area):
    """The first row inside a box is its tab strip; the rest is the pane.

    A blank row between them, and a column of inset, so the tabs read as
    labels on the box rather than as the first line of the text.
    """
    if area.h < 4:
        return (Rect(area.x, area.y, area.w, 1),
                Rect(area.x, area.y + 1, area.w, max(1, area.h - 1)))
    return (Rect(area.x + 1, area.y, max(1, area.w - 1), 1),
            Rect(area.x, area.y + 2, area.w, area.h - 2))


def grab_column(rects):
    """The column that resizes the side panel when you drag it."""
    box = rects.get('sidebar_box')
    if box is not None:
        return box.x2 - 1
    side = rects.get('sidebar')
    return None if side is None else side.x2 - 1


def grab_row(rects):
    """The row that resizes the bottom panel when you drag it."""
    box = rects.get('terminal_box')
    if box is not None:
        return box.y
    terminal = rects.get('terminal')
    return None if terminal is None else terminal.y
