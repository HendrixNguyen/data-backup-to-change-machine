from pathlib import Path
from claude_backup import plan


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
    assert forced["a"].verdict == "replace" and forced["b"].verdict == "replace"
    (target / "a").rename(target / "z")
    assert {e.unit: e.verdict for e in plan.build_content_plan(bundle, target, bundle_rel="personal/skills", force=False)}["a"] == "add"


def test_only_filter_is_bundle_relative():
    es = [plan.PlanEntry("personal/skills", "foo", "add", None, None, False), plan.PlanEntry("personal/skills", "bar", "add", None, None, False),
          plan.PlanEntry("harness/skills", "foo", "add", None, None, False)]
    kept = plan.apply_only(es, ["personal/skills/foo", "harness/skills"])
    assert [(e.kind, e.unit) for e in kept] == [("personal/skills", "foo"), ("harness/skills", "foo")]


def test_print_plan_summary(capsys):
    es = [plan.PlanEntry("personal/skills", "foo", "add", None, None, False), plan.PlanEntry("personal/skills", "bar", "skip", None, None, True)]
    plan.print_plan(es, notices=["hooks need a POSIX shell on Windows"])
    out = capsys.readouterr().out
    assert "add" in out and "skip" in out and "differs" in out and "1 add, 1 skip, 0 replace" in out and "hooks need" in out


def test_confirm_yes_flag_skips_prompt():
    assert plan.confirm(yes=True) is True
