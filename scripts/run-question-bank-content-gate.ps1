param(
  [ValidateSet('yueke_question_bank_content_v101_dev')]
  [string]$DatabaseName = 'yueke_question_bank_content_v101_dev'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend virtual environment is missing' }

$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$rootEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_ROOT_PASSWORD=*' } | Select-Object -First 1
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $rootEntry -or -not $passwordEntry) { throw 'MySQL development credentials are missing' }
$rootPassword = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$databasePassword = $passwordEntry.Substring('MYSQL_PASSWORD='.Length)

$sql = "CREATE DATABASE IF NOT EXISTS ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON ``$DatabaseName``.* TO 'yueke_dev'@'%'; FLUSH PRIVILEGES;"
docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -e $sql
if ($LASTEXITCODE -ne 0) { throw 'Question bank development database preparation failed' }

$escapedPassword = [System.Uri]::EscapeDataString($databasePassword)
$previousDatabaseUrl = $env:YUEKE_DATABASE_URL
$previousPythonPath = $env:PYTHONPATH
$previousPath = $env:PATH
try {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escapedPassword}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  $env:PATH = "$(Split-Path -Parent $python);$previousPath"
  Push-Location (Join-Path $repoRoot 'backend')
  try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Question bank migration failed' }
  } finally {
    Pop-Location
  }

  & $python -m pytest (Join-Path $repoRoot 'backend/tests/test_formal_question_bank.py') (Join-Path $repoRoot 'backend/tests/test_formal_question_bank_mysql.py') -q
  if ($LASTEXITCODE -ne 0) { throw 'Question bank contract or MySQL gate failed' }

  & $python (Join-Path $repoRoot 'tests/seed_question_bank_content.py')
  if ($LASTEXITCODE -ne 0) { throw 'Question bank content seeding failed' }
} finally {
  $env:YUEKE_DATABASE_URL = $previousDatabaseUrl
  $env:PYTHONPATH = $previousPythonPath
  $env:PATH = $previousPath
}
