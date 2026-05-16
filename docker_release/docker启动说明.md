# VL Data Gen Docker 启动说明

## 默认并发配置

当前镜像默认适配 20 人以内内网使用：

- `WEB_WORKERS=4`：Web 服务进程数
- `WORKER_CONCURRENCY=12`：后台数据处理 worker 数
- `PORT=8000`：容器内 Web 端口

不传环境变量时使用上述默认值。

## 构建镜像

在项目根目录执行：

```bash
cd /root/vl-data-gen
docker build -t vl-data-gen:0.2.2 .
```

## 保存镜像文件

```bash
mkdir -p docker_release
docker save vl-data-gen:0.2.2 | gzip > docker_release/vl-data-gen-0.2.2.tar.gz
```

本次已生成的镜像文件：

```text
/root/vl-data-gen/docker_release/vl-data-gen-0.2.2.tar.gz
大小：223M
SHA256：3ee4b3dac0286d74a559840c7456cff4b95e458835271d991b69f844104be7d7
```

## 加载镜像

在目标服务器执行：

```bash
gzip -dc vl-data-gen-0.2.2.tar.gz | docker load
```

## 单容器启动

```bash
mkdir -p /data/vl-data-gen/runs /data/vl-data-gen/data /data/vl-data-gen/logs

docker run -d \
  --name vl-data-gen \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /data/vl-data-gen/runs:/app/runs \
  -v /data/vl-data-gen/data:/app/data \
  -v /data/vl-data-gen/logs:/app/logs \
  vl-data-gen:0.2.2
```

访问：

```text
http://服务器IP:8000
```

## 修改并发参数

示例：Web 8 个进程，后台 16 个 worker。

```bash
docker run -d \
  --name vl-data-gen \
  --restart unless-stopped \
  -p 8000:8000 \
  -e WEB_WORKERS=8 \
  -e WORKER_CONCURRENCY=16 \
  -v /data/vl-data-gen/runs:/app/runs \
  -v /data/vl-data-gen/data:/app/data \
  -v /data/vl-data-gen/logs:/app/logs \
  vl-data-gen:0.2.2
```

建议范围：

- 20 人以内使用：`WEB_WORKERS=4-8`
- Qwen 算力充足：`WORKER_CONCURRENCY=12-16`
- 如果上传图片很大或磁盘较慢，先使用默认值 `12`

## Docker Compose 启动

项目内已提供 `docker-compose.yml`，默认启动 Redis，并使用同一个应用镜像运行 Web 与 worker。

```bash
cd /root/vl-data-gen
docker compose up -d --build
```

修改并发：

```bash
WEB_WORKERS=8 WORKER_CONCURRENCY=16 docker compose up -d --build
```

## 数据目录说明

建议挂载以下目录，避免容器删除后数据丢失：

- `/app/runs`：上传图片、中间结果、校核结果
- `/app/data`：SQLite 数据库
- `/app/logs`：Web 和 worker 日志

默认管理员账户：

```text
用户名：admin
```

默认管理员密码不在公开文档中展示；部署后请按内部流程获取或修改。

## 常用运维命令

查看日志：

```bash
docker logs -f vl-data-gen
```

查看 worker 日志：

```bash
docker exec -it vl-data-gen ls /app/logs
docker exec -it vl-data-gen tail -f /app/logs/worker-1.log
```

停止：

```bash
docker stop vl-data-gen
```

删除容器：

```bash
docker rm vl-data-gen
```

重新启动：

```bash
docker start vl-data-gen
```

## 本次环境说明

已完成：

- 当前机器已安装 Docker，并已完成镜像构建
- 镜像标签：`vl-data-gen:0.2.2`
- 镜像文件：`/root/vl-data-gen/docker_release/vl-data-gen-0.2.2.tar.gz`
- Dockerfile 已配置默认并发参数
- `docker/entrypoint.sh` 已支持通过环境变量修改并发
- `.dockerignore` 已排除运行数据、日志、账号文件和 Git 元数据
- `docker-compose.yml` 已支持 `WEB_WORKERS` 和 `WORKER_CONCURRENCY`
