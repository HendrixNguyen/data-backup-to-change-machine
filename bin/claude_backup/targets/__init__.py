"""Target adapters: where each tool keeps skills/agents/commands/MCP and how to write them."""
from __future__ import annotations

from pathlib import Path

from .. import common
from ..plan import PlanEntry

Servers = dict[str, dict]
ProjectServers = dict[str, Servers]


class Target:
    name = "base"
    supports_harness = False   # only Claude restores the harness scope (spec)
    has_agents = False
    has_commands = False

    # --- locations ---
    def skills_dir(self) -> Path: raise NotImplementedError
    def agents_dir(self) -> Path | None: return None
    def commands_dir(self) -> Path | None: return None

    # --- MCP ---
    def mcp_plan(self, global_servers: Servers, projects: ProjectServers, *, force: bool) -> list[PlanEntry]:
        raise NotImplementedError

    def write_mcp(self, global_servers: Servers, projects: ProjectServers, *, force: bool, dry: bool) -> list[Path]:
        """Returns the target files written (or that would be written, when dry)."""
        raise NotImplementedError

    def read_mcp_names(self) -> set[str]:
        """Server names currently configured in the target (for verify)."""
        raise NotImplementedError

    # --- agents / commands: default = copy the Claude markdown as-is ---
    def transform_agent(self, name: str, text: str) -> tuple[str, str] | None:
        """(filename, content) to write, or None to skip. Default: identical copy."""
        return (name, text)

    def transform_command(self, name: str, text: str) -> tuple[str, str] | None:
        return (name, text)

    def verify_agent(self, unit: str) -> bool | None:
        """None = verify checks agents_dir()/unit exists (default). A bool overrides (targets that store agents elsewhere)."""
        return None

    def flatten_projects(self, global_servers: Servers, projects: ProjectServers) -> tuple[Servers, list[str]]:
        """Non-Claude targets have one global MCP config: union project servers by name, first wins."""
        out = dict(global_servers)
        notes = []
        for proj, servers in projects.items():
            for name, cfg in servers.items():
                if name in out:
                    notes.append(f"{self.name}: '{name}' from {proj} skipped (name already present)")
                else:
                    out[name] = cfg
        return out, notes


REGISTRY: dict[str, type[Target]] = {}


def register(cls: type[Target]) -> type[Target]:
    REGISTRY[cls.name] = cls
    return cls


def get_target(name: str) -> Target:
    from . import claude, codex, antigravity, opencode, kilo  # noqa: F401  (registers)
    if name not in REGISTRY:
        raise common.BackupError(f"unknown --target {name!r}; choose from {', '.join(sorted(REGISTRY))} or all")
    return REGISTRY[name]()


def all_target_names() -> list[str]:
    get_target("claude")
    return sorted(REGISTRY)
