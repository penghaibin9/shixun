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
$gateEnvironmentNames = @(
  'E2E_REAL_RUNTIME',
  'YUEKE_AGENT_ALLOWED_DIGESTS',
  'YUEKE_DATABASE_URL',
  'YUEKE_GATE_API_URL',
  'YUEKE_GATE_IMAGE_DIGEST',
  'YUEKE_GRADING_BASE_URL',
  'YUEKE_INTERNAL_RUNTIME_TOKEN',
  'YUEKE_LAB_CATALOG_TOKEN',
  'YUEKE_LAB_CATALOG_URL',
  'YUEKE_NODE_AGENT_TOKEN',
  'YUEKE_RUNTIME_BASE_URL',
  'YUEKE_TEACHING_BASE_URL'
)
$previousEnvironment = @{}
foreach ($name in $gateEnvironmentNames) {
  $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, 'Process')
}
$agent = $null
try {
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
    # 学生真实启动/终端用例会留下管理员页所需的镜像、节点和已销毁实例事实，必须先串行完成。
    npx playwright test e2e/lab-runtime-live.spec.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'Student runtime browser gate failed' }
    npx playwright test e2e/lab-runtime-admin.spec.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'Administrator runtime browser gate failed' }
  } finally {
    Pop-Location
  }
} finally {
  if ($agent -and -not $agent.HasExited) { Stop-Process -Id $agent.Id -Force }
  foreach ($name in $gateEnvironmentNames) {
    if ($null -eq $previousEnvironment[$name]) {
      Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
      [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
  }
}
