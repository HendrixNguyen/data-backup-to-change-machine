import builtins
import os
import sys

import pytest

from claude_backup import common, plan


def test_verdicts_add_skip_replace(tmp_path):
    bundle = tmp_path / "b" / "personal" / "skills"; (bundle / "a").mkdir(parents=True); (bundle / "a" / "SKILL.md").write_text("new")
    (bundle / "b").mkdir(); (bundle / "b" / "SKILL.md").write_text("same")
    target = tmp_path / "t"; (target / "a").mkdir(parents=True); (target / "a" / "SKILL.md").write_text("old")
    (target / "b").mkdir(); (target / "b" / "SKILL.md").write_text("same")
    (target / "local-only").mkdir()
    entries = plan.build_content_plan(bundle, target, bundle_rel="personal/skills", force=False)
    by = {e.unit: e for e in entries}
    assert by["a"].verdict == "skip" and by["a"].differs is True
    assert by["b"].verdict == "skip" and by["b"].differs is False
    assert "local-only" not in by
    forced = {e.unit: e for e in plan.build_content_plan(bundle, target, bundle_rel="personal/skills", force=True)}
    assert forced["a"].verdict == "replace"
    assert forced["b"].verdict == "skip"   # identical: --force has nothing to replace
    (target / "a").rename(target / "z")
    assert {e.unit: e.verdict for e in plan.build_content_plan(bundle, target, bundle_rel="personal/skills", force=False)}["a"] == "add"


def test_differs_reads_content_not_stat(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "nested").mkdir(parents=True); (b / "nested").mkdir(parents=True)
    fa, fb = a / "nested" / "f.txt", b / "nested" / "f.txt"
    fa.write_text("aaa"); fb.write_text("bbb")   # same size
    os.utime(fa, (1_700_000_000, 1_700_000_000)); os.utime(fb, (1_700_000_000, 1_700_000_000))
    assert plan._differs(a, b) is True


def test_differs_sees_ignored_looking_names(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "__pycache__").mkdir(parents=True); (a / "__pycache__" / "m.pyc").write_bytes(b"\x00")
    (b).mkdir(parents=True)
    (a / "SKILL.md").write_text("x"); (b / "SKILL.md").write_text("x")
    assert plan._differs(a, b) is True


def test_differs_file_vs_dir_same_name(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "thing").write_text("i am a file")
    (b / "thing").mkdir()
    assert plan._differs(a, b) is True


def test_only_filter_is_bundle_relative():
    es = [plan.PlanEntry("personal/skills", "foo", "add", None, None, False), plan.PlanEntry("personal/skills", "bar", "add", None, None, False),
          plan.PlanEntry("harness/skills", "foo", "add", None, None, False)]
    kept = plan.apply_only(es, ["personal/skills/foo", "harness/skills"])
    assert [(e.kind, e.unit) for e in kept] == [("personal/skills", "foo"), ("harness/skills", "foo")]


def test_only_unmatched_keys_are_an_error():
    es = [plan.PlanEntry("personal/skills", "foo", "add", None, None, False)]
    with pytest.raises(common.BackupError, match="nope/one.*nope/two"):
        plan.apply_only(es, ["personal/skills/foo", "nope/one", "nope/two"])


def test_only_accepts_windows_separators():
    es = [plan.PlanEntry("personal/skills", "foo", "add", None, None, False)]
    assert plan.apply_only(es, ["personal\\skills\\foo"]) == es


def test_print_plan_summary(capsys):
    es = [plan.PlanEntry("personal/skills", "foo", "add", None, None, False), plan.PlanEntry("personal/skills", "bar", "skip", None, None, True)]
    plan.print_plan(es, notices=["hooks need a POSIX shell on Windows"])
    out = capsys.readouterr().out
    assert "add" in out and "skip" in out and "differs" in out and "1 add, 1 skip, 0 replace" in out and "hooks need" in out


def test_confirm_yes_flag_skips_prompt():
    assert plan.confirm(yes=True) is True


def test_confirm_non_tty_declines(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert plan.confirm(yes=False) is False
    assert "non-interactive" in capsys.readouterr().err


def test_confirm_eof_declines(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    def boom(*a):
        raise EOFError
    monkeypatch.setattr(builtins, "input", boom)
    assert plan.confirm(yes=False) is False
