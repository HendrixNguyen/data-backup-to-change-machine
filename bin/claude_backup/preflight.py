"""Preflight: required tools per target, per-OS installers, age key + manifest checks, autocrlf hint."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import common, manifest, secrets

PKG = {  # tool -> per-OS package id
    "git": {"brew": "git", "apt": "git", "dnf": "git", "winget": "Git.Git"},
    "age": {"brew": "age", "apt": "age", "dnf": "age", "winget": "FiloSottile.age"},
}
MANUAL = {
    "claude": "install Claude Code: https://claude.ai/code (or `npm install -g @anthropic-ai/claude-code`)",
    "git": "install git from https://git-scm.com/downloads",
    "age": "install age from https://github.com/FiloSottile/age#installation",
}


def required_tools(*, need_claude: bool) -> list[str]:
    return ["git", "age"] + (["claude"] if need_claude else [])


def missing(tools: list[str]) -> list[str]:
    return [t for t in tools if shutil.which(t) is None]


def install_command(tool: str, osn: str) -> list[str] | None:
    ids = PKG.get(tool)
    if not ids:
        return None
    if osn == "macos" and shutil.which("brew"):
        return ["brew", "install", ids["brew"]]
    if osn == "linux" and shutil.which("apt-get"):
        return ["sudo", "apt-get", "install", "-y", ids["apt"]]
    if osn == "linux" and shutil.which("dnf"):
        return ["sudo", "dnf", "install", "-y", ids["dnf"]]
    if osn == "windows" and shutil.which("winget"):
        return ["winget", "install", "--id", ids["winget"], "-e", "--accept-source-agreements", "--accept-package-agreements"]
    return None


def manual_hint(tool: str) -> str:
    return MANUAL.get(tool, f"install {tool} manually")


def crlf_hint(bundle_dir: Path) -> str:
    r = subprocess.run(["git", "config", "core.autocrlf"], cwd=bundle_dir, capture_output=True, text=True)
    if r.stdout.strip().lower() == "true":
        return ("git core.autocrlf=true converted line endings on checkout; fix with "
                "`git config core.autocrlf false && git rm -r --cached . && git reset --hard`")
    return ""


def run_preflight(*, need_claude: bool, bundle_dir: Path | None) -> None:
    osn = common.os_name()
    for tool in missing(required_tools(need_claude=need_claude)):
        cmd = install_command(tool, osn)
        if cmd is None:
            raise common.BackupError(f"{tool} is missing and no package manager was found — {manual_hint(tool)}")
        common.log(f"preflight: installing {tool}: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        if shutil.which(tool) is None:
            raise common.BackupError(f"{tool} still missing after install — {manual_hint(tool)}")
    if not secrets.default_key_file().exists():
        common.warn(f"no age key at {secrets.default_key_file()} — restore continues with placeholders only")
    if bundle_dir is not None:
        bad = manifest.verify_hashes(bundle_dir)
        if bad:
            hint = crlf_hint(bundle_dir)
            raise common.BackupError(f"bundle hash mismatch for {len(bad)} file(s): {', '.join(bad[:5])}"
                                     + (f"\n  likely cause: {hint}" if hint else ""))
