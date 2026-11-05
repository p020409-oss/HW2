$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
$utf8 = New-Object System.Text.UTF8Encoding($false)
$baseUrl = 'http://127.0.0.1:8765'
$runnerTemp = $env:RUNNER_TEMP
$outDir = Join-Path $runnerTemp 'meal-deploy-observation'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$logPath = Join-Path $outDir 'analysis-requests.jsonl'
$stagePath = Join-Path $outDir 'stage.txt'
$readyPath = Join-Path $outDir 'baseline-ready.txt'
$stopPath = Join-Path $outDir 'monitor-stop.txt'
$testImage = Join-Path $runnerTemp 'meal-fixed-cc0-food.jpg'
$stageFile = Join-Path $outDir 'stage-marker.txt'
$monitorPath = Join-Path $env:GITHUB_WORKSPACE '.github\workflows\monitor.ps1'
$containerName = 'meal-app'
$canaryName = 'meal-app-canary'
$volumeName = 'meal-data'
$image = "$env:IMAGE_NAME`:$env:IMAGE_TAG"
$monitor = $null
$deployError = $null
$oldImageId = $null
$newContainerStarted = $false
$deployResult = 'FAILED'

function Write-Stage([string]$Name) {
  [System.IO.File]::WriteAllText($stagePath, $Name, $utf8)
  [System.IO.File]::WriteAllText($stageFile, $Name, $utf8)
  Write-Host "DEPLOY_STAGE $Name"
}

function Wait-ForVersion([string]$Url, [string]$ExpectedAppVersion, [int]$Attempts = 45) {
  for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    try {
      $v = Invoke-RestMethod -Uri "$Url/api/version" -TimeoutSec 3
      if ($v.model_loaded -and $v.app_version -eq $ExpectedAppVersion) { return $v }
    } catch { }
    Start-Sleep -Seconds 2
  }
  throw "Service at $Url did not report the expected loaded version $ExpectedAppVersion."
}

function Test-Analysis([string]$Url, [string]$Path) {
  $client = [System.Net.Http.HttpClient]::new()
  $client.Timeout = [TimeSpan]::FromSeconds(30)
  $client.DefaultRequestHeaders.Add('X-Deployment-Monitor', '1')
  $multipart = $null
  try {
    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $part = [System.Net.Http.ByteArrayContent]::new($bytes)
    $part.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('image/jpeg')
    $multipart.Add($part, 'file', 'fixed-cc0-food.jpg')
    $r = $client.PostAsync("$Url/api/analyze", $multipart).GetAwaiter().GetResult()
    $body = $r.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    if (-not $r.IsSuccessStatusCode -or -not $body.choices -or $body.choices.Count -eq 0) {
      throw "Analysis failed at $Url with HTTP $([int]$r.StatusCode)."
    }
    return $body.choices[0].menu
  } finally {
    if ($multipart) { $multipart.Dispose() }
    $client.Dispose()
  }
}

function Escape-Markdown([string]$Value) { return ($Value -replace '\|', '\|') }

function Write-Summary([string]$Status, [string]$ErrorText) {
  $records = @()
  if (Test-Path $logPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($logPath, [System.Text.Encoding]::UTF8)) {
      if ($line) { try { $records += ($line | ConvertFrom-Json) } catch { } }
    }
  }
  $start = if ($records.Count) { $records[0].start_utc } else { [DateTimeOffset]::UtcNow.ToString('o') }
  $end = if ($records.Count) { $records[-1].end_utc } else { [DateTimeOffset]::UtcNow.ToString('o') }
  $success = @($records | Where-Object { $_.analysis_ok }).Count
  $failed = $records.Count - $success
  $before = @($records | Where-Object { $_.stage -eq 'Before' })
  $during = @($records | Where-Object { $_.stage -eq 'During' })
  $after = @($records | Where-Object { $_.stage -eq 'After' })
  $intervals = @($records | Where-Object { $null -ne $_.interval_from_previous_start_ms } | ForEach-Object { [double]$_.interval_from_previous_start_ms })
  $gaps = @($records | Where-Object { $null -ne $_.gap_from_previous_end_ms } | ForEach-Object { [double]$_.gap_from_previous_end_ms })
  $avgInterval = if ($intervals.Count) { [Math]::Round(($intervals | Measure-Object -Average).Average / 1000, 2) } else { 0 }
  $maxInterval = if ($intervals.Count) { [Math]::Round(($intervals | Measure-Object -Maximum).Maximum / 1000, 2) } else { 0 }
  $maxGap = if ($gaps.Count) { [Math]::Round(($gaps | Measure-Object -Maximum).Maximum / 1000, 2) } else { 0 }
  $gapsOver3 = @($gaps | Where-Object { $_ -gt 3000 }).Count
  $observedStatus = if ($Status -ne 'SUCCESS') { 'FAILED' } elseif ($failed -gt 0) { 'DEPLOYED; REQUEST FAILURES OBSERVED' } elseif ($during.Count -eq 0) { 'DEPLOYED; NO DURING SAMPLE' } else { 'SUCCESS; NO FAILURES IN OBSERVED REQUESTS' }

  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.Add('# Zero-Downtime Redeployment Verification')
  $lines.Add('')
  $lines.Add("**Result:** $observedStatus  | **Stable URL:** $baseUrl  | **UTC window:** $start to $end")
  $lines.Add('')
  $lines.Add("**API requests:** $($records.Count) total; $success successful; $failed failed. **Actual start-to-start interval:** average ${avgInterval}s, max ${maxInterval}s. **Maximum recorded response-end gap:** ${maxGap}s; gaps over 3s: $gapsOver3. Unobserved intervals are not proof of continuous availability.")
  $lines.Add('')
  $lines.Add('## Before / during / after')
  $lines.Add('')
  $lines.Add('| Stage | Requests (ok/total) | Sample | UTC start | HTTP / analysis | App / model version | Response | Suggested menu |')
  $lines.Add('|---|---:|---:|---|---|---|---:|---|')
  foreach ($stageName in @('Before','During','After')) {
    $group = @($records | Where-Object { $_.stage -eq $stageName })
    $ok = @($group | Where-Object { $_.analysis_ok }).Count
    $sample = if ($group.Count) { if ($stageName -eq 'During') { $group[[int][Math]::Floor(($group.Count - 1) / 2)] } else { $group[0] } } else { $null }
    if ($sample) {
      $lines.Add("| $stageName | $ok/$($group.Count) | #$($sample.request_id) | $($sample.start_utc) | $($sample.http_status) / $($sample.analysis_ok) | $(Escape-Markdown([string]$sample.app_version)) / $(Escape-Markdown([string]$sample.model_version)) | $($sample.response_ms) ms | $(Escape-Markdown([string]$sample.analysis_result)) |")
    } else { $lines.Add("| $stageName | $ok/$($group.Count) | n/a | n/a | n/a | n/a | n/a | n/a |") }
  }
  $versions = @($records | Where-Object { $_.analysis_ok } | ForEach-Object { "$($_.app_version) / $($_.model_version)" } | Select-Object -Unique)
  $lines.Add('')
  $lines.Add('## Version transition')
  $lines.Add('')
  $lines.Add(($versions | ForEach-Object { "- $_" }) -join "`n")
  $lines.Add('')
  $lines.Add('## Observation limits')
  $lines.Add('')
  $lines.Add("Requests used one fixed CC0 image from bharat-raghunathan/indian-foods-dataset and were scheduled one second after each response. Average actual request interval was $avgInterval seconds; the maximum response-end gap was $maxGap seconds. Gaps are unverified intervals, and availability describes only the recorded requests in this window.")
  if ($ErrorText) { $lines.Add(''); $lines.Add('## Deployment error'); $lines.Add(''); $lines.Add(('```text')); $lines.Add($ErrorText); $lines.Add(('```')) }
  [System.IO.File]::WriteAllLines((Join-Path $outDir 'summary.md'), $lines, $utf8)
  if (Test-Path $logPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($logPath, [System.Text.Encoding]::UTF8)) { Write-Host "ANALYSIS_REQUEST $line" }
  }
}

try {
  Write-Stage 'Before'
  $datasetApi = 'https://datasets-server.huggingface.co/rows?dataset=bharat-raghunathan/indian-foods-dataset&config=default&split=test&offset=0&length=1'
  $rowData = Invoke-RestMethod -Uri $datasetApi -Headers @{ 'User-Agent'='MealJournal-Deploy-Monitor' } -TimeoutSec 30
  if ($rowData.rows.Count -ne 1) { throw 'Could not retrieve fixed CC0 analysis image row.' }
  Invoke-WebRequest -Uri $rowData.rows[0].row.image.src -OutFile $testImage -TimeoutSec 60
  if (-not (Test-Path $testImage) -or (Get-Item $testImage).Length -lt 1000) { throw 'Fixed analysis image download is empty.' }

  Remove-Item $logPath,$readyPath,$stopPath -Force -ErrorAction SilentlyContinue
  $monitor = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -WindowStyle Hidden -PassThru -WorkingDirectory $env:GITHUB_WORKSPACE -ArgumentList @('-NoProfile','-File', $monitorPath, '-BaseUrl',$baseUrl,'-ImagePath',$testImage,'-LogPath',$logPath,'-StagePath',$stagePath,'-ReadyPath',$readyPath,'-StopPath',$stopPath)
  $ready = $false
  for ($i=0; $i -lt 90; $i++) {
    if (Test-Path $readyPath) { $ready = $true; break }
    if ($monitor.HasExited) { throw "Independent monitor exited before the baseline analysis succeeded (code $($monitor.ExitCode))." }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) { throw 'Baseline analysis did not succeed within 90 seconds; deployment was not started.' }
  Write-Host 'Independent monitor baseline analysis succeeded; deployment may proceed.'

  docker pull $image
  if ($LASTEXITCODE -ne 0) { throw "Could not pull immutable image $image" }
  docker volume create $volumeName | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Could not create Docker volume $volumeName" }

  # Remove only prior task-owned preview containers; the currently published service stays untouched.
  foreach ($name in @($canaryName,'meal-app-candidate-test')) {
    $id = docker container ls --all --quiet --filter "name=^/$name`$"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect container $name" }
    if ($id) { docker rm --force $name | Out-Null; if ($LASTEXITCODE -ne 0) { throw "Could not remove prior preview container $name" } }
  }

  $existing = docker container ls --all --quiet --filter "name=^/$containerName`$"
  if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the published service container.' }
  if ($existing) {
    $oldImageId = docker inspect --format '{{.Image}}' $containerName
    if ($LASTEXITCODE -ne 0 -or -not $oldImageId) { throw 'Could not record the current image for rollback.' }
    $oldImageId = $oldImageId.Trim()
  }

  docker run --detach --name $canaryName --restart no --publish 127.0.0.1:8766:8765 --volume "${volumeName}:/app/data" --env "APP_VERSION=$env:APP_VERSION" $image
  if ($LASTEXITCODE -ne 0) { throw 'Could not start canary container on port 8766.' }
  $canaryVersion = Wait-ForVersion 'http://127.0.0.1:8766' $env:APP_VERSION
  $canaryChoice = Test-Analysis 'http://127.0.0.1:8766' $testImage
  Write-Host "CANARY analysis ok; app=$($canaryVersion.app_version); model=$($canaryVersion.model_version); choice=$canaryChoice"

  Write-Stage 'During'
  if ($oldImageId) {
    docker stop $containerName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the currently published service.' }
    docker rm $containerName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the stopped service container.' }
  }
  docker run --detach --name $containerName --restart unless-stopped --publish 127.0.0.1:8765:8765 --volume "${volumeName}:/app/data" --env "APP_VERSION=$env:APP_VERSION" $image
  if ($LASTEXITCODE -ne 0) { throw 'Could not start the new published service.' }
  $newContainerStarted = $true
  $newVersion = Wait-ForVersion $baseUrl $env:APP_VERSION
  $newChoice = Test-Analysis $baseUrl $testImage
  Write-Host "PUBLISHED analysis ok; app=$($newVersion.app_version); model=$($newVersion.model_version); choice=$newChoice"
  docker rm --force $canaryName | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Could not remove the verified canary container.' }

  Write-Stage 'After'
  Write-Host 'Keeping independent analysis monitor active for 30 seconds after deployment.'
  Start-Sleep -Seconds 30
  $deployResult = 'SUCCESS'
} catch {
  $deployError = $_.ToString()
  Write-Host "DEPLOY_ERROR $deployError"
  try {
    $canary = docker container ls --all --quiet --filter "name=^/$canaryName`$"
    if ($canary) { docker rm --force $canaryName | Out-Null }
    $failed = docker container ls --all --quiet --filter "name=^/$containerName`$"
    if ($newContainerStarted -and $failed) {
      docker logs $containerName 2>&1 | ForEach-Object { Write-Host "DEPLOYED_CONTAINER_LOG $_" }
      docker rm --force $containerName | Out-Null
    }
    if ($oldImageId) {
      $stillRunning = docker container ls --all --quiet --filter "name=^/$containerName`$"
      if (-not $stillRunning) {
        docker run --detach --name $containerName --restart unless-stopped --publish 127.0.0.1:8765:8765 --volume "${volumeName}:/app/data" $oldImageId
        Write-Warning "Restored previous image $oldImageId."
      }
    }
  } catch { Write-Host "ROLLBACK_ERROR $($_.ToString())" }
} finally {
  if ($monitor -and -not $monitor.HasExited) {
    Write-Stage $(if ($deployResult -eq 'SUCCESS') { 'After' } else { 'During' })
    Start-Sleep -Seconds 2
    [System.IO.File]::WriteAllText($stopPath, 'stop', $utf8)
    if (-not $monitor.WaitForExit(15000)) { Stop-Process -Id $monitor.Id -Force -ErrorAction SilentlyContinue }
  }
  Write-Summary $deployResult $deployError
}

if ($deployResult -ne 'SUCCESS') { exit 1 }
