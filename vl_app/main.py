import base64
import csv
import io
import json
import mimetypes
import os
import re
import shutil
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import requests

import server as legacy
from . import db
from .queue import enqueue


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
RUNS = ROOT / "runs"
PIC_FILES = ROOT / "pic_files"
TEMP_FINALS = Path(os.environ.get("VL_TEMP_FINALS", str(ROOT / "temp_final")))
DEFAULT_SAMPLE_DATASET = ROOT / "sample_dataset"
APP_VERSION = "0.4.3"

app = FastAPI(title="电力分析能力评测数据采集与标注系统")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
if PIC_FILES.exists():
    app.mount("/pic_files", StaticFiles(directory=PIC_FILES), name="pic_files")


@app.on_event("startup")
def startup():
    RUNS.mkdir(exist_ok=True)
    TEMP_FINALS.mkdir(parents=True, exist_ok=True)
    db.init_db()
    sample_dataset_root().mkdir(parents=True, exist_ok=True)
    db.cleanup_expired_sessions()


def current_user(request: Request):
    sid = request.cookies.get("sid", "")
    user = db.user_for_session(sid)
    if user:
        return user
    db.pop_expired_session_username(sid)
    return None


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


def require_admin(request: Request):
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def safe_folder_name(name):
    return legacy.safe_folder_name(name)


def sample_dataset_root():
    configured = db.get_setting("sample_dataset_path", str(DEFAULT_SAMPLE_DATASET))
    return Path(configured).expanduser().resolve()


def move_sample_dataset(new_path):
    target = Path(new_path).expanduser()
    if not target.is_absolute():
        raise ValueError("样本集路径必须是绝对路径")
    target = target.resolve()
    current = sample_dataset_root()
    if target == current:
        target.mkdir(parents=True, exist_ok=True)
        db.set_setting("sample_dataset_path", str(target))
        return str(target)
    try:
        target.relative_to(current)
        raise ValueError("新路径不能位于当前样本集路径内部")
    except ValueError as exc:
        if "新路径不能" in str(exc):
            raise
    target.parent.mkdir(parents=True, exist_ok=True)
    if current.exists() and any(current.iterdir()):
        if target.exists():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(current, target, dirs_exist_ok=True)
            shutil.rmtree(current)
        else:
            shutil.move(str(current), str(target))
    else:
        target.mkdir(parents=True, exist_ok=True)
        if current.exists() and current != DEFAULT_SAMPLE_DATASET:
            shutil.rmtree(current, ignore_errors=True)
    db.set_setting("sample_dataset_path", str(target))
    return str(target)


def question_chapter(qid):
    text = str(qid or "").strip()
    return text.split("-", 1)[0] if "-" in text else text


def status_counts(job_id):
    md_path = RUNS / job_id / legacy.OUTPUT_NAME / "test_data.md"
    return {
        "question_count": legacy.count_markdown_questions(md_path),
        "figure_count": len(list((RUNS / job_id / legacy.OUTPUT_NAME / legacy.FIG_DIR_NAME).glob("*")))
        if (RUNS / job_id / legacy.OUTPUT_NAME / legacy.FIG_DIR_NAME).exists()
        else 0,
        "answer_count": legacy.count_markdown_answers(md_path),
        "markdown_url": f"/file/{job_id}/test_data.md",
        "result_url": f"/static/result.html?job_id={job_id}",
    }


def job_payload(job_id):
    payload = legacy.job_status_payload(job_id)
    job = db.get_job(job_id)
    if not payload and not job:
        return None
    if not payload:
        payload = {"job_id": job_id, "status": job.get("status", "processing"), "logs": []}
    if job:
        db_status = job.get("status", "")
        if db_status in {"uploading", "queued", "running"}:
            payload["status"] = "processing"
        elif db_status:
            payload["status"] = db_status
    if (RUNS / job_id / legacy.OUTPUT_NAME / "test_data.md").exists():
        payload.update(status_counts(job_id))
    return payload


def is_final_completed(job_id):
    return bool(legacy.read_job_meta(job_id).get("final_completed"))


def final_figure_name(figure_rel):
    stem = safe_folder_name(Path(str(figure_rel)).stem)
    return f"{stem}.jpg"


def copy_item_figures(job_id, item, target_dir):
    output_dir = RUNS / job_id / legacy.OUTPUT_NAME
    figures = [fig for fig in item.get("figures", []) if fig]
    copied = {}
    used_names = set()
    for figure in figures:
        source = (output_dir / figure).resolve()
        try:
            source.relative_to(output_dir.resolve())
        except ValueError:
            continue
        if not source.exists():
            continue
        filename = final_figure_name(figure)
        if filename in used_names:
            filename = f"{safe_folder_name(source.stem)}_{len(used_names) + 1}.jpg"
        shutil.copyfile(source, target_dir / filename)
        copied[source.stem] = filename
        used_names.add(filename)
    return copied


def question_with_figure_links(question, figure_map):
    if not question or not figure_map:
        return question

    def repl(match):
        raw_ref = match.group(1)
        ref = raw_ref.replace("－", "-").replace("—", "-")
        filename = figure_map.get(ref)
        if not filename:
            return match.group(0)
        return f"题图![{ref}]({filename}) "

    return re.sub(r"题图(?!\!)\s*([0-9]+(?:[-－—][0-9]+)?)\s*", repl, question)


def replace_markdown_source(md_text, source):
    return re.sub(r"(#（六）题目来源\n)(.*?)(\n?$)", rf"\1{source}\3", md_text, flags=re.S)


SAMPLE_INFO_FIELDS = ["序号", "数据来源", "样本编号", "创建用户", "创建时间", "状态", "备注"]


def sample_source_dir(data_source):
    return sample_dataset_root() / safe_folder_name(data_source or "数据来源")


def sample_info_path(source_dir):
    return source_dir / f"{source_dir.name}.csv"


def read_sample_info(source_dir):
    path = sample_info_path(source_dir)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_sample_info(source_dir, rows):
    source_dir.mkdir(parents=True, exist_ok=True)
    with sample_info_path(source_dir).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_INFO_FIELDS)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            item = {field: str(row.get(field, "")) for field in SAMPLE_INFO_FIELDS}
            item["序号"] = str(index)
            writer.writerow(item)


def upsert_sample_info(source_dir, data_source, sample_id, username, created_at, status="未审核", remark=""):
    rows = read_sample_info(source_dir)
    found = False
    for row in rows:
        if row.get("样本编号") == sample_id:
            row.update({"数据来源": data_source, "创建用户": username, "创建时间": created_at, "状态": status, "备注": remark})
            found = True
            break
    if not found:
        rows.append(
            {
                "序号": "",
                "数据来源": data_source,
                "样本编号": sample_id,
                "创建用户": username,
                "创建时间": created_at,
                "状态": status,
                "备注": remark,
            }
        )
    write_sample_info(source_dir, rows)


def unique_sample_dir(source_dir, qid):
    base = safe_folder_name(qid)
    target = source_dir / base
    if not target.exists():
        return target
    index = 2
    while True:
        candidate = source_dir / f"{base}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def normalize_sample_source_dir(source_dir):
    for child in list(source_dir.iterdir()) if source_dir.exists() else []:
        if not child.is_dir() or (child / "data.md").exists():
            continue
        for nested in list(child.iterdir()):
            if not nested.is_dir() or not (nested / "data.md").exists():
                continue
            target = source_dir / nested.name
            if target.exists():
                target = unique_sample_dir(source_dir, nested.name)
            shutil.move(str(nested), str(target))
        try:
            child.rmdir()
        except OSError:
            pass


def sync_sample_info(source_dir):
    normalize_sample_source_dir(source_dir)
    rows = [row for row in read_sample_info(source_dir) if (source_dir / safe_folder_name(row.get("样本编号", ""))).exists()]
    known = {row.get("样本编号", "") for row in rows}
    for sample_dir in sorted([path for path in source_dir.iterdir() if path.is_dir()], key=lambda path: legacy.question_sort_key(path.name)):
        if sample_dir.name not in known:
            rows.append(
                {
                    "序号": "",
                    "数据来源": source_dir.name,
                    "样本编号": sample_dir.name,
                    "创建用户": "",
                    "创建时间": "",
                    "状态": "未审核",
                    "备注": "",
                }
            )
    rows = sorted(rows, key=lambda row: legacy.question_sort_key(row.get("样本编号", "")))
    write_sample_info(source_dir, rows)
    return rows


def create_final_records(job_id, username):
    md_path = RUNS / job_id / legacy.OUTPUT_NAME / "test_data.md"
    if not md_path.exists():
        raise FileNotFoundError("test_data.md 不存在")
    records = legacy.parse_markdown_records(md_path.read_text(encoding="utf-8"))
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    saved = []
    for qid in sorted(records, key=legacy.question_sort_key):
        item = records[qid]
        data_source = item.get("source", "").strip() or "数据来源"
        source_dir = sample_source_dir(data_source)
        item_dir = unique_sample_dir(source_dir, qid)
        item_dir.mkdir(parents=True, exist_ok=True)
        figure_map = copy_item_figures(job_id, item, item_dir)
        final_item = dict(item)
        final_item["question"] = question_with_figure_links(item.get("question", ""), figure_map)
        (item_dir / "data.md").write_text(legacy.question_markdown(final_item), encoding="utf-8")
        upsert_sample_info(source_dir, data_source, item_dir.name, username, generated_at, status="未审核")
        saved.append(str(item_dir))
    db.delete_pending_final_items(job_id)
    update_job_meta(job_id, {"final_completed": True, "final_completed_at": generated_at, "sample_dirs": saved})
    return generated_at


def make_review_zip(job_id):
    temp_root = TEMP_FINALS / job_id
    if not temp_root.exists():
        raise FileNotFoundError("最终结果不存在，请先完成校核")
    zip_path = RUNS / job_id / f"{legacy.OUTPUT_NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with legacy.zipfile.ZipFile(zip_path, "w", compression=legacy.zipfile.ZIP_DEFLATED) as zf:
        for path in temp_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(temp_root.parent))
    return zip_path


def cleanup_job_artifacts(job_id):
    shutil.rmtree(TEMP_FINALS / job_id, ignore_errors=True)
    shutil.rmtree(RUNS / job_id, ignore_errors=True)


def sample_dataset_status():
    items = []
    sample_root = sample_dataset_root()
    if not sample_root.exists():
        return items
    for index, source_dir in enumerate(sorted([path for path in sample_root.iterdir() if path.is_dir()], key=lambda p: p.name), start=1):
        rows = sync_sample_info(source_dir)
        pending = sum(1 for row in rows if row.get("状态", "未审核") == "未审核")
        approved = sum(1 for row in rows if row.get("状态") == "已审核")
        items.append(
            {
                "index": index,
                "data_source": source_dir.name,
                "pending_count": pending,
                "approved_count": approved,
            }
        )
    return items


def sample_record(source, sample_id):
    source_dir = sample_source_dir(source)
    sample_dir = (source_dir / safe_folder_name(sample_id)).resolve()
    try:
        sample_dir.relative_to(source_dir.resolve())
    except ValueError:
        return None
    data_path = sample_dir / "data.md"
    if not data_path.exists():
        return None
    rows = read_sample_info(source_dir)
    info = next((row for row in rows if row.get("样本编号") == sample_dir.name), {})
    item = parse_sample_data_md(data_path.read_text(encoding="utf-8"))
    figures = [path.name for path in sorted(sample_dir.glob("*.jpg"))]
    return {
        "source": source_dir.name,
        "sample_id": sample_dir.name,
        "info": info,
        "type": item.get("type", ""),
        "difficulty": item.get("difficulty", ""),
        "question": item.get("question", ""),
        "answer": item.get("answer", ""),
        "figures": figures,
    }


def parse_sample_data_md(text):
    mapping = {
        "（一）题目类型": "type",
        "（二）题目难度": "difficulty",
        "（三）问题": "question",
        "（四）答案": "answer",
        "（五）解答过程": "solution",
        "（六）题目来源": "source",
    }
    data = {value: "" for value in mapping.values()}
    current = None
    for line in text.splitlines():
        match = re.match(r"^#\s*(（[一二三四五六]）.+)$", line.strip())
        if match:
            current = mapping.get(match.group(1).strip())
            if current:
                data[current] = []
            continue
        if current:
            data[current].append(line)
    return {key: "\n".join(value).strip() if isinstance(value, list) else value for key, value in data.items()}


def sample_data_markdown(item):
    return "\n".join(
        [
            "#（一）题目类型",
            str(item.get("type", "")).strip(),
            "#（二）题目难度",
            str(item.get("difficulty", "")).strip(),
            "#（三）问题",
            str(item.get("question", "")).strip(),
            "#（四）答案",
            str(item.get("answer", "")).strip(),
            "#（五）解答过程",
            str(item.get("solution", "解答过程暂略")).strip() or "解答过程暂略",
            "#（六）题目来源",
            str(item.get("source", "")).strip(),
            "",
        ]
    )


def update_sample_status(source, sample_id, status, remark=None):
    source_dir = sample_source_dir(source)
    rows = read_sample_info(source_dir)
    for row in rows:
        if row.get("样本编号") == sample_id:
            row["状态"] = status
            if remark is not None:
                row["备注"] = remark
            write_sample_info(source_dir, rows)
            return True
    return False


def cleanup_user_intermediate(username):
    for job_dir in RUNS.iterdir() if RUNS.exists() else []:
        if not job_dir.is_dir():
            continue
        meta = legacy.read_job_meta(job_dir.name)
        if meta.get("owner") != username or meta.get("final_completed"):
            continue
        job = db.get_job(job_dir.name)
        if job and job.get("status") in {"queued", "running"}:
            continue
        shutil.rmtree(job_dir, ignore_errors=True)


def reset_user_cache(username):
    job_ids = set(db.account_job_ids(username))
    for job_dir in RUNS.iterdir() if RUNS.exists() else []:
        if not job_dir.is_dir():
            continue
        meta = legacy.read_job_meta(job_dir.name)
        if meta.get("owner") == username:
            job_ids.add(job_dir.name)
    db.reset_account_cache(username, job_ids)
    for job_id in job_ids:
        shutil.rmtree(RUNS / job_id, ignore_errors=True)
        shutil.rmtree(TEMP_FINALS / job_id, ignore_errors=True)
    return sorted(job_ids)


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


def welcome_html():
    html = (STATIC / "welcome.html").read_text(encoding="utf-8")
    if db.get_appearance_mode() != "simple":
        return HTMLResponse(html)
    html = html.replace(
        "<title>电力分析能力评测数据采集与标注系统</title>",
        "<title>评测数据采集与标注</title>",
    )
    html = html.replace(
        '<body class="welcome-page">',
        '<body class="welcome-page simple-appearance">',
    )
    html = html.replace(
        '<h1 id="welcomeTitle">电力分析能力评测数据采集与标注系统</h1>',
        '<h1 id="welcomeTitle">评测数据采集与标注</h1>',
    )
    html = html.replace(
        '<p id="welcomeSubtitle">面向电力分析评测数据的采集、校核、标注与归档。</p>',
        '<p id="welcomeSubtitle" hidden>面向电力分析评测数据的采集、校核、标注与归档。</p>',
    )
    return HTMLResponse(html)


def register_html():
    html = (STATIC / "register.html").read_text(encoding="utf-8")
    if db.get_appearance_mode() != "simple":
        return HTMLResponse(html)
    html = html.replace(
        '<body class="welcome-page">',
        '<body class="welcome-page simple-appearance">',
    )
    html = html.replace(
        '<h1 id="registerTitle">电力分析能力评测数据采集与标注系统</h1>',
        '<h1 id="registerTitle">评测数据采集与标注</h1>',
    )
    html = html.replace(
        '<p id="registerSubtitle">注册账户后进入数据采集与标注工作台。</p>',
        '<p id="registerSubtitle" hidden>注册账户后进入数据采集与标注工作台。</p>',
    )
    return HTMLResponse(html)


def set_sid_cookie(response: Response, sid):
    response.set_cookie("sid", sid, httponly=True, samesite="lax", path="/")


def clear_sid_cookie(response: Response):
    response.delete_cookie("sid", path="/")


@app.get("/")
def welcome(request: Request):
    if current_user(request):
        return RedirectResponse("/app", status_code=302)
    return welcome_html()


@app.get("/app")
def processing_page(request: Request):
    require_user(request)
    return html_file("app.html")


@app.get("/register")
def register_page():
    return register_html()


@app.get("/manage")
def manage_page(request: Request):
    require_admin(request)
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


@app.post("/api/reset-cache")
def reset_cache(request: Request):
    user = require_user(request)
    job_ids = reset_user_cache(user["username"])
    return {"ok": True, "cleared_jobs": job_ids}


@app.get("/api/me")
def api_me(request: Request):
    config = db.get_model_config()
    return {
        "user": current_user(request),
        "version": APP_VERSION,
        "appearance": db.get_appearance_mode(),
        "model_configured": bool(config.get("url") and config.get("model_name") and config.get("api_key")),
    }


@app.get("/api/appearance")
def api_appearance():
    return {"appearance": db.get_appearance_mode(), "version": APP_VERSION}


@app.get("/api/default-config")
def default_config(request: Request):
    require_admin(request)
    config = db.get_model_config()
    return {
        "url": config["url"],
        "model_name": config["model_name"],
        "api_key_configured": bool(config.get("api_key")),
    }


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
    data_source = str(form.get("data_source") or "")
    config = db.get_model_config()
    config = {
        "url": str(config.get("url") or legacy.DEFAULT_URL).strip(),
        "model_name": str(config.get("model_name") or legacy.DEFAULT_MODEL).strip(),
        "api_key": str(config.get("api_key") or "").strip(),
    }
    if not config["api_key"]:
        return JSONResponse({"error": "管理员尚未配置多模态大模型 API Key"}, status_code=400)
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
    payload = job_payload(job_id)
    if not payload:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return payload


@app.get("/api/current-job")
def current_job(request: Request):
    user = require_user(request)
    for job in db.list_recent_jobs_for_owner(user["username"]):
        if is_final_completed(job["job_id"]):
            continue
        payload = job_payload(job["job_id"])
        if payload:
            payload["restored"] = True
            return payload
    return JSONResponse({"error": "暂无可恢复任务"}, status_code=404)


@app.get("/api/latest-result")
def latest_result(request: Request):
    user = require_user(request)
    for job in db.list_recent_jobs_for_owner(user["username"]):
        if is_final_completed(job["job_id"]):
            continue
        payload = job_payload(job["job_id"])
        if payload and payload.get("status") == "completed":
            return payload
    return JSONResponse({"error": "暂无已完成任务"}, status_code=404)


@app.get("/api/admin/stats")
def admin_stats(request: Request):
    require_admin(request)
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
    roles = {item["username"]: item["role"] for item in db.list_users()}
    users = []
    for item in stats.values():
        item["role"] = roles.get(item["username"], "user")
        users.append(item)
    return {"users": users}


@app.post("/api/admin/users/role")
async def update_user_role(request: Request, payload: dict):
    require_admin(request)
    username = str(payload.get("username", "")).strip()
    role = str(payload.get("role", "")).strip()
    if username == "admin":
        return JSONResponse({"error": "内置 admin 账户权限不可修改"}, status_code=400)
    if role not in {"admin", "user"}:
        return JSONResponse({"error": "权限值无效"}, status_code=400)
    db.update_user_role(username, role)
    return {"ok": True}


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
    require_admin(request)
    config = db.get_model_config()
    return {
        "register_code": db.get_register_code(),
        "appearance": db.get_appearance_mode(),
        "model_url": config["url"],
        "model_name": config["model_name"],
        "model_api_key_configured": bool(config.get("api_key")),
        "sample_dataset_path": str(sample_dataset_root()),
    }


@app.post("/api/admin/settings")
async def update_admin_settings(request: Request, payload: dict):
    require_admin(request)
    register_code = str(payload.get("register_code", db.get_register_code())).strip()
    appearance = str(payload.get("appearance", db.get_appearance_mode())).strip()
    model_url = payload.get("model_url")
    model_name = payload.get("model_name")
    model_api_key = str(payload.get("model_api_key", "")).strip() if "model_api_key" in payload else None
    sample_path = str(payload.get("sample_dataset_path", "")).strip() if "sample_dataset_path" in payload else ""
    if not register_code:
        return JSONResponse({"error": "注册码不能为空"}, status_code=400)
    if appearance not in {"standard", "simple"}:
        return JSONResponse({"error": "外观配置无效"}, status_code=400)
    if model_url is not None and not str(model_url).strip():
        return JSONResponse({"error": "模型 URL 不能为空"}, status_code=400)
    if model_name is not None and not str(model_name).strip():
        return JSONResponse({"error": "模型名称不能为空"}, status_code=400)
    db.set_register_code(register_code)
    db.set_appearance_mode(appearance)
    if model_url is not None or model_name is not None or model_api_key:
        db.set_model_config(
            url=str(model_url).strip() if model_url is not None else None,
            model_name=str(model_name).strip() if model_name is not None else None,
            api_key=model_api_key if model_api_key else None,
        )
    if sample_path:
        try:
            move_sample_dataset(sample_path)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    config = db.get_model_config()
    return {
        "ok": True,
        "register_code": db.get_register_code(),
        "appearance": db.get_appearance_mode(),
        "model_url": config["url"],
        "model_name": config["model_name"],
        "model_api_key_configured": bool(config.get("api_key")),
        "sample_dataset_path": str(sample_dataset_root()),
    }


@app.get("/api/admin/suggestions")
def admin_suggestions(request: Request):
    require_admin(request)
    return {"suggestions": db.list_suggestions()}


@app.get("/api/admin/final-items")
def admin_final_items(request: Request):
    require_admin(request)
    items = db.list_final_jobs("pending")
    for item in items:
        item["chapters"] = sorted(item.get("chapters", []), key=legacy.question_sort_key)
        item["qids"] = sorted(item.get("qids", []), key=legacy.question_sort_key)
    return {"items": items}


@app.get("/api/admin/sample-status")
def admin_sample_status(request: Request):
    require_admin(request)
    return {"items": sample_dataset_status()}


@app.get("/api/admin/sample-sources/{source}/samples")
def admin_sample_list(source: str, request: Request):
    require_admin(request)
    source_dir = sample_source_dir(source)
    rows = sync_sample_info(source_dir)
    items = []
    for index, row in enumerate(rows, start=1):
        sample_id = row.get("样本编号", "")
        record = sample_record(source, sample_id)
        if not record:
            continue
        items.append(
            {
                "index": index,
                "data_source": row.get("数据来源", source_dir.name),
                "sample_id": sample_id,
                "username": row.get("创建用户", ""),
                "created_at": row.get("创建时间", ""),
                "status": row.get("状态", "未审核"),
                "remark": row.get("备注", ""),
                "question": record.get("question", ""),
                "answer": record.get("answer", ""),
                "figures": record.get("figures", []),
            }
        )
    return {"source": source_dir.name, "items": items, "info_download_url": f"/api/admin/sample-sources/{quote(source_dir.name)}/info"}


@app.get("/api/admin/sample-sources/{source}/info")
def admin_sample_info_download(source: str, request: Request):
    require_admin(request)
    source_dir = sample_source_dir(source)
    rows = sync_sample_info(source_dir)
    if not rows:
        raise HTTPException(status_code=404, detail="样本信息表不存在")
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=SAMPLE_INFO_FIELDS)
    writer.writeheader()
    for row in rows:
        item = {field: str(row.get(field, "")) for field in SAMPLE_INFO_FIELDS}
        item["样本编号"] = f'="{item["样本编号"]}"'
        writer.writerow(item)
    filename = f"{source_dir.name}.csv"
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/admin/sample-sources/{source}/download")
def admin_sample_source_download(source: str, request: Request):
    require_admin(request)
    source_dir = sample_source_dir(source)
    rows = [row for row in read_sample_info(source_dir) if row.get("状态") == "已审核"]
    zip_path = source_dir / f"{source_dir.name}_已审核样本.zip"
    if zip_path.exists():
        zip_path.unlink()
    with legacy.zipfile.ZipFile(zip_path, "w", compression=legacy.zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            sample_dir = source_dir / safe_folder_name(row.get("样本编号", ""))
            if not sample_dir.exists():
                continue
            for path in sample_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(source_dir.parent))
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


@app.get("/api/admin/sample-sources/{source}/samples/{sample_id}/download")
def admin_sample_download(source: str, sample_id: str, request: Request):
    require_admin(request)
    source_dir = sample_source_dir(source)
    sample_dir = (source_dir / safe_folder_name(sample_id)).resolve()
    try:
        sample_dir.relative_to(source_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="样本不存在")
    if not sample_dir.exists() or not sample_dir.is_dir():
        raise HTTPException(status_code=404, detail="样本不存在")
    buffer = io.BytesIO()
    with legacy.zipfile.ZipFile(buffer, "w", compression=legacy.zipfile.ZIP_DEFLATED) as zf:
        for path in sample_dir.rglob("*"):
            if path.is_file():
                arcname = "/".join([source_dir.name, sample_dir.name, *path.relative_to(sample_dir).parts])
                zf.write(path, arcname)
    buffer.seek(0)
    filename = f"{sample_dir.name}.zip"
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/admin/sample-sources/{source}/samples/{sample_id}")
def admin_sample_detail(source: str, sample_id: str, request: Request):
    require_admin(request)
    record = sample_record(source, sample_id)
    if not record:
        return JSONResponse({"error": "样本不存在"}, status_code=404)
    return record


@app.post("/api/admin/sample-sources/{source}/samples/{sample_id}/save")
async def admin_sample_save(source: str, sample_id: str, request: Request):
    require_admin(request)
    source_dir = sample_source_dir(source)
    sample_dir = source_dir / safe_folder_name(sample_id)
    if not sample_dir.exists():
        return JSONResponse({"error": "样本不存在"}, status_code=404)
    record = sample_record(source, sample_id)
    if not record:
        return JSONResponse({"error": "样本不存在"}, status_code=404)
    if record.get("info", {}).get("状态") == "已审核":
        return JSONResponse({"error": "已审核样本不能继续修改"}, status_code=400)
    form = await request.form()
    payload_text = str(form.get("payload", "{}"))
    try:
        payload = json.loads(payload_text)
    except Exception:
        return JSONResponse({"error": "保存内容格式错误"}, status_code=400)
    item = {
        "type": payload.get("type", record.get("type", "")),
        "difficulty": payload.get("difficulty", record.get("difficulty", "")),
        "question": payload.get("question", record.get("question", "")),
        "answer": payload.get("answer", record.get("answer", "")),
        "solution": payload.get("solution", "解答过程暂略"),
        "source": payload.get("source", record.get("source", source_dir.name)),
    }
    (sample_dir / "data.md").write_text(sample_data_markdown(item), encoding="utf-8")
    saved_figures = []
    for key, value in form.multi_items():
        if key != "figure" or not getattr(value, "filename", None) or not getattr(value, "file", None):
            continue
        filename = legacy.safe_output_image_name(sample_dir.name, len(saved_figures), "figure", value.filename)
        with (sample_dir / filename).open("wb") as f:
            shutil.copyfileobj(value.file, f)
        saved_figures.append(filename)
    return {"ok": True, "figures": [path.name for path in sorted(sample_dir.glob('*.jpg'))]}


@app.post("/api/admin/sample-sources/{source}/samples/{sample_id}/status")
async def admin_sample_set_status(source: str, sample_id: str, request: Request, payload: dict):
    require_admin(request)
    status = str(payload.get("status", "")).strip()
    if status not in {"未审核", "已审核", "已放弃"}:
        return JSONResponse({"error": "状态无效"}, status_code=400)
    remark = str(payload.get("remark", "")).strip() if "remark" in payload else None
    record = sample_record(source, sample_id)
    if record and record.get("info", {}).get("状态") == "已审核" and status != "已审核":
        return JSONResponse({"error": "已审核样本不能继续修改"}, status_code=400)
    if not update_sample_status(source, safe_folder_name(sample_id), status, remark):
        return JSONResponse({"error": "样本不存在"}, status_code=404)
    return {"ok": True}


@app.get("/sample-asset/{source}/{sample_id}/{filename}")
def sample_asset(source: str, sample_id: str, filename: str, request: Request):
    require_admin(request)
    sample_dir = (sample_source_dir(source) / safe_folder_name(sample_id)).resolve()
    target = (sample_dir / safe_folder_name(filename)).resolve()
    try:
        target.relative_to(sample_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="非法路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, media_type=mimetypes.guess_type(str(target))[0] or "application/octet-stream")


@app.post("/api/admin/final-jobs/{job_id}/update")
async def admin_update_final_job(job_id: str, request: Request, payload: dict):
    require_admin(request)
    items = db.list_final_items_by_job(job_id, "pending")
    if not items:
        return JSONResponse({"error": "数据不存在或已处理"}, status_code=404)
    first = items[0]
    data_source = str(payload.get("data_source", first["data_source"])).strip() or "数据来源"
    chapter = str(payload.get("chapter", first["chapter"])).strip()
    username = str(payload.get("username", first["username"])).strip()
    if not chapter or not username:
        return JSONResponse({"error": "题目章节、账户名不能为空"}, status_code=400)
    db.update_final_job(job_id, data_source, chapter, username)
    return {"ok": True}


@app.post("/api/admin/final-jobs/{job_id}/discard")
def admin_discard_final_job(job_id: str, request: Request):
    require_admin(request)
    items = db.list_final_items_by_job(job_id, "pending")
    if not items:
        return JSONResponse({"error": "数据不存在或已处理"}, status_code=404)
    db.mark_final_job(job_id, "discarded")
    cleanup_job_artifacts(job_id)
    return {"ok": True}


@app.post("/api/admin/final-jobs/{job_id}/save")
def admin_save_final_job(job_id: str, request: Request):
    require_admin(request)
    items = db.list_final_items_by_job(job_id, "pending")
    if not items:
        return JSONResponse({"error": "数据不存在或已处理"}, status_code=404)
    saved_root = ""
    for item in items:
        temp_dir = Path(item["temp_dir"])
        if not temp_dir.exists():
            continue
        target = sample_dataset_root() / safe_folder_name(item["data_source"]) / safe_folder_name(item["qid"])
        target.mkdir(parents=True, exist_ok=True)
        data_text = (temp_dir / "data.md").read_text(encoding="utf-8") if (temp_dir / "data.md").exists() else ""
        if data_text:
            (target / "data.md").write_text(replace_markdown_source(data_text, item["data_source"]), encoding="utf-8")
        for figure_path in temp_dir.glob("*.jpg"):
            shutil.copyfile(figure_path, target / figure_path.name)
        saved_root = str(target.parent)
    db.mark_final_job(job_id, "saved", saved_root)
    cleanup_job_artifacts(job_id)
    return {"ok": True}


@app.post("/api/admin/final-items/{item_id}/update")
async def admin_update_final_item(item_id: int, request: Request, payload: dict):
    require_admin(request)
    item = db.get_final_item(item_id)
    if not item or item.get("status") != "pending":
        return JSONResponse({"error": "数据不存在或已处理"}, status_code=404)
    data_source = str(payload.get("data_source", item["data_source"])).strip() or "数据来源"
    qid = str(payload.get("qid", item["qid"])).strip()
    username = str(payload.get("username", item["username"])).strip()
    generated_at = str(payload.get("generated_at", item["generated_at"])).strip()
    if not qid or not username or not generated_at:
        return JSONResponse({"error": "题目编号、账户名、生成时间不能为空"}, status_code=400)
    db.update_final_item(item_id, data_source, qid, username, generated_at)
    return {"ok": True}


@app.post("/api/admin/final-items/{item_id}/discard")
def admin_discard_final_item(item_id: int, request: Request):
    require_admin(request)
    item = db.get_final_item(item_id)
    if not item or item.get("status") != "pending":
        return JSONResponse({"error": "数据不存在或已处理"}, status_code=404)
    temp_dir = Path(item["temp_dir"])
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    db.mark_final_item(item_id, "discarded")
    return {"ok": True}


@app.post("/api/admin/final-items/{item_id}/save")
def admin_save_final_item(item_id: int, request: Request):
    require_admin(request)
    item = db.get_final_item(item_id)
    if not item or item.get("status") != "pending":
        return JSONResponse({"error": "数据不存在或已处理"}, status_code=404)
    temp_dir = Path(item["temp_dir"])
    if not temp_dir.exists():
        return JSONResponse({"error": "临时结果文件不存在"}, status_code=404)
    target = sample_dataset_root() / safe_folder_name(item["data_source"]) / safe_folder_name(item["chapter"]) / safe_folder_name(item["qid"])
    target.mkdir(parents=True, exist_ok=True)
    data_text = (temp_dir / "data.md").read_text(encoding="utf-8") if (temp_dir / "data.md").exists() else ""
    if data_text:
        (target / "data.md").write_text(replace_markdown_source(data_text, item["data_source"]), encoding="utf-8")
    for figure_path in temp_dir.glob("*.jpg"):
        shutil.copyfile(figure_path, target / figure_path.name)
    shutil.rmtree(temp_dir)
    db.mark_final_item(item_id, "saved", str(target))
    return {"ok": True}


@app.get("/download/{job_id}")
def download(job_id: str, request: Request):
    user = require_admin(request)
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
        result = legacy.save_result_edits(job_id, items, files_by_key, make_package=False)
        db.update_job_status(job_id, "completed", reviewed_count=len(items))
        return result
    except Exception as exc:
        RUNS.mkdir(exist_ok=True)
        with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] FastAPI SaveResult\n{traceback.format_exc()}\n")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/complete-review")
async def complete_review(request: Request, payload: dict):
    user = require_user(request)
    job_id = str(payload.get("job_id", "")).strip()
    if not job_id:
        return JSONResponse({"error": "缺少 job_id"}, status_code=400)
    if not can_access(user, job_id):
        return JSONResponse({"error": "无权访问该任务"}, status_code=403)
    try:
        create_final_records(job_id, user["username"])
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/make-review-zip")
async def make_review_zip_api(request: Request, payload: dict):
    user = require_admin(request)
    job_id = str(payload.get("job_id", "")).strip()
    if not job_id:
        return JSONResponse({"error": "缺少 job_id"}, status_code=400)
    if not can_access(user, job_id):
        return JSONResponse({"error": "无权访问该任务"}, status_code=403)
    try:
        make_review_zip(job_id)
        return {"ok": True, "download_url": f"/download/{job_id}"}
    except Exception as exc:
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
