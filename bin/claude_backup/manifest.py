"""bundle.json: what was exported, from where, with per-file sha256, symlink origins and executable bits."""
from __future__ import annotations

import hashlib
import platform
from datetime import datetime, timezone
from pathlib import Path

from . import common, merge

MANIFEST = "bundle.json"
DATA_DIRS = ("personal", "harness")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(bundle_dir: Path, p: Path) -> str:
    return p.relative_to(bundle_dir).as_posix()


def iter_data_files(bundle_dir: Path):
    for d in DATA_DIRS:
        root = bundle_dir / d
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    yield p


def build(bundle_dir: Path, *, scopes: tuple[str, ...], claude_version: str | None,
          symlinks: dict[str, str], exec_bits: dict[str, bool]) -> dict:
    files = {}
    for p in iter_data_files(bundle_dir):
        r = rel(bundle_dir, p)
        files[r] = {"sha256": sha256_file(p)}
        if exec_bits.get(r):
            files[r]["exec"] = True
    return {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(),
        "os": common.os_name(),
        "claude_version": claude_version,
        "scopes": list(scopes),
        "files": files,
        "symlinks": symlinks,
    }


def write(bundle_dir: Path, m: dict) -> None:
    merge.atomic_write_json(bundle_dir / MANIFEST, m)


def read(bundle_dir: Path) -> dict:
    m = merge.read_json(bundle_dir / MANIFEST)
    if not m:
        raise common.BackupError(f"no {MANIFEST} in {bundle_dir} — run export first or check the clone")
    return m


def verify_hashes(bundle_dir: Path) -> list[str]:
    """Return bundle-relative paths whose content differs from the manifest (or are missing)."""
    m = read(bundle_dir)
    bad = []
    for r, meta in m["files"].items():
        p = bundle_dir / r
        if not p.is_file() or sha256_file(p) != meta["sha256"]:
            bad.append(r)
    return bad
