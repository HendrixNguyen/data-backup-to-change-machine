"""Preflight: required tools per target, per-OS installers, age key + manifest checks, autocrlf hint."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import common, manifest, plan, secrets

PKG = {  # tool -> per-OS package id
    "git": {"brew": "git", "apt": "git", "dnf": "git", "winget": "Git.Git"},
    "age": {"brew": "age", "apt": "age", "dnf": "age", "winget": "FiloSottile.age"},
}
MANUAL = {
    "claude": "install Claude Code: https://claude.ai/code (or `npm install -g @anthropic-ai/claude-code`)",
    "git": "install git from https://git-scm.com/downloads",
    "age": "install age from https://github.com/FiloSottile/age#installation",
}
INSTALL_TIMEOUT = 600


def required_tools(*, need_claude: bool, need_age: bool = True) -> list[str]:
    return ["git"] + (["age"] if need_age else []) + (["claude"] if need_claude else [])


def missing(tools: list[str]) -> list[str]:
    return [t for t in tools if shutil.which(t) is None]


def _sudo_prefix() -> list[str] | None:
    """[] when already root, ["sudo"] when sudo exists, None when neither — the caller then falls
    through to the manual hint rather than emitting a command that cannot work."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        return ["sudo"]
    return None


def install_command(tool: str, osn: str) -> list[str] | None:
    ids = PKG.get(tool)
    if not ids:
        return None
    if osn == "macos" and shutil.which("brew"):
        return ["brew", "install", ids["brew"]]
    if osn == "linux" and (shutil.which("apt-get") or shutil.which("dnf")):
        pre = _sudo_prefix()
        if pre is None:
            return None
        if shutil.which("apt-get"):
            return pre + ["apt-get", "install", "-y", ids["apt"]]
        return pre + ["dnf", "install", "-y", ids["dnf"]]
    if osn == "windows" and shutil.which("winget"):
        return ["winget", "install", "--id", ids["winget"], "-e", "--accept-source-agreements", "--accept-package-agreements"]
    return None


def manual_hint(tool: str) -> str:
    return MANUAL.get(tool, f"install {tool} manually")


def crlf_hint(bundle_dir: Path, sample_file: str | None = None) -> str:
    """Only when autocrlf really is on AND .gitattributes doesn't already force -text for the
    mismatched file — otherwise autocrlf is not what corrupted it and the remedy would mislead."""
    try:
        r = subprocess.run(["git", "config", "core.autocrlf"], cwd=bundle_dir, capture_output=True, text=True)
        if (r.stdout or "").strip().lower() != "true":
            return ""
        if sample_file:
            a = subprocess.run(["git", "check-attr", "text", "--", sample_file], cwd=bundle_dir, capture_output=True, text=True)
            if (a.stdout or "").strip().rsplit(":", 1)[-1].strip() != "unspecified":
                return ""
    except OSError:
        return ""
    return ("git core.autocrlf=true converted line endings on checkout; fix with "
            "`git config core.autocrlf false && git rm -r --cached . && git checkout -- .` "
            "(this discards uncommitted changes in the bundle clone)")


def _age_required(bundle_dir: Path | None) -> bool:
    """age is only needed when there is something to decrypt AND a key to decrypt it with."""
    return (bundle_dir is not None
            and (bundle_dir / "secrets.env.age").exists()
            and secrets.default_key_file().exists())


def _install(tool: str, cmd: list[str]) -> None:
    # No capture_output: a sudo password prompt has to stay visible. stdout -> stderr so package
    # manager chatter never lands in the plan table on stdout.
    try:
        subprocess.run(cmd, check=True, stdout=sys.stderr, timeout=INSTALL_TIMEOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise common.BackupError(f"installing {tool} failed ({e}) — {manual_hint(tool)}") from e


def run_preflight(*, need_claude: bool, bundle_dir: Path | None, yes: bool = False, dry_run: bool = False) -> None:
    osn = common.os_name()
    need_age = _age_required(bundle_dir)
    todo: list[tuple[str, list[str]]] = []
    for tool in missing(required_tools(need_claude=need_claude, need_age=need_age)):
        cmd = install_command(tool, osn)
        if cmd is None:
            raise common.BackupError(f"{tool} is missing and no package manager was found — {manual_hint(tool)}")
        todo.append((tool, cmd))
    if not need_age and shutil.which("age") is None:
        common.warn("age is not installed — encrypted secrets can't be used; restore continues with placeholders only")
    if todo:
        if dry_run:
            common.warn("dry run: not installing anything; would run: "
                        + "; ".join(" ".join(c) for _, c in todo))
        else:
            if not yes:
                common.log("preflight wants to install missing tools:")
                for _, cmd in todo:
                    common.log(f"  {' '.join(cmd)}")
                if not plan.confirm(yes=False):
                    raise common.BackupError("install declined — "
                                             + "; ".join(manual_hint(t) for t, _ in todo))
            for tool, cmd in todo:
                common.log(f"preflight: installing {tool}: {' '.join(cmd)}")
                _install(tool, cmd)
                if shutil.which(tool) is None:
                    raise common.BackupError(f"{tool} still missing after install — {manual_hint(tool)}")
    if not secrets.default_key_file().exists():
        common.warn(f"no age key at {secrets.default_key_file()} — restore continues with placeholders only")
    if bundle_dir is not None:
        bad = manifest.verify_hashes(bundle_dir)
        if bad:
            hint = crlf_hint(bundle_dir, bad[0])
            raise common.BackupError(f"bundle hash mismatch for {len(bad)} file(s): {', '.join(bad[:5])}"
                                     + (f"\n  likely cause: {hint}" if hint else ""))
