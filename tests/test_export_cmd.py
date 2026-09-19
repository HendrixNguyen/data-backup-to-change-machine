import json, subprocess
from types import SimpleNamespace
from claude_backup import export_cmd, manifest


def args(**kw):
    base = dict(scope="all", harness_path=None, bundle=None, yes=True, commit_secrets=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_export_personal_writes_bundle(fake_home, bundle_dir):
    rc = export_cmd.run_export(args(scope="personal", bundle=bundle_dir))
    assert rc == 0
    assert (bundle_dir / "personal/skills/real-skill/SKILL.md").exists()
    assert (bundle_dir / "personal/agents/the-validator.md").exists()
    assert (bundle_dir / "personal/commands/review-code.md").exists()
    assert (bundle_dir / "personal/instructions/CLAUDE.md").exists()
    settings = json.loads((bundle_dir / "personal/settings.json").read_text())
    assert settings["env"]["MY_TOKEN"] == "${PERSONAL_SETTINGS_MY_TOKEN}"
    projects = sorted(p.name for p in (bundle_dir / "personal/mcp/projects").glob("*.json"))
    assert len(projects) == 2
    plugins = json.loads((bundle_dir / "personal/plugins.json").read_text())
    assert plugins == [{"name": "feature-dev", "marketplace": "claude-code-plugins", "version": "1.0.0"}]
    req = (bundle_dir / "secrets.required").read_text().splitlines()
    assert "PERSONAL_MCP_FIGMA_URL" in req and "PERSONAL_MCP_FIGMA_AUTHORIZATION" in req and "PERSONAL_MCP_CONTEXT7_CONTEXT7_API_KEY" in req
    assert not (bundle_dir / "secrets.env").exists()          # no age recipient => nothing sensitive written
    m = manifest.read(bundle_dir)
    assert m["scopes"] == ["personal"] and "personal/skills/linked-skill" in m["symlinks"]


def test_export_all_includes_harness(fake_home, fake_harness, bundle_dir):
    assert export_cmd.run_export(args(harness_path=fake_harness, bundle=bundle_dir)) == 0
    assert (bundle_dir / "harness/skills/load-context/SKILL.md").exists()
    assert (bundle_dir / "harness/hooks/session-start.sh").exists()
    assert json.loads((bundle_dir / "harness/mcp.json").read_text())["mcpServers"]["playwright"]["command"] == "npx"
    assert manifest.read(bundle_dir)["scopes"] == ["personal", "harness"]


def test_export_refuses_dirty_bundle_without_yes(fake_home, bundle_dir):
    subprocess.run(["git", "init", "-q"], cwd=bundle_dir, check=True)
    (bundle_dir / "dirty.txt").write_text("x")
    rc = export_cmd.run_export(args(scope="personal", bundle=bundle_dir, yes=False))
    assert rc == 1


def test_export_second_run_is_idempotent(fake_home, bundle_dir):
    export_cmd.run_export(args(scope="personal", bundle=bundle_dir))
    first = {p.relative_to(bundle_dir).as_posix(): p.read_bytes() for p in bundle_dir.rglob("*") if p.is_file() and p.name != "bundle.json"}
    export_cmd.run_export(args(scope="personal", bundle=bundle_dir))
    second = {p.relative_to(bundle_dir).as_posix(): p.read_bytes() for p in bundle_dir.rglob("*") if p.is_file() and p.name != "bundle.json"}
    assert first == second


def test_export_warns_about_stale_artifacts(fake_home, bundle_dir, capsys):
    stale = bundle_dir / "personal" / "skills" / "x.bak-123"
    stale.mkdir(parents=True)
    assert export_cmd.run_export(args(scope="personal", bundle=bundle_dir)) == 0
    err = capsys.readouterr().err
    assert f"stale artifact from an interrupted run (safe to delete): {stale}" in err
