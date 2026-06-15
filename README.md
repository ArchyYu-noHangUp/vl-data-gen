# 电力分析能力评测数据采集与标注系统

面向电力分析评测数据的采集、校核、标注与归档。系统支持上传题目图片和答案图片，调用多模态大模型抽取题干、答案、题图，人工校核后生成结构化样本数据。

当前版本：`0.5.0`

当前分支：`windows-server`

本分支用于 Windows Server 裸机部署和 Windows Containers 镜像部署。Linux 裸机和 Linux Docker 部署请使用 `main` 分支。

版本更新内容见 [CHANGELOG.md](CHANGELOG.md)。

## 版本更新记录

每次发布新版本时，必须在本节写明主要更新内容，并同步维护 [CHANGELOG.md](CHANGELOG.md)，确保 GitHub 项目首页可以直接查看各版本变化。

### 0.5.0 - 2026-06-15

- 修复Windows CRLF换行导致PDF处理结果在“查看结果”页只显示一道题的问题。
- 多个问题图片或PDF页面先分别识别，再按原始页序合并跨文件题干。
- 题图统一使用`题目编号-fig序号.png`命名，并在问题正文末尾追加图片索引。
- 题图定位使用DashScope `qwen3.5-27b`和0-1000归一化坐标策略。
- 新增问题识别2并发、题图定位3并发、答案识别2并发，结果按原始索引排序。
- 新增任务耗时日志、worker持久启动修复和具体错误信息回传。
- 保留Windows Server下FFmpeg自动查找、环境变量路径和本地临时目录适配。

### 0.4.4 - 2026-06-12

- 数据处理页的问题和答案均支持上传图片或 PDF 文件。
- PDF 按 220 DPI 分页渲染后进入多模态模型处理流程。
- 查看结果页的题目编号改为按问题提取顺序生成，不再直接使用原始材料题号。
- 问题和答案分别提取后，采用原题号优先、其余内容按顺序补配的方式进行匹配，兼容填空题、选择题、简答题等不同编号方式。
- 题目类型新增“填空题”，并同步更新大模型判断提示词。
- 查看结果页新增“删除问题”功能，删除后自动重新生成连续题目编号。
- 答案中的 LaTeX 公式自动补充 `$...$` 或 `$$...$$` 定界符，确保公式预览正常显示。
- 新增图片和 PDF 文件格式校验，并增加 PyMuPDF PDF 处理依赖。
- Linux、Docker 与 Windows Server 裸机版本均完成 PDF 处理兼容。

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
- 管理员样本数据状态查看、样本列表和样本审核
- 管理员配置样本集保存绝对路径
- 管理员下载已审核样本数据
- 标准外观 / 简洁外观切换
- Windows Server 裸机部署
- Windows Containers 镜像部署

## 推荐部署方式

### Windows Server 裸机部署

先安装以下依赖：

- Python 3.11
- Git for Windows
- ffmpeg。若系统未安装，`scripts\windows\install.ps1` 会自动下载到项目内 `tools\ffmpeg`。

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
docker build -f Dockerfile.windows -t vl-data-gen:0.5.0-windows .
docker save -o docker_release\vl-data-gen-0.5.0-windows.tar vl-data-gen:0.5.0-windows
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
  vl-data-gen:0.5.0-windows
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
- `QUESTION_PAGE_CONCURRENCY`：单个任务的问题页识别并发数，默认 `2`
- `FIGURE_CONCURRENCY`：单个任务的题图定位并发数，默认 `3`
- `ANSWER_PAGE_CONCURRENCY`：单个任务的答案页识别并发数，默认 `2`
- `VL_TEMP_FINALS`：临时校核结果目录，默认 `temp_final`

示例：

```powershell
$env:PORT="8080"
$env:WEB_WORKERS="4"
$env:WORKER_CONCURRENCY="8"
$env:QUESTION_PAGE_CONCURRENCY="2"
$env:FIGURE_CONCURRENCY="3"
$env:ANSWER_PAGE_CONCURRENCY="2"
powershell -ExecutionPolicy Bypass -File scripts\windows\start.ps1
```

## 注意事项

- `main` 分支不适用于 Windows 裸机部署；Windows Server 请使用 `windows-server` 分支。
- 仓库已设为 public，Linux 和 Windows 服务器均可直接 clone 或使用 raw 链接部署。
- `data/`、`runs/`、`logs/`、`sample_dataset/` 属于运行数据，默认不提交 Git。
- `users.json` 和 SQLite 数据库不提交 Git，避免泄露账户和会话信息。
- API Key 不会设置默认值，请由管理员在系统管理页统一配置。
- 仓库为 public 后，Windows Server 可以直接 clone；不再需要 GitHub Token。
