param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 4173,
  [string]$UpstreamUrl = "http://127.0.0.1:62311",
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
$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$env:RELAY_UPSTREAM_URL = $UpstreamUrl
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

Write-Host "Serving Kiro Relay Portal from $root"
Write-Host "Portal URL: http://127.0.0.1:$Port"
Write-Host "Admin bootstrap: $AdminEmail"

Start-Process "http://127.0.0.1:$Port"

Push-Location $root
try {
  & $python .\server.py serve --host $BindHost --port $Port
}
finally {
  Pop-Location
}
