param(
  [string]$BaseUrl = "http://127.0.0.1:4173/v1",
  [string]$Model = "gpt-5.4",
  [string]$ReasoningEffort = "high",
  [string]$ProviderKey = "relay-local",
  [string]$ProviderName = "Relay Local",
  [string]$ApiKey = "",
  [string]$ConfigDir = "$env:USERPROFILE\\.codex",
  [string]$BackupRoot = "$env:USERPROFILE\\.codex-relay-backups",
  [switch]$RestoreLatest
)

$ErrorActionPreference = "Stop"

function Ensure-Directory([string]$Path) {
  New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Write-JsonFile([string]$Path, [hashtable]$Data) {
  $json = $Data | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Copy-IfExists([string]$Source, [string]$DestinationDirectory) {
  if (Test-Path $Source) {
    Copy-Item -LiteralPath $Source -Destination $DestinationDirectory -Force
  }
}

Ensure-Directory $ConfigDir
Ensure-Directory $BackupRoot

$configPath = Join-Path $ConfigDir "config.toml"
$authPath = Join-Path $ConfigDir "auth.json"

if ($RestoreLatest) {
  $latestBackup = Get-ChildItem -Path $BackupRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
  if (-not $latestBackup) {
    throw "No Codex backup was found in $BackupRoot"
  }

  Copy-IfExists (Join-Path $latestBackup.FullName "config.toml") $ConfigDir
  Copy-IfExists (Join-Path $latestBackup.FullName "auth.json") $ConfigDir

  Write-Host "Restored Codex config from $($latestBackup.FullName)"
  exit 0
}

if (-not $ApiKey) {
  throw "ApiKey is required unless -RestoreLatest is used."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $BackupRoot $timestamp
Ensure-Directory $backupDir
Copy-IfExists $configPath $backupDir
Copy-IfExists $authPath $backupDir

$configToml = @"
model_provider = "$ProviderKey"
model = "$Model"
model_reasoning_effort = "$ReasoningEffort"
disable_response_storage = false

[windows]
sandbox = "elevated"

[model_providers.$ProviderKey]
name = "$ProviderName"
base_url = "$BaseUrl"
wire_api = "responses"
requires_openai_auth = true
"@

[System.IO.File]::WriteAllText($configPath, $configToml, [System.Text.UTF8Encoding]::new($false))
Write-JsonFile $authPath @{ OPENAI_API_KEY = $ApiKey }

Write-Host "Codex relay config written."
Write-Host "Base URL: $BaseUrl"
Write-Host "Model:    $Model"
Write-Host "Backup:   $backupDir"
Write-Host ""
Write-Host "If you want to roll back later:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -RestoreLatest"
