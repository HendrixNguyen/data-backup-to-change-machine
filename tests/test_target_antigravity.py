import json
from claude_backup.targets import get_target


def test_antigravity_dirs(fake_home):
    t = get_target("antigravity")
    assert t.skills_dir() == fake_home / ".gemini/antigravity/skills"
    assert t.agents_dir() is None and t.has_agents is False
    assert t.commands_dir() == fake_home / ".gemini/antigravity/global_workflows" and t.has_commands


def test_antigravity_mcp_claude_shape_merge(fake_home, servers):
    g, p = servers
    t = get_target("antigravity")
    t.write_mcp(g, p, force=False, dry=False)
    cfg = json.loads(t.config().read_text())
    assert cfg["mcpServers"]["pw"] == g["pw"] and cfg["mcpServers"]["fig"] == g["fig"]
    t.config().write_text(json.dumps({"mcpServers": {"pw": {"command": "local"}}}))
    assert {e.unit: e.verdict for e in t.mcp_plan(g, p, force=False)} == {"pw": "skip", "fig": "add"}
    t.write_mcp(g, p, force=True, dry=False)
    assert json.loads(t.config().read_text())["mcpServers"]["pw"] == g["pw"]


def test_antigravity_command_becomes_workflow():
    name, text = get_target("antigravity").transform_command("review-code.md", "Review the code.\n")
    assert name == "review-code.md" and text.startswith("---\ndescription: review-code\n---\n") and text.endswith("Review the code.\n")


def test_antigravity_command_with_frontmatter_is_untouched():
    src = "---\ndescription: keep me\n---\nbody\n"
    assert get_target("antigravity").transform_command("x.md", src) == ("x.md", src)


def test_antigravity_dry_writes_nothing(fake_home, servers):
    t = get_target("antigravity")
    t.write_mcp(servers[0], {}, force=True, dry=True)
    assert not t.config().exists()
