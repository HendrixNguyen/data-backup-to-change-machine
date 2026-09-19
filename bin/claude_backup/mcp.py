"""MCP server extraction (Claude's ~/.claude.json + harness .mcp.json), bundle files, path remap."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from . import common, merge

Servers = dict[str, dict]
ProjectServers = dict[str, Servers]  # project path -> {name: server}


def slug(project_path: str) -> str:
    return re.sub(r"[^A-Za-z0-9._]+", "-", project_path).strip("-")


def extract_personal(claude_json: Path) -> tuple[Servers, ProjectServers]:
    data = merge.read_json(claude_json, default={}) or {}
    g = data.get("mcpServers") or {}
    projects = {p: v["mcpServers"] for p, v in (data.get("projects") or {}).items() if v.get("mcpServers")}
    return g, projects


def extract_harness(mcp_json: Path) -> Servers:
    return (merge.read_json(mcp_json, default={}) or {}).get("mcpServers") or {}


def write_projects(dst: Path, projects: ProjectServers) -> None:
    if dst.exists():
        for old in dst.glob("*.json"):
            old.unlink()
    for path, servers in projects.items():
        merge.atomic_write_json(dst / f"{slug(path)}.json", {"project": path, "mcpServers": servers})


def read_projects(src: Path) -> ProjectServers:
    out: ProjectServers = {}
    if src.is_dir():
        for f in sorted(src.glob("*.json")):
            d = merge.read_json(f)
            out[d["project"]] = d["mcpServers"]
    return out


def parse_remaps(flags: list[str]) -> list[tuple[str, str]]:
    out = []
    for f in flags:
        if "=" not in f:
            raise common.BackupError(f"--remap expects OLD=NEW, got {f!r}")
        old, new = f.split("=", 1)
        out.append((old, new))
    return out


def _remap_str(s: str, remaps: list[tuple[str, str]]) -> str:
    for old, new in remaps:
        if s.startswith(old):
            return new + s[len(old):]
    return s


def _remap_value(v, remaps):
    if isinstance(v, str):
        return _remap_str(v, remaps)
    if isinstance(v, list):
        return [_remap_value(x, remaps) for x in v]
    if isinstance(v, dict):
        return {k: _remap_value(x, remaps) for k, x in v.items()}
    return v


def remap_projects(projects: ProjectServers, remaps: list[tuple[str, str]]) -> ProjectServers:
    if not remaps:
        return copy.deepcopy(projects)
    return {_remap_str(p, remaps): _remap_value(s, remaps) for p, s in projects.items()}
