param(
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$DatabaseName = 'yueke_d_dev'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $passwordEntry) { throw 'MYSQL_PASSWORD is missing' }
$escaped = [System.Uri]::EscapeDataString($passwordEntry.Substring('MYSQL_PASSWORD='.Length))
$env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escaped}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
$env:YUEKE_NODE_AGENT_TOKEN = [guid]::NewGuid().ToString('N')
$env:YUEKE_INTERNAL_RUNTIME_TOKEN = [guid]::NewGuid().ToString('N')
$env:YUEKE_LAB_CATALOG_TOKEN = [guid]::NewGuid().ToString('N')
$env:YUEKE_LAB_CATALOG_URL = 'http://127.0.0.1:18003'
$env:YUEKE_RUNTIME_BASE_URL = 'http://127.0.0.1:18003'
$env:YUEKE_TEACHING_BASE_URL = 'http://127.0.0.1:18003'
$env:YUEKE_GRADING_BASE_URL = 'http://127.0.0.1:18003'
$env:YUEKE_GATE_API_URL = 'http://127.0.0.1:18003'
$env:E2E_REAL_RUNTIME = '1'
$imageId = docker image inspect python:3.11-bookworm --format '{{.Id}}'
if (-not $imageId.StartsWith('sha256:')) { throw 'Pinned Python OpenSSL image is missing' }
$env:YUEKE_AGENT_ALLOWED_DIGESTS = $imageId
$env:YUEKE_GATE_IMAGE_DIGEST = $imageId
$agent = $null
try {
  $agent = Start-Process python -ArgumentList '-m','uvicorn','app:app','--host','127.0.0.1','--port','19443' -WorkingDirectory (Join-Path $repoRoot 'node_agent') -PassThru -WindowStyle Hidden
  $ready = $false
  foreach ($attempt in 1..30) {
    try {
      $headers = @{ Authorization = "Bearer $env:YUEKE_NODE_AGENT_TOKEN" }
      if ((Invoke-WebRequest 'http://127.0.0.1:19443/health' -Headers $headers -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 300 }
  }
  if (-not $ready) { throw 'Node Agent failed to start' }
  Push-Location (Join-Path $repoRoot 'frontend')
  try {
    npx playwright test e2e/lab-runtime-live.spec.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'Runtime browser gate failed' }
  } finally {
    Pop-Location
  }
} finally {
  if ($agent -and -not $agent.HasExited) { Stop-Process -Id $agent.Id -Force }
}
