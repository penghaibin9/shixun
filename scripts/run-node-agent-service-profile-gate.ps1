param(
  [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$agentRoot = Join-Path $repoRoot 'node_agent'
$agentUrl = 'http://127.0.0.1:19444'
$agentToken = "service-profile-gate-$([guid]::NewGuid().ToString('N'))"
$savedEnvironment = @{
  YUEKE_AGENT_ALLOWED_DIGESTS = $env:YUEKE_AGENT_ALLOWED_DIGESTS
  YUEKE_AGENT_GRADER_DIGEST = $env:YUEKE_AGENT_GRADER_DIGEST
  YUEKE_NODE_AGENT_TOKEN = $env:YUEKE_NODE_AGENT_TOKEN
  YUEKE_SERVICE_PROFILE_GATE_URL = $env:YUEKE_SERVICE_PROFILE_GATE_URL
}
$agentProcess = $null
$pushed = $false
$graderDigest = 'sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca'
$images = [ordered]@{
  "python@$graderDigest" = $graderDigest
  'mysql@sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb' = 'sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb'
  'nginx@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10' = 'sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10'
}

$engine = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $engine.Trim() -ne 'linux') {
  throw 'The service-profile gate requires a Linux Docker Engine.'
}

foreach ($entry in $images.GetEnumerator()) {
  docker image inspect $entry.Value *> $null
  if ($LASTEXITCODE -ne 0) {
    docker pull $entry.Key
    if ($LASTEXITCODE -ne 0) {
      throw "Pinned image pull failed: $($entry.Key)"
    }
  }
  $actual = docker image inspect $entry.Value --format '{{.Id}}'
  if ($LASTEXITCODE -ne 0 -or $actual.Trim() -ne $entry.Value) {
    throw "Image digest verification failed: $($entry.Key)"
  }
}

try {
  $env:YUEKE_AGENT_ALLOWED_DIGESTS = ($images.Values -join ',')
  $env:YUEKE_AGENT_GRADER_DIGEST = $graderDigest
  $env:YUEKE_NODE_AGENT_TOKEN = $agentToken
  $env:YUEKE_SERVICE_PROFILE_GATE_URL = $agentUrl

  $agentProcess = Start-Process -FilePath $Python -ArgumentList @(
    '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '19444'
  ) -WorkingDirectory $agentRoot -WindowStyle Hidden -PassThru

  $ready = $false
  for ($attempt = 0; $attempt -lt 40; $attempt++) {
    if ($agentProcess.HasExited) {
      throw "Node Agent exited before the service-profile gate started (exit code $($agentProcess.ExitCode))."
    }
    try {
      $health = Invoke-RestMethod -Method Get -Uri "$agentUrl/health" -Headers @{ Authorization = "Bearer $agentToken" } -TimeoutSec 2
      if ($health.status -eq 'ok') {
        $ready = $true
        break
      }
    }
    catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if (-not $ready) {
    throw 'Node Agent did not become healthy for the service-profile gate.'
  }

  Push-Location $repoRoot
  $pushed = $true
  & $Python tests/node_agent_service_profile_gate.py
  if ($LASTEXITCODE -ne 0) {
    throw 'The MySQL/Nginx service-profile gate failed.'
  }
}
finally {
  if ($pushed) {
    Pop-Location
  }
  if ($null -ne $agentProcess -and -not $agentProcess.HasExited) {
    Stop-Process -Id $agentProcess.Id -Force
    Wait-Process -Id $agentProcess.Id -ErrorAction SilentlyContinue
  }
  foreach ($name in $savedEnvironment.Keys) {
    $value = $savedEnvironment[$name]
    if ($null -eq $value) {
      Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }
    else {
      Set-Item -Path "Env:$name" -Value $value
    }
  }
}
