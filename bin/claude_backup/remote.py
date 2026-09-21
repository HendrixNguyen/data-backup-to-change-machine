"""Is the bundle's git remote readable by the whole world?

The bundle is designed to be committed. That is safe in a private repo and a disclosure in a
public one: even with every secret lifted out into a placeholder, what remains is a map of your
skills, your project paths and your internal hostnames.

Visibility is decided by asking the host anonymously. A public repo is, by definition, one an
unauthenticated request can read, so no token and no extra dependency are needed.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import common

TIMEOUT = 5.0
PUBLIC, PRIVATE, UNKNOWN = "public", "private", "unknown"

# git@host:owner/repo.git | https://host/owner/repo(.git) | ssh://git@host/owner/repo.git
_SCP = re.compile(r"^(?:ssh://)?(?:[^@/]+@)?(?P<host>[^:/]+)(?::(?P<port>\d+))?[:/](?P<path>.+?)(?:\.git)?/?$")
_URL = re.compile(r"^https?://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.+?)(?:\.git)?/?$")


def origin_url(bundle_dir: Path) -> str | None:
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=bundle_dir,
                           capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    url = r.stdout.strip()
    return url if r.returncode == 0 and url else None


def parse_remote(url: str) -> tuple[str, str] | None:
    """(host, 'owner/repo') — the path may be nested, as GitLab groups are."""
    for rx in (_URL, _SCP):
        m = rx.match(url)
        if m:
            path = m.group("path").strip("/")
            if "/" in path:
                return m.group("host").lower(), path
    return None


def _probe(url: str) -> tuple[int | None, dict | None]:
    """Anonymous GET. Returns (status, body). A 404/403 is an answer — the world cannot read it —
    while a network failure is not, and must not be mistaken for one."""
    req = urllib.request.Request(url, headers={"User-Agent": "claude-backup"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def visibility(host: str, path: str) -> str:
    """PUBLIC only when an anonymous read succeeds. Anything else is not a green light."""
    if "github" in host:
        status, data = _probe(f"https://api.github.com/repos/{path}")
        if status == 200 and data is not None:
            return PRIVATE if data.get("private") else PUBLIC
        return PRIVATE if status in (401, 403, 404) else UNKNOWN
    if "gitlab" in host:
        status, data = _probe(f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(path, safe='')}")
        if status == 200 and data is not None:
            return PUBLIC if data.get("visibility") == "public" else PRIVATE
        return PRIVATE if status in (401, 403, 404) else UNKNOWN
    return UNKNOWN


def check(bundle_dir: Path) -> tuple[str, str | None]:
    """(verdict, human description of the remote)."""
    url = origin_url(bundle_dir)
    if not url:
        return UNKNOWN, None
    parsed = parse_remote(url)
    if not parsed:
        return UNKNOWN, url
    host, path = parsed
    return visibility(host, path), f"{host}/{path}"


def guard(bundle_dir: Path, *, allow_public: bool) -> None:
    """Refuse to fill a bundle that is wired to a world-readable remote."""
    verdict, where = check(bundle_dir)
    if verdict == PUBLIC and not allow_public:
        raise common.BackupError(
            f"refusing to export: {where} is a PUBLIC repository.\n"
            "  Committing a bundle there publishes your skills, project paths and internal\n"
            "  hostnames, even though the secrets themselves are placeholders.\n"
            "  Make it private, or pass --allow-public if that is genuinely what you want.")
    if verdict == PUBLIC:
        common.warn(f"{where} is PUBLIC and --allow-public was given: anything committed here is world-readable")
    elif verdict == UNKNOWN and where:
        common.warn(f"could not determine whether {where} is public — check before committing the bundle")
