#!/bin/sh
# Install tide without pip: clone it and link the launcher into PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/switch-to-tide/tide/main/install.sh | sh
#
# A particular version, as an argument or in TIDE_VERSION:
#
#   curl -fsSL .../install.sh | sh -s -- 0.1.0
#   curl -fsSL .../install.sh | TIDE_VERSION=0.1.0 sh
#
# The version may be a release (0.1.0 or v0.1.0), a branch, or a commit.
# Without one you get main, which is the newest code. Running the installer
# again moves an existing checkout to whatever you ask for that time.
#
# Override with TIDE_REPO, TIDE_HOME (checkout) or TIDE_BIN (link location).
set -e

REPO=${TIDE_REPO:-https://github.com/switch-to-tide/tide.git}
HOME_DIR=${TIDE_HOME:-$HOME/.local/share/tide}
BIN_DIR=${TIDE_BIN:-$HOME/.local/bin}
VERSION=${1:-${TIDE_VERSION:-}}

if ! command -v python3 >/dev/null 2>&1; then
    echo "tide needs python3 (3.7 or newer) on PATH." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "tide's installer needs git on PATH." >&2
    exit 1
fi

# releases are tagged v0.1.0, but nobody wants to type the v
case "$VERSION" in
    '')  REF=main ;;
    v*)  REF=$VERSION ;;
    [0-9]*) REF=v$VERSION ;;
    *)   REF=$VERSION ;;
esac

if [ -n "$VERSION" ] &&
   ! git ls-remote --exit-code "$REPO" "refs/tags/$REF" >/dev/null 2>&1 &&
   ! git ls-remote --exit-code "$REPO" "refs/heads/$REF" >/dev/null 2>&1; then
    echo "tide has no version '$VERSION'. Released versions:" >&2
    git ls-remote --tags --refs "$REPO" | sed 's|.*refs/tags/v*|    |' >&2
    echo "    (or a branch or commit, and nothing at all for the newest code)" >&2
    exit 1
fi

if [ -d "$HOME_DIR/.git" ]; then
    echo "Updating $HOME_DIR to $REF"
    git -C "$HOME_DIR" fetch -q --depth 1 --tags origin "$REF"
    if ! git -C "$HOME_DIR" checkout -q --detach FETCH_HEAD; then
        echo "$HOME_DIR has changes of its own; leaving it alone." >&2
        exit 1
    fi
else
    echo "Cloning $REF into $HOME_DIR"
    mkdir -p "$(dirname "$HOME_DIR")"
    git clone -q --depth 1 --branch "$REF" "$REPO" "$HOME_DIR" 2>/dev/null ||
        git clone -q --depth 1 "$REPO" "$HOME_DIR"    # a commit, not a ref
    git -C "$HOME_DIR" checkout -q --detach "$REF" 2>/dev/null || true
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

INSTALLED=$(sed -n "s/^__version__ = '\(.*\)'/\1/p" "$HOME_DIR/tide/__init__.py")
echo
echo "Done: tide ${INSTALLED:-installed}. Run 'tide' in any directory."
