"""export: read ~/.claude + harness, write the neutral bundle. Read-only against sources."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import common, content, manifest, mcp, merge, secrets

INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "RTK.md")
CONTENT_KINDS = {"personal": ("skills", "agents", "commands"), "harness": ("skills", "hooks")}


def _git_dirty(bundle_dir: Path) -> bool:
    if not (bundle_dir / ".git").exists():
        return False
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=bundle_dir, capture_output=True, text=True)
    except FileNotFoundError:
        return False   # no git binary: nothing we can check, and the export itself does not need it
    return bool(r.stdout.strip())


def _claude_version() -> str | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        return common.run([exe, "--version"], timeout=30).stdout.strip()
    except Exception:
        return None


def _export_settings(scope: str, src: Path, dst: Path, found: dict[str, str]) -> None:
    data = merge.read_json(src)
    if data is None:
        if dst.exists():
            dst.unlink()
        return
    out, f = secrets.placeholderize_settings(scope, data)
    found.update(f)
    merge.atomic_write_json(dst, out)


def _export_servers(scope: str, servers: mcp.Servers, found: dict[str, str]) -> mcp.Servers:
    out = {}
    for name, cfg in servers.items():
        out[name], f = secrets.placeholderize_server(scope, name, cfg)
        found.update(f)
    return out


def _reduce_plugins(installed: Path) -> list[dict]:
    data = merge.read_json(installed, default={}) or {}
    out = []
    for key, entries in (data.get("plugins") or {}).items():
        name, _, market = key.partition("@")
        for e in entries:
            out.append({"name": name, "marketplace": market, "version": e.get("version")})
    return sorted(out, key=lambda d: (d["name"], d["marketplace"]))


def export_personal(bundle_dir: Path, found: dict[str, str], symlinks: dict, exec_bits: dict) -> None:
    roots = common.personal_roots()
    scope_dir = bundle_dir / "personal"
    for kind in CONTENT_KINDS["personal"]:
        r = content.export_kind(roots.claude_dir / kind, scope_dir / kind, bundle_rel=f"personal/{kind}")
        symlinks.update(r.symlinks); exec_bits.update(r.exec_bits)
        common.log(f"  personal/{kind}: {len(r.units)} unit(s)")
    g, projects = mcp.extract_personal(roots.claude_json)
    merge.atomic_write_json(scope_dir / "mcp" / "global.json", {"mcpServers": _export_servers("personal", g, found)})
    mcp.write_projects(scope_dir / "mcp" / "projects", {p: _export_servers("personal", s, found) for p, s in projects.items()})
    common.log(f"  personal/mcp: {len(g)} global, {len(projects)} project(s)")
    _export_settings("personal", roots.claude_dir / "settings.json", scope_dir / "settings.json", found)
    _export_settings("personal", roots.claude_dir / "settings.local.json", scope_dir / "settings.local.json", found)
    inst = scope_dir / "instructions"
    inst.mkdir(parents=True, exist_ok=True)
    for name in INSTRUCTION_FILES:
        src = roots.claude_dir / name
        if src.exists():
            shutil.copy2(src, inst / name)
        elif (inst / name).exists():
            (inst / name).unlink()
    merge.atomic_write_json(scope_dir / "plugins.json", _reduce_plugins(roots.claude_dir / "plugins" / "installed_plugins.json"))


def export_harness(bundle_dir: Path, harness: Path, found: dict[str, str], symlinks: dict, exec_bits: dict) -> None:
    scope_dir = bundle_dir / "harness"
    for kind in CONTENT_KINDS["harness"]:
        r = content.export_kind(harness / ".claude" / kind, scope_dir / kind, bundle_rel=f"harness/{kind}")
        symlinks.update(r.symlinks); exec_bits.update(r.exec_bits)
        common.log(f"  harness/{kind}: {len(r.units)} unit(s)")
    _export_settings("harness", harness / ".claude" / "settings.json", scope_dir / "settings.json", found)
    servers = mcp.extract_harness(harness / ".mcp.json")
    merge.atomic_write_json(scope_dir / "mcp.json", {"mcpServers": _export_servers("harness", servers, found)})
    common.log(f"  harness/mcp: {len(servers)} server(s)")


def run_export(args) -> int:
    try:
        bundle_dir = common.resolve_bundle_dir(args.bundle)
        for stale in content.find_stale_artifacts(bundle_dir):
            common.warn(f"stale artifact from an interrupted run (safe to delete): {stale}")
        scopes = common.scopes_for(args.scope)
        if not args.yes and _git_dirty(bundle_dir):
            raise common.BackupError(f"{bundle_dir} has uncommitted changes — commit/stash them or pass --yes")
        bundle_dir.mkdir(parents=True, exist_ok=True)
        found: dict[str, str] = {}
        symlinks: dict[str, str] = {}
        exec_bits: dict[str, bool] = {}
        common.log(f"Exporting {', '.join(scopes)} → {bundle_dir}")
        if "personal" in scopes:
            export_personal(bundle_dir, found, symlinks, exec_bits)
        if "harness" in scopes:
            harness = common.resolve_harness_path(args.harness_path, interactive=not args.yes)
            export_harness(bundle_dir, harness, found, symlinks, exec_bits)
        secrets.write_required(bundle_dir / "secrets.required", found)
        recipient = secrets.resolve_recipient(bundle_dir)
        if found and recipient and secrets.age_available():
            plain = bundle_dir / "secrets.env"
            secrets.write_env(plain, found)
            secrets.age_encrypt(plain, bundle_dir / "secrets.env.age", recipient)
            common.log(f"  secrets: {len(found)} value(s) encrypted → secrets.env.age" + ("" if args.commit_secrets else " (gitignored)"))
            if args.commit_secrets:
                _unignore_secrets(bundle_dir)
        elif found:
            common.warn(f"{len(found)} secret value(s) were replaced by placeholders and NOT saved "
                        "(no age recipient: set AGE_RECIPIENT or write .age-recipient, and install age). See secrets.required.")
        manifest.write(bundle_dir, manifest.build(bundle_dir, scopes=scopes, claude_version=_claude_version(),
                                                  symlinks=symlinks, exec_bits=exec_bits))
        common.log("Done. Review with `git status`, then commit and push.")
        return 0
    except common.BackupError as e:
        common.log(f"error: {e}")
        return 1


def _unignore_secrets(bundle_dir: Path) -> None:
    gi = bundle_dir / ".gitignore"
    if gi.exists():
        lines = [l for l in gi.read_text().splitlines() if l.strip() != "secrets.env.age"]
        merge.atomic_write_text(gi, "\n".join(lines) + "\n")
