param(
  [Parameter(Mandatory = $true)]
  [string]$Snapshot,
  [switch]$DryRun,
  [switch]$ForceLive,
  [switch]$SkipSafetySnapshot,
  [object]$StopStackFirst = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$shouldStopStack = $true
if ($StopStackFirst -is [bool]) {
  $shouldStopStack = $StopStackFirst
} else {
  $normalized = [string]$StopStackFirst
  $shouldStopStack = @("1", "true", "yes", "on") -contains $normalized.ToLowerInvariant()
}

if ($shouldStopStack -and -not $ForceLive) {
  $stopScript = Join-Path $root "stop-stack.ps1"
  if (Test-Path $stopScript) {
    & $stopScript
  }
}

$arguments = @(".\\tools\\snapshot_manager.py", "restore", "--snapshot", $Snapshot, "--restored-by", "powershell", "--json")
if ($DryRun) { $arguments += "--dry-run" }
if ($ForceLive) { $arguments += "--force-live" }
if ($SkipSafetySnapshot) { $arguments += "--skip-safety-snapshot" }

Push-Location $root
try {
  & $python @arguments
}
finally {
  Pop-Location
}
