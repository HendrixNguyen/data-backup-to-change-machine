import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A throwaway $HOME with a realistic ~/.claude tree. Path.home() is patched, so no module may cache it at import."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CLAUDE_BACKUP_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    # never spawn the real `claude` CLI from tests (export's _claude_version, verify's CLI checks)
    import shutil as _shutil
    _real_which = _shutil.which
    monkeypatch.setattr(_shutil, "which", lambda n, *a, **k: None if n == "claude" else _real_which(n, *a, **k))

    c = home / ".claude"
    (c / "skills" / "real-skill").mkdir(parents=True)
    (c / "skills" / "real-skill" / "SKILL.md").write_text("---\nname: real-skill\ndescription: a real one\n---\nbody\n")
    (c / "agents").mkdir()
    (c / "agents" / "the-validator.md").write_text("---\nname: the-validator\ndescription: tests\nmodel: sonnet\ncolor: blue\n---\nYou validate.\n")
    (c / "commands").mkdir()
    (c / "commands" / "review-code.md").write_text("Review the code.\n")
    (c / "hooks").mkdir()
    (c / "CLAUDE.md").write_text("# global instructions\n")
    (c / "settings.json").write_text(json.dumps({
        "env": {"MY_TOKEN": "tok-123", "PLAIN": "1"},
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]},
    }, indent=2))
    (c / "plugins").mkdir()
    (c / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"feature-dev@claude-code-plugins": [{"scope": "user", "version": "1.0.0", "installPath": "/x"}]},
    }))
    (home / ".claude.json").write_text(json.dumps({
        "mcpServers": {},
        "projects": {
            str(home / "proj-a"): {"mcpServers": {"figma": {"type": "http", "url": "https://mcp.figma.com/mcp?key=abc", "headers": {"Authorization": "Bearer xyz"}}}},
            str(home / "proj-b"): {"mcpServers": {"context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"], "env": {"CONTEXT7_API_KEY": "ctx-key"}}}},
            str(home / "proj-none"): {"allowedTools": []},
        },
    }))
    # a symlinked skill, like ~/.claude/skills/brainstorming -> ~/.agents/skills/brainstorming
    agents_skill = home / ".agents" / "skills" / "linked-skill"
    agents_skill.mkdir(parents=True)
    (agents_skill / "SKILL.md").write_text("---\nname: linked-skill\ndescription: linked\n---\nlinked body\n")
    try:
        os.symlink(agents_skill, c / "skills" / "linked-skill", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this runner")
    return home


@pytest.fixture
def fake_harness(tmp_path):
    h = tmp_path / "harness"
    (h / ".claude" / "skills" / "load-context").mkdir(parents=True)
    (h / ".claude" / "skills" / "load-context" / "SKILL.md").write_text("---\nname: load-context\ndescription: h\n---\n")
    (h / ".claude" / "hooks").mkdir()
    hook = h / ".claude" / "hooks" / "session-start.sh"
    hook.write_text("#!/bin/sh\necho start\n")
    if os.name != "nt":
        hook.chmod(0o755)
    (h / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    (h / ".mcp.json").write_text(json.dumps({"mcpServers": {"playwright": {"command": "npx", "args": ["@playwright/mcp@0.0.80"]}}}))
    return h


@pytest.fixture
def bundle_dir(tmp_path):
    b = tmp_path / "bundle"
    b.mkdir()
    return b
