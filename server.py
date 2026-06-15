#!/usr/bin/env python3
import base64
import cgi
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.parse import quote

import requests


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
RUNS = ROOT / "runs"
USERS_FILE = ROOT / "users.json"
OUTPUT_NAME = "电力分析能力测试集"
FIG_DIR_NAME = "题图"
ANSWER_DIR_NAME = "答案"
DEFAULT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-27b"
JOB_STATUS = {}
SESSIONS = {}
REGISTER_CODE = "225-m1"
_TOOL_CACHE = {}
QUESTION_PAGE_CONCURRENCY = max(1, int(os.environ.get("QUESTION_PAGE_CONCURRENCY", "2")))
FIGURE_CONCURRENCY = max(1, int(os.environ.get("FIGURE_CONCURRENCY", "3")))
ANSWER_PAGE_CONCURRENCY = max(1, int(os.environ.get("ANSWER_PAGE_CONCURRENCY", "2")))


def external_tool(name):
    env_key = f"{name.upper()}_BIN"
    cached = _TOOL_CACHE.get(name)
    if cached and Path(cached).exists():
        return cached
    configured = os.environ.get(env_key)
    candidates = []
    if configured:
        candidates.append(Path(configured))
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    exe_name = f"{name}.exe" if os.name == "nt" else name
    candidates.extend([ROOT / "tools" / "ffmpeg" / "bin" / exe_name, ROOT / "tools" / "ffmpeg" / exe_name])
    for candidate in candidates:
        if candidate.exists():
            resolved = str(candidate)
            _TOOL_CACHE[name] = resolved
            return resolved
    raise RuntimeError(
        f"未找到 {name} 可执行文件。Windows Server裸机部署请重新执行scripts\\windows\\install.ps1，"
        f"或将{env_key}指向{exe_name}的完整路径。"
    )


QUESTION_PROMPT = """你是电力系统考试题图片信息抽取助手。
请从图片中识别每一道题，提取题目编号、题干文字、选项、公式、题目类型、题目难度，并定位每道题包含的题图区域。

要求：
1. 公式必须转换为 LaTeX，内联公式用 \\(...\\)，独立公式用 $$...$$。
2. 题干和选项保持原始语义与顺序，选项按 A:、B:、C:、D: 形式输出。
3. 题目类型 type 必须从以下选项判断：单选题、多选题、判断题、填空题、简答题。题干要求在空格、横线或括号中填写结果时判断为“填空题”；没有明确选项、判断语句或填空位置的计算/问答题，一般判断为“简答题”。
4. 题目难度 difficulty 必须从以下选项判断：简单、中等、困难。根据计算步骤、公式复杂度、是否跨多个知识点判断。
5. 如果一道题没有题图，figures 返回空数组。
6. bbox 统一使用 0-1000 归一化坐标 [x1, y1, x2, y2]，左上角为 [0,0]，右下角为 [1000,1000]，不要返回图片实际像素坐标。
7. 只框选电路图、曲线图、波形图、相量图、示意图、表格等视觉题图，可以包含其紧邻的“图1.1”“题图 13-3”等图注；不要框选题干文字，也不要框选只出现“如图1.1所示”“如题图 13-3 所示”的文字行。
8. 图注格式可能是“图1.1”“图 1-1”“题图 13-3”，也可能因扫描模糊而无法辨认。不要要求图注与题号完全一致，应结合题干中的图号引用、题图在题干附近的位置和视觉内容判断归属。
9. 如果当前图片出现了带 caption 的独立题图，即使对应题干在上一页或下一页，也必须为该题图返回一个 questions 项：id 使用 caption 中的题号，question 可以为空字符串，figures 必须包含该题图 bbox；type 和 difficulty 可以为空。
10. 页面顶部的题图很可能属于上一页末尾题目，不能因为当前页没有完整题干而忽略。例如图片顶部出现“题图 13-8”“题图 13-9”，也必须返回 id 为 13-8、13-9 的题图项。
11. bbox 要贴紧题图边缘；如果同一行有多个题图，不要把相邻题图合在一个 bbox 中。对于模糊、低对比度、压缩失真的扫描图，应依据电路连线、元件符号、坐标轴、曲线、箭头、表格边框和标注文字的视觉连续性确定完整边界，不能只依赖文字识别。
12. questions 数组必须严格按照题目在当前页面中的阅读顺序返回。id 只用于保留原材料中的编号；系统最终会按提取顺序重新编号。
13. figures 中的 description 必须填写，至少说明可见图注、题图相对位置和题图类型，例如“题干下方，图注图1.1，含N1/N2模块和3Ω电阻的电路图”。图注看不清时明确写“图注模糊”，不要编造。
14. 当前图片可能是多个连续子文件中的一页。如果页面开头是上一页题目的续文，例如以“(1)”“（2）”或计算条件开头，不得把它识别成一道新题；将 continuation_of_previous 设为 true。页面中真正出现新题号时才创建新题。
15. 只返回 JSON，不要返回 Markdown、解释或多余文本。

JSON 格式：
{
  "questions": [
    {
      "id": "1",
      "type": "简答题",
      "difficulty": "中等",
      "question": "题干和选项完整文本",
      "continuation_of_previous": false,
      "figures": [
        {"bbox": [10, 20, 300, 400], "description": "可选的题图说明"}
      ]
    }
  ]
}
"""


ANSWER_PROMPT = """你是电力系统考试答案图片信息抽取助手。
请从图片中识别每一道题的编号，并把每道题对应的答案完整转写为文本和 LaTeX。

要求：
1. 题号可能是“13-1”“13-2”“1”“2”或按题型重新编号。每个题号后面的公式、文字、数值就是该题答案。
2. 必须按题号逐题返回，不能把相邻题目的答案合并到同一个 answer_text。
3. 公式必须尽量转换为 LaTeX，内联公式必须用 $...$，独立公式必须用 $$...$$。禁止输出没有 $ 定界符的裸 LaTeX 公式。
4. 若该题答案换行，例如 13-4、13-11，要把该题所有连续行完整转写到 answer_text。
5. answer_text 不要包含左侧题号；如果无法稳定排除题号，也必须保证答案内容完整。
6. 电工仪表符号必须按仪表字母和下标识别，不要把圈起来的仪表符号误写成圈号：
   - 圈内是 V₁、V₂、V₃ 或 V1、V2、V3 时，写成 \\(V_1\\)、\\(V_2\\)、\\(V_3\\)，不要写 \\textcircled{1}、①，也不要写 \\textcircled{V_1}。
   - 圈内是 A₁、A₂、A₃ 或 A1、A2、A3 时，写成 \\(A_1\\)、\\(A_2\\)、\\(A_3\\)。
   - 圈内是 W₁、W₂ 或 W1、W2 时，写成 \\(W_1\\)、\\(W_2\\)。
   - 例如答案图中“圈中 V₁=220V”应输出 \\(V_1=220\\text{V}\\)，不是 \\textcircled{1}=220\\text{V}。
7. 禁止在 answer_text 中使用 \\textcircled{...}。只有图片中确实是纯圈号 ①、②、③ 且不是电压表/电流表/功率表符号时，才可以使用 Unicode 字符 ①、②、③。
8. answers 数组必须严格按照答案在当前页面中的阅读顺序返回。即使题号缺失或不同题型重新从 1 编号，也不能跳过答案；无法识别题号时 id 返回空字符串。
9. 不要包含章节标题、页眉、页脚、空白边框或其他题目的答案。
10. 只返回 JSON，不要返回 Markdown、解释或多余文本。

JSON 格式：
{
  "answers": [
    {"id": "13-1", "answer_text": "完整答案内容，公式用 LaTeX 表达"}
  ]
}
"""


def safe_name(name):
    return f"{uuid.uuid4().hex}.jpg"


def json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json_body(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else "{}"
    return json.loads(raw or "{}")


def load_users():
    if not USERS_FILE.exists():
        users = {
            "admin": {
                "salt": "admin",
                "password_hash": hash_password("1qaz@WSX", "admin"),
                "role": "admin",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        }
        save_users(users)
        return users
    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    if "admin" not in users:
        users["admin"] = {
            "salt": "admin",
            "password_hash": hash_password("1qaz@WSX", "admin"),
            "role": "admin",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_users(users)
    return users


def save_users(users):
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def hash_password(password, salt):
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def verify_password(user, password):
    return hash_password(password, user.get("salt", "")) == user.get("password_hash", "")


def parse_cookies(header):
    cookies = {}
    for part in (header or "").split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            cookies[key] = value
    return cookies


def current_user(handler):
    sid = parse_cookies(handler.headers.get("Cookie")).get("sid", "")
    username = SESSIONS.get(sid)
    if not username:
        return None
    users = load_users()
    if username not in users:
        return None
    return {"username": username, "role": users[username].get("role", "user")}


def require_user(handler):
    user = current_user(handler)
    if not user:
        json_response(handler, {"error": "请先登录"}, status=401)
        return None
    return user


def set_session_cookie(handler, username):
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = username
    handler.send_header("Set-Cookie", f"sid={sid}; Path=/; HttpOnly; SameSite=Lax")


def clear_session_cookie(handler):
    sid = parse_cookies(handler.headers.get("Cookie")).get("sid", "")
    if sid:
        SESSIONS.pop(sid, None)
    handler.send_header("Set-Cookie", "sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")


def write_job_meta(job_id, owner):
    job_dir = RUNS / job_id
    meta_path = job_dir / "meta.json"
    data = {}
    if meta_path.exists():
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    data.update({"owner": owner, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_meta(job_id):
    meta_path = RUNS / job_id / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def can_access_job(user, job_id):
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return read_job_meta(job_id).get("owner") == user.get("username")


def user_stats():
    users = load_users()
    stats = {name: {"username": name, "collected": 0, "reviewed": 0} for name in users}
    for job_dir in RUNS.iterdir() if RUNS.exists() else []:
        if not job_dir.is_dir():
            continue
        meta = read_job_meta(job_dir.name)
        owner = meta.get("owner")
        if not owner:
            continue
        stats.setdefault(owner, {"username": owner, "collected": 0, "reviewed": 0})
        md_path = job_dir / OUTPUT_NAME / "test_data.md"
        count = count_markdown_questions(md_path)
        stats[owner]["collected"] += count
        stats[owner]["reviewed"] += int(meta.get("reviewed_count") or 0)
    return list(stats.values())


def serve_file(handler, path, download_name=None):
    if not path.exists() or not path.is_file():
        handler.send_error(404)
        return
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(path.stat().st_size))
    if download_name:
        handler.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{quote(download_name)}",
        )
    handler.end_headers()
    with path.open("rb") as f:
        shutil.copyfileobj(f, handler.wfile)


def serve_output_asset(handler, job_id, rel_path):
    base = (RUNS / job_id / OUTPUT_NAME).resolve()
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        handler.send_error(403)
        return
    serve_file(handler, target)


def image_to_data_url(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def call_vlm(config, image_path, prompt, add_pixel_hint=True):
    if add_pixel_hint:
        width, height = ffprobe_size(image_path)
        prompt = (
            f"当前上传图片尺寸：宽 {width} 像素，高 {height} 像素。\n"
            f"所有 bbox 坐标必须以这张 {width}x{height} 图片为准。\n\n"
            f"{prompt}"
        )
    base_url = config["url"].rstrip("/")
    endpoint = base_url
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"

    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["model_name"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_to_data_url(image_path)},
                    },
                ],
            }
        ],
        "temperature": 0,
        "enable_thinking": False,
        "response_format": {"type": "json_object"},
    }
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=180)
            if resp.status_code in (400, 422) and "response_format" in resp.text:
                payload.pop("response_format", None)
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=180)
            if resp.status_code in (400, 422) and "enable_thinking" in resp.text:
                payload.pop("enable_thinking", None)
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            break
        except requests.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else 0
            if (status < 500 and status != 429) or attempt == 2:
                raise
            retry_after = exc.response.headers.get("Retry-After", "") if exc.response is not None else ""
            try:
                delay = max(float(retry_after), 1.5 * (attempt + 1))
            except (TypeError, ValueError):
                delay = 1.5 * (attempt + 1)
            time.sleep(delay)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    else:
        raise last_exc or RuntimeError("模型接口请求失败")
    data = resp.json()
    message = data["choices"][0]["message"]
    content = message.get("content", "")
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
    if not str(content).strip():
        content = message.get("reasoning_content", "")
    if not str(content).strip():
        raise ValueError(f"模型返回内容为空：{image_path.name}")
    return str(content)


def parse_json_text(text):
    text = text.strip()
    if not text:
        raise ValueError("模型返回内容为空，无法解析 JSON")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", text, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def ffprobe_size(path):
    cmd = [
        external_tool("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True)
    stream = json.loads(out)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def compress_image(src_path, dest_path=None, max_bytes=500 * 1024):
    dest_path = dest_path or src_path
    work_path = dest_path.with_suffix(".compressing.jpg")
    width, height = ffprobe_size(src_path)
    max_src_side = max(width, height)
    side_options = [max_src_side, 2000, 1800, 1600, 1400, 1200, 1000, 800, 640]
    side_options = [s for i, s in enumerate(side_options) if s > 0 and s not in side_options[:i]]
    qualities = [4, 6, 8, 10, 12, 16, 20, 24, 28, 31]
    best_path = None
    best_size = None

    for side in side_options:
        side = min(side, max_src_side)
        scale = (
            f"scale='if(gt(iw,ih),min({side},iw),-2)':"
            f"'if(gt(iw,ih),-2,min({side},ih))'"
        )
        for quality in qualities:
            cmd = [
                external_tool("ffmpeg"),
                "-y",
                "-i",
                str(src_path),
                "-vf",
                scale,
                "-q:v",
                str(quality),
                str(work_path),
            ]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            size = work_path.stat().st_size
            if best_size is None or size > best_size:
                best_size = size
                best_path = work_path
            if size <= max_bytes:
                shutil.move(str(work_path), str(dest_path))
                return dest_path

    if best_path and best_path.exists():
        shutil.move(str(best_path), str(dest_path))
    if dest_path.stat().st_size > max_bytes:
        raise RuntimeError(f"图片压缩后仍超过 500K：{dest_path.name}")
    return dest_path


def normalize_bbox(bbox, width, height, ref_size=None):
    vals = coerce_bbox(bbox)
    if not vals:
        raise ValueError(f"无法解析 bbox：{bbox}")
    if max(vals) <= 1.5:
        vals = [vals[0] * width, vals[1] * height, vals[2] * width, vals[3] * height]
    elif ref_size:
        ref_w, ref_h = ref_size
        if ref_w and ref_h and (ref_w != width or ref_h != height):
            vals = [
                vals[0] * width / ref_w,
                vals[1] * height / ref_h,
                vals[2] * width / ref_w,
                vals[3] * height / ref_h,
            ]
    x1, y1, x2, y2 = vals
    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])
    x1 = max(0, min(width - 1, round(x1)))
    y1 = max(0, min(height - 1, round(y1)))
    x2 = max(x1 + 1, min(width, round(x2)))
    y2 = max(y1 + 1, min(height, round(y2)))
    return x1, y1, x2, y2


def coerce_bbox(bbox):
    if isinstance(bbox, str):
        text = bbox.strip()
        try:
            bbox = json.loads(text)
        except json.JSONDecodeError:
            keyed = {}
            for key, value in re.findall(r"(x1|y1|x2|y2|left|top|right|bottom|width|height)\s*[:=]\s*(-?\d+(?:\.\d+)?)", text, flags=re.I):
                keyed[key.lower()] = float(value)
            if all(k in keyed for k in ["x1", "y1", "x2", "y2"]):
                return [keyed["x1"], keyed["y1"], keyed["x2"], keyed["y2"]]
            if all(k in keyed for k in ["left", "top", "right", "bottom"]):
                return [keyed["left"], keyed["top"], keyed["right"], keyed["bottom"]]
            if all(k in keyed for k in ["left", "top", "width", "height"]):
                return [keyed["left"], keyed["top"], keyed["left"] + keyed["width"], keyed["top"] + keyed["height"]]
            nums = re.findall(r"-?\d+(?:\.\d+)?", text)
            return [float(x) for x in nums[:4]] if len(nums) >= 4 else None
    if isinstance(bbox, dict):
        for keys in [
            ["x1", "y1", "x2", "y2"],
            ["left", "top", "right", "bottom"],
            ["xmin", "ymin", "xmax", "ymax"],
        ]:
            if all(k in bbox for k in keys):
                return [float(bbox[k]) for k in keys]
        for keys in [["x", "y", "width", "height"], ["left", "top", "width", "height"]]:
            if all(k in bbox for k in keys):
                x, y, w, h = [float(bbox[k]) for k in keys]
                return [x, y, x + w, y + h]
        nested = first_value(bbox, ["bbox", "box", "坐标", "答案bbox", "文字内容bbox"], default=None)
        return coerce_bbox(nested) if nested is not None else None
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return [float(x) for x in bbox[:4]]
    return None


def crop_region(image_path, bbox, out_path, ref_size=None):
    width, height = ffprobe_size(image_path)
    x1, y1, x2, y2 = normalize_bbox(bbox, width, height, ref_size=ref_size)
    crop_w = x2 - x1
    crop_h = y2 - y1
    cmd = [
        external_tool("ffmpeg"),
        "-y",
        "-i",
        str(image_path),
        "-vf",
        f"crop={crop_w}:{crop_h}:{x1}:{y1}",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def crop_figure(image_path, bbox, out_path, ref_size=None):
    crop_region(image_path, bbox, out_path, ref_size=ref_size)


def answer_bbox_ref_size(image_path, bbox):
    vals = coerce_bbox(bbox)
    if not vals:
        return None
    width, height = ffprobe_size(image_path)
    if max(vals[0], vals[2]) > width or max(vals[1], vals[3]) > height:
        if max(vals) <= 1100:
            return (1000, 1000)
    return None


def select_figure_bbox(initial_bbox, refined_bbox):
    initial_values = coerce_bbox(initial_bbox)
    if not initial_values:
        return refined_bbox
    if not refined_bbox:
        return initial_values
    refined_values = coerce_bbox(refined_bbox)
    if not refined_values:
        return initial_values
    ix1, iy1, ix2, iy2 = initial_values
    rx1, ry1, rx2, ry2 = refined_values
    initial_area = max(1, (ix2 - ix1) * (iy2 - iy1))
    refined_area = max(1, (rx2 - rx1) * (ry2 - ry1))
    area_ratio = refined_area / initial_area
    initial_center = ((ix1 + ix2) / 2, (iy1 + iy2) / 2)
    refined_center = ((rx1 + rx2) / 2, (ry1 + ry2) / 2)
    center_delta = (
        ((initial_center[0] - refined_center[0]) ** 2 + (initial_center[1] - refined_center[1]) ** 2) ** 0.5
    )
    initial_diagonal = max(1, ((ix2 - ix1) ** 2 + (iy2 - iy1) ** 2) ** 0.5)
    if not 0.4 <= area_ratio <= 2.5 or center_delta > initial_diagonal:
        return initial_values
    return refined_values


def answer_response_ref_size(image_path, answers):
    width, height = ffprobe_size(image_path)
    for ans in answers:
        if not isinstance(ans, dict):
            continue
        regions = first_value(
            ans,
            ["regions", "answer_regions", "bboxes", "boxes", "答案区域", "答案bbox列表"],
            default=[],
        )
        if isinstance(regions, dict):
            regions = [regions]
        bbox = first_value(ans, ["bbox_2d", "bbox", "box", "text_bbox", "answer_bbox", "坐标", "答案bbox", "文字内容bbox"], default=None)
        candidates = ([bbox] if bbox else []) + (regions if isinstance(regions, list) else [])
        for candidate in candidates:
            candidate_bbox = (
                first_value(candidate, ["bbox_2d", "bbox", "box", "text_bbox", "answer_bbox", "坐标", "答案bbox", "文字内容bbox"], default=None)
                if isinstance(candidate, dict)
                else candidate
            )
            vals = coerce_bbox(candidate_bbox)
            if vals and (max(vals[0], vals[2]) > width or max(vals[1], vals[3]) > height) and max(vals) <= 1100:
                return (1000, 1000)
    return None


def expand_answer_bbox(bbox, x_pad_ratio=0.06, y_pad_ratio=0.12):
    vals = coerce_bbox(bbox)
    if not vals:
        return bbox
    x1, y1, x2, y2 = vals
    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])
    width = x2 - x1
    height = y2 - y1
    return [
        x1 - width * x_pad_ratio,
        y1 - height * y_pad_ratio,
        x2 + width * x_pad_ratio,
        y2 + height * y_pad_ratio,
    ]


def read_gray_pixels(image_path):
    width, height = ffprobe_size(image_path)
    raw = subprocess.check_output(
        [external_tool("ffmpeg"), "-v", "error", "-i", str(image_path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
    )
    return width, height, raw


def detect_text_line_groups(width, height, raw, threshold=210):
    min_count = max(4, int(width * 0.006))
    groups = []
    in_group = False
    gap = 0
    start = 0
    last = 0
    for y in range(height):
        row = raw[y * width : (y + 1) * width]
        dark_count = sum(1 for pixel in row if pixel < threshold)
        if dark_count >= min_count:
            if not in_group:
                start = y
                in_group = True
            gap = 0
            last = y
        elif in_group:
            gap += 1
            if gap >= 4:
                groups.append((start, last))
                in_group = False
    if in_group:
        groups.append((start, last))
    return groups


def count_dark_pixels(raw, width, y1, y2, x1, x2, threshold=210):
    count = 0
    for y in range(y1, y2 + 1):
        row = raw[y * width : (y + 1) * width]
        count += sum(1 for pixel in row[x1:x2] if pixel < threshold)
    return count


def text_bbox_in_band(width, height, raw, y1, y2, exclude_left=75, threshold=210):
    min_x = width
    max_x = -1
    min_y = height
    max_y = -1
    for y in range(max(0, y1), min(height, y2 + 1)):
        row = raw[y * width : (y + 1) * width]
        for x in range(max(0, exclude_left), width):
            if row[x] < threshold:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
    if max_x < 0:
        for y in range(max(0, y1), min(height, y2 + 1)):
            row = raw[y * width : (y + 1) * width]
            for x, pixel in enumerate(row):
                if pixel < threshold:
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
    if max_x < 0:
        return [0, y1, width, y2]
    return [
        max(0, min_x - 6),
        max(0, min_y - 4),
        min(width, max_x + 7),
        min(height, max_y + 5),
    ]


def answer_line_bboxes(image_path, answers):
    ordered = [ans for ans in answers if isinstance(ans, dict) and infer_answer_id(ans)]
    if not ordered:
        return {}
    width, height, raw = read_gray_pixels(image_path)
    groups = detect_text_line_groups(width, height, raw)
    qid_starts = []
    qid_column_width = min(width, 75)
    for index, (y1, y2) in enumerate(groups):
        if count_dark_pixels(raw, width, y1, y2, 0, qid_column_width) >= 20:
            qid_starts.append(index)
    if len(qid_starts) != len(ordered):
        return {}

    bboxes = {}
    for answer_index, group_index in enumerate(qid_starts):
        next_group_index = qid_starts[answer_index + 1] if answer_index + 1 < len(qid_starts) else len(groups)
        y1 = groups[group_index][0]
        y2 = groups[next_group_index - 1][1]
        qid = infer_answer_id(ordered[answer_index])
        bboxes[qid] = text_bbox_in_band(width, height, raw, y1, y2, exclude_left=qid_column_width)
    return bboxes


def question_sort_key(qid):
    text = str(qid)
    parts = re.split(r"(\d+)", text)
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        elif part:
            key.append((1, part))
    return key


def build_markdown(records):
    chunks = []
    for qid in sorted(records, key=question_sort_key):
        item = records[qid]
        fig_lines = "\n".join(item.get("figures", []))
        answer_lines = item.get("answer", "").strip()
        if not answer_lines:
            answer_lines = "\n".join(item.get("answers", []))
        chunks.append(
            "\n".join(
                [
                    "# 题目编号",
                    str(qid),
                    "## 题目类型",
                    item.get("type", "").strip(),
                    "## 题目难度",
                    item.get("difficulty", "").strip(),
                    "## 问题",
                    item.get("question", "").strip(),
                    "## 题图地址",
                    fig_lines,
                    "## 答案",
                    answer_lines,
                    "## 解答过程",
                    item.get("solution", "").strip(),
                    "## 题目来源",
                    item.get("source", "").strip(),
                ]
            )
        )
    return "\n\n".join(chunks).strip() + "\n"


def attach_referenced_figures(records):
    for qid, item in records.items():
        if item.get("figures"):
            continue
        question = item.get("question", "")
        referenced = []
        for ref in re.findall(r"题图\s*([0-9]+(?:[-－—][0-9]+)?)", question):
            ref_qid = ref.replace("－", "-").replace("—", "-")
            ref_item = records.get(ref_qid)
            if not ref_item:
                continue
            for figure in ref_item.get("figures", []):
                if figure not in referenced:
                    referenced.append(figure)
        if referenced:
            item["figures"] = referenced
    return records


def parse_markdown_records(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    records = {}
    blocks = re.split(r"\n(?=# 题目编号\n)", text.strip())
    for block in [b.strip() for b in blocks if b.strip()]:
        data = {}
        current = None
        for line in block.splitlines():
            match = re.match(r"^#{1,2}\s+(.+)$", line)
            if match:
                current = match.group(1).strip()
                data[current] = []
            elif current:
                data[current].append(line)
        qid = "\n".join(data.get("题目编号", [])).strip()
        if not qid:
            continue
        records[qid] = {
            "type": "\n".join(data.get("题目类型", [])).strip(),
            "difficulty": "\n".join(data.get("题目难度", [])).strip(),
            "question": "\n".join(data.get("问题", [])).strip(),
            "figures": [line.strip() for line in data.get("题图地址", []) if line.strip()],
            "answers": [line.strip() for line in data.get("答案", []) if line.strip()],
            "answer": "\n".join(data.get("答案", [])).strip(),
            "solution": "\n".join(data.get("解答过程", [])).strip(),
            "source": "\n".join(data.get("题目来源", [])).strip(),
        }
    return records


def extract_items(parsed, key):
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        value = parsed.get(key)
        if isinstance(value, list):
            return value
        for fallback in ["data", "items", "result", "results"]:
            nested = parsed.get(fallback)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict) and isinstance(nested.get(key), list):
                return nested[key]
    return []


def first_value(data, keys, default=""):
    if not isinstance(data, dict):
        return default
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return default


def infer_answer_id(ans):
    qid = str(first_value(ans, ["id", "number", "qid", "question_id", "题号", "编号", "题目编号"])).strip()
    if qid:
        return qid
    text = str(first_value(ans, ["answer", "answer_text", "content", "text", "text_content", "答案"], default=""))
    match = re.search(r"\b\d{1,3}\s*[-－—]\s*\d{1,3}\b", text)
    if match:
        return re.sub(r"\s+", "", match.group(0)).replace("－", "-").replace("—", "-")
    return ""


def normalize_extraction_id(value):
    text = str(value or "").strip().replace("－", "-").replace("—", "-")
    text = re.sub(r"^(?:第\s*)?", "", text)
    text = re.sub(r"\s*(?:题|[.、:：])$", "", text)
    return re.sub(r"\s+", "", text).lower()


def merge_question_text(current, addition):
    current = str(current or "").strip()
    addition = str(addition or "").strip()
    if not addition:
        return current
    if not current:
        return addition
    if addition in current:
        return current
    if current in addition:
        return addition
    return f"{current}\n{addition}"


def is_question_continuation(text):
    text = str(text or "").strip()
    return bool(
        re.match(r"^(?:[（(]\s*\d+\s*[)）]|[①②③④⑤⑥⑦⑧⑨⑩]|[A-DＡ-Ｄ][.、:：])", text)
    )


def question_expects_continuation(text):
    text = str(text or "").rstrip()
    return bool(re.search(r"(?:求|问|包括|如下|分别为|计算)[：:]?\s*$", text) or text.endswith(("：", ":")))


def consolidate_question_pages(page_items, logs):
    consolidated = []
    indexes_by_source = {}
    last_question_item = None

    for page_index, fragments in enumerate(page_items):
        for fragment_index, fragment in enumerate(fragments):
            source_id = str(fragment.get("_source_id", "")).strip()
            normalized_id = normalize_extraction_id(source_id)
            question_text = str(fragment.get("question", "")).strip()
            figures = list(fragment.get("_figure_candidates", []))

            is_cross_page_continuation = (
                fragment_index == 0
                and page_index > 0
                and question_text
                and last_question_item is not None
                and (
                    fragment.get("_continues_previous")
                    or (
                        is_question_continuation(question_text)
                        and question_expects_continuation(last_question_item.get("question", ""))
                    )
                )
            )
            if is_cross_page_continuation:
                last_question_item["question"] = merge_question_text(last_question_item.get("question"), question_text)
                append_log(
                    logs,
                    f"跨文件续文合并：第 {page_index + 1} 个问题文件开头内容并入原编号 "
                    f"{last_question_item.get('_source_id') or '未识别'}",
                )
                question_text = ""

            target = None
            if normalized_id and indexes_by_source.get(normalized_id):
                candidate = consolidated[indexes_by_source[normalized_id][-1]]
                if not question_text or not candidate.get("question") or is_cross_page_continuation:
                    target = candidate
                elif fragment.get("_page_index", page_index) > candidate.get("_page_index", page_index):
                    if question_expects_continuation(candidate.get("question", "")) or is_question_continuation(question_text):
                        target = candidate

            if target is None and (question_text or figures or source_id):
                target = {
                    "_source_id": source_id,
                    "_page_index": page_index,
                    "question": "",
                    "answer": "",
                    "figures": [],
                    "_figure_candidates": [],
                    "answers": [],
                    "source": fragment.get("source", ""),
                }
                consolidated.append(target)
                if normalized_id:
                    indexes_by_source.setdefault(normalized_id, []).append(len(consolidated) - 1)

            if target is None:
                continue
            if question_text:
                target["question"] = merge_question_text(target.get("question"), question_text)
                last_question_item = target
            for key in ["type", "difficulty"]:
                if fragment.get(key):
                    target[key] = fragment[key]
            target["_figure_candidates"].extend(figures)

    return [item for item in consolidated if item.get("question") or item.get("_figure_candidates")]


def attach_referenced_figures_in_order(items):
    figures_by_source = {}
    for item in items:
        source_id = normalize_extraction_id(item.get("_source_id", ""))
        if source_id and item.get("figures"):
            figures_by_source.setdefault(source_id, [])
            for figure in item["figures"]:
                if figure not in figures_by_source[source_id]:
                    figures_by_source[source_id].append(figure)

    for item in items:
        if item.get("figures"):
            continue
        referenced = []
        for ref in re.findall(r"题图\s*([0-9]+(?:[-－—][0-9]+)?)", item.get("question", "")):
            for figure in figures_by_source.get(normalize_extraction_id(ref), []):
                if figure not in referenced:
                    referenced.append(figure)
        if referenced:
            item["figures"] = referenced
    return items


def match_answers_in_order(question_items, answer_items, logs):
    answers_by_id = {}
    for index, answer in enumerate(answer_items):
        source_id = normalize_extraction_id(answer.get("_source_id", ""))
        if source_id:
            answers_by_id.setdefault(source_id, []).append(index)

    used = set()
    matched = 0
    for question in question_items:
        source_id = normalize_extraction_id(question.get("_source_id", ""))
        match_index = None
        if source_id:
            for candidate in answers_by_id.get(source_id, []):
                if candidate not in used:
                    match_index = candidate
                    break
        if match_index is not None:
            question["answer"] = answer_items[match_index]["answer"]
            used.add(match_index)
            matched += 1

    remaining_answers = [index for index in range(len(answer_items)) if index not in used]
    remaining_questions = [item for item in question_items if not item.get("answer", "").strip()]
    for question, answer_index in zip(remaining_questions, remaining_answers):
        question["answer"] = answer_items[answer_index]["answer"]
        used.add(answer_index)
        matched += 1

    append_log(
        logs,
        f"问题与答案匹配完成：问题 {len(question_items)} 道，答案 {len(answer_items)} 条，成功匹配 {matched} 条",
    )
    return question_items


def normalize_answer_text(text):
    text = str(text or "")
    text = re.sub(r"\\textcircled\{\s*([VAW])\s*[_\s-]*(\d+)\s*\}", r"\1_\2", text)
    text = re.sub(r"\\textcircled\{\s*\\?text\{\s*([VAW])\s*\}\s*[_\s-]*(\d+)\s*\}", r"\1_\2", text)
    text = text.replace(r"\(", "$").replace(r"\)", "$")
    text = text.replace(r"\[", "$$").replace(r"\]", "$$")

    normalized = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            stripped
            and "$" not in stripped
            and not re.search(r"[\u3400-\u9fff]", stripped)
            and (
                re.search(r"\\(?:frac|sqrt|dot|angle|Omega|varphi|Delta|text|cos|sin|tan|mu|pm|times)\b", stripped)
                or re.search(r"[A-Za-z0-9}\)]\s*=\s*[A-Za-z0-9\\{(]", stripped)
                or re.search(r"[A-Za-z]_\{?\S+", stripped)
            )
        ):
            leading = line[: len(line) - len(line.lstrip())]
            trailing = line[len(line.rstrip()) :]
            line = f"{leading}${stripped}${trailing}"
        normalized.append(line)
    return "\n".join(normalized)


def make_zip(output_dir):
    zip_path = output_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in output_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(output_dir.parent))
    return zip_path


def safe_folder_name(name):
    text = str(name or "").strip() or "未命名"
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")
    return text or "未命名"


def final_figure_name(figure_rel):
    stem = safe_folder_name(Path(str(figure_rel)).stem)
    return f"{stem}.png"


def safe_figure_component(value):
    text = safe_folder_name(value)
    text = re.sub(r"[\s()\[\]{}]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text or "数据来源"


def standardized_figure_name(source, qid, index=0):
    return f"{safe_figure_component(qid)}-fig{int(index) + 1}.png"


def convert_image_to_png(source, target):
    cmd = [
        external_tool("ffmpeg"),
        "-y",
        "-i",
        str(source),
        "-frames:v",
        "1",
        str(target),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return target


def question_with_figure_links(question, figures):
    figure_names = [final_figure_name(figure) for figure in figures if figure]
    if not question:
        return question
    lines = []
    for line in str(question).splitlines():
        if re.fullmatch(r"\s*!\[[^\]]*\]\([^)]+\)\s*", line):
            continue
        lines.append(re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", line))
    clean_question = "\n".join(lines).strip()
    if not figure_names:
        return clean_question

    labels = [
        f"{label}{ref}"
        for label, ref in re.findall(
            r"(?<!\[)(题图|图)\s*([0-9]+(?:[.\-－—][0-9]+)*)",
            clean_question,
        )
    ]
    indexes = [
        f"![{labels[index] if index < len(labels) else f'题图{index + 1}'}]({filename})"
        for index, filename in enumerate(figure_names)
    ]
    return f"{clean_question}\n" + "\n".join(indexes)


def question_markdown(item):
    question = question_with_figure_links(
        str(item.get("question", "")).strip(),
        item.get("figures", []),
    )
    return "\n".join(
        [
            "#（一）题目类型",
            str(item.get("type", "")).strip(),
            "#（二）题目难度",
            str(item.get("difficulty", "")).strip(),
            "#（三）问题",
            question,
            "#（四）答案",
            str(item.get("answer", "")).strip(),
            "#（五）解答过程",
            "解答过程暂略",
            "#（六）题目来源",
            str(item.get("source", "")).strip(),
            "",
        ]
    )


def make_final_package(job_id, records, source):
    job_dir = RUNS / job_id
    output_dir = job_dir / OUTPUT_NAME
    package_name = f"{safe_folder_name(source)}_{time.strftime('%Y%m%d-%H%M%S')}"
    package_dir = job_dir / package_name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    for qid in sorted(records, key=question_sort_key):
        item = records[qid]
        item_source = item.get("source", source)
        question_dir = package_dir / f"{safe_folder_name(item_source)}_{safe_folder_name(qid)}"
        question_dir.mkdir(parents=True, exist_ok=True)
        (question_dir / "data.md").write_text(question_markdown(item), encoding="utf-8")
        for figure_index, figure in enumerate([fig for fig in item.get("figures", []) if fig], start=1):
            source_path = (output_dir / figure).resolve()
            try:
                source_path.relative_to(output_dir.resolve())
            except ValueError:
                source_path = None
            if source_path and source_path.exists():
                convert_image_to_png(source_path, question_dir / final_figure_name(figure))

    zip_path = job_dir / f"{OUTPUT_NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in package_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(job_dir))
    return zip_path, package_dir


def safe_output_image_name(qid, index, field, filename, current_rel=""):
    if current_rel:
        current_name = Path(current_rel).name
        if current_name:
            return current_name
    safe_qid = safe_folder_name(qid)
    stem = f"{safe_qid}-fig{int(index) + 1}"
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or field
    return f"{stem}.png"


def save_uploaded_image(file_item, target):
    source_ext = Path(getattr(file_item, "filename", "") or "").suffix.lower()
    if source_ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        raise ValueError("不支持的题图文件格式")
    temp_path = target.with_name(f".{target.stem}-{uuid.uuid4().hex}{source_ext}")
    try:
        with temp_path.open("wb") as f:
            shutil.copyfileobj(file_item.file, f)
        if target.suffix.lower() in {".jpg", ".jpeg"}:
            compress_image(temp_path, target)
        elif target.suffix.lower() == ".png":
            cmd = [
                external_tool("ffmpeg"),
                "-y",
                "-i",
                str(temp_path),
                "-frames:v",
                "1",
                str(target),
            ]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            shutil.move(str(temp_path), str(target))
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def save_replacement_image(file_item, output_dir, folder, qid, index, field, current_rel=""):
    target_dir = output_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_output_image_name(qid, index, field, getattr(file_item, "filename", ""), current_rel=current_rel)
    target = (target_dir / filename).resolve()
    try:
        target.relative_to(target_dir.resolve())
    except ValueError:
        raise ValueError("非法图片文件名")

    if current_rel:
        old = (output_dir / current_rel).resolve()
        try:
            old.relative_to(output_dir.resolve())
        except ValueError:
            old = None
        if old and old.exists() and old != target:
            old.unlink()

    save_uploaded_image(file_item, target)
    return f"{folder}/{filename}"


def save_result_edits(job_id, items, files_by_key, make_package=True):
    job_dir = RUNS / job_id
    output_dir = job_dir / OUTPUT_NAME
    md_path = output_dir / "test_data.md"
    if not md_path.exists():
        raise FileNotFoundError("test_data.md 不存在")

    existing = parse_markdown_records(md_path.read_text(encoding="utf-8"))
    existing_figures = {
        str(figure).strip()
        for item in existing.values()
        for figure in item.get("figures", [])
        if str(figure).strip()
    }
    updated = {}
    for idx, item in enumerate(items):
        qid = str(item.get("id", "")).strip()
        if not qid:
            continue
        previous = existing.get(qid, {})
        figures = [str(x).strip() for x in item.get("figures", previous.get("figures", [])) if str(x).strip()]
        answer_text = normalize_answer_text(item.get("answer", previous.get("answer", ""))).strip()

        for key, file_item in files_by_key.items():
            parts = key.split(":")
            if len(parts) != 3:
                continue
            field, item_idx, image_idx = parts
            if item_idx != str(idx) or field != "figure":
                continue
            image_index = int(image_idx)
            current = figures[image_index] if field == "figure" and image_index < len(figures) else ""
            image_base = f"{item.get('source', previous.get('source', '数据来源'))}-{qid}"
            rel_path = save_replacement_image(
                file_item,
                output_dir,
                FIG_DIR_NAME,
                image_base,
                image_index,
                field,
                current_rel=current,
            )
            while len(figures) <= image_index:
                figures.append("")
            figures[image_index] = rel_path

        updated[qid] = {
            "type": str(item.get("type", previous.get("type", ""))).strip(),
            "difficulty": str(item.get("difficulty", previous.get("difficulty", ""))).strip(),
            "question": str(item.get("question", previous.get("question", ""))).strip(),
            "figures": [x for x in figures if x],
            "answers": [],
            "answer": answer_text,
            "solution": str(item.get("solution", previous.get("solution", ""))).strip(),
            "source": str(item.get("source", previous.get("source", ""))).strip(),
        }

    kept_figures = {
        str(figure).strip()
        for item in updated.values()
        for figure in item.get("figures", [])
        if str(figure).strip()
    }
    for rel_path in existing_figures - kept_figures:
        target = (output_dir / rel_path).resolve()
        try:
            target.relative_to(output_dir.resolve())
        except ValueError:
            continue
        if target.exists() and target.is_file():
            target.unlink()

    md_path.write_text(build_markdown(updated), encoding="utf-8")
    sources = [item.get("source", "").strip() for item in updated.values() if item.get("source", "").strip()]
    package_source = sources[0] if sources else "数据来源"
    zip_path = None
    package_dir = None
    if make_package:
        zip_path, package_dir = make_final_package(job_id, updated, package_source)
    status = job_status_payload(job_id)
    logs = status.get("logs", []) if status else []
    if make_package and package_dir:
        logs = logs + [f"{time.strftime('%H:%M:%S')} 人工校核保存完成，已生成 {package_dir.name}.zip"]
    else:
        logs = logs + [f"{time.strftime('%H:%M:%S')} 人工校核保存完成，尚未生成最终 zip"]
    write_process_log(job_dir, logs)
    meta = read_job_meta(job_id)
    meta["reviewed_count"] = len(updated)
    meta["owner"] = meta.get("owner", "")
    meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (job_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    JOB_STATUS[job_id] = {
        "job_id": job_id,
        "status": "completed",
        "question_count": len(updated),
        "figure_count": sum(len(v.get("figures", [])) for v in updated.values()),
        "answer_count": sum(1 for v in updated.values() if v.get("answer", "").strip()),
        "download_url": f"/download/{job_id}" if make_package else "",
        "markdown_url": f"/file/{job_id}/test_data.md",
        "result_url": f"/static/result.html?job_id={job_id}",
        "logs": logs,
    }
    return JOB_STATUS[job_id]


def append_log(logs, message):
    logs.append(f"{time.strftime('%H:%M:%S')} {message}")


def write_process_log(job_dir, logs):
    try:
        (job_dir / "process.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    except Exception:
        pass


class JobLogs(list):
    def __init__(self, job_id, job_dir):
        existing = []
        log_path = job_dir / "process.log"
        if log_path.exists():
            existing = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        super().__init__(existing)
        self.job_id = job_id
        self.job_dir = job_dir

    def append(self, item):
        super().append(item)
        write_process_log(self.job_dir, self)
        status = JOB_STATUS.setdefault(self.job_id, {"job_id": self.job_id})
        status["logs"] = list(self)


def write_model_output(job_dir, name, text):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    (job_dir / f"model-output-{safe}.txt").write_text(text, encoding="utf-8")


def latest_completed_job(user=None):
    if not RUNS.exists():
        return None
    candidates = []
    for job_dir in RUNS.iterdir():
        if not job_dir.is_dir():
            continue
        if user and not can_access_job(user, job_dir.name):
            continue
        output_dir = job_dir / OUTPUT_NAME
        md_path = output_dir / "test_data.md"
        zip_path = job_dir / f"{OUTPUT_NAME}.zip"
        if md_path.exists() and zip_path.exists():
            candidates.append((zip_path.stat().st_mtime, job_dir.name, output_dir))
    if not candidates:
        return None
    _, job_id, output_dir = max(candidates)
    return {
        "job_id": job_id,
        "question_count": count_markdown_questions(output_dir / "test_data.md"),
        "figure_count": len(list((output_dir / FIG_DIR_NAME).glob("*"))) if (output_dir / FIG_DIR_NAME).exists() else 0,
        "answer_count": count_markdown_answers(output_dir / "test_data.md"),
        "download_url": f"/download/{job_id}",
        "markdown_url": f"/file/{job_id}/test_data.md",
        "result_url": f"/static/result.html?job_id={job_id}",
        "logs": ["已恢复最新完成任务。"],
    }


def count_markdown_questions(md_path):
    if not md_path.exists():
        return 0
    text = md_path.read_text(encoding="utf-8")
    return len(re.findall(r"^# 题目编号$", text, flags=re.M))


def count_markdown_answers(md_path):
    if not md_path.exists():
        return 0
    records = parse_markdown_records(md_path.read_text(encoding="utf-8"))
    return sum(1 for item in records.values() if item.get("answer", "").strip())


def extract_bbox_value(data):
    if isinstance(data, list) and data:
        return extract_bbox_value(data[0])
    if isinstance(data, dict):
        for key in ["bbox_2d", "bbox", "box", "text_bbox", "answer_bbox", "坐标", "答案bbox", "文字内容bbox"]:
            value = data.get(key)
            if value is not None and value != "":
                return value
    return data


def expand_bbox(bbox, pad_ratio=0.08):
    vals = coerce_bbox(bbox)
    if not vals:
        return bbox
    x1, y1, x2, y2 = vals
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    pad_x = max(8, w * pad_ratio)
    pad_y = max(8, h * pad_ratio)
    return [x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y]


def expand_figure_bbox(bbox):
    vals = coerce_bbox(bbox)
    if not vals:
        return bbox
    x1, y1, x2, y2 = vals
    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])
    width = x2 - x1
    height = y2 - y1
    return [
        x1 - max(4, width * 0.03),
        y1 - max(4, height * 0.03),
        x2 + max(4, width * 0.03),
        y2 + max(8, height * 0.1),
    ]


def refine_figure_bbox(
    config,
    image_path,
    qid,
    question_text,
    description,
    initial_bbox,
    job_dir,
    logs,
    output_key=None,
):
    question_hint = re.sub(r"\s+", " ", str(question_text or "")).strip()[:500]
    description_hint = re.sub(r"\s+", " ", str(description or "")).strip()[:300]
    prompt = f"""你是题图 bbox 精确定位助手。
当前任务：只定位图片中 caption/图注 为“题图 {qid}”的那一个视觉题图区域。

严格要求：
1. bbox 使用 0-1000 坐标系返回，不要使用图片像素坐标。左上角为 [0,0]，右下角为 [1000,1000]。
2. bbox 必须覆盖完整视觉题图：电路图/曲线图/表格本体、所有连线、元件符号、箭头、节点标注、参数文字和图内说明。
3. 必须包含题图内部或紧邻题图的所有元件标注、节点标注和参数文字，例如 Z、Z_A、R=、j6Ω、220∠0°V、电动机 等；不能切掉任何一个字符或线条端点。
4. 下方“题图 {qid}”图注必须完整包含在 bbox 内。
5. 不要框选题干文字，也不要框选“如题图 {qid} 所示”或“计算题图 {qid}”这类文字行；bbox 顶边应在题图上方最近的空白处，不要延伸到上一段文字。
6. 如果同一行有多个题图，只返回“题图 {qid}”对应的单个题图；相邻题图的端子字母 A/B/C、线条、元件、箭头或图注都必须排除在 bbox 外。
   例如定位左侧题图时，右侧相邻题图开头的 A、B、C 端子字母不能进入 bbox；定位右侧题图时，左侧相邻题图的线条或元件不能进入 bbox。
7. bbox 要贴近题图边缘，四周只保留少量空白；宁可留少量空白，也不能切断线条、元件、标注文字或图注。
8. 只返回 JSON：{{"bbox_2d":[x1,y1,x2,y2]}}。
"""
    qid_pattern = re.escape(str(qid or "").strip()).replace(r"\-", r"[-－—\s]*")
    has_target_caption = bool(
        qid_pattern
        and re.search(rf"(?:题图|图)\s*{qid_pattern}", description_hint, flags=re.I)
    )
    if description_hint and not has_target_caption:
        prompt += f"\n图注模糊或与题号不一致时，辅助描述：{description_hint}"
    if question_hint and not has_target_caption:
        prompt += f"\n仍无法确定时，使用题干摘要辅助判断：{question_hint}"
    raw = call_vlm(config, image_path, prompt, add_pixel_hint=False)
    write_model_output(job_dir, output_key or f"refine-{qid}-{image_path.stem}", raw)
    parsed = parse_json_text(raw)
    bbox = extract_bbox_value(parsed)
    if not bbox:
        append_log(logs, f"题图二次定位失败：题号 {qid} 未返回 bbox")
        return None
    append_log(logs, f"题图二次定位返回：题号 {qid}，bbox_2d={bbox}")
    return bbox


def recognize_page(config, image_path, prompt, add_pixel_hint):
    started = time.perf_counter()
    raw = call_vlm(config, image_path, prompt, add_pixel_hint=add_pixel_hint)
    return raw, time.perf_counter() - started


def run_indexed_concurrently(items, max_workers, worker):
    if not items:
        return []
    results = [None] * len(items)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
        futures = {
            executor.submit(worker, index, item): index
            for index, item in enumerate(items)
        }
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    return results


def crop_consolidated_question_figures(config, question_items, data_source, fig_dir, job_dir, logs, timings):
    figure_tasks = []
    for item_index, rec in enumerate(question_items, start=1):
        display_id = str(item_index)
        for candidate_index, candidate in enumerate(rec.get("_figure_candidates", [])):
            figure_tasks.append(
                {
                    "rec": rec,
                    "display_id": display_id,
                    "candidate_index": candidate_index,
                    "candidate": candidate,
                    "figure_label": rec.get("_source_id") or display_id,
                }
            )

    def locate_figure(_, task):
        local_logs = []
        candidate = task["candidate"]
        refined_bbox = None
        error = None
        try:
            refined_bbox = refine_figure_bbox(
                config,
                candidate["image_path"],
                task["figure_label"],
                task["rec"].get("question", ""),
                candidate.get("description", ""),
                candidate["bbox"],
                job_dir,
                local_logs,
                output_key=(
                    f"refine-{task['figure_label']}-{task['display_id']}-"
                    f"{task['candidate_index'] + 1}-{candidate['image_path'].stem}"
                ),
            )
        except Exception as exc:
            error = str(exc)
        return refined_bbox, local_logs, error

    stage_started = time.perf_counter()
    located = run_indexed_concurrently(figure_tasks, FIGURE_CONCURRENCY, locate_figure)
    timings["figure_refinement"] += time.perf_counter() - stage_started

    for task, result in zip(figure_tasks, located):
        refined_bbox, local_logs, error = result
        for message in local_logs:
            logs.append(message)
        rec = task["rec"]
        display_id = task["display_id"]
        candidate = task["candidate"]
        image_path = candidate["image_path"]
        bbox = candidate["bbox"]
        if error:
            append_log(logs, f"题图二次定位异常：题目 {display_id}，错误={error}")
        out_name = standardized_figure_name(data_source, display_id, len(rec["figures"]))
        out_path = fig_dir / out_name
        try:
            selected_bbox = select_figure_bbox(bbox, refined_bbox)
            crop_region(
                image_path,
                expand_figure_bbox(selected_bbox),
                out_path,
                ref_size=(1000, 1000),
            )
            rec["figures"].append(f"{FIG_DIR_NAME}/{out_name}")
            append_log(logs, f"题图裁剪成功：{FIG_DIR_NAME}/{out_name}，0-1000 bbox={selected_bbox}")
        except Exception as exc:
            append_log(logs, f"题图裁剪失败：题目 {display_id}，bbox={refined_bbox or bbox}，错误={exc}")


def process_job(config, question_files=None, answer_files=None, job_id=None, saved_questions=None, saved_answers=None, data_source=""):
    job_id = job_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job_dir = RUNS / job_id
    upload_dir = job_dir / "uploads"
    output_dir = job_dir / OUTPUT_NAME
    fig_dir = output_dir / FIG_DIR_NAME
    answer_dir = output_dir / ANSWER_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)
    answer_dir.mkdir(parents=True, exist_ok=True)

    question_pages = []
    question_items = []
    answer_items = []
    logs = JobLogs(job_id, job_dir)

    saved_questions = saved_questions if saved_questions is not None else save_uploads(question_files or [], upload_dir / "questions")
    saved_answers = saved_answers if saved_answers is not None else save_uploads(answer_files or [], upload_dir / "answers")

    try:
        total_started = time.perf_counter()
        timings = {
            "question_recognition": 0.0,
            "figure_refinement": 0.0,
            "answer_recognition": 0.0,
        }
        append_log(logs, "开始处理任务")
        append_log(
            logs,
            f"并发配置：问题识别 {QUESTION_PAGE_CONCURRENCY}，"
            f"题图定位 {FIGURE_CONCURRENCY}，答案识别 {ANSWER_PAGE_CONCURRENCY}",
        )
        for image_path in saved_questions:
            append_log(logs, f"提交问题识别：{image_path.name}")
        stage_started = time.perf_counter()
        question_results = run_indexed_concurrently(
            saved_questions,
            QUESTION_PAGE_CONCURRENCY,
            lambda _, image_path: recognize_page(
                config,
                image_path,
                QUESTION_PROMPT,
                add_pixel_hint=False,
            ),
        )
        timings["question_recognition"] += time.perf_counter() - stage_started

        for page_index, (image_path, result) in enumerate(zip(saved_questions, question_results)):
            raw, request_elapsed = result
            write_model_output(job_dir, f"question-{image_path.stem}", raw)
            append_log(logs, f"问题图片模型返回：{image_path.name}，请求耗时 {request_elapsed:.1f} 秒")
            parsed = parse_json_text(raw)
            page_fragments = []
            for q in extract_items(parsed, "questions"):
                if not isinstance(q, dict):
                    continue
                source_id = str(first_value(q, ["id", "number", "qid", "question_id", "题号", "编号", "题目编号"])).strip()
                question_text = str(first_value(q, ["question", "content", "text", "stem", "题目", "问题"])).strip()
                figures = first_value(q, ["figures", "images", "diagrams", "bboxes", "题图"], default=[])
                if isinstance(figures, dict):
                    figures = [figures]
                if not source_id and not question_text and not figures:
                    continue

                continuation_value = first_value(
                    q,
                    ["continuation_of_previous", "continues_previous", "is_continuation", "承接上一页"],
                    default=False,
                )
                rec = {
                    "_source_id": source_id,
                    "_page_index": page_index,
                    "_continues_previous": continuation_value is True
                    or str(continuation_value).strip().lower() in {"true", "1", "yes", "是"},
                    "question": question_text,
                    "answer": "",
                    "figures": [],
                    "_figure_candidates": [],
                    "answers": [],
                    "source": data_source,
                }
                q_type = str(first_value(q, ["type", "question_type", "题目类型"], default="")).strip()
                q_difficulty = str(first_value(q, ["difficulty", "level", "题目难度", "难度"], default="")).strip()
                if q_type:
                    rec["type"] = q_type
                if q_difficulty:
                    rec["difficulty"] = q_difficulty
                for idx, fig in enumerate(figures if isinstance(figures, list) else [], start=1):
                    bbox = first_value(fig, ["bbox_2d", "bbox", "box", "坐标"], default=None) if isinstance(fig, dict) else fig
                    if not bbox:
                        continue
                    description = first_value(
                        fig,
                        ["description", "caption", "label", "图注", "说明"],
                        default="",
                    ) if isinstance(fig, dict) else ""
                    rec["_figure_candidates"].append(
                        {
                            "image_path": image_path,
                            "bbox": bbox,
                            "description": str(description or "").strip(),
                        }
                    )
                page_fragments.append(rec)
            question_pages.append(page_fragments)
            append_log(logs, f"问题子文件识别完成：{image_path.name}，识别片段 {len(page_fragments)} 个")

        question_items = consolidate_question_pages(question_pages, logs)
        append_log(logs, f"全部问题子文件合并完成：形成完整题目 {len(question_items)} 道")
        crop_consolidated_question_figures(
            config,
            question_items,
            data_source,
            fig_dir,
            job_dir,
            logs,
            timings,
        )

        for image_path in saved_answers:
            append_log(logs, f"提交答案识别：{image_path.name}")
        stage_started = time.perf_counter()
        answer_results = run_indexed_concurrently(
            saved_answers,
            ANSWER_PAGE_CONCURRENCY,
            lambda _, image_path: recognize_page(
                config,
                image_path,
                ANSWER_PROMPT,
                add_pixel_hint=True,
            ),
        )
        timings["answer_recognition"] += time.perf_counter() - stage_started

        for image_path, result in zip(saved_answers, answer_results):
            raw, request_elapsed = result
            write_model_output(job_dir, f"answer-{image_path.stem}", raw)
            append_log(logs, f"答案图片模型返回：{image_path.name}，请求耗时 {request_elapsed:.1f} 秒")
            parsed = parse_json_text(raw)
            extracted_answers = extract_items(parsed, "answers")
            for ans in extracted_answers:
                if not isinstance(ans, dict):
                    continue
                answer_text = first_value(ans, ["answer", "answer_text", "content", "text", "text_content", "答案"])
                if answer_text:
                    source_id = infer_answer_id(ans)
                    answer_items.append(
                        {
                            "_source_id": source_id,
                            "answer": normalize_answer_text(answer_text).strip(),
                        }
                    )
                    append_log(logs, f"答案文本识别成功：顺序 {len(answer_items)}，原编号 {source_id or '未识别'}")

        attach_referenced_figures_in_order(question_items)
        match_answers_in_order(question_items, answer_items, logs)
        records = {}
        for index, item in enumerate(question_items, start=1):
            if data_source and not item.get("source"):
                item["source"] = data_source
            item.pop("_source_id", None)
            item.pop("_page_index", None)
            item.pop("_continues_previous", None)
            item.pop("_figure_candidates", None)
            records[str(index)] = item
        md_path = output_dir / "test_data.md"
        md_path.write_text(build_markdown(records), encoding="utf-8")
        append_log(logs, f"生成 Markdown：{md_path.relative_to(job_dir)}")
        total_elapsed = time.perf_counter() - total_started
        append_log(
            logs,
            "耗时统计："
            f"问题识别 {timings['question_recognition']:.1f} 秒，"
            f"题图定位 {timings['figure_refinement']:.1f} 秒，"
            f"答案识别 {timings['answer_recognition']:.1f} 秒，"
            f"任务总计 {total_elapsed:.1f} 秒",
        )
        append_log(logs, "模型处理完成，等待人工校核")
    except Exception as exc:
        append_log(logs, f"任务失败：{exc}")
        write_process_log(job_dir, logs)
        status = JOB_STATUS.setdefault(job_id, {"job_id": job_id})
        status.update({"status": "failed", "error": str(exc), "logs": list(logs)})
        raise
    write_process_log(job_dir, logs)
    result = {
        "job_id": job_id,
        "status": "completed",
        "question_count": len(records),
        "figure_count": sum(len(v.get("figures", [])) for v in records.values()),
        "answer_count": sum(1 for v in records.values() if v.get("answer", "").strip()),
        "download_url": f"/download/{job_id}",
        "markdown_url": f"/file/{job_id}/test_data.md",
        "result_url": f"/static/result.html?job_id={job_id}",
        "logs": logs,
    }
    JOB_STATUS[job_id] = {**result, "logs": list(logs)}
    return result


def save_uploads(file_items, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in file_items:
        filename = getattr(item, "filename", "") or "upload.jpg"
        extension = Path(filename).suffix.lower()
        if extension == ".pdf":
            path = dest_dir / f"{uuid.uuid4().hex}.pdf"
        elif extension in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
            path = dest_dir / safe_name(filename)
        else:
            raise ValueError(f"不支持的文件格式：{filename}")
        with path.open("wb") as f:
            data = item.file.read()
            f.write(data)
        if extension == ".pdf":
            saved.extend(render_pdf_pages(path, dpi=220))
        else:
            compress_image(path)
            saved.append(path)
    return saved


def render_pdf_pages(pdf_path, dpi=220):
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 处理依赖 PyMuPDF，请先安装 requirements.txt") from exc

    pages = []
    try:
        document = fitz.open(str(pdf_path))
    except Exception as exc:
        raise ValueError(f"无法打开 PDF 文件：{pdf_path.name}") from exc
    try:
        if document.page_count < 1:
            raise ValueError(f"PDF 文件没有可处理页面：{pdf_path.name}")
        scale = float(dpi) / 72.0
        matrix = fitz.Matrix(scale, scale)
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
            output_path = pdf_path.with_name(f"{pdf_path.stem}-page-{page_index + 1:04d}.jpg")
            pixmap.save(str(output_path))
            compress_image(output_path)
            pages.append(output_path)
    finally:
        document.close()
    return pages


def start_background_job(config, question_files, answer_files, data_source="", owner=""):
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job_dir = RUNS / job_id
    upload_dir = job_dir / "uploads"
    output_dir = job_dir / OUTPUT_NAME
    (output_dir / FIG_DIR_NAME).mkdir(parents=True, exist_ok=True)
    (output_dir / ANSWER_DIR_NAME).mkdir(parents=True, exist_ok=True)
    write_job_meta(job_id, owner)

    JOB_STATUS[job_id] = {
        "job_id": job_id,
        "status": "uploading",
        "logs": [f"{time.strftime('%H:%M:%S')} 正在保存并压缩上传图片"],
    }
    write_process_log(job_dir, JOB_STATUS[job_id]["logs"])
    saved_questions = save_uploads(question_files, upload_dir / "questions")
    saved_answers = save_uploads(answer_files, upload_dir / "answers")
    JOB_STATUS[job_id].update(
        {
            "status": "processing",
            "logs": JOB_STATUS[job_id]["logs"] + [f"{time.strftime('%H:%M:%S')} 上传完成，后台任务已启动"],
        }
    )
    write_process_log(job_dir, JOB_STATUS[job_id]["logs"])

    thread = threading.Thread(
        target=run_background_job,
        args=(config, job_id, saved_questions, saved_answers, data_source, owner),
        daemon=True,
    )
    thread.start()
    return job_id


def run_background_job(config, job_id, saved_questions, saved_answers, data_source="", owner=""):
    try:
        process_job(
            config,
            job_id=job_id,
            saved_questions=saved_questions,
            saved_answers=saved_answers,
            data_source=data_source,
        )
        if owner:
            write_job_meta(job_id, owner)
    except Exception as exc:
        RUNS.mkdir(exist_ok=True)
        with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Background job {job_id}\n{traceback.format_exc()}\n")
        status = JOB_STATUS.setdefault(job_id, {"job_id": job_id})
        status.update({"status": "failed", "error": str(exc)})


def job_status_payload(job_id):
    status = JOB_STATUS.get(job_id)
    job_dir = RUNS / job_id
    log_path = job_dir / "process.log"
    if status is None and not job_dir.exists():
        return None
    if status is None:
        status = {"job_id": job_id, "status": "completed" if (job_dir / f"{OUTPUT_NAME}.zip").exists() else "processing"}
    if log_path.exists():
        status["logs"] = log_path.read_text(encoding="utf-8").splitlines()
    if (job_dir / f"{OUTPUT_NAME}.zip").exists():
        output_dir = job_dir / OUTPUT_NAME
        status.update(
            {
                "status": "completed",
                "question_count": count_markdown_questions(output_dir / "test_data.md"),
                "figure_count": len(list((output_dir / FIG_DIR_NAME).glob("*"))) if (output_dir / FIG_DIR_NAME).exists() else 0,
                "answer_count": count_markdown_answers(output_dir / "test_data.md"),
                "download_url": f"/download/{job_id}",
                "markdown_url": f"/file/{job_id}/test_data.md",
                "result_url": f"/static/result.html?job_id={job_id}",
            }
        )
    return status


class Handler(BaseHTTPRequestHandler):
    server_version = "VLDataGen/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            if current_user(self):
                self.send_response(302)
                self.send_header("Location", "/app")
                self.end_headers()
                return
            serve_file(self, STATIC / "welcome.html")
            return
        if path == "/logout":
            self.send_response(302)
            clear_session_cookie(self)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if path == "/app":
            if not current_user(self):
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            serve_file(self, STATIC / "app.html")
            return
        if path == "/register":
            serve_file(self, STATIC / "register.html")
            return
        if path == "/manage":
            user = current_user(self)
            if not user:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if user.get("role") != "admin":
                self.send_error(403)
                return
            serve_file(self, STATIC / "manage.html")
            return
        if path.startswith("/static/"):
            serve_file(self, STATIC / path.removeprefix("/static/"))
            return
        if path.startswith("/download/"):
            user = current_user(self)
            job_id = path.split("/", 2)[2]
            if not can_access_job(user, job_id):
                self.send_error(403)
                return
            serve_file(
                self,
                RUNS / job_id / f"{OUTPUT_NAME}.zip",
                download_name=f"{OUTPUT_NAME}.zip",
            )
            return
        if path.startswith("/file/") and path.endswith("/test_data.md"):
            user = current_user(self)
            job_id = path.split("/")[2]
            if not can_access_job(user, job_id):
                self.send_error(403)
                return
            serve_file(self, RUNS / job_id / OUTPUT_NAME / "test_data.md")
            return
        if path.startswith("/asset/"):
            user = current_user(self)
            parts = path.split("/", 3)
            if len(parts) != 4:
                self.send_error(404)
                return
            job_id = parts[2]
            if not can_access_job(user, job_id):
                self.send_error(403)
                return
            rel_path = unquote(parts[3])
            serve_output_asset(self, job_id, rel_path)
            return
        if path == "/api/default-config":
            if not require_user(self):
                return
            json_response(
                self,
                {"url": DEFAULT_URL, "model_name": DEFAULT_MODEL, "api_key": ""},
            )
            return
        if path == "/api/latest-result":
            user = require_user(self)
            if not user:
                return
            latest = latest_completed_job(user)
            if latest:
                json_response(self, latest)
            else:
                json_response(self, {"error": "暂无已完成任务"}, status=404)
            return
        if path.startswith("/api/status/"):
            user = require_user(self)
            if not user:
                return
            job_id = path.split("/", 3)[3]
            if not can_access_job(user, job_id):
                json_response(self, {"error": "无权访问该任务"}, status=403)
                return
            payload = job_status_payload(job_id)
            if payload:
                json_response(self, payload)
            else:
                json_response(self, {"error": "任务不存在"}, status=404)
            return
        if path == "/api/me":
            user = current_user(self)
            json_response(self, {"user": user})
            return
        if path == "/api/admin/stats":
            user = require_user(self)
            if not user:
                return
            if user.get("role") != "admin":
                json_response(self, {"error": "需要管理员权限"}, status=403)
                return
            json_response(self, {"users": user_stats()})
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/register":
            self.handle_register()
            return
        if path == "/api/login":
            self.handle_login()
            return
        if path == "/login-form":
            self.handle_login_form()
            return
        if path == "/api/logout":
            self.send_response(200)
            clear_session_cookie(self)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            return
        if path == "/api/save-result":
            user = require_user(self)
            if not user:
                return
            self.handle_save_result()
            return
        if path != "/api/process":
            self.send_error(404)
            return

        try:
            user = require_user(self)
            if not user:
                return
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                },
            )
            config = {
                "url": (form.getfirst("url") or DEFAULT_URL).strip(),
                "model_name": (form.getfirst("model_name") or DEFAULT_MODEL).strip(),
                "api_key": (form.getfirst("api_key") or "").strip(),
            }
            data_source = (form.getfirst("data_source") or "").strip()
            if not config["api_key"]:
                json_response(self, {"error": "请填写 api_key"}, status=400)
                return
            question_files = form["question_images"] if "question_images" in form else []
            answer_files = form["answer_images"] if "answer_images" in form else []
            if not isinstance(question_files, list):
                question_files = [question_files]
            if not isinstance(answer_files, list):
                answer_files = [answer_files]
            question_files = [f for f in question_files if getattr(f, "filename", None)]
            answer_files = [f for f in answer_files if getattr(f, "filename", None)]
            if not question_files and not answer_files:
                json_response(self, {"error": "请至少上传一张图片"}, status=400)
                return
            job_id = start_background_job(config, question_files, answer_files, data_source=data_source, owner=user["username"])
            json_response(
                self,
                {
                    "job_id": job_id,
                    "status": "processing",
                    "status_url": f"/api/status/{job_id}",
                    "logs": JOB_STATUS[job_id]["logs"],
                },
                status=202,
            )
        except requests.HTTPError as exc:
            body = exc.response.text[:2000] if exc.response is not None else str(exc)
            with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] HTTPError\n{body}\n")
            json_response(self, {"error": f"模型接口请求失败：{body}"}, status=502)
        except Exception as exc:
            RUNS.mkdir(exist_ok=True)
            with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Exception\n{traceback.format_exc()}\n")
            json_response(self, {"error": str(exc)}, status=500)

    def handle_register(self):
        try:
            payload = read_json_body(self)
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", ""))
            repeat = str(payload.get("repeat", ""))
            code = str(payload.get("code", "")).strip()
            if not username or not password:
                json_response(self, {"error": "请填写用户名和密码"}, status=400)
                return
            if password != repeat:
                json_response(self, {"error": "两次密码不一致"}, status=400)
                return
            if code != REGISTER_CODE:
                json_response(self, {"error": "注册码错误"}, status=400)
                return
            users = load_users()
            if username in users:
                json_response(self, {"error": "用户名已存在"}, status=400)
                return
            salt = secrets.token_hex(12)
            users[username] = {
                "salt": salt,
                "password_hash": hash_password(password, salt),
                "role": "user",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_users(users)
            self.send_response(200)
            set_session_cookie(self, username)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "user": {"username": username, "role": "user"}}, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=500)

    def handle_login(self):
        try:
            payload = read_json_body(self)
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", ""))
            users = load_users()
            user = users.get(username)
            if not user or not verify_password(user, password):
                json_response(self, {"error": "用户名或密码错误"}, status=401)
                return
            self.send_response(200)
            set_session_cookie(self, username)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            body = {"ok": True, "user": {"username": username, "role": user.get("role", "user")}}
            self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=500)

    def handle_login_form(self):
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                },
            )
            username = (form.getfirst("username") or "").strip()
            password = form.getfirst("password") or ""
            users = load_users()
            user = users.get(username)
            if not user or not verify_password(user, password):
                self.send_response(302)
                self.send_header("Location", "/?error=login")
                self.end_headers()
                return
            self.send_response(302)
            set_session_cookie(self, username)
            self.send_header("Location", "/app")
            self.end_headers()
        except Exception:
            self.send_response(302)
            self.send_header("Location", "/?error=login")
            self.end_headers()

    def handle_save_result(self):
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                },
            )
            job_id = (form.getfirst("job_id") or "").strip()
            payload_text = form.getfirst("payload") or ""
            if not job_id:
                json_response(self, {"error": "缺少 job_id"}, status=400)
                return
            user = current_user(self)
            if not can_access_job(user, job_id):
                json_response(self, {"error": "无权访问该任务"}, status=403)
                return
            payload = json.loads(payload_text)
            items = payload.get("items", [])
            if not isinstance(items, list):
                json_response(self, {"error": "payload.items 必须是数组"}, status=400)
                return

            files_by_key = {}
            for key in form.keys():
                value = form[key]
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if getattr(item, "filename", None):
                        files_by_key[key] = item

            result = save_result_edits(job_id, items, files_by_key)
            json_response(self, result)
        except Exception as exc:
            RUNS.mkdir(exist_ok=True)
            with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
                f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] SaveResult\n{traceback.format_exc()}\n")
            json_response(self, {"error": str(exc)}, status=500)


def main():
    RUNS.mkdir(exist_ok=True)
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving on http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
