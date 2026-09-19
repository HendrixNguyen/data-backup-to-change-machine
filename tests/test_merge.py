import json, re
from claude_backup import merge


def test_deep_merge_local_wins_by_default():
    local = {"a": 1, "nested": {"x": "local"}, "list": ["l"]}
    bundle = {"a": 2, "nested": {"x": "bundle", "y": 3}, "list": ["b", "l"], "new": True}
    out = merge.deep_merge(local, bundle, force=False)
    assert out == {"a": 1, "nested": {"x": "local", "y": 3}, "list": ["l", "b"], "new": True}


def test_deep_merge_force_bundle_wins():
    out = merge.deep_merge({"a": 1, "n": {"x": 1}}, {"a": 2, "n": {"x": 2}}, force=True)
    assert out == {"a": 2, "n": {"x": 2}}


def test_deep_merge_list_union_by_json_equality():
    h = {"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}
    out = merge.deep_merge({"PreToolUse": [h]}, {"PreToolUse": [dict(h), {"matcher": "Edit"}]}, force=False)
    assert out["PreToolUse"] == [h, {"matcher": "Edit"}]


def test_atomic_write_json_and_backup(tmp_path):
    f = tmp_path / "s.json"
    merge.atomic_write_json(f, {"b": 1, "a": 2})
    assert f.read_text() == '{\n  "b": 1,\n  "a": 2\n}\n'
    bak = merge.backup_file(f)
    assert bak and re.search(r"s\.json\.bak-\d{8}T\d{6}$", bak.name)
    assert bak.read_text() == f.read_text()
    assert merge.backup_file(tmp_path / "missing.json") is None


def test_atomic_write_no_partial_on_failure(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("old")
    try:
        merge.atomic_write_text(f, None)  # type: ignore[arg-type]
    except TypeError:
        pass
    assert f.read_text() == "old"
    assert list(tmp_path.glob("*.tmp*")) == []
