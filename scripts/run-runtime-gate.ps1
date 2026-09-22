param(
  [string]$GateScript = 'tests/runtime_gate.py',
  [ValidatePattern('^[a-zA-Z0-9_]+$')]
  [string]$DatabaseName = 'yueke_d_dev',
  [string]$AgentUrl = 'http://127.0.0.1:19443',
  [bool]$StartLocalAgent = $true
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$agentUri = $null
if (-not [System.Uri]::TryCreate($AgentUrl, [System.UriKind]::Absolute, [ref]$agentUri) -or $agentUri.Scheme -notin @('http', 'https')) {
  throw 'AgentUrl must be an absolute HTTP(S) URL'
}
if ($agentUri.AbsolutePath -ne '/') { throw 'AgentUrl must not contain a path' }
$agentUrlNormalized = $AgentUrl.TrimEnd('/')
if ($StartLocalAgent -and -not $agentUri.IsLoopback) {
  throw 'StartLocalAgent can only bind a loopback AgentUrl; use -StartLocalAgent:$false for a remote Linux agent'
}
$containerEnv = docker inspect yueke-contract-mysql-dev --format '{{json .Config.Env}}' | ConvertFrom-Json
$passwordEntry = $containerEnv | Where-Object { $_ -like 'MYSQL_PASSWORD=*' } | Select-Object -First 1
if (-not $passwordEntry) { throw 'MYSQL_PASSWORD is missing' }
$escaped = [System.Uri]::EscapeDataString($passwordEntry.Substring('MYSQL_PASSWORD='.Length))
$gateRunId = [guid]::NewGuid().ToString('N')
$temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$captureDirectory = Join-Path $temporaryRoot "yueke-node-captures-$gateRunId"
$artifactDirectory = Join-Path $temporaryRoot "yueke-runtime-artifacts-$gateRunId"
$captureImageTag = "yueke-traffic-capture-gate:$gateRunId"
$gateEnvironmentNames = @(
  'YUEKE_AGENT_ALLOWED_DIGESTS',
  'YUEKE_AGENT_CAPTURE_DIGEST',
  'YUEKE_AGENT_CAPTURE_DIR',
  'YUEKE_AGENT_GRADER_DIGEST',
  'YUEKE_ARTIFACT_STORAGE_SIGNING_KEY',
  'YUEKE_DATABASE_URL',
  'YUEKE_GATE_NODE_AGENT_URL',
  'YUEKE_GATE_EXPECT_POSIX_PTY',
  'YUEKE_GATE_API_URL',
  'YUEKE_GATE_IMAGE_DIGEST',
  'YUEKE_LAB_CATALOG_TOKEN',
  'YUEKE_LAB_CATALOG_URL',
  'YUEKE_NODE_AGENT_TOKEN',
  'YUEKE_RUNTIME_ARTIFACT_DIR'
)
$previousEnvironment = @{}
foreach ($name in $gateEnvironmentNames) {
  $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, 'Process')
}
$agent = $null
$api = $null
$captureImageBuilt = $false
try {
  New-Item -ItemType Directory -Path $captureDirectory,$artifactDirectory -ErrorAction Stop | Out-Null
  $env:YUEKE_DATABASE_URL = "mysql+pymysql://yueke_dev:${escaped}@127.0.0.1:13384/${DatabaseName}?charset=utf8mb4"
  if ($StartLocalAgent) {
    $env:YUEKE_NODE_AGENT_TOKEN = [guid]::NewGuid().ToString('N')
  } elseif (-not $env:YUEKE_NODE_AGENT_TOKEN) {
    throw 'YUEKE_NODE_AGENT_TOKEN is required when StartLocalAgent is false'
  }
  $env:YUEKE_GATE_NODE_AGENT_URL = $agentUrlNormalized
  $env:YUEKE_GATE_EXPECT_POSIX_PTY = if ($StartLocalAgent) { '0' } else { '1' }
  $env:YUEKE_LAB_CATALOG_URL = 'http://127.0.0.1:18080'
  $env:YUEKE_LAB_CATALOG_TOKEN = [guid]::NewGuid().ToString('N')
  $imageId = docker image inspect python:3.11-bookworm --format '{{.Id}}'
  if (-not $imageId.StartsWith('sha256:')) { throw 'Pinned Python OpenSSL image is missing' }
  if ($StartLocalAgent) {
    docker build --quiet --tag $captureImageTag (Join-Path $repoRoot 'tests/fixtures/traffic-capture') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Pinned traffic capture image build failed' }
    $captureImageBuilt = $true
    $captureImageId = docker image inspect $captureImageTag --format '{{.Id}}'
    if (-not $captureImageId.StartsWith('sha256:')) { throw 'Pinned traffic capture image is missing' }
    $env:YUEKE_AGENT_CAPTURE_DIGEST = $captureImageId
    $env:YUEKE_AGENT_CAPTURE_DIR = $captureDirectory
    $env:YUEKE_AGENT_ALLOWED_DIGESTS = "$imageId,$captureImageId"
  } else {
    $env:YUEKE_AGENT_ALLOWED_DIGESTS = $imageId
  }
  $env:YUEKE_AGENT_GRADER_DIGEST = $imageId
  $env:YUEKE_GATE_IMAGE_DIGEST = $imageId
  $env:YUEKE_GATE_API_URL = 'http://127.0.0.1:18080'
  $env:YUEKE_RUNTIME_ARTIFACT_DIR = $artifactDirectory
  $env:YUEKE_ARTIFACT_STORAGE_SIGNING_KEY = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
  if ($StartLocalAgent) {
    $agent = Start-Process python -ArgumentList '-m','uvicorn','app:app','--host','127.0.0.1','--port',([string]$agentUri.Port) -WorkingDirectory (Join-Path $repoRoot 'node_agent') -PassThru -WindowStyle Hidden
  }
  $api = Start-Process python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18080' -WorkingDirectory (Join-Path $repoRoot 'backend') -PassThru -WindowStyle Hidden
  $agentReady = $false
  foreach ($attempt in 1..30) {
    try {
      $headers = @{ Authorization = "Bearer $env:YUEKE_NODE_AGENT_TOKEN" }
      if ((Invoke-WebRequest "$agentUrlNormalized/health" -Headers $headers -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $agentReady = $true; break }
    } catch { Start-Sleep -Milliseconds 300 }
  }
  if (-not $agentReady) { throw "Node Agent failed readiness check at $agentUrlNormalized" }
  $ready = $false
  foreach ($attempt in 1..30) {
    try { if ((Invoke-WebRequest 'http://127.0.0.1:18080/health' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) { $ready = $true; break } } catch { Start-Sleep -Milliseconds 300 }
  }
  if (-not $ready) { throw 'Control API failed to start' }
  python (Join-Path $repoRoot $GateScript)
  if ($LASTEXITCODE -ne 0) { throw 'Runtime gate failed' }
} finally {
  if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
  if ($agent -and -not $agent.HasExited) { Stop-Process -Id $agent.Id -Force }
  if ($captureImageBuilt) { docker image rm --force $captureImageTag | Out-Null }
  foreach ($path in @($captureDirectory, $artifactDirectory)) {
    $resolved = [System.IO.Path]::GetFullPath($path)
    $expectedPrefix = $temporaryRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolved) -like 'yueke-*-*') {
      Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
    }
  }
  foreach ($name in $gateEnvironmentNames) {
    if ($null -eq $previousEnvironment[$name]) {
      Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
      [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
  }
}
