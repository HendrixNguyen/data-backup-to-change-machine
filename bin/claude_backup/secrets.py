"""Lift secrets out of config as ${VAR} placeholders; secrets.env I/O; age encrypt/decrypt; substitution."""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

from . import common

SECRET_KEY_RE = re.compile(r"token|key|secret|password", re.I)
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
ALWAYS_SECRET_CONTAINERS = ("env", "headers")


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", s.upper())


def var_name(scope: str, kind: str, owner: str | None, key: str) -> str:
    parts = [_norm(scope), _norm(kind)] + ([_norm(owner)] if owner else []) + [_norm(key)]
    return "_".join(parts)


def _is_url_with_query(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://")) and "?" in v


def placeholderize_server(scope: str, name: str, server: dict) -> tuple[dict, dict[str, str]]:
    """Return (server copy with placeholders, {VAR: real}). Rules per spec §Export step 5."""
    out = copy.deepcopy(server)
    found: dict[str, str] = {}

    def take(container: dict, key: str) -> None:
        v = container[key]
        if not isinstance(v, str):
            return
        var = var_name(scope, "mcp", name, key)
        found[var] = v
        container[key] = "${" + var + "}"

    for k in list(out.keys()):
        v = out[k]
        if k in ALWAYS_SECRET_CONTAINERS and isinstance(v, dict):
            for kk in list(v.keys()):
                take(v, kk)
        elif k == "url" and _is_url_with_query(v):
            take(out, k)
        elif SECRET_KEY_RE.search(k) and isinstance(v, str):
            take(out, k)
    return out, found


def placeholderize_settings(scope: str, settings: dict) -> tuple[dict, dict[str, str]]:
    out = copy.deepcopy(settings)
    found: dict[str, str] = {}
    for k, v in list((out.get("env") or {}).items()):
        if isinstance(v, str):
            var = var_name(scope, "settings", None, k)
            found[var] = v
            out["env"][k] = "${" + var + "}"
    return out, found


def write_env(path: Path, values: dict[str, str]) -> None:
    from . import merge
    merge.atomic_write_text(path, "".join(f"{k}={values[k]}\n" for k in sorted(values)))


def read_env(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def write_required(path: Path, values: dict[str, str]) -> None:
    from . import merge
    merge.atomic_write_text(path, "".join(f"{k}\n" for k in sorted(values)))


def substitute(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        var = m.group(1)
        if var in values:
            return values[var]
        if var not in missing:
            missing.append(var)
        return m.group(0)

    return PLACEHOLDER_RE.sub(sub, text), missing


def age_available() -> bool:
    return shutil.which("age") is not None


def age_encrypt(plain: Path, out: Path, recipient: str) -> None:
    if not age_available():
        raise common.BackupError("age is not installed; run doctor")
    common.run(["age", "-r", recipient, "-o", str(out), str(plain)])
    plain.write_bytes(b"\0" * plain.stat().st_size)  # best-effort shred
    plain.unlink()


def age_decrypt(enc: Path, key_file: Path) -> dict[str, str]:
    if not age_available():
        raise common.BackupError("age is not installed; run doctor")
    try:
        r = common.run(["age", "-d", "-i", str(key_file), str(enc)])
    except Exception as e:  # key present but wrong: hard stop (spec)
        raise common.BackupError(f"age decryption failed for {enc}: {getattr(e, 'stderr', e)}") from e
    values = {}
    for line in r.stdout.splitlines():
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            values[k] = v
    return values


def default_key_file() -> Path:
    return common.home() / ".config" / "age" / "keys.txt"


def resolve_recipient(bundle_dir: Path) -> str | None:
    import os
    env = os.environ.get("AGE_RECIPIENT")
    if env:
        return env
    f = bundle_dir / ".age-recipient"
    return f.read_text().strip() if f.exists() else None
