import json
from pathlib import Path
import pytest
from claude_backup import mcp
from claude_backup.common import BackupError


def test_slug_is_portable():
    assert mcp.slug("/Users/h/Workspaces/a b") == "Users-h-Workspaces-a-b"
    assert mcp.slug(r"C:\Users\h\proj") == "C-Users-h-proj"


def test_extract_personal(fake_home):
    g, projects = mcp.extract_personal(fake_home / ".claude.json")
    assert g == {}
    assert set(projects) == {str(fake_home / "proj-a"), str(fake_home / "proj-b")}   # proj-none has no mcpServers
    assert projects[str(fake_home / "proj-a")]["figma"]["type"] == "http"


def test_extract_harness(fake_harness):
    assert mcp.extract_harness(fake_harness / ".mcp.json") == {"playwright": {"command": "npx", "args": ["@playwright/mcp@0.0.80"]}}


def test_write_and_read_project_files(bundle_dir):
    mcp.write_projects(bundle_dir / "personal" / "mcp" / "projects", {"/Users/h/p": {"s": {"command": "x"}}})
    f = bundle_dir / "personal/mcp/projects/Users-h-p.json"
    assert json.loads(f.read_text()) == {"project": "/Users/h/p", "mcpServers": {"s": {"command": "x"}}}
    assert mcp.read_projects(bundle_dir / "personal" / "mcp" / "projects") == {"/Users/h/p": {"s": {"command": "x"}}}


def test_remap_paths():
    servers = {"/Users/h/p": {"s": {"command": "/Users/h/bin/x", "args": ["--root", "/Users/h/p"], "env": {"A": "/Users/h/x"}}}}
    out = mcp.remap_projects(servers, [("/Users/h", "/home/h")])
    assert list(out) == ["/home/h/p"]
    s = out["/home/h/p"]["s"]
    assert s["command"] == "/home/h/bin/x" and s["args"] == ["--root", "/home/h/p"] and s["env"]["A"] == "/home/h/x"


def test_parse_remap_flag():
    assert mcp.parse_remaps(["/Users/h=/home/h", r"C:\a=D:\b"]) == [("/Users/h", "/home/h"), (r"C:\a", r"D:\b")]


def test_write_projects_disambiguates_slug_collisions(bundle_dir):
    dst = bundle_dir / "personal" / "mcp" / "projects"
    mcp.write_projects(dst, {"/a/b": {"s1": {"command": "x"}}, "/a-b": {"s2": {"command": "y"}}})
    assert len(list(dst.glob("*.json"))) == 2
    assert mcp.read_projects(dst) == {"/a/b": {"s1": {"command": "x"}}, "/a-b": {"s2": {"command": "y"}}}


def test_read_projects_rejects_a_malformed_file(bundle_dir):
    dst = bundle_dir / "projects"; dst.mkdir()
    (dst / "bogus.json").write_text(json.dumps({"mcpServers": {}}))
    with pytest.raises(BackupError, match="not a project MCP file"):
        mcp.read_projects(dst)


def test_remap_respects_path_segment_boundaries():
    projects = {"/Users/huygen/x": {}, "/Users/huy/x": {}}
    out = mcp.remap_projects(projects, [("/Users/huy", "/home/huy2")])
    assert set(out) == {"/Users/huygen/x", "/home/huy2/x"}   # huygen is a different segment, untouched


def test_remap_skips_partial_hit_and_uses_the_later_valid_one():
    out = mcp.remap_projects({"/Users/huygen/x": {}}, [("/Users/huy", "/A"), ("/Users/huygen", "/B")])
    assert list(out) == ["/B/x"]


def test_remap_matches_whole_string_and_windows_separator():
    out = mcp.remap_projects({"/Users/huy": {}, r"C:\a\p": {}}, [("/Users/huy", "/home/h"), (r"C:\a", r"D:\b")])
    assert set(out) == {"/home/h", r"D:\b\p"}
