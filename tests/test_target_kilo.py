import json
from claude_backup.targets import get_target


def test_kilo_dirs(fake_home):
    t = get_target("kilo")
    assert t.skills_dir() == fake_home / ".kilocode/skills"
    assert t.has_agents is True and t.agents_dir() == fake_home / ".kilocode"
    assert t.has_commands is False


def test_kilo_agent_becomes_mode_entry(fake_home):
    t = get_target("kilo")
    res = t.transform_agent("the-validator.md", "---\nname: the-validator\ndescription: tests things\nmodel: sonnet\n---\nYou validate.\n")
    assert res is None                      # modes are written by flush_modes(), not as files
    t.queue_agent("the-validator.md", "---\nname: the-validator\ndescription: tests things\n---\nYou validate.\n")
    t.flush_modes(dry=False)
    modes = (fake_home / ".kilocode/custom_modes.yaml").read_text()
    assert modes.count("slug: the-validator") == 1 and "roleDefinition: |" in modes and "You validate." in modes and "groups: [read, edit, command]" in modes
    assert t.verify_agent("the-validator.md") is True and t.verify_agent("nope.md") is False


def test_kilo_mcp_claude_shape(fake_home, servers):
    t = get_target("kilo")
    t.write_mcp(servers[0], {}, force=False, dry=False)
    assert set(json.loads((fake_home / ".kilocode/mcp_settings.json").read_text())["mcpServers"]) == {"pw", "fig"}


def test_kilo_flush_modes_is_noop_without_queue(fake_home):
    assert get_target("kilo").flush_modes(dry=False) is None
    assert not (fake_home / ".kilocode/custom_modes.yaml").exists()
