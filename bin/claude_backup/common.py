"""Shared helpers: OS detection, well-known roots, scope resolution, logging, subprocess."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPES = ("personal", "harness")


class BackupError(RuntimeError):
    """Fatal, user-facing. The CLI prints str(e) and exits 1."""


def os_name() -> str:
    s = platform.system()
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(s, s.lower())


def home() -> Path:
    return Path.home()  # patched in tests; never cache at import time


@dataclass(frozen=True)
class PersonalRoots:
    claude_dir: Path
    claude_json: Path


def personal_roots() -> PersonalRoots:
    return PersonalRoots(home() / ".claude", home() / ".claude.json")


def resolve_harness_path(explicit: Path | None, *, interactive: bool) -> Path:
    """--harness-path, else $CLAUDE_PROJECT_DIR, else ~/optisigns, else ask (or fail when non-interactive)."""
    candidates = [explicit, os.environ.get("CLAUDE_PROJECT_DIR"), home() / "optisigns"]
    for c in candidates:
        if c and (Path(c) / ".claude").is_dir():
            return Path(c).resolve()
    if interactive and sys.stdin.isatty():
        ans = input("Path to the os-claude-harness checkout (contains .claude/): ").strip()
        if ans and (Path(ans) / ".claude").is_dir():
            return Path(ans).resolve()
    raise BackupError("harness path not found: pass --harness-path <dir> (a dir containing .claude/)")


def resolve_bundle_dir(explicit: Path | None) -> Path:
    """--bundle, else $CLAUDE_BACKUP_DIR, else the repo this code lives in."""
    if explicit:
        return explicit.resolve()
    env = os.environ.get("CLAUDE_BACKUP_DIR")
    if env:
        return Path(env).resolve()
    return REPO_ROOT


def scopes_for(arg: str) -> tuple[str, ...]:
    return SCOPES if arg == "all" else (arg,)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def run(cmd: list[str], *, check: bool = True, input_text: str | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, input=input_text, timeout=timeout)
