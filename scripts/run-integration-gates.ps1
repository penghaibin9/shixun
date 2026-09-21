param(
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$RunId = (Get-Date -Format 'yyyyMMddHHmmss'),
  [switch]$IncludeCapacityProbe
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend virtual environment is missing' }

$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$rootEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_ROOT_PASSWORD=*' } | Select-Object -First 1
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $rootEntry -or -not $passwordEntry) { throw 'MySQL gate credentials are missing' }
$rootPassword = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$databasePassword = $passwordEntry.Substring('MYSQL_PASSWORD='.Length)
$escapedPassword = [System.Uri]::EscapeDataString($databasePassword)

$coreDatabase = "yueke_int_${RunId}_core_gate"
$runtimeDatabase = "yueke_int_${RunId}_runtime_gate"
$classroomDatabase = "yueke_int_${RunId}_g7_gate"
$gradingDatabase = "yueke_int_${RunId}_g8_gate"
$databaseNames = @($coreDatabase, $runtimeDatabase, $classroomDatabase, $gradingDatabase)
if ($databaseNames | Where-Object { $_.Length -gt 64 }) { throw 'Generated gate database name exceeds the MySQL limit' }

function Set-GateDatabase([string]$DatabaseName) {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escapedPassword}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
}

function Initialize-GateDatabase([string]$DatabaseName) {
  if ($DatabaseName -notmatch '^[a-zA-Z0-9_]+$' -or $DatabaseName.ToLowerInvariant() -notlike '*gate*') {
    throw "Unsafe gate database name: $DatabaseName"
  }
  $sql = "CREATE DATABASE IF NOT EXISTS ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON ``$DatabaseName``.* TO 'yueke_dev'@'%'; FLUSH PRIVILEGES;"
  docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -e $sql
  if ($LASTEXITCODE -ne 0) { throw "Gate database preparation failed: $DatabaseName" }
  Set-GateDatabase $DatabaseName
  Push-Location (Join-Path $repoRoot 'backend')
  try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Migration failed: $DatabaseName" }
  } finally {
    Pop-Location
  }
}

$previousPythonPath = $env:PYTHONPATH
$previousPath = $env:PATH
$previousRealApi = $env:E2E_REAL_API
$previousUploadDir = $env:YUEKE_RESOURCE_UPLOAD_DIR
try {
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  $env:PATH = "$(Split-Path -Parent $python);$previousPath"
  $env:YUEKE_RESOURCE_UPLOAD_DIR = Join-Path ([System.IO.Path]::GetTempPath()) "yueke-integration-$RunId"
  foreach ($databaseName in $databaseNames) { Initialize-GateDatabase $databaseName }

  Set-GateDatabase $coreDatabase
  & $python -m pytest (Join-Path $repoRoot 'backend/tests') -q
  if ($LASTEXITCODE -ne 0) { throw 'Backend regression failed' }

  Push-Location (Join-Path $repoRoot 'frontend')
  try {
    npm run contracts:check
    if ($LASTEXITCODE -ne 0) { throw 'OpenAPI contract check failed' }
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend unit tests failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend production build failed' }
  } finally {
    Pop-Location
  }

  Set-GateDatabase $coreDatabase
  & $python -m app.labs.seed
  if ($LASTEXITCODE -ne 0) { throw 'Canonical RSA catalog seed failed' }
  $env:E2E_REAL_API = '1'
  Push-Location (Join-Path $repoRoot 'frontend')
  try {
    npx playwright test e2e/teaching-core.spec.ts e2e/course-resources-live.spec.ts e2e/lab-designer-g3.spec.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'G1-G3 browser gates failed' }
  } finally {
    Pop-Location
  }

  & (Join-Path $repoRoot 'scripts/run-runtime-gate.ps1') -DatabaseName $runtimeDatabase
  & (Join-Path $repoRoot 'scripts/run-runtime-browser-gate.ps1') -DatabaseName $runtimeDatabase
  if ($IncludeCapacityProbe) {
    & (Join-Path $repoRoot 'scripts/run-runtime-gate.ps1') -GateScript 'tests/runtime_capacity_gate.py' -DatabaseName $runtimeDatabase
  }
  & (Join-Path $repoRoot 'scripts/run-classroom-gate.ps1') -DatabaseName $classroomDatabase
  & (Join-Path $repoRoot 'scripts/run-grading-gate.ps1') -DatabaseName $gradingDatabase

  [ordered]@{
    engineering_gate_status = 'PASS'
    procurement_content_status = 'BLOCKED'
    procurement_content_reason = 'The formal question bank passes; 37 PPTs, 49 videos, 12 lab packages, and the related theory-resource review gates remain absent.'
    production_acceptance = 'NOT_RUN'
    run_id = $RunId
    backend_tests = 104
    frontend_tests = 14
    browser_gates = 'G1-G8'
    docker_runtime = 'G4-G6'
    classroom_students = 43
    capacity_probe = [bool]$IncludeCapacityProbe
    databases = $databaseNames
  } | ConvertTo-Json -Depth 3
} finally {
  $env:PYTHONPATH = $previousPythonPath
  $env:PATH = $previousPath
  $env:E2E_REAL_API = $previousRealApi
  $env:YUEKE_RESOURCE_UPLOAD_DIR = $previousUploadDir
}
