#!/usr/bin/env bash
set -euo pipefail

WEB_WORKERS="${WEB_WORKERS:-4}"
WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-12}"
PORT="${PORT:-8000}"

mkdir -p /app/runs /app/data /app/logs

echo "Starting ${WORKER_CONCURRENCY} worker process(es)"
for index in $(seq 1 "$WORKER_CONCURRENCY"); do
  python -m vl_app.worker >>"/app/logs/worker-${index}.log" 2>&1 &
done

echo "Starting web: ${WEB_WORKERS} uvicorn worker(s) on port ${PORT}"
exec uvicorn vl_app.main:app --host 0.0.0.0 --port "$PORT" --workers "$WEB_WORKERS"
