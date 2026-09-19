#!/bin/sh
# claude-backup doctor — see README.md
exec sh "$(dirname -- "$0")/_bootstrap.sh" doctor "$@"
