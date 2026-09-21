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


def is_wsl() -> bool:
    """WSL reports itself as Linux, which is correct for how files behave, but it has two homes."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def wsl_windows_claude_dirs() -> list[Path]:
    """Native-Windows Claude Code configs as WSL sees them, if the Windows drive is mounted."""
    out: list[Path] = []
    for users in (Path("/mnt/c/Users"), Path("/c/Users")):
        try:
            if users.is_dir():
                out += sorted(p for p in users.glob("*/.claude") if p.is_dir())
        except OSError:
            pass
    return out


def wsl_notice() -> str | None:
    """Under WSL, say which of the two homes is being used. Restoring into the Linux home when
    Claude Code actually runs on Windows would report success and change nothing that matters."""
    if not is_wsl():
        return None
    linux_side = personal_roots().claude_dir
    windows_side = wsl_windows_claude_dirs()
    if not windows_side:
        return None
    if not linux_side.exists():
        return (f"WSL: targeting {linux_side}, which does not exist, while a Windows-side config is at "
                f"{windows_side[0]}. If your Claude Code runs on Windows, use .\\restore.ps1 from Windows "
                f"or point HOME at the Windows home.")
    return (f"WSL: targeting the Linux home {linux_side}. The Windows-side config at {windows_side[0]} "
            "is a separate install and is not touched.")


def scopes_for(arg: str) -> tuple[str, ...]:
    return SCOPES if arg == "all" else (arg,)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def run(cmd: list[str], *, check: bool = True, input_text: str | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, input=input_text, timeout=timeout)
