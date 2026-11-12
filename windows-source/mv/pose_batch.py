"""Tạo hàng loạt "Video hướng dẫn tạo dáng": 1 lô = N video, mỗi video 1 dự án pose riêng (người mẫu + bối cảnh + pose
khác nhau, lên kế hoạch bằng mv/pose_themes.py). Một luồng nền đi từng bước cho mọi video của các lô đang chạy:
  design  — Muse thiết kế người mẫu (2 phương án) + vẽ bối cảnh
  poses   — Muse đề xuất pose + vẽ ảnh (dáng sai + các pose)
  videos  — Muse tạo video chuyển động cho từng pose
  render  — dựng video trên máy (kiểu "ai" hoặc "classic")
Tự thử lại khi Muse lỗi (ảnh pose bị từ chối 2 lần -> đổi sang dáng nhẹ nhàng hơn; vẫn lỗi -> bỏ pose đó).
Gọi lại chính API của tool (như scripts/pose_batch.py) nên mọi việc vẫn hiện bình thường trong từng dự án.
Lô lưu ở output/plans/batches/{id}.json, tắt tool bật lại thì chạy tiếp."""

import json
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

from mv import pose_themes

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "output" / "plans" / "batches"
TICK = 20
MAX_TRY = 2
TAME = ("Đổi sang dáng nhẹ nhàng, thanh lịch hơn nhưng vẫn cuốn hút: đứng hoặc ngồi tự nhiên trong bối cảnh, "
        "trang phục chỉnh tề kín đáo hơn một chút. Giữ nguyên gương mặt, kiểu tóc và phong cách người mẫu.")
STAGE_LABEL = {"new": "Chờ bắt đầu", "design": "Thiết kế người mẫu & bối cảnh", "poses": "Đề xuất & vẽ ảnh pose",
               "videos": "Tạo video chuyển động", "render": "Dựng video", "done": "Xong", "error": "Lỗi"}
_lock = threading.RLock()
_api = "http://127.0.0.1:8765/api/mv"


def call(method: str, url: str, body: dict | None = None, form: dict | None = None):
    if form is not None:
        b = "----posebatch"
        data = "".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n" for k, v in form.items()) + f"--{b}--\r\n"
        req = urllib.request.Request(_api + url, data=data.encode(), method=method,
                                     headers={"content-type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(_api + url, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()[:300])


# ---------- lưu trữ ----------

def _path(bid: int) -> Path:
    return DIR / f"{bid}.json"


def load(bid: int) -> dict | None:
    f = _path(bid)
    return json.loads(f.read_text()) if f.exists() else None


def save(b: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(b["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(b, ensure_ascii=False, indent=1))
    tmp.replace(_path(b["id"]))


def all_batches() -> list[dict]:
    if not DIR.exists():
        return []
    return sorted((json.loads(f.read_text()) for f in DIR.glob("*.json")), key=lambda b: -b["id"])


def used_themes() -> set:
    """Bối cảnh đã dùng ở các lô trước và ở kế hoạch tay (output/plans/pose_ads_*.json)."""
    out = {it["theme"] for b in all_batches() for it in b["items"]}
    for f in (ROOT / "output" / "plans").glob("pose_ads_*.json"):
        if not f.name.endswith(".state.json"):
            out |= {pose_themes.ALIASES.get(e["location"]["name"], e["location"]["name"]) for e in json.loads(f.read_text())}
    return out


# ---------- từng bước của 1 video ----------

def spec(it: dict) -> dict:
    keys = ("gender", "region", "age", "aesthetic", "hair", "makeup", "body", "sexy", "style", "notes")
    return {"source": "new", **{k: it.get(k, "") for k in keys}}


def tried(it: dict, key: str) -> int:
    it.setdefault("tries", {})
    it["tries"][key] = it["tries"].get(key, 0) + 1
    return it["tries"][key]


def start_design(it: dict, prefix: str) -> None:
    pid = call("POST", "", form={"kind": "pose", "title": f"{prefix} · {it['title']}"})["id"]
    it["pid"] = pid
    call("PATCH", f"/{pid}", {"model_spec": {**spec(it), "pose": "photo"}})
    call("POST", f"/{pid}/task/model_design", {**spec(it), "outfit": "", "variants": 2})
    loc = call("POST", f"/{pid}/assets", {"kind": "location", **it["location"]})["id"]
    call("PATCH", f"/{pid}", {"sel_location": loc})
    call("POST", f"/assets/{loc}/generate", {})
    it["stage"] = "design"


def step(b: dict, it: dict) -> None:
    """Đẩy 1 video sang bước tiếp theo khi dự án của nó không còn việc đang chạy."""
    if it["stage"] in ("done", "error"):
        return
    if it["stage"] == "new":
        start_design(it, b["title"])
        return
    p = call("GET", f"/{it['pid']}")
    busy = [t["kind"] for t in p["tasks"] if t["status"] in ("queued", "running")]
    if busy:
        it["msg"] = "Đang chạy: " + ", ".join(busy)
        return
    it["msg"] = ""
    pid = it["pid"]
    rows = p["shorts"]
    if it["stage"] == "design":
        chars = [a for a in p["assets"] if a["kind"] == "character" and a["image_url"]]
        loc = next((a for a in p["assets"] if a["id"] == p["sel_location"]), None)
        if not chars:
            if tried(it, "design") > MAX_TRY:
                raise RuntimeError("Muse không vẽ được người mẫu")
            call("POST", f"/{pid}/task/model_design", {**spec(it), "outfit": "", "variants": 2})
            return
        if not any(a["id"] == p["sel_model"] for a in chars):
            call("PATCH", f"/{pid}", {"sel_model": chars[0]["id"]})
        if not (loc and loc["image_url"]):
            if tried(it, "location") > MAX_TRY:
                raise RuntimeError("Muse không vẽ được bối cảnh")
            call("POST", f"/assets/{p['sel_location']}/generate", {})
            return
        call("POST", f"/{pid}/task/pose_list", {"count": b["poses"], "notes": it.get("pose_notes", "")})
        call("POST", f"/{pid}/task/pose_images", {})
        it["stage"] = "poses"
    elif it["stage"] == "poses":
        if len(rows) < 2:
            if tried(it, "pose_list") > MAX_TRY:
                raise RuntimeError("Muse không đề xuất được pose")
            call("POST", f"/{pid}/task/pose_list", {"count": b["poses"], "notes": it.get("pose_notes", "")})
            call("POST", f"/{pid}/task/pose_images", {})
            return
        missing = [s for s in rows if not s["thumb_url"]]
        if missing:
            n = tried(it, "images")
            if n <= MAX_TRY:  # lần 1-2: vẽ lại như cũ
                call("POST", f"/{pid}/task/pose_images", {})
            elif n == MAX_TRY + 1:  # lần 3: có thể Muse từ chối vì dáng quá hở -> đổi dáng nhẹ nhàng hơn
                for s in missing:
                    call("POST", f"/shorts/{s['id']}/pose_regen", {"feedback": TAME})
            elif rows[0]["thumb_url"] and len(rows) - len(missing) >= 3:  # vẫn lỗi -> bỏ các pose đó
                keep = [{"id": s["id"], "name": s["lyric"] or "", "description": s["description"]} for s in rows if s["thumb_url"]]
                call("PUT", f"/{pid}/poses", {"poses": keep})
            else:
                raise RuntimeError("Muse không vẽ được ảnh pose")
            return
        if b["live"]:
            call("POST", f"/{pid}/task/pose_videos", {})
            it["stage"] = "videos"
        else:
            it["stage"] = "render"
            step(b, it)
    elif it["stage"] == "videos":
        if any(not s["video_url"] for s in rows[1:]) and tried(it, "videos") <= MAX_TRY:
            call("POST", f"/{pid}/task/pose_videos", {})
            return
        it["stage"] = "render"  # pose nào vẫn không có video thì dựng bằng ảnh tĩnh
        step(b, it)
    elif it["stage"] == "render":
        if it.get("render_task"):
            t = next((t for t in p["tasks"] if t["id"] == it["render_task"]), None)
            if t and t["status"] == "done" and p["exported_path"]:
                it.update(stage="done", video=p["exported_path"], video_url=p["exported_url"], finished=time.time())
                return
            if tried(it, "render") > MAX_TRY:
                raise RuntimeError("Dựng video lỗi: " + ((t or {}).get("error") or "")[:200])
        it["render_task"] = call("POST", f"/{pid}/task/pose_render",
                                 {"music": b.get("music") or p.get("audio_path") or "", "style": b["render"]})["task"]


def tick() -> None:
    for b in all_batches():
        if b["status"] != "running":
            continue
        with _lock:
            b = load(b["id"])
            if not b or b["status"] != "running":
                continue
            for it in b["items"]:
                try:
                    step(b, it)
                except Exception as e:
                    traceback.print_exc()
                    it.update(last_stage=it["stage"], stage="error", msg=str(e)[:300])
            if all(it["stage"] in ("done", "error") for it in b["items"]):
                b["status"] = "done"
                b["finished"] = time.time()
            save(b)


def loop() -> None:
    time.sleep(5)
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        time.sleep(TICK)


def start(api: str | None = None) -> None:
    global _api
    if api:
        _api = api
    threading.Thread(target=loop, daemon=True, name="pose-batch").start()


# ---------- API ----------

def project_view(b: dict) -> dict:
    for it in b["items"]:
        it["stage_label"] = STAGE_LABEL.get(it["stage"], it["stage"])
    b["done_count"] = sum(it["stage"] == "done" for it in b["items"])
    return b


def make_router() -> APIRouter:
    r = APIRouter(prefix="/api/pose_batch")

    @r.post("/plan")
    def make_plan(body: dict):
        n = int(body.get("count") or 5)
        if not 1 <= n <= 30:
            raise HTTPException(400, "Số video từ 1 đến 30")
        return {"items": pose_themes.plan(n, body.get("gender", "mix"), body.get("sexy", "auto"), used_themes(),
                                          notes=(body.get("notes") or "").strip())}

    @r.post("/reroll")
    def reroll(body: dict):
        items, idx = body["items"], int(body["index"])
        return pose_themes.reroll(items, idx, used_themes())

    @r.post("")
    def create(body: dict):
        items = body.get("items") or []
        if not items:
            raise HTTPException(400, "Chưa có video nào trong kế hoạch")
        names = [it["theme"] for it in items]
        if len(set(names)) < len(names):
            raise HTTPException(400, "Có 2 video trùng bối cảnh — bấm Đổi ở 1 video")
        with _lock:
            bid = max([b["id"] for b in all_batches()] + [0]) + 1
            b = {"id": bid, "title": (body.get("title") or "").strip() or f"Lô {bid}", "created": time.time(),
                 "status": "running", "render": body.get("render", "ai"), "live": bool(body.get("live", True)),
                 "poses": int(body.get("poses") or 5), "music": body.get("music") or "",
                 "items": [{**it, "stage": "new", "pid": None, "msg": ""} for it in items]}
            save(b)
        return project_view(b)

    @r.get("")
    def batches():
        return [project_view(b) for b in all_batches()]

    @r.post("/{bid}/{action}")
    def control(bid: int, action: str):
        with _lock:
            b = load(bid)
            if not b:
                raise HTTPException(404)
            if action == "pause":
                b["status"] = "paused"
            elif action in ("resume", "retry"):
                if action == "retry":  # chạy lại các video lỗi từ bước đang dở
                    for it in b["items"]:
                        if it["stage"] == "error":
                            it.update(stage="new" if not it.get("pid") else it.get("last_stage") or "design",
                                      tries={}, msg="")
                b["status"] = "running"
            else:
                raise HTTPException(400)
            save(b)
        return project_view(b)

    @r.delete("/{bid}")
    def delete(bid: int):
        """Chỉ xoá lô khỏi danh sách — các dự án và video đã tạo vẫn giữ nguyên."""
        with _lock:
            _path(bid).unlink(missing_ok=True)
        return {"ok": True}

    return r
