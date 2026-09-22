param(
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$DatabaseName = "yueke_c_formal_gate_$(Get-Date -Format 'yyyyMMddHHmmss')"
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend virtual environment is missing' }

$expectedImages = @{
  'python:3.11-bookworm' = 'sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca'
  'mysql:8.4' = 'sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb'
  'nginx:1.27-alpine' = 'sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10'
}
foreach ($image in $expectedImages.Keys) {
  $actual = docker image inspect $image --format '{{.Id}}'
  if ($LASTEXITCODE -ne 0 -or $actual -ne $expectedImages[$image]) {
    throw "Pinned lab image mismatch: $image"
  }
}

$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$rootEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_ROOT_PASSWORD=*' } | Select-Object -First 1
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $rootEntry -or -not $passwordEntry) { throw 'MySQL development credentials are missing' }
$rootPassword = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$databasePassword = $passwordEntry.Substring('MYSQL_PASSWORD='.Length)
$existingDatabase = docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -Nse "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '$DatabaseName';"
if ($LASTEXITCODE -ne 0) { throw 'Lab designer development database inventory failed' }
if ($existingDatabase) { throw "Lab designer gate requires a new empty database: $DatabaseName" }
$sql = "CREATE DATABASE ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON ``$DatabaseName``.* TO 'yueke_dev'@'%'; FLUSH PRIVILEGES;"
docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -e $sql
if ($LASTEXITCODE -ne 0) { throw 'Lab designer development database preparation failed' }

$escapedPassword = [System.Uri]::EscapeDataString($databasePassword)
$previousDatabaseUrl = $env:YUEKE_DATABASE_URL
$previousPythonPath = $env:PYTHONPATH
try {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escapedPassword}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  Push-Location (Join-Path $repoRoot 'backend')
  try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Lab designer migration failed' }
  } finally {
    Pop-Location
  }
  & $python -m pytest `
    (Join-Path $repoRoot 'backend/tests/test_lab_schema.py') `
    (Join-Path $repoRoot 'backend/tests/test_lab_mysql.py') -q
  if ($LASTEXITCODE -ne 0) { throw 'Lab designer schema or MySQL gate failed' }
} finally {
  $env:YUEKE_DATABASE_URL = $previousDatabaseUrl
  $env:PYTHONPATH = $previousPythonPath
}
