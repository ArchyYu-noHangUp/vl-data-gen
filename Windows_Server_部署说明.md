# Windows Server 部署说明

本分支为 Windows Server 适配分支：`windows-server`。

## 方式一：Windows 裸机部署

### 依赖

- Windows Server 2019/2022
- Python 3.11
- Git for Windows
- ffmpeg。若系统未安装，安装脚本会自动下载到项目内 `tools\ffmpeg`，启动脚本会自动配置本次服务进程使用。

### 拉取代码

```powershell
git clone -b windows-server https://github.com/ArchyYu-noHangUp/vl-data-gen.git C:\vl-data-gen
cd C:\vl-data-gen
```

### 安装依赖

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
```

### 启动服务

```powershell
cd C:\vl-data-gen
powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1
```

访问：

```text
http://服务器IP:8000
```

### 修改端口和并发

```powershell
$env:PORT="8080"
$env:WEB_WORKERS="4"
$env:WORKER_CONCURRENCY="8"
powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1
```

## 方式二：Windows Containers 镜像

Windows 容器镜像只能在 Docker 的 Windows Containers 模式下构建和运行。

```powershell
docker build -f Dockerfile.windows -t vl-data-gen:0.4.4-windows .
docker save -o docker_release\vl-data-gen-0.4.4-windows.tar vl-data-gen:0.4.4-windows
```

启动：

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
  vl-data-gen:0.4.4-windows
```

## 说明

- 默认只保留 SQLite 队列回退能力，不强制依赖 Redis。
- 系统运行数据在 `data`、`runs`、`logs`、`sample_dataset`、`temp_final` 目录中。
- 如果处理时报 `[WinError 2] The system cannot find the file specified`，通常是 `ffmpeg/ffprobe` 未安装或未被服务进程识别。请重新执行 `scripts\windows\install.ps1` 后再执行 `scripts\windows\start.ps1`。
- 管理员账号仍由系统初始化创建，公开文档不展示默认密码。
