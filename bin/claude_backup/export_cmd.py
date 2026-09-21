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


def _export_settings(scope: str, src: Path, dst: Path, found: dict[str, str], owners: dict) -> None:
    data = merge.read_json(src)
    if data is None:
        if dst.exists():
            dst.unlink()
        return
    out, _ = secrets.placeholderize_settings(scope, data, found=found, owners=owners)
    merge.atomic_write_json(dst, out)


def _export_servers(scope: str, servers: mcp.Servers, found: dict[str, str], owners: dict) -> mcp.Servers:
    """One `found`/`owners` pair for the whole export, so two servers whose keys normalise alike
    get distinct variables instead of silently overwriting each other."""
    out = {}
    for name, cfg in servers.items():
        out[name], _ = secrets.placeholderize_server(scope, name, cfg, found=found, owners=owners)
    return out


def _reduce_plugins(installed: Path) -> list[dict]:
    data = merge.read_json(installed, default={}) or {}
    out = []
    for key, entries in (data.get("plugins") or {}).items():
        name, _, market = key.partition("@")
        for e in entries:
            out.append({"name": name, "marketplace": market, "version": e.get("version")})
    return sorted(out, key=lambda d: (d["name"], d["marketplace"]))


def export_personal(bundle_dir: Path, found: dict[str, str], owners: dict, symlinks: dict, exec_bits: dict) -> None:
    roots = common.personal_roots()
    scope_dir = bundle_dir / "personal"
    for kind in CONTENT_KINDS["personal"]:
        r = content.export_kind(roots.claude_dir / kind, scope_dir / kind, bundle_rel=f"personal/{kind}")
        symlinks.update(r.symlinks); exec_bits.update(r.exec_bits)
        common.log(f"  personal/{kind}: {len(r.units)} unit(s)")
    g, projects = mcp.extract_personal(roots.claude_json)
    merge.atomic_write_json(scope_dir / "mcp" / "global.json", {"mcpServers": _export_servers("personal", g, found, owners)})
    mcp.write_projects(scope_dir / "mcp" / "projects", {p: _export_servers("personal", s, found, owners) for p, s in projects.items()})
    common.log(f"  personal/mcp: {len(g)} global, {len(projects)} project(s)")
    _export_settings("personal", roots.claude_dir / "settings.json", scope_dir / "settings.json", found, owners)
    _export_settings("personal", roots.claude_dir / "settings.local.json", scope_dir / "settings.local.json", found, owners)
    inst = scope_dir / "instructions"
    inst.mkdir(parents=True, exist_ok=True)
    for name in INSTRUCTION_FILES:
        src = roots.claude_dir / name
        if src.exists():
            shutil.copy2(src, inst / name)
        elif (inst / name).exists():
            (inst / name).unlink()
    merge.atomic_write_json(scope_dir / "plugins.json", _reduce_plugins(roots.claude_dir / "plugins" / "installed_plugins.json"))


def export_harness(bundle_dir: Path, harness: Path, found: dict[str, str], owners: dict, symlinks: dict, exec_bits: dict) -> None:
    scope_dir = bundle_dir / "harness"
    for kind in CONTENT_KINDS["harness"]:
        r = content.export_kind(harness / ".claude" / kind, scope_dir / kind, bundle_rel=f"harness/{kind}")
        symlinks.update(r.symlinks); exec_bits.update(r.exec_bits)
        common.log(f"  harness/{kind}: {len(r.units)} unit(s)")
    _export_settings("harness", harness / ".claude" / "settings.json", scope_dir / "settings.json", found, owners)
    servers = mcp.extract_harness(harness / ".mcp.json")
    merge.atomic_write_json(scope_dir / "mcp.json", {"mcpServers": _export_servers("harness", servers, found, owners)})
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
        owners: dict = {}
        symlinks: dict[str, str] = {}
        exec_bits: dict[str, bool] = {}
        wsl = common.wsl_notice()
        if wsl:
            common.warn(wsl)
        common.log(f"Exporting {', '.join(scopes)} → {bundle_dir}")
        if "personal" in scopes:
            export_personal(bundle_dir, found, owners, symlinks, exec_bits)
        if "harness" in scopes:
            harness = common.resolve_harness_path(args.harness_path, interactive=not args.yes)
            export_harness(bundle_dir, harness, found, owners, symlinks, exec_bits)
        secrets.write_required(bundle_dir / "secrets.required", found)
        recipient = secrets.resolve_recipient(bundle_dir)
        if found and recipient and secrets.age_available():
            _encrypt_secrets(bundle_dir, found, recipient, commit_secrets=args.commit_secrets)
        elif found:
            common.warn(f"{len(found)} secret value(s) were replaced by placeholders and NOT saved — "
                        + _why_no_encryption(recipient) + ". See secrets.required.")
        manifest.write(bundle_dir, manifest.build(bundle_dir, scopes=scopes, claude_version=_claude_version(),
                                                  symlinks=symlinks, exec_bits=exec_bits))
        _refuse_on_leak(bundle_dir)
        common.log("Done. Review with `git status`, then commit and push.")
        return 0
    except common.BackupError as e:
        common.log(f"error: {e}")
        return 1
    except OSError as e:                       # unreadable source, full disk, bad permissions
        common.log(f"error: {e}")
        return 1


def _why_no_encryption(recipient: str | None) -> str:
    if not recipient:
        return "no age recipient (set AGE_RECIPIENT or write .age-recipient)"
    return "age is not installed (run doctor)"


def _encrypt_secrets(bundle_dir: Path, found: dict[str, str], recipient: str, *, commit_secrets: bool) -> None:
    """Write, encrypt, and make sure the plaintext never survives a failure."""
    plain = bundle_dir / "secrets.env"
    enc = bundle_dir / "secrets.env.age"
    try:
        secrets.write_env(plain, found)
        secrets.age_encrypt(plain, enc, recipient)
    except Exception as e:
        if plain.exists():                     # age_encrypt shreds on success; do it here on failure too
            plain.write_bytes(b"\0" * plain.stat().st_size)
            plain.unlink()
        if enc.exists():
            enc.unlink()                       # a partial ciphertext is worse than none
        raise common.BackupError(f"encrypting secrets failed: {e}") from e
    common.log(f"  secrets: {len(found)} value(s) encrypted → secrets.env.age"
               + ("" if commit_secrets else " (gitignored)"))
    if commit_secrets:
        _unignore_secrets(bundle_dir)


def _refuse_on_leak(bundle_dir: Path) -> None:
    """Last line of defence: never let a raw credential reach a bundle that is meant to be committable."""
    allowlist = secrets.load_leak_allowlist(bundle_dir)
    hits = []
    for scope in ("personal", "harness"):
        hits += [h for h in secrets.scan_for_leaks(bundle_dir / scope)
                 if not secrets.allowed(h[0], h[2], allowlist)]
    if hits:
        where = "; ".join(f"{p}:{line} ({pattern})" for p, line, pattern in hits[:10])
        raise common.BackupError(
            f"refusing to finish: {len(hits)} possible raw secret(s) in the bundle — {where}"
            f"\n  if a match is genuinely not a credential, record why in {bundle_dir / secrets.ALLOWLIST}"
            f" as: <path-substring> <pattern-name>  # reason")


def _unignore_secrets(bundle_dir: Path) -> None:
    gi = bundle_dir / ".gitignore"
    if gi.exists():
        lines = [l for l in gi.read_text().splitlines() if l.strip() != "secrets.env.age"]
        merge.atomic_write_text(gi, "\n".join(lines) + "\n")
