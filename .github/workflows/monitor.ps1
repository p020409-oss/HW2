param(
  [Parameter(Mandatory=$true)][string]$BaseUrl,
  [Parameter(Mandatory=$true)][string]$ImagePath,
  [Parameter(Mandatory=$true)][string]$LogPath,
  [Parameter(Mandatory=$true)][string]$StagePath,
  [Parameter(Mandatory=$true)][string]$ReadyPath,
  [Parameter(Mandatory=$true)][string]$StopPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
$utf8 = New-Object System.Text.UTF8Encoding($false)
$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromSeconds(20)
  $client.DefaultRequestHeaders.Add('X-Deployment-Monitor', '1')
$previousEnd = $null
$previousStart = $null
$requestId = 0

function Send-Analysis {
  param([string]$Stage)
  $script:requestId++
  $start = [DateTimeOffset]::UtcNow
  $response = $null
  $status = 0
  $analysisOk = $false
  $appVersion = 'unknown'
  $modelVersion = 'unknown'
  $analysisResult = ''
  $detail = ''
  $body = $null
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    $bytes = [System.IO.File]::ReadAllBytes($ImagePath)
    $part = [System.Net.Http.ByteArrayContent]::new($bytes)
    $part.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('image/jpeg')
    $multipart.Add($part, 'file', 'fixed-cc0-food.jpg')
    $response = $client.PostAsync("$BaseUrl/api/analyze", $multipart).GetAwaiter().GetResult()
    $status = [int]$response.StatusCode
    if ($response.Headers.Contains('X-App-Version')) { $appVersion = ($response.Headers.GetValues('X-App-Version') | Select-Object -First 1) }
    if ($response.Headers.Contains('X-Model-Version')) { $modelVersion = ($response.Headers.GetValues('X-Model-Version') | Select-Object -First 1) }
    $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    $analysisOk = ($response.IsSuccessStatusCode -and $body.choices -and $body.choices.Count -gt 0 -and $body.choices[0].menu)
    if ($analysisOk) { $analysisResult = [string]$body.choices[0].menu }
    if (-not $analysisOk -and $body.detail) { $detail = [string]$body.detail }
  } catch {
    if ($_.Exception -and $_.Exception.Message) { $detail = $_.Exception.Message }
  } finally {
    $timer.Stop()
    if ($response) { $response.Dispose() }
    if ($multipart) { $multipart.Dispose() }
  }
  $end = [DateTimeOffset]::UtcNow
  $gapMs = if ($script:previousEnd) { [Math]::Round(($start - $script:previousEnd).TotalMilliseconds, 1) } else { $null }
  $intervalMs = if ($script:previousStart) { [Math]::Round(($start - $script:previousStart).TotalMilliseconds, 1) } else { $null }
  $record = [ordered]@{
    request_id = $script:requestId
    stage = $Stage
    start_utc = $start.ToString('o')
    end_utc = $end.ToString('o')
    response_ms = [Math]::Round($timer.Elapsed.TotalMilliseconds, 1)
    interval_from_previous_start_ms = $intervalMs
    gap_from_previous_end_ms = $gapMs
    http_status = $status
    analysis_ok = [bool]$analysisOk
    app_version = $appVersion
    model_version = $modelVersion
    analysis_result = $analysisResult
    error = $detail
  }
  $line = $record | ConvertTo-Json -Compress -Depth 4
  [System.IO.File]::AppendAllText($LogPath, $line + "`n", $utf8)
  Write-Output "ANALYSIS_REQUEST $line"
  $script:previousEnd = $end
  $script:previousStart = $start
  if ($analysisOk -and -not (Test-Path $ReadyPath)) { [System.IO.File]::WriteAllText($ReadyPath, $start.ToString('o'), $utf8) }
}

while (-not (Test-Path $StopPath)) {
  $stage = 'Before'
  if (Test-Path $StagePath) {
    $stageValue = [System.IO.File]::ReadAllText($StagePath, $utf8).Trim()
    if ($stageValue) { $stage = $stageValue }
  }
  Send-Analysis -Stage $stage
  if (-not (Test-Path $StopPath)) { Start-Sleep -Milliseconds 1000 }
}
$client.Dispose()
