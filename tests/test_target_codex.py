import tomllib
import pytest
from claude_backup import common
from claude_backup.targets import get_target


def test_codex_dirs_and_capabilities(fake_home):
    t = get_target("codex")
    assert t.skills_dir() == fake_home / ".codex" / "skills"
    assert t.has_agents is False and t.has_commands is False and t.supports_harness is False


def test_codex_writes_new_config(fake_home, servers):
    g, p = servers
    t = get_target("codex")
    t.write_mcp(g, p, force=False, dry=False)
    cfg = tomllib.loads((fake_home / ".codex" / "config.toml").read_text())
    assert cfg["mcp_servers"]["pw"] == {"command": "npx", "args": ["@playwright/mcp"], "env": {"A": "1"}}
    assert cfg["mcp_servers"]["fig"] == {"url": "https://mcp.figma.com/mcp", "http_headers": {"Authorization": "Bearer t"}}


def test_codex_merge_appends_only_missing_and_keeps_rest_byte_identical(fake_home, servers):
    g, p = servers
    f = fake_home / ".codex" / "config.toml"; f.parent.mkdir()
    existing = 'model = "gpt"\n\n[mcp_servers.pw]\ncommand = "local"\n\n[features]\nx = true\n'
    f.write_text(existing)
    t = get_target("codex")
    es = t.mcp_plan(g, p, force=False)
    assert {e.unit: e.verdict for e in es} == {"pw": "skip", "fig": "add"}
    t.write_mcp(g, p, force=False, dry=False)
    out = f.read_text()
    assert out.startswith(existing)                       # untouched prefix
    assert tomllib.loads(out)["mcp_servers"]["pw"]["command"] == "local"
    assert tomllib.loads(out)["mcp_servers"]["fig"]["url"] == "https://mcp.figma.com/mcp"
    assert list(f.parent.glob("config.toml.bak-*"))


def test_codex_force_replaces_only_colliding_block(fake_home, servers):
    g, p = servers
    f = fake_home / ".codex" / "config.toml"; f.parent.mkdir()
    f.write_text('model = "gpt"\n\n[mcp_servers.pw]\ncommand = "local"\n\n[mcp_servers.pw.env]\nZ = "9"\n\n[features]\nx = true\n')
    get_target("codex").write_mcp({"pw": g["pw"]}, {}, force=True, dry=False)
    out = f.read_text()
    cfg = tomllib.loads(out)
    assert cfg["mcp_servers"]["pw"] == g["pw"] and cfg["features"] == {"x": True} and cfg["model"] == "gpt"
    assert out.count("[mcp_servers.pw]") == 1


def test_codex_inline_table_collision_detected(fake_home, servers):
    f = fake_home / ".codex" / "config.toml"; f.parent.mkdir()
    f.write_text('mcp_servers.pw = { command = "inline" }\n')
    es = get_target("codex").mcp_plan(servers[0], {}, force=False)
    assert {e.unit: e.verdict for e in es}["pw"] == "skip"


def test_codex_read_names(fake_home, servers):
    get_target("codex").write_mcp(servers[0], {}, force=False, dry=False)
    assert get_target("codex").read_mcp_names() == {"pw", "fig"}


def test_codex_dry_writes_nothing(fake_home, servers):
    get_target("codex").write_mcp(servers[0], {}, force=True, dry=True)
    assert not (fake_home / ".codex" / "config.toml").exists()


def test_codex_invalid_toml_is_backup_error(fake_home, servers):
    f = fake_home / ".codex" / "config.toml"; f.parent.mkdir(); f.write_text("this = [is not toml\n")
    with pytest.raises(common.BackupError):
        get_target("codex").mcp_plan(servers[0], {}, force=False)
