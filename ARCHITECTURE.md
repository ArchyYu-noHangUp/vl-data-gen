# 电力分析能力评测数据采集与标注系统架构

## 组件

- `web`: FastAPI，负责登录、注册、页面、文件上传、结果校核 API。
- `worker`: 独立 Python 进程，负责调用 Qwen、题图裁剪、答案识别、打包 zip。
- `redis`: 任务队列。未配置 Redis 时，代码会回退到 SQLite 队列表，便于单机调试。
- `sqlite`: `data/app.db`，保存账户、session、任务状态和统计基础数据。
- `nginx`: 静态资源和反向代理，容器外暴露 `8000` 端口。
- `volume`: `runs/` 保存上传文件、模型输出、裁图和 zip；`data/` 保存 SQLite。

## 资源建议

4 核 8G 可以运行该方案。Qwen 是远程 API，本机主要消耗在图片压缩、裁剪和上传缓存。

建议初始配置：

- `web`: 1 个 Uvicorn worker。
- `worker`: 1 个进程，避免并发调用模型导致内存和接口超时压力。
- `redis`: 默认配置即可。
- `sqlite`: 当前账户和任务规模足够；后续多用户并发明显增加时再换 Postgres。

## 启动命令

裸机安装依赖后启动：

```bash
cd /root/vl-data-gen
uvicorn vl_app.main:app --host 0.0.0.0 --port 8000
python -m vl_app.worker
```

Docker Compose 启动：

```bash
cd /root/vl-data-gen
docker compose up -d --build
```

旧版单进程回退启动命令仍然保留：

```bash
cd /root/vl-data-gen
python3 server.py
```
