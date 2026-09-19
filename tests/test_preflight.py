import subprocess
import pytest
from claude_backup import preflight, common


def test_required_tools_depend_on_target():
    assert preflight.required_tools(need_claude=False) == ["git", "age"]
    assert preflight.required_tools(need_claude=True) == ["git", "age", "claude"]


def test_missing_tools_detected(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None if n == "age" else "/bin/x")
    assert preflight.missing(["git", "age"]) == ["age"]


def test_install_command_per_os(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/opt/homebrew/bin/brew" if n == "brew" else None)
    assert preflight.install_command("age", "macos") == ["brew", "install", "age"]
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/usr/bin/apt-get" if n == "apt-get" else None)
    assert preflight.install_command("age", "linux") == ["sudo", "apt-get", "install", "-y", "age"]
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "C:/winget" if n == "winget" else None)
    assert preflight.install_command("age", "windows") == ["winget", "install", "--id", "FiloSottile.age", "-e", "--accept-source-agreements", "--accept-package-agreements"]
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None)
    assert preflight.install_command("age", "linux") is None


def test_claude_install_is_manual_line():
    assert "claude.ai" in preflight.manual_hint("claude") or "npm" in preflight.manual_hint("claude")


def test_run_preflight_installs_then_rechecks(monkeypatch):
    calls = []
    state = {"age": False}
    monkeypatch.setattr(preflight.shutil, "which", lambda n: ("/x" if (n != "age" or state["age"]) else None))
    def fake_run(cmd, **kw):
        calls.append(cmd); state["age"] = True
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    preflight.run_preflight(need_claude=False, bundle_dir=None)
    assert calls == [["brew", "install", "age"]]


def test_hash_mismatch_is_hard_stop(monkeypatch, tmp_path):
    from claude_backup import manifest
    b = tmp_path / "b"; (b / "personal").mkdir(parents=True); f = b / "personal" / "x.json"; f.write_text("1")
    manifest.write(b, manifest.build(b, scopes=("personal",), claude_version=None, symlinks={}, exec_bits={}))
    f.write_text("2")
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/x")
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    with pytest.raises(common.BackupError, match="hash mismatch"):
        preflight.run_preflight(need_claude=False, bundle_dir=b)


def test_autocrlf_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "true\n", ""))
    assert "core.autocrlf" in preflight.crlf_hint(tmp_path)
