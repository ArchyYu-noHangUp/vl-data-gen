#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

mkdir -p logs data runs

WEB_PID_FILE="$ROOT/logs/web.pid"
WORKER_PID_FILE="$ROOT/logs/worker.pid"
WEB_LOG="$ROOT/logs/web.log"
WORKER_LOG="$ROOT/logs/worker.log"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

web_pid_by_port() {
  ss -ltnp 'sport = :8000' 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n 1
}

worker_pid_by_name() {
  pgrep -f "^python3 -m vl_app\\.worker$" | head -n 1
}

WEB_PORT_PID="$(web_pid_by_port || true)"
WORKER_NAME_PID="$(worker_pid_by_name || true)"

if [[ -n "$WEB_PORT_PID" ]]; then
  echo "$WEB_PORT_PID" >"$WEB_PID_FILE"
  echo "Web 已在运行，PID: $WEB_PORT_PID"
elif is_running "$WEB_PID_FILE"; then
  echo "Web 已在运行，PID: $(cat "$WEB_PID_FILE")"
else
  nohup uvicorn vl_app.main:app --host 0.0.0.0 --port 8000 --workers 1 >>"$WEB_LOG" 2>&1 &
  echo "$!" >"$WEB_PID_FILE"
  echo "Web 已启动，PID: $(cat "$WEB_PID_FILE")，日志: $WEB_LOG"
fi

if [[ -n "$WORKER_NAME_PID" ]]; then
  echo "$WORKER_NAME_PID" >"$WORKER_PID_FILE"
  echo "Worker 已在运行，PID: $WORKER_NAME_PID"
elif is_running "$WORKER_PID_FILE"; then
  echo "Worker 已在运行，PID: $(cat "$WORKER_PID_FILE")"
else
  nohup setsid python3 -m vl_app.worker >>"$WORKER_LOG" 2>&1 < /dev/null &
  echo "$!" >"$WORKER_PID_FILE"
  echo "Worker 已启动，PID: $(cat "$WORKER_PID_FILE")，日志: $WORKER_LOG"
fi

echo "访问地址: http://127.0.0.1:8000"
