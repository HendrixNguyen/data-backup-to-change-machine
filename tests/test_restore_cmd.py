import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_backup import export_cmd, restore_cmd


def eargs(**kw):
    b = dict(scope="all", harness_path=None, bundle=None, yes=True, commit_secrets=False); b.update(kw); return SimpleNamespace(**b)


def rargs(**kw):
    b = dict(scope="all", harness_path=None, bundle=None, yes=True, target="claude", only=[], dry_run=False, force=False, remap=[]); b.update(kw); return SimpleNamespace(**b)


@pytest.fixture
def exported(fake_home, fake_harness, bundle_dir, monkeypatch):
    assert export_cmd.run_export(eargs(harness_path=fake_harness, bundle=bundle_dir)) == 0
    # simulate a new machine: wipe ~/.claude and ~/.claude.json, keep the harness clone but drop one skill
    import shutil
    shutil.rmtree(fake_home / ".claude"); (fake_home / ".claude.json").unlink()
    shutil.rmtree(fake_harness / ".claude" / "skills" / "load-context")
    monkeypatch.setattr(restore_cmd.preflight, "run_preflight", lambda **kw: None)   # tools are unit-tested separately
    monkeypatch.setattr(restore_cmd.shutil, "which", lambda n: None)                    # never spawn the real `claude` CLI in tests
    return bundle_dir


def test_dry_run_writes_nothing(exported, fake_home, fake_harness, capsys):
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, dry_run=True))
    assert rc == 0
    assert not (fake_home / ".claude").exists()
    out = capsys.readouterr().out
    assert "add     personal/skills/real-skill" in out and "add     harness/skills/load-context" in out


def test_restore_into_empty_home(exported, fake_home, fake_harness):
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness))
    assert rc == 0
    assert (fake_home / ".claude/skills/real-skill/SKILL.md").exists()
    assert (fake_home / ".claude/skills/linked-skill/SKILL.md").exists()
    assert (fake_home / ".claude/agents/the-validator.md").exists()
    assert (fake_home / ".claude/commands/review-code.md").exists()
    assert (fake_home / ".claude/CLAUDE.md").exists()
    assert (fake_harness / ".claude/skills/load-context/SKILL.md").exists()
    cj = json.loads((fake_home / ".claude.json").read_text())
    assert "context7" in cj["projects"][str(fake_home / "proj-b")]["mcpServers"]
    assert str(fake_harness) not in cj["projects"]                                       # harness MCP goes to <harness>/.mcp.json, not ~/.claude.json
    assert "playwright" in json.loads((fake_harness / ".mcp.json").read_text())["mcpServers"]
    settings = json.loads((fake_home / ".claude/settings.json").read_text())
    assert settings["env"]["MY_TOKEN"] == "${PERSONAL_SETTINGS_MY_TOKEN}"   # no key => placeholder stays, listed


def test_restore_recreates_symlink_when_origin_exists(exported, fake_home, fake_harness):
    restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness))
    p = fake_home / ".claude/skills/linked-skill"
    assert p.is_symlink() and p.resolve() == (fake_home / ".agents/skills/linked-skill").resolve()


def test_merge_skips_existing_force_replaces(exported, fake_home, fake_harness):
    (fake_home / ".claude/skills/real-skill").mkdir(parents=True)
    (fake_home / ".claude/skills/real-skill/SKILL.md").write_text("LOCAL")
    restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal"))
    assert (fake_home / ".claude/skills/real-skill/SKILL.md").read_text() == "LOCAL"
    restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal", force=True, only=["personal/skills/real-skill"]))
    assert (fake_home / ".claude/skills/real-skill/SKILL.md").read_text().startswith("---")
    assert list((fake_home / ".claude/skills").glob("real-skill.bak-*"))   # restore keeps the aside dir


def test_remap_applies_to_project_paths(exported, fake_home, fake_harness):
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal", remap=[f"{fake_home}=/new/home"]))
    assert rc == 0
    cj = json.loads((fake_home / ".claude.json").read_text())
    assert "/new/home/proj-b" in cj["projects"]


def test_secrets_substituted_when_key_present(exported, fake_home, fake_harness, monkeypatch):
    monkeypatch.setattr(restore_cmd.secrets, "default_key_file", lambda: fake_home / "k")
    (fake_home / "k").write_text("fake")
    monkeypatch.setattr(restore_cmd.secrets, "age_decrypt", lambda enc, key: {"PERSONAL_SETTINGS_MY_TOKEN": "tok-123", "PERSONAL_MCP_CONTEXT7_CONTEXT7_API_KEY": "ctx-key"})
    (exported / "secrets.env.age").write_bytes(b"x")
    restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal"))
    assert json.loads((fake_home / ".claude/settings.json").read_text())["env"]["MY_TOKEN"] == "tok-123"
    cj = json.loads((fake_home / ".claude.json").read_text())
    assert cj["projects"][str(fake_home / "proj-b")]["mcpServers"]["context7"]["env"]["CONTEXT7_API_KEY"] == "ctx-key"


def test_plugins_are_printed_not_installed(exported, fake_home, fake_harness, capsys):
    restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal"))
    assert "claude plugin install feature-dev@claude-code-plugins" in capsys.readouterr().out


def test_harness_scope_skipped_for_non_claude_target(exported, fake_home, fake_harness, capsys):
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, target="codex", dry_run=True))
    assert rc == 0 and "harness scope is Claude-only" in capsys.readouterr().out


def test_harness_mcp_on_fresh_clone_is_skip(exported, fake_home, fake_harness, capsys):
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="harness", dry_run=True))
    assert rc == 0 and "skip    harness/mcp/playwright" in capsys.readouterr().out


def test_windows_path_in_env_secret_survives(exported, fake_home, fake_harness, monkeypatch):
    monkeypatch.setattr(restore_cmd.secrets, "default_key_file", lambda: fake_home / "k"); (fake_home / "k").write_text("k")
    monkeypatch.setattr(restore_cmd.secrets, "age_decrypt", lambda enc, key: {"PERSONAL_SETTINGS_PLAIN": 'C:\\Users\\h "q"\nx'})
    (exported / "secrets.env.age").write_bytes(b"x")
    assert restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal")) == 0
    assert json.loads((fake_home / ".claude/settings.json").read_text())["env"]["PLAIN"] == 'C:\\Users\\h "q"\nx'


def test_dry_run_never_installs_tools(exported, fake_home, fake_harness, monkeypatch):
    """A dry run inspects; it must not change the machine. Guards the preflight wiring."""
    from claude_backup import preflight
    seen = {}
    monkeypatch.setattr(restore_cmd.preflight, "run_preflight",
                        lambda **kw: seen.update(kw))
    restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, dry_run=True))
    assert seen.get("dry_run") is True


def test_only_does_not_write_unselected_harness_servers(exported, fake_home, fake_harness):
    """--only prunes the plan; it must prune the writes too. A second bundle server that the user
    filtered out must not reach <harness>/.mcp.json."""
    hm = exported / "harness" / "mcp.json"
    data = json.loads(hm.read_text())
    data["mcpServers"]["serverB"] = {"command": "b"}
    hm.write_text(json.dumps(data))
    from claude_backup import manifest
    manifest.write(exported, manifest.build(exported, scopes=("personal", "harness"), claude_version=None,
                                            symlinks=manifest.read(exported).get("symlinks", {}), exec_bits={}))
    (fake_harness / ".mcp.json").write_text(json.dumps({"mcpServers": {}}))
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="harness",
                                       only=["harness/mcp/playwright"]))
    assert rc == 0
    written = json.loads((fake_harness / ".mcp.json").read_text())["mcpServers"]
    assert "playwright" in written and "serverB" not in written


def test_only_verify_ignores_units_outside_the_filter(exported, fake_home, fake_harness):
    """A --only restore must not fail verify over units it deliberately skipped."""
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal",
                                       only=["personal/skills/real-skill"]))
    assert rc == 0
    assert (fake_home / ".claude/skills/real-skill/SKILL.md").exists()
    assert not (fake_home / ".claude/skills/linked-skill").exists()   # excluded, and not a failure


def test_only_global_mcp_does_not_touch_a_same_named_project_server(exported, fake_home, fake_harness):
    """--only carries (scope, name), not just name. A global 'dup' must not overwrite project-a's 'dup'."""
    gf = exported / "personal" / "mcp" / "global.json"
    gf.write_text(json.dumps({"mcpServers": {"dup": {"command": "from-global"}}}))
    pdir = exported / "personal" / "mcp" / "projects"
    pa = str(fake_home / "proj-a")
    for f in pdir.glob("*.json"):
        d = json.loads(f.read_text())
        if d["project"] == pa:
            d["mcpServers"]["dup"] = {"command": "from-project"}
            f.write_text(json.dumps(d))
    from claude_backup import manifest
    manifest.write(exported, manifest.build(exported, scopes=("personal", "harness"), claude_version=None,
                                            symlinks=manifest.read(exported).get("symlinks", {}), exec_bits={}))
    (fake_home / ".claude.json").write_text(json.dumps(
        {"mcpServers": {}, "projects": {pa: {"mcpServers": {"dup": {"command": "LOCAL-KEEP"}}}}}))
    rc = restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, scope="personal",
                                       only=["personal/mcp/global/dup"], force=True))
    assert rc == 0
    cj = json.loads((fake_home / ".claude.json").read_text())
    assert cj["mcpServers"]["dup"] == {"command": "from-global"}
    assert cj["projects"][pa]["mcpServers"]["dup"] == {"command": "LOCAL-KEEP"}   # never selected


def test_force_restore_is_idempotent_for_mcp_and_symlinks(exported, fake_home, fake_harness):
    """A second --force run over an unchanged bundle must not rewrite or pile up .bak copies."""
    assert restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, force=True)) == 0
    baks = lambda: len(list((fake_home / ".claude" / "skills").glob("*.bak-*"))) + \
                   len(list(fake_home.glob(".claude.json.bak-*")))
    before = baks()
    assert restore_cmd.run_restore(rargs(bundle=exported, harness_path=fake_harness, force=True)) == 0
    assert baks() == before
    p = fake_home / ".claude/skills/linked-skill"
    assert p.is_symlink()                                        # still a symlink, not churned into a copy


def test_aside_is_recorded_before_the_risky_rename(fake_home, tmp_path, monkeypatch):
    """If the second rename fails, the user must still be told where their directory went."""
    from claude_backup import content
    target = tmp_path / "unit"; target.mkdir(); (target / "f").write_text("original")
    new_tree = tmp_path / "staged"; new_tree.mkdir(); (new_tree / "f").write_text("new")
    seen = []
    real_rename = content.os.rename
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("no space left on device")
        return real_rename(a, b)

    monkeypatch.setattr(content.os, "rename", flaky)
    with pytest.raises(OSError):
        content.replace_dir(target, new_tree, keep_aside=True, on_aside=seen.append)
    assert len(seen) == 1 and (seen[0] / "f").read_text() == "original"
    assert not target.exists()          # the failure mode; recoverable only because seen[0] is known
