# Changelog

Versions are tagged in git as `v0.1.0` and so on, and the installer takes one:

```sh
curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh -s -- 0.1.0
```

## 0.1.1 — unreleased

- Install a particular version: pass it to the installer, or set
  `TIDE_VERSION`. A branch or a commit works too; nothing at all still gets
  you the newest code.
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
