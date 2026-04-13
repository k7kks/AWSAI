$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "run\\services.json"

if (-not (Test-Path $pidFile)) {
  Write-Host "No running stack metadata found."
  exit 0
}

$data = Get-Content $pidFile -Raw | ConvertFrom-Json

foreach ($processId in @($data.portalPid, $data.adminPid)) {
  if ($processId) {
    try {
      Stop-Process -Id $processId -Force
      Write-Host "Stopped PID $processId"
    } catch {
    }
  }
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
