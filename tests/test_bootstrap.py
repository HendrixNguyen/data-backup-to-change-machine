import os, shutil, subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name == "nt", reason="POSIX bootstrapper")
@pytest.mark.parametrize("name", ["export.sh", "restore.sh", "doctor.sh"])
def test_sh_bootstrapper_reaches_python(name):
    out = subprocess.run(["sh", str(ROOT / name), "--version"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "claude-backup 0.1.0"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("pwsh") and not shutil.which("powershell"), reason="PowerShell bootstrapper")
@pytest.mark.parametrize("name", ["export.ps1", "restore.ps1", "doctor.ps1"])
def test_ps1_bootstrapper_reaches_python(name):
    ps = shutil.which("pwsh") or shutil.which("powershell")
    out = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / name), "--version"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "claude-backup 0.1.0"
