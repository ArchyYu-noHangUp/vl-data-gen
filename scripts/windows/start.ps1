$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

$env:PORT = if ($env:PORT) { $env:PORT } else { "8000" }
$env:WEB_WORKERS = if ($env:WEB_WORKERS) { $env:WEB_WORKERS } else { "4" }
$env:WORKER_CONCURRENCY = if ($env:WORKER_CONCURRENCY) { $env:WORKER_CONCURRENCY } else { "4" }
$env:VL_TEMP_FINALS = if ($env:VL_TEMP_FINALS) { $env:VL_TEMP_FINALS } else { Join-Path $Root "temp_final" }

$localFfmpegBin = Join-Path $Root "tools\ffmpeg\bin"
$localFfmpeg = Join-Path $localFfmpegBin "ffmpeg.exe"
$localFfprobe = Join-Path $localFfmpegBin "ffprobe.exe"
if ((Test-Path $localFfmpeg) -and (Test-Path $localFfprobe)) {
    $env:PATH = "$localFfmpegBin;$env:PATH"
    $env:FFMPEG_BIN = $localFfmpeg
    $env:FFPROBE_BIN = $localFfprobe
}

New-Item -ItemType Directory -Force -Path `
    (Join-Path $Root "data"), `
    (Join-Path $Root "runs"), `
    (Join-Path $Root "logs"), `
    (Join-Path $Root "sample_dataset"), `
    $env:VL_TEMP_FINALS | Out-Null

if (!(Test-Path ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

for ($index = 1; $index -le [int]$env:WORKER_CONCURRENCY; $index++) {
    $outLog = Join-Path $Root "logs\worker-$index.log"
    $errLog = Join-Path $Root "logs\worker-$index.err.log"
    Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "vl_app.worker" `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden
}

.\.venv\Scripts\python.exe -m uvicorn vl_app.main:app --host 0.0.0.0 --port $env:PORT --workers $env:WEB_WORKERS
