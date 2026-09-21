"""The bundle is built to be committed, so a world-readable remote is a disclosure."""
import subprocess

import pytest

from claude_backup import common, remote


@pytest.mark.parametrize("url,expected", [
    ("git@github.com:owner/repo.git", ("github.com", "owner/repo")),
    ("https://github.com/owner/repo.git", ("github.com", "owner/repo")),
    ("https://github.com/owner/repo", ("github.com", "owner/repo")),
    ("git@gitlab.com:group/sub/repo.git", ("gitlab.com", "group/sub/repo")),
    ("ssh://git@example.com:2222/team/repo.git", ("example.com", "team/repo")),
    ("https://user@git.corp:8443/team/repo.git", ("git.corp", "team/repo")),
    ("/plain/local/path", None),
    ("", None),
])
def test_parse_remote(url, expected):
    assert remote.parse_remote(url) == expected


def _stub_probe(monkeypatch, status, body):
    monkeypatch.setattr(remote, "_probe", lambda url: (status, body))


def test_github_public_and_private(monkeypatch):
    _stub_probe(monkeypatch, 200, {"private": False})
    assert remote.visibility("github.com", "o/r") == remote.PUBLIC
    _stub_probe(monkeypatch, 200, {"private": True})
    assert remote.visibility("github.com", "o/r") == remote.PRIVATE


def test_404_means_the_world_cannot_read_it(monkeypatch):
    _stub_probe(monkeypatch, 404, None)
    assert remote.visibility("github.com", "o/r") == remote.PRIVATE


def test_network_failure_is_not_an_answer(monkeypatch):
    _stub_probe(monkeypatch, None, None)
    assert remote.visibility("github.com", "o/r") == remote.UNKNOWN


def test_gitlab_visibility(monkeypatch):
    _stub_probe(monkeypatch, 200, {"visibility": "public"})
    assert remote.visibility("gitlab.com", "g/r") == remote.PUBLIC
    _stub_probe(monkeypatch, 200, {"visibility": "private"})
    assert remote.visibility("gitlab.com", "g/r") == remote.PRIVATE


def test_unknown_host_is_never_assumed_public(monkeypatch):
    assert remote.visibility("git.internal.corp", "t/r") == remote.UNKNOWN


def _repo_with_origin(tmp_path, url):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=tmp_path, check=True)
    return tmp_path


def test_guard_refuses_a_public_remote(tmp_path, monkeypatch):
    d = _repo_with_origin(tmp_path, "git@github.com:owner/repo.git")
    monkeypatch.setattr(remote, "visibility", lambda h, p: remote.PUBLIC)
    with pytest.raises(common.BackupError, match="PUBLIC"):
        remote.guard(d, allow_public=False)


def test_guard_allows_public_when_asked(tmp_path, monkeypatch, capsys):
    d = _repo_with_origin(tmp_path, "git@github.com:owner/repo.git")
    monkeypatch.setattr(remote, "visibility", lambda h, p: remote.PUBLIC)
    remote.guard(d, allow_public=True)
    assert "world-readable" in capsys.readouterr().err


def test_guard_is_silent_for_a_private_remote(tmp_path, monkeypatch, capsys):
    d = _repo_with_origin(tmp_path, "git@github.com:owner/repo.git")
    monkeypatch.setattr(remote, "visibility", lambda h, p: remote.PRIVATE)
    remote.guard(d, allow_public=False)
    assert capsys.readouterr().err == ""


def test_guard_says_nothing_without_a_remote(tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    remote.guard(tmp_path, allow_public=False)
    assert capsys.readouterr().err == ""
