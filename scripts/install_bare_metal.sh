#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ArchyYu-noHangUp/vl-data-gen.git}"
BRANCH="${BRANCH:-main}"
APP_ROOT="${APP_ROOT:-/opt/vl-data-gen}"
SOURCE_DIR="${SOURCE_DIR:-$APP_ROOT/source}"
PORT="${PORT:-8000}"
WEB_WORKERS="${WEB_WORKERS:-4}"
WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-4}"
SERVICE_USER="${SERVICE_USER:-root}"

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "请使用 root 或 sudo 执行。"
    exit 1
  fi
}

install_system_deps() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3 python3-venv python3-pip git ffmpeg ca-certificates
    return
  fi
  if command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip git ffmpeg ca-certificates
    python3 -m ensurepip --upgrade || true
    return
  fi
  echo "未识别系统包管理器，请手动安装 Python 3.10+、pip、venv、git、ffmpeg。"
  exit 1
}

prepare_source() {
  mkdir -p "$APP_ROOT"
  if [[ -f "$PWD/requirements.txt" && -d "$PWD/vl_app" ]]; then
    SOURCE_DIR="$PWD"
  elif [[ ! -d "$SOURCE_DIR/.git" ]]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$SOURCE_DIR"
  else
    git -C "$SOURCE_DIR" fetch origin "$BRANCH"
    git -C "$SOURCE_DIR" checkout "$BRANCH"
    git -C "$SOURCE_DIR" pull --ff-only origin "$BRANCH"
  fi
  mkdir -p "$SOURCE_DIR/data" "$SOURCE_DIR/runs" "$SOURCE_DIR/logs" "$SOURCE_DIR/sample_dataset"
}

install_python_deps() {
  cd "$SOURCE_DIR"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
}

write_env() {
  cat >"$SOURCE_DIR/.env.service" <<EOF
PORT=$PORT
WEB_WORKERS=$WEB_WORKERS
WORKER_CONCURRENCY=$WORKER_CONCURRENCY
PYTHONUNBUFFERED=1
EOF
}

write_services() {
  cat >/etc/systemd/system/vl-data-gen-web.service <<EOF
[Unit]
Description=VL Data Gen Web Service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$SOURCE_DIR
EnvironmentFile=$SOURCE_DIR/.env.service
ExecStart=$SOURCE_DIR/.venv/bin/uvicorn vl_app.main:app --host 0.0.0.0 --port \${PORT} --workers \${WEB_WORKERS}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/vl-data-gen-worker@.service <<EOF
[Unit]
Description=VL Data Gen Worker %i
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$SOURCE_DIR
EnvironmentFile=$SOURCE_DIR/.env.service
ExecStart=$SOURCE_DIR/.venv/bin/python -m vl_app.worker
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
}

start_services() {
  systemctl daemon-reload
  systemctl enable vl-data-gen-web.service
  systemctl restart vl-data-gen-web.service
  for index in $(seq 1 "$WORKER_CONCURRENCY"); do
    systemctl enable "vl-data-gen-worker@${index}.service"
    systemctl restart "vl-data-gen-worker@${index}.service"
  done
}

require_root
install_system_deps
prepare_source
install_python_deps
write_env
write_services
start_services

echo "裸机部署完成。"
echo "安装目录：$SOURCE_DIR"
echo "访问地址：http://服务器IP:$PORT"
echo "默认管理员：admin"
echo "默认管理员密码请按内部流程获取或修改。"
echo "查看 Web 日志：journalctl -u vl-data-gen-web -f"
echo "查看 Worker 日志：journalctl -u 'vl-data-gen-worker@*' -f"
