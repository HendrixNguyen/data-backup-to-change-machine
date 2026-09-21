"""OpenCode target: ~/.config/opencode/{skills,agents,commands}, MCP in opencode.json (JSONC read, JSON write).

Confirmed against https://opencode.ai/docs/config/, /mcp-servers/, /agents/, /commands/, /skills/ (2026-09-21):
- Global config: ~/.config/opencode/opencode.json (JSON or JSONC; no separate Windows path is documented,
  so this follows the same home()-relative convention as the codex/claude targets).
- MCP ("mcp" key): local/stdio -> {"type": "local", "command": [...], "environment": {...}, "enabled": true};
  remote/http -> {"type": "remote", "url": "...", "headers": {...}, "enabled": true}. Matches this adapter as-is.
- Skills: OpenCode does have a skills concept (unlike Codex) - ~/.config/opencode/skills/<name>/SKILL.md is
  one of its discovery roots, so skills_dir() returns a normal path rather than raising.
- Agents/commands: the docs' canonical examples use the plural directories agents/ and commands/ (the
  source's own glob also accepts the singular agent/command aliases, but we write the documented form).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import Target, register
from .. import common, merge
from ..plan import PlanEntry

_JSONC_COMMENT = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)


def strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments that are not inside a string literal (read side only)."""
    return _JSONC_COMMENT.sub(lambda m: m.group(1) or "", text)


def to_opencode_server(cfg: dict) -> dict:
    if cfg.get("url"):
        out = {"type": "remote", "url": cfg["url"]}
        if cfg.get("headers"):
            out["headers"] = dict(cfg["headers"])
    else:
        out = {"type": "local", "command": [cfg.get("command", "")] + list(cfg.get("args") or [])}
        if cfg.get("env"):
            out["environment"] = dict(cfg["env"])
    out["enabled"] = True
    return out


def _frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, m.group(2)


@register
class OpenCodeTarget(Target):
    name = "opencode"
    has_agents = True
    has_commands = True

    def root(self) -> Path: return common.home() / ".config" / "opencode"
    def skills_dir(self) -> Path: return self.root() / "skills"
    def agents_dir(self) -> Path: return self.root() / "agents"
    def commands_dir(self) -> Path: return self.root() / "commands"
    def config(self) -> Path: return self.root() / "opencode.json"

    def transform_agent(self, name, text):
        fm, body = _frontmatter(text)
        # Claude model aliases (sonnet/opus) are not OpenCode provider/model ids, so `model:` is dropped on purpose.
        lines = ["---", f"description: {fm.get('description', name.removesuffix('.md'))}", "mode: subagent"]
        return name, "\n".join(lines) + "\n---\n" + body

    def _load(self) -> dict:
        p = self.config()
        if not p.exists():
            return {}
        try:
            return json.loads(strip_jsonc(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise common.BackupError(f"{p} is not valid JSON/JSONC: {e}")

    def mcp_plan(self, global_servers, projects, *, force):
        servers, _ = self.flatten_projects(global_servers, projects)
        cur = self._load().get("mcp", {}) or {}
        return [PlanEntry("personal/mcp", n, "add" if n not in cur else ("replace" if force else "skip"), None, self.config(),
                          n in cur and cur[n] != to_opencode_server(c)) for n, c in servers.items()]

    def write_mcp(self, global_servers, projects, *, force, dry):
        servers, _ = self.flatten_projects(global_servers, projects)
        data = self._load()
        cur = data.setdefault("mcp", {})
        changed = False
        for n, c in servers.items():
            if n in cur and not force:
                continue
            cur[n] = to_opencode_server(c)
            changed = True
        if changed and not dry:
            b = merge.backup_file(self.config())
            if b:
                common.log(f"  backup: {b} (comments in opencode.json are not preserved)")
            merge.atomic_write_json(self.config(), data)
        return [self.config()]

    def read_mcp_names(self) -> set[str]:
        return set(self._load().get("mcp", {}) or {})
