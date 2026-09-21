"""Antigravity target: ~/.gemini/antigravity/{skills,global_workflows}, MCP JSON in Claude shape. No subagents."""
from __future__ import annotations

from pathlib import Path

from . import Target, register
from .. import common, merge
from ..plan import PlanEntry


class ClaudeShapeJsonMixin:
    """MCP config that is {"mcpServers": {...}} in one global JSON file (Antigravity, Kilo)."""

    def config(self) -> Path: raise NotImplementedError

    def _servers(self) -> dict:
        return (merge.read_json(self.config(), default={}) or {}).get("mcpServers", {}) or {}

    def mcp_plan(self, global_servers, projects, *, force):
        servers, _ = self.flatten_projects(global_servers, projects)
        cur = self._servers()
        return [PlanEntry("personal/mcp", n, "add" if n not in cur else ("replace" if force else "skip"), None, self.config(),
                          n in cur and cur[n] != c) for n, c in servers.items()]

    def write_mcp(self, global_servers, projects, *, force, dry):
        servers, _ = self.flatten_projects(global_servers, projects)
        data = merge.read_json(self.config(), default={}) or {}
        cur = data.setdefault("mcpServers", {})
        changed = False
        for n, c in servers.items():
            if n in cur and not force:
                continue
            cur[n] = c
            changed = True
        if changed and not dry:
            b = merge.backup_file(self.config())
            if b:
                common.log(f"  backup: {b}")
            merge.atomic_write_json(self.config(), data)
        return [self.config()]

    def read_mcp_names(self) -> set[str]:
        return set(self._servers())


@register
class AntigravityTarget(ClaudeShapeJsonMixin, Target):
    name = "antigravity"
    has_commands = True

    def root(self) -> Path: return common.home() / ".gemini" / "antigravity"
    def skills_dir(self) -> Path: return self.root() / "skills"
    def commands_dir(self) -> Path: return self.root() / "global_workflows"
    def config(self) -> Path: return self.root() / "mcp_config.json"

    def transform_command(self, name, text):
        if text.startswith("---\n"):
            return name, text
        return name, f"---\ndescription: {name.removesuffix('.md')}\n---\n{text}"
