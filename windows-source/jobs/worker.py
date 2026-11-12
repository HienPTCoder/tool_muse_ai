"""Thread nền chạy hàng đợi: mỗi lần 1 job, sở hữu duy nhất trình duyệt Playwright."""

import queue
import json
import re
import base64
import ipaddress
import threading
import time
import traceback
from concurrent.futures import Future
from pathlib import Path
from urllib.parse import urlparse

from jobs import store
from muse import auth
from mv import store as mvstore
from muse.browser import Cancelled, MuseBrowser, NotLoggedIn
from post import ffmpeg
from jobs import product_fetch

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CLIPS = OUTPUT / "clips"
THUMBS = OUTPUT / "thumbs"
DEBUG = OUTPUT / "debug"
NEW_CHAT = "new"  # target: mỗi job 1 chat mới trên Muse

# Câu trả lời của Muse khi công cụ tạo video bên trong bị lỗi (500/502...)
_SERVICE_ERR = re.compile(
    r"\b(500|502|503|504)\b|lỗi (nội bộ|từ phía máy chủ|máy chủ|hệ thống)|sự cố|"
    r"server error|internal error|service (is )?unavailable|temporarily unavailable",
    re.IGNORECASE,
)


# Hết lượt tạo video của tài khoản (429). KHÁC hẳn từ chối nội dung: gửi lại hay "bản an toàn hơn"
# đều vô ích, chỉ tốn lượt. Phải chờ hạn mức mở lại.
_QUOTA_ERR = re.compile(
    r"\b429\b|24[- ]hour video limit|daily (video )?limit|video limit|quota|rate.?limit|"
    r"out of (credits|generations)|hết lượt|hết hạn mức",
    re.IGNORECASE,
)


# Muse chặn hẳn khả năng tạo video của tài khoản theo quốc gia/khu vực. Muse nói rõ đây KHÔNG phải
# sự cố tạm thời, nên chờ cũng vô ích — khác cả từ chối nội dung lẫn hết lượt 24h. Phải đổi tài khoản
# hoặc đổi vùng rồi mới chạy lại được.
_BLOCKED_ERR = re.compile(
    r"(video generation|video).{0,40}(is|isn't|is not|not) (available|supported).{0,40}"
    r"(country|region)|in its country or region|not available in your (country|region)|"
    r"lasting restriction|permanent(ly)? (restricted|blocked)|"
    r"video is still unavailable for (this|your) account|"
    r"video generation is still blocked",
    re.IGNORECASE,
)


def is_service_error(text: str | None) -> bool:
    return bool(text and _SERVICE_ERR.search(text))


def is_blocked_error(text: str | None) -> bool:
    """Muse chặn tạo video với tài khoản này theo quốc gia/khu vực — chờ không hết."""
    return bool(text and _BLOCKED_ERR.search(text))


def is_quota_error(text: str | None) -> bool:
    """Muse báo tài khoản hết lượt tạo video trong 24 giờ."""
    return bool(text and _QUOTA_ERR.search(text))


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="muse-worker")
        self.paused = False
        self.current_job: int | None = None
        self.current_task: int | None = None  # tác vụ MV đang chạy
        self.phase = "idle"   # idle|starting|sending|waiting|downloading|login
        self.logged_in: bool | None = None
        self.last_error: str | None = None
        self.cooldown_until = 0.0  # Muse lỗi máy chủ: không gửi job nào trước thời điểm này
        self._cancel = threading.Event()
        self._login_done = threading.Event()
        self._cmds: "queue.Queue[tuple]" = queue.Queue()
        self._browser: MuseBrowser | None = None
        for d in (CLIPS, THUMBS, DEBUG):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- API cho server (gọi từ thread khác) ----------

    def state(self) -> dict:
        return {"paused": self.paused, "current_job": self.current_job, "current_task": self.current_task,
                "phase": self.phase,
                "logged_in": self.logged_in, "browser": bool(self._browser and self._browser.running),
                "last_error": self.last_error,
                "cooldown_until": self.cooldown_until if self.cooldown_until > time.time() else None}

    def cancel(self, job_id: int) -> None:
        if self.current_job == job_id:
            self._cancel.set()

    def cancel_task(self, task_id: int) -> None:
        if self.current_task == task_id:
            self._cancel.set()

    @property
    def busy(self) -> bool:
        return self.current_job is not None or self.current_task is not None or self.phase == "analyzing"

    def call(self, fn_name: str, *args, timeout: float = 120):
        """Chạy 1 lệnh trong thread worker (giữa các job) và chờ kết quả."""
        fut: Future = Future()
        self._cmds.put((fn_name, args, fut))
        return fut.result(timeout=timeout)

    def clear_cooldown(self) -> None:
        self.cooldown_until = 0.0

    def post(self, fn_name: str, *args) -> None:
        """Như call() nhưng không chờ kết quả."""
        self._cmds.put((fn_name, args, Future()))

    def finish_login(self) -> None:
        self._login_done.set()

    # ---------- lệnh ----------

    def _cmd_check_login(self):
        b = self._get_browser()
        t = store.get_settings()["target_url"]
        self.logged_in = b.check_login(t if t.startswith("http") else "https://muse.ai/")
        return self.logged_in

    def _cmd_muse_text(self, prompt: str, atts: list[dict] | None = None):
        """Gửi yêu cầu chỉ lấy văn bản vào Muse; lệnh chạy trong thread sở hữu Playwright."""
        b = self._get_browser()
        self.phase = "analyzing"
        try:
            sid = b.start_thread(prompt, atts=atts or [])
            settings = store.get_settings()
            result = b.wait_threads(
                [sid], timeout_s=max(60, int(settings["reply_timeout_min"]) * 60),
                on_progress=lambda _text: None, should_cancel=lambda: False,
                label="phân tích và viết kịch bản", wait_for_files=False,
            )[sid]
            self.logged_in = True
            return result.get("text", "")
        finally:
            self.phase = "idle"

    def _cmd_muse_text_batch(self, prompts: list[str], atts: list[dict] | None = None,
                             attachments_per_prompt: list[list[dict]] | None = None):
        """Mở một chat Muse riêng cho từng yêu cầu, gửi tất cả trước rồi đợi câu trả lời song song."""
        b = self._get_browser()
        self.phase = "analyzing"
        try:
            common = atts or []
            per_prompt = attachments_per_prompt or [[] for _ in prompts]
            sids, results_by_index = {}, [""] * len(prompts)
            for i, prompt in enumerate(prompts):
                try:
                    sid = b.start_thread(prompt, atts=common + (per_prompt[i] if i < len(per_prompt) else []))
                    sids[sid] = i
                except Exception as e:
                    results_by_index[i] = f"Không gửi được yêu cầu vào chat riêng: {str(e)[:250]}"
            settings = store.get_settings()
            if sids:
                try:
                    results = b.wait_threads(
                        list(sids), timeout_s=max(60, int(settings["reply_timeout_min"]) * 60),
                        on_progress=lambda _text: None, should_cancel=lambda: False,
                        label="phân tích các sản phẩm song song", wait_for_files=False,
                    )
                    for sid, res in results.items():
                        results_by_index[sids[sid]] = res.get("text", "") or ""
                except Exception as e:
                    for i in sids.values():
                        if not results_by_index[i]:
                            results_by_index[i] = f"Muse không trả lời được chat này: {str(e)[:250]}"
            self.logged_in = True
            return results_by_index
        finally:
            self.phase = "idle"

    def _cmd_product_images(self, urls: list[str]):
        """Mở từng link trong tab phụ: trích thông tin trang + tải ảnh sản phẩm thật (không dùng ảnh AI)."""
        b = self._get_browser()
        self.phase = "analyzing"
        results = []
        page = b.ctx.new_page()
        try:
            for index, raw_url in enumerate(urls, 1):
                try:
                    results.append(product_fetch.scrape_product(
                        b.ctx, page, raw_url, index, OUTPUT / "tmp" / "product_images", ffmpeg.small_jpeg))
                except Exception as exc:
                    results.append({"url": str(raw_url), "error": str(exc)[:200]})
                    if page.is_closed():
                        page = b.ctx.new_page()
        finally:
            try:
                page.close()
            except Exception:
                pass
            self.phase = "idle"
        return results

    def _finish_single_chat(self, jid: int, saved: list[int], scene_count: int, log) -> list[int]:
        """Job 1 chat/nhiều short: đảm bảo có đúng 1 clip gộp. Muse đã gộp (file dài ≈ tổng các short) thì gắn nhãn
        'merged'; chưa thì tool tự ghép các short theo thứ tự bằng ffmpeg."""
        vids = store.get_videos(saved)
        if not vids:
            return saved
        durations = [float(v.get("duration") or 0) for v in vids]
        longest = max(range(len(vids)), key=lambda k: durations[k])
        others = sum(d for k, d in enumerate(durations) if k != longest)
        if len(vids) == 1:
            if scene_count > 1 and durations[0] >= 0.7 * scene_count * 10:
                store.update_video(vids[0]["id"], kind="merged")
                log("Muse đã trả sẵn 1 clip gộp")
            return saved
        if others > 0 and durations[longest] >= 0.8 * others:
            store.update_video(vids[longest]["id"], kind="merged")
            log(f"Muse đã tự gộp các short thành 1 clip ({durations[longest]:.1f}s)")
            return saved
        clips = [Path(v["path"]) for v in vids]
        w, h = vids[0].get("width") or 0, vids[0].get("height") or 0
        aspect = "9:16" if h > w else "1:1" if h == w else "16:9"
        out = OUTPUT / "merged" / f"job{jid:04d}_gop_{int(time.time())}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            ffmpeg.merge(clips, out, aspect=aspect)
            meta = ffmpeg.probe(out)
            thumb = ffmpeg.thumbnail(out, THUMBS / (out.stem + ".jpg"))
            vid = store.add_video(jid, str(out), meta, kind="merged", thumb=str(thumb) if thumb else None)
            log(f"Muse chưa tự gộp — tool đã ghép {len(clips)} short thành 1 clip ({meta['duration']:.1f}s)")
            return saved + [vid]
        except Exception as e:
            log(f"Ghép clip lỗi: {e}")
            return saved

    def _cmd_restart_browser(self):
        self._close_browser()
        return True

    def _cmd_switch_account(self):
        """Đổi tài khoản: xoá phiên cũ trong profile, nạp cookie của tài khoản mới rồi kiểm tra."""
        self._close_browser()
        self.logged_in = None
        self.phase = "starting"
        self._browser = MuseBrowser(headless=store.get_settings()["headless"])
        try:
            self._browser.start(reset_cookies=True)
        finally:
            self.phase = "idle"
        return self._cmd_check_login()

    def _cmd_open_login(self):
        """Mở cửa sổ Chrome thật để người dùng tự đăng nhập; session lưu vào browser_profile.
        Kết thúc khi người dùng bấm "Xong" trong tool hoặc tự đóng cửa sổ Chrome."""
        self._close_browser()
        self.phase = "login"
        self._login_done.clear()
        b = MuseBrowser(headless=False, log=print)
        try:
            b.start()
            b.page.goto("https://muse.ai/")
            deadline = time.time() + 1800
            while not self._login_done.is_set() and time.time() < deadline:
                if b.page.is_closed() or not b.ctx.pages:
                    break
                b.page.wait_for_timeout(1000)
        except Exception:
            pass  # người dùng đóng cửa sổ giữa chừng
        try:
            # lưu phiên vừa đăng nhập thành tài khoản, để lần sau không bị cookie cũ ghi đè
            auth.save_playwright_cookies("Đăng nhập Chrome", b.ctx.cookies(["https://muse.ai"]))
        except Exception:
            pass
        finally:
            try:
                b.close()
            except Exception:
                pass
            self.phase = "idle"
        return self._cmd_check_login()

    # ---------- vòng lặp ----------

    def run(self) -> None:
        while True:
            try:
                fn_name, args, fut = self._cmds.get_nowait()
            except queue.Empty:
                fn_name = None
            if fn_name:
                try:
                    fut.set_result(getattr(self, f"_cmd_{fn_name}")(*args))
                except Exception as e:
                    self.last_error = str(e)
                    fut.set_exception(e)
                continue

            task = None if self.paused else mvstore.next_task()
            if task:
                self._run_mv_task(task)
                continue

            job = None if self.paused or time.time() < self.cooldown_until else store.next_queued()
            if not job:
                time.sleep(1)
                continue
            self._run_job(job)
            delay = store.get_settings()["delay_between_jobs_sec"]
            for _ in range(int(delay)):
                if not self._cmds.empty() or not store.next_queued() or mvstore.next_task():
                    break
                time.sleep(1)

    def _safe(self, fn):
        try:
            return fn()
        except Exception as e:
            self.last_error = str(e)
            traceback.print_exc()

    def _get_browser(self) -> MuseBrowser:
        headless = store.get_settings()["headless"]
        if self._browser and self._browser.headless != headless:
            self._close_browser()
        if self._browser and not self._browser.recover():
            self._close_browser()  # cửa sổ Chrome đã bị đóng hẳn
        if not self._browser:
            self.phase = "starting"
            self._browser = MuseBrowser(headless=headless)
            self._browser.start()
            self.phase = "idle"
        return self._browser

    def _close_browser_if_dead(self) -> None:
        """Chỉ tắt Chrome khi nó thật sự hỏng. Muse từ chối / không trả video là lỗi nội dung,
        giữ nguyên cửa sổ đang đăng nhập thay vì bật cửa sổ mới cho lần sau."""
        if not self._browser or not self._browser.recover():
            self._close_browser()

    def _close_browser(self) -> None:
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

    # ---------- chạy 1 job ----------

    def _run_job(self, job: dict) -> None:
        jid = job["id"]
        self.current_job = jid
        self._cancel.clear()
        settings = store.get_settings()
        log = lambda s: store.append_log(jid, s)
        store.update_job(jid, status="running", started=time.time(), error=None)
        target = job["target_url"] or settings["target_url"]
        sequence = store.get_sequence(job["sequence_id"]) if job.get("sequence_id") else None
        prompt = job["prompt"].strip()
        if settings["prompt_suffix"].strip():
            prompt += "\n\n" + settings["prompt_suffix"].strip()

        try:
            b = self._get_browser()
            saved, service_error = [], False
            attempts = job["attempts"]
            base_prompt = prompt
            for attempt in range(int(settings["auto_retry"]) + 1):
                prompt = base_prompt
                attempts += 1
                store.update_job(jid, attempts=attempts)
                self.phase = "sending"
                retry_note = f" (lần thử {attempt + 1})" if attempt else ""
                if sequence:
                    prior_sid = sequence.get("session_id") if sequence.get("continuity", 1) else None
                    ref_atts = []
                    try:
                        product_refs = json.loads(sequence.get("reference_images") or "[]")
                    except (TypeError, json.JSONDecodeError):
                        product_refs = []
                    for index, image_path in enumerate(product_refs, 1):
                        image_file = Path(image_path)
                        if image_file.is_file():
                            ref_atts.append(MuseBrowser.attachment(image_file, f"anh_san_pham_{index}{image_file.suffix}"))
                    if ref_atts:
                        prompt += ("\n\nẢNH THAM CHIẾU ĐÍNH KÈM: đây là ảnh thật lấy từ link hoặc do người dùng cung cấp. "
                                   "Nếu ảnh có sản phẩm quảng cáo, hãy dùng đúng sản phẩm đó và giữ nguyên hình dáng, màu, nhãn, bao bì; không thay bằng món tương tự "
                                   "hoặc tự sửa logo/chữ. Nếu ảnh là nguyên liệu hay dụng cụ, giữ đúng vật thể nhìn thấy và chỉ dùng khi phù hợp cảnh.")
                        log(f"Đính kèm {len(ref_atts)} ảnh tham chiếu sản phẩm")
                    if sequence.get("continuity", 1) and int(job.get("sequence_order") or 1) > 1:
                        prior_jobs = store.list_sequence_jobs(sequence["id"])
                        previous = next((j for j in prior_jobs if int(j.get("sequence_order") or 0) == int(job["sequence_order"]) - 1), None)
                        prior_videos = store.list_videos(previous["id"]) if previous else []
                        if prior_videos:
                            frame = OUTPUT / "tmp" / f"sequence{sequence['id']}_scene{job['sequence_order'] - 1}_last.jpg"
                            frame.parent.mkdir(parents=True, exist_ok=True)
                            extracted = ffmpeg.last_frame(Path(prior_videos[0]["path"]), frame)
                            if extracted:
                                ref_atts.append(MuseBrowser.attachment(extracted, "khung_cuoi_canh_truoc.jpg"))
                                log("Đã lấy khung hình cuối short trước làm ảnh tham chiếu")
                                prompt += ("\n\nTIẾP DIỄN TỪ ẢNH THAM CHIẾU ĐÍNH KÈM: đây là khung hình cuối của short ngay trước. "
                                           "Dựa vào ảnh để xác định chính xác người, sản phẩm, vị trí tay/đạo cụ, bối cảnh, ánh sáng và trạng thái hành động hiện tại. "
                                           "Mở cảnh mới từ trạng thái đó, rồi phát triển bước tiếp theo theo kịch bản; không lặp lại, không tua lại, không đổi nhân vật/sản phẩm/bối cảnh.")
                            else:
                                log("Không trích được khung hình cuối cảnh trước; tiếp tục bằng ngữ cảnh chat Muse")
                    log((f"Gửi cảnh tiếp theo vào chat chung ({sequence['title']})" if prior_sid
                         else f"Mở chat mới cho chuỗi cảnh: {sequence['title']}") + retry_note)
                    self.phase = "waiting"
                    sid = b.start_thread(prompt, atts=ref_atts, session_id=prior_sid)
                    store.update_sequence(sequence["id"], session_id=sid)
                    sequence["session_id"] = sid
                    single = bool(sequence.get("single_chat"))
                    scene_count = max(1, prompt.count("=== SHORT ")) if single else 1
                    res = b.wait_threads(
                        [sid], timeout_s=settings["reply_timeout_min"] * 60 * (max(1, (scene_count + 1) // 2) if single else 1),
                        on_progress=log, should_cancel=self._cancel.is_set,
                        label="tạo video", last_turn=bool(prior_sid),
                    )[sid]
                    self.logged_in = True
                    snap = {"text": res["text"]}
                    if res["text"]:
                        log(f"Muse: {res['text'][:500]}")
                    store.update_job(jid, reply=res["text"])
                    self.phase = "downloading"
                    saved = self._save_runtime_files(jid, b, res["files"], log)
                    if single and saved:
                        saved = self._finish_single_chat(jid, saved, scene_count, log)
                elif target == NEW_CHAT:
                    log("Gửi prompt vào 1 chat mới trên Muse" + retry_note)
                    self.phase = "waiting"
                    res = b.generate_new_thread(
                        prompt,
                        timeout_s=settings["reply_timeout_min"] * 60,
                        on_progress=log,
                        should_cancel=self._cancel.is_set,
                    )
                    self.logged_in = True
                    snap = {"text": res["text"]}
                    if res["text"]:
                        log(f"Muse: {res['text'][:500]}")
                    store.update_job(jid, reply=res["text"])
                    self.phase = "downloading"
                    saved = self._save_runtime_files(jid, b, res["files"], log)
                else:
                    log(f"Mở {target}" + retry_note)
                    b.open(target)
                    self.logged_in = True
                    b.send(prompt)
                    log("Đã gửi prompt, đang chờ Muse tạo video…")
                    self.phase = "waiting"
                    snap = b.wait_reply(
                        timeout_s=settings["reply_timeout_min"] * 60,
                        grace_s=settings["idle_grace_sec"],
                        on_progress=lambda t: log(f"Muse: {t}"),
                        should_cancel=self._cancel.is_set,
                    )
                    store.update_job(jid, reply=snap["text"])
                    self.phase = "downloading"
                    saved = self._save_videos(jid, b, snap["videos"], log)
                if saved:
                    break
                dbg = DEBUG / f"job{jid}_try{attempts}"
                dbg.mkdir(parents=True, exist_ok=True)
                b.screenshot(dbg / "screen.png")
                (dbg / "reply.txt").write_text(snap["text"] or "")
                store.update_job(jid, debug_dir=str(dbg))
                log("Không tìm thấy video trong câu trả lời")
                if is_service_error(snap["text"]):
                    service_error = True
                    break  # Muse đang lỗi: gửi lại ngay chỉ tốn lượt, chuyển sang hẹn giờ
                if attempt < int(settings["auto_retry"]):
                    log("Chờ 60 giây rồi gửi lại…")
                    for _ in range(60):
                        if self._cancel.is_set():
                            raise Cancelled()
                        time.sleep(1)

            n = job["service_retries"] + 1
            if not saved and service_error and n <= int(settings["service_retry_max"]):
                wait_min = min(settings["service_retry_wait_min"] * 2 ** (n - 1), 60)
                retry_at = time.time() + wait_min * 60
                self.cooldown_until = retry_at  # các job khác cũng chờ, tránh tốn lượt
                store.update_job(jid, status="waiting", service_retries=n, retry_at=retry_at)
                log(f"Muse đang lỗi máy chủ — tự thử lại lúc {time.strftime('%H:%M', time.localtime(retry_at))} "
                    f"(lần hẹn {n}/{settings['service_retry_max']})")
                return
            store.update_job(jid, status="done" if saved else "no_video", finished=time.time(), retry_at=None)
            log(f"Hoàn tất: {len(saved)} video" if saved else "Kết thúc: Muse không trả về video")
        except Cancelled:
            store.update_job(jid, status="cancelled", finished=time.time())
            log("Đã huỷ")
        except NotLoggedIn as e:
            self.logged_in = False
            store.update_job(jid, status="failed", error=str(e), finished=time.time())
            log(f"Lỗi đăng nhập: {e}")
            self.paused = True  # không chạy tiếp các job khác khi chưa đăng nhập
        except Exception as e:
            traceback.print_exc()
            store.update_job(jid, status="failed", error=str(e)[:500], finished=time.time())
            log(f"Lỗi: {e}")
            self._close_browser_if_dead()
        finally:
            self.current_job = None
            self.phase = "idle"

    # ---------- tác vụ MV ----------

    def _run_mv_task(self, task: dict) -> None:
        from mv.pipeline import Runner  # import muộn: pipeline dùng lại is_service_error ở file này
        tid = task["id"]
        self.current_task = tid
        self._cancel.clear()
        self.phase = "mv"
        mvstore.update_task(tid, status="running", error=None)
        try:
            b = self._get_browser()
            self.phase = "mv"
            Runner(b, task, self._cancel.is_set, store.get_settings()["reply_timeout_min"]).run()
            self.logged_in = True
            rem = any(s["status"] == "queued" for s in mvstore.list_shorts(task["project_id"]))
            if task["kind"] in ("shorts", "pose_videos") and rem:
                mvstore.update_task(tid, status="queued")
            else:
                mvstore.update_task(tid, status="done", finished=time.time())
        except Cancelled:
            mvstore.update_task(tid, status="cancelled", finished=time.time())
            mvstore.task_log(tid, "Đã huỷ")
            if task["kind"] == "shorts":
                for s in mvstore.list_shorts(task["project_id"]):
                    if s["status"] in ("queued", "running"):
                        mvstore.update_short(s["id"], status="pending")
        except NotLoggedIn as e:
            self.logged_in = False
            mvstore.update_task(tid, status="failed", error=str(e), finished=time.time())
            self.paused = True
            if task["kind"] == "shorts":
                for s in mvstore.list_shorts(task["project_id"]):
                    if s["status"] in ("queued", "running"):
                        mvstore.update_short(s["id"], status="pending")
        except Exception as e:
            traceback.print_exc()
            mvstore.update_task(tid, status="failed", error=str(e)[:600], finished=time.time())
            mvstore.task_log(tid, f"Lỗi: {e}")
            if task["kind"] == "shorts":
                for s in mvstore.list_shorts(task["project_id"]):
                    if s["status"] in ("queued", "running"):
                        mvstore.update_short(s["id"], status="failed", error=str(e)[:200])
            self._close_browser_if_dead()
        finally:
            self.current_task = None
            self.phase = "idle"

    def _save_runtime_files(self, jid: int, b: MuseBrowser, files: list[dict], log) -> list[int]:
        saved = []
        videos = [f for f in files if (f.get("mime") or "").startswith("video/")]
        if files and not videos:
            log(f"Muse trả về {len(files)} file nhưng không có video ({', '.join(f.get('mime') or '?' for f in files)})")
        for i, f in enumerate(videos, 1):
            ext = (f["mime"].split("/")[1] or "mp4").replace("quicktime", "mov")
            dest = CLIPS / f"job{jid:04d}_{int(time.time())}_{i}.{ext}"
            try:
                b.download_runtime_file(f, dest)
                meta = ffmpeg.probe(dest)
                thumb = ffmpeg.thumbnail(dest, THUMBS / (dest.stem + ".jpg"))
                saved.append(store.add_video(jid, str(dest), meta, thumb=str(thumb) if thumb else None))
                log(f"Đã tải {dest.name} ({meta['duration']:.1f}s, {meta['width']}x{meta['height']})")
            except Exception as e:
                dest.unlink(missing_ok=True)
                log(f"Tải video {i} lỗi: {e}")
        return saved

    def _save_videos(self, jid: int, b: MuseBrowser, videos: list[dict], log) -> list[int]:
        saved, seen = [], set()
        for i, m in enumerate(videos, 1):
            if m["key"] in seen:
                continue
            seen.add(m["key"])
            dest = CLIPS / f"job{jid:04d}_{int(time.time())}_{i}.mp4"
            try:
                b.download(m, dest)
                meta = ffmpeg.probe(dest)
                thumb = ffmpeg.thumbnail(dest, THUMBS / (dest.stem + ".jpg"))
                vid = store.add_video(jid, str(dest), meta, thumb=str(thumb) if thumb else None)
                saved.append(vid)
                log(f"Đã tải {dest.name} ({meta['duration']:.1f}s, {meta['width']}x{meta['height']})")
            except Exception as e:
                dest.unlink(missing_ok=True)
                log(f"Tải video {i} lỗi: {e}")
        return saved
