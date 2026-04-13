param(
  [string]$Version = (Get-Date -Format "yyyyMMdd-HHmmss")
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $root "dist"
$stageRoot = Join-Path $distDir "stage"
$packageName = "kiro-relay-$Version"
$stageDir = Join-Path $stageRoot $packageName
$archivePath = Join-Path $distDir "$packageName.zip"

$files = @(
  ".env.example",
  "bootstrap-admin.ps1",
  "build-release.ps1",
  "configure-codex-relay.ps1",
  "index.html",
  "README.md",
  "requirements.txt",
  "server.py",
  "snapshot-backup.ps1",
  "snapshot-list.ps1",
  "snapshot-restore.ps1",
  "start.ps1",
  "start-stack.ps1",
  "stop-stack.ps1"
)

$directories = @(
  "assets",
  "deploy",
  "tools"
)

if (Test-Path $stageDir) {
  Remove-Item -LiteralPath $stageDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stageDir "upstream") | Out-Null

foreach ($file in $files) {
  $source = Join-Path $root $file
  if (Test-Path $source) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $stageDir $file) -Force
  }
}

foreach ($directory in $directories) {
  $source = Join-Path $root $directory
  if (Test-Path $source) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $stageDir $directory) -Recurse -Force
  }
}

Get-ChildItem -Path $stageDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $stageDir -Recurse -File -Include "*.pyc" -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue

$upstreamZip = Join-Path $root "upstream\\claude-server-windows-amd64.zip"
if (Test-Path $upstreamZip) {
  Copy-Item -LiteralPath $upstreamZip -Destination (Join-Path $stageDir "upstream\\claude-server-windows-amd64.zip") -Force
}

$buildInfo = [PSCustomObject]@{
  packageName = $packageName
  builtAt = (Get-Date).ToString("s")
  sourceRoot = $root
}
$buildInfo | ConvertTo-Json | Set-Content -Path (Join-Path $stageDir "BUILD_INFO.json") -Encoding utf8

if (Test-Path $archivePath) {
  Remove-Item -LiteralPath $archivePath -Force
}

Compress-Archive -Path (Join-Path $stageRoot $packageName) -DestinationPath $archivePath -Force

Write-Host "Release package created:"
Write-Host "  $archivePath"
