"""restore: preflight → plan → confirm → apply (content, MCP, settings, secrets, plugins) → verify. Also doctor."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from . import common, content, manifest, mcp, merge, plan as planmod, preflight, secrets, verify
from .plan import PlanEntry
from .targets import Target, get_target, all_target_names

INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", "RTK.md")


class Session:
    """State for one restore run against one target."""

    def __init__(self, args, target: Target, bundle_dir: Path, harness_path: Path | None, values: dict[str, str], missing_key: bool):
        self.args, self.target, self.bundle_dir, self.harness_path = args, target, bundle_dir, harness_path
        self.values, self.missing_key = values, missing_key
        self.written: list[Path] = []
        self.backups: list[Path] = []
        self.missing_secrets: list[str] = []
        self.notices: list[str] = []
        self.scopes = tuple(s for s in common.scopes_for(args.scope) if s == "personal" or target.supports_harness)
        if "harness" in common.scopes_for(args.scope) and not target.supports_harness:
            self.notices.append(f"harness scope is Claude-only — skipped for --target {target.name}")

    # ---------- content ----------
    def content_kinds(self) -> list[tuple[str, Path, str]]:
        """(bundle_rel, target_dir, kind) for every content kind this target takes."""
        out = []
        if "personal" in self.scopes:
            out.append(("personal/skills", self.target.skills_dir(), "skills"))
            if self.target.has_agents and self.target.agents_dir():
                out.append(("personal/agents", self.target.agents_dir(), "agents"))
            if self.target.has_commands and self.target.commands_dir():
                out.append(("personal/commands", self.target.commands_dir(), "commands"))
        if "harness" in self.scopes and self.harness_path:
            out.append(("harness/skills", self.harness_path / ".claude" / "skills", "skills"))
            out.append(("harness/hooks", self.harness_path / ".claude" / "hooks", "hooks"))
        return out

    def _text_with_secrets(self, src: Path) -> str:
        text = src.read_text(encoding="utf-8", errors="replace")
        text, missing = secrets.substitute(text, self.values)
        for m in missing:
            if m not in self.missing_secrets:
                self.missing_secrets.append(m)
        return text

    def apply_content_entry(self, e: PlanEntry, kind: str, m: dict) -> None:
        if e.verdict == "skip" or self.args.dry_run:
            return
        src, dst = e.src, e.dst
        if kind in ("agents", "commands") and src.is_file():
            fn = self.target.transform_agent if kind == "agents" else self.target.transform_command
            res = fn(src.name, self._text_with_secrets(src))
            if res is None:
                if not hasattr(self.target, "flush_modes"):
                    self.notices.append(f"{self.target.name}: {e.rel} skipped (no equivalent)")
                return
            name, text = res
            dst = dst.with_name(name)
            if e.verdict == "replace":
                b = merge.backup_file(dst)
                b and self.backups.append(b)
            merge.atomic_write_text(dst, text)
            self.written.append(dst)
            return
        origin = m.get("symlinks", {}).get(e.rel)
        if origin and Path(origin).exists() and os.name != "nt":
            if dst.exists() or dst.is_symlink():
                aside = content.aside_path(dst)
                os.rename(dst, aside)
                self.backups.append(aside)
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(origin, dst, target_is_directory=src.is_dir())
            self.written.append(dst)
            return
        if origin and os.name == "nt":
            self.notices.append(f"{e.rel}: was a symlink to {origin}; copied instead (Windows)")
        if src.is_dir():
            dst.parent.mkdir(parents=True, exist_ok=True)          # same filesystem as dst, so the rename below is not cross-device
            tmp = Path(tempfile.mkdtemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent))
            shutil.rmtree(tmp)
            shutil.copytree(src, tmp)
            aside = content.replace_dir(dst, tmp, keep_aside=True)
            if aside:
                self.backups.append(aside)
            content.apply_exec_bits(dst, e.rel, m.get("files", {}) and {k: v.get("exec", False) for k, v in m["files"].items()})
            self.written += [p for p in dst.rglob("*") if p.is_file()]
        else:
            if e.verdict == "replace":
                b = merge.backup_file(dst)
                b and self.backups.append(b)
            if b"${" in src.read_bytes():
                merge.atomic_write_text(dst, self._text_with_secrets(src))
            else:                                                  # byte-for-byte (spec): no re-encoding, no newline changes
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            if m.get("files", {}).get(e.rel, {}).get("exec") and os.name != "nt":
                dst.chmod(dst.stat().st_mode | 0o111)
            self.written.append(dst)

    # ---------- MCP ----------
    def mcp_inputs(self):
        g, projects = {}, {}
        if "personal" in self.scopes:
            g = (merge.read_json(self.bundle_dir / "personal/mcp/global.json", default={}) or {}).get("mcpServers") or {}
            projects = mcp.read_projects(self.bundle_dir / "personal/mcp/projects")
            projects = mcp.remap_projects(projects, mcp.parse_remaps(self.args.remap))
            missing_projects = [p for p in projects if not Path(p).exists()]
            if missing_projects and not self.args.remap:
                self.notices.append("project paths not present on this machine (use --remap OLD=NEW): " + ", ".join(missing_projects[:5]))
        g = self._subst_obj(g)
        projects = self._subst_obj(projects)
        if self.target.name != "claude":
            g, notes = self.target.flatten_projects(g, projects)
            projects = {}
            self.notices += notes
        return g, projects

    def _subst_obj(self, obj):
        """Substitute placeholders per string leaf (never through a JSON dump — values may contain quotes/backslashes)."""
        if isinstance(obj, str):
            out, missing = secrets.substitute(obj, self.values)
            for m in missing:
                if m not in self.missing_secrets:
                    self.missing_secrets.append(m)
            return out
        if isinstance(obj, list):
            return [self._subst_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self._subst_obj(v) for k, v in obj.items()}
        return obj

    # ---------- harness .mcp.json (Claude only; merged into <harness>/.mcp.json, never ~/.claude.json) ----------
    def harness_mcp(self) -> tuple[list[PlanEntry], dict | None]:
        """Plan only. The merge happens in _apply, after --only has pruned the entries — building the
        merged document here would write servers the user filtered out."""
        if "harness" not in self.scopes or not self.target.supports_harness or not self.harness_path:
            return [], None
        bundle = self._subst_obj((merge.read_json(self.bundle_dir / "harness/mcp.json", default={}) or {}).get("mcpServers") or {})
        dst = self.harness_path / ".mcp.json"
        cur = (merge.read_json(dst, default={}) or {}).get("mcpServers") or {}
        entries = []
        for n, c in bundle.items():
            v = "add" if n not in cur else ("replace" if self.args.force else "skip")
            entries.append(PlanEntry("harness/mcp", n, v, None, dst, n in cur and cur[n] != c))
        return entries, bundle

    # ---------- settings / instructions ----------
    def settings_entries(self) -> list[tuple[PlanEntry, dict]]:
        out = []
        pairs = []
        if "personal" in self.scopes and self.target.name == "claude":
            root = common.personal_roots().claude_dir
            pairs += [("personal", "settings.json", root / "settings.json"), ("personal", "settings.local.json", root / "settings.local.json")]
        if "harness" in self.scopes and self.target.supports_harness and self.harness_path:
            pairs += [("harness", "settings.json", self.harness_path / ".claude" / "settings.json")]
        for scope, name, dst in pairs:
            src = self.bundle_dir / scope / name
            if not src.exists():
                continue
            bundle_data = self._subst_obj(merge.read_json(src))
            local = merge.read_json(dst)
            if local is None:
                v, merged = "add", bundle_data
            else:
                merged = merge.deep_merge(local, bundle_data, force=self.args.force)
                v = "skip" if merged == local else ("replace" if self.args.force else "add")
            out.append((PlanEntry(f"{scope}/settings", name, v, src, dst, local is not None and local != bundle_data), merged))
        return out

    def instruction_entries(self) -> list[PlanEntry]:
        if "personal" not in self.scopes or self.target.name != "claude":
            return []
        root = common.personal_roots().claude_dir
        out = []
        for name in INSTRUCTION_FILES:
            src = self.bundle_dir / "personal/instructions" / name
            if src.exists():
                v, d = planmod.verdict_for(src, root / name, force=self.args.force)
                out.append(PlanEntry("personal/instructions", name, v, src, root / name, d))
        return out


def _load_secret_values(bundle_dir: Path) -> tuple[dict[str, str], bool]:
    enc = bundle_dir / "secrets.env.age"
    key = secrets.default_key_file()
    if enc.exists() and key.exists():
        return secrets.age_decrypt(enc, key), False
    return {}, enc.exists()


def restore_one(args, target: Target, bundle_dir: Path, harness_path: Path | None) -> int:
    m = manifest.read(bundle_dir)
    values, missing_key = _load_secret_values(bundle_dir)
    s = Session(args, target, bundle_dir, harness_path, values, missing_key)
    if missing_key:
        s.notices.append("secrets.env.age present but no age key — placeholders left in place")
    if common.os_name() == "windows" and (bundle_dir / "harness/hooks").exists() and "harness" in s.scopes:
        s.notices.append("bundle contains POSIX hook scripts; on Windows they need a POSIX shell (Git Bash/WSL) to run")

    # plan
    entries: list[tuple[PlanEntry, str]] = []
    for rel, tdir, kind in s.content_kinds():
        for e in planmod.build_content_plan(bundle_dir / rel, tdir, bundle_rel=rel, force=args.force):
            entries.append((e, kind))
    for e in s.instruction_entries():
        entries.append((e, "instructions"))
    g, projects = s.mcp_inputs()
    mcp_entries = target.mcp_plan(g, projects, force=args.force)
    hmcp_entries, hmcp_data = s.harness_mcp()
    settings = s.settings_entries()
    all_entries = planmod.apply_only([e for e, _ in entries] + mcp_entries + hmcp_entries + [e for e, _ in settings], args.only)
    keep = {id(e) for e in all_entries}
    print(f"\nRestore plan — target {target.name}, scopes {', '.join(s.scopes) or '(none)'}:")
    planmod.print_plan(all_entries, notices=s.notices)
    if args.dry_run:
        return 0
    if not planmod.confirm(yes=args.yes):
        return 1

    # apply (wrapped so an abort still reports what was written — spec §Error handling)
    try:
        _apply(s, entries, keep, m, mcp_entries, g, projects, hmcp_entries, hmcp_data, settings, target, args)
    except Exception as e:
        print(f"\nerror: restore aborted in {type(e).__name__}: {e}")
        print("files written before the abort:")
        for p in s.written:
            print(f"  {p}")
        print("backups:")
        for p in s.backups:
            print(f"  {p}")
        return 1
    return _finish(s, bundle_dir, target, harness_path, args)


def _apply(s, entries, keep, m, mcp_entries, g, projects, hmcp_entries, hmcp_data, settings, target, args):
    for e, kind in entries:
        if id(e) in keep:
            s.apply_content_entry(e, kind, m)
    if hasattr(target, "flush_modes"):
        p = target.flush_modes(dry=False)
        if p:
            s.written.append(p)
    kept_mcp = [e for e in mcp_entries if id(e) in keep and e.verdict != "skip"]
    if kept_mcp:
        # --only on MCP is per server: restrict what write_mcp sees to the kept names
        names = {e.unit.rsplit("/", 1)[-1] for e in kept_mcp}
        g2 = {n: c for n, c in g.items() if n in names}
        p2 = {p: {n: c for n, c in srv.items() if n in names} for p, srv in projects.items()}
        p2 = {p: srv for p, srv in p2.items() if srv}
        s.written += target.write_mcp(g2, p2, force=args.force, dry=False)
    kept_harness = [e for e in hmcp_entries if id(e) in keep and e.verdict != "skip"]
    if kept_harness and hmcp_data is not None:
        dst = kept_harness[0].dst
        data = merge.read_json(dst, default={}) or {}       # re-read: the plan may be minutes old
        cur = data.setdefault("mcpServers", {})
        for e in kept_harness:
            cur[e.unit] = hmcp_data[e.unit]
        b = merge.backup_file(dst)
        b and s.backups.append(b)
        merge.atomic_write_json(dst, data)
        s.written.append(dst)
    for e, merged in settings:
        if id(e) in keep and e.verdict != "skip":
            b = merge.backup_file(e.dst)
            b and s.backups.append(b)
            merge.atomic_write_json(e.dst, merged)
            s.written.append(e.dst)


def _finish(s, bundle_dir, target, harness_path, args) -> int:
    plugins = merge.read_json(bundle_dir / "personal/plugins.json", default=[]) or []
    if plugins and "personal" in s.scopes and target.name == "claude":
        print("\nPlugins (run these yourself):")
        for p in plugins:
            print(f"  claude plugin install {p['name']}@{p['marketplace']}")
    if s.backups:
        print("\nBackups written (rollback = move back):")
        for b in s.backups:
            print(f"  {b}")

    # verify
    print("\nVerify:")
    checks = verify.run_checks(bundle_dir, target, scopes=s.scopes, written_files=s.written, missing_secrets=s.missing_secrets,
                               run_cli=(target.name == "claude" and shutil.which("claude") is not None), harness_path=harness_path,
                               only=args.only)
    return verify.report(checks)


def _harness_path_if_needed(args, scopes) -> Path | None:
    if "harness" not in scopes:
        return None
    return common.resolve_harness_path(args.harness_path, interactive=not args.yes)


def run_restore(args) -> int:
    try:
        bundle_dir = common.resolve_bundle_dir(args.bundle)
        names = all_target_names() if args.target == "all" else [args.target]
        targets = [get_target(n) for n in names]
        preflight.run_preflight(need_claude=any(t.name == "claude" for t in targets), bundle_dir=bundle_dir,
                                yes=args.yes, dry_run=args.dry_run)   # a dry run must never install anything
        harness_path = _harness_path_if_needed(args, common.scopes_for(args.scope)) if any(t.supports_harness for t in targets) else None
        rc = 0
        for t in targets:
            rc = max(rc, restore_one(args, t, bundle_dir, harness_path))
        return rc
    except common.BackupError as e:
        common.log(f"error: {e}")
        return 1


def run_doctor(args) -> int:
    try:
        bundle_dir = common.resolve_bundle_dir(args.bundle)
        target = get_target(args.target)
        preflight.run_preflight(need_claude=(target.name == "claude"),
                                bundle_dir=bundle_dir if (bundle_dir / manifest.MANIFEST).exists() else None,
                                yes=args.yes)
        print("preflight: ok")
        if (bundle_dir / manifest.MANIFEST).exists():
            scopes = common.scopes_for(args.scope)
            hp = None
            if "harness" in scopes and target.supports_harness:
                try:
                    hp = common.resolve_harness_path(args.harness_path, interactive=not args.yes)
                except common.BackupError:
                    scopes = ("personal",)
            checks = verify.run_checks(bundle_dir, target, scopes=scopes, written_files=[], missing_secrets=[], run_cli=(target.name == "claude"), harness_path=hp)
            return verify.report(checks)
        return 0
    except common.BackupError as e:
        common.log(f"error: {e}")
        return 1
