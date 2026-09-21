"""WSL looks like Linux to Python but has two homes. These simulate it; CI has no WSL runner."""
from pathlib import Path

from claude_backup import common


def _fake_wsl(monkeypatch, tmp_path, *, windows_users: Path | None):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    real_is_dir = Path.is_dir
    real_glob = Path.glob

    def is_dir(self):
        if self.as_posix() in ("/mnt/c/Users", "/c/Users"):   # str() uses backslashes on Windows
            return windows_users is not None
        return real_is_dir(self)

    def glob(self, pat):
        if self.as_posix() in ("/mnt/c/Users", "/c/Users") and windows_users is not None:
            return real_glob(windows_users, pat)
        return real_glob(self, pat)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    monkeypatch.setattr(Path, "glob", glob)


def test_not_wsl_on_a_normal_machine(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (_ for _ in ()).throw(OSError()))
    assert common.is_wsl() is False
    assert common.wsl_notice() is None


def test_wsl_detected_from_env(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert common.is_wsl() is True


def test_wsl_with_no_windows_mount_says_nothing(monkeypatch, fake_home, tmp_path):
    _fake_wsl(monkeypatch, tmp_path, windows_users=None)
    assert common.wsl_notice() is None


def test_wsl_warns_loudly_when_only_the_windows_side_exists(monkeypatch, fake_home, tmp_path):
    """The dangerous case: restoring into an empty Linux home while the real config is on Windows."""
    import shutil
    shutil.rmtree(fake_home / ".claude")
    winusers = tmp_path / "winusers"
    (winusers / "huy" / ".claude").mkdir(parents=True)
    _fake_wsl(monkeypatch, tmp_path, windows_users=winusers)
    note = common.wsl_notice()
    assert note and "does not exist" in note and "restore.ps1" in note


def test_wsl_names_both_homes_when_both_exist(monkeypatch, fake_home, tmp_path):
    winusers = tmp_path / "winusers"
    (winusers / "huy" / ".claude").mkdir(parents=True)
    _fake_wsl(monkeypatch, tmp_path, windows_users=winusers)
    note = common.wsl_notice()
    assert note and "is not touched" in note and str(fake_home / ".claude") in note
