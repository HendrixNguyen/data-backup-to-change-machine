"""Restore plan: one PlanEntry per unit with an add/skip/replace verdict; printing; --only; confirm."""
from __future__ import annotations

import filecmp
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


def _differs(a: Path, b: Path) -> bool:
    if a.is_dir() and b.is_dir():
        cmp = filecmp.dircmp(a, b)
        return bool(cmp.left_only or cmp.right_only or cmp.diff_files or any(_differs(a / d, b / d) for d in cmp.common_dirs))
    if a.is_file() and b.is_file():
        return not filecmp.cmp(a, b, shallow=False)
    return True


def verdict_for(src: Path, dst: Path, *, force: bool) -> tuple[Verdict, bool]:
    if not dst.exists() and not dst.is_symlink():
        return "add", False
    d = _differs(src, dst)
    return ("replace" if force else "skip"), d


def build_content_plan(bundle_kind_dir: Path, target_dir: Path, *, bundle_rel: str, force: bool) -> list[PlanEntry]:
    from .content import list_units
    out = []
    for unit in list_units(bundle_kind_dir):
        src, dst = bundle_kind_dir / unit, target_dir / unit
        v, d = verdict_for(src, dst, force=force)
        out.append(PlanEntry(bundle_rel, unit, v, src, dst, d))
    return out


def apply_only(entries: list[PlanEntry], only: list[str]) -> list[PlanEntry]:
    if not only:
        return entries
    keys = [o.strip("/") for o in only]
    return [e for e in entries if any(e.rel == k or e.rel.startswith(k + "/") or e.kind == k for k in keys)]


def print_plan(entries: list[PlanEntry], *, notices: list[str] = ()) -> None:
    counts = {"add": 0, "skip": 0, "replace": 0}
    for e in entries:
        counts[e.verdict] += 1
        flag = "  (differs)" if e.verdict == "skip" and e.differs else ""
        print(f"  {e.verdict:<8}{e.rel}{flag}")
    print(f"\n{counts['add']} add, {counts['skip']} skip, {counts['replace']} replace")
    for n in notices:
        print(f"NOTE: {n}")


def confirm(*, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print("non-interactive and no --yes: not applying (use --dry-run to inspect, --yes to apply)")
        return False
    return input("Apply this plan? [y/N] ").strip().lower() == "y"
