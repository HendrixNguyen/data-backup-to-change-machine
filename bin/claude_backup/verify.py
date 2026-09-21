"""Post-restore verification: files present, frontmatter parses, MCP names present, no stray placeholders, CLI runs."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import common, mcp, merge, secrets
from .content import list_units
from .targets import Target


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def frontmatter_ok(text: str) -> bool:
    m = re.match(r"^---\n(.*?\n)?---\n", text, re.S)   # check the matched block, not the first literal '---'
    return bool(m) and "name:" in (m.group(1) or "")


def selected(rel: str, only) -> bool:
    """Same matching rule as plan.apply_only: exact unit, a prefix path, or a whole kind."""
    if not only:
        return True
    for k in (o.replace("\\", "/").strip("/") for o in only):
        if rel == k or rel.startswith(k + "/") or rel.rsplit("/", 1)[0] == k:
            return True
    return False


def _content_checks(bundle_dir: Path, target: Target, scopes, harness_path: Path | None, only=()) -> list[Check]:
    out = []
    kinds = []
    if "personal" in scopes:
        kinds += [("personal/skills", target.skills_dir(), "skill", True), ("personal/agents", target.agents_dir(), "agent", target.has_agents),
                  ("personal/commands", target.commands_dir(), "command", target.has_commands)]
    if "harness" in scopes and target.supports_harness and harness_path:
        kinds += [("harness/skills", harness_path / ".claude" / "skills", "skill", True), ("harness/hooks", harness_path / ".claude" / "hooks", "hook", True)]
    for rel, tdir, label, enabled in kinds:
        if not enabled:
            continue
        for unit in list_units(bundle_dir / rel):
            if not selected(f"{rel}/{unit}", only):
                continue
            dst = tdir / unit
            if label == "agent":
                override = target.verify_agent(unit)
                if override is not None:
                    out.append(Check(f"{label} {rel}/{unit}", override, "" if override else "not found in target's agent store"))
                    continue
            if not dst.exists():
                out.append(Check(f"{label} {rel}/{unit}", False, f"missing at {dst}"))
            elif label == "skill":
                sk = dst / "SKILL.md"
                ok = sk.is_file() and frontmatter_ok(sk.read_text(encoding="utf-8", errors="replace"))
                out.append(Check(f"{label} {rel}/{unit}", ok, "" if ok else "SKILL.md missing or frontmatter invalid"))
            else:
                out.append(Check(f"{label} {rel}/{unit}", True))
    return out


def _mcp_checks(bundle_dir: Path, target: Target, scopes, harness_path: Path | None, only=()) -> list[Check]:
    names = set()
    if "personal" in scopes:
        names |= set((merge.read_json(bundle_dir / "personal/mcp/global.json", default={}) or {}).get("mcpServers") or {})
        for servers in mcp.read_projects(bundle_dir / "personal/mcp/projects").values():
            names |= set(servers)
    present = target.read_mcp_names()
    names = {n for n in names if selected(f"personal/mcp/{n}", only)}
    out = [Check(f"mcp {n}", n in present, "" if n in present else "not in target config") for n in sorted(names)]
    if "harness" in scopes and target.supports_harness and harness_path:
        hnames = {n for n in ((merge.read_json(bundle_dir / "harness/mcp.json", default={}) or {}).get("mcpServers") or {})
                  if selected(f"harness/mcp/{n}", only)}
        hpresent = set(mcp.extract_harness(harness_path / ".mcp.json"))
        out += [Check(f"mcp harness/{n}", n in hpresent, "" if n in hpresent else f"not in {harness_path / '.mcp.json'}") for n in sorted(hnames)]
    return out


def _placeholder_check(written_files: list[Path], missing_secrets: list[str]) -> Check:
    stray, known = set(), set()
    for f in written_files:
        if f.is_file():
            for var in secrets.PLACEHOLDER_RE.findall(f.read_text(encoding="utf-8", errors="replace")):
                (known if var in missing_secrets else stray).add(var)
    if stray:
        return Check("placeholders resolved", False, "unresolved: " + ", ".join(sorted(stray)))
    return Check("placeholders resolved", True, ("missing secrets (no key): " + ", ".join(sorted(known))) if known else "")


def _cli_checks(target: Target) -> list[Check]:
    if target.name != "claude":
        return []
    exe = shutil.which("claude")
    if not exe:
        return [Check("claude --version", False, "claude not on PATH")]
    try:
        v = common.run([exe, "--version"], check=False, timeout=60)
    except Exception as e:
        return [Check("claude --version", False, str(e))]
    out = [Check("claude --version", v.returncode == 0, v.stdout.strip() or v.stderr.strip())]
    try:
        lst = common.run([exe, "mcp", "list"], check=False, timeout=120)
    except Exception as e:
        return out + [Check("claude mcp list (informational)", True, f"skipped: {e}")]
    out.append(Check("claude mcp list (informational)", True, (lst.stdout or lst.stderr).strip()[:2000]))
    return out


def run_checks(bundle_dir: Path, target: Target, *, scopes, written_files: list[Path], missing_secrets: list[str], run_cli: bool,
               harness_path: Path | None = None, only=()) -> list[Check]:
    checks = (_content_checks(bundle_dir, target, scopes, harness_path, only)
              + _mcp_checks(bundle_dir, target, scopes, harness_path, only)
              + [_placeholder_check(written_files, missing_secrets)])
    if run_cli:
        checks += _cli_checks(target)
    return checks


def report(checks: list[Check]) -> int:
    for c in checks:
        print(f"  {'PASS' if c.ok else 'FAIL'}  {c.name}" + (f"  — {c.detail}" if c.detail else ""))
    failed = [c for c in checks if not c.ok]
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0
