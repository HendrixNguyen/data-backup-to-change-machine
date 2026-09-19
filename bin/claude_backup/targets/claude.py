"""Claude Code target: ~/.claude/{skills,agents,commands}, MCP in ~/.claude.json (global + per project)."""
from __future__ import annotations

from pathlib import Path

from . import Target, register, Servers, ProjectServers
from .. import common, merge
from ..plan import PlanEntry


@register
class ClaudeTarget(Target):
    name = "claude"
    supports_harness = True
    has_agents = True
    has_commands = True

    def root(self) -> Path:
        return common.personal_roots().claude_dir

    def skills_dir(self) -> Path: return self.root() / "skills"
    def agents_dir(self) -> Path: return self.root() / "agents"
    def commands_dir(self) -> Path: return self.root() / "commands"

    def _claude_json(self) -> Path:
        return common.personal_roots().claude_json

    def _merged(self, global_servers: Servers, projects: ProjectServers, *, force: bool) -> tuple[dict, list[PlanEntry]]:
        data = merge.read_json(self._claude_json(), default={}) or {}
        entries: list[PlanEntry] = []
        cur = data.setdefault("mcpServers", {})
        for name, cfg in global_servers.items():
            v = "add" if name not in cur else ("replace" if force else "skip")
            entries.append(PlanEntry("personal/mcp", f"global/{name}", v, None, self._claude_json(), name in cur and cur[name] != cfg))
            if v != "skip":
                cur[name] = cfg
        projs = data.setdefault("projects", {})
        for proj, servers in projects.items():
            pcur = projs.setdefault(proj, {}).setdefault("mcpServers", {})
            for name, cfg in servers.items():
                v = "add" if name not in pcur else ("replace" if force else "skip")
                entries.append(PlanEntry("personal/mcp", f"{proj}/{name}", v, None, self._claude_json(), name in pcur and pcur[name] != cfg))
                if v != "skip":
                    pcur[name] = cfg
        return data, entries

    def mcp_plan(self, global_servers, projects, *, force):
        return self._merged(global_servers, projects, force=force)[1]

    def write_mcp(self, global_servers, projects, *, force, dry):
        data, entries = self._merged(global_servers, projects, force=force)
        if not dry and any(e.verdict != "skip" for e in entries):
            bak = merge.backup_file(self._claude_json())
            if bak:
                common.log(f"  backup: {bak}")
            merge.atomic_write_json(self._claude_json(), data)
        return [self._claude_json()]

    def read_mcp_names(self) -> set[str]:
        data = merge.read_json(self._claude_json(), default={}) or {}
        names = set(data.get("mcpServers") or {})
        for p in (data.get("projects") or {}).values():
            names |= set(p.get("mcpServers") or {})
        return names
