#!/usr/bin/env python3
"""claude-backup CLI. Subcommands are wired in later tasks; this file only parses args."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_backup import __version__  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claude-backup")
    p.add_argument("--version", action="version", version=f"claude-backup {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--scope", choices=["personal", "harness", "all"], default="all")
    common.add_argument("--harness-path", type=Path, default=None)
    common.add_argument("--bundle", type=Path, default=None, help="bundle dir (default: $CLAUDE_BACKUP_DIR or this repo)")
    common.add_argument("--yes", action="store_true", help="skip confirmations")

    e = sub.add_parser("export", parents=[common])
    e.add_argument("--commit-secrets", action="store_true")

    r = sub.add_parser("restore", parents=[common])
    r.add_argument("--target", default="claude", help="claude|codex|antigravity|opencode|kilo|all")
    r.add_argument("--only", action="append", default=[], help="bundle-relative path, e.g. personal/skills/foo")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--force", action="store_true")
    r.add_argument("--remap", action="append", default=[], help="OLD_PREFIX=NEW_PREFIX for project paths")

    d = sub.add_parser("doctor", parents=[common])
    d.add_argument("--target", default="claude")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "export":
        from claude_backup.export_cmd import run_export
        return run_export(args)
    if args.cmd == "restore":
        from claude_backup.restore_cmd import run_restore
        return run_restore(args)
    if args.cmd == "doctor":
        from claude_backup.restore_cmd import run_doctor
        return run_doctor(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
