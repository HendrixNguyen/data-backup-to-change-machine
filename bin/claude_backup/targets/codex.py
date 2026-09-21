"""Codex CLI target: ~/.codex/skills, MCP as [mcp_servers.<name>] tables in ~/.codex/config.toml. No agents/commands."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from . import Target, register
from .. import common, merge, toml_min
from ..plan import PlanEntry


def to_codex_server(cfg: dict) -> dict:
    if cfg.get("url"):
        out = {"url": cfg["url"]}
        if cfg.get("headers"):
            out["http_headers"] = dict(cfg["headers"])
        return out
    out = {"command": cfg.get("command", "")}
    if cfg.get("args"):
        out["args"] = list(cfg["args"])
    if cfg.get("env"):
        out["env"] = dict(cfg["env"])
    return out


@register
class CodexTarget(Target):
    name = "codex"

    def root(self) -> Path: return common.home() / ".codex"
    def skills_dir(self) -> Path: return self.root() / "skills"
    def config(self) -> Path: return self.root() / "config.toml"

    def _existing(self) -> dict:
        p = self.config()
        if not p.exists():
            return {}
        try:
            return tomllib.loads(p.read_text(encoding="utf-8")).get("mcp_servers", {}) or {}
        except tomllib.TOMLDecodeError as e:
            raise common.BackupError(f"{p} is not valid TOML: {e}")

    def mcp_plan(self, global_servers, projects, *, force):
        servers, _ = self.flatten_projects(global_servers, projects)
        cur = self._existing()
        return [PlanEntry("personal/mcp", n, "add" if n not in cur else ("replace" if force else "skip"), None, self.config(),
                          n in cur and cur[n] != to_codex_server(c)) for n, c in servers.items()]

    def write_mcp(self, global_servers, projects, *, force, dry):
        servers, _ = self.flatten_projects(global_servers, projects)
        p = self.config()
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        cur = self._existing()
        changed = False
        for name, cfg in servers.items():
            block = toml_min.dumps_table(f"mcp_servers.{name}", to_codex_server(cfg))
            if name in cur:
                if not force:
                    continue
                span = toml_min.find_table_span(text, f"mcp_servers.{name}")
                if span:
                    text = text[:span[0]] + block + "\n" + text[span[1]:]
                else:  # inline / dotted form: drop that line, append a standard table
                    text = "\n".join(l for l in text.splitlines()
                                     if not re.match(r"\s*mcp_servers\." + re.escape(name) + r"\s*=", l)) + "\n"
                    text = text.rstrip("\n") + "\n\n" + block
            else:
                text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
            changed = True
        if changed and not dry:
            b = merge.backup_file(p)
            if b:
                common.log(f"  backup: {b}")
            merge.atomic_write_text(p, text if text.endswith("\n") else text + "\n")
        return [p]

    def read_mcp_names(self) -> set[str]:
        return set(self._existing())
