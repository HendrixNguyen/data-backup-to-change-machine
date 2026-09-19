import hashlib, os
from claude_backup import manifest


def test_sha256_of_file(tmp_path):
    f = tmp_path / "a"; f.write_bytes(b"hello")
    assert manifest.sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_build_and_write_manifest(bundle_dir):
    (bundle_dir / "personal" / "skills" / "s").mkdir(parents=True)
    f = bundle_dir / "personal" / "skills" / "s" / "SKILL.md"; f.write_text("x")
    m = manifest.build(bundle_dir, scopes=("personal",), claude_version="2.1.0",
                       symlinks={"personal/skills/s": "/home/u/.agents/skills/s"}, exec_bits={"personal/skills/s/SKILL.md": False})
    assert m["version"] == 1 and m["scopes"] == ["personal"]
    assert m["files"]["personal/skills/s/SKILL.md"]["sha256"] == manifest.sha256_file(f)
    assert m["symlinks"] == {"personal/skills/s": "/home/u/.agents/skills/s"}
    manifest.write(bundle_dir, m)
    assert manifest.read(bundle_dir)["host"] == m["host"]


def test_verify_hashes_detects_tamper(bundle_dir):
    (bundle_dir / "personal").mkdir()
    f = bundle_dir / "personal" / "x.json"; f.write_text("1")
    manifest.write(bundle_dir, manifest.build(bundle_dir, scopes=("personal",), claude_version=None, symlinks={}, exec_bits={}))
    assert manifest.verify_hashes(bundle_dir) == []
    f.write_text("2")
    assert manifest.verify_hashes(bundle_dir) == ["personal/x.json"]


def test_verify_hashes_detects_deleted_file(bundle_dir):
    (bundle_dir / "personal").mkdir()
    f = bundle_dir / "personal" / "x.json"; f.write_text("1")
    manifest.write(bundle_dir, manifest.build(bundle_dir, scopes=("personal",), claude_version=None, symlinks={}, exec_bits={}))
    assert manifest.verify_hashes(bundle_dir) == []
    f.unlink()
    assert manifest.verify_hashes(bundle_dir) == ["personal/x.json"]


def test_manifest_paths_use_forward_slashes(bundle_dir):
    (bundle_dir / "harness" / "hooks").mkdir(parents=True)
    (bundle_dir / "harness" / "hooks" / "h.sh").write_text("#!/bin/sh\n")
    m = manifest.build(bundle_dir, scopes=("harness",), claude_version=None, symlinks={}, exec_bits={})
    assert "harness/hooks/h.sh" in m["files"]
