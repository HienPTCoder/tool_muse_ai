"""Dự án tạo video nhiều short: MV âm nhạc (kind=mv), người mẫu tạo dáng (kind=model) và
MV làm lại từ video có sẵn (kind=remake).
Dùng chung: nhân vật/bối cảnh khoá, các short, tác vụ gửi Muse."""

import json
import time

from jobs.store import _conn, _lock

# Tác vụ chạy ngay trên máy (thread riêng), không cần Muse
LOCAL_KINDS = {"lyrics", "pose_render"}

# Cột lưu dạng JSON
_JSON = {"lyrics", "characters", "args", "model_spec", "song", "refs"}

PROJECT_FIELDS = {"title", "step", "audio_path", "duration", "aspect", "style", "lipsync_pct",
                  "max_short_sec", "lyrics", "script", "exported_path", "chat_mode", "chat_session",
                  "analysis", "model_spec", "ref_video_path", "sel_model", "sel_location", "show_lyrics", "region",
                  "song", "mv_mode"}
ASSET_FIELDS = {"kind", "name", "description", "image_path", "locked", "source", "orig_path", "refs", "mode"}
SHORT_FIELDS = {"idx", "start", "end", "lyric", "description", "lipsync", "characters", "location",
                "video_path", "thumb_path", "status", "feedback", "error", "version", "lyric_mode", "script_id", "cont",
                "retries"}


def init() -> None:
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mv_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            step INTEGER NOT NULL DEFAULT 1,           -- bước đang làm trên giao diện (1..5)
            audio_path TEXT, duration REAL,
            aspect TEXT NOT NULL DEFAULT '16:9', style TEXT NOT NULL DEFAULT 'hoạt hình 2D',
            lipsync_pct INTEGER NOT NULL DEFAULT 50, max_short_sec INTEGER NOT NULL DEFAULT 8,
            lyrics TEXT,                               -- JSON [{start, end, text, section}]
            script TEXT, exported_path TEXT, created REAL
        );
        CREATE TABLE IF NOT EXISTS mv_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            kind TEXT NOT NULL,                        -- character|location
            name TEXT NOT NULL, description TEXT, image_path TEXT,
            locked INTEGER NOT NULL DEFAULT 0, source TEXT  -- muse|import
        );
        CREATE TABLE IF NOT EXISTS mv_shorts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, idx INTEGER NOT NULL,
            start REAL NOT NULL, "end" REAL NOT NULL, lyric TEXT, description TEXT,
            lipsync INTEGER NOT NULL DEFAULT 0,
            characters TEXT,                           -- JSON [tên nhân vật]
            location TEXT, video_path TEXT, thumb_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',    -- pending|queued|running|done|failed
            feedback TEXT, error TEXT, version INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mv_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            kind TEXT NOT NULL,                        -- lyrics|lyrics_fix|script|assets|asset_image|plan|shorts
            args TEXT, status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed|cancelled
            log TEXT NOT NULL DEFAULT '', error TEXT, created REAL, finished REAL
        );
        """)
        for col in ("chat_mode TEXT NOT NULL DEFAULT 'new'",  # new = mỗi short 1 chat mới; single = 1 chat cho cả MV; chain = nối khung cuối
                    "chat_session TEXT",                       # session id của chat dùng chung (chế độ single)
                    "kind TEXT NOT NULL DEFAULT 'mv'",         # mv | model (người mẫu tạo dáng) | remake (làm lại MV có sẵn)
                    "ref_video_path TEXT",                     # model: video mẫu
                    "analysis TEXT",                           # model: Muse phân tích video mẫu
                    "model_spec TEXT",                         # model: JSON lựa chọn thiết kế người mẫu
                    "sel_model INTEGER",                       # model: người mẫu đang chọn để viết kịch bản
                    "sel_location INTEGER",                    # model: bối cảnh đang chọn để viết kịch bản
                    "show_lyrics INTEGER DEFAULT 0",           # MV: phủ lời karaoke dưới video khi xuất
                    "region TEXT",                             # MV: phong cách nhân vật/bối cảnh '' | eu | asia
                    "song TEXT",                               # MV: JSON phân tích bài hát (giọng, tuổi, ngôn ngữ, chủ đề, người trình bày)
                    "mv_mode TEXT"):                           # MV: story (chỉ kể chuyện) | singer (có ca sĩ + vài đoạn lip sync) | full (lip sync cả bài)
            try:
                c.execute(f"ALTER TABLE mv_projects ADD COLUMN {col}")
            except Exception:
                pass
        for col in ("orig_path TEXT",            # remake: ảnh cắt từ video gốc
                    "refs TEXT",                 # remake: JSON [đường dẫn ảnh người dùng tải lên để thay thế]
                    "mode TEXT DEFAULT 'keep'"): # remake: keep = giữ như gốc | replace = thay bằng ảnh của người dùng
            try:
                c.execute(f"ALTER TABLE mv_assets ADD COLUMN {col}")
            except Exception:
                pass
        try:
            c.execute("ALTER TABLE mv_shorts ADD COLUMN script_id INTEGER")  # model: short thuộc kịch bản nào
        except Exception:
            pass
        c.execute("""CREATE TABLE IF NOT EXISTS mv_scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            title TEXT NOT NULL, concept TEXT, created REAL)""")
        for col in ("model_id INTEGER", "location_id INTEGER"):  # người mẫu + bối cảnh của kịch bản
            try:
                c.execute(f"ALTER TABLE mv_scripts ADD COLUMN {col}")
            except Exception:
                pass
        try:
            # quote = gửi kèm lời hát để nhép; plain = chỉ tả hát nhép theo nhịp (Muse hay từ chối hát lời bài có bản quyền)
            c.execute("ALTER TABLE mv_shorts ADD COLUMN lyric_mode TEXT NOT NULL DEFAULT 'quote'")
        except Exception:
            pass
        try:
            # MV: short nối tiếp short liền trước trong cùng 1 phân cảnh (giữ góc máy, bối cảnh, hành động liền mạch)
            c.execute("ALTER TABLE mv_shorts ADD COLUMN cont INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            # số lần tool đã tự gửi lại short này khi Muse không trả về video
            c.execute("ALTER TABLE mv_shorts ADD COLUMN retries INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        # tool bị tắt giữa chừng -> chạy lại
        # tác vụ chạy trên máy (LOCAL_KINDS) không được worker lấy lại từ hàng chờ -> báo lỗi để người dùng bấm chạy lại
        local = tuple(LOCAL_KINDS)
        marks = ",".join("?" * len(local))
        c.execute(f"UPDATE mv_tasks SET status='queued' WHERE status='running' AND kind NOT IN ({marks})", local)
        c.execute(f"UPDATE mv_tasks SET status='failed', error='Tool bị tắt giữa chừng — bấm chạy lại' "
                  f"WHERE status IN ('queued','running') AND kind IN ({marks})", local)
        c.execute("UPDATE mv_shorts SET status='queued' WHERE status='running'")


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in _JSON & d.keys():
        d[k] = json.loads(d[k]) if d[k] else ([] if k != "args" else {})
    return d


def _dump(fields: dict, allowed: set) -> dict:
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Trường không hợp lệ: {', '.join(bad)}")
    return {k: json.dumps(v, ensure_ascii=False) if k in _JSON else v for k, v in fields.items()}


def _update(table: str, row_id: int, fields: dict, allowed: set) -> None:
    fields = _dump(fields, allowed)
    if not fields:
        return
    cols = ", ".join(f'"{k}"=?' for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), row_id))


# ---------- dự án ----------

def add_project(title: str, kind: str = "mv") -> int:
    with _lock, _conn() as c:
        return c.execute("INSERT INTO mv_projects (title, kind, created) VALUES (?, ?, ?)",
                         (title, kind, time.time())).lastrowid


def list_projects() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("""SELECT p.id, p.title, p.kind, p.step, p.duration, p.created,
            (SELECT COUNT(*) FROM mv_shorts s WHERE s.project_id=p.id) AS n_shorts,
            (SELECT COUNT(*) FROM mv_shorts s WHERE s.project_id=p.id AND s.status='done') AS n_done
            FROM mv_projects p ORDER BY p.id DESC""").fetchall()
    return [dict(r) for r in rows]


def get_project(pid: int) -> dict | None:
    with _lock, _conn() as c:
        return _row(c.execute("SELECT * FROM mv_projects WHERE id=?", (pid,)).fetchone())


def update_project(pid: int, **fields) -> None:
    _update("mv_projects", pid, fields, PROJECT_FIELDS)


def delete_project(pid: int) -> None:
    with _lock, _conn() as c:
        for t in ("mv_assets", "mv_shorts", "mv_tasks", "mv_scripts"):
            c.execute(f"DELETE FROM {t} WHERE project_id=?", (pid,))
        c.execute("DELETE FROM mv_projects WHERE id=?", (pid,))


# ---------- nhân vật / bối cảnh ----------

def list_assets(pid: int) -> list[dict]:
    with _lock, _conn() as c:
        return [_row(r) for r in c.execute(
            "SELECT * FROM mv_assets WHERE project_id=? ORDER BY kind, id", (pid,))]


def get_asset(aid: int) -> dict | None:
    with _lock, _conn() as c:
        return _row(c.execute("SELECT * FROM mv_assets WHERE id=?", (aid,)).fetchone())


def add_asset(pid: int, kind: str, name: str, description: str = "") -> int:
    with _lock, _conn() as c:
        return c.execute("INSERT INTO mv_assets (project_id, kind, name, description) VALUES (?, ?, ?, ?)",
                         (pid, kind, name, description)).lastrowid


def update_asset(aid: int, **fields) -> None:
    _update("mv_assets", aid, fields, ASSET_FIELDS)


def delete_asset(aid: int) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM mv_assets WHERE id=?", (aid,))


def replace_unlocked_assets(pid: int, items: list[dict], kinds: tuple = ("character", "location", "prop")) -> None:
    """Kết quả phân tích mới thay cho các mục chưa khoá (thuộc `kinds`); mục đã khoá giữ nguyên."""
    marks = ",".join("?" * len(kinds))
    with _lock, _conn() as c:
        locked = {(r["kind"], r["name"].lower()) for r in c.execute(
            "SELECT kind, name FROM mv_assets WHERE project_id=? AND locked=1", (pid,))}
        c.execute(f"DELETE FROM mv_assets WHERE project_id=? AND locked=0 AND kind IN ({marks})", (pid, *kinds))
        for a in items:
            if (a["kind"], a["name"].lower()) not in locked:
                c.execute("INSERT INTO mv_assets (project_id, kind, name, description, orig_path) VALUES (?, ?, ?, ?, ?)",
                          (pid, a["kind"], a["name"], a.get("description", ""), a.get("orig_path")))


# ---------- short ----------

def list_shorts(pid: int, script_id: int | None = None) -> list[dict]:
    q, args = "SELECT * FROM mv_shorts WHERE project_id=?", (pid,)
    if script_id is not None:
        q, args = q + " AND script_id=?", (pid, script_id)
    with _lock, _conn() as c:
        return [_row(r) for r in c.execute(q + " ORDER BY script_id, idx", args)]


def get_short(sid: int) -> dict | None:
    with _lock, _conn() as c:
        return _row(c.execute("SELECT * FROM mv_shorts WHERE id=?", (sid,)).fetchone())


def update_short(sid: int, **fields) -> None:
    _update("mv_shorts", sid, fields, SHORT_FIELDS)


def replace_shorts(pid: int, shorts: list[dict]) -> None:
    with _lock, _conn() as c:
        old_shorts = {r["id"]: dict(r) for r in c.execute("SELECT * FROM mv_shorts WHERE project_id=?", (pid,))}
        c.execute("DELETE FROM mv_shorts WHERE project_id=?", (pid,))
        for i, s in enumerate(shorts, 1):
            old = old_shorts.get(s.get("id")) if s.get("id") else None
            video_path = s.get("video_path") or (old["video_path"] if old else None)
            thumb_path = s.get("thumb_path") or (old["thumb_path"] if old else None)
            status = "done" if video_path else s.get("status", "pending")
            chars = s.get("characters", [])
            chars_json = json.dumps(chars, ensure_ascii=False) if isinstance(chars, list) else (str(chars) if chars else "[]")
            c.execute(
                'INSERT INTO mv_shorts (project_id, idx, start, "end", lyric, description, lipsync, characters, location, cont, video_path, thumb_path, status) '
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, i, float(s.get("start", 0)), float(s.get("end", 5)), s.get("lyric", ""), s.get("description", ""),
                 int(bool(s.get("lipsync"))), chars_json,
                 s.get("location", ""), int(bool(s.get("cont")) and i > 1), video_path, thumb_path, status))


def set_poses(pid: int, poses: list[dict]) -> None:
    """Video hướng dẫn tạo dáng: mỗi pose là 1 dòng short (idx 0 = dáng sai mở đầu), ảnh pose lưu ở thumb_path."""
    with _lock, _conn() as c:
        c.execute("DELETE FROM mv_shorts WHERE project_id=?", (pid,))
        for i, x in enumerate(poses):
            c.execute('INSERT INTO mv_shorts (project_id, idx, start, "end", lyric, description, thumb_path, status) '
                      "VALUES (?, ?, 0, 0, ?, ?, ?, ?)",
                      (pid, i, x.get("name", ""), x.get("description", ""), x.get("thumb_path"),
                       "done" if x.get("thumb_path") else "pending"))


# ---------- kịch bản (người mẫu tạo dáng: mỗi kịch bản có dãy short riêng) ----------

def list_scripts(pid: int) -> list[dict]:
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM mv_scripts WHERE project_id=? ORDER BY id", (pid,))]


def get_script(script_id: int) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM mv_scripts WHERE id=?", (script_id,)).fetchone()
        return dict(r) if r else None


def add_script(pid: int, title: str, concept: str, shorts: list[dict],
               model_id: int | None = None, location_id: int | None = None) -> int:
    with _lock, _conn() as c:
        sid = c.execute("INSERT INTO mv_scripts (project_id, title, concept, created, model_id, location_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (pid, title, concept, time.time(), model_id, location_id)).lastrowid
        for i, s in enumerate(shorts, 1):
            c.execute(
                'INSERT INTO mv_shorts (project_id, script_id, idx, start, "end", lyric, description, characters, location) '
                "VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)",
                (pid, sid, i, s["start"], s["end"], s.get("description", ""),
                 json.dumps(s.get("characters", []), ensure_ascii=False), s.get("location", "")))
        return sid


def update_script(script_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in ("title", "concept")}
    if fields:
        cols = ", ".join(f"{k}=?" for k in fields)
        with _lock, _conn() as c:
            c.execute(f"UPDATE mv_scripts SET {cols} WHERE id=?", (*fields.values(), script_id))


def delete_script(script_id: int) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM mv_shorts WHERE script_id=?", (script_id,))
        c.execute("DELETE FROM mv_scripts WHERE id=?", (script_id,))


# ---------- tác vụ Muse ----------

def add_task(pid: int, kind: str, args: dict | None = None) -> int:
    with _lock, _conn() as c:
        return c.execute("INSERT INTO mv_tasks (project_id, kind, args, created) VALUES (?, ?, ?, ?)",
                         (pid, kind, json.dumps(args or {}, ensure_ascii=False), time.time())).lastrowid


def next_task() -> dict | None:
    with _lock, _conn() as c:
        return _row(c.execute(
            f"SELECT * FROM mv_tasks WHERE status='queued' AND kind NOT IN ({','.join('?' * len(LOCAL_KINDS))}) "
            "ORDER BY CASE WHEN kind IN ('shorts', 'pose_videos') THEN 1 ELSE 0 END, id LIMIT 1",
            tuple(LOCAL_KINDS)).fetchone())


def has_other_waiting_task(current_pid: int | None = None) -> bool:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT id FROM mv_tasks WHERE status='queued' "
            "AND kind NOT IN ('shorts', 'pose_videos') LIMIT 1"
        ).fetchone()
        return bool(row)


def list_tasks(pid: int, limit: int = 20) -> list[dict]:
    with _lock, _conn() as c:
        return [_row(r) for r in c.execute(
            "SELECT * FROM mv_tasks WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limit))]


def get_task(tid: int) -> dict | None:
    with _lock, _conn() as c:
        return _row(c.execute("SELECT * FROM mv_tasks WHERE id=?", (tid,)).fetchone())


def update_task(tid: int, **fields) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE mv_tasks SET {cols} WHERE id=?", (*fields.values(), tid))


def task_log(tid: int, line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    with _lock, _conn() as c:
        c.execute("UPDATE mv_tasks SET log = log || ? WHERE id=?", (f"[{stamp}] {line}\n", tid))


def active_task(pid: int, kind: str | None = None) -> dict | None:
    q = "SELECT * FROM mv_tasks WHERE project_id=? AND status IN ('queued','running')"
    args: tuple = (pid,)
    if kind:
        q, args = q + " AND kind=?", (pid, kind)
    with _lock, _conn() as c:
        return _row(c.execute(q + " ORDER BY id LIMIT 1", args).fetchone())
