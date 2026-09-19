"""Restore plan: one PlanEntry per unit with an add/skip/replace verdict; printing; --only; confirm."""
from __future__ import annotations

import filecmp
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from . import common
from .content import list_units

Verdict = Literal["add", "skip", "replace"]


@dataclass
class PlanEntry:
    kind: str            # bundle-relative kind dir, e.g. "personal/skills", "personal/mcp", "harness/settings"
    unit: str            # skill name, agent file, server name, "settings.json"
    verdict: Verdict
    src: Path | None     # bundle path (None for synthesized entries)
    dst: Path | None     # target path
    differs: bool        # existing target content differs from bundle

    @property
    def rel(self) -> str:
        return f"{self.kind}/{self.unit}"


def _walk_entries(root: Path) -> set[str]:
    """Every entry (dirs, files, symlinks) under root as posix relative paths. No ignores: a
    difference anywhere under a unit — including __pycache__ or a dotfile — is a real difference."""
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        for name in dirnames + filenames:
            out.add((d / name).relative_to(root).as_posix())
    return out


def _node_differs(a: Path, b: Path) -> bool:
    """One entry that exists on both sides. Directories compare equal here — their contents are
    covered by the caller's entry-set walk."""
    a_link, b_link = a.is_symlink(), b.is_symlink()
    if a_link or b_link:
        return not (a_link and b_link) or os.readlink(a) != os.readlink(b)
    a_dir, b_dir = a.is_dir(), b.is_dir()
    if a_dir != b_dir:
        return True
    if a_dir:
        return False
    return not filecmp.cmp(a, b, shallow=False)


def _differs(a: Path, b: Path) -> bool:
    """Content comparison, never shallow: same size + mtime is not "same". Anything unreadable or
    unstat-able counts as different, so restore never claims a unit is identical without proof."""
    try:
        if a.is_symlink() or b.is_symlink():
            return _node_differs(a, b)
        if a.is_dir() and b.is_dir():
            entries = _walk_entries(a)
            if entries != _walk_entries(b):
                return True
            return any(_node_differs(a / r, b / r) for r in sorted(entries))
        if a.is_file() and b.is_file():
            return not filecmp.cmp(a, b, shallow=False)
        return True
    except OSError:
        return True


def verdict_for(src: Path, dst: Path, *, force: bool) -> tuple[Verdict, bool]:
    if not dst.exists() and not dst.is_symlink():
        return "add", False
    d = _differs(src, dst)
    return ("replace" if (force and d) else "skip"), d


def build_content_plan(bundle_kind_dir: Path, target_dir: Path, *, bundle_rel: str, force: bool) -> list[PlanEntry]:
    out = []
    for unit in list_units(bundle_kind_dir):
        src, dst = bundle_kind_dir / unit, target_dir / unit
        v, d = verdict_for(src, dst, force=force)
        out.append(PlanEntry(bundle_rel, unit, v, src, dst, d))
    return out


def apply_only(entries: list[PlanEntry], only: list[str]) -> list[PlanEntry]:
    """Filter to the --only keys. A key that matches nothing is a typo, not an empty plan."""
    if not only:
        return entries
    keys = [o.replace("\\", "/").strip("/") for o in only]
    hit = {k: False for k in keys}
    kept = []
    for e in entries:
        matched = [k for k in keys if e.rel == k or e.rel.startswith(k + "/") or e.kind == k]
        for k in matched:
            hit[k] = True
        if matched:
            kept.append(e)
    unmatched = [k for k in keys if not hit[k]]
    if unmatched:
        raise common.BackupError("--only matched nothing: " + ", ".join(unmatched))
    return kept


def print_plan(entries: list[PlanEntry], *, notices: Sequence[str] = ()) -> None:
    counts = Counter(e.verdict for e in entries)
    for e in entries:
        flag = "  (differs)" if e.verdict == "skip" and e.differs else ""
        print(f"  {e.verdict:<8}{e.rel}{flag}")
    print(f"\n{counts['add']} add, {counts['skip']} skip, {counts['replace']} replace")
    for n in notices:
        print(f"NOTE: {n}")


def confirm(*, yes: bool) -> bool:
    if yes:
        return True
    if sys.stdin is None or not sys.stdin.isatty():
        common.log("non-interactive and no --yes: not applying (use --dry-run to inspect, --yes to apply)")
        return False
    try:
        return input("Apply this plan? [y/N] ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        print()
        return False
