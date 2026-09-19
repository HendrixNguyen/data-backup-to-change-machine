import os
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
