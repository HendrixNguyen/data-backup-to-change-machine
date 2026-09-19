import os
from datetime import datetime
from pathlib import Path
import pytest
from claude_backup import content


def test_export_kind_copies_units_and_records_symlinks(fake_home, bundle_dir):
    src = fake_home / ".claude" / "skills"
    res = content.export_kind(src, bundle_dir / "personal" / "skills", bundle_rel="personal/skills")
    assert (bundle_dir / "personal/skills/real-skill/SKILL.md").read_text().startswith("---")
    assert (bundle_dir / "personal/skills/linked-skill/SKILL.md").exists()
    assert not (bundle_dir / "personal/skills/linked-skill").is_symlink()
    assert res.symlinks == {"personal/skills/linked-skill": str((fake_home / ".agents/skills/linked-skill").resolve())}
    assert res.units == ["linked-skill", "real-skill"]


@pytest.mark.skipif(os.name == "nt", reason="exec bits are POSIX")
def test_export_kind_records_exec_bits(fake_harness, bundle_dir):
    res = content.export_kind(fake_harness / ".claude" / "hooks", bundle_dir / "harness" / "hooks", bundle_rel="harness/hooks")
    assert res.exec_bits == {"harness/hooks/session-start.sh": True}


def test_export_kind_refresh_removes_stale_units(fake_home, bundle_dir):
    dst = bundle_dir / "personal" / "skills"
    (dst / "gone").mkdir(parents=True); (dst / "gone" / "SKILL.md").write_text("old")
    content.export_kind(fake_home / ".claude" / "skills", dst, bundle_rel="personal/skills")
    assert not (dst / "gone").exists()
    assert not list(bundle_dir.glob("**/*.bak-*"))  # export deletes the aside dir


def test_export_kind_missing_source_yields_empty(tmp_path, bundle_dir):
    res = content.export_kind(tmp_path / "nope", bundle_dir / "x", bundle_rel="x")
    assert res.units == [] and not (bundle_dir / "x").exists()


def test_list_units_files_and_dirs(fake_home):
    assert content.list_units(fake_home / ".claude" / "agents") == ["the-validator.md"]
    assert content.list_units(fake_home / ".claude" / "skills") == ["linked-skill", "real-skill"]


def test_replace_dir_keeps_aside_when_asked(tmp_path):
    old = tmp_path / "u"; old.mkdir(); (old / "f").write_text("old")
    new = tmp_path / "new"; new.mkdir(); (new / "f").write_text("new")
    aside = content.replace_dir(old, new, keep_aside=True)
    assert (old / "f").read_text() == "new" and aside and (aside / "f").read_text() == "old"


def test_export_kind_skips_broken_symlinks(fake_home, bundle_dir, capsys):
    os.symlink(fake_home / "nonexistent", fake_home / ".claude" / "skills" / "dead", target_is_directory=True)
    res = content.export_kind(fake_home / ".claude" / "skills", bundle_dir / "personal" / "skills",
                              bundle_rel="personal/skills")
    assert res.units == ["linked-skill", "real-skill"]          # "dead" skipped, no traceback
    assert "personal/skills/dead" not in res.symlinks
    assert not (bundle_dir / "personal/skills/dead").exists()
    assert "broken symlink" in capsys.readouterr().err


def test_export_kind_tolerates_dangling_symlink_inside_a_unit(fake_home, bundle_dir):
    os.symlink(fake_home / "nonexistent", fake_home / ".claude" / "skills" / "real-skill" / "ref")
    res = content.export_kind(fake_home / ".claude" / "skills", bundle_dir / "personal" / "skills",
                              bundle_rel="personal/skills")
    assert "real-skill" in res.units
    assert (bundle_dir / "personal/skills/real-skill/SKILL.md").exists()


def test_replace_dir_aside_names_do_not_collide(tmp_path, monkeypatch):
    class _Frozen:
        @staticmethod
        def now():
            return datetime(2026, 1, 2, 3, 4, 5, 678901)

    monkeypatch.setattr(content, "datetime", _Frozen)
    target = tmp_path / "u"; target.mkdir(); (target / "f").write_text("gen0")
    asides = []
    for i in (1, 2):
        new = tmp_path / f"new{i}"; new.mkdir(); (new / "f").write_text(f"gen{i}")
        asides.append(content.replace_dir(target, new, keep_aside=True))
    assert asides[0] != asides[1]
    assert all(a and a.is_dir() for a in asides)
    assert [(a / "f").read_text() for a in asides] == ["gen0", "gen1"]
    assert (target / "f").read_text() == "gen2"


def test_find_stale_artifacts(bundle_dir):
    (bundle_dir / "personal" / "skills").mkdir(parents=True)
    (bundle_dir / "personal" / "skills" / "keep").mkdir()
    stale_dir = bundle_dir / "personal" / "skills.bak-20260102T030405678901"
    stale_dir.mkdir(); (stale_dir / "inner").mkdir()
    stale_tmp = bundle_dir / "personal" / ".skills.ab12cd.tmp"
    stale_tmp.mkdir()
    stale_file = bundle_dir / "personal" / "settings.json.bak-20260102T030405678901"
    stale_file.write_text("{}")
    found = content.find_stale_artifacts(bundle_dir)
    assert found == sorted([stale_dir, stale_tmp, stale_file])   # matched dirs reported once, not descended
    assert content.find_stale_artifacts(bundle_dir / "nope") == []


@pytest.mark.skipif(os.name == "nt", reason="exec bits are POSIX")
def test_apply_exec_bits_sets_the_bit(tmp_path):
    root = tmp_path / "hooks"; root.mkdir()
    f = root / "x.sh"; f.write_text("#!/bin/sh\n"); f.chmod(0o644)
    content.apply_exec_bits(root, "harness/hooks", {"harness/hooks/x.sh": True})
    assert f.stat().st_mode & 0o111


@pytest.mark.skipif(os.name == "nt", reason="exec bits are POSIX")
def test_apply_exec_bits_ignores_other_prefixes_and_false(tmp_path):
    root = tmp_path / "hooks"; root.mkdir()
    f = root / "x.sh"; f.write_text("#!/bin/sh\n"); f.chmod(0o644)
    content.apply_exec_bits(root, "harness/hooks", {"personal/skills/x.sh": True, "harness/hooks/x.sh": False})
    assert not f.stat().st_mode & 0o111
