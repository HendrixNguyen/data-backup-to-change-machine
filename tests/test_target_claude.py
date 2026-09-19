import json
from claude_backup.targets import get_target, all_target_names


def test_registry_has_all_targets():
    assert set(all_target_names()) == {"claude", "codex", "antigravity", "opencode", "kilo"}


def test_claude_dirs(fake_home):
    t = get_target("claude")
    assert t.skills_dir() == fake_home / ".claude" / "skills"
    assert t.agents_dir() == fake_home / ".claude" / "agents"
    assert t.commands_dir() == fake_home / ".claude" / "commands"
    assert t.supports_harness is True


def test_claude_mcp_merge_adds_only_missing(fake_home):
    t = get_target("claude")
    g = {"newglobal": {"command": "x"}}
    projects = {str(fake_home / "proj-a"): {"figma": {"type": "http", "url": "REPLACED"}, "extra": {"command": "y"}}}
    written = t.write_mcp(g, projects, force=False, dry=False)
    data = json.loads((fake_home / ".claude.json").read_text())
    assert data["mcpServers"] == {"newglobal": {"command": "x"}}
    pa = data["projects"][str(fake_home / "proj-a")]["mcpServers"]
    assert pa["figma"]["url"] == "https://mcp.figma.com/mcp?key=abc"     # local wins
    assert pa["extra"] == {"command": "y"}
    assert written == [fake_home / ".claude.json"]
    assert list(fake_home.glob(".claude.json.bak-*"))


def test_claude_mcp_force_replaces(fake_home):
    t = get_target("claude")
    t.write_mcp({}, {str(fake_home / "proj-a"): {"figma": {"type": "http", "url": "REPLACED"}}}, force=True, dry=False)
    data = json.loads((fake_home / ".claude.json").read_text())
    assert data["projects"][str(fake_home / "proj-a")]["mcpServers"]["figma"]["url"] == "REPLACED"


def test_claude_mcp_dry_writes_nothing(fake_home):
    before = (fake_home / ".claude.json").read_text()
    get_target("claude").write_mcp({"n": {"command": "x"}}, {}, force=True, dry=True)
    assert (fake_home / ".claude.json").read_text() == before


def test_claude_mcp_plan_entries(fake_home):
    t = get_target("claude")
    es = t.mcp_plan({"newglobal": {"command": "x"}}, {str(fake_home / "proj-a"): {"figma": {"url": "u"}}}, force=False)
    assert {(e.unit, e.verdict) for e in es} == {("global/newglobal", "add"), (f"{str(fake_home / 'proj-a')}/figma", "skip")}
