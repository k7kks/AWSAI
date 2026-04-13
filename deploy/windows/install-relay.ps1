param(
  [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\\python.exe"
$upstreamZip = Join-Path $root "upstream\\claude-server-windows-amd64.zip"
$upstreamDir = Join-Path $root "upstream\\claude-server"
$upstreamExe = Join-Path $upstreamDir "claude-server-windows-amd64.exe"

if (-not (Test-Path $venvPython)) {
  & $PythonCommand -m venv $venvDir
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")

if (-not (Test-Path $upstreamExe) -and (Test-Path $upstreamZip)) {
  New-Item -ItemType Directory -Force -Path $upstreamDir | Out-Null
  Expand-Archive -Path $upstreamZip -DestinationPath $upstreamDir -Force
}

Write-Host "Windows runtime is ready."
Write-Host "Start with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\\start-stack.ps1"
