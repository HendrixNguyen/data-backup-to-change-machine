#!/bin/sh
# claude-backup doctor — see README.md
S="$0"; while [ -h "$S" ]; do D=$(dirname -- "$S"); S=$(readlink "$S"); case "$S" in /*) ;; *) S="$D/$S";; esac; done
exec sh "$(dirname -- "$S")/_bootstrap.sh" doctor "$@"
