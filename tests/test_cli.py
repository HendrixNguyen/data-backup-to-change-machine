import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "backup.py"


def test_version_flag_prints_version():
    out = subprocess.run([sys.executable, str(CLI), "--version"], capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.strip() == "claude-backup 0.1.0"


def test_no_subcommand_exits_2_with_usage():
    out = subprocess.run([sys.executable, str(CLI)], capture_output=True, text=True)
    assert out.returncode == 2
    assert "usage:" in out.stderr
