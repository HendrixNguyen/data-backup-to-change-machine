"""Lift secrets out of config as ${VAR} placeholders; secrets.env I/O; age encrypt/decrypt; substitution."""
from __future__ import annotations

import copy
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import common

# Substring match on purpose: over-redaction is the safe direction for a public bundle.
SECRET_KEY_RE = re.compile(r"token|key|secret|password|auth|credential|bearer", re.I)
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
ALWAYS_SECRET_CONTAINERS = ("env", "headers")

_USERINFO_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@", re.I)
_FLAG_VALUE_RE = re.compile(r"^(--?)([^=\s]+)=(.*)$", re.S)
_FLAG_RE = re.compile(r"^--?([^=\s]+)$")


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", s.upper())


def var_name(scope: str, kind: str, owner: str | None, key: str) -> str:
    parts = [_norm(scope), _norm(kind)] + ([_norm(owner)] if owner else []) + [_norm(key)]
    return "_".join(parts)


def _is_url_with_query(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://")) and "?" in v


def _has_userinfo(v: Any) -> bool:
    return isinstance(v, str) and _USERINFO_URL_RE.search(v) is not None


def _put(found: dict[str, str], owners: dict[str, str], var: str, value: str, key: str) -> str:
    """Record value under var; on a same-name/different-value clash use var_2, var_3, … (first free)."""
    cand = var
    n = 1
    while cand in found:
        if found[cand] == value:
            return cand  # same secret reached twice: one VAR, no warning
        n += 1
        cand = f"{var}_{n}"
    if cand != var:
        common.warn(
            f"variable name collision: '{owners.get(var, var)}' and '{key}' both normalise to {var}; "
            f"using {cand} for '{key}'"
        )
    found[cand] = value
    owners[cand] = key
    return cand


def placeholderize_server(scope: str, name: str, server: dict) -> tuple[dict, dict[str, str]]:
    """Return (server copy with placeholders, {VAR: real}). Rules per spec §Export step 5.

    Walks the whole object: every dict at any depth, plus lists of strings (argv-style flags).
    """
    out = copy.deepcopy(server)
    found: dict[str, str] = {}
    owners: dict[str, str] = {}

    def emit(key: str, value: str) -> str:
        return "${" + _put(found, owners, var_name(scope, "mcp", name, key), value, key) + "}"

    def walk_dict(d: dict, always: bool) -> None:
        for k in list(d.keys()):
            v = d[k]
            secret_container = always or k in ALWAYS_SECRET_CONTAINERS
            if isinstance(v, dict):
                walk_dict(v, secret_container)
            elif isinstance(v, list):
                walk_list(v, secret_container, k)
            elif isinstance(v, str):
                if always or SECRET_KEY_RE.search(k) or _is_url_with_query(v) or _has_userinfo(v):
                    d[k] = emit(k, v)

    def walk_list(lst: list, always: bool, parent_key: str) -> None:
        i = 0
        while i < len(lst):
            item = lst[i]
            if isinstance(item, dict):
                walk_dict(item, always)
            elif isinstance(item, list):
                walk_list(item, always, parent_key)
            elif isinstance(item, str):
                if always:
                    lst[i] = emit(parent_key, item)
                else:
                    i = _take_flag(lst, i, item)
            i += 1

    def _take_flag(lst: list, i: int, item: str) -> int:
        """Handle '--flag=value' (value only) and '--flag' + next item. Returns the new index."""
        m = _FLAG_VALUE_RE.match(item)
        if m and SECRET_KEY_RE.search(m.group(2)):
            lst[i] = m.group(1) + m.group(2) + "=" + emit(f"ARG_{m.group(2)}", m.group(3))
            return i
        m = _FLAG_RE.match(item)
        if m and SECRET_KEY_RE.search(m.group(1)) and i + 1 < len(lst) and isinstance(lst[i + 1], str):
            lst[i + 1] = emit(f"ARG_{m.group(1)}", lst[i + 1])
            return i + 1  # consume the value so it is not re-examined as a flag
        return i

    if isinstance(out, dict):
        walk_dict(out, False)
    return out, found


def placeholderize_settings(scope: str, settings: dict) -> tuple[dict, dict[str, str]]:
    out = copy.deepcopy(settings)
    found: dict[str, str] = {}
    owners: dict[str, str] = {}
    for k, v in list((out.get("env") or {}).items()):
        if isinstance(v, str):
            var = _put(found, owners, var_name(scope, "settings", None, k), v, k)
            out["env"][k] = "${" + var + "}"
    return out, found


def _escape_env(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def _unescape_env(v: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            if nxt in ("n", "r", "\\"):
                out.append({"n": "\n", "r": "\r", "\\": "\\"}[nxt])
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _parse_env_text(text: str) -> dict[str, str]:
    """Parse KEY=escaped-value lines (secrets.env on disk, or `age -d` stdout)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = _unescape_env(v)
    return out


def write_env(path: Path, values: dict[str, str]) -> None:
    from . import merge
    for k in values:
        if "=" in k or "\n" in k or "\r" in k:
            raise common.BackupError(f"invalid secrets.env key (contains '=' or a newline): {k!r}")
    merge.atomic_write_text(path, "".join(f"{k}={_escape_env(values[k])}\n" for k in sorted(values)))


def read_env(path: Path) -> dict[str, str]:
    return _parse_env_text(path.read_text(encoding="utf-8"))


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
    except subprocess.CalledProcessError as e:  # key present but wrong: hard stop (spec)
        raise common.BackupError(f"age decryption failed for {enc}: {e.stderr}") from e
    except FileNotFoundError as e:
        raise common.BackupError(f"{enc} not found") from e
    return _parse_env_text(r.stdout)


def default_key_file() -> Path:
    return common.home() / ".config" / "age" / "keys.txt"


def resolve_recipient(bundle_dir: Path) -> str | None:
    import os
    env = os.environ.get("AGE_RECIPIENT")
    if env:
        return env
    f = bundle_dir / ".age-recipient"
    return f.read_text().strip() if f.exists() else None
