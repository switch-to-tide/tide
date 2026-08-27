#!/bin/sh
# Install terminal_ide without pip: clone it and link the launcher into PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh
#
# Override with TIDE_REPO, TIDE_HOME (checkout) or TIDE_BIN (link location).
set -e

REPO=${TIDE_REPO:-https://github.com/switch-to-tide/tide.git}
HOME_DIR=${TIDE_HOME:-$HOME/.local/share/tide}
BIN_DIR=${TIDE_BIN:-$HOME/.local/bin}

if ! command -v python3 >/dev/null 2>&1; then
    echo "terminal_ide needs python3 (3.7 or newer) on PATH." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "terminal_ide's installer needs git on PATH." >&2
    exit 1
fi

if [ -d "$HOME_DIR/.git" ]; then
    echo "Updating $HOME_DIR"
    git -C "$HOME_DIR" pull --ff-only
else
    echo "Cloning into $HOME_DIR"
    mkdir -p "$(dirname "$HOME_DIR")"
    git clone --depth 1 "$REPO" "$HOME_DIR"
fi

mkdir -p "$BIN_DIR"
ln -sf "$HOME_DIR/bin/tide" "$BIN_DIR/tide"
echo "Linked $BIN_DIR/tide"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo
       echo "$BIN_DIR is not on your PATH. Add this to your shell profile:"
       echo "    export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo
echo "Done. Run 'tide' in any directory."
