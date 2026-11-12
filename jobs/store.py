"""Lưu job, video và cài đặt trong SQLite."""

import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data.db"

DEFAULT_SETTINGS = {
    "headless": True,
    "target_url": "new",  # "new" = mỗi job 1 chat mới; hoặc URL chat/thread có sẵn
    "prompt_suffix": "Generate the video as described. Do not ask questions.",
    "reply_timeout_min": 20,   # tối đa chờ 1 câu trả lời
    "idle_grace_sec": 120,     # Muse im lặng bao lâu thì coi như xong
    "delay_between_jobs_sec": 20,
    "auto_retry": 1,           # số lần tự gửi lại khi không có video
    "service_retry_wait_min": 15,  # Muse báo lỗi máy chủ: chờ bao lâu rồi thử lại (tăng gấp đôi, tối đa 60)
    "service_retry_max": 8,        # số lần hẹn giờ thử lại tối đa khi Muse lỗi máy chủ
}

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, prompt TEXT NOT NULL, target_url TEXT,
            status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|waiting|done|no_video|failed|cancelled
            attempts INTEGER NOT NULL DEFAULT 0,
            reply TEXT, error TEXT, debug_dir TEXT, log TEXT NOT NULL DEFAULT '',
            created REAL, started REAL, finished REAL
        );
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER, path TEXT NOT NULL, thumb TEXT,
            duration REAL, width INTEGER, height INTEGER, size INTEGER,
            kind TEXT NOT NULL DEFAULT 'clip',  -- clip|merged
            created REAL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS video_sequences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            session_id TEXT,
            continuity INTEGER NOT NULL DEFAULT 1,
            reference_images TEXT NOT NULL DEFAULT '[]',
            created REAL
        );
        """)
        for col in ("service_retries INTEGER NOT NULL DEFAULT 0", "retry_at REAL", "sequence_id INTEGER", "sequence_order INTEGER"):
            try:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # cột đã có
        try:
            c.execute("ALTER TABLE video_sequences ADD COLUMN continuity INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass  # cột đã có
        try:
            c.execute("ALTER TABLE video_sequences ADD COLUMN single_chat INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # cột đã có
        try:
            c.execute("ALTER TABLE video_sequences ADD COLUMN reference_images TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # cột đã có
        # job đang chạy dở khi tool bị tắt -> đưa lại vào hàng đợi
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")


# ---------- settings ----------

def get_settings() -> dict:
    with _lock, _conn() as c:
        rows = {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT * FROM settings")}
    return {**DEFAULT_SETTINGS, **rows}


def save_settings(values: dict) -> dict:
    with _lock, _conn() as c:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                c.execute("REPLACE INTO settings VALUES (?, ?)", (k, json.dumps(v)))
    return get_settings()


# ---------- jobs ----------

def add_job(prompt: str, title: str | None, target_url: str | None) -> int:
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO jobs (title, prompt, target_url, created) VALUES (?, ?, ?, ?)",
            (title or prompt[:60], prompt, target_url, time.time()),
        )
        return cur.lastrowid


def add_sequence(title: str, prompts: list[str], continuity: bool = True,
                 reference_images: list[str] | None = None, single_chat: bool = False,
                 master_prompt: str | None = None) -> list[int]:
    """Thêm video vào hàng đợi. Mặc định mỗi cảnh một job trong chung một chat Muse.
    single_chat: MỘT job duy nhất mang `master_prompt` (cả chuỗi short + yêu cầu gộp) gửi vào MỘT chat."""
    if not prompts:
        return []
    now = time.time()
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO video_sequences (title, continuity, reference_images, single_chat, created) VALUES (?, ?, ?, ?, ?)",
                        (title, int(continuity), json.dumps(reference_images or []), int(single_chat), now))
        sid = cur.lastrowid
        if single_chat:
            job = c.execute(
                "INSERT INTO jobs (title, prompt, target_url, sequence_id, sequence_order, created) VALUES (?, ?, NULL, ?, 1, ?)",
                (f"{title} · {len(prompts)} short → 1 clip", master_prompt or "\n\n".join(prompts), sid, now))
            return [job.lastrowid]
        ids = []
        for i, prompt in enumerate(prompts, 1):
            job = c.execute(
                "INSERT INTO jobs (title, prompt, target_url, sequence_id, sequence_order, created) VALUES (?, ?, NULL, ?, ?, ?)",
                (f"{title} · cảnh {i}/{len(prompts)}", prompt, sid, i, now),
            )
            ids.append(job.lastrowid)
    return ids


def get_sequence(sequence_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM video_sequences WHERE id=?", (sequence_id,)).fetchone()
    return dict(row) if row else None


def list_sequences() -> list[dict]:
    with _lock, _conn() as c:
        return [dict(row) for row in c.execute("SELECT * FROM video_sequences ORDER BY id DESC")]


def list_sequence_jobs(sequence_id: int) -> list[dict]:
    with _lock, _conn() as c:
        return [dict(row) for row in c.execute(
            "SELECT * FROM jobs WHERE sequence_id=? ORDER BY sequence_order, id", (sequence_id,))]


def update_sequence(sequence_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{key}=?" for key in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE video_sequences SET {cols} WHERE id=?", (*fields.values(), sequence_id))


def list_jobs(limit: int = 200) -> list[dict]:
    with _lock, _conn() as c:
        jobs = [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]
        counts = {r[0]: r[1] for r in c.execute("SELECT job_id, COUNT(*) FROM videos WHERE kind='clip' GROUP BY job_id")}
    for j in jobs:
        j["video_count"] = counts.get(j["id"], 0)
    return jobs


def get_job(job_id: int) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(r) if r else None


def next_queued() -> dict | None:
    with _lock, _conn() as c:
        r = c.execute(
            "SELECT * FROM jobs WHERE status='queued' OR (status='waiting' AND retry_at <= ?) ORDER BY id LIMIT 1",
            (time.time(),),
        ).fetchone()
    return dict(r) if r else None


def update_job(job_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def append_log(job_id: int, line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    with _lock, _conn() as c:
        c.execute("UPDATE jobs SET log = log || ? WHERE id=?", (f"[{stamp}] {line}\n", job_id))


def delete_job(job_id: int) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


# ---------- videos ----------

def add_video(job_id: int | None, path: str, meta: dict, kind: str = "clip", thumb: str | None = None) -> int:
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO videos (job_id, path, thumb, duration, width, height, size, kind, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, path, thumb, meta.get("duration"), meta.get("width"), meta.get("height"),
             meta.get("size"), kind, time.time()),
        )
        return cur.lastrowid


def list_videos(job_id: int | None = None) -> list[dict]:
    q, args = "SELECT v.*, j.title AS job_title FROM videos v LEFT JOIN jobs j ON j.id=v.job_id", ()
    if job_id is not None:
        q, args = q + " WHERE v.job_id=?", (job_id,)
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY v.id DESC", args)]


def get_videos(ids: list[int]) -> list[dict]:
    with _lock, _conn() as c:
        rows = {r["id"]: dict(r) for r in c.execute(
            f"SELECT * FROM videos WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return [rows[i] for i in ids if i in rows]


def delete_video(video_id: int) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        c.execute("DELETE FROM videos WHERE id=?", (video_id,))
    return dict(r) if r else None


def update_video(video_id: int, **fields) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE videos SET {cols} WHERE id=?", (*fields.values(), video_id))
