from pathlib import Path
from claude_backup import verify
from claude_backup.targets import get_target


def _bundle(tmp_path):
    b = tmp_path / "bundle"
    (b / "personal/skills/s").mkdir(parents=True); (b / "personal/skills/s/SKILL.md").write_text("---\nname: s\ndescription: d\n---\n")
    (b / "personal/agents").mkdir(); (b / "personal/agents/a.md").write_text("---\nname: a\n---\n")
    (b / "personal/mcp").mkdir(); (b / "personal/mcp/global.json").write_text('{"mcpServers": {"srv": {"command": "x"}}}')
    (b / "personal/mcp/projects").mkdir()
    # a real bundle always records the variables it created; verify uses it to tell our
    # placeholders apart from ${...} text a skill legitimately contains
    (b / "secrets.required").write_text("PERSONAL_MCP_X_TOKEN\n")
    return b


def test_frontmatter_parse():
    assert verify.frontmatter_ok("---\nname: x\ndescription: y\n---\nbody") is True
    assert verify.frontmatter_ok("no frontmatter") is False
    assert verify.frontmatter_ok("---\nname: x\n") is False


def test_checks_fail_when_skill_missing(fake_home, tmp_path):
    b = _bundle(tmp_path)
    checks = verify.run_checks(b, get_target("claude"), scopes=("personal",), written_files=[], missing_secrets=[], run_cli=False)
    names = {(c.name, c.ok) for c in checks}
    assert ("skill personal/skills/s", False) in names
    assert ("agent personal/agents/a.md", False) in names
    assert ("mcp srv", False) in names


def test_checks_pass_after_files_exist(fake_home, tmp_path):
    b = _bundle(tmp_path)
    t = get_target("claude")
    (t.skills_dir() / "s").mkdir(parents=True); (t.skills_dir() / "s/SKILL.md").write_text("---\nname: s\ndescription: d\n---\n")
    (t.agents_dir() / "a.md").write_text("---\nname: a\n---\n")
    t.write_mcp({"srv": {"command": "x"}}, {}, force=False, dry=False)
    checks = verify.run_checks(b, t, scopes=("personal",), written_files=[], missing_secrets=[], run_cli=False)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_unresolved_placeholder_in_written_file_fails(fake_home, tmp_path):
    f = fake_home / "w.json"; f.write_text('{"a": "${PERSONAL_MCP_X_TOKEN}"}')
    checks = verify.run_checks(_bundle(tmp_path), get_target("claude"), scopes=(), written_files=[f], missing_secrets=[], run_cli=False)
    c = [c for c in checks if c.name.startswith("placeholders")][0]
    assert c.ok is False and "PERSONAL_MCP_X_TOKEN" in c.detail


def test_known_missing_secret_is_listed_not_failed(fake_home, tmp_path):
    f = fake_home / "w.json"; f.write_text('{"a": "${PERSONAL_MCP_X_TOKEN}"}')
    checks = verify.run_checks(_bundle(tmp_path), get_target("claude"), scopes=(), written_files=[f], missing_secrets=["PERSONAL_MCP_X_TOKEN"], run_cli=False)
    c = [c for c in checks if c.name.startswith("placeholders")][0]
    assert c.ok is True and "PERSONAL_MCP_X_TOKEN" in c.detail


def test_exit_code(capsys):
    assert verify.report([verify.Check("a", True, ""), verify.Check("b", False, "why")]) == 1
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" in out and "why" in out
    assert verify.report([verify.Check("a", True, "")]) == 0


def test_frontmatter_ok_allows_dashes_inside_values():
    assert verify.frontmatter_ok("---\ndescription: a --- b\nname: x\n---\nbody") is True
    assert verify.frontmatter_ok("---\ndescription: d\n---\nname: only in body\n") is False


def test_foreign_placeholder_is_not_a_failure(fake_home, tmp_path):
    """${CLAUDE_PLUGIN_ROOT} in a skill doc is the skill's own text, not an unresolved secret."""
    b = _bundle(tmp_path)
    f = fake_home / "w.md"; f.write_text("run ${CLAUDE_PLUGIN_ROOT}/bin and ${PROJECT_ENC}\n")
    checks = verify.run_checks(b, get_target("claude"), scopes=(), written_files=[f], missing_secrets=[], run_cli=False)
    c = [c for c in checks if c.name.startswith("placeholders")][0]
    assert c.ok is True


def test_our_own_unresolved_placeholder_still_fails(fake_home, tmp_path):
    b = _bundle(tmp_path)
    f = fake_home / "w.json"; f.write_text('{"a": "${PERSONAL_MCP_X_TOKEN}"}')
    checks = verify.run_checks(b, get_target("claude"), scopes=(), written_files=[f], missing_secrets=[], run_cli=False)
    c = [c for c in checks if c.name.startswith("placeholders")][0]
    assert c.ok is False and "PERSONAL_MCP_X_TOKEN" in c.detail
