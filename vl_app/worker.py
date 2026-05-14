import time
import traceback
from pathlib import Path

import server as legacy
from . import db
from .queue import finish, pop


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def append_error(job_id, text):
    RUNS.mkdir(exist_ok=True)
    with (RUNS / "server-errors.log").open("a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Worker job {job_id}\n{text}\n")


def run_task(task):
    payload = task["payload"]
    job_id = payload["job_id"]
    owner = payload.get("owner", "")
    db.update_job_status(job_id, "running")
    try:
        legacy.process_job(
            payload["config"],
            job_id=job_id,
            saved_questions=[Path(path) for path in payload.get("question_paths", [])],
            saved_answers=[Path(path) for path in payload.get("answer_paths", [])],
            data_source=payload.get("data_source", ""),
        )
        if owner:
            legacy.write_job_meta(job_id, owner)
        db.update_job_status(job_id, "completed")
        finish(task, "done")
    except Exception:
        append_error(job_id, traceback.format_exc())
        db.update_job_status(job_id, "failed")
        finish(task, "failed")


def main():
    db.init_db()
    RUNS.mkdir(exist_ok=True)
    print("Worker started", flush=True)
    while True:
        task = pop(block=True)
        if not task:
            continue
        run_task(task)


if __name__ == "__main__":
    main()
