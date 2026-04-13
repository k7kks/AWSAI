param(
  [string]$Label = "",
  [int]$KeepLatest = 20
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

Push-Location $root
try {
  & $python ".\\tools\\snapshot_manager.py" create --label $Label --keep-latest $KeepLatest --created-by powershell --json
}
finally {
  Pop-Location
}
