import json
from pathlib import Path
from claude_backup import mcp


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
