# Windows Server Docker 镜像说明

本说明用于构建和运行 Windows Containers 版本镜像。该镜像与现有 Linux 镜像并行，不替换原有 `Dockerfile`。

## 前提条件

- Windows Server 2019/2022，建议 Windows Server 2022。
- Docker 已切换到 Windows Containers 模式。
- 构建机器可以访问 `https://www.gyan.dev/ffmpeg/builds/` 下载 Windows 版 ffmpeg。

确认 Docker 当前是 Windows 容器模式：

```powershell
docker info
```

如果之前加载 Linux 镜像时报：

```text
cannot load linux image on windows
```

说明当前 Docker 是 Windows Containers 模式，需使用本 Windows 镜像版本。

## 构建镜像

在项目根目录执行：

```powershell
docker build -f Dockerfile.windows -t vl-data-gen:0.4.3-windows .
```

或使用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File docker_release\build-windows-image.ps1
```

默认导出文件：

```text
docker_release\vl-data-gen-0.4.3-windows.tar
```

## 加载镜像

```powershell
docker load -i D:\docker_release\vl-data-gen-0.4.3-windows.tar
```

注意：Windows Docker 的 `docker load -i` 建议直接使用 `.tar`，不要使用 `.tar.gz`。

## 启动容器

```powershell
mkdir C:\vl-data-gen\runs
mkdir C:\vl-data-gen\data
mkdir C:\vl-data-gen\logs

docker run -d `
  --name vl-data-gen `
  --restart unless-stopped `
  -p 8000:8000 `
  -e WEB_WORKERS=4 `
  -e WORKER_CONCURRENCY=12 `
  -v C:\vl-data-gen\runs:C:\app\runs `
  -v C:\vl-data-gen\data:C:\app\data `
  -v C:\vl-data-gen\logs:C:\app\logs `
  vl-data-gen:0.4.3-windows
```

访问：

```text
http://服务器IP:8000
```

## 修改并发

```powershell
docker run -d `
  --name vl-data-gen `
  --restart unless-stopped `
  -p 8000:8000 `
  -e WEB_WORKERS=8 `
  -e WORKER_CONCURRENCY=16 `
  -v C:\vl-data-gen\runs:C:\app\runs `
  -v C:\vl-data-gen\data:C:\app\data `
  -v C:\vl-data-gen\logs:C:\app\logs `
  vl-data-gen:0.4.3-windows
```

## 常用命令

查看日志：

```powershell
docker logs -f vl-data-gen
```

进入容器：

```powershell
docker exec -it vl-data-gen powershell
```

停止并删除：

```powershell
docker stop vl-data-gen
docker rm vl-data-gen
```

## 重要说明

- Windows 镜像只能在 Windows Containers 模式下构建和运行。
- Linux 主机或 Linux Docker daemon 不能构建 Windows 容器镜像。
- 当前项目运行数据仍建议挂载到宿主机目录，避免删除容器后数据丢失。
