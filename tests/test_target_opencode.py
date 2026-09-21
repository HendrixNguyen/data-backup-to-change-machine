import json

from claude_backup.targets import get_target


def test_opencode_dirs(fake_home):
    t = get_target("opencode")
    assert t.skills_dir() == fake_home / ".config/opencode/skills"
    # Docs (https://opencode.ai/docs/agents/, /commands/) document the plural
    # directories; the opencode source's glob accepts singular aliases too
    # ({agent,agents}, {command,commands}), but we write the canonical form.
    assert t.agents_dir() == fake_home / ".config/opencode/agents"
    assert t.commands_dir() == fake_home / ".config/opencode/commands"
    assert t.has_agents and t.has_commands


def test_opencode_agent_transform_remaps_frontmatter():
    t = get_target("opencode")
    name, text = t.transform_agent(
        "the-validator.md",
        "---\nname: the-validator\ndescription: tests\nmodel: sonnet\ncolor: blue\ntools: Read, Edit\n---\nYou validate.\n",
    )
    assert name == "the-validator.md"
    assert text.startswith("---\ndescription: tests\nmode: subagent\n---\n") and text.endswith("You validate.\n")
    assert "color:" not in text and "tools:" not in text


def test_opencode_mcp_write_new_and_merge(fake_home, servers):
    g, p = servers
    t = get_target("opencode")
    t.write_mcp(g, p, force=False, dry=False)
    cfg = json.loads((fake_home / ".config/opencode/opencode.json").read_text())
    assert cfg["mcp"]["pw"] == {"type": "local", "command": ["npx", "@playwright/mcp"], "environment": {"A": "1"}, "enabled": True}
    assert cfg["mcp"]["fig"] == {"type": "remote", "url": "https://mcp.figma.com/mcp", "headers": {"Authorization": "Bearer t"}, "enabled": True}
    (fake_home / ".config/opencode/opencode.json").write_text('// comment\n{"theme": "x", "mcp": {"pw": {"type": "local", "command": ["local"]}}}')
    assert {e.unit: e.verdict for e in t.mcp_plan(g, p, force=False)} == {"pw": "skip", "fig": "add"}
    t.write_mcp(g, p, force=False, dry=False)
    out = json.loads((fake_home / ".config/opencode/opencode.json").read_text())  # comments dropped on rewrite, documented
    assert out["theme"] == "x" and out["mcp"]["pw"]["command"] == ["local"] and "fig" in out["mcp"]


def test_opencode_dry_writes_nothing(fake_home, servers):
    get_target("opencode").write_mcp(servers[0], {}, force=True, dry=True)
    assert not (fake_home / ".config/opencode/opencode.json").exists()


def test_opencode_read_names(fake_home, servers):
    t = get_target("opencode")
    t.write_mcp(servers[0], {}, force=False, dry=False)
    assert t.read_mcp_names() == {"pw", "fig"}
