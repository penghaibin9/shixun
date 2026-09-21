param(
  [ValidateSet('yueke_question_bank_content_v101_dev')]
  [string]$DatabaseName = 'yueke_question_bank_content_v101_dev'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
$uploadRoot = Join-Path $repoRoot 'backend/var/question_bank_content_v101_uploads'
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
if (-not $rootEntry -or -not $passwordEntry) { throw 'MySQL development credentials are missing' }
$rootPassword = $rootEntry.Substring('MYSQL_ROOT_PASSWORD='.Length)
$databasePassword = $passwordEntry.Substring('MYSQL_PASSWORD='.Length)
$sql = "CREATE DATABASE IF NOT EXISTS ``$DatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL PRIVILEGES ON ``$DatabaseName``.* TO 'yueke_dev'@'%'; FLUSH PRIVILEGES;"
docker exec -e "MYSQL_PWD=$rootPassword" yueke-contract-mysql-dev mysql -uroot -e $sql
if ($LASTEXITCODE -ne 0) { throw 'Course-video development database preparation failed' }

$escapedPassword = [System.Uri]::EscapeDataString($databasePassword)
$previousDatabaseUrl = $env:YUEKE_DATABASE_URL
$previousPythonPath = $env:PYTHONPATH
$previousUploadRoot = $env:YUEKE_RESOURCE_UPLOAD_DIR
$previousProbe = $env:YUEKE_FFPROBE
$previousPath = $env:PATH
try {
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escapedPassword}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  $env:PYTHONPATH = Join-Path $repoRoot 'backend'
  $env:YUEKE_RESOURCE_UPLOAD_DIR = $uploadRoot
  $env:YUEKE_FFPROBE = $ffprobe
  $env:PATH = "$(Split-Path -Parent $ffprobe);$(Split-Path -Parent $python);$previousPath"

  Push-Location (Join-Path $repoRoot 'backend')
  try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Course-video migration failed' }
  } finally {
    Pop-Location
  }

  & $python -m pytest `
    (Join-Path $repoRoot 'backend/tests/test_course_videos.py') `
    (Join-Path $repoRoot 'backend/tests/test_formal_course_videos_mysql.py') -q
  if ($LASTEXITCODE -ne 0) { throw 'Course-video static or MySQL gate failed' }

  & $python (Join-Path $repoRoot 'tests/seed_question_bank_content.py')
  if ($LASTEXITCODE -ne 0) { throw 'Formal question-bank prerequisite seeding failed' }
  & $python (Join-Path $repoRoot 'tests/seed_lab_file_packs.py')
  if ($LASTEXITCODE -ne 0) { throw 'Formal lab-file prerequisite seeding failed' }
  & $python (Join-Path $repoRoot 'tests/seed_theory_ppts.py')
  if ($LASTEXITCODE -ne 0) { throw 'Formal theory-PPT prerequisite seeding failed' }
  & $python (Join-Path $repoRoot 'tests/seed_course_videos.py')
  if ($LASTEXITCODE -ne 0) { throw 'Course-video content seeding failed' }
} finally {
  $env:YUEKE_DATABASE_URL = $previousDatabaseUrl
  $env:PYTHONPATH = $previousPythonPath
  $env:YUEKE_RESOURCE_UPLOAD_DIR = $previousUploadRoot
  $env:YUEKE_FFPROBE = $previousProbe
  $env:PATH = $previousPath
}
