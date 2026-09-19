"""JSON deep-merge (local wins unless force), atomic writes, timestamped backups."""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import BackupError


def deep_merge(local: Any, bundle: Any, *, force: bool) -> Any:
    """Dicts recurse. Lists union by JSON equality (local order first). Scalars: local unless force."""
    if isinstance(local, dict) and isinstance(bundle, dict):
        out = dict(local)
        for k, v in bundle.items():
            out[k] = deep_merge(local[k], v, force=force) if k in local else v
        return out
    if isinstance(local, list) and isinstance(bundle, list):
        seen = [json.dumps(x, sort_keys=True) for x in local]
        out = list(local)
        for x in bundle:
            key = json.dumps(x, sort_keys=True)
            if key not in seen:
                out.append(x)
                seen.append(key)
        return out
    return bundle if force else local


def atomic_write_text(path: Path, text: str) -> None:
    if not isinstance(text, str):
        raise TypeError("atomic_write_text needs str")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise BackupError(f"cannot replace {path}: it is open or locked by another program — close it and retry")
                time.sleep(0.2)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dumps_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, dumps_json(data))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BackupError(f"{path} is not valid JSON: {e}") from e


def backup_file(path: Path) -> Path | None:
    """Copy <path> to <path>.bak-<YYYYMMDDTHHMMSSffffff>, disambiguated with -N on collision. Returns the backup path, or None if <path> is absent."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    bak = path.with_name(f"{path.name}.bak-{stamp}")
    n = 1
    while bak.exists():
        bak = path.with_name(f"{path.name}.bak-{stamp}-{n}")
        n += 1
    bak.write_bytes(path.read_bytes())
    return bak
