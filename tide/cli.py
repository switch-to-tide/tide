"""Command line entry point."""

import argparse
import os
import sys

from . import __version__
from . import theme
from .app import App


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(
        prog='tide', description='A small terminal IDE: editor, explorer and shells.')
    ap.add_argument('--version', action='version',
                    version='terminal_ide %s' % __version__)
    ap.add_argument('paths', nargs='*', help='files or a directory to open')
    ap.add_argument('--no-terminal', action='store_true', help='start with the terminal hidden')
    ap.add_argument('--no-tree', action='store_true', help='start with the explorer hidden')
    ap.add_argument('--no-autosave', action='store_true',
                    help='do not write files automatically (ctrl+s to save)')
    ap.add_argument('--autosave-delay', type=float, default=None, metavar='SECONDS',
                    help='quiet time before an edited file is written')
    ap.add_argument('--max-lines', type=int, default=None, metavar='N',
                    help='ask before opening a file with more lines')
    ap.add_argument('--max-mb', type=float, default=None, metavar='MB',
                    help='ask before opening a file bigger than this')
    ap.add_argument('--theme', default=None, choices=['dark', 'midnight', 'ember', 'light'],
                    help='colour theme for this session')
    args = ap.parse_args(argv)

    root = None
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            root = p
        else:
            files.append(p)
    if root is None:
        root = os.path.dirname(os.path.abspath(files[0])) if files else os.getcwd()

    if not sys.stdout.isatty():
        sys.stderr.write('tide needs an interactive terminal.\n')
        return 2

    app = App(root=root, paths=[])
    if args.no_terminal:
        app.show_term = False
    if args.no_tree:
        app.show_tree = False
    # flags win for this session, but are not written to the settings file
    if args.no_autosave:
        app.autosave = False
    if args.autosave_delay is not None:
        app.autosave_delay = max(0.1, args.autosave_delay)
    if args.max_lines is not None:
        app.max_file_lines = max(1, args.max_lines)
    if args.max_mb is not None:
        app.max_file_bytes = int(max(0.01, args.max_mb) * 1024 * 1024)
    if args.theme:
        theme.apply(args.theme)
    for f in files:
        app.open_file(f)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
