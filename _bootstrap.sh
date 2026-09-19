#!/bin/sh
# Shared POSIX bootstrapper: find Python >= 3.11 or install it, then exec bin/backup.py <subcommand> "$@".
# No business logic lives here. Keep under 30 lines.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SUB="$1"; shift
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }
PY=""
for c in python3.13 python3.12 python3.11 python3 python; do command -v "$c" >/dev/null 2>&1 && py_ok "$c" && { PY="$c"; break; }; done
if [ -z "$PY" ]; then
  echo "claude-backup: Python 3.11+ not found, installing..." >&2
  if command -v brew >/dev/null 2>&1; then brew install python@3.12
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y python3
  elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y python3
  else echo "claude-backup: no package manager found. Install Python 3.11+ from https://www.python.org/downloads/ and re-run." >&2; exit 1; fi
  for c in python3.13 python3.12 python3.11 python3 python; do command -v "$c" >/dev/null 2>&1 && py_ok "$c" && { PY="$c"; break; }; done
  [ -n "$PY" ] || { echo "claude-backup: Python install did not produce a usable python3" >&2; exit 1; }
fi
case "${1:-}" in --version|-h|--help) exec "$PY" "$HERE/bin/backup.py" "$@";; esac
exec "$PY" "$HERE/bin/backup.py" "$SUB" "$@"
