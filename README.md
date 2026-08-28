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

**To update**, from anywhere:

```sh
tide --update            # the newest code
tide --update 0.1.0      # or a particular version, back or forward
```

Re-running the curl command does the same thing. A tide that is already open
keeps the version it started with — open a new one to use what you just
pulled. To remove it:

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
python3 main.py --update              # pull the newest code and exit
python3 main.py --appearance modern   # floating boxes for this session
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
- Sideways, a file scrolls only as far as its widest line, with a matching bar
  along the bottom of the pane while you scroll and gone a moment later.
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
- Tabs carry the same git decoration as the explorer: `M` in orange for a
  modified file, `U` in green for a new one, greyed out when git is told to
  ignore it. The unsaved `*` keeps its own slot beside it.
- Tabs with an unsaved marker and an `x` close button, fuzzy quick-open. Two
  open files with the same name pick up as much of their folders as it takes
  to tell them apart (`alpha/models/schema.py`), and a name too long for a tab
  is cropped with `…` — the end for a plain name, the front for a path, so the
  filename is always the part you keep. The explorer crops the same way. When
  there are more tabs than fit, the strip crops with `<` and `>` at the edges;
  the wheel over it scrolls through them, and switching tabs brings the new one
  into view. Editor tabs and terminal tabs scroll independently.
- Indent style (tabs vs spaces, width) is detected per file.

**Audio**
- **Off until you turn it on**, because it needs a player that is not part of
  any operating system. Switch **Audio playback** on in the settings and one
  of three things happens: with `ffmpeg` or `mpv` installed it simply turns
  on; with only a plain player here (`afplay`, `aplay`, `paplay`) it asks
  whether to use that instead, which plays but cannot seek or change speed —
  say no and it stays off until you have installed one; with nothing at all it
  says what to install and stays off. It never turns itself on or off.
- A `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg` or `.aiff` file opens in a tab of
  its own — no question first, no binary dump — with a play button, a bar you
  can click or drag to go anywhere in the file, and a speed button cycling
  0.5, 1, 1.25, 1.5 and 2×. `space` plays and pauses, `←`/`→` move five
  seconds, `s` changes speed. Nothing about it can be edited.
- It plays through whatever the machine already has, best first: `ffplay`,
  `mpv`, `sox`, then **ffmpeg piped into whatever can make a noise** (`aplay`,
  `pw-cat`, `afplay`) for servers that have ffmpeg but no player of their own,
  then `cvlc`, `afplay` (on every Mac), and finally the plain
  `paplay`/`pw-play`/`aplay`. Pausing signals the whole process group, so a
  pipeline stops as one; seeking restarts it at the new offset. Where the
  player cannot seek — `afplay` cannot — a trimmed temporary copy stands in
  for the formats the standard library can rewrite, so a `.wav` seeks on a
  bare Mac.
- **If the file is deleted while it is open**, the tab says so, gets a red `!`
  beside its name in the tab strip, and goes on playing: an open handle keeps
  the bytes alive, and a copy is taken so you can still pause, seek and play
  it again. Closing the tab throws that copy away, and it is gone for good.
  `ctrl+s` on a sound tab does nothing at all. If the file comes back, the
  warning clears and the new one is measured.
- Over ssh the sound comes out of the machine tide is running on — the tab
  says so. A terminal cannot do what VS Code does here, which is ship the
  bytes to the local Electron window and decode them there.
- It costs nothing when you are not using it: the module is imported the first
  time an audio file is opened, the screen only repaints while something is
  actually playing, and with the setting off a sound file is just another
  binary and no line of this code runs.

**Settings**
- `f9`, `ctrl+t`, `alt+,`, or a click on **settings** in the top right — any of
  them open the settings panel: theme, auto-save and its delay,
  the size and line limits that trigger the "open anyway?" question, whether
  the terminal panel and explorer start visible, the default indent width, and
  which kinds of file start open in the review.
  Arrow keys or a click change a value; it applies immediately.
- Preferences are global and live in `~/.config/tide/settings.json`, so a theme
  you pick in one repository is there in every other one. Command line flags
  (`--theme`, `--max-lines`, …) override them for one session without changing
  the file.
- Two **appearances**, each with four palettes:
  - **classic** — the panes flush against each other, as they have always
    been: **dark** (the default), **midnight** (darker, cooler), **ember**
    (warm), **light**.
  - **modern** — the same layout with every pane drawn as a floating box:
    a thin rounded border, a little air between them, and the tabs inside the
    pane they belong to. Its palettes are **dark**, **alien** (very dark, with
    the accents turned up), **forest** (very dark, green and slate) and
    **light**.
  Everything else is identical between the two: the same panes in the same
  proportions, the same dividers to drag, split view, the review, all of it.
  `--appearance modern` tries one for a session, and naming a palette that
  only one appearance has brings that appearance with it (`--theme forest`).

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
- **Review** (`f10`, or the button in the top right) puts every change in the
  working tree on one page, the way a commit reads on a forge: the files that
  changed down the left in their folders, and one long side-by-side diff you
  scroll from the first to the last, a rule between them. Each file has a
  heading with a triangle — click it to fold that file away. Added and deleted
  files start folded, and which kinds start open is in the settings.
  It is read only, it takes over the screen without touching what is behind it
  (your tabs, your split, your running shells all come back), the shell docked
  at the bottom stays live while you read, and `esc` or the `x` leaves.
  A file that was only moved, with nothing edited, is left out.
- That is the whole of it, deliberately. Branches, staging, commits and pushing
  are things you already do in a shell — and there is one right there.

**Built-in terminals**
- Real shells on ptys, not command runners: prompts, colours, job control,
  `ctrl+c`, and full-screen programs (`less`, `vi`, `top`, a Python REPL) all
  work, because each panel is a VT100/xterm emulator.
- A small panel docked at the bottom (`ctrl+j`), always the same session —
  drag its `TERMINAL` bar to resize it.
- Each terminal tab is named after whatever it is running — `sh`, `python3`,
  `uv run`, `claude`, `git log` — and goes back to the shell's name when the
  command finishes. The name comes from the pty's foreground process group, so
  it costs one `ps` per command, not one per frame.
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
- Both dividers drag: the line down the right of the explorer resizes it, and
  the `TERMINAL` bar resizes the bottom panel. Neither pane can be dragged
  away entirely.
- The explorer has its own scrollbar, which appears down that divider while
  you scroll and fades once you stop; it stops at the last entry rather than
  scrolling into empty space. Folders open and close with `▸` / `▾`, and
  everything inside an open folder carries a faint line down the indent.

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
| `f10`, or **review** | the whole working tree, as one review page (`esc` leaves) |
| `alt+left` `alt+right` | previous / next tab |
| `ctrl+b` / `ctrl+j` | toggle explorer / bottom terminal panel |
| `f2`, or the `Editor` / `Terminals` switch | switch the main area: editor <-> full-size terminal |
| `f4` | new full-size terminal session |
| `f6` | cycle focus between panes |
| drag the explorer edge / the `TERMINAL` bar | resize the side / bottom panel |
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
python3 tests/run_all.py       # 678 tests, ~5 min
python3 tests/test_units.py    # editing core, instant
python3 tests/test_saving.py   # what lands on disk, instant
python3 tests/test_durability.py   # quick exits, signals, lost terminals
python3 tests/test_watch.py    # picking up outside changes from disk
python3 tests/test_history.py  # undo/redo model, grouping, lifetime
python3 tests/test_parity.py   # the VS Code behaviours above
python3 tests/test_sync.py     # vim / assistants / git writing the same file
python3 tests/test_workflows.py    # whole sessions, and a no-silent-loss property
python3 tests/test_filesystem.py   # odd content, odd names, odd file types, failed writes
python3 tests/test_panes.py    # dividers, tree scrolling, the sideways bar
python3 tests/test_names.py    # what tabs are called, and cropping
python3 tests/test_review.py   # the git review page
python3 tests/test_appearance.py   # classic panes and modern boxes
python3 tests/test_audio.py    # the player, the tab, and the setting
python3 tests/test_update.py   # tide --update, including from inside tide
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

- No LSP, no word wrap, no multi-cursor
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
