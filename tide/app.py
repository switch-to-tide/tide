"""The IDE shell: layout, focus, tabs, event loop."""

import os
import select
import signal
import sys
import time

from . import settings as settings_store
from . import theme
from .buffer import Document, StaleFileError
from .editor import Editor
from .diff import DiffView, buffer_source, disk_source, head_source, rev_source
from .filetree import FileTree, IGNORE_DIRS, IGNORE_FILES
from .git import Git
from . import chrome
from . import sessions
from . import menu as menus
from . import names as tabnames
from .keys import ALT, CTRL, SHIFT, Decoder, Key, Mouse, Paste
from .review import Review
from .overlay import Choice, Confirm, Help, Prompt, SettingsPanel
from .term import (BOLD, DIM, ITALIC, STRIKE, Out, RawTerminal, Rect,
                   Screen)
from .termpanel import TerminalPanel

SIDEBAR_W = 26
MIN_SIDEBAR_W = 12           # narrower than this and names are unreadable
MIN_MAIN_W = 30              # what the editor keeps when you drag the divider
MESSAGE_SECONDS = 6          # how long a status message stays on the bar
MIN_TERM_H = 3
DEFAULT_TERM_H = 12
MENU_MAX_W = 46      # menus are all one width; a long name is cropped
HOVER_GAP = 0.08     # how often an open menu catches up with the pointer


class App(object):
    def __init__(self, root='.', paths=(), out=None, in_fd=None):
        self.root = os.path.abspath(root)
        self.settings = settings_store.load()
        # the settings only ever mean the modern appearance; classic lives on
        # behind --appearance, and is not offered in the panel any more
        self.settings['appearance'] = 'modern'
        name = theme.apply(self.settings['theme'], 'modern')
        if name != self.settings['theme']:
            self.settings['theme'] = name      # it was a palette classic had
        self.out = out or sys.stdout
        self._pending = []           # input read while a frame was going out
        self.in_fd = in_fd if in_fd is not None else sys.stdin.fileno()
        try:
            live = self.out.isatty()
        except Exception:
            live = False
        if live:
            # frames go out without ever blocking us into a deadlock with a
            # terminal that is busy talking to us
            self.out = Out(self.out, self.in_fd, self._pending.append)
        self.editors = []
        self.active = 0
        self.git = Git(self.root)
        self.tree = FileTree(self, self.root)
        self.terminal = TerminalPanel(self, cwd=self.root)
        self.big_terms = []          # full-size terminal sessions
        self.big_active = 0
        self.main_view = 'editor'    # in single view, what the main area shows;
                                     # in split view, which half has the focus
        self.split = self.settings.get('split_view', False)
        self._next_tab_id = 0
        self._view_state = {}        # view mode -> {tab id: what it was showing}
        self._term_seq = 0
        self.show_tree = self.settings['show_tree']
        self.show_term = self.settings['show_terminal']
        self.autosave = self.settings['autosave']
        self.autosave_delay = self.settings['autosave_delay']
        self.default_tab_width = self.settings['tab_width']
        self.max_file_bytes = int(self.settings['max_mb'] * 1024 * 1024)
        self.max_file_lines = self.settings['max_lines']
        self.watch_interval = 0.7    # how often open files are checked on disk
        self.tree_interval = 2.0
        self._last_watch = 0.0
        self._last_tree_refresh = 0.0
        self.term_h = DEFAULT_TERM_H
        self.term_h_user_set = False
        self.sidebar_w = max(MIN_SIDEBAR_W,
                             int(self.settings.get('sidebar_width') or SIDEBAR_W))
        kept = int(self.settings.get('terminal_height') or 0)
        if kept >= MIN_TERM_H:
            self.term_h = kept              # the height you last dragged it to
            self.term_h_user_set = True
        self._tree_indicator = False
        self.review = None           # the git review, when it is on screen
        self._review_focus = None    # what had the keyboard before it opened
        self.menu_open = None        # which menu is down, if any
        self._splitter_hold = 0      # where on the divider a drag took hold
        self._main_w = 80            # width the layout last gave the panes
        self.menu_spans = []
        self._menu_end = 0
        self._tracking = False
        self._hover_at = None    # where the pointer was last reported
        self._hover_seen = 0.0
        self._seen_tab = None        # the tab in front of us, and the one
        self._prev_tab = None        # before it, in each of the two groups
        self._seen_term = None
        self._prev_term = None
        self._pgid_names = {}        # foreground process group -> program name
        self._last_title_poll = 0.0
        self._hbar_showing = False
        self.focus = 'editor'
        self.overlay = None
        self.message = ''
        self.message_time = 0
        self.running = True
        self.screen = Screen(80, 24)
        self.decoder = Decoder()
        self.need_render = True
        self.resized = False
        self.mouse_capture = None
        self.tab_spans = []
        self.tab_close_spans = []
        self.toggle_spans = []
        self.settings_span = None
        self.new_term_span = None
        self.diff_spans = []
        self.plus_span = None
        self.tab_scrolls = {'editor': 0, 'terminal': 0}
        self.tab_arrows = []
        self._tab_metrics = {}
        self._shown_tab = {}
        self._file_cache = None
        self.rects = {}
        self.session = None          # the named session this is, if any
        for p in paths:
            self.open_file(p)
        if not self.editors:
            self.new_file()

    # ---------------- tabs ----------------
    def adopt(self, tab):
        """Give a tab a lasting id, so it can be found again after a change."""
        self._next_tab_id += 1
        tab.tab_id = self._next_tab_id
        return tab

    def viewports(self):
        """What each tab is looking at, by tab id: editors, diffs and shells."""
        state = {}
        for tab in list(self.editors) + list(self.big_terms):
            if getattr(tab, 'is_diff', False):
                state[tab.tab_id] = ('diff', tab.top, dict(tab.cols), tab.side)
            elif hasattr(tab, 'doc'):
                state[tab.tab_id] = ('editor', tab.top, tab.left)
            else:
                state[tab.tab_id] = ('terminal', tab.scroll)
        return state

    def restore_viewports(self, state):
        if not state:
            return
        for tab in list(self.editors) + list(self.big_terms):
            saved = state.get(getattr(tab, 'tab_id', None))
            if not saved:
                continue
            if saved[0] == 'diff' and getattr(tab, 'is_diff', False):
                tab.top = saved[1]
                tab.cols.update(saved[2])
                tab.side = saved[3]
            elif saved[0] == 'editor' and hasattr(tab, 'doc'):
                tab.top, tab.left = saved[1], saved[2]
            elif saved[0] == 'terminal' and hasattr(tab, 'scroll'):
                tab.scroll = min(saved[1], len(tab.vt.scrollback))

    # ---------------- documents ----------------
    @property
    def editor(self):
        return self.editors[self.active] if self.editors else None

    def new_file(self):
        ed = self.adopt(Editor(self, Document()))
        self.editors.append(ed)
        self.active = len(self.editors) - 1
        self.focus = 'editor'
        self.need_render = True
        return ed

    def _open_guard(self, path):
        """Why opening this file might be a bad idea, or None if it is fine."""
        if os.path.exists(path) and not os.path.isfile(path):
            return None                   # handled before we get here
        try:
            size = os.path.getsize(path)
        except OSError:
            return None
        name = os.path.basename(path)
        if size > self.max_file_bytes:
            return '%s is %.1f MB' % (name, size / 1048576.0)
        try:
            with open(path, 'rb') as f:
                head = f.read(8192)
                rest = f.read()
        except OSError:
            return None
        if b'\x00' in head:
            return '%s looks like a binary file' % name
        lines = (head + rest).count(b'\n') + 1
        if lines > self.max_file_lines:
            return '%s has %d lines' % (name, lines)
        return None

    def open_file(self, path, force=False):
        path = os.path.abspath(path)
        if os.path.isdir(path):
            self.status('%s is a directory' % path)
            return None
        if os.path.exists(path) and not os.path.isfile(path):
            # pipes, sockets and device nodes: reading one would hang us
            self.status('%s is not a regular file' % os.path.basename(path))
            return None
        if self.settings.get('audio'):
            from . import audio                 # a set literal, nothing more
            if audio.is_audio(path):
                return self.open_audio(path)
        if not force:
            reason = self._open_guard(path)
            if reason:
                self.overlay = Confirm(
                    '%s. Open anyway (it may be slow)?' % reason,
                    lambda: self.open_file(path, force=True),
                    on_no=lambda: self.status('Did not open %s'
                                              % os.path.basename(path)))
                self.need_render = True
                return None
        real = os.path.realpath(path)
        try:
            st = os.stat(path)
            key = (st.st_dev, st.st_ino)
        except OSError:
            key = None
        for i, ed in enumerate(self.editors):
            # the filesystem decides what counts as the same file, so a link or
            # a differently cased path cannot open a second buffer for it
            same = ed.path and os.path.realpath(ed.path) == real
            if not same and key is not None and hasattr(ed.doc, 'file_key'):
                same = ed.doc.file_key() == key
            if same:
                self.active = i
                self.focus = 'editor'
                self.main_view = 'editor'      # the file half, not the shell
                self.recheck_disk_soon()
                self.need_render = True
                return ed
        try:
            doc = Document(path)
        except Exception as exc:
            self.status('Cannot open %s: %s' % (os.path.basename(path), exc))
            return None
        ed = self.adopt(Editor(self, doc))
        # replace a pristine untitled tab
        cur = self.editor
        if (cur and cur.path is None and not cur.doc.dirty
                and cur.doc.text() == '' and len(self.editors) == 1):
            self.editors[0] = ed
            self.active = 0
        else:
            self.editors.append(ed)
            self.active = len(self.editors) - 1
        self.focus = 'editor'
        self.main_view = 'editor'
        self.need_render = True
        if doc.readonly:
            self.status('%s is not valid UTF-8 - opened read-only' % self.rel(path))
        else:
            self.status('Opened %s' % self.rel(path))
        return ed

    def open_audio(self, path):
        """An audio file gets a tab of its own, with a play button in it."""
        from . import audio
        real = os.path.realpath(path)
        for i, tab in enumerate(self.editors):
            if getattr(tab, 'is_audio', False) and \
                    os.path.realpath(tab.path) == real:
                self.active, self.focus = i, 'editor'
                self.main_view = 'editor'
                self.need_render = True
                return tab
        try:
            view = audio.open_view(self, path)
        except Exception as exc:               # never let this break opening
            self.status('Cannot play %s: %s' % (os.path.basename(path), exc))
            return None
        self.hush_audio()                      # nothing else keeps playing
        cur = self.editor
        if (cur and cur.path is None and not cur.doc.dirty
                and cur.doc.text() == '' and len(self.editors) == 1):
            self.editors[0] = view             # replace a pristine untitled tab
            self.active = 0
        else:
            self.editors.append(view)
            self.active = len(self.editors) - 1
        self.focus = 'editor'
        self.main_view = 'editor'
        self.need_render = True
        self.status('Opened %s' % self.rel(path))
        return view

    def rel(self, path):
        """A path relative to the project, for showing in the status bar."""
        if not path:
            return 'untitled'
        for root in (self.root, os.path.realpath(self.root)):
            try:
                # /tmp and /var are symlinks on macOS, so try the real root too
                short = os.path.relpath(os.path.realpath(path), root)
            except ValueError:
                continue
            if not short.startswith('..'):
                return short
        try:
            short = os.path.relpath(path, self.root)
        except ValueError:
            return path
        return path if short.startswith('..') else short

    def close_tab(self, index=None):
        index = self.active if index is None else index
        if not self.editors:
            return
        ed = self.editors[index]
        if (ed.doc.dirty and self.autosave and ed.doc.path
                and not ed.doc.autosave_blocked and not ed.doc.readonly):
            try:
                ed.doc.save()             # auto-save owns it; just write it
            except Exception as exc:
                self.status('Save failed: %s' % exc)
        if ed.doc.dirty:
            def do_save():
                if self.save(ed):
                    self._remove_tab(index)
            self.overlay = Confirm('Save %s before closing?' % ed.title, do_save,
                                   on_no=lambda: self._remove_tab(index))
            return
        self._remove_tab(index)

    def _remove_tab(self, index):
        closing = self.editors[index]
        if hasattr(closing, 'close'):
            closing.close()                    # an audio tab lets go of its player
        del self.editors[index]
        if not self.editors:
            self.new_file()
        self.active = max(0, min(self.active if index > self.active else self.active - 1,
                                 len(self.editors) - 1))
        self.need_render = True

    def save(self, ed=None, path=None, force=False):
        ed = ed or self.editor
        if ed is None:
            return False
        if getattr(ed, 'is_audio', False):
            return False               # a sound file has nothing to save
        if ed.doc.disk_missing and path is None:
            self.status('%s was deleted; it will not be written back'
                        % self.rel(ed.doc.path))
            return False               # 'save as' is still the way to keep it
        if ed.is_diff:
            self.status('%s is a read-only diff' % ed.title)
            return False
        target = path or ed.doc.path
        if not target:
            self.prompt_save_as(ed)
            return False
        if (not force and not ed.doc.dirty and target == ed.doc.path
                and not ed.doc.disk_missing and not ed.doc.autosave_blocked):
            self.status('%s is already saved' % self.rel(target))
            return True                      # nothing to write, like VS Code
        try:
            ed.doc.save(target, force=force)
        except StaleFileError:
            self.overlay = Confirm(
                '%s changed on disk. Overwrite it with your version?' % ed.title,
                lambda: self.save(ed, path, force=True),
                on_no=lambda: self.status('Not saved - the file on disk is newer'),
                extra=('d', 'd to diff', lambda: self.open_conflict_diff(ed)))
            self.need_render = True
            return False
        except Exception as exc:
            self.status('Save failed: %s' % exc)
            return False
        ed.hl = ed.hl.for_path(target)
        ed.states.hl = ed.hl
        ed.states.invalidate_from(0)
        self.status('Saved %s' % self.rel(target))
        self.tree.refresh()
        self._file_cache = None
        return True

    def autosave_tick(self):
        """Write any file that has been sitting modified and idle."""
        if not self.autosave:
            return
        now = time.time()
        for ed in self.editors:
            doc = ed.doc
            if not doc.dirty or not doc.path or doc.autosave_blocked or doc.readonly:
                continue
            if now - doc.changed_at < self.autosave_delay:
                continue
            try:
                doc.save()
            except StaleFileError:
                doc.autosave_blocked = True   # the watcher will ask about it
            except Exception as exc:
                doc.autosave_blocked = True   # do not retry every keystroke
                self.status('Auto-save failed for %s: %s (ctrl+s to retry)'
                            % (self.rel(doc.path), exc))
            self.need_render = True

    def autosave_flush(self):
        """Write everything auto-save owns right now (on quit, for instance)."""
        if not self.autosave:
            return
        for ed in self.editors:
            doc = ed.doc
            if doc.dirty and doc.path and not doc.autosave_blocked and not doc.readonly:
                try:
                    doc.save()
                except Exception:
                    doc.autosave_blocked = True

    # ---------------- keeping up with the filesystem ----------------
    def recheck_disk_soon(self):
        """Look at the files again on the next tick (after a tab switch, say)."""
        self._last_watch = 0.0

    def check_disk_changes(self, force=False):
        """Notice files that something else - a terminal, a tool - rewrote."""
        now = time.time()
        if not force and now - self._last_watch < self.watch_interval:
            return
        self._last_watch = now
        for index, ed in enumerate(self.editors):
            try:
                self._check_one_file(index, ed)
            except Exception as exc:
                # a file going strange must never take the editor down
                ed.doc.autosave_blocked = True
                self.status('Cannot follow %s: %s' % (self.rel(ed.doc.path), exc))
                self.need_render = True
        self._refresh_tree_if_due(now)

    def _check_one_file(self, index, ed):
        if getattr(ed, 'is_audio', False):
            return ed.check_disk()        # a sound tab watches its own file
        doc = ed.doc
        if not doc.path:
            return
        state = doc.disk_status()
        if state == 'missing':
            if not doc.disk_missing:
                doc.disk_missing = True
                doc.autosave_blocked = True       # do not resurrect it silently
                self.status('%s was deleted on disk - the tab is read-only '
                            'now; copy what you need before closing it'
                            % self.rel(doc.path))
                self.need_render = True
            return
        doc.disk_missing = False
        if state != 'changed':
            return
        if doc.dirty:
            self._resolve_conflict(index, ed)
            return
        size = doc.disk_size()
        if size > self.max_file_bytes:
            if not doc.autosave_blocked:
                doc.autosave_blocked = True
                shown = ('%.1f MB' % (size / 1048576.0) if size >= 1048576
                         else '%d KB' % max(1, size // 1024))
                self.status('%s grew to %s on disk - not reloading it'
                            % (self.rel(doc.path), shown))
                self.need_render = True
            return
        doc.reload()
        ed.ensure_visible()
        self.status('Reloaded %s (changed on disk)' % self.rel(doc.path))
        self.need_render = True

    def _resolve_conflict(self, index, ed):
        """The file moved under us while the buffer had unsaved edits."""
        doc = ed.doc
        doc.autosave_blocked = True        # never overwrite it behind their back
        if getattr(doc, 'conflict_ack_stamp', None) == doc.disk_state():
            return                         # already answered for this version
        if self.overlay is not None or index != self.active or self.main_view != 'editor':
            return                         # ask when they are looking at that tab

        def take_disk():
            doc.reload()
            ed.ensure_visible()
            doc.autosave_blocked = False
            self.status('Reloaded %s from disk' % self.rel(doc.path))

        def keep_mine():
            doc.stamp_disk()               # stop asking; this buffer is the truth
            doc.autosave_blocked = False
            doc.changed_at = time.time()
            self.status('Kept your version of %s' % self.rel(doc.path))

        self.overlay = Confirm(
            '%s changed on disk. Reload and lose your unsaved edits?' % ed.title,
            take_disk, on_no=keep_mine, on_cancel=keep_mine,
            extra=('d', 'd to diff', lambda: self.open_conflict_diff(ed)))
        self.need_render = True

    def refresh_git(self):
        """Keep the explorer letters and the editor change bars current."""
        if not self.git.enabled:
            return
        branch = self.git.branch
        if self.git.refresh():                  # self throttling
            self.git.line_cache.clear()         # a commit or checkout landed
            self.need_render = True
        if self.git.branch != branch:           # a checkout with a clean tree
            self.need_render = True
        ed = self.editor
        if ed is None or not ed.doc.path:
            return
        marks = self.git.line_status(ed.doc.path, ed.doc.disk_stamp)
        if marks is not ed.git_marks:
            ed.git_marks = marks
            self.need_render = True

    def _refresh_tree_if_due(self, now):
        if now - self._last_tree_refresh < self.tree_interval:
            return
        self._last_tree_refresh = now
        if not self.show_tree:
            return
        before = [e.path for e in self.tree.entries]
        self.tree.refresh()
        if [e.path for e in self.tree.entries] != before:
            self._file_cache = None        # quick-open should see new files
            self.need_render = True

    # ---------------- preferences ----------------
    def set_setting(self, key, value):
        """Change one preference, apply it now and remember it for next time."""
        if self.settings.get(key) == value:
            return
        if key == 'audio' and value and not self.audio_allowed():
            return                     # it stays off until there is a player
        self.settings[key] = value
        settings_store.save(self.settings)
        self.apply_setting(key, value)
        self.need_render = True

    def audio_allowed(self):
        """Turning sound on: ask where it should come out, then check.

        The panel answers itself away and puts the settings back. Everything
        it does goes through force_setting, so the preference only ever moves
        because an answer moved it.
        """
        from .audio.setup import AudioSetup
        panel = self.overlay if isinstance(self.overlay, SettingsPanel) else None
        self.overlay = AudioSetup(self, panel)
        self.need_render = True
        return False

    def enable_audio_locally(self):
        """The checks as they have always been, for sound on this machine."""
        from . import audio
        self.settings['audio_sink_port'] = 0
        full, plain = audio.survey()
        if full:
            self.force_setting('audio', True,
                               'audio playback on, using %s' % full)
            return True
        both = '%s or %s' % (audio.PREFERRED, audio.PREFERRED_ALSO)
        panel = self.overlay if isinstance(self.overlay, SettingsPanel) else None
        if plain:
            self.overlay = Confirm(
                '%s is not installed, so audio cannot seek or change speed. '
                'Use %s anyway?' % (both, plain),
                lambda: (self.force_setting('audio', True,
                                            'audio playback on, using %s - '
                                            'install %s for seeking'
                                            % (plain, both)),
                         self.back_to(panel)),
                on_no=lambda: (self.status('audio stays off; install %s and '
                                           'turn it on again' % both),
                               self.back_to(panel)),
                on_cancel=lambda: self.back_to(panel))
            self.need_render = True
            return False
        self.status('audio needs %s installed - it stays off' % both)
        return False

    def back_to(self, overlay):
        """Put a panel back after a question interrupted it."""
        if overlay is not None:
            self.overlay = overlay
            self.need_render = True

    def force_setting(self, key, value, message=None):
        """Set a preference without asking again - the answer to the asking."""
        self.settings[key] = value
        settings_store.save(self.settings)
        self.apply_setting(key, value)
        if message:
            self.status(message)
        self.need_render = True

    def apply_setting(self, key, value):
        if key.startswith('review_') and self.review is not None:
            self.review.reset_folds()      # show it the way it is now asked for
        if key == 'appearance':
            # each appearance has its own four palettes; keep the name if it
            # exists in the new set, otherwise fall back to its first
            name = theme.apply(self.settings.get('theme'), value)
            if name != self.settings.get('theme'):
                self.settings['theme'] = name
                settings_store.save(self.settings)
            self.screen.prev = None
            self.need_render = True
            return
        if key == 'theme':
            theme.apply(value, self.settings.get('appearance'))
            self.screen.prev = None            # every cell changed
        elif key == 'autosave':
            self.autosave = value
            if value:
                self.autosave_flush()
        elif key == 'autosave_delay':
            self.autosave_delay = value
        elif key == 'max_lines':
            self.max_file_lines = value
        elif key == 'max_mb':
            self.max_file_bytes = int(value * 1024 * 1024)
        elif key == 'split_view':
            self.split = value            # with no terminal the editor just fills
                                          # the pane, and the top bar offers one
        elif key == 'show_terminal':
            self.show_term = value
            if not value and self.focus == 'terminal':
                self.focus = 'editor'
        elif key == 'show_tree':
            self.show_tree = value
            if not value and self.focus == 'tree':
                self.focus = 'editor'
        elif key == 'tab_width':
            self.default_tab_width = value
            for ed in self.editors:
                if not ed.indent_detected:     # a file with indentation keeps its own
                    ed.tab_width = value

    def open_settings(self):
        self.overlay = SettingsPanel(self)
        self.need_render = True

    def toggle_settings(self):
        if isinstance(self.overlay, SettingsPanel):
            self.overlay = None
            self.need_render = True
        else:
            self.open_settings()

    def toggle_autosave(self):
        self.set_setting('autosave', not self.autosave)
        self.status('Auto-save %s' % ('on' if self.autosave else 'off'))

    def prompt_save_as(self, ed=None):
        ed = ed or self.text_editor()
        if ed is None:
            return
        start = ed.doc.path or os.path.join(self.root, '')

        def accept(text):
            if not text:
                return
            target = os.path.abspath(os.path.expanduser(text))
            if os.path.exists(target) and target != (ed.doc.path or ''):
                self.overlay = Confirm(
                    '%s already exists. Overwrite it?' % os.path.basename(target),
                    lambda: self.save(ed, target, force=True),
                    on_no=lambda: self.status('Not saved'))
                self.need_render = True
                return
            self.save(ed, target)
        self.overlay = Prompt('Save as:', text=start, on_accept=accept)
        self.need_render = True   # show it at once

    # ---------------- full-size terminals ----------------
    def big_term(self):
        """The full-size terminal session currently on show, if any."""
        if not self.big_terms:
            return None
        self.big_active = max(0, min(self.big_active, len(self.big_terms) - 1))
        return self.big_terms[self.big_active]

    def main_is_terminal(self):
        return self.main_view == 'terminal' and bool(self.big_terms)

    def split_active(self, main_w=None):
        """Split view only applies with a session to show and room to show it."""
        if not self.split or not self.big_terms:
            return False
        if main_w is None:
            # what the layout last had to work with: reconstructing it from
            # the panes under-counts whatever the frame took, and then this
            # answers differently depending on who asks
            main_w = self._main_w
        return main_w >= 60

    def toggle_split(self):
        """Swap between the two layouts, putting every tab back as it was."""
        was = 'split' if self.split else 'single'
        self._view_state[was] = self.viewports()
        self.set_setting('split_view', not self.split)
        now = 'split' if self.split else 'single'
        self.restore_viewports(self._view_state.get(now))
        self.status('Split view %s' % ('on' if self.split else 'off'))

    def new_big_terminal(self):
        self._term_seq += 1
        term = self.adopt(TerminalPanel(self, cwd=self.root, header=False,
                                        title='terminal %d' % self._term_seq))
        rect = self.rects.get('editor') if self.rects else None
        term.start(rect.w if rect else 80, rect.h if rect else 24)
        self.big_terms.append(term)
        self._last_title_poll = 0.0        # name it as soon as it has a shell
        self.big_active = len(self.big_terms) - 1
        self.main_view = 'terminal'
        self.focus = 'editor'
        self.need_render = True
        return term

    def show_terminal_view(self):
        if not self.big_terms:
            self.new_big_terminal()
        else:
            self.main_view = 'terminal'
            self.focus = 'editor'
            self.need_render = True

    def show_editor_view(self):
        self.main_view = 'editor'
        self.focus = 'editor'
        self.recheck_disk_soon()
        self.need_render = True

    def toggle_main_view(self):
        if self.main_view == 'terminal':
            self.show_editor_view()
        else:
            self.show_terminal_view()

    def close_big_terminal(self, index):
        if not (0 <= index < len(self.big_terms)):
            return
        self.big_terms.pop(index).stop()
        if not self.big_terms:
            self.main_view = 'editor'
            self.focus = 'editor'
        elif index < self.big_active:
            self.big_active -= 1          # keep showing the same session
        elif index == self.big_active:
            self.big_active = min(index, len(self.big_terms) - 1)
        self.need_render = True

    def _track_tabs(self):
        """Remember what was in front of us, so ctrl+t can go back to it.

        Watching here rather than at every place that changes a tab means
        nothing can move without being noticed - opening, closing, clicking
        and quick-open all pass through a repaint.
        """
        current = self.editors[self.active] if self.editors else None
        if current is not self._seen_tab:
            self._prev_tab, self._seen_tab = self._seen_tab, current
        term = self.big_terms[self.big_active] if self.big_terms else None
        if term is not self._seen_term:
            self._prev_term, self._seen_term = self._seen_term, term

    def switch_back(self):
        """ctrl+t: back to the tab you were on before this one.

        Files swap with files and shells with shells, whichever group you are
        looking at; f2 is still the way across. With only one tab, or once the
        other one has been closed, there is nothing to go back to.
        """
        if self.main_view == 'terminal':
            group, previous = self.big_terms, self._prev_term
        else:
            group, previous = self.editors, self._prev_tab
        if previous is None or previous not in group:
            return False
        index = group.index(previous)
        if self.main_view == 'terminal':
            if index == self.big_active:
                return False
            self.big_active = index
        else:
            if index == self.active:
                return False
            self.active = index
        self.focus = 'editor'
        self.need_render = True
        return True

    def select_big_terminal(self, delta):
        if len(self.big_terms) > 1:
            self.big_active = (self.big_active + delta) % len(self.big_terms)
            self.need_render = True

    # ---------------- diff tabs ----------------
    def text_editor(self):
        """The active tab if it is a real editor, else None."""
        ed = self.editor
        if ed is None or ed.is_diff or getattr(ed, 'is_audio', False):
            return None
        return ed

    def open_diff(self, view):
        self.adopt(view)
        for i, tab in enumerate(self.editors):
            if getattr(tab, 'key', None) == view.key:
                view.tab_id = tab.tab_id        # the same tab, rebuilt in place
                self.editors[i] = view
                self.active = i
                break
        else:
            self.editors.append(view)
            self.active = len(self.editors) - 1
        self.main_view = 'editor'
        self.focus = 'editor'
        self.need_render = True
        return view

    def open_conflict_diff(self, ed):
        """Your unsaved buffer against the newer file on disk."""
        path = ed.doc.path
        view = DiffView(self, 'conflict:%s' % path, 'diff %s' % ed.title,
                        buffer_source(ed, 'yours (unsaved)'),
                        disk_source(path, 'on disk (newer)'))
        ed.doc.conflict_ack_stamp = ed.doc.disk_state()
        self.status('Read-only diff. Edit in the file tab; this updates as you go.')
        return self.open_diff(view)

    def open_git_diff(self, ed=None, minimal=True):
        ed = ed or self.text_editor()
        if ed is None or not ed.doc.path:
            self.status('Open a file first')
            return None
        if not self.git.enabled:
            self.status('Not inside a git repository')
            return None
        if not self.git.has_diff(ed.doc.path):
            self.status('%s has no committed version to compare with' % ed.title)
            return None
        kind = 'changes' if minimal else 'all'
        upstream = self.git.upstream_ref()
        alt = (rev_source(self.git, ed.doc.path, upstream, upstream)
               if upstream else None)
        view = DiffView(self, 'git:%s:%s' % (kind, ed.doc.path),
                        'diff %s (%s)' % (ed.title, kind),
                        head_source(self.git, ed.doc.path, 'last commit'),
                        buffer_source(ed, '%s (working)' % ed.title),
                        minimal=minimal, alt_left=alt)
        return self.open_diff(view)

    def refresh_diffs(self):
        view = self.editor
        if view is not None and view.is_diff and self.main_view == 'editor':
            if view.refresh():
                self.need_render = True

    # ---------------- status ----------------
    def status(self, msg):
        self.message = msg
        self.message_time = time.time()
        self.need_render = True

    def refresh_terminal_titles(self):
        """Name each terminal after whatever it is running."""
        now = time.time()
        if now - self._last_title_poll < 0.6:
            return
        self._last_title_poll = now
        panels = list(self.big_terms)
        if self.show_term:
            panels.append(self.terminal)
        for panel in panels:
            shell = panel.shell
            if shell is None or shell.fd is None or shell.exited:
                continue
            found = tabnames.foreground(shell.fd, shell.pid, self._pgid_names)
            if found and found != panel.program:
                panel.program = found
                self.need_render = True

    def remember_panes(self):
        """Keep the proportions you dragged the panes to, for next time."""
        width = int(self.sidebar_w)
        height = int(self.term_h) if self.term_h_user_set else 0
        if (self.settings.get('sidebar_width') == width
                and self.settings.get('terminal_height') == height):
            return
        self.settings['sidebar_width'] = width
        self.settings['terminal_height'] = height
        settings_store.save(self.settings)

    def repaint(self):
        """Paint the whole screen again, as if nothing were on it.

        Something else writing to the terminal - a program in a shell, a
        resize the terminal never told us about - can leave characters
        stranded where tide believes it has already drawn. Forgetting what we
        think is up there, wiping it, and painting again puts it right without
        touching a single tab, pane or shell.
        """
        self.check_resize()
        self.screen.prev = None            # nothing on screen is to be trusted
        try:
            self.out.write('\x1b[2J')       # and wipe what anything else left
            self.out.flush()
        except Exception:
            pass
        self.need_render = True

    def toggle_tree(self):
        """Show or hide the explorer; f12, or ctrl+b."""
        self.show_tree = not self.show_tree
        if not self.show_tree and self.focus == 'tree':
            self.focus = 'editor'
        self.need_render = True

    def hush_audio(self, keep=None):
        """One sound at a time: quieten every other audio tab.

        Two players talking to one sink - or to one pair of speakers - is
        nobody's idea of playback, and the sink only makes one sound anyway.
        """
        for tab in self.editors:
            if getattr(tab, 'is_audio', False) and tab is not keep:
                try:
                    tab.player.stop(keep_position=True)
                except Exception:
                    pass

    def _audio_busy(self):
        """Whether the tab on screen is playing something and wants repainting."""
        view = self.editor
        return bool(getattr(view, 'is_audio', False) and self.main_view == 'editor'
                    and view.busy())

    def _sideways_bar_showing(self):
        """Whether the pane on screen is drawing its sideways scrollbar."""
        showing = getattr(self.editor, 'hbar_showing', None)   # not a diff tab
        return bool(showing and showing())

    # ---------------- layout ----------------
    def layout(self):
        w, h = self.screen.width, self.screen.height
        prompt_h = 1 if (self.overlay is not None and not isinstance(self.overlay, (Help,))
                         and not getattr(self.overlay, 'is_list', False)) else 0
        content_h = max(1, h - 1 - prompt_h)
        sw = 0
        if (self.show_tree or self.review is not None) and w > 50:
            sw = min(self.sidebar_w, max(MIN_SIDEBAR_W, w - MIN_MAIN_W))
            sw = max(MIN_SIDEBAR_W, sw)
        rects = {'status': Rect(0, h - 1, w, 1),
                 'sidebar': Rect(0, 0, sw, content_h) if sw else None}
        main_x = sw
        main_w = w - sw
        self._main_w = main_w
        rects['switch'] = Rect(main_x, 0, main_w, 1)
        rects['tabs'] = Rect(main_x, 1, main_w, 1)
        body_h = content_h - 2
        term_h = 0
        if self.show_term:
            # until the user drags the splitter, keep the panel to a sane share
            desired = self.term_h if self.term_h_user_set else min(
                DEFAULT_TERM_H, max(MIN_TERM_H, int(body_h * 0.45)))
            term_h = max(MIN_TERM_H, min(desired, max(MIN_TERM_H, body_h - 3)))
            term_h = max(0, min(term_h, body_h))
        editor_h = max(1, body_h - term_h)
        if self.split_active(main_w) and self.review is None:
            left_w = (main_w - 1) // 2
            rects['editor'] = Rect(main_x, 2, left_w, editor_h)
            rects['divider'] = main_x + left_w
            rects['split'] = Rect(main_x + left_w + 1, 2,
                                  main_w - left_w - 1, editor_h)
        else:
            rects['editor'] = Rect(main_x, 2, main_w, editor_h)
            rects['divider'] = None
            rects['split'] = None
        rects['terminal'] = Rect(main_x, 2 + editor_h, main_w, term_h) if term_h else None
        rects['overlay_area'] = Rect(0, 0, w, h - 1)
        rects = chrome.arrange(rects)
        self.rects = rects
        return rects

    # ---------------- rendering ----------------
    def render(self):
        scr = self.screen
        self._track_tabs()
        r = self.layout()
        scr.clear(bg=theme.BG)
        cursor = None
        if chrome.boxed() and r['sidebar']:
            # with the explorer up, the menus have the top row above it to
            # themselves; without it the switch row draws them, in the same
            # place, rather than being painted over them
            self.render_menu_bar(scr, scr.width)
        if self.review is not None:
            return self.render_review(scr, r)
        if r['sidebar']:
            chrome.frame(scr, r.get('sidebar_box'), self.focus == 'tree')
            self.tree.render(scr, r['sidebar'], self.focus == 'tree')
            self._tree_indicator = self.tree.indicator_showing()
        self._hbar_showing = self._sideways_bar_showing()
        self.render_switch(scr, r['switch'])
        self.render_tabs(scr, r['tabs'])
        if r['split'] is not None:
            left, right = self.editor, self.big_term()
            focused = self.focus == 'editor'
            chrome.frame(scr, r.get('editor_box'),
                         focused and self.main_view == 'editor')
            chrome.frame(scr, r.get('split_box'),
                         focused and self.main_view == 'terminal')
            c_left = left.render(scr, r['editor'],
                                 focused and self.main_view == 'editor') if left else None
            c_right = right.render(scr, r['split'],
                                   focused and self.main_view == 'terminal')
            scr.fill(r['divider'], r['editor'].y, 1, r['editor'].h, bg=theme.PANEL)
            if focused:
                cursor = c_right if self.main_view == 'terminal' else c_left
        else:
            chrome.frame(scr, r.get('editor_box'), self.focus == 'editor')
            main = self.big_term() if self.main_is_terminal() else self.editor
            if main is not None:
                c = main.render(scr, r['editor'], self.focus == 'editor')
                if self.focus == 'editor':
                    cursor = c
        if r['terminal']:
            chrome.frame(scr, r.get('terminal_box'), self.focus == 'terminal')
            c = self.terminal.render(scr, r['terminal'], self.focus == 'terminal')
            if self.focus == 'terminal':
                cursor = c
        self.render_status(scr, r['status'])
        if self.overlay is not None:
            c = self.overlay.render(scr, r['overlay_area'])
            if c:
                cursor = c
        scr.flush(self.out, cursor)
        self.need_render = False

    def render_review(self, scr, r):
        """The review's own screen: changed files, one long diff, the shell."""
        cursor = None
        if r['sidebar']:
            chrome.frame(scr, r.get('sidebar_box'), self.focus == 'tree')
            self.review.render_tree(scr, r['sidebar'], self.focus == 'tree')
        self.render_review_bar(scr, r['switch'])
        self.render_review_tab(scr, r['tabs'])
        chrome.frame(scr, r.get('editor_box'), self.focus == 'editor')
        self.review.render(scr, r['editor'], self.focus == 'editor')
        if r['terminal']:
            chrome.frame(scr, r.get('terminal_box'), self.focus == 'terminal')
            c = self.terminal.render(scr, r['terminal'], self.focus == 'terminal')
            if self.focus == 'terminal':
                cursor = c
        self.render_status(scr, r['status'])
        if self.overlay is not None:
            c = self.overlay.render(scr, r['overlay_area'])
            if c:
                cursor = c
        scr.flush(self.out, cursor)
        self.need_render = False

    def render_review_bar(self, scr, rect):
        """Where the view switch usually is: what this is, and the way out."""
        scr.fill(rect.x, rect.y, rect.w, 1, bg=theme.PANEL)
        label = '  GIT REVIEW  '
        scr.fill(rect.x + 1, rect.y, min(len(label), rect.w - 1), 1,
                 bg=theme.STATUS_ACC)
        scr.put(rect.x + 1, rect.y, label, fg=theme.STATUS_FG, bg=theme.STATUS_ACC,
                attr=BOLD, max_x=rect.x2)
        branch = self.git.read_branch() or ''
        if branch and rect.w > len(label) + len(branch) + 20:
            scr.put(rect.x + len(label) + 3, rect.y, branch, fg=theme.FG_DIM,
                    bg=theme.PANEL)
        chip = '  x  '
        cx = rect.x2 - len(chip)
        self.review_close_span = (cx, rect.x2)
        scr.fill(cx, rect.y, len(chip), 1, bg=theme.PANEL_ALT)
        scr.put(cx, rect.y, chip, fg=theme.TAB_MARK, bg=theme.PANEL_ALT, attr=BOLD)
        hint = 'esc leaves the review '
        if cx - len(hint) > rect.x + len(label) + 4:
            scr.put(cx - len(hint), rect.y, hint, fg=theme.FG_DIM, bg=theme.PANEL)

    def render_review_tab(self, scr, rect):
        """One tab, for the one thing being reviewed."""
        scr.fill(rect.x, rect.y, rect.w, 1, bg=theme.TAB_BG)
        self.tab_spans = []
        self.tab_close_spans = []
        self.tab_arrows = []
        self.plus_span = None
        count = self.review.count()
        label = ' Review: %d file%s changed ' % (count, '' if count == 1 else 's')
        scr.fill(rect.x, rect.y, min(len(label), rect.w), 1, bg=theme.TAB_ACTIVE_BG)
        scr.put(rect.x, rect.y, label, fg=theme.TAB_ACTIVE_FG,
                bg=theme.TAB_ACTIVE_BG, attr=BOLD, max_x=rect.x2)

    def open_review(self):
        """Show every change in the working tree, read only."""
        if not self.git.enabled:
            self.status('not a git repository')
            return False
        if self.review is not None:
            return False
        review = Review(self)
        if not review.count():
            self.status('nothing has changed since the last commit')
            return False
        self.review = review
        self._review_focus = self.focus
        if self.focus != 'terminal':
            self.focus = 'editor'
        self.need_render = True
        return True

    def close_review(self):
        """Put back exactly what was on screen before."""
        if self.review is None:
            return False
        self.review = None
        if self._review_focus and self.focus != 'terminal':
            self.focus = self._review_focus
        self._review_focus = None
        self.need_render = True
        return True

    def render_menu_bar(self, scr, width):
        """The menus, across the very top - where the boxes leave room."""
        row = Rect(0, 0, width, 1)
        scr.fill(0, 0, width, 1, bg=theme.PANEL)
        self.menu_spans, self._menu_end = menus.MenuBar.render(scr, row,
                                                               self.menu_open)

    def render_switch(self, scr, rect):
        """The row above the tabs: the menus, then what the main area shows."""
        self.toggle_spans = []
        x = rect.x + 1
        if not chrome.boxed() or rect.x == 0:
            # the menus belong at the very top left whatever else is showing,
            # so when nothing is to the left of this row they go in it
            scr.fill(rect.x, rect.y, rect.w, 1, bg=theme.PANEL)
            self.menu_spans, x = menus.MenuBar.render(scr, rect, self.menu_open)
            x += 1
        else:
            # the bar was drawn above the explorer and may reach past its
            # edge: start after it, and leave what it painted alone
            x = min(max(x, self._menu_end + 1), rect.x2)
            scr.fill(x, rect.y, max(0, rect.x2 - x), 1, bg=theme.PANEL)
        if not self.split:           # in split view both are already on screen
            # in split view both sets of tabs are on screen, so there is
            # nothing to switch between
            count = ' %d' % len(self.big_terms) if self.big_terms else ''
            for view, label in (('editor', '  Editor  '),
                                ('terminal', '  Terminals%s  ' % count)):
                active = self.main_view == view
                bg = theme.STATUS_ACC if active else theme.PANEL_ALT
                fg = theme.STATUS_FG if active else theme.FG_DIM
                if x < rect.x2:
                    scr.fill(x, rect.y, min(len(label), rect.x2 - x), 1, bg=bg)
                    scr.put(x, rect.y, label, fg=fg, bg=bg,
                            attr=BOLD if active else 0, max_x=rect.x2)
                self.toggle_spans.append((x, x + len(label), view))
                x += len(label) + 1
        # the buttons, laid out right to left with the same gap between each
        self.settings_span = None
        self.repaint_span = None
        self.review_span = None
        self.new_term_span = None
        self.diff_spans = []
        cx = rect.x2
        # settings and review live in the menus now
        cx, self.repaint_span = self._chip(scr, rect, cx, x, ' \u21bb ',
                                           theme.FG_DIM)
        # in split view with nothing to split with, offer to start a shell
        if self.split and not self.big_terms:
            cx, self.new_term_span = self._chip(scr, rect, cx, x, ' </> ',
                                                theme.OK, bold=True)
        # diff buttons, when the file in front of us has committed changes
        ed = self.text_editor()
        if (ed is not None and ed.doc.path and self.git.enabled
                and self.git.has_diff(ed.doc.path)):
            for label, minimal in ((' changes ', True), (' diff all ', False)):
                cx, span = self._chip(scr, rect, cx, x, label,
                                      theme.GIT_LINE_MODIFIED)
                if span is None:
                    break
                self.diff_spans.append((span[0], span[1], minimal))
        hint = 'f2 switch  f5 split  '
        if cx - len(hint) > x + 2:
            scr.put(cx - len(hint), rect.y, hint, fg=theme.FG_DIM, bg=theme.PANEL)

    @staticmethod
    def _chip(scr, rect, cx, floor, label, fg, bold=False):
        """One button in the top bar. Returns where the next one may end."""
        bx = cx - len(label)
        if bx <= floor + 1:            # do not crowd the view switch
            return cx, None
        scr.fill(bx, rect.y, len(label), 1, bg=theme.PANEL_ALT)
        scr.put(bx, rect.y, label, fg=fg, bg=theme.PANEL_ALT,
                attr=BOLD if bold else 0, max_x=rect.x2)
        return bx - 1, (bx, bx + len(label))

    def render_tabs(self, scr, rect):
        """The tab row: one strip normally, one per half in split view."""
        scr.fill(rect.x, rect.y, rect.w, 1, bg=theme.TAB_BG)
        self.tab_spans = []
        self.tab_close_spans = []
        self.tab_arrows = []
        self.plus_span = None
        divider = self.rects.get('divider')
        if self.split_active() and divider is not None:
            left = self.rects.get('tabs_left') or \
                Rect(rect.x, rect.y, divider - rect.x, 1)
            right = self.rects.get('tabs_right') or \
                Rect(divider + 1, rect.y, rect.x2 - divider - 1, 1)
            self._render_strip(scr, left, 'editor')
            self._render_strip(scr, right, 'terminal')
            if not chrome.boxed():     # the boxes already keep them apart
                scr.fill(divider, rect.y, 1, 1, bg=theme.PANEL)
                scr.put(divider, rect.y, '|', fg=theme.BORDER, bg=theme.PANEL)
        else:
            self._render_strip(
                scr, rect, 'terminal' if self.main_is_terminal() else 'editor')

    def outside_project(self, path):
        """Whether a file lives somewhere other than under the project root."""
        if not path:
            return False
        try:
            root = os.path.realpath(self.root)
            here = os.path.realpath(path)
        except OSError:
            return False
        return os.path.relpath(here, root).startswith('..')

    def editor_titles(self):
        """Tab names: the file, plus folders where two of them share a name."""
        paths = [getattr(ed, 'path', None) for ed in self.editors]
        labels = tabnames.titles(paths)
        return [tabnames.tab_label(labels[i] or ed.title)
                for i, ed in enumerate(self.editors)]

    def tab_git_marks(self):
        """(letter, colour) per editor tab, matching the explorer's marks."""
        git = getattr(self, 'git', None)
        if git is None or not git.enabled:
            return [getattr(ed, 'tab_mark', lambda: None)()
                    for ed in self.editors]
        out = []
        for ed in self.editors:
            own = getattr(ed, 'tab_mark', None)
            if own is not None:            # a tab with something of its own
                out.append(own())          # to say - a deleted sound file
                continue
            path = getattr(ed, 'path', None)
            status = git.status_for(path, False) if path else None
            if path and git.is_ignored(path):
                out.append(('', theme.GIT_IGNORED))     # greyed, and no letter
                continue
            out.append((status, theme.git_colour(status)) if status else None)
        return out

    def terminal_titles(self):
        """Tab names: the program each is running, numbered if two match."""
        labels, seen = [], {}
        for term in self.big_terms:
            name = term.tab_title()
            seen[name] = seen.get(name, 0) + 1
            labels.append(name if seen[name] == 1 else '%s %d' % (name, seen[name]))
        return [tabnames.tab_label(lb) for lb in labels]

    def _render_strip(self, scr, rect, strip):
        """One row of tabs, cropped to its own space and scrollable."""
        if rect.w < 4:
            return
        terminals = strip == 'terminal'
        focused = self.main_is_terminal() == terminals
        if terminals:
            names = self.terminal_titles()
            styles = [0] * len(names)
            active_i = self.big_active
            marks = [False] * len(names)
        else:
            names = self.editor_titles()
            active_i = self.active
            marks = [ed.doc.dirty for ed in self.editors]
            # a file from outside the project is named in italics
            styles = [(ITALIC if self.outside_project(getattr(ed, 'path', None))
                       else 0) | (STRIKE if getattr(ed.doc, 'disk_missing', False)
                                  else 0)
                      for ed in self.editors]
        # ' name* M x ' - the marker and git slots keep their width so that
        # tabs never jump about as files change underneath them
        marks_git = self.tab_git_marks() if not terminals else [None] * len(names)
        gap = ' ' if any(m is not None for m in marks_git) else ''
        labels = [' %s%s%s x ' % (n, '*' if marks[i] else ' ',
                                  (gap + ' ') if gap else '')
                  for i, n in enumerate(names)]
        widths = [len(lb) for lb in labels]
        plus = ' + ' if terminals else ''
        total = sum(widths) + len(plus)
        avail = max(1, rect.w)
        self._tab_metrics[strip] = (total, avail)
        scroll = self.tab_scrolls.get(strip, 0)
        max_scroll = max(0, total - avail)
        # reveal the active tab when it changes, but leave a strip the user has
        # scrolled by hand where they put it
        if widths and self._shown_tab.get(strip) != active_i:
            self._shown_tab[strip] = active_i
            acc = sum(widths[:active_i])
            if acc < scroll:
                scroll = acc
            elif acc + widths[active_i] > scroll + avail:
                scroll = acc + widths[active_i] - avail
        scroll = max(0, min(scroll, max_scroll))
        self.tab_scrolls[strip] = scroll

        tx = rect.x - scroll
        for i, label in enumerate(labels):
            active = i == active_i
            bg = theme.TAB_ACTIVE_BG if active else theme.TAB_BG
            fg = theme.TAB_ACTIVE_FG if active else theme.TAB_FG
            if active and not focused:
                fg = theme.FG_DIM          # the half that does not have the keyboard
            if marks_git[i]:               # coloured like the explorer's entry
                fg = marks_git[i][1]
            left = max(rect.x, tx)
            if tx + widths[i] > rect.x and tx < rect.x2:
                scr.fill(left, rect.y, min(tx + widths[i], rect.x2) - left, 1, bg=bg)
                attr = (BOLD if active else 0) | (styles[i] if i < len(styles)
                                                  else 0)
                scr.put(tx, rect.y, label, fg=fg, bg=bg, attr=attr,
                        max_x=rect.x2, min_x=rect.x)
                if gap:
                    letter, colour = marks_git[i] or (None, None)
                    git_x = tx + widths[i] - 4
                    if letter and rect.x <= git_x < rect.x2:
                        scr.put(git_x, rect.y, letter, fg=colour, bg=bg, attr=BOLD)
                mark_x = tx + widths[i] - (6 if gap else 4)
                if marks[i] and rect.x <= mark_x < rect.x2:
                    scr.put(mark_x, rect.y, '*', fg=theme.TAB_MARK, bg=bg, attr=BOLD)
                close_x = tx + widths[i] - 2
                if rect.x <= close_x < rect.x2:
                    scr.put(close_x, rect.y, 'x',
                            fg=theme.FG if active else theme.FG_DIM, bg=bg)
                    self.tab_close_spans.append((close_x, i, strip))
            # only claim clicks inside this strip, or a tab overflowing past
            # the divider would swallow the other half's
            x1, x2 = max(tx, rect.x), min(tx + widths[i], rect.x2)
            if x2 > x1:
                self.tab_spans.append((x1, x2, i, strip))
            tx += widths[i]
        if plus and rect.x <= tx and tx + len(plus) <= rect.x2:
            scr.fill(tx, rect.y, len(plus), 1, bg=theme.PANEL_ALT)
            scr.put(tx, rect.y, plus, fg=theme.OK, bg=theme.PANEL_ALT, attr=BOLD)
            self.plus_span = (tx, tx + len(plus))
        # arrows at the edges, when there is more than fits
        if scroll > 0:
            scr.put(rect.x, rect.y, '<', fg=theme.FG, bg=theme.PANEL_ALT, attr=BOLD)
            self.tab_arrows.append((rect.x, -1, strip))
        if scroll < max_scroll:
            scr.put(rect.x2 - 1, rect.y, '>', fg=theme.FG, bg=theme.PANEL_ALT, attr=BOLD)
            self.tab_arrows.append((rect.x2 - 1, 1, strip))

    def strip_at(self, x):
        """Which set of tabs sits under this column."""
        divider = self.rects.get('divider')
        if self.split_active() and divider is not None:
            return 'editor' if x < divider else 'terminal'
        return 'terminal' if self.main_is_terminal() else 'editor'

    def scroll_tabs(self, direction, step=8, strip=None):
        """Slide one tab strip sideways, the way VS Code's wheel does."""
        strip = strip or ('terminal' if self.main_is_terminal() else 'editor')
        total, avail = self._tab_metrics.get(strip, (0, 1))
        limit = max(0, total - avail)
        self.tab_scrolls[strip] = max(0, min(limit, self.tab_scrolls.get(strip, 0)
                                             + direction * step))
        self.need_render = True

    def render_status(self, scr, rect):
        scr.fill(rect.x, rect.y, rect.w, 1, bg=theme.STATUS_BG)
        x0 = rect.x + 1
        if self.git.enabled and self.git.branch:
            mark = '*' if self.git.statuses else ''
            chip = ' %s%s ' % (self.git.branch, mark)
            scr.fill(rect.x, rect.y, min(len(chip) + 1, rect.w), 1, bg=theme.STATUS_ACC)
            scr.put(rect.x + 1, rect.y, chip.strip(), fg=theme.STATUS_FG,
                    bg=theme.STATUS_ACC, attr=BOLD, max_x=rect.x2)
            x0 = rect.x + len(chip) + 2
        ed = self.editor
        left = ''
        if self.message and time.time() - self.message_time < MESSAGE_SECONDS:
            left = self.message
        elif self.main_is_terminal():
            left = self.big_term().tab_title()
        elif ed is not None and getattr(ed, 'is_audio', False):
            left = ed.title
        elif ed is not None and ed.is_diff:
            left = ed.title
        elif ed:
            left = self.rel(ed.path) + (' *' if ed.doc.dirty else '')
        scr.put(x0, rect.y, left, fg=theme.STATUS_FG, bg=theme.STATUS_BG,
                max_x=rect.x2 - 40)
        right = ''
        if ed is not None and getattr(ed, 'is_audio', False):
            player = ed.player
            state = 'playing' if player.playing else (
                'paused' if player.paused else 'stopped')
            right = '%s  %g×  read-only' % (state, player.rate)
        elif ed is not None and ed.is_diff:
            swap = ('  r: %s' % ed.alt_left.label) if ed.alt_left else ''
            right = '%d changes  %s  read-only  m: %s%s' % (
                ed.changes, 'changes only' if ed.minimal else 'whole file',
                'whole file' if ed.minimal else 'changes only', swap)
        elif self.main_is_terminal():
            term = self.big_term()
            if term.shell and term.shell.exited:
                state = 'exited'
            elif term.scroll:
                state = 'scrolled %d lines back' % term.scroll
            else:
                state = os.path.basename(os.environ.get('SHELL', 'sh'))
            right = 'Terminal %d/%d  %s  f2 editor  f4 new  f1 help' % (
                self.big_active + 1, len(self.big_terms), state)
        elif ed:
            row, col = ed.doc.cursor
            sel = ed.doc.selection()
            selinfo = ''
            if sel:
                n = len(ed.doc.get_range(*sel))
                selinfo = '(%d selected) ' % n
            right = '%sLn %d, Col %d  %s  %s  %s  f1 help' % (
                selinfo, row + 1, col + 1, ed.hl.name,
                'Spaces: %d' % ed.tab_width if ed.use_spaces else 'Tabs',
                'READ-ONLY' if ed.doc.readonly else
                ('auto-save' if self.autosave else 'manual save'))
        if self.focus != 'editor':
            right = '[%s]  %s' % (self.focus, right)
        x = rect.x2 - len(right) - 1
        if x > rect.x:
            scr.put(x, rect.y, right, fg=theme.STATUS_FG, bg=theme.STATUS_BG, max_x=rect.x2)

    # ---------------- focus ----------------
    def cycle_focus(self, back=False):
        order = []
        if self.show_tree:
            order.append('tree')
        order.append('editor')
        if self.show_term:
            order.append('terminal')
        if self.focus not in order:
            self.focus = order[0]
        else:
            i = order.index(self.focus)
            self.focus = order[(i + (-1 if back else 1)) % len(order)]
        self.need_render = True

    def toggle_terminal_visible(self):
        """Show or hide the docked shell.

        ctrl+j has two stages - show and focus, then hide - which is what you
        want from a key you press twice a minute. A menu with a tick beside it
        should just be the tick.
        """
        self.show_term = not self.show_term
        if self.show_term:
            self.focus = 'terminal'
        elif self.focus == 'terminal':
            self.focus = 'editor'
        self.need_render = True

    def toggle_terminal(self):
        if not self.show_term:
            self.show_term = True
            self.focus = 'terminal'
        elif self.focus == 'terminal':
            self.show_term = False
            self.focus = 'editor'
        else:
            self.focus = 'terminal'
        self.need_render = True

    # ---------------- prompts ----------------
    def all_files(self):
        if self._file_cache is not None:
            return self._file_cache
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.git')]
            for f in filenames:
                if f in IGNORE_FILES:
                    continue
                full = os.path.join(dirpath, f)
                out.append(os.path.relpath(full, self.root))
                if len(out) > 20000:
                    break
            if len(out) > 20000:
                break
        out.sort()
        self._file_cache = out
        return out

    def quick_open(self):
        files = self.all_files()

        def accept(name):
            if name:
                self.open_file(os.path.join(self.root, name))
        self.overlay = Prompt('Open:', items=files, on_accept=accept)
        self.need_render = True

    def prompt_open_path(self):
        def accept(text):
            if text:
                self.open_file(os.path.abspath(os.path.expanduser(text)))
        self.overlay = Prompt('Path:', text='', on_accept=accept)
        self.need_render = True   # show it at once

    def prompt_find(self):
        ed = self.text_editor()
        if not ed:
            return
        sel = ed.doc.selection()
        initial = ed.doc.get_range(*sel) if sel and sel[0][0] == sel[1][0] else ed.find_query

        def change(text):
            ed.set_find(text)
            self.overlay.info = '%d matches' % len(ed.find_matches) if text else ''
            if ed.find_matches:
                ed.find_index = min(ed.find_index, len(ed.find_matches) - 1)
                s, e = ed.find_matches[ed.find_index]
                ed.doc.anchor, ed.doc.cursor = s, e
                ed.ensure_visible()

        def accept(text):
            ed.find_next()
            return 'keep'

        def cancel():
            ed.find_query = ''
            ed.find_matches = []

        self.overlay = Prompt('Find:', text=initial, on_accept=accept, on_change=change,
                              on_cancel=cancel)
        self.need_render = True   # show it at once
        if initial:
            change(initial)

    def prompt_replace(self):
        ed = self.text_editor()
        if not ed or not ed.find_query:
            self.status('Use ctrl+f first, then ctrl+r to replace all matches')
            return
        query = ed.find_query

        def accept(text):
            matches = ed.doc.find_all(query)
            for s, e in reversed(matches):
                ed.doc.replace(s, e, text)
            ed.refresh_find()
            self.status('Replaced %d occurrence(s)' % len(matches))
        self.overlay = Prompt('Replace "%s" with:' % query, on_accept=accept)
        self.need_render = True   # show it at once

    def prompt_goto(self):
        ed = self.text_editor()
        if not ed:
            return

        def accept(text):
            try:
                n = int(text.strip().split(':')[0])
            except ValueError:
                self.status('Not a line number: %s' % text)
                return
            # before the first line is the first line, past the last is the
            # last: a number out of range still takes you somewhere sensible
            row = max(0, min(len(ed.doc.lines) - 1, n - 1))
            ed.set_cursor((row, 0))
            ed.top = max(0, row - ed.text_rect.h // 2)
        self.overlay = Prompt('Go to line:', on_accept=accept,
                              info='1-%d' % len(ed.doc.lines))
        self.need_render = True   # show it at once

    # ---------------- events ----------------
    def handle_key(self, key):
        combo = key.combo()
        if self.overlay is not None:
            current = self.overlay
            res = current.on_key(key)
            # a handler may have opened a follow up question; do not wipe it
            if res == 'close' and self.overlay is current:
                self.overlay = None
            self.need_render = True
            return
        if combo == 'f1':
            self.overlay = Help()
            self.need_render = True
            return
        if self.review is not None:
            self.review_key(key, combo)
            return
        if combo == 'f10':
            self.toggle_review()
            return
        if combo in ('f6', 'shift+f6'):
            self.cycle_focus(back=key.shift)
            return
        if combo == 'ctrl+j':
            self.toggle_terminal()
            return
        if combo == 'f5':
            self.toggle_split()
            return
        if combo == 'f12':
            self.toggle_tree()
            return
        if combo == 'f7':
            self.open_git_diff(minimal=True)
            return
        if combo == 'f8':
            self.open_git_diff(minimal=False)
            return
        if combo in ('f9', 'alt+,', 'ctrl+,'):
            self.toggle_settings()
            return
        if combo == 'ctrl+t':
            self.switch_back()
            return
        if combo == 'f2':
            self.toggle_main_view()
            return
        if combo == 'f4':
            self.new_big_terminal()
            return
        if self.focus == 'terminal':
            self.terminal.on_key(key)
            self.need_render = True
            return
        if self.focus == 'editor' and self.main_is_terminal():
            # the main area is a shell: only tab switching is kept back from it
            if combo in ('alt+left', 'ctrl+pageup'):
                self.select_big_terminal(-1)
            elif combo in ('alt+right', 'ctrl+pagedown'):
                self.select_big_terminal(1)
            else:
                self.big_term().on_key(key)
            self.need_render = True
            return
        if self.focus == 'tree':
            if self.tree.on_key(key):
                self.need_render = True
                return
        if combo == 'ctrl+l':
            self.repaint()
            return
        if combo == 'ctrl+q':
            self.quit()
            return
        if combo == 'ctrl+p':
            self.quick_open()
            return
        if combo == 'ctrl+o':
            self.prompt_open_path()
            return
        if combo == 'ctrl+b':
            self.toggle_tree()
            return
        if combo == 'ctrl+n':
            self.new_file()
            return
        if combo == 'ctrl+w':
            self.close_tab()
            return
        if combo == 'ctrl+s':
            self.save()
            self.need_render = True
            return
        if combo in ('alt+s',):
            self.prompt_save_as()
            return
        if combo == 'alt+a':
            self.toggle_autosave()
            return
        if combo == 'ctrl+f':
            self.prompt_find()
            return
        if combo == 'ctrl+r':
            self.prompt_replace()
            return
        if combo == 'ctrl+g':
            self.prompt_goto()
            return
        if combo in ('alt+left', 'ctrl+pageup'):
            if self.editors:
                self.active = (self.active - 1) % len(self.editors)
                self.recheck_disk_soon()
                self.need_render = True
            return
        if combo in ('alt+right', 'ctrl+pagedown'):
            if self.editors:
                self.active = (self.active + 1) % len(self.editors)
                self.recheck_disk_soon()
                self.need_render = True
            return
        if self.focus == 'editor' and self.editor:
            if self.editor.on_key(key):
                self.need_render = True
                return
        self.need_render = True

    def handle_paste(self, ev):
        if self.overlay is not None:
            self.overlay.on_paste(ev.text)
        elif self.focus == 'terminal':
            self.terminal.on_paste(ev.text)
        elif self.focus == 'editor' and self.main_is_terminal():
            self.big_term().on_paste(ev.text)
        elif self.editor:
            self.editor.paste(ev.text)
        self.need_render = True

    def handle_mouse(self, ev):
        if ev.kind == 'move':
            # these arrive in floods, so one costs a pair of numbers and
            # nothing else: where the pointer was. The menu catches up with it
            # on a timer (see hover_tick), and nothing else in tide ever hears
            # about the pointer moving
            self._hover_at = (ev.x, ev.y)
            return
        self.need_render = True
        if self.overlay is not None:
            current = self.overlay
            res = current.on_mouse(ev)
            if res == 'accept':
                r = current.on_key(Key('enter'))
                if r == 'close' and self.overlay is current:
                    self.overlay = None
            if res:
                return
            if ev.kind == 'press' and self.overlay is current:
                self.overlay = None
            return
        r = self.rects or self.layout()
        if ev.y == 0 and not self.mouse_capture:
            for x1, x2, name in self.menu_spans:     # the bar across the top
                if x1 <= ev.x < x2:
                    if ev.kind == 'press':
                        self.open_menu(name, x1)
                    return
        if self.review is not None and not self.mouse_capture:
            if self.review_mouse(ev, r):
                return
        if self.mouse_capture and ev.kind in ('drag', 'release'):
            target = self.mouse_capture
            if ev.kind == 'release':
                self.mouse_capture = None
                if target in ('splitter', 'vsplitter'):
                    self.remember_panes()
            if target == 'splitter':
                if ev.kind == 'drag':
                    body_bottom = r['status'].y
                    self.term_h = max(MIN_TERM_H,
                                      body_bottom - (ev.y - self._splitter_hold))
                    self.term_h_user_set = True
                return
            if target == 'vsplitter':
                if ev.kind == 'drag':
                    w = self.screen.width
                    self.sidebar_w = max(MIN_SIDEBAR_W,
                                         min(ev.x + 1, max(MIN_SIDEBAR_W,
                                                           w - MIN_MAIN_W)))
                return
            if target == 'editor':
                main = self.big_term() if self.main_is_terminal() else self.editor
                if r['split'] is not None:
                    main = self.editor
                if main is not None:
                    main.on_mouse(ev)
                return
            if target == 'split':
                term = self.big_term()
                if term is not None:
                    term.on_mouse(ev)
                return
            if target == 'terminal':
                self.terminal.on_mouse(ev)
                return
            if target == 'tree':
                self.tree.on_mouse(ev)
                return
            return
        grab = chrome.grab_row(r)
        if r['terminal'] and grab is not None and ev.y == grab \
                and ev.x >= r['terminal'].x:
            if ev.kind == 'press':
                self.mouse_capture = 'splitter'
                self._splitter_hold = 0      # grabbed by the border itself
                self.focus = 'terminal'
            return
        if r['terminal'] and r['terminal'].contains(ev.x, ev.y):
            if ev.y == r['terminal'].y:  # header = splitter
                if ev.kind == 'press':
                    self.mouse_capture = 'splitter'
                    # the row grabbed is the row that follows the pointer,
                    # whether that is the box's border or the header inside it
                    self._splitter_hold = ev.y - (grab if grab is not None
                                                  else ev.y)
                    self.focus = 'terminal'
                return
            if ev.kind == 'press':
                self.focus = 'terminal'
                self.mouse_capture = 'terminal'
            self.terminal.on_mouse(ev)
            return
        if (r['sidebar'] and ev.x == chrome.grab_column(r)
                and ev.y < r['status'].y):
            if ev.kind == 'press':       # the divider: drag it to resize
                self.mouse_capture = 'vsplitter'
            return
        if r['sidebar'] and r['sidebar'].contains(ev.x, ev.y):
            if ev.kind == 'press':
                self.focus = 'tree'
                self.mouse_capture = 'tree'
            self.tree.on_mouse(ev)
            return
        if r['switch'].contains(ev.x, ev.y):
            if ev.kind == 'press':
                self._click_switch(ev)
            return
        if r['tabs'].contains(ev.x, ev.y):
            if ev.kind == 'press':
                self._click_tab_bar(ev)
            elif ev.kind in ('wheel_up', 'wheel_left'):
                self.scroll_tabs(-1, strip=self.strip_at(ev.x))
            elif ev.kind in ('wheel_down', 'wheel_right'):
                self.scroll_tabs(1, strip=self.strip_at(ev.x))
            return
        if r['split'] is not None and r['split'].contains(ev.x, ev.y):
            term = self.big_term()
            if term is None:
                return
            if ev.kind == 'press':
                self.focus = 'editor'
                self.main_view = 'terminal'      # the right half now has it
                self.mouse_capture = 'split'
            term.on_mouse(ev)
            return
        if r['editor'].contains(ev.x, ev.y):
            if r['split'] is not None:
                main = self.editor
                if ev.kind == 'press':
                    self.main_view = 'editor'
            else:
                main = self.big_term() if self.main_is_terminal() else self.editor
            if main is None:
                return
            if ev.kind == 'press':
                self.focus = 'editor'
                self.mouse_capture = 'editor'
            main.on_mouse(ev)
            return

    def review_mouse(self, ev, r):
        """Clicks while reviewing: the file list, the page, the way out."""
        if r['terminal'] and r['terminal'].contains(ev.x, ev.y):
            return False                       # the shell below is still live
        if r['switch'].contains(ev.x, ev.y):
            span = getattr(self, 'review_close_span', None)
            if ev.kind == 'press' and span and span[0] <= ev.x < span[1]:
                self.close_review()
            return True
        if (r['sidebar'] and ev.x == chrome.grab_column(r)
                and ev.y < r['status'].y):
            if ev.kind == 'press':             # the divider still resizes
                self.mouse_capture = 'vsplitter'
            return True
        if r['sidebar'] and r['sidebar'].contains(ev.x, ev.y):
            if ev.kind == 'press':
                self.focus = 'tree'
            self.review.on_tree_mouse(ev)
            return True
        if r['tabs'].contains(ev.x, ev.y):
            return True                        # the one tab does nothing
        if r['editor'].contains(ev.x, ev.y):
            if ev.kind == 'press':
                self.focus = 'editor'
            self.review.on_mouse(ev)
            return True
        return True

    def review_key(self, key, combo):
        """While reviewing: scroll, pick a file, or leave. Nothing edits."""
        if combo in ('escape', 'ctrl+w', 'f10'):
            self.close_review()
            return
        if combo == 'ctrl+q':
            self.quit()
            return
        if combo == 'ctrl+j':
            self.toggle_terminal()
            return
        if combo in ('f6', 'shift+f6'):
            self.cycle_focus(back=key.shift)
            return
        if self.focus == 'terminal':
            self.terminal.on_key(key)
            self.need_render = True
            return
        if self.focus == 'tree':
            if self.review.on_tree_key(key):
                self.need_render = True
                return
        if self.review.on_key(key):
            self.need_render = True

    def hover_tick(self):
        """Let the open menu catch up with the pointer, a few times a second.

        Following it report by report would mean a repaint per twitch of the
        hand; a menu is not worth that, and a tenth of a second is not a wait
        anyone notices.
        """
        if self._hover_at is None:
            return
        now = time.time()
        if now - self._hover_seen < HOVER_GAP:
            return
        x, y = self._hover_at
        self._hover_at = None
        self._hover_seen = now
        if isinstance(self.overlay, menus.Dropdown):
            self.overlay.hover(x, y)

    def track_pointer(self, on):
        """Ask the terminal to report the pointer moving, or stop.

        Only while a menu is open, and only if the setting allows it: it is a
        report for every cell the pointer crosses, so it is asked for as
        narrowly as possible and turned off the moment the menu goes.
        """
        on = bool(on) and self.settings.get('menu_hover', True)
        if on == self._tracking:
            return
        self._tracking = on
        try:
            # 1000, 1002 and 1003 are one tracking mode, not three switches:
            # turning 1003 off turns the mouse off altogether, which leaves
            # tide deaf to it and the terminal doing its own selection. So
            # what tide always wants is asked for again on the way back down
            self.out.write('\x1b[?1003h\x1b[?1006h' if on else
                           '\x1b[?1003l\x1b[?1000h\x1b[?1002h\x1b[?1006h')
            self.out.flush()
        except Exception:
            pass

    def open_menu(self, name, x=None):
        """Drop one of the menus open under its name."""
        if self.menu_open == name:
            self.menu_open = None
            self.overlay = None
            self.track_pointer(False)
            self.need_render = True
            return
        items = self.menu_items(name)
        if items is None:
            self.menu_open = None
            self.track_pointer(False)
            self.overlay = Help()          # Help is the shortcut list itself
            self.need_render = True
            return
        if x is None:
            x = next((s[0] for s in self.menu_spans if s[2] == name), 1)
        self.menu_open = name
        self.overlay = menus.Dropdown(self, name, x, self.rects['switch'].y + 1,
                                      items, width=self.menu_width())
        self.track_pointer(True)
        self.need_render = True

    def open_menu_beside(self, name, delta):
        """Left and right walk along the bar, as menus do everywhere."""
        order = [span[2] for span in self.menu_spans] or list(menus.NAMES)
        if name not in order:
            return
        self.menu_open = None
        self.open_menu(order[(order.index(name) + delta) % len(order)])

    def menu_width(self):
        """One width for all of them, so the box does not jump about."""
        widest = 0
        for name in menus.NAMES:
            items = self.menu_items(name)
            if items:
                widest = max(widest, menus.item_width(items))
        return min(max(widest, 18), MENU_MAX_W)

    def open_documents(self):
        """The File menu: go to a line, and every open document."""
        items = [('Open File...', 'ctrl+o', self.browse_files),
                 ('Go to line...', 'ctrl+g',
                  self.prompt_goto if self.text_editor() else None),
                 menus.SEPARATOR]
        names = self.editor_titles()
        marks = self.tab_git_marks()
        for i, ed in enumerate(self.editors):
            style = ITALIC if self.outside_project(getattr(ed, 'path', None)) else 0
            if getattr(ed.doc, 'disk_missing', False):
                style |= STRIKE
            letter = (marks[i][0] if marks[i] else '') or ''
            label = menus.tick(i == self.active) + names[i] + \
                ('*' if ed.doc.dirty else '')
            items.append((tabnames.crop(label, MENU_MAX_W - 8), letter,
                          (lambda n=i: self.show_tab(n)), style))
        return items

    def show_tab(self, index):
        """Go to that document, from the File menu."""
        if 0 <= index < len(self.editors):
            self.active = index
            self.main_view = 'editor'
            self.focus = 'editor'
            self.need_render = True

    def menu_items(self, name):
        """What each menu offers. None means it is a button, not a menu."""
        tick = menus.tick
        if name == 'Tide':
            return [
                ('Settings...', 'f9', self.open_settings),
                menus.SEPARATOR,
                ('Save to named session...', '',
                 None if self.session else self.name_session),
                ('Rename session...', self.session or '',
                 self.rename_session if self.session else None),
                menus.SEPARATOR,
                ('Quit', 'ctrl+q', self.quit),
            ]
        if name == 'File':
            return self.open_documents()
        if name == 'View':
            return [
                (tick(self.show_term) + 'Terminal panel', 'ctrl+j',
                 self.toggle_terminal_visible),
                (tick(self.split) + 'Split view', 'f5', self.toggle_split),
                (tick(self.show_tree) + 'Explorer', 'f12', self.toggle_tree),
                menus.SEPARATOR,
                (tick(self.review is not None) + 'Git review', 'f10',
                 self.toggle_review),
            ]
        return None

    def toggle_review(self):
        """In and out of the review, from the same place in the menu."""
        if self.review is not None:
            return self.close_review()
        return self.open_review()

    def browse_files(self):
        """Open File...: look around the machine and pick one."""
        from .browser import FileBrowser
        here = self.editor.path if getattr(self.editor, 'path', None) else None
        self.overlay = FileBrowser(self, os.path.dirname(here) if here
                                   else self.root)
        self.need_render = True

    def rel_folder(self, path):
        """A folder to show in a title: short if it is under the project."""
        try:
            short = os.path.relpath(path, self.root)
        except ValueError:
            return path
        if short == '.':
            return os.path.basename(self.root) or self.root
        if not short.startswith('..'):
            return short
        home = os.path.expanduser('~')
        return ('~' + path[len(home):]) if path.startswith(home) else path

    def _click_switch(self, ev):
        for x1, x2, name in self.menu_spans:
            if x1 <= ev.x < x2:
                self.open_menu(name, x1)
                return
        if self.settings_span and self.settings_span[0] <= ev.x < self.settings_span[1]:
            self.open_settings()
            return
        if self.new_term_span and self.new_term_span[0] <= ev.x < self.new_term_span[1]:
            self.new_big_terminal()
            return
        span = getattr(self, 'repaint_span', None)
        if span and span[0] <= ev.x < span[1]:
            self.repaint()
            return
        span = getattr(self, 'review_span', None)
        if span and span[0] <= ev.x < span[1]:
            self.open_review()
            return
        for x1, x2, minimal in self.diff_spans:
            if x1 <= ev.x < x2:
                self.open_git_diff(minimal=minimal)
                return
        for x1, x2, view in self.toggle_spans:
            if x1 <= ev.x < x2:
                if view == 'terminal':
                    self.show_terminal_view()
                else:
                    self.show_editor_view()
                return

    def _close_index(self, i, strip=None):
        strip = strip or ('terminal' if self.main_is_terminal() else 'editor')
        if strip == 'terminal':
            self.close_big_terminal(i)
        else:
            self.close_tab(i)

    def _click_tab_bar(self, ev):
        for x, direction, strip in self.tab_arrows:
            if ev.x == x:
                self.scroll_tabs(direction, step=16, strip=strip)
                return
        if self.plus_span and self.plus_span[0] <= ev.x < self.plus_span[1]:
            self.new_big_terminal()
            return
        for close_x, i, strip in self.tab_close_spans:
            if ev.x == close_x:
                self._close_index(i, strip)
                return
        for x1, x2, i, strip in self.tab_spans:
            if x1 <= ev.x < x2:
                if ev.button == 1:          # middle-click also closes
                    self._close_index(i, strip)
                elif strip == 'terminal':
                    self.big_active = i
                    self.main_view = 'terminal'
                    self.focus = 'editor'
                else:
                    self.active = i
                    self.main_view = 'editor'
                    self.focus = 'editor'
                    self.recheck_disk_soon()
                return

    # ---------------- named sessions ----------------
    def session_state(self):
        """What this session is: where, which documents, how the panes are."""
        files = []
        for tab in self.editors:
            path = getattr(tab, 'path', None)
            if path and not tab.is_diff and not getattr(tab, 'is_audio', False):
                files.append(os.path.abspath(path))
        here = getattr(self.editor, 'path', None)
        return {'root': self.root, 'files': files,
                'active': files.index(os.path.abspath(here))
                if here and os.path.abspath(here) in files else 0,
                'split': bool(self.split), 'show_term': bool(self.show_term),
                'show_tree': bool(self.show_tree)}

    def save_session(self):
        """Keep the named session up to date; unnamed sessions keep nothing."""
        if self.session:
            sessions.save(self.session, self.session_state())

    def enter_session(self, name):
        """This is now that session: take the lock and write it down."""
        self.session = name
        sessions.claim(name)
        self.save_session()

    def name_session(self):
        """Save what is open as a session with a name of its own."""
        if self.session:
            return

        def accept(text):
            name = (text or '').strip()
            trouble = sessions.why_not(name)
            if not trouble and (sessions.exists(name) or sessions.busy(name)):
                trouble = 'there is already a session called %s' % name
            if trouble:
                self.overlay.info = trouble
                self.need_render = True
                return 'keep'
            self.enter_session(name)
            self.status('session %s - reopen with  tide --resume %s'
                        % (name, name))
        self.overlay = Prompt('Save to named session:', on_accept=accept,
                              info='letters, digits, dot, dash, underscore')
        self.need_render = True

    def rename_session(self):
        """Give the session a different name, if nothing else has it."""
        if not self.session:
            return

        def accept(text):
            name = (text or '').strip()
            trouble = sessions.why_not(name)
            if not trouble and name != self.session and (
                    sessions.exists(name) or sessions.busy(name)):
                trouble = 'there is already a session called %s' % name
            if trouble:
                self.overlay.info = trouble
                self.need_render = True
                return 'keep'
            if name == self.session:
                return
            self.save_session()
            if not sessions.rename(self.session, name):
                self.overlay.info = 'could not rename it'
                self.need_render = True
                return 'keep'
            self.session = name
            self.status('session renamed to %s' % name)
        self.overlay = Prompt('Rename session:', text=self.session,
                              on_accept=accept)
        self.need_render = True

    def quit(self):
        self.autosave_flush()
        if self.autosave:
            # auto-save means what it says: nothing is lost on the way out
            for e in self.editors:
                if e.doc.dirty and e.doc.path:
                    self.save(e)
        dirty = [e for e in self.editors if e.doc.dirty]
        if not dirty:
            self.running = False
            return

        def save_all():
            for e in dirty:
                if e.doc.path:
                    self.save(e)
            if any(e.doc.dirty for e in self.editors):
                # something could not be written: untitled, or a failed save
                self.status('Still unsaved - use alt+s to give it a name, '
                            'or ctrl+q then q to discard')
                return
            self.running = False

        names = ', '.join(e.doc.name for e in dirty[:4])
        if len(dirty) > 4:
            names += ' and %d more' % (len(dirty) - 4)
        self.overlay = Choice(
            'Unsaved changes',
            ['%d file(s) have changes that are not on disk:' % len(dirty),
             names, '', 'Quitting without saving loses them.'],
            [('s', 'Save all and quit', save_all),
             ('q', 'Quit without saving',
              lambda: setattr(self, 'running', False)),
             ('c', 'Cancel - stay in tide', lambda: None)])
        self.need_render = True

    # ---------------- main loop ----------------
    def _on_winch(self, *_a):
        self.resized = True

    def check_resize(self):
        try:
            cols, rows = os.get_terminal_size(self.out.fileno())
        except Exception:
            cols, rows = 80, 24
        if cols != self.screen.width or rows != self.screen.height:
            self.screen.resize(cols, rows)
            self.need_render = True

    def _on_terminate(self, *_a):
        """SIGHUP/SIGTERM (the window closed, or someone killed us)."""
        self.running = False

    def stuck_report(self):
        """Where tide is, right now, written where it can be read afterwards.

        If the screen ever stops answering, `kill -USR1 <pid>` from another
        terminal leaves a traceback in this file saying exactly what tide was
        doing - which beats guessing at it from the outside.
        """
        import faulthandler
        path = os.path.join(os.path.dirname(settings_store.config_path()),
                            'stuck.log')
        try:
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            self._stuck_file = open(path, 'a')
            faulthandler.enable(self._stuck_file)
            faulthandler.register(signal.SIGUSR1, file=self._stuck_file,
                                  all_threads=True, chain=False)
        except Exception:
            pass                        # a diagnostic is never worth a crash

    def run(self):
        self.stuck_report()
        try:
            signal.signal(signal.SIGWINCH, self._on_winch)
        except (ValueError, AttributeError):
            pass
        for name in ('SIGHUP', 'SIGTERM', 'SIGINT'):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, self._on_terminate)
                except (ValueError, OSError):
                    pass
        try:
            with RawTerminal(self.in_fd, self.out):
                self.check_resize()
                self.layout()
                if self.show_term:
                    self.terminal.start(
                        self.rects['terminal'].w if self.rects['terminal'] else 80,
                        max(2, (self.rects['terminal'].h - 1) if self.rects['terminal'] else 10))
                self.render()
                while self.running:
                    self.tick()
        finally:
            # last line of defence: an exception, a lost terminal or a signal
            # must not cost the user their edits
            self.autosave_flush()
            self.terminal.stop()
            for term in self.big_terms:
                term.stop()
            for tab in self.editors:
                if hasattr(tab, 'close'):
                    tab.close()          # no sound outlives the editor
            if isinstance(self.out, Out):
                self.out.restore()
            if self.session:
                # what was open is what you get back next time
                self.save_session()
                sessions.release(self.session)

    def tick(self, timeout=0.2):
        if self.resized:
            self.resized = False
            self.check_resize()
        if self.message and time.time() - self.message_time >= MESSAGE_SECONDS:
            self.message = ''            # it has timed out; take it off the bar
            self.need_render = True
        if self._tree_indicator and not self.tree.indicator_showing():
            self.need_render = True      # the explorer's scroll bar has faded
        if self._hbar_showing and not self._sideways_bar_showing():
            self.need_render = True      # so has the editor's sideways one
        panels = {}
        if self.show_term and self.terminal.fd is not None:
            panels[self.terminal.fd] = (self.terminal, True)
        for i, term in enumerate(self.big_terms):
            if term.fd is not None:
                panels[term.fd] = (term, self.main_view == 'terminal' and i == self.big_active)
        fds = [self.in_fd] + list(panels)
        try:
            ready, _, _ = select.select(fds, [], [], timeout)
        except (select.error, OSError) as exc:
            if getattr(exc, 'errno', None) == 4:  # EINTR
                return
            ready = []
        for fd in ready:
            if fd not in panels:
                continue
            panel, visible = panels[fd]
            # drain a little so bursty output does not cause a redraw per chunk
            deadline = time.time() + 0.02
            while True:
                if not panel.pump():
                    break
                if time.time() > deadline:
                    break
                r2, _, _ = select.select([fd], [], [], 0)
                if not r2:
                    break
            if visible:
                self.need_render = True
        if self._pending or self.in_fd in ready:
            data = b''.join(self._pending)     # heard while a frame went out
            del self._pending[:]
            if self.in_fd in ready:
                try:
                    data += os.read(self.in_fd, 65536)
                except BlockingIOError:
                    pass                       # nothing there after all
                except OSError:
                    self.running = False
                    return
                else:
                    if not data:
                        self.running = False   # the terminal has gone
                        return
            events = list(self.decoder.feed(data))
            for i, ev in enumerate(events):
                if (isinstance(ev, Mouse) and ev.kind == 'move'
                        and i + 1 < len(events)
                        and isinstance(events[i + 1], Mouse)
                        and events[i + 1].kind == 'move'):
                    continue      # only where a run of moves ended matters
                if isinstance(ev, Key):
                    self.handle_key(ev)
                elif isinstance(ev, Mouse):
                    self.handle_mouse(ev)
                elif isinstance(ev, Paste):
                    self.handle_paste(ev)
                if not self.running:
                    break
        if getattr(self.out, 'stalled', False):
            self.out.stalled = False
            self.screen.prev = None      # the terminal missed a frame: redraw
            self.need_render = True
        self.hover_tick()
        if self._tracking and not isinstance(self.overlay, menus.Dropdown):
            self.track_pointer(False)   # nothing is listening: stop the reports
        if self._audio_busy():
            self.need_render = True
        self.autosave_tick()
        self.refresh_terminal_titles()
        self.check_disk_changes()
        self.refresh_git()
        self.refresh_diffs()
        if self.review is not None and self.review.refresh():
            self.need_render = True
        if self.show_term and self.terminal.shell and self.terminal.shell.exited:
            self.terminal.shell.poll()
        # a full-size session closes itself when its shell exits
        for i in range(len(self.big_terms) - 1, -1, -1):
            shell = self.big_terms[i].shell
            if shell and shell.exited:
                shell.poll()
                self.close_big_terminal(i)
        if self.need_render and self.running:
            self.render()
