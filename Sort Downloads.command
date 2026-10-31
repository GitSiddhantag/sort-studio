#!/bin/zsh
# Double-click: scans ~/Downloads and opens the sorting page in your browser.
cd "$(dirname "$0")"
python3 sort.py "$@"
