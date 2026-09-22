param(
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$RunId = (Get-Date -Format 'yyyyMMddHHmmss'),
  [switch]$IncludeCapacityProbe,
  [string]$RuntimeAgentUrl = 'http://127.0.0.1:19443',
  [bool]$StartLocalRuntimeAgent = $true
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend virtual environment is missing' }
$ffprobeCommand = Get-Command ffprobe -ErrorAction SilentlyContinue
$ffprobe = if ($ffprobeCommand) { $ffprobeCommand.Source } else {
  Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft/WinGet/Packages') -Recurse -Filter 'ffprobe.exe' -ErrorAction SilentlyContinue |
    Where-Object FullName -Match 'Gyan\.FFmpeg_' |
    Sort-Object FullName -Descending |
    Select-Object -ExpandProperty FullName -First 1
}
if (-not $ffprobe) { throw 'ffprobe is required for the formal course-video gate' }

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

$gateEnvironmentNames = @(
  'PATH',
  'PYTHONPATH',
  'E2E_REAL_API',
  'E2E_REAL_CLASSROOM',
  'E2E_REAL_GRADING',
  'E2E_REAL_RUNTIME',
  'YUEKE_AGENT_ALLOWED_DIGESTS',
  'YUEKE_AGENT_GRADER_DIGEST',
  'YUEKE_DATABASE_URL',
  'YUEKE_ENV',
  'YUEKE_FFPROBE',
  'YUEKE_GATE_API_URL',
  'YUEKE_GATE_IMAGE_DIGEST',
  'YUEKE_GRADING_BASE_URL',
  'YUEKE_INTERNAL_RUNTIME_TOKEN',
  'YUEKE_ALLOW_DEV_IDENTITY_HEADERS',
  'YUEKE_LAB_CATALOG_TOKEN',
  'YUEKE_LAB_CATALOG_URL',
  'YUEKE_NODE_AGENT_TOKEN',
  'YUEKE_RESOURCE_UPLOAD_DIR',
  'YUEKE_RUNTIME_BASE_URL',
  'YUEKE_TEACHING_BASE_URL'
)
$previousEnvironment = @{}
foreach ($name in $gateEnvironmentNames) {
  $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  $env:YUEKE_FFPROBE = $ffprobe
  $env:YUEKE_ENV = 'test'
  $env:YUEKE_ALLOW_DEV_IDENTITY_HEADERS = '1'
  $env:PATH = "$(Split-Path -Parent $ffprobe);$(Split-Path -Parent $python);$($previousEnvironment['PATH'])"
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
  $env:YUEKE_GATE_API_URL = 'http://127.0.0.1:18013'
  $env:YUEKE_RUNTIME_BASE_URL = 'http://127.0.0.1:18013'
  $env:YUEKE_TEACHING_BASE_URL = 'http://127.0.0.1:18013'
  $env:YUEKE_GRADING_BASE_URL = 'http://127.0.0.1:18013'
  $env:YUEKE_LAB_CATALOG_URL = 'http://127.0.0.1:18013'
  $env:E2E_REAL_API = '1'
  Push-Location (Join-Path $repoRoot 'frontend')
  try {
    npx playwright test e2e/teaching-core.spec.ts e2e/course-resources-live.spec.ts e2e/lab-designer-g3.spec.ts --config=playwright.grading.config.ts --reporter=line
    if ($LASTEXITCODE -ne 0) { throw 'G1-G3 browser gates failed' }
  } finally {
    Pop-Location
  }

  & (Join-Path $repoRoot 'scripts/run-runtime-gate.ps1') -DatabaseName $runtimeDatabase -AgentUrl $RuntimeAgentUrl -StartLocalAgent:$StartLocalRuntimeAgent
  & (Join-Path $repoRoot 'scripts/run-runtime-browser-gate.ps1') -DatabaseName $runtimeDatabase -AgentUrl $RuntimeAgentUrl -StartLocalAgent:$StartLocalRuntimeAgent
  if ($IncludeCapacityProbe) {
    & (Join-Path $repoRoot 'scripts/run-runtime-gate.ps1') -GateScript 'tests/runtime_capacity_gate.py' -DatabaseName $runtimeDatabase -AgentUrl $RuntimeAgentUrl -StartLocalAgent:$StartLocalRuntimeAgent
  }
  & (Join-Path $repoRoot 'scripts/run-classroom-gate.ps1') -DatabaseName $classroomDatabase
  & (Join-Path $repoRoot 'scripts/run-grading-gate.ps1') -DatabaseName $gradingDatabase

  $g5Status = if ($StartLocalRuntimeAgent) { 'PARTIAL' } else { 'PASS' }
  $engineeringGateStatus = if ($g5Status -eq 'PASS') { 'PASS' } else { 'PARTIAL' }
  $browserGates = if ($g5Status -eq 'PASS') { 'G1-G8' } else { 'G1-G4,G6-G8; G5 PARTIAL' }
  $dockerRuntime = if ($g5Status -eq 'PASS') { 'G4-G6 PASS' } else { 'G4/G6 PASS; G5 PARTIAL' }
  [ordered]@{
    engineering_gate_status = $engineeringGateStatus
    procurement_content_status = 'PASS_AUTOMATED'
    procurement_content_reason = 'Automated corpus gates passed; external teaching-expert review was not run.'
    production_acceptance = 'NOT_RUN'
    run_id = $RunId
    backend_regression = 'PASS'
    frontend_contracts = 'PASS'
    frontend_unit_tests = 'PASS'
    frontend_build = 'PASS'
    browser_gates = $browserGates
    docker_runtime = $dockerRuntime
    g5_terminal = $g5Status
    runtime_agent_url = $RuntimeAgentUrl
    runtime_agent_started_locally = $StartLocalRuntimeAgent
    classroom_students = 43
    capacity_probe = [bool]$IncludeCapacityProbe
    databases = $databaseNames
  } | ConvertTo-Json -Depth 3
} finally {
  foreach ($name in $gateEnvironmentNames) {
    if ($null -eq $previousEnvironment[$name]) {
      Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
      [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
  }
}
