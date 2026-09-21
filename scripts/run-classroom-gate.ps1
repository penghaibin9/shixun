param(
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$DatabaseName = 'yueke_e_gate'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $passwordEntry) { throw 'MYSQL_PASSWORD is missing' }
$escaped = [System.Uri]::EscapeDataString($passwordEntry.Substring('MYSQL_PASSWORD='.Length))
$env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escaped}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
$env:YUEKE_RUNTIME_BASE_URL = 'http://127.0.0.1:18003'
$env:YUEKE_TEACHING_BASE_URL = 'http://127.0.0.1:18003'
$env:YUEKE_GRADING_BASE_URL = 'http://127.0.0.1:18003'
$env:YUEKE_GATE_API_URL = 'http://127.0.0.1:18003'
$env:E2E_REAL_CLASSROOM = '1'
$previousPythonPath = $env:PYTHONPATH
try {
  $env:PYTHONPATH = (Join-Path $repoRoot 'backend')
  python (Join-Path $repoRoot 'tests/seed_classroom_gate.py')
  if ($LASTEXITCODE -ne 0) { throw 'G7 gate data preparation failed' }
  Push-Location (Join-Path $repoRoot 'frontend')
  try {
    npx playwright test e2e/lab-classroom-live.spec.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'G7 browser gate failed' }
  } finally {
    Pop-Location
  }
} finally {
  $env:PYTHONPATH = $previousPythonPath
}
