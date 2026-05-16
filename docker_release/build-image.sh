#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

IMAGE_NAME="${IMAGE_NAME:-vl-data-gen:0.2.2}"
OUTPUT="${OUTPUT:-docker_release/vl-data-gen-0.2.2.tar.gz}"

docker build -t "$IMAGE_NAME" .
docker save "$IMAGE_NAME" | gzip > "$OUTPUT"

echo "镜像已保存到: $OUTPUT"
