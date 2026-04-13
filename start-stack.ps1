param(
  [string]$BindHost = "0.0.0.0",
  [int]$PortalPort = 4173,
  [int]$AdminPort = 62311,
  [string]$UpstreamAdminPassword = "RelayAdmin!2026#AWS",
  [string]$AdminEmail = "admin@relay.local",
  [string]$AdminPassword = "RelayPortal!2026#Admin",
  [string]$AdminName = "Relay Admin",
  [string]$PublicPortalBaseUrl = "",
  [string]$PublicApiBaseUrl = "",
  [string]$PublicAdminBaseUrl = "",
  [string]$Sub2ApiBaseUrl = "",
  [string]$Sub2ApiPublicUrl = "",
  [string]$Sub2ApiAdminUrl = "",
  [string]$Sub2ApiApiBaseUrl = "",
  [string]$Sub2ApiHealthUrl = "",
  [string]$Sub2ApiAdminApiKey = "",
  [switch]$EnableSub2Api
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root "run"
$logDir = Join-Path $runDir "logs"
$pidFile = Join-Path $runDir "services.json"
$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
$portalScript = Join-Path $root "server.py"
$upstreamExe = Join-Path $root "upstream\\claude-server\\claude-server-windows-amd64.exe"
$upstreamZip = Join-Path $root "upstream\\claude-server-windows-amd64.zip"
$upstreamExtractDir = Join-Path $root "upstream\\claude-server"
$upstreamDataDir = Join-Path $root "upstream\\data"

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $upstreamDataDir | Out-Null
New-Item -ItemType Directory -Force -Path $upstreamExtractDir | Out-Null

function Stop-IfRunning($processId) {
  if (-not $processId) { return }
  try {
    $proc = Get-Process -Id $processId -ErrorAction Stop
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  } catch {
  }
}

if (Test-Path $pidFile) {
  $existing = Get-Content $pidFile -Raw | ConvertFrom-Json
  Stop-IfRunning $existing.portalPid
  Stop-IfRunning $existing.adminPid
}

if (-not (Test-Path $upstreamExe)) {
  if (-not (Test-Path $upstreamZip)) {
    throw "Missing upstream binary. Expected '$upstreamExe' or '$upstreamZip'."
  }
  Expand-Archive -Path $upstreamZip -DestinationPath $upstreamExtractDir -Force
  $candidate = Get-ChildItem -Path $upstreamExtractDir -Recurse -Filter "claude-server-windows-amd64.exe" | Select-Object -First 1
  if (-not $candidate) {
    throw "Unable to extract claude-server-windows-amd64.exe from $upstreamZip"
  }
  $upstreamExe = $candidate.FullName
}

$portalOut = Join-Path $logDir "portal.stdout.log"
$portalErr = Join-Path $logDir "portal.stderr.log"
$adminOut = Join-Path $logDir "admin.stdout.log"
$adminErr = Join-Path $logDir "admin.stderr.log"

$adminProc = Start-Process $upstreamExe `
  -ArgumentList "-data-dir", $upstreamDataDir, "-port", $AdminPort, "-no-browser" `
  -WorkingDirectory $upstreamDataDir `
  -RedirectStandardOutput $adminOut `
  -RedirectStandardError $adminErr `
  -PassThru

Start-Sleep -Seconds 4

$env:RELAY_UPSTREAM_URL = "http://127.0.0.1:$AdminPort"
$env:RELAY_UPSTREAM_ADMIN_PASSWORD = $UpstreamAdminPassword
$env:RELAY_BOOTSTRAP_ADMIN_EMAIL = $AdminEmail
$env:RELAY_BOOTSTRAP_ADMIN_PASSWORD = $AdminPassword
$env:RELAY_BOOTSTRAP_ADMIN_NAME = $AdminName

if ($PublicPortalBaseUrl) { $env:RELAY_PUBLIC_PORTAL_BASE_URL = $PublicPortalBaseUrl }
if ($PublicApiBaseUrl) { $env:RELAY_PUBLIC_API_BASE_URL = $PublicApiBaseUrl }
if ($PublicAdminBaseUrl) { $env:RELAY_PUBLIC_ADMIN_BASE_URL = $PublicAdminBaseUrl }
if ($PSBoundParameters.ContainsKey("EnableSub2Api")) { $env:RELAY_SUB2API_ENABLED = if ($EnableSub2Api) { "true" } else { "false" } }
if ($Sub2ApiBaseUrl) { $env:RELAY_SUB2API_BASE_URL = $Sub2ApiBaseUrl }
if ($Sub2ApiPublicUrl) { $env:RELAY_SUB2API_PUBLIC_URL = $Sub2ApiPublicUrl }
if ($Sub2ApiAdminUrl) { $env:RELAY_SUB2API_ADMIN_URL = $Sub2ApiAdminUrl }
if ($Sub2ApiApiBaseUrl) { $env:RELAY_SUB2API_API_BASE_URL = $Sub2ApiApiBaseUrl }
if ($Sub2ApiHealthUrl) { $env:RELAY_SUB2API_HEALTH_URL = $Sub2ApiHealthUrl }
if ($Sub2ApiAdminApiKey) { $env:RELAY_SUB2API_ADMIN_API_KEY = $Sub2ApiAdminApiKey }

$portalProc = Start-Process $python `
  -ArgumentList $portalScript, "serve", "--host", $BindHost, "--port", $PortalPort `
  -WorkingDirectory $root `
  -RedirectStandardOutput $portalOut `
  -RedirectStandardError $portalErr `
  -PassThru

$lanIPs = Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {
    $_.IPAddress -notlike "127.*" -and
    $_.IPAddress -notlike "169.254*" -and
    $_.IPAddress -notlike "198.18.*" -and
    $_.IPAddress -notlike "192.168.56.*"
  } |
  Select-Object -ExpandProperty IPAddress

$data = [PSCustomObject]@{
  host = $BindHost
  portalPort = $PortalPort
  adminPort = $AdminPort
  portalPid = $portalProc.Id
  adminPid = $adminProc.Id
  startedAt = (Get-Date).ToString("s")
}
$data | ConvertTo-Json | Set-Content -Encoding utf8 $pidFile

Write-Host "Portal PID: $($portalProc.Id)"
Write-Host "Admin PID:  $($adminProc.Id)"
Write-Host "Portal local: http://127.0.0.1:$PortalPort"
Write-Host "Admin local:  http://127.0.0.1:$AdminPort"
Write-Host "Portal admin bootstrap: $AdminEmail"

foreach ($ip in $lanIPs) {
  Write-Host "Portal LAN:   http://$ip`:$PortalPort"
  Write-Host "Admin LAN:    http://$ip`:$AdminPort"
}

Write-Host "Logs:"
Write-Host "  $portalOut"
Write-Host "  $adminOut"
