"""Just enough git for the decorations: file status and per-line change marks.

Branches, staging, pushing and the rest stay in the terminal where they
belong.  This only answers two questions: how has this file changed, and
which of its lines are new or edited?
"""

import io
import os
import re
import subprocess
import time

# status letters, in the order they take precedence
CONFLICT = '!'
UNTRACKED = 'U'
ADDED = 'A'
DELETED = 'D'
RENAMED = 'R'
MODIFIED = 'M'

# per-line marks in the editor gutter
LINE_ADDED = 'added'
LINE_MODIFIED = 'modified'
LINE_DELETED = 'deleted'

_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


class Git(object):
    def __init__(self, root, interval=1.5):
        self.root = os.path.abspath(root)
        # git reports resolved paths ("/private/var/..."), while the explorer
        # carries whatever the user typed ("/var/..."); line them up once
        self._root_real = os.path.realpath(self.root)
        self._alias = self.root if self._root_real != self.root else None
        self.repo = None
        self.statuses = {}        # abspath -> status letter
        self.dir_marks = {}       # directory abspath -> status letter
        self.line_cache = {}      # abspath -> (stamp, {line_no: mark})
        self.interval = interval
        self.enabled = False
        self.revision = 0             # bumped whenever the status set changes
        self.branch = None            # the name shown in the status bar
        self._upstream = None
        self._upstream_token = object()
        self._ignored = {}            # path -> True, as git check-ignore says
        self._ignored_revision = -1
        self._last_refresh = 0.0
        self._failures = 0
        self.repo = self._toplevel()
        self.enabled = self.repo is not None
        self.branch = self.read_branch()

    def _norm(self, path):
        """A path in the same shape as the keys git hands back."""
        path = os.path.abspath(path)
        if self._alias and path.startswith(self._alias):
            return self._root_real + path[len(self._alias):]
        return path

    # ---------------- running git ----------------
    def _run(self, args, timeout=3.0, stdin=None):
        try:
            if stdin is not None:
                process = subprocess.Popen(
                    ['git'] + args, cwd=self.root, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                out = process.communicate(stdin, timeout=timeout)[0]
                if process.returncode not in (0, 1):   # 1 just means no matches
                    raise OSError('git said %s' % process.returncode)
            else:
                out = subprocess.check_output(
                    ['git'] + args, cwd=self.root, stderr=subprocess.DEVNULL,
                    timeout=timeout)
        except Exception:
            self._failures += 1
            if self._failures >= 3:
                self.enabled = False       # not a repo, no git, or too slow
            return None
        self._failures = 0
        return out

    def _toplevel(self):
        out = self._run(['rev-parse', '--show-toplevel'], timeout=2.0)
        if not out:
            return None
        top = out.decode('utf-8', 'replace').strip()
        return top or None

    # ---------------- file status ----------------
    def refresh(self, force=False):
        """Re-read `git status`; cheap enough to call on a timer."""
        if not self.enabled:
            return False
        now = time.time()
        if not force and now - self._last_refresh < self.interval:
            return False
        self._last_refresh = now
        self.branch = self.read_branch()      # cheap, and only every interval
        out = self._run(['status', '--porcelain', '-z', '--untracked-files=all'])
        if out is None:
            return False
        statuses = {}
        parts = out.decode('utf-8', 'replace').split('\0')
        i = 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            xy, name = entry[:2], entry[3:]
            if xy[0] in 'RC':
                i += 1                     # the rename source follows
            statuses[os.path.join(self.repo, name)] = self._letter(xy)
        changed = statuses != self.statuses
        self.statuses = statuses
        if changed:
            self.dir_marks = self._roll_up(statuses)
            self.revision += 1
        return changed

    @staticmethod
    def _letter(xy):
        if xy == '??':
            return UNTRACKED
        if 'U' in xy or xy in ('AA', 'DD'):
            return CONFLICT
        if 'A' in xy:
            return ADDED
        if 'D' in xy:
            return DELETED
        if 'R' in xy or 'C' in xy:
            return RENAMED
        return MODIFIED

    def _roll_up(self, statuses):
        """Mark the directories that contain changes, the way VS Code does."""
        marks = {}
        for path, letter in statuses.items():
            parent = os.path.dirname(path)
            while parent and parent.startswith(self.repo):
                current = marks.get(parent)
                if current is None or (current == UNTRACKED and letter != UNTRACKED):
                    marks[parent] = letter if letter == UNTRACKED else MODIFIED
                if parent == self.repo:
                    break
                parent = os.path.dirname(parent)
        return marks

    def status_for(self, path, is_dir=False):
        if not self.enabled or not path:
            return None
        path = self._norm(path)
        return self.dir_marks.get(path) if is_dir else self.statuses.get(path)

    # ---------------- per line marks ----------------
    def line_status(self, path, stamp=None):
        """{line number (0 based): mark} for a file, against HEAD."""
        if not self.enabled or not path:
            return {}
        path = self._norm(path)
        cached = self.line_cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        marks = self._compute_lines(path)
        self.line_cache[path] = (stamp, marks)
        return marks

    def _compute_lines(self, path):
        if self.statuses.get(path) == UNTRACKED:
            try:
                with open(path, 'rb') as f:
                    count = f.read().count(b'\n') + 1
            except OSError:
                return {}
            return dict((i, LINE_ADDED) for i in range(count))
        out = self._run(['diff', '--no-color', '--no-ext-diff', '-U0', 'HEAD', '--', path])
        if not out:
            return {}
        marks = {}
        for line in out.decode('utf-8', 'replace').splitlines():
            m = _HUNK.match(line)
            if not m:
                continue
            old_len = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_len = int(m.group(4)) if m.group(4) is not None else 1
            if new_len == 0:                       # lines were removed here
                marks[max(0, new_start - 1)] = LINE_DELETED
                continue
            kind = LINE_ADDED if old_len == 0 else LINE_MODIFIED
            for n in range(new_start, new_start + new_len):
                marks[n - 1] = kind
        return marks

    # ---------------- revisions ----------------
    STATE_FILES = ('HEAD', 'index', 'FETCH_HEAD', 'ORIG_HEAD', 'packed-refs',
                   'MERGE_HEAD', os.path.join('refs', 'heads'),
                   os.path.join('refs', 'remotes'))

    def state_token(self):
        """A cheap fingerprint of the repository's state.

        Stats a handful of files inside .git, so a commit, checkout, reset,
        fetch or pull changes it - without running git or touching the network.
        """
        if not self.enabled:
            return None
        base = os.path.join(self.repo, '.git')
        if os.path.isfile(base):              # a worktree or submodule pointer
            base = self.repo
        marks = []
        for name in self.STATE_FILES:
            try:
                st = os.stat(os.path.join(base, name))
                marks.append(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
            except OSError:
                marks.append(0)
        return tuple(marks)

    def git_dir(self):
        base = os.path.join(self.repo, '.git') if self.repo else None
        if base and os.path.isfile(base):     # a worktree or submodule pointer
            return self.repo
        return base

    def read_branch(self):
        """The current branch, straight out of .git/HEAD - no subprocess."""
        base = self.git_dir()
        if not base:
            return None
        try:
            with io.open(os.path.join(base, 'HEAD'), encoding='utf-8') as f:
                head = f.read().strip()
        except (OSError, IOError):
            return None
        if head.startswith('ref: refs/heads/'):
            return head[len('ref: refs/heads/'):]
        if head.startswith('ref: '):
            return head[5:].rsplit('/', 1)[-1]
        return (head[:7] + '...') if head else None

    def upstream_ref(self):
        """The branch this one tracks ('origin/main'), or None.

        Cached until the repository state changes; we never fetch ourselves,
        so this only moves when you fetch or pull in a terminal.
        """
        token = self.state_token()
        if self._upstream_token == token:
            return self._upstream
        self._upstream_token = token
        out = self._run(['rev-parse', '--abbrev-ref', '--symbolic-full-name',
                         '@{upstream}'], timeout=2.0)
        self._upstream = out.decode('utf-8', 'replace').strip() if out else None
        return self._upstream

    def file_at_rev(self, path, rev='HEAD'):
        """The text of a file at a revision, or None if it is not there."""
        if not self.enabled:
            return None
        rel = os.path.relpath(self._norm(path), self.repo)
        if rel.startswith('..'):
            return None
        out = self._run(['show', '%s:%s' % (rev, rel.replace(os.sep, '/'))])
        if out is None:
            return None
        return out.decode('utf-8', 'replace')

    def file_at_head(self, path):
        return self.file_at_rev(path, 'HEAD')

    # ---------------- ignored files ----------------
    def mark_ignored(self, paths):
        """Ask git which of these paths are ignored, and remember the answer.

        One call for everything the explorer is showing, refreshed when the
        repository changes, so drawing a row costs nothing.
        """
        if not self.enabled or not paths:
            return
        if self._ignored_revision != self.revision:
            self._ignored = {}
            self._ignored_revision = self.revision
        unknown = [p for p in paths if p not in self._ignored]
        if not unknown:
            return
        out = self._run(['check-ignore', '--stdin', '-z'],
                        stdin=b'\0'.join(p.encode('utf-8') for p in unknown))
        hits = set()
        if out:
            hits = set(part for part in out.decode('utf-8', 'replace').split('\0') if part)
        for p in unknown:
            self._ignored[p] = p in hits

    def is_ignored(self, path):
        return bool(self._ignored.get(path))

    def has_diff(self, path):
        """True for a tracked file with changes - the case a diff is worth it."""
        return self.status_for(path) in ('M', 'A', 'R')

    def forget(self, path):
        self.line_cache.pop(self._norm(path), None)
