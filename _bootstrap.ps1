# Shared PowerShell bootstrapper: find Python >= 3.11 or install via winget, then run bin\backup.py <sub> @args.
param([Parameter(Mandatory=$true)][string]$Sub, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Rest = @($Rest)
function Find-Py {
  foreach ($c in @("py -3", "python3.13", "python3.12", "python3.11", "python3", "python")) {
    $parts = $c.Split(" ", 2)
    $exe = $parts[0]
    $argv = @()
    if ($parts.Count -gt 1 -and $parts[1]) { $argv += $parts[1] }
    try {
      & $exe @argv -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { return $c }
    } catch {}
  }
  return $null
}
$Py = Find-Py
if (-not $Py) {
  Write-Host "claude-backup: Python 3.11+ not found, installing via winget..."
  if (Get-Command winget -ErrorAction SilentlyContinue) { winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements }
  else { Write-Error "claude-backup: winget not found. Install Python 3.11+ from https://www.python.org/downloads/ and re-run."; exit 1 }
  $Py = Find-Py
  if (-not $Py) { Write-Error "claude-backup: Python install did not produce a usable python"; exit 1 }
}
$parts = $Py.Split(" ", 2)
$exe = $parts[0]
$argv = @()
if ($parts.Count -gt 1 -and $parts[1]) { $argv += $parts[1] }
if ($Rest.Count -gt 0 -and $Rest[0] -in @("--version", "-h", "--help")) { & $exe @argv "$Here\bin\backup.py" @Rest; exit $LASTEXITCODE }
& $exe @argv "$Here\bin\backup.py" $Sub @Rest
exit $LASTEXITCODE
