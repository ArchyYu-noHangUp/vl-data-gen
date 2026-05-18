# 电力分析能力评测数据采集与标注系统

面向电力分析评测数据的采集、校核、标注与归档。系统支持上传题目图片和答案图片，调用多模态大模型抽取题干、答案、题图，人工校核后生成结构化样本数据。

当前版本：`0.3.0`

当前分支：`windows-server`

本分支用于 Windows Server 裸机部署和 Windows Containers 镜像部署。Linux 裸机和 Linux Docker 部署请使用 `main` 分支。

版本更新内容见 [CHANGELOG.md](CHANGELOG.md)。

默认管理员账户：

```text
用户名：admin
```

默认管理员密码不在公开文档中展示；部署后请按内部流程获取或修改。

## 功能概览

- 登录、注册、管理员账户管理
- 管理员集中配置多模态大模型 URL、模型名和 API Key
- 数据来源录入
- 题目类型、题目难度识别和人工校核
- 问题和答案 LaTeX 预览校核
- 题图裁剪、替换和归档
- 校核助手对话
- 管理员数据管理、样本集状态查看
- 管理员配置样本集保存绝对路径
- 管理员下载校核后的 zip 数据
- 标准外观 / 简洁外观切换
- Windows Server 裸机部署
- Windows Containers 镜像部署

## 推荐部署方式

### Windows Server 裸机部署

先安装以下依赖：

- Python 3.11
- Git for Windows
- ffmpeg，并将 `ffmpeg.exe` 加入 `PATH`

然后执行：

```powershell
git clone -b windows-server https://github.com/ArchyYu-noHangUp/vl-data-gen.git C:\vl-data-gen
cd C:\vl-data-gen
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1
```

部署完成后访问：

```text
http://服务器IP:8000
```

详细说明见 [Windows_Server_部署说明.md](Windows_Server_部署说明.md)。

### Windows Containers 部署

Windows 容器镜像只能在 Docker 的 Windows Containers 模式下构建和运行：

```powershell
docker build -f Dockerfile.windows -t vl-data-gen:0.3.0-windows .
docker save -o docker_release\vl-data-gen-0.3.0-windows.tar vl-data-gen:0.3.0-windows
```

启动：

```powershell
docker run -d `
  --name vl-data-gen `
  --restart unless-stopped `
  -p 8000:8000 `
  -v C:\vl-data-gen\runs:C:\app\runs `
  -v C:\vl-data-gen\data:C:\app\data `
  -v C:\vl-data-gen\logs:C:\app\logs `
  vl-data-gen:0.3.0-windows
```

Docker 详细说明见 [docker_release/windows-docker启动说明.md](docker_release/windows-docker启动说明.md)。

## 本地开发启动

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
mkdir data,runs,logs,sample_dataset,temp_final
.\.venv\Scripts\python.exe -m uvicorn vl_app.main:app --host 0.0.0.0 --port 8000 --reload
```

另开终端启动 worker：

```powershell
.\.venv\Scripts\python.exe -m vl_app.worker
```

访问：

```text
http://127.0.0.1:8000
```

## 目录说明

- `vl_app/`：FastAPI 应用、数据库、任务队列、worker
- `static/`：前端页面和样式
- `pic_files/`：欢迎页背景、机器人图标等静态素材
- `docker/`：Docker 入口脚本
- `docker_release/`：Docker 镜像构建脚本和启动说明
- `scripts/windows/`：Windows Server 安装和启动脚本
- `runs/`：运行时上传文件和中间结果，默认不提交
- `data/`：SQLite 数据库，默认不提交
- `logs/`：日志，默认不提交
- `sample_dataset/`：样本集目录，默认不提交

## 配置参数

- `PORT`：Web 端口，默认 `8000`
- `WEB_WORKERS`：Web 进程数，默认 `4`
- `WORKER_CONCURRENCY`：worker 数，裸机默认 `4`，Windows 容器默认 `12`
- `VL_TEMP_FINALS`：临时校核结果目录，默认 `temp_final`

示例：

```powershell
$env:PORT="8080"
$env:WEB_WORKERS="4"
$env:WORKER_CONCURRENCY="8"
powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1
```

## 注意事项

- `data/`、`runs/`、`logs/`、`sample_dataset/` 属于运行数据，默认不提交 Git。
- `users.json` 和 SQLite 数据库不提交 Git，避免泄露账户和会话信息。
- API Key 不会设置默认值，请由管理员在系统管理页统一配置。
- 仓库为 public 后，Windows Server 可以直接 clone；不再需要 GitHub Token。
