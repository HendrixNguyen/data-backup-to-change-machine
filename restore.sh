#!/bin/sh
# claude-backup restore — see README.md
exec sh "$(dirname -- "$0")/_bootstrap.sh" restore "$@"
