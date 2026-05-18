# 电力分析能力评测数据采集与标注系统

面向电力分析评测数据的采集、校核、标注与归档。系统支持上传题目图片和答案图片，调用多模态大模型抽取题干、答案、题图，人工校核后生成结构化样本数据。

当前版本：`0.3.0`

当前分支：`main`

本分支用于 Linux 裸机部署和 Linux Docker 部署。Windows Server 裸机和 Windows Containers 部署请使用 [`windows-server`](https://github.com/ArchyYu-noHangUp/vl-data-gen/tree/windows-server) 分支。

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
- Docker 部署和裸机部署

## 推荐部署方式

### Windows Server

请切换到 `windows-server` 分支：

```powershell
git clone -b windows-server https://github.com/ArchyYu-noHangUp/vl-data-gen.git C:\vl-data-gen
cd C:\vl-data-gen
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1
```

Windows 详细说明见 [`windows-server` 分支](https://github.com/ArchyYu-noHangUp/vl-data-gen/tree/windows-server)。

### 裸机一键部署

适用于 Linux 服务器：

```bash
curl -fsSL https://raw.githubusercontent.com/ArchyYu-noHangUp/vl-data-gen/main/scripts/install_bare_metal.sh | sudo bash
```

部署完成后访问：

```text
http://服务器IP:8000
```

详细说明见 [裸机部署说明.md](裸机部署说明.md)。

### Docker 一键部署

在已安装 Linux Docker 的服务器上：

```bash
git clone https://github.com/ArchyYu-noHangUp/vl-data-gen.git
cd vl-data-gen
sudo bash scripts/install_and_deploy.sh
```

或使用本机已生成的镜像包：

```bash
gzip -dc docker_release/vl-data-gen-0.3.0.tar.gz | docker load
docker run -d \
  --name vl-data-gen \
  --restart unless-stopped \
  -p 8000:8000 \
  -v /data/vl-data-gen/runs:/app/runs \
  -v /data/vl-data-gen/data:/app/data \
  -v /data/vl-data-gen/logs:/app/logs \
  vl-data-gen:0.3.0
```

Docker 详细说明见 [docker_release/docker启动说明.md](docker_release/docker启动说明.md)。

## 本地开发启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p data runs logs sample_dataset
.venv/bin/uvicorn vl_app.main:app --host 0.0.0.0 --port 8000 --reload
```

另开终端启动 worker：

```bash
.venv/bin/python -m vl_app.worker
```

访问：

```text
http://127.0.0.1:8000
```

## 目录说明

- `vl_app/`：FastAPI 应用、数据库、任务队列、worker
- `static/`：前端页面和样式
- `pic_files/`：欢迎页背景、机器人图标等静态素材
- `docker/`：Docker 入口脚本和 nginx 配置
- `docker_release/`：Docker 镜像构建脚本和启动说明
- `scripts/`：一键部署脚本
- `runs/`：运行时上传文件和中间结果，默认不提交
- `data/`：SQLite 数据库，默认不提交
- `logs/`：日志，默认不提交
- `sample_dataset/`：样本集目录，默认不提交

## 配置参数

### 裸机部署

`scripts/install_bare_metal.sh` 支持：

- `PORT`：Web 端口，默认 `8000`
- `WEB_WORKERS`：Web 进程数，默认 `4`
- `WORKER_CONCURRENCY`：worker 数，默认 `4`
- `APP_ROOT`：安装根目录，默认 `/opt/vl-data-gen`
- `BRANCH`：Git 分支，默认 `main`

示例：

```bash
sudo PORT=8080 WEB_WORKERS=8 WORKER_CONCURRENCY=16 bash scripts/install_bare_metal.sh
```

### Docker 部署

Docker 默认：

- `WEB_WORKERS=4`
- `WORKER_CONCURRENCY=12`
- `PORT=8000`

示例：

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
  vl-data-gen:0.3.0
```

## 注意事项

- `main` 分支不适用于 Windows 裸机部署；Windows Server 请使用 `windows-server` 分支。
- 仓库已设为 public，Linux 和 Windows 服务器均可直接 clone 或使用 raw 链接部署。
- `data/`、`runs/`、`logs/`、`sample_dataset/` 属于运行数据，默认不提交 Git。
- `users.json` 和 SQLite 数据库不提交 Git，避免泄露账户和会话信息。
- API Key 不会设置默认值，请由管理员在系统管理页统一配置。
