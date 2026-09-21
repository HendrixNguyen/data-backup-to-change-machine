"""Kilo Code target: ~/.kilocode/skills, MCP in mcp_settings.json (Claude shape), agents → custom_modes.yaml entries."""
from __future__ import annotations

import re
from pathlib import Path

from . import Target, register
from .antigravity import ClaudeShapeJsonMixin
from .. import common, merge


def _frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)}
    return fm, m.group(2)


@register
class KiloTarget(ClaudeShapeJsonMixin, Target):
    name = "kilo"
    has_agents = True

    def __init__(self):
        self._modes: list[tuple[str, str, str]] = []

    def root(self) -> Path: return common.home() / ".kilocode"
    def skills_dir(self) -> Path: return self.root() / "skills"
    def agents_dir(self) -> Path: return self.root()          # placeholder; modes live in custom_modes.yaml
    def config(self) -> Path: return self.root() / "mcp_settings.json"
    def modes_file(self) -> Path: return self.root() / "custom_modes.yaml"

    def queue_agent(self, name: str, text: str) -> None:
        fm, body = _frontmatter(text)
        slug = fm.get("name") or name.removesuffix(".md")
        self._modes.append((slug, fm.get("description", slug), body.strip()))

    def transform_agent(self, name, text):
        self.queue_agent(name, text)
        return None   # restore_cmd treats None as "handled elsewhere"; flush_modes() writes the file

    def verify_agent(self, unit: str) -> bool | None:
        p = self.modes_file()
        slug = unit.removesuffix(".md")
        return p.exists() and f"slug: {slug}\n" in p.read_text(encoding="utf-8")

    def flush_modes(self, *, dry: bool) -> Path | None:
        if not self._modes:
            return None
        p = self.modes_file()
        existing = p.read_text(encoding="utf-8") if p.exists() else "customModes:\n"
        out = existing.rstrip("\n") + "\n"
        for slug, desc, body in self._modes:
            if f"slug: {slug}\n" in out:          # already present (or queued twice): keep one
                continue
            indented = "\n".join("      " + l for l in body.splitlines())
            out += (f"  - slug: {slug}\n    name: {slug}\n    description: {desc}\n"
                    f"    roleDefinition: |\n{indented}\n    groups: [read, edit, command]\n")
        if not dry and out != existing:
            b = merge.backup_file(p)
            if b:
                common.log(f"  backup: {b}")
            merge.atomic_write_text(p, out)
        self._modes.clear()
        return p
