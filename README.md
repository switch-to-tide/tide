## Install

Run this in any terminal, on any machine with `python3` (3.7+) and `git`:

```sh
curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh
```

It clones the repo to `~/.local/share/tide` and links the launcher at
`~/.local/bin/tide`. Nothing else is installed — no dependencies, no config.

**Add it to your PATH** (only if the installer says `~/.local/bin` is not on it):

```sh
# zsh - the default on macOS
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

**Then use it from any directory:**

```sh
tide                # open the directory you are in
tide file.py        # open a file
tide src/ a.py      # a project root plus some files
```

**A particular version** (releases are tagged `v0.1.0`, `v0.1.1`, …):

```sh
curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh -s -- 0.1.0
```

`TIDE_VERSION=0.1.0` does the same thing, and a branch or a commit works
where a version does. Running the installer again moves the checkout to
whatever you ask for that time, so it downgrades as easily as it updates.
`git ls-remote --tags https://github.com/switch-to-tide/tide.git` lists what
there is; `tide --version` says what you have.

To update to the newest code, run the same curl command again. To remove it:

```sh
rm -rf ~/.local/share/tide ~/.local/bin/tide
```

With pip, a version pins the same way:

```sh
pip install "git+https://github.com/switch-to-tide/tide.git@v0.1.0"
```

## Run it from a clone

```sh
python3 main.py                 # open the current directory
python3 main.py file.py         # open a file
python3 main.py src/ a.py b.py  # a project root plus some files
./bin/tide file.py              # same thing, from anywhere
python3 -m tide                 # or as a module

python3 main.py --no-terminal   # start with the terminal panel hidden
python3 main.py --no-tree       # start with the explorer hidden
python3 main.py --no-autosave   # save only when you press ctrl+s
python3 main.py --autosave-delay 3    # wait 3s of quiet instead of 0.8
python3 main.py --max-lines 2000      # ask before opening anything longer
python3 main.py --max-mb 0.5          # ask before opening anything bigger
```

Requires Python 3.7+ and a terminal that speaks xterm mouse reporting
(Terminal.app, iTerm2, Ghostty, kitty, WezTerm, VS Code's terminal, tmux).

## What it does

**Editing**
- Syntax highlighting for Python, JS/TS, Rust, C/C++, Go, Java/Kotlin/C#/Swift,
  shell, SQL, CSS, JSON, TOML, YAML, Markdown, HTML/XML, INI and diffs —
  multi-line strings and block comments survive scrolling.
- Click to place the cursor, drag to select, double-click a word, triple-click
  a line, shift-click to extend, wheel to scroll. Select a chunk and one
  keystroke deletes it.
- A scrollbar down the right edge of the editor, and only the editor: the thumb
  shrinks as the file grows, shows where you are from top to bottom, drags like
  any other scrollbar, and clicking the track jumps there. It disappears when
  the whole file already fits.
- Undo/redo with sensible grouping (a typing run undoes as one edit).
- Auto-indent, indent/dedent a selection, comment toggle, duplicate, move lines,
  delete lines, word-wise motion and deletion.
- Find with live match highlighting, find-next, replace-all, go-to-line.
- **Auto-save**: edits are written 0.8s after you stop typing, so the file on
  disk matches what you see. `alt+a` toggles it, `ctrl+s` still saves on
  demand, and untitled buffers wait for a real path. Saves are atomic (temp
  file, fsync, rename), keep the file's permissions, and write through a
  symlink rather than replacing it.
- **Live reload**: open files are checked a few times a second, so anything a
  terminal writes — a formatter, `git checkout`, a code assistant — shows up in
  the tab. Unsaved edits are never thrown away silently: you get asked. New
  files appear in the explorer and in quick-open on their own.
- **Guard rails on opening**: a file over 2 MB or 20,000 lines, or one that
  looks binary, asks before it opens; anything that is not valid UTF-8 opens
  read-only so it cannot be corrupted by a save.
- Tabs with an unsaved marker and an `x` close button, fuzzy quick-open. When
  there are more tabs than fit, the strip crops with `<` and `>` at the edges;
  the wheel over it scrolls through them, and switching tabs brings the new one
  into view. Editor tabs and terminal tabs scroll independently.
- Indent style (tabs vs spaces, width) is detected per file.

**Settings**
- `f9`, `ctrl+t`, `alt+,`, or a click on **settings** in the top right — any of
  them open the settings panel: theme, auto-save and its delay,
  the size and line limits that trigger the "open anyway?" question, whether
  the terminal panel and explorer start visible, and the default indent width.
  Arrow keys or a click change a value; it applies immediately.
- Preferences are global and live in `~/.config/tide/settings.json`, so a theme
  you pick in one repository is there in every other one. Command line flags
  (`--theme`, `--max-lines`, …) override them for one session without changing
  the file.
- Four themes: **dark** (the default), **midnight** (darker, cooler), **ember**
  (warm), and **light**.

> `cmd+,` cannot reach a terminal program: macOS keeps it for the terminal's
> own preferences, and nothing is sent to the app. On a Mac laptop `f9` may
> also need `fn` unless "Use F1, F2, etc. keys as standard function keys" is on
> in System Settings. So there are three fallbacks that always work: `ctrl+t`,
> the clickable **settings** in the top right, and `alt+,` where Option is set
> to act as Meta. In iTerm2 or Ghostty you can also map `cmd+,` to send `\e[20~`.

**Diffs**
- A file with committed changes gets two buttons in the top right: **changes**
  (only the changed parts, with context) and **diff all** (both files in full).
  `f7` and `f8` do the same. Each opens a read-only tab beside your editors,
  the committed version on the left and what you are editing on the right.
- When a file changes underneath you, the "changed on disk" question takes a
  third answer, **d**, which opens the same kind of tab: your unsaved buffer
  against the newer file, so you can see what you would be throwing away
  before answering.
- Diffs are live. Edit the file in its own tab, come back, and the comparison
  has already caught up - likewise when something else rewrites the file, and
  likewise when the repository moves under you (a commit, checkout, or a pull
  you ran in the terminal).
- Press `r` in a git diff to compare against the **upstream branch**
  (`origin/main`) rather than your last commit. tide never talks to the
  network itself; the remote side moves when *you* fetch or pull, which makes
  this a live view of what you are about to merge.
- Staying current is cheap: each side is polled by a token - the buffer's
  version, the file's timestamp, a handful of stats inside `.git` - and
  nothing is read or run unless one of them moved. An open diff that is up to
  date costs no `git` processes at all.
- Inside a diff: `m` switches between the trimmed and whole-file views, `r`
  swaps the committed side, `n` and `p` jump between changes.
- The two halves scroll **vertically as one** - the alignment leaves a blank
  gap on whichever side is missing lines, so the code below a change stays
  level. Scrolling **sideways moves only the half under the pointer**, so a
  long line on one side can be read without disturbing the other. Use the
  sideways wheel or `shift`+wheel, or the arrow keys with `tab` to pick a half;
  the header shows both column offsets.

**Keyboard, and why it is `ctrl` everywhere**
- `ctrl+z`, `ctrl+y`, `ctrl+c`, `ctrl+x`, `ctrl+v` work identically on macOS,
  Linux and Windows. Use `ctrl`, not `cmd`, even on a Mac.
- `cmd` cannot be used: terminals have no way to encode the Command modifier,
  so a `cmd` chord never reaches the program — macOS keeps it for the
  terminal's own menus (`cmd+c`/`cmd+v` copy and paste the *terminal's*
  selection, and `cmd+v` does paste into the editor, because the terminal
  turns it into ordinary pasted text).
- `ctrl+shift+z` is not usable for redo either: terminals send the same byte
  for `ctrl+z` and `ctrl+shift+z`, so redo is `ctrl+y`.
- Auto-save does not touch undo history — you can undo back past any number of
  saves, and the file follows. (A full history of 4000 edits is under 200 KB,
  so nothing is discarded to save memory.)
- If you really want `cmd+z`, map it in your terminal to send the byte
  `ctrl+z` does: iTerm2 → Keys → Key Bindings → `⌘Z` → Send Hex Code `0x1a`
  (and `⌘⇧Z` → `0x19` for redo). Scope it to a profile, or `⌘Z` will suspend
  jobs in an ordinary shell.

**Split view**
- `f5` (or the **Split view** row in the settings) puts one file editor and one
  full-size terminal side by side, instead of switching between them. The tab
  row splits with them: file tabs over the left half, terminal tabs over the
  right, a divider between, each scrolling on its own. The `Editor` /
  `Terminals` switch disappears, since both are already on screen; `f2`, a
  click on a tab, or a click in a half moves the keyboard between them.
- With split view on and no terminal open, the editor keeps the whole pane and
  a small `</>` appears in the top right; click it (or press `f4`) to start a
  shell on the right. Close the last terminal and the editor takes the space
  back, with the button offered again. Nothing appears when split view is off.
- Each layout remembers where every tab was: scroll positions for files, diffs
  and terminal scrollback all come back when you toggle, and tabs keep their
  order and identity.
- The preference is global, so it is there in the next repository you open.

**Git**
- The explorer marks changed files the way VS Code does: `U` in green for new
  files, `M` in orange for modified ones, `D` for deleted, `A` for staged, `!`
  for conflicts. Folders containing changes are tinted too.
- A change bar runs down the left of the editor gutter: **green** for lines
  added since the last commit, **blue** for lines edited, and a small **red**
  mark where lines were removed. The same colours appear as ticks down the
  scrollbar, in proportion to where they fall in the file, so a long file shows
  its edits at a glance - and there are none when the file already fits.
- Files git is told to ignore are greyed in the explorer and carry no status.
- That is the whole of it, deliberately. Branches, staging, commits and pushing
  are things you already do in a shell — and there is one right there.

**Built-in terminals**
- Real shells on ptys, not command runners: prompts, colours, job control,
  `ctrl+c`, and full-screen programs (`less`, `vi`, `top`, a Python REPL) all
  work, because each panel is a VT100/xterm emulator.
- A small panel docked at the bottom (`ctrl+j`), always the same session —
  drag its `TERMINAL` bar to resize it.
- **Full-size sessions** that take over the editor area: `f2` or the
  `Editor` / `Terminals` switch in the top bar flips between them, `f4` or the
  `+` tab starts another, `alt+left` / `alt+right` or a click on a tab moves
  between them. They are separate shells from the docked panel and from each
  other, they keep running while hidden, and the tab's `x` (or `exit`, or a
  middle-click) closes one — closing the last returns you to the editor.
- Scrollback with the wheel that stays where you put it while output keeps
  arriving; typing jumps back to the live end. Drag to select and copy.
- Every window — each editor tab, each full-size session, the docked panel —
  scrolls independently and keeps its position when you switch away and back.

**Panels**
- File explorer, editor tabs, terminal, status bar. Click a pane to focus it,
  or cycle with `f6`; `ctrl+b` / `ctrl+j` show and hide the side and bottom panels.

## Keys

Press `f1` inside the app for this list.

| Key | Action |
|---|---|
| `ctrl+p` / `ctrl+o` | quick open (fuzzy) / open a path |
| `ctrl+n` / `ctrl+w` | new tab / close tab |
| click `x` on a tab | close it (middle-click works too) |
| `ctrl+s` / `alt+s` | save / save as |
| `alt+a` | toggle auto-save (on by default) |
| `f9`, `ctrl+t`, `alt+,`, or click **settings** | settings panel |
| `f5` | split view: file and terminal side by side |
| `f7` / `f8` | diff a modified file: changes only / whole file |
| `alt+left` `alt+right` | previous / next tab |
| `ctrl+b` / `ctrl+j` | toggle explorer / bottom terminal panel |
| `f2`, or the `Editor` / `Terminals` switch | switch the main area: editor <-> full-size terminal |
| `f4` | new full-size terminal session |
| `f6` | cycle focus between panes |
| `ctrl+q` | quit (asks about unsaved files) |
| `f1` | help |
| **editor** | |
| click, drag, double, triple click | cursor, select, word, line |
| `shift+arrows`, `shift+click` | extend the selection |
| `ctrl+left/right` | move by word |
| `ctrl+c` `ctrl+x` `ctrl+v` | copy / cut / paste (system clipboard) |
| `ctrl+z` / `ctrl+y` | undo / redo (same keys on macOS - see below) |
| `ctrl+k` / `ctrl+d` | delete line(s) / duplicate |
| `alt+up` / `alt+down` | move line(s) |
| `tab` / `shift+tab` | indent / dedent the selection |
| `ctrl+/` | toggle comment |
| `ctrl+a` | select all |
| `ctrl+f` / `f3` / `ctrl+r` | find / find next / replace all |
| `ctrl+g` | go to line |
| **terminals** | |
| everything else | goes straight to the shell (`ctrl+c`, `ctrl+d`, …) |
| `alt+left` / `alt+right` | previous / next session (in the full-size view) |
| drag | select, and copy on release |
| wheel | scrollback |
| drag the `TERMINAL` bar | resize the docked panel |
| the tab's `x`, middle-click, or `exit` | close a full-size session |

`f1`, `f2`, `f4`, `f6` and `ctrl+j` are the only keys a focused terminal keeps
for itself; everything else reaches the shell.

## How it is put together

```
main.py            entry point            bin/tide  launcher for a clone
pyproject.toml     packaging (`tide` console script)   install.sh  pip-free install
tide/
  term.py          raw mode, the cell grid, the diffing flush, Rect
  keys.py          escape-sequence decoder -> Key / Mouse / Paste events
  buffer.py        Document: lines, cursor, selection, edits, undo
  highlight.py     tokenizers and regex rules per language
  editor.py        the editor pane: viewport, painting, keys, mouse
  vt.py            VT100/xterm emulator (the terminal panel's screen)
  shell.py         a shell on a pty + key -> bytes translation
  termpanel.py     one shell session in a pane (docked or full-size)
  filetree.py      the explorer      git.py  status letters and change bars
  settings.py      global preferences, stored as JSON
  diff.py          side by side diff tabs (conflict and git)
  overlay.py       prompts, fuzzy picker, confirmations, help
  app.py           layout, focus, tabs, terminal sessions, the event loop
  theme.py         colours          clipboard.py  pbcopy/xclip bridge
```

One frame is: everything paints into a `Screen` of cells, which is diffed
against the last frame so only changed runs are written. Input is one
`select()` over stdin and every live shell's pty, so background sessions keep
running whether or not they are on screen.

## Tests

```sh
python3 tests/run_all.py       # 461 tests, ~3 min
python3 tests/test_units.py    # editing core, instant
python3 tests/test_saving.py   # what lands on disk, instant
python3 tests/test_durability.py   # quick exits, signals, lost terminals
python3 tests/test_watch.py    # picking up outside changes from disk
python3 tests/test_history.py  # undo/redo model, grouping, lifetime
python3 tests/test_parity.py   # the VS Code behaviours above
python3 tests/test_sync.py     # vim / assistants / git writing the same file
python3 tests/test_workflows.py    # whole sessions, and a no-silent-loss property
python3 tests/test_filesystem.py   # odd content, odd names, odd file types, failed writes
```

`tests/harness.py` launches the IDE on its own pty and feeds it real key and
mouse escape sequences, then reads the painted screen back **through the same
VT emulator the terminal panel uses** — so tests assert on actual rendered
characters and colours ("the `def` on screen is colour 75", "dragging here and
pressing backspace removes that chunk", "`echo` output appears in the panel").

Saving gets particular attention, since it is the part that can lose work:

- every file shape (no trailing newline, CRLF, tabs, 20k-character lines,
  unicode, empty) is opened and saved untouched, byte for byte;
- a randomised run applies thousands of edits, deletions, undos and redos and
  compares the buffer to a plain-string model after **every** step, then checks
  the saved bytes;
- the durability suite types into a real IDE and then ends it abruptly — an
  instant `ctrl+q`, SIGHUP, SIGTERM, the terminal being destroyed — and checks
  the file afterwards (including that `kill -9` does lose it, so the guarantee
  is honest).

## How saving compares to VS Code

The file on disk is the thing that matters, so the rules follow VS Code's,
and `tests/test_parity.py` and `tests/test_sync.py` hold them in place.

| Behaviour | VS Code | tide |
|---|---|---|
| Auto-save after a delay | 1000 ms default | 800 ms, configurable |
| Auto-save on untitled buffers | never | never |
| Saving an unchanged file | does nothing | does nothing |
| Dirty marker after undoing back to the saved state | clears | clears |
| Undo history across a save | kept | kept |
| Redo after a new edit | dropped | dropped |
| Content added on save (final newline, trimming) | off by default | never |
| Line endings | the file's own | the file's own |
| External change, clean buffer | reloads | reloads |
| External change, unsaved buffer | asks, keeps yours | asks, keeps yours |
| Saving over a file that changed on disk | refuses, offers compare/overwrite | refuses, asks to overwrite or diff |
| Save As over an existing file | asks | asks |
| One file reached by two paths | opens twice (a known bug) | one buffer, matched by inode |
| Deleted on disk | editor stays, save restores | editor stays, `ctrl+s` restores |

Where the convention comes from somewhere other than VS Code:

| Behaviour | Convention | tide |
|---|---|---|
| Atomic write | VS Code truncates then writes; a temp file plus rename is the safer pattern | temp file, `fsync`, rename |
| `fsync` before replacing | Emacs does it unless you turn it off | always |
| A file with more than one hard link | vim's `backupcopy=auto` writes in place so the links survive | writes in place |
| Runs of typing in one undo step | Emacs starts a new step every 20 characters | every 20 characters, or at a space, newline or cursor move |
| Undo history size | vim keeps 1000 levels | 4000 edits, then the oldest go |

Deliberate differences, each with a test that says so:

- **No hot exit and no backup files.** VS Code writes unsaved buffers to a
  backup directory a second after you stop typing and restores them after a
  crash; vim leaves `.swp` files and Emacs leaves `#file#`. tide keeps history
  in memory only, so quitting drops it and nothing is ever written beside your
  files. Auto-save means there is normally nothing to lose - but a crash
  between your last keystroke and the next write does lose it.
- **A reload clears undo history.** VS Code lets you undo past an external
  change; tide does not, which is simpler and can never resurrect content that
  another tool deliberately replaced.
- **No encoding guessing.** A file that is not valid UTF-8 opens read-only
  rather than being decoded speculatively and rewritten as something else.

## Known limits

- No LSP, no git integration, no word wrap, no multi-cursor, no split editors
  (the main area shows one thing at a time: the editor or a terminal).
- Very long single lines scroll horizontally rather than wrapping.
- Mixed line endings in one file are normalised on save (CRLF wins if the file
  had any); everything else round-trips byte for byte, including a byte order
  mark, carriage-return-only endings, NUL bytes and emoji.
- Pipes, sockets and device nodes are refused rather than opened or written
  over; reading one would hang the editor and writing one would destroy it.
- A save replaces the file through a rename, so a hard link to it is broken
  (the symlink case is handled).
- Change detection uses the file's modification time, change time and size,
  and then compares the bytes. On a filesystem with one second timestamps
  (some network mounts) a second write of the same length inside the same
  second can go unnoticed.
- There is no cross process lock, so two editors on one file resolve by asking
  each writer before it overwrites the other - the same as VS Code, and the
  reason the question exists.
- Nothing survives `kill -9` before auto-save's timer; SIGHUP, SIGTERM, a
  closed window and a crash all flush first.
- Git decorations are computed from the file on disk, not the unsaved buffer,
  so they follow your typing by about a second (the same beat as auto-save).
  `git status` runs at most every 1.5s; on a very large repository that is the
  cost you pay for the letters in the explorer.
- The bundled `nvim-macos-arm64` binary in the parent folder hangs in this
  environment (`nvim --version` never returns, outside this app too), so it is
  unused here; system `vi` runs fine inside the terminal panel.
