import subprocess

import pytest

from claude_backup import common, plan, preflight


def _age_bundle(tmp_path, home):
    """A bundle that really does need `age`: an encrypted blob plus a key to open it with."""
    from claude_backup import manifest
    b = tmp_path / "bundle"; b.mkdir()
    (b / "secrets.env.age").write_text("-----BEGIN AGE ENCRYPTED FILE-----\n")
    manifest.write(b, manifest.build(b, scopes=("personal",), claude_version=None, symlinks={}, exec_bits={}))
    key = home / ".config" / "age" / "keys.txt"; key.parent.mkdir(parents=True); key.write_text("AGE-SECRET-KEY-1\n")
    return b


def test_required_tools_depend_on_target():
    assert preflight.required_tools(need_claude=False) == ["git", "age"]
    assert preflight.required_tools(need_claude=True) == ["git", "age", "claude"]
    assert preflight.required_tools(need_claude=True, need_age=False) == ["git", "claude"]


def test_missing_tools_detected(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None if n == "age" else "/bin/x")
    assert preflight.missing(["git", "age"]) == ["age"]


def test_install_command_per_os(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/opt/homebrew/bin/brew" if n == "brew" else None)
    assert preflight.install_command("age", "macos") == ["brew", "install", "age"]
    monkeypatch.setattr(preflight.shutil, "which", lambda n: {"apt-get": "/usr/bin/apt-get", "sudo": "/usr/bin/sudo"}.get(n))
    assert preflight.install_command("age", "linux") == ["sudo", "apt-get", "install", "-y", "age"]
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "C:/winget" if n == "winget" else None)
    assert preflight.install_command("age", "windows") == ["winget", "install", "--id", "FiloSottile.age", "-e", "--accept-source-agreements", "--accept-package-agreements"]
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None)
    assert preflight.install_command("age", "linux") is None


def test_install_command_needs_sudo_or_root(monkeypatch):
    """A package manager but no sudo and not root: no usable command, so fall through to the hint."""
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/usr/bin/dnf" if n == "dnf" else None)
    monkeypatch.setattr(preflight.os, "geteuid", lambda: 1000, raising=False)
    assert preflight.install_command("age", "linux") is None
    monkeypatch.setattr(preflight.os, "geteuid", lambda: 0, raising=False)
    assert preflight.install_command("age", "linux") == ["dnf", "install", "-y", "age"]


def test_claude_install_is_manual_line():
    assert "claude.ai" in preflight.manual_hint("claude") or "npm" in preflight.manual_hint("claude")


def test_run_preflight_installs_then_rechecks(monkeypatch, tmp_path, fake_home):
    calls = []
    state = {"age": False}
    b = _age_bundle(tmp_path, fake_home)
    monkeypatch.setattr(preflight.shutil, "which", lambda n: ("/x" if (n != "age" or state["age"]) else None))
    def fake_run(cmd, **kw):
        calls.append(cmd); state["age"] = True
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    preflight.run_preflight(need_claude=False, bundle_dir=b, yes=True)
    assert calls == [["brew", "install", "age"]]


def test_run_preflight_asks_before_installing(monkeypatch, tmp_path, fake_home, capsys):
    b = _age_bundle(tmp_path, fake_home)
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None if n == "age" else "/x")
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: pytest.fail("installed without consent"))
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    monkeypatch.setattr(plan, "confirm", lambda **kw: False)
    with pytest.raises(common.BackupError, match="install declined"):
        preflight.run_preflight(need_claude=False, bundle_dir=b)
    assert "brew install age" in capsys.readouterr().err


def test_run_preflight_dry_run_installs_nothing(monkeypatch, tmp_path, fake_home, capsys):
    b = _age_bundle(tmp_path, fake_home)
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None if n == "age" else "/x")
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: pytest.fail("dry run must not install"))
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    monkeypatch.setattr(plan, "confirm", lambda **kw: pytest.fail("dry run must not prompt"))
    preflight.run_preflight(need_claude=False, bundle_dir=b, dry_run=True)
    err = capsys.readouterr().err
    assert "dry run" in err and "brew install age" in err


def test_install_failure_is_backup_error(monkeypatch, tmp_path, fake_home):
    b = _age_bundle(tmp_path, fake_home)
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None if n == "age" else "/x")
    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(preflight.subprocess, "run", boom)
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    with pytest.raises(common.BackupError, match="installing age failed"):
        preflight.run_preflight(need_claude=False, bundle_dir=b, yes=True)


def test_age_not_required_without_encrypted_secrets(monkeypatch, tmp_path, fake_home, capsys):
    """No secrets.env.age (or no key): a missing `age` is a warning, never an install."""
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None if n == "age" else "/x")
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: pytest.fail("age must not be installed here"))
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    preflight.run_preflight(need_claude=False, bundle_dir=None)
    assert "age is not installed" in capsys.readouterr().err


def test_warns_when_no_age_key(monkeypatch, fake_home, capsys):
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/x")
    monkeypatch.setattr(preflight.common, "os_name", lambda: "macos")
    preflight.run_preflight(need_claude=False, bundle_dir=None)
    assert "no age key at" in capsys.readouterr().err


def test_hash_mismatch_is_hard_stop(monkeypatch, tmp_path, fake_home):
    from claude_backup import manifest
    b = tmp_path / "b"; (b / "personal").mkdir(parents=True); f = b / "personal" / "x.json"; f.write_text("1")
    manifest.write(b, manifest.build(b, scopes=("personal",), claude_version=None, symlinks={}, exec_bits={}))
    f.write_text("2")
    monkeypatch.setattr(preflight.shutil, "which", lambda n: "/x")
    monkeypatch.setattr(preflight.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    with pytest.raises(common.BackupError, match="hash mismatch"):
        preflight.run_preflight(need_claude=False, bundle_dir=b)


def test_autocrlf_hint(monkeypatch, tmp_path):
    def fake_run(cmd, **kw):
        out = "true\n" if cmd[1] == "config" else "personal/x.json: text: unspecified\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    hint = preflight.crlf_hint(tmp_path, "personal/x.json")
    assert "core.autocrlf" in hint and "discards uncommitted changes" in hint


def test_autocrlf_hint_silent_when_gitattributes_wins(monkeypatch, tmp_path):
    def fake_run(cmd, **kw):
        out = "true\n" if cmd[1] == "config" else "personal/x.json: text: unset\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    assert preflight.crlf_hint(tmp_path, "personal/x.json") == ""


def test_autocrlf_hint_survives_missing_git(monkeypatch, tmp_path):
    def no_git(cmd, **kw):
        raise FileNotFoundError("git")
    monkeypatch.setattr(preflight.subprocess, "run", no_git)
    assert preflight.crlf_hint(tmp_path) == ""
