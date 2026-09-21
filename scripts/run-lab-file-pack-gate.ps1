param(
  [ValidateSet('yueke_question_bank_content_v101_dev')]
  [string]$DatabaseName = 'yueke_question_bank_content_v101_dev'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
$uploadRoot = Join-Path $repoRoot 'backend/var/question_bank_content_v101_uploads'
$containerImage = 'python@sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend virtual environment is missing' }

$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$rootEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_ROOT_PASSWORD=*' } | Select-Object -First 1
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $rootEntry -or -not $passwordEntry) { throw 'MySQL development credentials are missing' }
$rootPassword = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$databasePassword = $passwordEntry.Substring('MYSQL_PASSWORD='.Length)

$sql = "CREATE DATABASE IF NOT EXISTS ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON ``$DatabaseName``.* TO 'yueke_dev'@'%'; FLUSH PRIVILEGES;"
docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -e $sql
if ($LASTEXITCODE -ne 0) { throw 'Lab file pack development database preparation failed' }

$escapedPassword = [System.Uri]::EscapeDataString($databasePassword)
$previousDatabaseUrl = $env:YUEKE_DATABASE_URL
$previousPythonPath = $env:PYTHONPATH
$previousUploadRoot = $env:YUEKE_RESOURCE_UPLOAD_DIR
$previousPath = $env:PATH
try {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escapedPassword}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  $env:YUEKE_RESOURCE_UPLOAD_DIR = $uploadRoot
  $env:PATH = "$(Split-Path -Parent $python);$previousPath"

  Push-Location (Join-Path $repoRoot 'backend')
  try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Lab file pack migration failed' }
  } finally {
    Pop-Location
  }

  & $python (Join-Path $repoRoot 'scripts/build-lab-file-packs.py')
  if ($LASTEXITCODE -ne 0) { throw 'Lab file pack build failed' }

  & $python -m pytest `
    (Join-Path $repoRoot 'backend/tests/test_lab_file_packs.py') `
    (Join-Path $repoRoot 'backend/tests/test_resource_storage.py') `
    (Join-Path $repoRoot 'backend/tests/test_formal_lab_file_packs_mysql.py') -q
  if ($LASTEXITCODE -ne 0) { throw 'Lab file pack contract or MySQL gate failed' }

  docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges `
    --pids-limit 128 --memory 512m --cpus 1 --tmpfs /tmp:rw,size=128m `
    -v "${repoRoot}:/workspace:ro" -w /workspace $containerImage python tests/verify_lab_file_packs.py
  if ($LASTEXITCODE -ne 0) { throw 'Lab file pack isolated execution failed' }

  & $python (Join-Path $repoRoot 'tests/seed_question_bank_content.py')
  if ($LASTEXITCODE -ne 0) { throw 'Formal question bank prerequisite seeding failed' }
  & $python (Join-Path $repoRoot 'tests/seed_lab_file_packs.py')
  if ($LASTEXITCODE -ne 0) { throw 'Lab file pack content seeding failed' }
} finally {
  $env:YUEKE_DATABASE_URL = $previousDatabaseUrl
  $env:PYTHONPATH = $previousPythonPath
  $env:YUEKE_RESOURCE_UPLOAD_DIR = $previousUploadRoot
  $env:PATH = $previousPath
}
