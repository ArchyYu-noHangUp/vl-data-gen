import json
import os
import time

from . import db


QUEUE_NAME = os.environ.get("QUEUE_NAME", "vl-data-gen:jobs")
REDIS_URL = os.environ.get("REDIS_URL", "")


def redis_client():
    if not REDIS_URL:
        return None
    try:
        import redis

        return redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        return None


def enqueue(job_id, payload):
    client = redis_client()
    if client:
        client.rpush(QUEUE_NAME, json.dumps(payload, ensure_ascii=False))
        return "redis"
    db.enqueue_sqlite(job_id, payload)
    return "sqlite"


def pop(block=True):
    client = redis_client()
    if client:
        item = client.blpop(QUEUE_NAME, timeout=5 if block else 1)
        if not item:
            return None
        _, raw = item
        return {"backend": "redis", "id": None, "payload": json.loads(raw)}
    while True:
        task = db.pop_sqlite_task()
        if task:
            task["backend"] = "sqlite"
            return task
        if not block:
            return None
        time.sleep(1)


def finish(task, status):
    if task and task.get("backend") == "sqlite":
        db.finish_sqlite_task(task["id"], status)
