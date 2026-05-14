import base64
import json
import mimetypes
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import requests

import server as legacy
from . import db
from .queue import enqueue


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
RUNS = ROOT / "runs"
PIC_FILES = ROOT / "pic_files"

app = FastAPI(title="电力分析能力评测数据采集与标注系统")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
if PIC_FILES.exists():
    app.mount("/pic_files", StaticFiles(directory=PIC_FILES), name="pic_files")


@app.on_event("startup")
def startup():
    RUNS.mkdir(exist_ok=True)
    db.init_db()


def current_user(request: Request):
    return db.user_for_session(request.cookies.get("sid", ""))


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def can_access(user, job_id):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    job = db.get_job(job_id)
    if job:
        return job.get("owner") == user.get("username")
    return legacy.read_job_meta(job_id).get("owner") == user.get("username")


def update_job_meta(job_id, data):
    job_dir = RUNS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    meta_path = job_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta.update(data)
    meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def job_model_config(job_id):
    meta = legacy.read_job_meta(job_id)
    config = meta.get("model_config") or {}
    if not config.get("api_key"):
        return None
    return {
        "url": (config.get("url") or legacy.DEFAULT_URL).strip(),
        "model_name": (config.get("model_name") or legacy.DEFAULT_MODEL).strip(),
        "api_key": str(config.get("api_key") or "").strip(),
    }


def call_chat_model(config, message, uploads):
    base_url = config["url"].rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    content = []
    if message:
        content.append({"type": "text", "text": message})
    for upload in uploads:
        raw = upload.file.read()
        if not raw:
            continue
        mime = upload.content_type or mimetypes.guess_type(upload.filename or "")[0] or "image/jpeg"
        encoded = base64.b64encode(raw).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    payload = {
        "model": config["model_name"],
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "enable_thinking": False,
    }
    headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=180)
    if resp.status_code in (400, 422) and "enable_thinking" in resp.text:
        payload.pop("enable_thinking", None)
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"].get("content", "")
    if isinstance(content, list):
        return "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def html_file(name):
    return FileResponse(STATIC / name, media_type="text/html; charset=utf-8")


def set_sid_cookie(response: Response, sid):
    response.set_cookie("sid", sid, httponly=True, samesite="lax", path="/")


def clear_sid_cookie(response: Response):
    response.delete_cookie("sid", path="/")


@app.get("/")
def welcome(request: Request):
    if current_user(request):
        return RedirectResponse("/app", status_code=302)
    return html_file("welcome.html")


@app.get("/app")
def processing_page(request: Request):
    require_user(request)
    return html_file("app.html")


@app.get("/register")
def register_page():
    return html_file("register.html")


@app.get("/manage")
def manage_page(request: Request):
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return html_file("manage.html")


@app.get("/logout")
def logout(request: Request):
    db.delete_session(request.cookies.get("sid", ""))
    response = RedirectResponse("/", status_code=302)
    clear_sid_cookie(response)
    return response


@app.post("/login-form")
async def login_form(username: str = Form(""), password: str = Form("")):
    user = db.verify_user(username.strip(), password)
    if not user:
        return RedirectResponse("/?error=login", status_code=302)
    response = RedirectResponse("/app", status_code=302)
    set_sid_cookie(response, db.create_session(user["username"]))
    return response


@app.post("/api/login")
async def api_login(payload: dict):
    user = db.verify_user(str(payload.get("username", "")).strip(), str(payload.get("password", "")))
    if not user:
        return JSONResponse({"error": "用户名或密码错误"}, status_code=401)
    response = JSONResponse({"ok": True, "user": user})
    set_sid_cookie(response, db.create_session(user["username"]))
    return response


@app.post("/api/register")
async def api_register(payload: dict):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    repeat = str(payload.get("repeat", ""))
    code = str(payload.get("code", "")).strip()
    if not username or not password:
        return JSONResponse({"error": "请填写用户名和密码"}, status_code=400)
    if password != repeat:
        return JSONResponse({"error": "两次密码不一致"}, status_code=400)
    if code != db.get_register_code():
        return JSONResponse({"error": "注册码错误"}, status_code=400)
    if db.get_user(username):
        return JSONResponse({"error": "用户名已存在"}, status_code=400)
    user = db.create_user(username, password)
    response = JSONResponse({"ok": True, "user": user})
    set_sid_cookie(response, db.create_session(username))
    return response


@app.post("/api/logout")
def api_logout(request: Request):
    db.delete_session(request.cookies.get("sid", ""))
    response = JSONResponse({"ok": True})
    clear_sid_cookie(response)
    return response


@app.get("/api/me")
def api_me(request: Request):
    return {"user": current_user(request)}


@app.get("/api/default-config")
def default_config(request: Request):
    require_user(request)
    return {"url": legacy.DEFAULT_URL, "model_name": legacy.DEFAULT_MODEL, "api_key": ""}


class UploadWrapper:
    def __init__(self, upload: UploadFile):
        self.filename = upload.filename
        self.file = upload.file


def create_job_dirs(job_id, owner):
    job_dir = RUNS / job_id
    output_dir = job_dir / legacy.OUTPUT_NAME
    (output_dir / legacy.FIG_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (output_dir / legacy.ANSWER_DIR_NAME).mkdir(parents=True, exist_ok=True)
    legacy.write_job_meta(job_id, owner)
    update_job_meta(job_id, {"owner": owner})
    db.upsert_job(job_id, owner, "uploading")
    return job_dir


def write_initial_log(job_dir):
    logs = [f"{time.strftime('%H:%M:%S')} 正在保存并压缩上传图片"]
    legacy.write_process_log(job_dir, logs)
    return logs


@app.post("/api/process")
async def process(request: Request):
    user = require_user(request)
    form = await request.form()
    url = str(form.get("url") or legacy.DEFAULT_URL)
    model_name = str(form.get("model_name") or legacy.DEFAULT_MODEL)
    api_key = str(form.get("api_key") or "")
    data_source = str(form.get("data_source") or "")
    config = {"url": url.strip() or legacy.DEFAULT_URL, "model_name": model_name.strip() or legacy.DEFAULT_MODEL, "api_key": api_key.strip()}
    if not config["api_key"]:
        return JSONResponse({"error": "请填写 api_key"}, status_code=400)
    question_images = [item for item in form.getlist("question_images") if getattr(item, "filename", None)]
    answer_images = [item for item in form.getlist("answer_images") if getattr(item, "filename", None)]
    if not question_images and not answer_images:
        return JSONResponse({"error": "请至少上传一张图片"}, status_code=400)

    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job_dir = create_job_dirs(job_id, user["username"])
    update_job_meta(job_id, {"model_config": config})
    logs = write_initial_log(job_dir)
    try:
        upload_dir = job_dir / "uploads"
        saved_questions = legacy.save_uploads([UploadWrapper(item) for item in question_images], upload_dir / "questions")
        saved_answers = legacy.save_uploads([UploadWrapper(item) for item in answer_images], upload_dir / "answers")
    except Exception as exc:
        db.update_job_status(job_id, "failed")
        return JSONResponse({"error": str(exc)}, status_code=500)

    logs.append(f"{time.strftime('%H:%M:%S')} 上传完成，任务已进入队列")
    legacy.write_process_log(job_dir, logs)
    db.update_job_status(job_id, "queued")
    backend = enqueue(
        job_id,
        {
            "job_id": job_id,
            "owner": user["username"],
            "config": config,
            "question_paths": [str(path) for path in saved_questions],
            "answer_paths": [str(path) for path in saved_answers],
            "data_source": data_source.strip(),
        },
    )
    return {
        "job_id": job_id,
        "status": "processing",
        "queue": backend,
        "status_url": f"/api/status/{job_id}",
        "logs": logs,
    }


@app.get("/api/status/{job_id}")
def status(job_id: str, request: Request):
    user = require_user(request)
    if not can_access(user, job_id):
        return JSONResponse({"error": "无权访问该任务"}, status_code=403)
    payload = legacy.job_status_payload(job_id)
    job = db.get_job(job_id)
    if not payload:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if job and payload.get("status") != "completed":
        payload["status"] = "processing" if job["status"] in {"queued", "running"} else job["status"]
    return payload


@app.get("/api/latest-result")
def latest_result(request: Request):
    user = require_user(request)
    latest = legacy.latest_completed_job(user)
    if not latest:
        return JSONResponse({"error": "暂无已完成任务"}, status_code=404)
    return latest


@app.get("/api/admin/stats")
def admin_stats(request: Request):
    user = require_user(request)
    if user.get("role") != "admin":
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
    stats = {item["username"]: {"username": item["username"], "collected": 0, "reviewed": 0} for item in db.list_users()}
    for job_dir in RUNS.iterdir() if RUNS.exists() else []:
        if not job_dir.is_dir():
            continue
        meta = legacy.read_job_meta(job_dir.name)
        owner = meta.get("owner")
        if not owner:
            job = db.get_job(job_dir.name)
            owner = job.get("owner") if job else ""
        if not owner:
            continue
        stats.setdefault(owner, {"username": owner, "collected": 0, "reviewed": 0})
        stats[owner]["collected"] += legacy.count_markdown_questions(job_dir / legacy.OUTPUT_NAME / "test_data.md")
        stats[owner]["reviewed"] += int(meta.get("reviewed_count") or 0)
    return {"users": list(stats.values())}


@app.post("/api/suggestions")
async def create_suggestion(request: Request, payload: dict):
    user = require_user(request)
    content = str(payload.get("content", "")).strip()
    if not content:
        return JSONResponse({"error": "请填写修改建议"}, status_code=400)
    db.add_suggestion(user["username"], content)
    return {"ok": True}


@app.get("/api/admin/settings")
def admin_settings(request: Request):
    user = require_user(request)
    if user.get("role") != "admin":
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
    return {"register_code": db.get_register_code()}


@app.post("/api/admin/settings")
async def update_admin_settings(request: Request, payload: dict):
    user = require_user(request)
    if user.get("role") != "admin":
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
    register_code = str(payload.get("register_code", "")).strip()
    if not register_code:
        return JSONResponse({"error": "注册码不能为空"}, status_code=400)
    db.set_register_code(register_code)
    return {"ok": True, "register_code": register_code}


@app.get("/api/admin/suggestions")
def admin_suggestions(request: Request):
    user = require_user(request)
    if user.get("role") != "admin":
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
    return {"suggestions": db.list_suggestions()}


@app.get("/download/{job_id}")
def download(job_id: str, request: Request):
    user = require_user(request)
    if not can_access(user, job_id):
        raise HTTPException(status_code=403, detail="无权访问该任务")
    path = RUNS / job_id / f"{legacy.OUTPUT_NAME}.zip"
    return FileResponse(path, filename=f"{legacy.OUTPUT_NAME}.zip")


@app.get("/file/{job_id}/test_data.md")
def markdown_file(job_id: str, request: Request):
    user = require_user(request)
    if not can_access(user, job_id):
        raise HTTPException(status_code=403, detail="无权访问该任务")
    return FileResponse(RUNS / job_id / legacy.OUTPUT_NAME / "test_data.md", media_type="text/markdown; charset=utf-8")


@app.get("/asset/{job_id}/{rel_path:path}")
def asset(job_id: str, rel_path: str, request: Request):
    user = require_user(request)
    if not can_access(user, job_id):
        raise HTTPException(status_code=403, detail="无权访问该任务")
    base = (RUNS / job_id / legacy.OUTPUT_NAME).resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="非法路径")
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@app.post("/api/save-result")
async def save_result(request: Request):
    user = require_user(request)
    form = await request.form()
    job_id = str(form.get("job_id", "")).strip()
    payload_text = str(form.get("payload", ""))
    if not job_id:
        return JSONResponse({"error": "缺少 job_id"}, status_code=400)
    if not can_access(user, job_id):
        return JSONResponse({"error": "无权访问该任务"}, status_code=403)
    try:
        payload = json.loads(payload_text)
        items = payload.get("items", [])
        files_by_key = {
            key: value
            for key, value in form.multi_items()
            if getattr(value, "filename", None) and getattr(value, "file", None)
        }
        result = legacy.save_result_edits(job_id, items, files_by_key)
        db.update_job_status(job_id, "completed", reviewed_count=len(items))
        return result
    except Exception as exc:
        RUNS.mkdir(exist_ok=True)
        with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] FastAPI SaveResult\n{traceback.format_exc()}\n")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/job-chat")
async def job_chat(request: Request):
    user = require_user(request)
    form = await request.form()
    job_id = str(form.get("job_id") or "")
    message = str(form.get("message") or "")
    job_id = job_id.strip()
    if not job_id:
        return JSONResponse({"error": "缺少 job_id"}, status_code=400)
    if not can_access(user, job_id):
        return JSONResponse({"error": "无权访问该任务"}, status_code=403)
    config = job_model_config(job_id)
    if not config:
        return JSONResponse({"error": "该任务没有可用的模型配置，请重新处理生成结果"}, status_code=400)
    uploads = [item for item in form.getlist("images") if getattr(item, "filename", None)]
    if not message.strip() and not uploads:
        return JSONResponse({"error": "请输入文字或上传图片"}, status_code=400)
    try:
        answer = call_chat_model(config, message.strip(), uploads)
        return {"answer": answer}
    except requests.HTTPError as exc:
        body = exc.response.text[:1200] if exc.response is not None else str(exc)
        return JSONResponse({"error": f"模型接口请求失败：{body}"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
