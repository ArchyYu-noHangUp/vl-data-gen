import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"
USERS_FILE = ROOT / "users.json"
REGISTER_CODE = "225-m1"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists users (
                username text primary key,
                salt text not null,
                password_hash text not null,
                role text not null default 'user',
                created_at text not null
            );
            create table if not exists sessions (
                sid text primary key,
                username text not null,
                created_at integer not null,
                expires_at integer not null
            );
            create table if not exists jobs (
                job_id text primary key,
                owner text not null,
                status text not null,
                reviewed_count integer not null default 0,
                created_at text not null,
                updated_at text not null
            );
            create table if not exists task_queue (
                id integer primary key autoincrement,
                job_id text not null,
                payload text not null,
                status text not null default 'pending',
                created_at integer not null,
                started_at integer,
                finished_at integer
            );
            create table if not exists settings (
                key text primary key,
                value text not null,
                updated_at text not null
            );
            create table if not exists suggestions (
                id integer primary key autoincrement,
                username text not null,
                content text not null,
                created_at text not null
            );
            """
        )
        conn.execute(
            "insert or ignore into settings(key, value, updated_at) values ('register_code', ?, ?)",
            (REGISTER_CODE, now_text()),
        )
    ensure_admin()
    migrate_users_json()


def hash_password(password, salt):
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def ensure_admin():
    with connect() as conn:
        row = conn.execute("select username from users where username = ?", ("admin",)).fetchone()
        if row:
            return
        conn.execute(
            "insert into users(username, salt, password_hash, role, created_at) values (?, ?, ?, ?, ?)",
            ("admin", "admin", hash_password("1qaz@WSX", "admin"), "admin", now_text()),
        )


def migrate_users_json():
    if not USERS_FILE.exists():
        return
    try:
        users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    with connect() as conn:
        for username, item in users.items():
            conn.execute(
                """
                insert or ignore into users(username, salt, password_hash, role, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    item.get("salt", ""),
                    item.get("password_hash", ""),
                    item.get("role", "user"),
                    item.get("created_at", now_text()),
                ),
            )


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def get_user(username):
    with connect() as conn:
        row = conn.execute("select * from users where username = ?", (username,)).fetchone()
    return dict(row) if row else None


def verify_user(username, password):
    user = get_user(username)
    if not user:
        return None
    if hash_password(password, user["salt"]) != user["password_hash"]:
        return None
    return {"username": user["username"], "role": user["role"]}


def create_user(username, password):
    salt = secrets.token_hex(12)
    with connect() as conn:
        conn.execute(
            "insert into users(username, salt, password_hash, role, created_at) values (?, ?, ?, ?, ?)",
            (username, salt, hash_password(password, salt), "user", now_text()),
        )
    return {"username": username, "role": "user"}


def get_setting(key, default=""):
    with connect() as conn:
        row = conn.execute("select value from settings where key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            """
            insert into settings(key, value, updated_at) values (?, ?, ?)
            on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now_text()),
        )


def get_register_code():
    return get_setting("register_code", REGISTER_CODE)


def set_register_code(value):
    set_setting("register_code", value)


def add_suggestion(username, content):
    with connect() as conn:
        conn.execute(
            "insert into suggestions(username, content, created_at) values (?, ?, ?)",
            (username, content, now_text()),
        )


def list_suggestions(limit=200):
    with connect() as conn:
        rows = conn.execute(
            "select id, username, content, created_at from suggestions order by id desc limit ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_session(username, ttl_seconds=60 * 60 * 24 * 7):
    sid = secrets.token_urlsafe(32)
    now = int(time.time())
    with connect() as conn:
        conn.execute(
            "insert into sessions(sid, username, created_at, expires_at) values (?, ?, ?, ?)",
            (sid, username, now, now + ttl_seconds),
        )
    return sid


def delete_session(sid):
    if not sid:
        return
    with connect() as conn:
        conn.execute("delete from sessions where sid = ?", (sid,))


def user_for_session(sid):
    if not sid:
        return None
    now = int(time.time())
    with connect() as conn:
        row = conn.execute(
            """
            select u.username, u.role
            from sessions s
            join users u on u.username = s.username
            where s.sid = ? and s.expires_at > ?
            """,
            (sid, now),
        ).fetchone()
    return dict(row) if row else None


def upsert_job(job_id, owner, status):
    current = now_text()
    with connect() as conn:
        conn.execute(
            """
            insert into jobs(job_id, owner, status, created_at, updated_at)
            values (?, ?, ?, ?, ?)
            on conflict(job_id) do update set
                owner = excluded.owner,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (job_id, owner, status, current, current),
        )


def update_job_status(job_id, status, reviewed_count=None):
    with connect() as conn:
        if reviewed_count is None:
            conn.execute(
                "update jobs set status = ?, updated_at = ? where job_id = ?",
                (status, now_text(), job_id),
            )
        else:
            conn.execute(
                "update jobs set status = ?, reviewed_count = ?, updated_at = ? where job_id = ?",
                (status, reviewed_count, now_text(), job_id),
            )


def get_job(job_id):
    with connect() as conn:
        row = conn.execute("select * from jobs where job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_users():
    with connect() as conn:
        rows = conn.execute("select username, role from users order by username").fetchall()
    return [dict(row) for row in rows]


def enqueue_sqlite(job_id, payload):
    with connect() as conn:
        conn.execute(
            "insert into task_queue(job_id, payload, status, created_at) values (?, ?, 'pending', ?)",
            (job_id, json.dumps(payload, ensure_ascii=False), int(time.time())),
        )


def pop_sqlite_task():
    with connect() as conn:
        row = conn.execute(
            "select id, job_id, payload from task_queue where status = 'pending' order by id limit 1"
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "update task_queue set status = 'running', started_at = ? where id = ?",
            (int(time.time()), row["id"]),
        )
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    return data


def finish_sqlite_task(task_id, status):
    with connect() as conn:
        conn.execute(
            "update task_queue set status = ?, finished_at = ? where id = ?",
            (status, int(time.time()), task_id),
        )
