param(
  [string]$GateScript = 'tests/runtime_gate.py',
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$DatabaseName = 'yueke_d_dev'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $passwordEntry) { throw 'MYSQL_PASSWORD is missing' }
$escaped = [System.Uri]::EscapeDataString($passwordEntry.Substring('MYSQL_PASSWORD='.Length))
$gateEnvironmentNames = @(
  'YUEKE_AGENT_ALLOWED_DIGESTS',
  'YUEKE_AGENT_GRADER_DIGEST',
  'YUEKE_DATABASE_URL',
  'YUEKE_GATE_API_URL',
  'YUEKE_GATE_IMAGE_DIGEST',
  'YUEKE_LAB_CATALOG_TOKEN',
  'YUEKE_LAB_CATALOG_URL',
  'YUEKE_NODE_AGENT_TOKEN'
)
$previousEnvironment = @{}
foreach ($name in $gateEnvironmentNames) {
  $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, 'Process')
}
$agent = $null
$api = $null
try {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escaped}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  $env:YUEKE_NODE_AGENT_TOKEN = [guid]::NewGuid().ToString('N')
  $env:YUEKE_LAB_CATALOG_URL = 'http://127.0.0.1:18080'
  $env:YUEKE_LAB_CATALOG_TOKEN = [guid]::NewGuid().ToString('N')
  $imageId = docker image inspect python:3.11-bookworm --format '{{.Id}}'
  if (-not $imageId.StartsWith('sha256:')) { throw 'Pinned Python OpenSSL image is missing' }
  $env:YUEKE_AGENT_ALLOWED_DIGESTS = $imageId
  $env:YUEKE_AGENT_GRADER_DIGEST = $imageId
  $env:YUEKE_GATE_IMAGE_DIGEST = $imageId
  $env:YUEKE_GATE_API_URL = 'http://127.0.0.1:18080'
  $agent = Start-Process python -ArgumentList '-m','uvicorn','app:app','--host','127.0.0.1','--port','19443' -WorkingDirectory (Join-Path $repoRoot 'node_agent') -PassThru -WindowStyle Hidden
  $api = Start-Process python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18080' -WorkingDirectory (Join-Path $repoRoot 'backend') -PassThru -WindowStyle Hidden
  $ready = $false
  foreach ($attempt in 1..30) {
    try { if ((Invoke-WebRequest 'http://127.0.0.1:18080/health' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) { $ready = $true; break } } catch { Start-Sleep -Milliseconds 300 }
  }
  if (-not $ready) { throw 'Control API failed to start' }
  python (Join-Path $repoRoot $GateScript)
  if ($LASTEXITCODE -ne 0) { throw 'Runtime gate failed' }
} finally {
  if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
  if ($agent -and -not $agent.HasExited) { Stop-Process -Id $agent.Id -Force }
  foreach ($name in $gateEnvironmentNames) {
    if ($null -eq $previousEnvironment[$name]) {
      Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
      [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
  }
}
