#!/bin/sh
# claude-backup export — see README.md
exec sh "$(dirname -- "$0")/_bootstrap.sh" export "$@"
