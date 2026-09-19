import os
from pathlib import Path
import pytest
from claude_backup import common


def test_home_is_patched(fake_home):
    assert common.home() == fake_home


def test_personal_roots(fake_home):
    r = common.personal_roots()
    assert r.claude_dir == fake_home / ".claude"
    assert r.claude_json == fake_home / ".claude.json"


def test_harness_root_explicit(fake_harness):
    assert common.resolve_harness_path(fake_harness, interactive=False) == fake_harness


def test_harness_root_env(fake_harness, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(fake_harness))
    assert common.resolve_harness_path(None, interactive=False) == fake_harness


def test_harness_root_missing_non_interactive(fake_home):
    with pytest.raises(common.BackupError, match="harness path"):
        common.resolve_harness_path(None, interactive=False)


def test_bundle_dir_default_is_repo_root(fake_home, monkeypatch):
    assert common.resolve_bundle_dir(None) == common.REPO_ROOT


def test_bundle_dir_env(fake_home, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_BACKUP_DIR", str(tmp_path))
    assert common.resolve_bundle_dir(None) == tmp_path


def test_os_name():
    assert common.os_name() in {"macos", "linux", "windows"}
