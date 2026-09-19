import json, re
from datetime import datetime

import pytest

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


def test_deep_merge_list_dedupes_bundle_duplicates():
    out = merge.deep_merge({"PreToolUse": []}, {"PreToolUse": [{"a": 1}, {"a": 1}]}, force=False)
    assert out["PreToolUse"] == [{"a": 1}]


def test_deep_merge_type_mismatch_dict_vs_scalar():
    assert merge.deep_merge({"a": 1}, 5, force=False) == {"a": 1}
    assert merge.deep_merge({"a": 1}, 5, force=True) == 5


def test_deep_merge_type_mismatch_dict_vs_list():
    assert merge.deep_merge({"a": 1}, [1, 2], force=False) == {"a": 1}
    assert merge.deep_merge({"a": 1}, [1, 2], force=True) == [1, 2]


def test_deep_merge_type_mismatch_none_vs_dict():
    assert merge.deep_merge(None, {"a": 1}, force=False) is None
    assert merge.deep_merge(None, {"a": 1}, force=True) == {"a": 1}


def test_atomic_write_json_and_backup(tmp_path):
    f = tmp_path / "s.json"
    merge.atomic_write_json(f, {"b": 1, "a": 2})
    assert f.read_text() == '{\n  "b": 1,\n  "a": 2\n}\n'
    bak = merge.backup_file(f)
    assert bak and re.search(r"s\.json\.bak-\d{8}T\d{12}$", bak.name)
    assert bak.read_text() == f.read_text()
    assert merge.backup_file(tmp_path / "missing.json") is None


def test_backup_file_collision_disambiguated(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text("v1")
    fixed = datetime(2026, 1, 1, 12, 0, 0, 123456)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(merge, "datetime", FixedDateTime)
    bak1 = merge.backup_file(f)
    f.write_text("v2")
    bak2 = merge.backup_file(f)
    assert bak1 != bak2
    assert bak1.exists() and bak2.exists()
    assert bak1.read_text() == "v1"
    assert bak2.read_text() == "v2"


def test_atomic_write_no_partial_on_failure(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("old")
    try:
        merge.atomic_write_text(f, None)  # type: ignore[arg-type]
    except TypeError:
        pass
    assert f.read_text() == "old"
    assert list(tmp_path.glob("*.tmp*")) == []


def test_atomic_write_text_replace_failure_leaves_original_untouched(tmp_path, monkeypatch):
    f = tmp_path / "x.json"
    f.write_text("old")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(merge.os, "replace", boom)
    with pytest.raises(OSError):
        merge.atomic_write_text(f, "new")
    assert f.read_text() == "old"
    assert list(tmp_path.glob("*.tmp*")) == []
