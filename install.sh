#!/bin/bash
# Sort Studio installer for Mac and Linux: downloads the app to ~/sort-studio and opens it on your Downloads folder.
#   curl -fsSL https://raw.githubusercontent.com/GitSiddhantag/sort-studio/main/install.sh | bash
set -e
REPO="GitSiddhantag/sort-studio"
DIR="$HOME/sort-studio"

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
  echo "Sort Studio needs Python 3."
  echo "On a Mac run:  xcode-select --install   (or install it from https://www.python.org/downloads/), then run this again."
  exit 1
fi

echo "Downloading Sort Studio…"
TMP="$(mktemp -d)"
curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP"
mkdir -p "$DIR"
cp -R "$TMP"/*/. "$DIR"/
rm -rf "$TMP"
chmod +x "$DIR/Sort Downloads.command" 2>/dev/null || true

echo "Installed in $DIR"
echo "Next time, just run:  python3 $DIR/sort.py"
echo "Opening… (press Ctrl+C here to stop)"
cd "$DIR"
exec python3 sort.py "$@"
