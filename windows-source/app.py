"""Muse Video Studio — server local + giao diện web.

    .venv/bin/python app.py      → mở http://127.0.0.1:8765
"""

import base64
import json
import os
import shutil
import subprocess
import time
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jobs import store
from jobs.worker import CLIPS, OUTPUT, THUMBS, Worker
from muse import auth
from muse.auth import COOKIES_FILE
from mv import store as mvstore
from mv import pose_batch
from mv import batch_prompt
from mv.api import make_router
from post import ffmpeg

ROOT = Path(__file__).resolve().parent
MERGED = OUTPUT / "merged"
HOST, PORT = "127.0.0.1", 8765

store.init()
mvstore.init()
worker = Worker()
app = FastAPI(title="Muse Video Studio")
app.mount("/files", StaticFiles(directory=OUTPUT), name="files")


def _url(path: str | None) -> str | None:
    if not path:
        return None
    # Một đường dẫn nằm ngoài output/ (ví dụ ảnh tham chiếu trỏ vào thư mục tạm) không phục vụ được
    # qua /files. Trước đây relative_to ném ValueError và làm sập CẢ API chi tiết dự án, khiến dự án
    # không mở được trên giao diện. Giờ chỉ bỏ qua đường dẫn đó.
    try:
        return "/files/" + str(Path(path).resolve().relative_to(OUTPUT.resolve()))
    except ValueError:
        return None


def _video_out(v: dict) -> dict:
    return {**v, "url": _url(v["path"]), "thumb_url": _url(v["thumb"]), "name": Path(v["path"]).name}


app.include_router(make_router(worker, lambda p: _url(p)))
app.include_router(pose_batch.make_router())


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/{name}.js")
def web_js(name: str):
    if name not in ("mv", "model", "remake", "pose", "posebatch", "stickerman"):
        raise HTTPException(404)
    return FileResponse(ROOT / "web" / f"{name}.js", media_type="text/javascript")


# ---------- trạng thái ----------

@app.get("/api/state")
def state():
    return {
        "worker": worker.state(),
        "jobs": store.list_jobs(),
        "settings": store.get_settings(),
        "has_cookies": COOKIES_FILE.exists(),
        "account": auth.active_account(),
    }


# ---------- job ----------

class NewJobs(BaseModel):
    prompts: list[str]
    target_url: str | None = None


@app.post("/api/jobs")
def add_jobs(body: NewJobs):
    ids = [store.add_job(p.strip(), None, body.target_url or None) for p in body.prompts if p.strip()]
    if not ids:
        raise HTTPException(400, "Chưa có prompt nào")
    return {"ids": ids}


@app.get("/api/sequences")
def sequences():
    result = []
    for seq in store.list_sequences():
        scenes = []
        for job in store.list_sequence_jobs(seq["id"]):
            scenes.append({**job, "videos": [_video_out(v) for v in store.list_videos(job["id"]) ]})
        result.append({**seq, "scenes": scenes})
    return result


@app.post("/api/sequences")
def add_sequences(body: dict):
    """Xếp các cảnh theo thứ tự, mỗi video ở một chat Muse riêng để giữ ngữ cảnh nối cảnh."""
    videos = body.get("videos") or []
    if not isinstance(videos, list) or not videos or len(videos) > 20:
        raise HTTPException(400, "Chọn từ 1 đến 20 video")
    raw_attachments = body.get("attachments") or []
    if not isinstance(raw_attachments, list) or len(raw_attachments) > 8:
        raise HTTPException(400, "Tối đa 8 ảnh tham chiếu")
    refs = []
    total = 0
    ref_dir = OUTPUT / "tmp" / "product_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ext_by_mime = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    def save_image_refs(items):
        saved, size = [], 0
        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(400, "Ảnh tham chiếu không hợp lệ")
            mime = str(item.get("mimeType") or "").lower()
            if mime not in ext_by_mime or not item.get("dataBase64"):
                raise HTTPException(400, "Ảnh tham chiếu không hợp lệ (dùng JPG, PNG hoặc WebP)")
            try:
                data = base64.b64decode(item["dataBase64"], validate=True)
            except Exception:
                raise HTTPException(400, "Dữ liệu ảnh không hợp lệ")
            size += len(data)
            path = ref_dir / f"ref_{uuid.uuid4().hex}{ext_by_mime[mime]}"
            path.write_bytes(data)
            saved.append(str(path))
        return saved, size
    refs, total = save_image_refs(raw_attachments)
    all_ids = []
    for i, video in enumerate(videos, 1):
        prompts = video.get("prompts") if isinstance(video, dict) else None
        if not isinstance(prompts, list) or not prompts or len(prompts) > 18:
            raise HTTPException(400, f"Video {i}: cần từ 1 đến 18 cảnh")
        clean = [p.strip() for p in prompts if isinstance(p, str) and p.strip()]
        if len(clean) != len(prompts):
            raise HTTPException(400, f"Video {i}: có cảnh trống hoặc không hợp lệ")
        product_refs, product_total = save_image_refs(video.get("attachments") or [])
        if len(refs) + len(product_refs) > 8:
            raise HTTPException(400, f"Video {i}: tối đa 8 ảnh tham chiếu")
        if total + product_total > 7 * 1024 * 1024:
            raise HTTPException(400, f"Video {i}: tổng dung lượng ảnh phải nhỏ hơn 7 MB")
        title = str(video.get("title") or f"Video {i}").strip()[:100]
        single = bool(body.get("single_chat", False))
        master = None
        if single:
            if len(clean) > 6:
                raise HTTPException(400, f"Video {i}: chế độ 1 chat tối đa 6 short (6 x 10 giây = 1 phút)")
            master = batch_prompt.build_vi(clean, max_sec=10, total_sec=len(clean) * 10)
        all_ids.extend(store.add_sequence(title, clean, bool(body.get("continuity", True)), refs + product_refs,
                                          single_chat=single, master_prompt=master))
    if not all_ids:
        raise HTTPException(400, "Chưa có cảnh nào")
    return {"job_ids": all_ids}


@app.post("/api/muse/text")
def ask_muse_text(body: dict):
    if worker.busy:
        raise HTTPException(409, "Muse đang bận tạo video. Chờ job hiện tại xong rồi gửi yêu cầu phân tích lại.")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Thiếu yêu cầu gửi Muse")
    attachments = body.get("attachments") or []
    if not isinstance(attachments, list) or len(attachments) > 8:
        raise HTTPException(400, "Tối đa 8 ảnh tham chiếu")
    for item in attachments:
        if not isinstance(item, dict) or not item.get("dataBase64") or item.get("category") != "image":
            raise HTTPException(400, "Ảnh tham chiếu không hợp lệ")
    timeout = max(120, int(store.get_settings()["reply_timeout_min"]) * 60 + 60)
    try:
        text = worker.call("muse_text", prompt, attachments, timeout=timeout)
    except TimeoutError:
        raise HTTPException(504, "Muse chưa trả lời trong thời gian chờ")
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    if not text:
        raise HTTPException(502, "Muse chưa trả về nội dung văn bản")
    return {"text": text}


@app.post("/api/muse/text-batch")
def ask_muse_text_batch(body: dict):
    if worker.busy:
        raise HTTPException(409, "Muse đang bận tạo video. Chờ job hiện tại xong rồi gửi yêu cầu phân tích lại.")
    prompts = body.get("prompts") or []
    if not isinstance(prompts, list) or not prompts or len(prompts) > 10 or any(not str(p).strip() for p in prompts):
        raise HTTPException(400, "Cần từ 1 đến 10 yêu cầu phân tích link")
    attachments = body.get("attachments") or []
    if not isinstance(attachments, list) or len(attachments) > 8:
        raise HTTPException(400, "Tối đa 8 ảnh tham chiếu")
    if any(not isinstance(a, dict) or not a.get("dataBase64") or a.get("category") != "image" for a in attachments):
        raise HTTPException(400, "Ảnh tham chiếu không hợp lệ")
    per_prompt = body.get("attachments_per_prompt") or [[] for _ in prompts]
    if not isinstance(per_prompt, list) or len(per_prompt) != len(prompts):
        raise HTTPException(400, "Số bộ ảnh tham chiếu phải khớp số yêu cầu")
    for group in per_prompt:
        if not isinstance(group, list) or len(group) + len(attachments) > 8:
            raise HTTPException(400, "Mỗi chat tối đa 8 ảnh tham chiếu")
        if any(not isinstance(a, dict) or not a.get("dataBase64") or a.get("category") != "image" for a in group):
            raise HTTPException(400, "Ảnh tham chiếu sản phẩm không hợp lệ")
    timeout = max(120, int(store.get_settings()["reply_timeout_min"]) * 60 + 60)
    try:
        results = worker.call("muse_text_batch", [str(p) for p in prompts], attachments, per_prompt, timeout=timeout)
    except TimeoutError:
        raise HTTPException(504, "Muse chưa trả lời trong thời gian chờ")
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    return {"results": results}


@app.post("/api/product-images")
def get_product_images(body: dict):
    """Lấy ảnh sản phẩm gốc từ trang thương mại điện tử để làm ảnh tham chiếu video."""
    if worker.busy:
        raise HTTPException(409, "Muse đang bận tạo video. Chờ job hiện tại xong rồi lấy ảnh sản phẩm.")
    urls = body.get("urls") or []
    if not isinstance(urls, list) or not urls or len(urls) > 10:
        raise HTTPException(400, "Cần từ 1 đến 10 link sản phẩm")
    if any(not isinstance(u, str) or not u.strip() for u in urls):
        raise HTTPException(400, "Link sản phẩm không được để trống")
    try:
        results = worker.call("product_images", urls, timeout=max(180, len(urls) * 90 + 30))
    except TimeoutError:
        raise HTTPException(504, "Hết thời gian lấy ảnh sản phẩm")
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    return {"results": results}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Không có job này")
    job["videos"] = [_video_out(v) for v in store.list_videos(job_id)]
    if job.get("debug_dir") and (Path(job["debug_dir"]) / "screen.png").exists():
        job["debug_screen"] = _url(str(Path(job["debug_dir"]) / "screen.png"))
    return job


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int):
    store.update_job(job_id, status="queued", error=None, service_retries=0, retry_at=None)
    worker.clear_cooldown()
    store.append_log(job_id, "Đưa lại vào hàng đợi")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    job = store.get_job(job_id)
    if job and job["status"] in ("queued", "waiting"):
        store.update_job(job_id, status="cancelled")
    worker.cancel(job_id)
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    if worker.current_job == job_id:
        raise HTTPException(409, "Job đang chạy, hãy huỷ trước")
    store.delete_job(job_id)
    return {"ok": True}


@app.post("/api/queue/{action}")
def queue_action(action: str):
    if action not in ("pause", "resume"):
        raise HTTPException(400)
    worker.paused = action == "pause"
    return worker.state()


# ---------- video ----------

@app.get("/api/videos")
def videos():
    return [_video_out(v) for v in store.list_videos() if Path(v["path"]).exists()]


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int):
    v = store.delete_video(video_id)
    if v:
        for p in (v["path"], v["thumb"]):
            if p:
                Path(p).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/videos/import")
def import_video(file: UploadFile = File(...)):
    """Thêm video có sẵn (ví dụ tải tay từ Muse) vào thư viện để ghép."""
    dest = CLIPS / f"import_{int(time.time())}_{Path(file.filename).name}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        meta = ffmpeg.probe(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    thumb = ffmpeg.thumbnail(dest, THUMBS / (dest.stem + ".jpg"))
    return {"id": store.add_video(None, str(dest), meta, thumb=str(thumb) if thumb else None)}


@app.post("/api/merge")
def merge(
    ids: str = Form(...), aspect: str = Form("16:9"), xfade: float = Form(0.0),
    keep_audio: bool = Form(True), music_volume: float = Form(0.3),
    name: str = Form(""), music: UploadFile | None = File(None),
):
    vids = store.get_videos(json.loads(ids))
    if len(vids) < 1:
        raise HTTPException(400, "Chọn ít nhất 1 clip")
    MERGED.mkdir(parents=True, exist_ok=True)
    music_path = None
    if music and music.filename:
        music_path = MERGED / f"_music_{int(time.time())}{Path(music.filename).suffix}"
        with music_path.open("wb") as f:
            shutil.copyfileobj(music.file, f)
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_")
    out = MERGED / f"{safe or 'merged'}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    try:
        ffmpeg.merge([Path(v["path"]) for v in vids], out, aspect=aspect, xfade=xfade,
                     music=music_path, music_volume=music_volume, keep_audio=keep_audio)
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if music_path:
            music_path.unlink(missing_ok=True)
    meta = ffmpeg.probe(out)
    thumb = ffmpeg.thumbnail(out, THUMBS / (out.stem + ".jpg"))
    vid = store.add_video(None, str(out), meta, kind="merged", thumb=str(thumb) if thumb else None)
    return _video_out(store.get_videos([vid])[0])


@app.post("/api/open-folder")
def open_folder():
    subprocess.run(["open", str(OUTPUT)])
    return {"ok": True}


# ---------- cài đặt & đăng nhập ----------

@app.post("/api/settings")
def save_settings(values: dict):
    s = store.save_settings(values)
    return s


class AccountIn(BaseModel):
    text: str
    name: str | None = None


def _switch() -> bool | None:
    """Nạp tài khoản đang chọn vào trình duyệt; nếu đang chạy job thì để job sau mới đổi."""
    if worker.busy:
        worker.post("switch_account")
        return None
    return worker.call("switch_account", timeout=120)


@app.get("/api/accounts")
def accounts():
    return auth.list_accounts()


@app.post("/api/accounts")
def add_account(body: AccountIn):
    """Dán cookie JSON để đăng nhập / thêm tài khoản; tài khoản mới được chọn dùng ngay."""
    name = body.name or f"Tài khoản {len(auth.list_accounts()) + 1}"
    try:
        name = auth.save_account(name, body.text)
        auth.activate_account(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"name": name, "logged_in": _switch()}


@app.post("/api/accounts/{name}/activate")
def activate_account(name: str):
    try:
        auth.activate_account(name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"name": name, "logged_in": _switch()}


@app.delete("/api/accounts/{name}")
def delete_account(name: str):
    was_active = auth.active_account() == name
    auth.delete_account(name)
    if was_active:
        _switch()
    return {"ok": True}


def _busy_guard():
    if worker.busy:
        raise HTTPException(409, "Đang chạy job, hãy tạm dừng hàng đợi và chờ job hiện tại xong")


@app.post("/api/login/check")
def login_check():
    _busy_guard()
    return {"logged_in": worker.call("check_login", timeout=90)}


@app.post("/api/login/open")
def login_open():
    _busy_guard()
    worker.post("open_login")
    return {"ok": True}


@app.post("/api/login/done")
def login_done():
    worker.finish_login()
    return {"ok": True}


if __name__ == "__main__":
    worker.start()
    pose_batch.start(f"http://{HOST}:{PORT}/api/mv")
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(f"http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
