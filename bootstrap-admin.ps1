param(
  [Parameter(Mandatory = $true)]
  [string]$Email,
  [Parameter(Mandatory = $true)]
  [string]$Password,
  [string]$Name = "Relay Admin"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

Push-Location $root
try {
  & $python .\server.py bootstrap-admin --email $Email --password $Password --name $Name
}
finally {
  Pop-Location
}
