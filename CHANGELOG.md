# Changelog

Versions are tagged in git as `v0.1.0` and so on, and the installer takes one:

```sh
curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh -s -- 0.1.0
```

## 0.1.17 — unreleased

- In the classic appearance a highlighted row in the explorer ran through the
  vertical line at its edge, since the row was being filled across the column
  the line is drawn in. The row now stops one column short, and the line keeps
  the panel behind it.

## 0.1.16 — 2026-08-28

- The shells sit a column in from the edge of their pane, both the docked one
  and the full-size ones: a prompt hard against the border read as a mistake.
- `ctrl+l`, or the **↻** button beside the settings, paints the whole screen
  again - for when something has written over the terminal and left
  characters stranded. It changes nothing: no window opens or closes, it only
  stops trusting what it thinks is on screen. A focused shell still gets
  `ctrl+l` for itself.

## 0.1.15 — 2026-08-28

- Two more modern palettes: **parchment**, dark but warm, in beige and ochre,
  and **octopus**, deep purple on black with light grey to read by.
- Forest is less relentlessly green: the scrollbar, the tab names and the
  status text are grey again, and green is left to mean something - the
  accent, and what git has to say.
- `f12` shows and hides the explorer, as `ctrl+b` already did.
- An ignored file's name is readable on the tab it is open in: the grey the
  modern palettes greyed it with was too close to the tab's own background.
- A folder in the explorer now shows a letter as well as a colour: `U` when
  everything inside it is new, `M` once anything in it has been modified.

## 0.1.14 — 2026-08-28

- In the review, a file that was added or deleted is shown whole and full
  width, rather than side by side with an empty half: a green or red bar down
  its edge, the line numbers, and the same syntax colours the editor gives it.
  Modified files keep both sides. Read only, as the rest of the review is.

## 0.1.13 — 2026-08-28

- A sentence in the pipe advice ended better one clause earlier.

## 0.1.12 — 2026-08-28

- `tide --show-audio-pipe` says whether the pipe is up or down, and when it is
  down says what to check and how to set it up again. A tab that cannot reach
  the sink says the same thing rather than only the error.
- Turning audio off and on again asks from the beginning, so setting the pipe
  up again is two keystrokes in the settings.

## 0.1.11 — 2026-08-28

- `tide --show-audio-pipe` prints how to connect the audio pipe to this
  machine - the sink command, both ssh forms and the ssh config block - and
  says whether a sink is answering right now. With audio off, or with no pipe
  set up, it says that instead.

## 0.1.10 — 2026-08-28

- The panes remember their proportions: drag the explorer's edge or the
  terminal's bar and that is where they are the next time tide opens.
- The ssh setup panel also shows the plain `ssh -R … host` form, for when the
  host is already named in your ssh config and `you@host` is not what you
  type.

## 0.1.9 — 2026-08-28

- **Two sound tabs no longer wedge the screen.** The sink served one
  conversation at a time, so a second tab asking to play waited behind the
  first and the far side sat waiting for a reply that never came. Connections
  are now served from one select loop, several tabs can be connected at once,
  and starting one stops whatever else was playing - on either machine, one
  sound at a time. Every wait on the far side is bounded as well, so a stalled
  tunnel shows an error in the tab instead of holding up the editor.

## 0.1.8 — 2026-08-28

- **Sound from an ssh session, out of the machine you are sitting at.**
  Turning audio on now asks where the sound should come out. *This machine*
  behaves exactly as before, unchanged. *The machine I am sitting at* shows
  what to run there - `tide --audio-sink` - and the ssh line that carries a
  port back, and takes the port you paste in. It is remembered, so every
  session afterwards just plays, for as long as the sink is running.
  The file crosses once, when you first press play; seeking, pausing and
  speed are short messages after that, and the progress bar is worked out
  locally so a slow link never holds up the screen. The sink plays through
  whatever that machine has, so it works from a mac or from linux.

## 0.1.7 — 2026-08-28

- **Fixed updates being stuck.** A version tag that had been repointed on the
  remote made `git fetch --tags` refuse the whole fetch - "would clobber
  existing tag" - so `tide --update` and re-running the installer both stopped
  without moving, and without saying why. Both now fetch with `--force`, and
  the installer says so out loud instead of ending quietly.

## 0.1.6 — 2026-08-28

- A sound file deleted while its tab is open no longer trips anything up: the
  tab warns, its name picks up a red `!` beside it, and it keeps playing from
  a copy taken while the file was still there - so you can pause, seek and
  replay until you close the tab, and then it is gone. If the file comes back,
  the warning clears and the new one is measured.
- Fixed a crash on Linux when the disk watcher reached a sound tab: it asked
  the tab for things only a text document has. Sound tabs now watch their own
  file and are left out of that loop.
- More ways to make a noise: ffmpeg piped into `aplay`, `pw-cat` or `afplay`,
  for machines that have ffmpeg but no player of their own. Pausing signals
  the process group, so a pipeline stops and starts as one.
- The tab says when you are over ssh, because then the sound comes out of the
  machine tide is running on.
- **Fixed audio failing silently.** A player that cannot open a sound device
  often exits with a success status - ffplay on a machine with no sound card
  does exactly that - so the bar ran to the end and nothing said why. Any
  player that stops well before the end is now a failure whatever its status,
  and the tab shows what it said. When that message is a machine with nowhere
  to send sound, the tab says so, and over ssh it shows the command to hear
  the file on the machine you are sitting at.
- **Fixed audio on Linux**: with ffmpeg but no ffplay, tide piped a wav into
  `aplay`, and a wav on a pipe carries no length - the sink read it as an
  empty file and exited happily, so the bar jumped to the end and nothing
  played. The pipe now carries raw samples at a fixed rate, the two programs
  run as two children rather than through a shell so a failure can be
  attributed, and a player that stops well before the end is treated as a
  failure whatever its exit status - with whatever it said on the way out
  shown in the tab.
- **`tide --update` works on a copy installed before the repository moved.**
  It was fetching from a place that no longer exists and reporting that as a
  missing version. It now says what git said, points the checkout at the right
  place and tries once more, and lists the versions that do exist when the one
  you asked for is not among them. `TIDE_REPO` names a fork or mirror to
  follow instead.
- `tide --audio-check [FILE]` prints what is installed, which player was
  chosen, the exact command, and what happened when it ran.
- `ctrl+t` goes back to the tab you were on before, files among files and
  shells among shells; `f2` still crosses between them. The settings panel is
  `f9`, `alt+,` or the button, as it always was.
- Folders in the explorer are bold rather than blue, unless git has something
  to say about what is inside them.
- **Audio playback now starts off**, since it needs a player no operating
  system ships. Turning it on checks the machine once: with ffmpeg or mpv it
  turns on; with only a plain player it asks whether to use that (no seeking,
  no speed) or wait until you have installed one; with nothing it says what to
  install and stays off. It never moves on its own.
- In the modern appearance the open tab has a background of its own again, so
  you can see which file or shell you are looking at.

## 0.1.4 — 2026-08-28

- **Audio playback.** Sound files open in their own tab with a play button, a
  bar you can click or drag to seek, and speeds of 0.5, 1, 1.25, 1.5 and 2×.
  It drives whatever player the machine has — ffplay, mpv, afplay, sox, cvlc,
  paplay, aplay — pausing with a signal and seeking by restarting, and it
  trims a temporary copy for players that cannot seek by themselves. All of it
  lives in `tide/audio/`, is imported the first time it is needed, repaints
  only while something is playing, and can be turned off completely with the
  **Audio playback** setting.
- The tabs in the modern appearance have a blank row under them and sit a
  column in from the border, so they read as labels rather than as the first
  line of the file.

## 0.1.3 — 2026-08-28

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
