$ErrorActionPreference = "Stop"

$port = if ($env:PORT) { $env:PORT } else { "8000" }
$webWorkers = if ($env:WEB_WORKERS) { [int]$env:WEB_WORKERS } else { 4 }
$workerConcurrency = if ($env:WORKER_CONCURRENCY) { [int]$env:WORKER_CONCURRENCY } else { 12 }

New-Item -ItemType Directory -Force -Path "C:\app\runs", "C:\app\data", "C:\app\logs" | Out-Null

Write-Host "Starting $workerConcurrency worker process(es)"
for ($index = 1; $index -le $workerConcurrency; $index++) {
    $outLog = "C:\app\logs\worker-$index.log"
    $errLog = "C:\app\logs\worker-$index.err.log"
    Start-Process -FilePath "python" `
        -ArgumentList "-m", "vl_app.worker" `
        -WorkingDirectory "C:\app" `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden
}

Write-Host "Starting web: $webWorkers uvicorn worker(s) on port $port"
python -m uvicorn vl_app.main:app --host 0.0.0.0 --port $port --workers $webWorkers
