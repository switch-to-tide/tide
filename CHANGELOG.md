# Changelog

Versions are tagged in git as `v0.1.0` and so on, and the installer takes one:

```sh
curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh -s -- 0.1.0
```

## 0.1.34 — 2026-08-29

- **Preview tabs.** Clicking a file in the explorer shows it in a tab marked
  `(p)`, and the next click replaces that tab rather than opening another, so
  looking through a folder leaves one tab behind instead of twenty. The tab
  becomes a real one the moment you type in it, or when you press enter on it
  in the explorer - which is the only way to keep a picture, since there is
  nothing to type into. Opening a file any other way - the quick open, the
  File menu, the command line - is never a preview.
- **The divider between the halves of a split view can be dragged**, like the
  explorer's edge and the terminal's bar, and where you leave it is where it
  is next time.

## 0.1.33 — 2026-08-29

- **PNG files open as pictures.** A tab of its own, fitted to the pane, read
  only: `+` and `-` zoom, `f` fits it again, the arrows pan around it when it
  is bigger than the pane, and the wheel zooms. It says what it is along the
  bottom - the size and how it was stored - and a file deleted underneath you
  keeps its picture on screen with a red `!` on the tab, as a sound file does.
- It works the same everywhere, which was the point: every cell is two pixels
  drawn as an upper half block in the colour above and behind, so a picture is
  ordinary coloured text. Nothing is asked of the terminal, so it looks the
  same over ssh, under tmux, in a split pane, at any size. The decoder is
  `zlib` and `struct` and nothing else - grey, palette, colour, 8 and 16 bit,
  transparency laid over a checkerboard. Interlaced files say so rather than
  guessing, and a damaged one shows what is wrong with it instead of failing.

## 0.1.32 — 2026-08-29

- The highlight keeps up with the pointer: a menu catches up every 30
  milliseconds rather than every 80, and tide no longer waits in its select
  loop while a move is sitting there unshown.

## 0.1.31 — 2026-08-29

- **Fixed the mouse dying after a menu was opened and closed.** Closing one
  turned off the pointer reporting it had asked for, and 1000, 1002 and 1003
  are not three switches but one mode: turning the last off turns the mouse
  off altogether. tide went deaf to clicks and the terminal started doing its
  own selection, which is exactly what it looked like. What tide always wants
  - clicks, drags and SGR coordinates - is now asked for again every time the
  hover reporting stops.

## 0.1.30 — 2026-08-29

- Writing a frame can no longer spin or hang. Waiting for room to write now
  waits on the terminal's input alone for twenty milliseconds at a time - a
  full terminal can claim to be ready for more, and believing it meant
  spinning at full tilt - and a frame the terminal will not take within two
  seconds is abandoned rather than waited on, with the next frame drawn from
  scratch.
- `kill -USR1 <pid>` from another terminal writes a traceback to
  `~/.config/tide/stuck.log` saying exactly what tide is doing. If the screen
  ever stops answering, that says whether tide is stuck or the terminal is,
  which is not something that can be told from the outside.

## 0.1.29 — 2026-08-29

- **Hover in the menus costs nothing.** A report of the pointer moving now
  stores a pair of numbers and stops there - no work, no repaint. The open
  menu catches up with where the pointer is a dozen times a second, which is
  what a menu is worth: five thousand reports take a millisecond and a half
  between them, and ask for no repainting of their own.
- **Fixed the freeze for good, whatever caused it.** Frames went out with one
  blocking write. A terminal busy pushing input at us - mouse reports, a held
  key - can stop reading, and then neither side can move: it will not read
  until it has finished writing to us, and it cannot finish until we read.
  tide now writes frames without blocking, and listens to the terminal while
  it waits for room, so the two can never wedge each other again.

## 0.1.28 — 2026-08-29

- **The pointer only ever moves the highlight inside the menu that is open.**
  It never opens another one - a click does that - so a hand crossing the bar
  cannot set one menu going after another.
- Hover repaints at most twenty times a second, and a terminal that reports
  the pointer faster than any hand can move it (400 reports in a second) has
  the hover switched off with a line in the status bar, rather than taking
  the session with it. **Menu follows mouse** in the settings turns it off
  outright.
- `tide --mouse-check` asks this terminal to report the pointer for five
  seconds and says what came back - how many reports a second, in which
  encoding - so a terminal that cannot do it can be told apart from one that
  can, without finding out mid-session.

## 0.1.27 — 2026-08-29

- The highlight follows the pointer in an open menu again, and moving on to
  another name opens that menu. It is asked for as narrowly as it can be -
  only while a menu is down, off the moment it closes, checked every pass
  round the loop, and never reaching the editor, the explorer or a shell. If
  your terminal still dislikes it, **Menu follows mouse** in the settings
  turns it off and everything else stays as it is.
- The panes reach the right hand edge of the screen now: the border, the
  scrollbar, the gap and the change ruler took four columns and a margin, and
  the margin is gone.
- **Open File...** has moved from the Tide menu to the File menu, where it
  belongs, above Go to line... Help lists what each menu holds.

## 0.1.26 — 2026-08-29

- **tide no longer asks the terminal to report the pointer moving.** The
  hover-follows-the-mouse highlight in the menus needed any-motion reporting,
  which sends tide an event for every pixel the pointer crosses - enough to
  wedge the screen. It is gone, and tide now clears that mode when it starts
  as well as when it leaves, so a terminal left in it by an earlier version
  comes back to normal.
- Menus behave without it: **one click moves from one menu to another**,
  clicking the open one closes it, and dragging along the bar or down a menu
  moves the highlight the way a menu should - all from the button-drag
  reporting tide already used.
- A blank column between the scrollbar and the change ruler, so a change is
  still visible where the scrollbar's thumb sits beside it.

## 0.1.25 — 2026-08-29

- **Fixed the editor going sluggish after using a menu.** A menu asks the
  terminal to report the pointer moving, so the highlight can follow it, and
  only clicking its own name again turned that back off - every other way of
  closing one left every mouse movement pouring into tide, and into whatever
  the shell was running. Closing a menu now stops it however it is closed, and
  so does leaving tide.
- The change ruler is a continuous line in its own column, just to the right
  of the scrollbar rather than on top of it: the file squeezed down to the
  height of the pane, so a run of changed lines is one unbroken bar of its own
  height and a brand new file is one line from top to bottom. Thinner than the
  bar in the gutter, and out of the scrollbar's way.
- A menu longer than four fifths of the screen - the File menu with a lot of
  documents open - stops there and scrolls, with a thumb down its edge.

## 0.1.24 — 2026-08-29

- **A File menu**, between Tide and View: every open document, named exactly
  as its tab is - the git letter, italics for a file from outside the project,
  a strikethrough for one deleted on disk, and a tick beside the one you are
  looking at. Choosing one goes to it, which beats hunting along a crowded tab
  strip. **Go to line...** sits above them, greyed out unless the tab in front
  is a document; a number before the first line or past the last takes you to
  the first or the last.
- The menus are all one width now, and while one is open, moving the pointer
  along the bar opens whichever you are over. Clicking the name of the open
  one still closes it, and Help still needs a click, so a sweep across the bar
  cannot land you in the shortcut list.

## 0.1.23 — 2026-08-29

- **Long lines can wrap.** A new setting, *Long lines*: wrap text files (the
  default - prose, logs, markdown and anything without an extension wrap, code
  scrolls sideways as before), wrap all, or scroll all. A wrapped line carries
  on in the next row with no line number of its own, and a blank row after the
  last piece shows where the real newline is, so a wrap never reads as one.
  Clicking, selecting, the cursor and scrolling all follow the rows on screen.
- **Quitting with unsaved work asks properly.** With auto-save off, ctrl+q
  names the files that are not on disk and offers three answers: save all and
  quit, quit without saving, or stay. With auto-save on, everything with a
  name is written before tide leaves.

## 0.1.22 — 2026-08-29

- **Named sessions.** *Tide > Save to named session...* remembers where you
  are working, which documents are open and how the panes are set; the item is
  greyed out once the session has a name, and *Rename session...* takes over.
  From a terminal: `tide --resume NAME` opens that folder with those files
  again, `tide --new-session NAME` names the folder you are in, and
  `tide --list-sessions`, `tide --remove-session NAME` and
  `tide --remove-all-sessions` (both ask first) manage them. Shells are not
  kept - a session is files and panes. A session already open somewhere else
  will not open twice, and says where it is.
- The Help screen (`f1`) now lists the terminal commands as well as the keys,
  and scrolls, since there is more of it than fits.

## 0.1.21 — 2026-08-29

- The menus keep the top left corner to themselves. With the explorer closed
  the row belonged to the editor and terminal tabs, but the menus were still
  listening underneath them, so a click on a tab dropped a menu open. Tide,
  View and Help now sit in the same three places whether the explorer is
  showing or not, and everything else in that row starts after them.

## 0.1.20 — 2026-08-29

- The change markers down the scrollbar are as tall as the change they mark:
  a run of changed lines is one continuous bar of its share of the file,
  rather than a tick wherever a change begins.
- A file deleted on disk while it is open stays readable but is no longer
  yours to change: its name is struck through on the tab, edits are refused,
  and `ctrl+s` will not write it back into existence. Close the tab and it is
  gone.
- The menus follow the pointer: whatever you are over is what is highlighted,
  rather than always the first item.
- **Git review** is ticked in the View menu while you are in it, and choosing
  it again leaves - as `f10` already did.
- Split view never offers the Editor/Terminals switch, not even with no shell
  open: both panes are already on screen, and the `</>` button opens one.

## 0.1.19 — 2026-08-28

- **Menus across the top left**: Tide, View and Help. Tide holds Settings,
  Open File... and Quit; View holds the terminal panel, split view, the
  explorer and the git review, each with a tick beside what is showing; Help
  is the shortcut list. The settings and review buttons have moved off the
  right hand side into them.
- **Open File...** browses the machine: folders first, `..` to go up, enter or
  a click to open. A file opened this way is opened exactly as any other is -
  same guards, same watching, same saving - and one from outside the project
  is named in italics on its tab.
- `ctrl+f` shows the search line straight away, with the cursor in it, rather
  than waiting for the first keystroke. Four other prompts had the same fault.
- In split view the right hand tab strip keeps the same inset as the left, and
  the two strips no longer disagree with the layout about how wide the halves
  are.
- Dragging the docked terminal by its header is exact again, rather than
  landing a row out.

## 0.1.18 — 2026-08-28

- **The classic appearance is deprecated.** The settings panel no longer
  offers a choice: tide is the modern one, with its six palettes. The classic
  code and its four palettes are still there, reachable with
  `--appearance classic` and still under test, but nothing in the settings
  will take you there and a session started from a settings file that says
  classic comes up modern.

## 0.1.17 — 2026-08-28

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
