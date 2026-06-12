#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ArchyYu-noHangUp/vl-data-gen.git}"
BRANCH="${BRANCH:-main}"
APP_ROOT="${APP_ROOT:-/opt/vl-data-gen}"
SOURCE_DIR="${SOURCE_DIR:-$APP_ROOT/source}"
DATA_DIR="${DATA_DIR:-$APP_ROOT/data}"
IMAGE_NAME="${IMAGE_NAME:-vl-data-gen:0.4.4}"
CONTAINER_NAME="${CONTAINER_NAME:-vl-data-gen}"
PORT="${PORT:-8000}"
WEB_WORKERS="${WEB_WORKERS:-4}"
WORKER_CONCURRENCY="${WORKER_CONCURRENCY:-12}"

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "请使用 root 或 sudo 执行本脚本。"
    exit 1
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y docker.io git ca-certificates
    systemctl enable docker || true
    systemctl start docker || true
    return
  fi
  echo "未检测到 docker，且当前系统不是 apt-get 环境。请先安装 Docker。"
  exit 1
}

prepare_source() {
  mkdir -p "$APP_ROOT" "$DATA_DIR/runs" "$DATA_DIR/data" "$DATA_DIR/logs"
  if [[ -f "$PWD/Dockerfile" && -d "$PWD/vl_app" ]]; then
    SOURCE_DIR="$PWD"
    return
  fi
  if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$SOURCE_DIR"
  else
    git -C "$SOURCE_DIR" fetch origin "$BRANCH"
    git -C "$SOURCE_DIR" checkout "$BRANCH"
    git -C "$SOURCE_DIR" pull --ff-only origin "$BRANCH"
  fi
}

build_or_load_image() {
  cd "$SOURCE_DIR"
  local release_tar="docker_release/vl-data-gen-0.4.4.tar.gz"
  if [[ -f "$release_tar" ]]; then
    gzip -dc "$release_tar" | docker load
  else
    docker build -t "$IMAGE_NAME" .
  fi
}

run_container() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "$PORT:8000" \
    -e WEB_WORKERS="$WEB_WORKERS" \
    -e WORKER_CONCURRENCY="$WORKER_CONCURRENCY" \
    -v "$DATA_DIR/runs:/app/runs" \
    -v "$DATA_DIR/data:/app/data" \
    -v "$DATA_DIR/logs:/app/logs" \
    "$IMAGE_NAME"
}

require_root
install_docker
prepare_source
build_or_load_image
run_container

echo "部署完成。"
echo "访问地址：http://服务器IP:$PORT"
echo "默认管理员：admin"
echo "默认管理员密码请按内部流程获取或修改。"
