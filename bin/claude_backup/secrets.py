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
_URL_QUERY_RE = re.compile(r"^[a-z][a-z0-9+.-]*://\S*\?", re.I)
_FLAG_VALUE_RE = re.compile(r"^(--?)([^=\s]+)=(.*)$", re.S)
_FLAG_RE = re.compile(r"^--?([^=\s]+)$")
_LOOKS_LIKE_FLAG_RE = re.compile(r"^--?[A-Za-z]")

_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Where a placeholder came from: (scope, kind, owner, key). Two emissions sharing it are the same
# config slot (e.g. successive elements of one list), not a real name collision.
Source = tuple[str, str, "str | None", str]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", s.upper())


def var_name(scope: str, kind: str, owner: str | None, key: str) -> str:
    parts = [_norm(scope), _norm(kind)] + ([_norm(owner)] if owner else []) + [_norm(key)]
    return "_".join(parts)


def _is_url_with_query(v: Any) -> bool:
    return isinstance(v, str) and _URL_QUERY_RE.search(v) is not None


def _has_userinfo(v: Any) -> bool:
    return isinstance(v, str) and _USERINFO_URL_RE.search(v) is not None


def _put(found: dict[str, str], owners: dict, var: str, value: str, key: str, source: Source) -> str:
    """Record value under var; on a same-name/different-value clash use var_2, var_3, … (first free)."""
    cand = var
    n = 1
    while cand in found:
        if found[cand] == value:
            return cand  # same secret reached twice: one VAR, no warning
        n += 1
        cand = f"{var}_{n}"
    prev = owners.get(var)
    if cand != var and (prev is None or prev[0] != source):  # same slot twice (a list) is not a collision
        common.warn(
            f"variable name collision: '{prev[1] if prev else var}' and '{key}' both normalise to {var}; "
            f"using {cand} for '{key}'"
        )
    found[cand] = value
    owners[cand] = (source, key)
    return cand


def _walk(obj: Any, *, scope: str, kind: str, owner: str | None, found: dict[str, str], owners: dict,
          always: bool = False) -> dict[str, str]:
    """Placeholderize `obj` in place; return {VAR: real} for the values produced by THIS call.

    Walks the whole object: every dict at any depth, plus lists of strings (argv-style flags).
    `found`/`owners` may be shared across calls so variable names stay unique across a whole export.
    """
    produced: dict[str, str] = {}

    def emit(key: str, value: str) -> str:
        var = _put(found, owners, var_name(scope, kind, owner, key), value, key, (scope, kind, owner, key))
        produced[var] = value
        return "${" + var + "}"

    def walk_dict(d: dict, always: bool) -> None:
        for k in sorted(d):  # sorted so collision suffixes are deterministic run to run
            v = d[k]
            # a container reached through a secret-looking key is secret whole: apiKeys[], credentials{}, auth{}
            secret_container = always or k in ALWAYS_SECRET_CONTAINERS or bool(SECRET_KEY_RE.search(k))
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
        if (m and SECRET_KEY_RE.search(m.group(1)) and i + 1 < len(lst) and isinstance(lst[i + 1], str)
                and not _LOOKS_LIKE_FLAG_RE.match(lst[i + 1])):  # in '--no-auth --port 3000', --port is not a value
            lst[i + 1] = emit(f"ARG_{m.group(1)}", lst[i + 1])
            return i + 1  # consume the value so it is not re-examined as a flag
        return i

    if isinstance(obj, dict):
        walk_dict(obj, always)
    elif isinstance(obj, list):
        walk_list(obj, always, kind)
    return produced


def placeholderize_server(scope: str, name: str, server: dict, *, found: dict[str, str] | None = None,
                          owners: dict | None = None) -> tuple[dict, dict[str, str]]:
    """Return (server copy with placeholders, {VAR: real}). Rules per spec §Export step 5.

    Pass one `found`/`owners` pair for a whole export to keep variable names unique across servers
    and scopes; the returned dict still holds only the values this call produced.
    """
    out = copy.deepcopy(server)
    produced = _walk(out, scope=scope, kind="mcp", owner=name,
                     found=found if found is not None else {}, owners=owners if owners is not None else {})
    return out, produced


def placeholderize_settings(scope: str, settings: dict, *, found: dict[str, str] | None = None,
                            owners: dict | None = None) -> tuple[dict, dict[str, str]]:
    """Same walk as a server, minus the owner segment: every `env` block (top-level or nested) is a
    secret container, and elsewhere the key/URL rules apply — so `apiKeyHelper` is lifted while
    `model`, `permissions` and `hooks` commands are left alone."""
    out = copy.deepcopy(settings)
    produced = _walk(out, scope=scope, kind="settings", owner=None,
                     found=found if found is not None else {}, owners=owners if owners is not None else {})
    return out, produced


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
        if not _ENV_KEY_RE.fullmatch(k):
            raise common.BackupError(f"invalid secrets.env key (not a shell-safe identifier): {k!r}")
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


# Last line of defence: if the redactor missed something, this catches the well-known token shapes
# before they reach a public repo. Names are for the operator; the matched text is never printed.
LEAK_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github-token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("gitlab-token", re.compile(r"glpat-[A-Za-z0-9_-]{16,}")),
    ("slack-token", re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}")),
    ("aws-access-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"Bearer [A-Za-z0-9._~+/=-]{16,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    # A literal password next to its key, in JSON or as a shell/env assignment. `${...}` and obvious
    # placeholders are excluded so a correctly placeholderised bundle stays clean.
    ("inline-password", re.compile(r"""["']?pass(?:word|wd)?["']?\s*[:=]\s*["'](?!\$\{)(?!\*)[^"']{4,}["']""", re.I)),
)
_SCAN_SUFFIXES = (".json", ".md", ".toml", ".sh", ".txt", ".yaml", ".yml")
_SCAN_SKIP_NAMES = ("bundle.json", "secrets.required")


ALLOWLIST = ".leak-allow"


def load_leak_allowlist(bundle_dir: Path) -> list[tuple[str, str]]:
    """Read `.leak-allow`: one `<path-substring> <pattern-name>  # why` per line.

    An allowlist entry is a deliberate, reviewable decision that a match is not a credential —
    a Firebase Web API key, say, which is a public client identifier. Keeping the refusal as the
    default and the exceptions in a committed file beats loosening the patterns for everyone.
    """
    f = bundle_dir / ALLOWLIST
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def allowed(path: Path, pattern: str, allowlist: list[tuple[str, str]]) -> bool:
    return any(frag in path.as_posix() and pat == pattern for frag, pat in allowlist)


def scan_for_leaks(root: Path) -> list[tuple[Path, int, str]]:
    """Grep an exported tree for live-looking credentials. Returns (file, line number, pattern name)."""
    hits: list[tuple[Path, int, str]] = []
    if not root.is_dir():
        return hits
    for p in sorted(root.rglob("*")):
        if p.name in _SCAN_SKIP_NAMES or p.name.endswith(".age") or p.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, rx in LEAK_PATTERNS:
                if rx.search(line):
                    hits.append((p, lineno, name))
                    break  # one report per line is enough to send the operator to it
    return hits


def default_key_file() -> Path:
    return common.home() / ".config" / "age" / "keys.txt"


def resolve_recipient(bundle_dir: Path) -> str | None:
    import os
    env = os.environ.get("AGE_RECIPIENT")
    if env:
        return env
    f = bundle_dir / ".age-recipient"
    return f.read_text().strip() if f.exists() else None
