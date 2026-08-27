"""Text document: lines, cursor, selection, editing primitives and undo."""

import hashlib
import io
import os
import re
import stat
import time

WORD_RE = re.compile(r'\w+')

# how many typed characters collect into one undo step before a new one starts;
# Emacs draws the same line at twenty
COALESCE_LIMIT = 20

# the temp file is created private and readable only by us; a brand new file
# then gets the mode a plain open() would have given it. Reading the umask
# means setting it, so we do it once here, at import, before anything runs.
_UMASK = os.umask(0o022)
os.umask(_UMASK)
NEW_FILE_MODE = 0o666 & ~_UMASK


class StaleFileError(IOError):
    """The file changed on disk after we read it; saving would lose that work."""


def is_word_char(c):
    return c.isalnum() or c == '_'


class Edit(object):
    """One reversible change, in the command-pattern sense."""

    __slots__ = ('start', 'removed', 'inserted', 'cur_before', 'cur_after',
                 'sel_before', 'version_before', 'version_after')

    def __init__(self, start, removed, inserted, cur_before, cur_after, sel_before,
                 version_before=0, version_after=0):
        self.start = start
        self.removed = removed
        self.inserted = inserted
        self.cur_before = cur_before
        self.cur_after = cur_after
        self.sel_before = sel_before
        # the document version either side of this edit; undo and redo move
        # between them, so "are we back at the saved state?" is answerable
        self.version_before = version_before
        self.version_after = version_after


class Document(object):
    def __init__(self, path=None, text=None):
        self.path = path
        self.lines = ['']
        self.eol = '\n'
        self.encoding = 'utf-8'
        self.readonly = False         # set when the file is not valid UTF-8
        self.changed_at = 0.0         # time of the last edit (for auto-save)
        self.disk_stamp = None        # timestamps and size as of our last sync
        self.disk_hash = None         # what the file held when we last synced
        self.disk_missing = False
        self.autosave_blocked = False  # set after an auto-save fails
        self.cursor = (0, 0)          # (row, col)
        self.anchor = None            # selection anchor or None
        self.goal_col = None          # remembered column for vertical moves
        self.undo_stack = []
        self.redo_stack = []
        self._coalesce = False
        self.on_change = None         # callback(first_changed_row)
        self._version = 0             # changes with every edit
        self._version_seq = 0
        self.saved_version = 0        # the version last written to disk
        if text is not None:
            self.set_text(text)
        elif path and os.path.exists(path):
            self.load(path)

    # ---------------- content ----------------
    @property
    def dirty(self):
        """True when the buffer differs from what was last saved or loaded.

        Tracked by version rather than by counting undo entries: undoing back
        to the saved state marks the file clean again, and undoing then typing
        something else marks it dirty even though the stack is the same height.
        """
        return self._version != self.saved_version

    def _new_version(self):
        self._version_seq += 1
        return self._version_seq

    def set_text(self, text):
        if '\r\n' in text:
            self.eol = '\r\n'
            text = text.replace('\r\n', '\n')
        self.lines = text.split('\n') or ['']
        if not self.lines:
            self.lines = ['']
        self._version = self.saved_version = 0
        self._version_seq = 0
        self._changed(0)

    def text(self):
        return '\n'.join(self.lines)

    def load(self, path):
        if os.path.exists(path) and not os.path.isfile(path):
            # a pipe would block for ever, a device would be nonsense
            raise IOError('%s is not a regular file' % os.path.basename(path))
        with io.open(path, 'rb') as f:
            raw = f.read()
        try:
            text = raw.decode('utf-8')
            self.readonly = False
        except UnicodeDecodeError:
            # we would have to invent bytes to write this back out, so don't
            text = raw.decode('utf-8', 'replace')
            self.readonly = True
        self.set_text(text)
        self.path = path
        self.undo_stack = []
        self.redo_stack = []
        self._version = self.saved_version = 0   # a fresh read is the saved state
        self._version_seq = 0
        self._coalesce = False
        self.disk_missing = False
        self.disk_hash = self._hash(self.text())   # what the file held just now
        self.stamp_disk()

    def save(self, path=None, force=False):
        """Write the buffer out.

        Refuses if the file changed on disk since we last read or wrote it -
        the same guard VS Code puts up as "the content on disk is newer" -
        unless `force` says the user has decided to overwrite it.
        """
        path = path or self.path
        if not path:
            raise ValueError('no path')
        if self.readonly:
            raise IOError('%s is not valid UTF-8 and was opened read-only'
                          % os.path.basename(path))
        # only the bytes count: a chmod or a touch moves the stamp without
        # changing anything we would be overwriting
        guard = (not force and path == self.path and self.disk_stamp is not None)
        if guard and self.disk_status() == 'changed':
            raise StaleFileError('%s changed on disk since it was read'
                                 % os.path.basename(path))
        # write through a symlink to the file it points at, not over the link
        target = os.path.realpath(path)
        if os.path.exists(target) and not os.path.isfile(target):
            raise IOError('%s is not a regular file' % os.path.basename(target))
        data = self.eol.join(self.lines)
        # vim's backupcopy=auto rule: a file with more than one name is written
        # in place, because a rename would leave the other names on the old
        # content. Everything else gets the atomic temp file and rename.
        try:
            links = os.stat(target).st_nlink
        except OSError:
            links = 1
        if links > 1:
            self._write_in_place(target, data, guard, path)
        else:
            self._write_atomically(target, data, guard, path)
        self.path = path
        self.autosave_blocked = False
        self.disk_missing = False
        self.disk_hash = self._hash(self.text())
        self.stamp_disk()             # our own write must not look external
        self.saved_version = self._version
        # start a fresh undo group, so typing that continues after a save is
        # recorded as a new edit and still registers as unsaved
        self._coalesce = False
        return path

    # ---------------- keeping up with the file on disk ----------------
    def file_key(self):
        """What the filesystem calls this file, whatever path was typed.

        Two paths that differ only in case, or through a link, are the same
        file - and must never end up in two buffers.
        """
        if not self.path:
            return None
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    def disk_state(self):
        """(mtime, ctime, size) of the file, or None if it is not there.

        The change time is in there because a tool can restore a file's
        modification time after rewriting it (`cp -p`, `touch -r`), but
        nothing in user space can hold the change time still.
        """
        if not self.path:
            return None
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        mtime = getattr(st, 'st_mtime_ns', None)
        if mtime is None:
            mtime = int(st.st_mtime * 1e9)
        ctime = getattr(st, 'st_ctime_ns', None)
        if ctime is None:
            ctime = int(st.st_ctime * 1e9)
        return (mtime, ctime, st.st_size)

    def disk_size(self):
        state = self.disk_state()
        return state[2] if state else 0

    def stamp_disk(self):
        self.disk_stamp = self.disk_state()

    @staticmethod
    def _hash(text):
        return hashlib.sha1(text.encode('utf-8', 'replace')).digest()

    def disk_status(self):
        """'same', 'changed', 'missing' or 'untracked'."""
        if not self.path:
            return 'untracked'
        state = self.disk_state()
        if state is None:
            return 'missing'
        if self.disk_stamp is None or state == self.disk_stamp:
            return 'same'
        # the stamp moved: only call it a change if the bytes really differ
        # from the ones we last read or wrote - a chmod, a touch or a rewrite
        # with identical content is not something to interrupt anyone about
        try:
            with io.open(self.path, 'rb') as f:
                raw = f.read()
        except OSError:
            return 'missing'
        if self.disk_state() != state:
            # it changed again while we were reading it, so the writer is
            # still going; leave it alone and look again next time
            return 'same'
        try:
            text = raw.decode('utf-8').replace('\r\n', '\n')
        except UnicodeDecodeError:
            self.disk_stamp = state
            return 'changed'
        if self.disk_hash is not None and self._hash(text) == self.disk_hash:
            self.disk_stamp = state       # metadata moved, content did not
            return 'same'
        return 'changed'

    def reload(self):
        """Re-read the file, keeping the cursor roughly where it was."""
        row, col = self.cursor
        self.load(self.path)
        self.cursor = self.clamp((row, col))
        self.anchor = None
        self.goal_col = None
        return True

    def _write_atomically(self, target, data, guard, path):
        # The process id keeps two editors saving the same file apart, and the
        # random tail keeps us apart from a leftover of a dead one. O_EXCL is
        # what matters: we create the temp file or we fail, so nobody who can
        # write to this directory can leave a symlink here beforehand and have
        # the save land on a file of their choosing.
        tmp = '%s.tide-tmp.%d.%s' % (target, os.getpid(), os.urandom(4).hex())
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(tmp, flags, 0o600)
            with io.open(fd, 'w', encoding='utf-8', newline='') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())      # on disk before the rename
            self._copy_metadata(target, tmp)
            # writing took time; make sure nobody wrote while we did
            if guard and self.disk_status() == 'changed':
                raise StaleFileError('%s changed on disk while it was being saved'
                                     % os.path.basename(path))
            os.replace(tmp, target)       # atomic: readers see old or new
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def _write_in_place(self, target, data, guard, path):
        if guard and self.disk_status() == 'changed':
            raise StaleFileError('%s changed on disk while it was being saved'
                                 % os.path.basename(path))
        with io.open(target, 'w', encoding='utf-8', newline='') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _copy_metadata(original, tmp):
        """Give the replacement the permissions the original had."""
        try:
            st = os.stat(original)
        except OSError:
            try:
                os.chmod(tmp, NEW_FILE_MODE)   # brand new file: the usual mode
            except OSError:
                pass
            return
        try:
            os.chmod(tmp, stat.S_IMODE(st.st_mode))
        except OSError:
            pass
        if hasattr(os, 'chown'):
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except OSError:
                pass                      # not permitted; the content matters more

    @property
    def name(self):
        return os.path.basename(self.path) if self.path else 'untitled'

    def line(self, row):
        return self.lines[row] if 0 <= row < len(self.lines) else ''

    def _changed(self, row):
        self.changed_at = time.time()
        if self.on_change:
            self.on_change(row)

    # ---------------- positions ----------------
    def clamp(self, pos):
        row, col = pos
        row = max(0, min(row, len(self.lines) - 1))
        col = max(0, min(col, len(self.lines[row])))
        return (row, col)

    def end_pos(self):
        return (len(self.lines) - 1, len(self.lines[-1]))

    @staticmethod
    def _ordered(a, b):
        return (a, b) if a <= b else (b, a)

    def selection(self):
        """-> (start, end) or None."""
        if self.anchor is None or self.anchor == self.cursor:
            return None
        return self._ordered(self.anchor, self.cursor)

    def selected_text(self):
        sel = self.selection()
        return self.get_range(*sel) if sel else ''

    def get_range(self, start, end):
        (r1, c1), (r2, c2) = start, end
        if r1 == r2:
            return self.lines[r1][c1:c2]
        out = [self.lines[r1][c1:]]
        out.extend(self.lines[r1 + 1:r2])
        out.append(self.lines[r2][:c2])
        return '\n'.join(out)

    # ---------------- raw edits ----------------
    def _raw_replace(self, start, end, text):
        (r1, c1), (r2, c2) = start, end
        head = self.lines[r1][:c1]
        tail = self.lines[r2][c2:]
        new = (head + text + tail).split('\n')
        self.lines[r1:r2 + 1] = new
        if len(new) == 1:
            return (r1, len(head) + len(text))
        return (r1 + len(new) - 1, len(new[-1]))

    def replace(self, start, end, text, coalesce=False):
        """Replace [start, end) with text; records undo. -> new position."""
        start, end = self._ordered(self.clamp(start), self.clamp(end))
        removed = self.get_range(start, end)
        if not removed and not text:
            return start
        cur_before = self.cursor
        sel_before = self.anchor
        last = self.undo_stack[-1] if self.undo_stack else None
        merged = False
        if (coalesce and self._coalesce and last is not None and not removed
                and not last.removed and '\n' not in text
                and len(last.inserted) < COALESCE_LIMIT):
            er = self._pos_after(last.start, last.inserted)
            if er == start:
                last.inserted += text
                merged = True
        newpos = self._raw_replace(start, end, text)
        version = self._new_version()
        if not merged:
            self.undo_stack.append(Edit(start, removed, text, cur_before, newpos,
                                        sel_before, self._version, version))
        else:
            self.undo_stack[-1].cur_after = newpos
            self.undo_stack[-1].version_after = version
        self._version = version
        self._coalesce = coalesce
        del self.redo_stack[:]        # a new edit ends the redo branch
        if len(self.undo_stack) > 4000:
            del self.undo_stack[:1000]   # bound the history; the rest still works
        self.cursor = newpos
        self.anchor = None
        self._changed(start[0])
        return newpos

    @staticmethod
    def _pos_after(start, text):
        if '\n' not in text:
            return (start[0], start[1] + len(text))
        parts = text.split('\n')
        return (start[0] + len(parts) - 1, len(parts[-1]))

    def insert(self, text, coalesce=False):
        sel = self.selection()
        if sel:
            return self.replace(sel[0], sel[1], text)
        return self.replace(self.cursor, self.cursor, text, coalesce=coalesce)

    def delete_range(self, start, end):
        return self.replace(start, end, '')

    def break_undo_group(self):
        self._coalesce = False

    def undo(self):
        if not self.undo_stack:
            return False
        e = self.undo_stack.pop()
        end = self._pos_after(e.start, e.inserted)
        self._raw_replace(e.start, end, e.removed)
        self._version = e.version_before
        self.redo_stack.append(e)
        self.cursor = self.clamp(e.cur_before)
        self.anchor = None
        self._coalesce = False
        self._changed(e.start[0])
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        e = self.redo_stack.pop()
        end = self._pos_after(e.start, e.removed)
        self._raw_replace(e.start, end, e.inserted)
        self._version = e.version_after
        self.undo_stack.append(e)
        self.cursor = self.clamp(e.cur_after)
        self.anchor = None
        self._coalesce = False
        self._changed(e.start[0])
        return True

    # ---------------- movement helpers ----------------
    def move_left(self, pos):
        r, c = pos
        if c > 0:
            return (r, c - 1)
        if r > 0:
            return (r - 1, len(self.lines[r - 1]))
        return pos

    def move_right(self, pos):
        r, c = pos
        if c < len(self.lines[r]):
            return (r, c + 1)
        if r < len(self.lines) - 1:
            return (r + 1, 0)
        return pos

    def word_left(self, pos):
        r, c = pos
        if c == 0:
            return self.move_left(pos)
        line = self.lines[r]
        i = c
        while i > 0 and line[i - 1].isspace():
            i -= 1
        if i > 0:
            if is_word_char(line[i - 1]):
                while i > 0 and is_word_char(line[i - 1]):
                    i -= 1
            else:
                while i > 0 and not is_word_char(line[i - 1]) and not line[i - 1].isspace():
                    i -= 1
        return (r, i)

    def word_right(self, pos):
        r, c = pos
        line = self.lines[r]
        if c >= len(line):
            return self.move_right(pos)
        i = c
        if is_word_char(line[i]):
            while i < len(line) and is_word_char(line[i]):
                i += 1
        elif not line[i].isspace():
            while i < len(line) and not is_word_char(line[i]) and not line[i].isspace():
                i += 1
        while i < len(line) and line[i].isspace():
            i += 1
        return (r, i)

    def word_at(self, pos):
        """-> (start, end) of the word under pos, or None."""
        r, c = self.clamp(pos)
        line = self.lines[r]
        if not line:
            return None
        i = min(c, len(line) - 1)
        if not is_word_char(line[i]):
            if c > 0 and is_word_char(line[c - 1]):
                i = c - 1
            else:
                return None
        s = i
        while s > 0 and is_word_char(line[s - 1]):
            s -= 1
        e = i
        while e < len(line) and is_word_char(line[e]):
            e += 1
        return ((r, s), (r, e))

    def first_nonblank(self, row):
        line = self.line(row)
        return len(line) - len(line.lstrip())

    def indent_of(self, row):
        line = self.line(row)
        return line[:len(line) - len(line.lstrip())]

    def find_all(self, needle, ignore_case=True, regex=False):
        if not needle:
            return []
        flags = re.IGNORECASE if ignore_case else 0
        try:
            rx = re.compile(needle if regex else re.escape(needle), flags)
        except re.error:
            return []
        out = []
        for r, line in enumerate(self.lines):
            for m in rx.finditer(line):
                if m.end() > m.start():
                    out.append(((r, m.start()), (r, m.end())))
        return out
