"""Copy content units (skill dirs, agent/command/hook files) for export and restore."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ExportResult:
    units: list[str] = field(default_factory=list)
    symlinks: dict[str, str] = field(default_factory=dict)   # bundle-rel -> resolved origin
    exec_bits: dict[str, bool] = field(default_factory=dict)  # bundle-rel file -> True


def list_units(src: Path) -> list[str]:
    if not src.is_dir():
        return []
    return sorted(p.name for p in src.iterdir() if not p.name.startswith(".") and not p.name.endswith(".tmp"))


def _copy_unit(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=False)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst, follow_symlinks=True)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def replace_dir(target: Path, new_tree: Path, *, keep_aside: bool) -> Path | None:
    """Spec 'directory replace': rename target aside as <name>.bak-<ts>, rename new_tree into place.
    Returns the aside path when kept, else None. Never uses os.replace on a non-empty dir."""
    aside = None
    if target.exists():
        aside = target.with_name(f"{target.name}.bak-{_ts()}")
        os.rename(target, aside)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(new_tree, target)
    if aside and not keep_aside:
        shutil.rmtree(aside)
        aside = None
    return aside


def export_kind(src: Path, dst: Path, *, bundle_rel: str) -> ExportResult:
    """Copy every unit under src into dst (fresh tree, then swap). Missing src => dst removed."""
    res = ExportResult()
    units = list_units(src)
    if not units:
        if dst.exists():
            shutil.rmtree(dst)
        return res
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent))
    for name in units:
        s = src / name
        if s.is_symlink():
            res.symlinks[f"{bundle_rel}/{name}"] = str(s.resolve())
        _copy_unit(s, tmp / name)
        res.units.append(name)
    for p in tmp.rglob("*"):
        if p.is_file() and os.name != "nt" and os.access(p, os.X_OK):
            res.exec_bits[f"{bundle_rel}/{p.relative_to(tmp).as_posix()}"] = True
    replace_dir(dst, tmp, keep_aside=False)
    return res


def apply_exec_bits(root: Path, bundle_rel_prefix: str, exec_bits: dict[str, bool]) -> None:
    if os.name == "nt":
        return
    for rel, on in exec_bits.items():
        if on and rel.startswith(bundle_rel_prefix + "/"):
            p = root / rel[len(bundle_rel_prefix) + 1:]
            if p.is_file():
                p.chmod(p.stat().st_mode | 0o111)
