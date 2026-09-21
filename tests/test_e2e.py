import json, os, shutil
from pathlib import Path
from types import SimpleNamespace
from claude_backup import export_cmd, restore_cmd, manifest


def _snapshot(root: Path) -> dict:
    """Bytes for every file, except .json files compare as parsed JSON (formatting is not part of the contract)."""
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and ".bak-" not in str(p) and "plugins" not in p.parts:
            rel = p.relative_to(root).as_posix()
            out[rel] = json.loads(p.read_text()) if p.suffix == ".json" else p.read_bytes()
    return out


def test_export_restore_roundtrip_is_byte_identical_after_secrets(fake_home, fake_harness, bundle_dir, monkeypatch):
    monkeypatch.setattr(restore_cmd.preflight, "run_preflight", lambda **kw: None)
    monkeypatch.setattr(restore_cmd.shutil, "which", lambda n: None)
    before = _snapshot(fake_home / ".claude")
    before_cj = json.loads((fake_home / ".claude.json").read_text())
    assert export_cmd.run_export(SimpleNamespace(scope="all", harness_path=fake_harness, bundle=bundle_dir, yes=True, commit_secrets=False)) == 0
    # pretend the secrets came back via age
    from claude_backup import secrets
    req = (bundle_dir / "secrets.required").read_text().split()
    real = {"PERSONAL_MCP_FIGMA_URL": "https://mcp.figma.com/mcp?key=abc", "PERSONAL_MCP_FIGMA_AUTHORIZATION": "Bearer xyz",
            "PERSONAL_MCP_CONTEXT7_CONTEXT7_API_KEY": "ctx-key", "PERSONAL_SETTINGS_MY_TOKEN": "tok-123", "PERSONAL_SETTINGS_PLAIN": "1"}
    assert set(req) == set(real)
    (bundle_dir / "secrets.env.age").write_bytes(b"x")
    monkeypatch.setattr(secrets, "default_key_file", lambda: fake_home / "k"); (fake_home / "k").write_text("k")
    monkeypatch.setattr(secrets, "age_decrypt", lambda enc, key: real)
    shutil.rmtree(fake_home / ".claude"); (fake_home / ".claude.json").unlink()
    rc = restore_cmd.run_restore(SimpleNamespace(scope="all", harness_path=fake_harness, bundle=bundle_dir, yes=True, target="claude",
                                                 only=[], dry_run=False, force=False, remap=[]))
    assert rc == 0
    after = _snapshot(fake_home / ".claude")
    assert {k: v for k, v in after.items() if not k.startswith("plugins/")} == {k: v for k, v in before.items() if not k.startswith("plugins/")}
    after_cj = json.loads((fake_home / ".claude.json").read_text())
    assert after_cj["projects"][str(fake_home / "proj-a")]["mcpServers"] == before_cj["projects"][str(fake_home / "proj-a")]["mcpServers"]


def test_posix_bundle_restores_on_any_os_with_remap(fake_home, fake_harness, bundle_dir, monkeypatch):
    """Simulates a bundle exported under /Users/old and restored under this runner's fake home."""
    monkeypatch.setattr(restore_cmd.preflight, "run_preflight", lambda **kw: None)
    monkeypatch.setattr(restore_cmd.shutil, "which", lambda n: None)
    export_cmd.run_export(SimpleNamespace(scope="personal", harness_path=None, bundle=bundle_dir, yes=True, commit_secrets=False))
    # rewrite project keys to a foreign prefix, re-manifest
    pdir = bundle_dir / "personal/mcp/projects"
    for f in pdir.glob("*.json"):
        d = json.loads(f.read_text()); d["project"] = d["project"].replace(str(fake_home), "/Users/old"); f.write_text(json.dumps(d))
    m = manifest.build(bundle_dir, scopes=("personal",), claude_version=None, symlinks={}, exec_bits={}); manifest.write(bundle_dir, m)
    shutil.rmtree(fake_home / ".claude"); (fake_home / ".claude.json").unlink()
    rc = restore_cmd.run_restore(SimpleNamespace(scope="personal", harness_path=None, bundle=bundle_dir, yes=True, target="claude",
                                                 only=[], dry_run=False, force=False, remap=[f"/Users/old={fake_home}"]))
    assert rc == 0
    cj = json.loads((fake_home / ".claude.json").read_text())
    assert str(fake_home / "proj-b") in cj["projects"]
