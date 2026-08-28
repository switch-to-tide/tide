# Changelog

Versions are tagged in git as `v0.1.0` and so on, and the installer takes one:

```sh
curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh -s -- 0.1.0
```

## 0.1.3 — unreleased

- **Appearance**, a new global setting with two values. `classic` is what
  there has always been, untouched. `modern` draws every pane as a floating
  box — a thin rounded border, a little space between them, the tabs inside
  the pane they belong to — and brings its own four palettes: dark, **alien**
  (very dark, bright accents) and **forest** (very dark, green and slate),
  and light. The layout, the dividers you drag, split view and the review all
  work exactly as before; the appearance is a thin frame around them, not a
  second implementation.
- Every button in the top right is drawn the same way now, with the same gap
  between them, instead of settings and review running together.

## 0.1.2 — 2026-08-28

- **Git review** (`f10`, or the button in the top right): every change in the
  working tree on one page — the changed files in their folders down the left,
  and one long side-by-side diff scrolling from the first to the last with a
  rule between them. Each file has a heading with a triangle you can click to
  fold it away; added and deleted files start folded, and the settings say
  which kinds start open. Read only, and it leaves everything behind it
  exactly as it was: tabs, split view, and running shells all come back when
  you press escape. Files that were only moved are left out.

## 0.1.1 — 2026-08-28

- Install a particular version: pass it to the installer, or set
  `TIDE_VERSION`. A branch or a commit works too; nothing at all still gets
  you the newest code.
- `tide --update` pulls the newest code into the copy you already have, and
  takes a version if you want a different one. A session that is already
  running keeps the version it started with, so updating from a terminal
  inside tide cannot pull the floor out from under it.
- Drag the divider between the explorer and the editor to resize it, the
  same way the bar above the bottom terminal already worked.
- The explorer scrolls no further than its last entry, and shows a scrollbar
  down its edge while you scroll.
- Folders open and close with a triangle rather than `+` and `-`, and what is
  inside an open one is marked with a faint line down the indent.
- Files scroll sideways no further than their widest line, with a scrollbar
  along the bottom of the pane while you do it.
- Terminal tabs are named after what they are running — `python3`, `uv run`,
  `claude` — instead of `terminal 1`, `terminal 2`.
- File tabs show the git status the explorer shows: the same letter, the same
  colour, and the same grey for ignored files.
- Two open files with the same name now show enough of their folders to tell
  them apart, the way VS Code does it.
- Names too long for a tab or for the explorer are cropped with `…` rather
  than cut off flat, keeping the filename rather than the path.
- `tide --version` now says `tide`, not `terminal_ide`.

## 0.1.0 — 2026-08-28

The first released version.

- Editor with mouse selection, undo/redo, find and replace, syntax
  highlighting for twenty-odd languages, and a draggable scrollbar.
- Atomic auto-save that keeps permissions, follows symlinks, refuses to
  overwrite a file that changed underneath you, and never writes anything
  beside your files.
- File explorer, editor tabs, fuzzy quick-open.
- Real shells on ptys: one docked panel, any number of full-size sessions,
  and a split view pairing an editor with a terminal.
- Git decorations — status letters in the explorer, change bars in the
  gutter, ticks down the scrollbar, greyed-out ignored files — plus
  side-by-side diffs against a commit or the upstream branch.
- Four themes and global settings in `~/.config/tide/settings.json`.
