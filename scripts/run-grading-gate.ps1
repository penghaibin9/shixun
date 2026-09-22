param(
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$DatabaseName = 'yueke_g8_gate'
)
$ErrorActionPreference = 'Stop'
if ($DatabaseName.ToLowerInvariant() -notlike '*g8*' -or $DatabaseName.ToLowerInvariant() -notlike '*gate*') {
  throw 'G8 gate database name must contain both g8 and gate'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$rootEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_ROOT_PASSWORD=*' } | Select-Object -First 1
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $rootEntry -or -not $passwordEntry) { throw 'MySQL gate credentials are missing' }
$rootPassword = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$databasePassword = $passwordEntry.Substring('MYSQL_PASSWORD='.Length)

$sql = "CREATE DATABASE IF NOT EXISTS ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON ``$DatabaseName``.* TO 'yueke_dev'@'%'; FLUSH PRIVILEGES;"
docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -e $sql
if ($LASTEXITCODE -ne 0) { throw 'G8 gate database preparation failed' }

$escaped = [System.Uri]::EscapeDataString($databasePassword)
$gateEnvironmentNames = @(
  'PATH',
  'PYTHONPATH',
  'E2E_REAL_GRADING',
  'YUEKE_DATABASE_URL',
  'YUEKE_ENV',
  'YUEKE_GRADING_BASE_URL',
  'YUEKE_ALLOW_DEV_IDENTITY_HEADERS',
  'YUEKE_RESOURCE_UPLOAD_DIR',
  'YUEKE_RUNTIME_BASE_URL',
  'YUEKE_TEACHING_BASE_URL'
)
$previousEnvironment = @{}
foreach ($name in $gateEnvironmentNames) {
  $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escaped}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  $env:YUEKE_ENV = 'test'
  $env:YUEKE_ALLOW_DEV_IDENTITY_HEADERS = '1'
  $env:YUEKE_RUNTIME_BASE_URL = 'http://127.0.0.1:18003'
  $env:YUEKE_TEACHING_BASE_URL = 'http://127.0.0.1:18003'
  $env:YUEKE_GRADING_BASE_URL = 'http://127.0.0.1:18003'
  $env:YUEKE_RESOURCE_UPLOAD_DIR = Join-Path ([System.IO.Path]::GetTempPath()) 'yueke-g8-gate-artifacts'
  $env:E2E_REAL_GRADING = '1'
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  $env:PATH = "$(Split-Path -Parent $python);$($previousEnvironment['PATH'])"
  Push-Location (Join-Path $repoRoot 'backend')
  try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'G8 gate migration failed' }
  } finally {
    Pop-Location
  }
  & $python (Join-Path $repoRoot 'tests/seed_grading_gate.py')
  if ($LASTEXITCODE -ne 0) { throw 'G8 gate data preparation failed' }
  Push-Location (Join-Path $repoRoot 'frontend')
  try {
    npx playwright test e2e/grading-live.spec.ts --config=playwright.grading.config.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'G8 browser gate failed' }
  } finally {
    Pop-Location
  }
} finally {
  foreach ($name in $gateEnvironmentNames) {
    if ($null -eq $previousEnvironment[$name]) {
      Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
      [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
  }
}
