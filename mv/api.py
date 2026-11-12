"""API cho dự án nhiều short: MV âm nhạc và người mẫu tạo dáng (giao diện web/mv.js + web/model.js)."""

import shutil
import threading
import time
import traceback
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from jobs import store as jobstore
from mv import store
from mv.pipeline import Runner, project_dir
from post import ffmpeg, lyrics_overlay

TASK_KINDS = {"lyrics", "lyrics_fix", "script", "assets", "asset_image", "plan", "shorts",
              "video_analysis", "model_design", "locations", "model_scripts", "thumbnail", "asset_images", "song_analysis",
              "remake_analysis", "pose_list", "pose_images", "pose_image", "pose_render", "pose_videos",
              "stickerman_script", "stickerman_plan"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def run_local(tid: int) -> None:
    """Tác vụ chạy trên máy (chép lời bằng Whisper) — không chiếm trình duyệt Muse."""
    task = store.get_task(tid)
    store.update_task(tid, status="running")
    try:
        Runner(None, task, lambda: False, 0).run()
        store.update_task(tid, status="done", finished=time.time())
    except Exception as e:
        traceback.print_exc()
        store.update_task(tid, status="failed", error=str(e)[:600], finished=time.time())


def short_versions(pid: int, sid: int) -> list[tuple[int, Path]]:
    """Mọi bản video đã tạo của 1 short (s{id}_v{n}.mp4, bỏ bản _raw chưa chỉnh màu), mới nhất trước."""
    out = []
    for f in (project_dir(pid) / "shorts").glob(f"s{sid}_v*.mp4"):
        n = f.stem.split("_v", 1)[1]
        if n.isdigit():
            out.append((int(n), f))
    return sorted(out, reverse=True)


def make_router(worker, url) -> APIRouter:
    r = APIRouter(prefix="/api/mv")

    def project_out(pid: int) -> dict:
        p = store.get_project(pid)
        if not p:
            raise HTTPException(404, "Không có dự án này")
        p["audio_url"] = url(p["audio_path"])
        p["ref_video_url"] = url(p["ref_video_path"])
        p["scripts"] = store.list_scripts(pid)
        p["exported_url"] = url(p["exported_path"])
        p["beauty_url"] = url((p.get("model_spec") or {}).get("beauty_ref"))
        tdir = project_dir(pid) / "thumbs"
        p["thumbs"] = [url(str(f)) for f in sorted(tdir.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
                       if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")] if tdir.exists() else []
        p["assets"] = [{**a, "image_url": url(a["image_path"]), "orig_url": url(a.get("orig_path")),
                        "ref_urls": [url(f) for f in a.get("refs") or []]} for a in store.list_assets(pid)]
        p["shorts"] = [{**s, "video_url": url(s["video_path"]), "thumb_url": url(s["thumb_path"]),
                        "versions": [{"v": v, "video_url": url(f), "thumb_url": url(f.with_suffix(".jpg")),
                                      "current": str(f) == s["video_path"]} for v, f in short_versions(pid, s["id"])]}
                       for s in store.list_shorts(pid)]
        p["tasks"] = store.list_tasks(pid, 8)
        p["worker_task"] = worker.current_task
        return p

    def queue_task(pid: int, kind: str, args: dict | None = None) -> int:
        if kind not in TASK_KINDS:
            raise HTTPException(400, "Tác vụ không hợp lệ")
        if kind not in ("asset_image", "pose_image") and store.active_task(pid, kind):
            raise HTTPException(409, "Tác vụ này đang chạy hoặc đang chờ")
        return store.add_task(pid, kind, args)

    @r.get("")
    def projects():
        return store.list_projects()

    @r.post("")
    async def create(title: str = Form(""), kind: str = Form("mv"),
                     audio: UploadFile | None = File(None), video: UploadFile | None = File(None)):
        """MV âm nhạc: cần file nhạc. Người mẫu tạo dáng: video mẫu không bắt buộc. Làm lại MV: cần video MV gốc."""
        up, exts, name = (audio, AUDIO_EXT, "song") if kind in ("mv", "stickerman") else (video, VIDEO_EXT, "ref")
        if kind not in ("mv", "model", "remake", "pose", "stickerman", "scriptvideo") or (up is None and kind == "mv"):
            raise HTTPException(400, "Thiếu file nhạc")
        if kind == "remake" and (up is None or not up.filename):
            raise HTTPException(400, "Chọn video MV gốc")
        if up is None or not up.filename:
            if kind in ("stickerman", "scriptvideo"):
                pid = store.add_project(title.strip() or time.strftime("Video kịch bản %d/%m %H:%M"), kind)
                project_dir(pid)
                store.update_project(pid, aspect="9:16", max_short_sec=6, chat_mode="chain", duration=30.0,
                                     style="2D stick figure animation",
                                     model_spec={"style_preset": "stick2d", "genre": "custom_script", "scenes_count": 5})
                return {"id": pid}
            pid = store.add_project(title.strip() or time.strftime(("Tạo dáng " if kind == "pose" else "Người mẫu ") + "%d/%m %H:%M"), kind)
            project_dir(pid)
            store.update_project(pid, aspect="9:16", max_short_sec=6, chat_mode="chain",
                                 style="ảnh/video thời trang chụp thật", model_spec={"source": "new", "pose": "photo"})
            return {"id": pid}
        ext = Path(up.filename or "").suffix.lower()
        if ext not in exts:
            raise HTTPException(400, "Chỉ nhận file nhạc mp3/wav/m4a/aac/flac/ogg" if kind in ("mv", "stickerman")
                                else "Chỉ nhận video mp4/mov/m4v/webm")
        pid = store.add_project(title.strip() or Path(up.filename).stem, kind)
        dest = project_dir(pid) / f"{name}{ext}"
        with dest.open("wb") as f:
            shutil.copyfileobj(up.file, f)
        try:
            if kind == "stickerman":
                store.update_project(pid, audio_path=str(dest), duration=ffmpeg.audio_duration(dest),
                                     aspect="9:16", max_short_sec=6, chat_mode="chain",
                                     style="Sticker 2D viền trắng",
                                     model_spec={"style_preset": "diecut", "genre": "comedy", "scenes_count": 5})
            elif kind == "mv":
                store.update_project(pid, audio_path=str(dest), duration=ffmpeg.audio_duration(dest))
            elif kind == "remake":
                meta = ffmpeg.probe(dest)
                w, h = meta["width"], meta["height"]
                song = ffmpeg.extract_audio(dest, dest.parent / "song.m4a")
                store.update_project(pid, ref_video_path=str(dest), duration=meta["duration"],
                                     audio_path=str(song) if song else None,
                                     aspect="9:16" if h > w * 1.2 else "16:9" if w > h * 1.2 else "1:1",
                                     max_short_sec=6, chat_mode="chain", style="giống hệt video gốc")
            else:
                meta = ffmpeg.probe(dest)
                w, h = meta["width"], meta["height"]
                store.update_project(pid, ref_video_path=str(dest), duration=meta["duration"],
                                     aspect="9:16", max_short_sec=6, chat_mode="chain",
                                     style="clip thời trang đường phố quay bằng điện thoại, ánh sáng tự nhiên",
                                     model_spec={"source": "new", "pose": "photo"})
        except Exception as e:  # không để lại dự án dở dang
            store.delete_project(pid)
            shutil.rmtree(dest.parent, ignore_errors=True)
            if isinstance(e, RuntimeError):
                raise HTTPException(400, str(e))
            raise
        return {"id": pid}

    @r.get("/{pid}")
    def detail(pid: int):
        return project_out(pid)

    @r.post("/{pid}/translate_script")
    def translate_script(pid: int):
        p = store.get_project(pid)
        if not p or not p.get("script"):
            raise HTTPException(400, "Dự án chưa có kịch bản")
        from mv.pipeline import to_en
        en_script = to_en(p["script"])
        store.update_project(pid, script=en_script)
        return {"script": en_script}

    @r.patch("/{pid}")
    def update(pid: int, body: dict):
        try:
            store.update_project(pid, **body)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return project_out(pid)

    @r.delete("/{pid}")
    def delete(pid: int):
        if (t := store.active_task(pid)) and worker.current_task == t["id"]:
            raise HTTPException(409, "Dự án đang chạy tác vụ, hãy huỷ trước")
        store.delete_project(pid)
        shutil.rmtree(project_dir(pid), ignore_errors=True)
        return {"ok": True}

    # ---------- tác vụ Muse ----------

    @r.post("/{pid}/task/{kind}")
    def run_task(pid: int, kind: str, body: dict | None = None):
        p = store.get_project(pid)
        need = {"script": ("lyrics", "Chưa có lời bài hát"), "assets": ("script", "Chưa có kịch bản"),
                "plan": ("script", "Chưa có kịch bản"), "stickerman_plan": ("script", "Chưa có kịch bản")}
        if kind in need and not p.get(need[kind][0]):
            raise HTTPException(400, need[kind][1])
        if kind == "plan" and not p.get("lyrics"):
            raise HTTPException(400, "Chưa có lời bài hát")
        if kind in ("video_analysis", "remake_analysis") and not p.get("ref_video_path"):
            raise HTTPException(400, "Dự án không có video mẫu")
        if kind in ("model_scripts", "locations", "model_design") and p["kind"] not in ("model", "pose"):
            raise HTTPException(400, "Tác vụ không hợp lệ cho loại dự án này")
        if kind == "model_scripts" and not (store.get_asset(p.get("sel_model") or 0) and store.get_asset(p.get("sel_location") or 0)):
            raise HTTPException(400, "Chọn 1 người mẫu và 1 bối cảnh ở bước 2 trước")
        if kind in ("lyrics_fix", "song_analysis") and not p.get("lyrics"):
            raise HTTPException(400, "Chưa có lời bài hát")
        tid = queue_task(pid, kind, body or {})
        if kind in store.LOCAL_KINDS:
            threading.Thread(target=run_local, args=(tid,), daemon=True).start()
        return {"task": tid}

    @r.post("/tasks/{tid}/cancel")
    def cancel_task(tid: int):
        t = store.get_task(tid)
        if t and t["status"] == "queued":
            store.update_task(tid, status="cancelled", finished=time.time())
        worker.cancel_task(tid)
        return {"ok": True}

    # ---------- nhân vật / bối cảnh ----------

    @r.post("/{pid}/assets")
    def add_asset(pid: int, body: dict):
        if body.get("kind") not in ("character", "location", "prop") or not (body.get("name") or "").strip():
            raise HTTPException(400, "Cần loại (nhân vật/bối cảnh) và tên")
        return {"id": store.add_asset(pid, body["kind"], body["name"].strip(), body.get("description", ""))}

    @r.patch("/assets/{aid}")
    def update_asset(aid: int, body: dict):
        try:
            store.update_asset(aid, **{k: v for k, v in body.items() if k in ("name", "description", "locked", "mode")})
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @r.delete("/assets/{aid}")
    def delete_asset(aid: int):
        a = store.get_asset(aid)
        store.delete_asset(aid)
        if a:  # bỏ chọn nếu đang được chọn để viết kịch bản
            p = store.get_project(a["project_id"])
            for f in ("sel_model", "sel_location"):
                if p.get(f) == aid:
                    store.update_project(p["id"], **{f: None})
        return {"ok": True}

    @r.post("/assets/{aid}/image")
    async def import_image(aid: int, file: UploadFile = File(...)):
        a = store.get_asset(aid)
        ext = Path(file.filename or "").suffix.lower()
        if not a or ext not in IMAGE_EXT:
            raise HTTPException(400, "Chỉ nhận ảnh png/jpg/webp")
        dest = project_dir(a["project_id"]) / "assets" / f"a{aid}_{int(time.time())}{ext}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        store.update_asset(aid, image_path=str(dest), source="import")
        return {"ok": True}

    @r.post("/{pid}/beauty_ref")
    async def beauty_ref(pid: int, file: UploadFile = File(...)):
        """Người mẫu: ảnh "chuẩn vẻ đẹp" để Muse thiết kế người mẫu mới theo gu này."""
        p = store.get_project(pid)
        ext = Path(file.filename or "").suffix.lower()
        if not p or ext not in IMAGE_EXT:
            raise HTTPException(400, "Chỉ nhận ảnh png/jpg/webp")
        dest = project_dir(pid) / "assets" / f"beauty_{int(time.time())}{ext}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        store.update_project(pid, model_spec={**(p.get("model_spec") or {}), "beauty_ref": str(dest)})
        return project_out(pid)

    @r.delete("/{pid}/beauty_ref")
    def del_beauty_ref(pid: int):
        p = store.get_project(pid)
        store.update_project(pid, model_spec={k: v for k, v in (p.get("model_spec") or {}).items() if k != "beauty_ref"})
        return project_out(pid)

    @r.post("/assets/{aid}/refs")
    async def add_refs(aid: int, files: list[UploadFile] = File(...)):
        """Làm lại MV: người dùng tải lên ảnh của mình (nhiều góc) để thay nhân vật/bối cảnh/đạo cụ."""
        a = store.get_asset(aid)
        if not a:
            raise HTTPException(404)
        refs = list(a.get("refs") or [])
        for i, f in enumerate(files):
            ext = Path(f.filename or "").suffix.lower()
            if ext not in IMAGE_EXT:
                raise HTTPException(400, "Chỉ nhận ảnh png/jpg/webp")
            dest = project_dir(a["project_id"]) / "assets" / f"r{aid}_{int(time.time() * 1000)}_{i}{ext}"
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            refs.append(str(dest))
        store.update_asset(aid, refs=refs[-8:], mode="replace")
        return {"ok": True}

    @r.delete("/assets/{aid}/refs/{i}")
    def delete_ref(aid: int, i: int):
        a = store.get_asset(aid)
        refs = list((a or {}).get("refs") or [])
        if 0 <= i < len(refs):
            refs.pop(i)
            store.update_asset(aid, refs=refs)
        return {"ok": True}

    @r.post("/assets/{aid}/refs/{i}/main")
    def main_ref(aid: int, i: int):
        """Đặt 1 ảnh làm ảnh mặt chuẩn (đứng đầu danh sách, được gửi kèm ở mọi bước)."""
        a = store.get_asset(aid)
        refs = list((a or {}).get("refs") or [])
        if 0 <= i < len(refs):
            refs.insert(0, refs.pop(i))
            store.update_asset(aid, refs=refs)
        return {"ok": True}

    @r.post("/assets/{aid}/use_ref")
    def use_ref(aid: int, body: dict):
        """Dùng thẳng 1 ảnh đã tải lên làm ảnh thay thế (hợp với bối cảnh/đạo cụ chụp thật)."""
        a = store.get_asset(aid)
        refs = (a or {}).get("refs") or []
        i = int(body.get("i", 0))
        if not 0 <= i < len(refs):
            raise HTTPException(400, "Không có ảnh này")
        store.update_asset(aid, image_path=refs[i], source="import")
        return {"ok": True}

    @r.post("/assets/{aid}/frame")
    def frame_image(aid: int, body: dict):
        """Lấy 1 khung hình của video mẫu (giây `t`) làm ảnh cho mục này."""
        a = store.get_asset(aid)
        p = store.get_project(a["project_id"]) if a else None
        if not p or not p.get("ref_video_path"):
            raise HTTPException(400, "Dự án không có video mẫu")
        dest = project_dir(p["id"]) / "assets" / f"a{aid}_{int(time.time())}.jpg"
        try:
            ffmpeg.frame(Path(p["ref_video_path"]), float(body.get("t", 0)), dest)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        if p["kind"] == "remake":  # làm lại MV: khung hình này là ảnh gốc của mục, ảnh thay thế giữ nguyên
            store.update_asset(aid, orig_path=str(dest))
        else:
            store.update_asset(aid, image_path=str(dest), source="video")
        return {"ok": True}

    @r.post("/{pid}/draw_all")
    def draw_all(pid: int, body: dict):
        """Muse vẽ tất cả nhân vật hoặc tất cả bối cảnh chưa khoá."""
        kind = body.get("kind")
        if kind not in ("character", "location", "prop"):
            raise HTTPException(400, "kind phải là character, location hoặc prop")
        if not any(a["kind"] == kind and not a["locked"] for a in store.list_assets(pid)):
            raise HTTPException(400, "Không có mục nào chưa khoá để vẽ")
        return {"task": queue_task(pid, "asset_images", {"kind": kind})}

    @r.post("/assets/{aid}/generate")
    def generate_image(aid: int, body: dict | None = None):
        a = store.get_asset(aid)
        if not a:
            raise HTTPException(404)
        if a["locked"]:
            raise HTTPException(400, "Mục này đang khoá — mở khoá trước khi tạo lại")
        return {"task": queue_task(a["project_id"], "asset_image",
                                   {"asset_id": aid, "feedback": (body or {}).get("feedback", "")})}

    # ---------- kịch bản (người mẫu) ----------

    @r.patch("/scripts/{script_id}")
    def update_script(script_id: int, body: dict):
        store.update_script(script_id, **body)
        return {"ok": True}

    @r.delete("/scripts/{script_id}")
    def delete_script(script_id: int):
        store.delete_script(script_id)
        return {"ok": True}

    # ---------- short ----------

    @r.put("/{pid}/shorts")
    @r.put("/{pid}/plan")
    @r.post("/{pid}/plan")
    async def save_plan(pid: int, request: Request):
        running = store.active_task(pid, "shorts")
        if running and running.get("status") == "running":
            raise HTTPException(409, "Đang tạo short trên trình duyệt, hãy huỷ trước khi sửa plan")
        try:
            data = await request.json()
        except Exception:
            data = []
        if isinstance(data, dict):
            shorts_list = data.get("shorts", [])
        elif isinstance(data, list):
            shorts_list = data
        else:
            shorts_list = []
        store.replace_shorts(pid, shorts_list)
        return project_out(pid)

    @r.post("/{pid}/generate")
    def generate(pid: int, body: dict | None = None):
        """Đưa các short chưa có video vào hàng đợi; một số loại tạo tuần tự để nối khung hình."""
        p = store.get_project(pid)
        if not p:
            raise HTTPException(404, "Không có dự án này")
        if p["kind"] == "scriptvideo" and not any(a["kind"] == "character" and a["locked"] and a.get("image_path")
                                                    and Path(a["image_path"]).exists() for a in store.list_assets(pid)):
            raise HTTPException(400, "Hãy tạo hoặc import ảnh nhân vật chính rồi khoá ảnh trước khi tạo short")
        ids = set((body or {}).get("ids") or [])
        reset_all = bool((body or {}).get("reset_all"))
        n = 0
        active = store.active_task(pid, "shorts")
        for s in store.list_shorts(pid, (body or {}).get("script_id")):
            should_queue = (s["id"] in ids) if ids else (reset_all or s["status"] in ("pending", "failed") or (not active and s["status"] != "done"))
            if should_queue:
                store.update_short(s["id"], status="queued", retries=0, error=None)
                n += 1
        if not n:
            raise HTTPException(400, "Không còn short nào cần tạo")
        if not active:
            store.add_task(pid, "shorts")
        worker.paused = False
        return {"queued": n}

    @r.patch("/shorts/{sid}")
    def update_short(sid: int, body: dict):
        try:
            store.update_short(sid, **{k: v for k, v in body.items()
                                       if k in ("description", "lipsync", "lyric", "characters", "location", "cont")})
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @r.post("/shorts/{sid}/use")
    def use_version(sid: int, body: dict):
        """Quay lại dùng 1 bản đã tạo trước đó của short (khi bản tạo lại không ưng)."""
        s = store.get_short(sid)
        if not s:
            raise HTTPException(404)
        if s["status"] in ("queued", "running") and store.active_task(s["project_id"], "shorts"):
            raise HTTPException(409, "Short này đang được tạo")
        f = dict(short_versions(s["project_id"], sid)).get(int(body.get("v") or 0))
        if not f:
            raise HTTPException(404, "Không còn file của bản này")
        thumb = f.with_suffix(".jpg")
        store.update_short(sid, status="done", video_path=str(f), error=None,
                           thumb_path=str(thumb) if thumb.exists() else None)
        return {"ok": True}

    @r.post("/shorts/{sid}/regen")
    def regen(sid: int, body: dict):
        s = store.get_short(sid)
        if not s:
            raise HTTPException(404)
        if s["status"] in ("queued", "running") and store.active_task(s["project_id"], "shorts"):
            raise HTTPException(409, "Short này đang được tạo")
        store.update_short(sid, status="queued", retries=0, error=None,
                           feedback=(body.get("feedback") or "").strip(), lyric_mode="quote",
                           **{k: body[k] for k in ("description", "lipsync") if k in body})
        if body.get("with_next"):  # các short nối cảnh phía sau phải quay lại từ khung cuối mới
            rest = [x for x in store.list_shorts(s["project_id"], s.get("script_id")) if x["idx"] > s["idx"]]
            for x in rest:
                if not x.get("cont") or x["status"] in ("queued", "running"):
                    break
                store.update_short(x["id"], status="queued", retries=0, error=None, feedback="", lyric_mode="quote")
        if not store.active_task(s["project_id"], "shorts"):
            store.add_task(s["project_id"], "shorts")
        worker.paused = False
        return {"ok": True}

    # ---------- video hướng dẫn tạo dáng ----------

    @r.put("/{pid}/poses")
    def save_poses(pid: int, body: dict):
        """Lưu danh sách pose người dùng sửa (giữ ảnh đã vẽ của pose còn nguyên mô tả)."""
        old = {s["id"]: s for s in store.list_shorts(pid)}
        poses = []
        for x in body.get("poses") or []:
            o = old.get(x.get("id"))
            keep = o and o["description"] == x.get("description") and o.get("thumb_path")
            poses.append({"name": x.get("name", ""), "description": x.get("description", ""),
                          "thumb_path": o["thumb_path"] if keep else None})
        store.set_poses(pid, poses)
        return project_out(pid)

    @r.post("/shorts/{sid}/pose_regen")
    def pose_regen(sid: int, body: dict | None = None):
        s = store.get_short(sid)
        if not s:
            raise HTTPException(404)
        store.update_short(sid, status="queued")
        return {"task": queue_task(s["project_id"], "pose_image", {"short_id": sid, "feedback": (body or {}).get("feedback", "")})}

    @r.post("/{pid}/music")
    async def upload_music(pid: int, file: UploadFile = File(...)):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in AUDIO_EXT | VIDEO_EXT:
            raise HTTPException(400, "Chỉ nhận file nhạc mp3/wav/m4a/aac (hoặc video có tiếng)")
        dest = project_dir(pid) / f"music_{int(time.time())}{ext}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        store.update_project(pid, audio_path=str(dest))
        return project_out(pid)

    @r.delete("/{pid}/music")
    def delete_music(pid: int):
        store.update_project(pid, audio_path=None)
        return project_out(pid)

    # ---------- xuất MV ----------

    @r.post("/{pid}/export")
    async def export(pid: int, script_id: int | None = Form(None), music: UploadFile | None = File(None)):
        """MV: ghép mọi short + nhạc gốc. Người mẫu: ghép short của 1 kịch bản, nhạc nền tuỳ chọn."""
        p = store.get_project(pid)
        shorts = store.list_shorts(pid, script_id)
        if not shorts or not any(s["video_path"] for s in shorts):
            raise HTTPException(400, "Chưa có short nào có video")
        segs = [{"path": s["video_path"] if s["video_path"] and Path(s["video_path"]).exists() else None,
                 "duration": s["end"] - s["start"]} for s in shorts]
        audio = Path(p["audio_path"]) if p["kind"] in ("mv", "remake", "stickerman") and p.get("audio_path") else None
        if music and music.filename:
            audio = project_dir(pid) / "tmp" / ("music" + Path(music.filename).suffix.lower())
            with audio.open("wb") as f:
                shutil.copyfileobj(music.file, f)
        tag = f"{p['kind']}{pid}" if p["kind"] in ("mv", "remake", "stickerman", "scriptvideo") else f"model{pid}_kb{script_id or 'all'}"
        out = jobstore.DB_PATH.parent / "output" / "merged" / f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        ly = None
        if (p["kind"] == "mv" and p.get("show_lyrics") and p.get("lyrics")) or (p["kind"] == "stickerman" and p.get("show_lyrics")):
            w, h = ffmpeg.ASPECTS.get(p["aspect"], ffmpeg.ASPECTS["9:16" if p["kind"] == "stickerman" else "16:9"])
            sub_lines = []
            if p["kind"] == "stickerman":
                for s in shorts:
                    if s.get("lyric"):
                        sub_lines.append({"start": s["start"], "end": s["end"], "text": s["lyric"]})
            else:
                sub_lines = p.get("lyrics") or []
            if sub_lines:
                ly = lyrics_overlay.build(sub_lines, sum(s["duration"] for s in segs), (w, h), project_dir(pid) / "tmp" / "lyrics")
        try:
            # video theo kịch bản: giữ âm thanh Muse tạo trong từng short (trước đây xuất ra bản im lặng)
            ffmpeg.export_mv(segs, audio, out, p["aspect"], ly, clip_audio=(p["kind"] == "scriptvideo" and not audio))
            meta = ffmpeg.probe(out)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        thumb = ffmpeg.thumbnail(out, out.parent.parent / "thumbs" / (out.stem + ".jpg"))
        jobstore.add_video(None, str(out), meta, kind="merged", thumb=str(thumb) if thumb else None)
        store.update_project(pid, exported_path=str(out))
        return {"url": url(str(out)), "missing": sum(1 for s in segs if not s["path"])}

    return r
