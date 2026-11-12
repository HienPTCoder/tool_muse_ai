"""Điều khiển chat Muse bằng Playwright: gửi prompt, chờ trả lời, lấy video về.

Chỉ dùng từ một thread duy nhất (Playwright sync API không thread-safe).
"""

import base64
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Page, sync_playwright

from muse.auth import COOKIES_FILE, load_cookies

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "browser_profile"
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")
MAX_ATTACH = 8 * 1024 * 1024  # Muse giới hạn tổng file đính kèm ~8MB
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}


class Cancelled(Exception):
    pass


class NotLoggedIn(Exception):
    pass


# Cách chính: gọi thẳng các hàm nội bộ của trang muse.ai (bộ gửi tin trong cây React
# và runtime gateway), giống ~/ai-video-studio/extension/page.js. Mỗi job 1 chat mới,
# theo dõi bằng sessions.list, lấy kết quả bằng chat.history, tải file bằng fs.raw.
RUNTIME_JS = r"""() => {
  if (window.__mvs) return true;
  const CHUNK = 2 * 1024 * 1024;
  const runtime = () => window.__hatchEarlyGatewayRuntimeState?.activeRuntime?.getSnapshot();
  const client = () => {
    if (!document.body) return null;
    let root;
    for (const el of [document.body, ...document.querySelectorAll('body *')].slice(0, 80)) {
      const k = Object.keys(el).find(k => k.startsWith('__reactContainer') || k.startsWith('__reactFiber'));
      if (k) { root = el[k]; break; }
    }
    if (!root) return null;
    if (root.stateNode?.current) root = root.stateNode.current;
    for (const stack = [root]; stack.length;) {
      const f = stack.pop();
      const v = f.memoizedProps?.value;
      if (v && typeof v.sendMessage === 'function' && typeof v.ensureActiveChatSendReady === 'function') return v;
      if (f.sibling) stack.push(f.sibling);
      if (f.child) stack.push(f.child);
    }
    return null;
  };
  const blobs = new Map();
  let seq = 0;
  window.__mvs = {
    ready: () => Boolean(client() && runtime()),
    async send(text, atts, sid) {
      let c = client();
      for (let i = 0; !c && i < 20; i++) { await new Promise(r => setTimeout(r, 1000)); c = client(); }
      if (!c) return {ok: false, reason: 'Trang muse.ai chưa sẵn sàng'};
      // sid có sẵn -> gửi tiếp vào chat đó; không có -> mở chat mới
      const opts = sid ? {targetRoute: {kind: 'thread', sessionId: sid}, waitForReadiness: true}
                       : {createNewThread: true, waitForReadiness: true};
      const r = await c.sendMessage(text, atts || [], opts);
      return {ok: Boolean(r?.ok), sessionId: r?.sessionId || '', reason: r?.reason || r?.error || ''};
    },
    async status(sid) {
      const {sessions = []} = await runtime().sendRequest('sessions.list', {});
      return sessions.find(s => s.session_id === sid)?.status || null;
    },
    async result(sid, lastTurn) {
      const h = await runtime().sendRequest('chat.history', {session_id: sid, limit: 50});
      const text = [], files = [];
      let events = h.chat_events || [];
      if (lastTurn) {  // chỉ lấy phần trả lời sau tin nhắn cuối cùng của mình (chat dùng chung nhiều short)
        let i = events.length - 1;
        while (i >= 0 && events[i].role !== 'user') i--;
        events = events.slice(i + 1);
      }
      for (const e of events) {
        if (e.role !== 'assistant') continue;
        const body = e.display_text ?? e.text ?? e.content ?? e.payload?.display_text ??
          e.payload?.text ?? e.payload?.data?.text ?? e.payload?.data?.content;
        if (typeof body === 'string' && body.trim()) text.push(body);
        else if (Array.isArray(body)) {
          const parts = body.map(part => typeof part === 'string' ? part : part?.text || part?.content || '').filter(Boolean);
          if (parts.length) text.push(parts.join('\n'));
        }
        for (const m of [...(e.payload?.data?.videos || []), ...(e.payload?.data?.images || [])]) {
          if (!m.missing) files.push({path: m.path, mime: m.mime, size: m.byte_len});
        }
      }
      return {text: text.join('\n\n'), files};
    },
    async open(p) {
      const r = await runtime().sendRequest('fs.raw', {path: p.replace(/^sandbox:\/\//, '')});
      blobs.set(++seq, r instanceof Blob ? r : r.data);
      return seq;
    },
    async slice(id, i) {
      const u8 = new Uint8Array(await blobs.get(id).slice(i * CHUNK, (i + 1) * CHUNK).arrayBuffer());
      let s = '';
      for (let k = 0; k < u8.length; k += 32768) s += String.fromCharCode.apply(null, u8.subarray(k, k + 32768));
      return btoa(s);
    },
    drop(id) { blobs.delete(id); },
    async cancel(sid) { await runtime().sendRequest('chat.cancel', {session_id: sid}); },
  };
  return true;
}"""
CHUNK = 2 * 1024 * 1024
GRACE_POLLS = 3   # phiên xong, đã có chữ nhưng chưa có file -> đọc lại 3 nhịp (~12s)
EMPTY_POLLS = 8   # phiên xong mà chưa có gì -> đọc lại 8 nhịp (~32s)
NEVER_RAN_S = 300  # phiên không bao giờ chạy và im lặng -> bỏ sau 5 phút, không chờ hết giờ


# Chat Muse chỉ giữ một số tin gần nhất trong DOM (tin cũ bị gỡ khi có tin mới), nên
# không thể đếm số tin. Thay vào đó, trước khi gửi ta đánh dấu mọi tin/media đang có;
# sau đó chỉ tính những gì CHƯA đánh dấu và nằm sau tin đã đánh dấu cuối cùng.
_FIND_JS = r"""
  const root = document.querySelector('[aria-label="Chat messages"]') || document.body;
  const bodies = [...document.querySelectorAll('[data-hatch-assistant-message-body]')];
  const media = [];
  for (const v of root.querySelectorAll('video')) {
    if (v.closest('[data-hatch-media-owner]') || v.getAttribute('data-hatch-media-owner')) continue;
    if (v.closest('[data-hatch-avatar-stage],[data-hatch-status-panel-surface]')) continue;
    const src = v.currentSrc || v.src || (v.querySelector('source') || {}).src;
    if (src) media.push([v, {kind: 'video', src, key: 'v:' + src}]);
  }
  for (const c of root.querySelectorAll('[data-testid^="hatch-chat-file-card-"]')) {
    const id = c.getAttribute('data-testid');
    let path = '';
    try { path = decodeURIComponent(id.slice(21).replace(/(..)/g, '%$1')); } catch (e) {}
    media.push([c, {kind: 'card', testid: id, path, key: 'c:' + id}]);
  }
  for (const a of root.querySelectorAll('a[href]')) {
    const h = a.href.split('?')[0].toLowerCase();
    if (/\.(mp4|mov|webm|m4v)$/.test(h)) media.push([a, {kind: 'link', src: a.href, key: 'a:' + a.href}]);
  }
"""

MARK_JS = "() => {" + _FIND_JS + r"""
  for (const el of [...bodies, ...media.map(m => m[0])]) el.setAttribute('data-mvs-seen', '1');
  return bodies.length;
}"""

SNAPSHOT_JS = "() => {" + _FIND_JS + r"""
  const seen = bodies.filter(b => b.hasAttribute('data-mvs-seen'));
  const anchor = seen[seen.length - 1];
  const after = (el) => !anchor || (anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const fresh = bodies.filter(b => !b.hasAttribute('data-mvs-seen') && after(b));
  return {
    url: location.href,
    n_new: fresh.length,
    streaming: document.querySelectorAll('[data-hatch-markdown-streaming="true"]').length,
    busy: root.querySelectorAll('[aria-busy="true"]').length,
    text: fresh.map(b => b.innerText.trim()).join('\n\n'),
    media: media.filter(([el]) => !el.hasAttribute('data-mvs-seen') && after(el)).map(m => m[1]),
  };
}"""

FETCH_B64_JS = r"""async (src) => {
  const r = await fetch(src);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const blob = await r.blob();
  return await new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result.split(',')[1]);
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(blob);
  });
}"""


class MuseBrowser:
    def __init__(self, headless: bool = True, log: Callable[[str], None] = print):
        self.headless = headless
        self.log = log
        self._pw = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None

    # ---------- vòng đời ----------

    def start(self, reset_cookies: bool = False) -> None:
        """reset_cookies: xoá phiên cũ trong profile (khi đổi tài khoản) trước khi nạp cookie mới."""
        if self.ctx:
            return
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", headless=self.headless,
            viewport={"width": 1440, "height": 900}, accept_downloads=True,
        )
        if reset_cookies:
            self.ctx.clear_cookies()
        if COOKIES_FILE.exists():
            self.ctx.add_cookies(load_cookies())
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def close(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._pw = self.ctx = self.page = None

    @property
    def running(self) -> bool:
        return self.ctx is not None

    @property
    def alive(self) -> bool:
        """Trình duyệt còn dùng được (cửa sổ Chrome chưa bị đóng)."""
        try:
            return bool(self.ctx and self.page and not self.page.is_closed())
        except Exception:
            return False

    def recover(self) -> bool:
        """Tab chat bị đóng nhưng Chrome còn sống -> mở lại tab, khỏi phải bật cửa sổ Chrome mới.
        False = trình duyệt hỏng thật, phải khởi động lại."""
        try:
            if not self.ctx:
                return False
            if self.page and not self.page.is_closed():
                return True
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
            return not self.page.is_closed()
        except Exception:
            return False

    # ---------- điều hướng ----------

    def open(self, url: str) -> None:
        self.start()
        if self.page.url.rstrip("/") != url.rstrip("/"):
            self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.locator('textarea[aria-label="Message"]').first.wait_for(state="visible", timeout=30000)
        except Exception:
            raise NotLoggedIn(f"Không thấy khung chat ở {self.page.url} — có thể chưa đăng nhập hoặc cookie hết hạn")
        self.page.wait_for_timeout(2500)  # chờ lịch sử chat tải xong

    def check_login(self, url: str = "https://muse.ai/") -> bool:
        try:
            self.open(url)
            return True
        except NotLoggedIn:
            return False

    def screenshot(self, path: Path) -> None:
        if self.page:
            self.page.screenshot(path=str(path))

    # ---------- chat mới qua runtime nội bộ (cách chính) ----------

    def _mvs(self, fn: str, *args):
        for _ in range(10):
            try:
                self.page.evaluate(RUNTIME_JS)
                return self.page.evaluate(
                    "([fn, args]) => window.__mvs[fn](...args)", [fn, list(args)])
            except Exception as e:
                err = str(e)
                if "Execution context was destroyed" in err or "navigation" in err or "Cannot find context" in err:
                    self.page.wait_for_timeout(1000)
                    continue
                raise
        # Thử lần cuối nếu vẫn lỗi
        self.page.evaluate(RUNTIME_JS)
        return self.page.evaluate("([fn, args]) => window.__mvs[fn](...args)", [fn, list(args)])

    @staticmethod
    def attachment(path: Path, name: str | None = None) -> dict:
        """File đính kèm cho sendMessage của Muse (ảnh tham chiếu, đoạn nhạc). Tổng tối đa ~8MB."""
        mime = MIME.get(path.suffix.lower(), "application/octet-stream")
        return {"filename": name or path.name, "mimeType": mime,
                "dataBase64": base64.b64encode(path.read_bytes()).decode(),
                "category": "audio" if mime.startswith("audio/") else "image"}

    def start_thread(self, text: str, atts: list[dict] | None = None, session_id: str | None = None) -> str:
        """Gửi tin vào chat `session_id` (hoặc 1 chat mới nếu không có), trả về session id (không chờ trả lời)."""
        if not self.page or "muse.ai" not in self.page.url:
            self.open("https://muse.ai/")
        for _ in range(20):
            if self._mvs("ready"):
                break
            self.page.wait_for_timeout(1000)
        try:
            self.page.screenshot(path="/Users/user/muse-video-tool/output/debug/current_page.png")
            print(f"[DEBUG BROWSER] url={self.page.url} title={self.page.title()} ready={self._mvs('ready')}", flush=True)
        except Exception as e:
            print(f"[DEBUG BROWSER] err={e}", flush=True)
        size = sum(len(a["dataBase64"]) * 3 // 4 for a in atts or [])
        if size > MAX_ATTACH:
            raise RuntimeError(f"File đính kèm {size / 1048576:.1f}MB vượt giới hạn ~8MB của Muse")
        sent = self._mvs("send", text, atts or [], session_id)
        if not sent.get("ok") or not sent.get("sessionId"):
            raise RuntimeError(f"muse.ai không nhận yêu cầu: {sent.get('reason') or 'không rõ lý do'}")
        return sent["sessionId"]

    def wait_threads(self, sids: list[str], timeout_s: float, on_progress: Callable[[str], None],
                     should_cancel: Callable[[], bool], label: str = "làm", last_turn: bool = False,
                     wait_for_files: bool = True) -> dict[str, dict]:
        """Chờ nhiều chat chạy song song tới khi xong; trả về {sid: {text, files, session_id}}.
        last_turn: chỉ lấy câu trả lời cho tin nhắn vừa gửi (khi gửi tiếp vào chat cũ)."""
        t0, last_log = time.time(), 0.0
        seen, done, errors, empty = set(), {}, 0, {}
        text_candidates: dict[str, tuple[str, int]] = {}
        while len(done) < len(sids):
            if should_cancel():
                for sid in sids:
                    try:
                        self._mvs("cancel", sid)
                    except Exception:
                        pass
                raise Cancelled()
            self.page.wait_for_timeout(4000)
            elapsed = time.time() - t0
            for sid in sids:
                if sid in done:
                    continue
                try:
                    st = self._mvs("status", sid)
                    errors = 0
                except Exception:
                    errors += 1
                    if errors >= 5:
                        raise
                    continue
                if st == "running":
                    seen.add(sid)
                    empty.pop(sid, None)
                    if not wait_for_files:
                        # Muse có thể để phiên ở trạng thái running ngay cả khi câu trả lời
                        # văn bản đã hiện trong lịch sử. Đọc lịch sử cả khi đang chạy và chờ
                        # nội dung ổn định vài nhịp để không trả về câu trả lời còn dang dở.
                        try:
                            live = self._mvs("result", sid, last_turn)
                        except Exception:
                            continue
                        text = (live.get("text") or "").strip()
                        if text:
                            previous, stable = text_candidates.get(sid, ("", 0))
                            stable = stable + 1 if previous == text else 1
                            text_candidates[sid] = (text, stable)
                            if stable >= 3:
                                live["session_id"] = sid
                                done[sid] = live
                        continue
                    continue
                if sid not in seen and elapsed <= 30:
                    continue  # phiên vừa gửi, chưa kịp chuyển sang "running"
                try:
                    res = self._mvs("result", sid, last_turn)
                except Exception:
                    continue
                # Phân tích và viết kịch bản chỉ cần văn bản. Không đợi các nhịp dự phòng
                # dành cho file video/ảnh vốn không được tạo trong các yêu cầu này.
                if not wait_for_files and res["text"]:
                    res["session_id"] = sid
                    done[sid] = res
                    continue
                if not res["files"]:
                    # Muse đánh dấu phiên xong trước khi file video xuất hiện trong lịch sử chat,
                    # nên chờ thêm vài nhịp rồi đọc lại thay vì kết luận "không có video".
                    n = empty[sid] = empty.get(sid, 0) + 1
                    if sid not in seen:
                        # chưa bao giờ thấy phiên "running": chỉ kết luận khi Muse đã trả lời bằng chữ
                        if (not res["text"] or n < EMPTY_POLLS * 2) and elapsed < NEVER_RAN_S:
                            continue  # quá lâu mà phiên vẫn im lặng -> coi như không có video, bên gọi gửi lại
                    elif n < (GRACE_POLLS if res["text"] else EMPTY_POLLS):
                        continue
                res["session_id"] = sid
                done[sid] = res
            if elapsed > timeout_s:
                # hết giờ: huỷ phần còn lại và trả về kết quả rỗng cho từng phiên,
                # để bên gọi tự xử lý (gửi lại short đó) thay vì hỏng cả lượt
                for sid in set(sids) - set(done):
                    try:
                        self._mvs("cancel", sid)
                    except Exception:
                        pass
                    try:
                        res = self._mvs("result", sid, last_turn)
                    except Exception:
                        res = {"text": "", "files": []}
                    if not res["files"]:
                        res["text"] = (res["text"] or "") + \
                            f"\n(Quá {int(timeout_s // 60)} phút Muse chưa làm xong)"
                    res["session_id"] = sid
                    done[sid] = res
                on_progress(f"Quá {int(timeout_s // 60)} phút Muse chưa làm xong — bỏ qua phiên còn lại")
                break
            if elapsed - last_log >= 60:
                extra = f" ({len(done)}/{len(sids)} xong)" if len(sids) > 1 else ""
                on_progress(f"Muse đang {label}… {int(elapsed)}s{extra}")
                last_log = elapsed
        return done

    def generate_new_thread(self, prompt: str, timeout_s: float, on_progress: Callable[[str], None],
                            should_cancel: Callable[[], bool], atts: list[dict] | None = None,
                            label: str = "tạo video") -> dict:
        """Gửi prompt vào 1 chat mới, chờ phiên chạy xong, trả về {text, files, session_id}."""
        sid = self.start_thread(prompt, atts)
        on_progress(f"Đã tạo chat mới (phiên {sid[:8]}…)")
        return self.wait_threads([sid], timeout_s, on_progress, should_cancel, label)[sid]

    def download_runtime_file(self, f: dict, dest: Path) -> Path:
        fid = self._mvs("open", f["path"])
        parts = []
        try:
            for i in range((f["size"] + CHUNK - 1) // CHUNK):
                parts.append(base64.b64decode(self._mvs("slice", fid, i)))
        finally:
            try:
                self._mvs("drop", fid)
            except Exception:
                pass
        data = b"".join(parts)
        if len(data) != f["size"]:
            raise RuntimeError(f"Tải file lỗi ({len(data)}/{f['size']} byte)")
        dest.write_bytes(data)
        return dest

    # ---------- chat có sẵn qua giao diện (dùng khi gửi vào 1 thread cụ thể) ----------

    def snapshot(self) -> dict:
        return self.page.evaluate(SNAPSHOT_JS)

    def send(self, prompt: str) -> None:
        """Đánh dấu các tin hiện có rồi gửi prompt."""
        self.page.evaluate(MARK_JS)
        box = self.page.locator('textarea[aria-label="Message"]').first
        box.click()
        box.fill(prompt)
        self.page.wait_for_timeout(400)
        box.press("Enter")
        # xác nhận đã gửi: khung nhập được xoá trống
        for _ in range(20):
            self.page.wait_for_timeout(500)
            if not box.input_value().strip():
                return
        send_btn = self.page.locator('button[aria-label="Send"]').first
        if send_btn.is_visible():
            send_btn.click()
            self.page.wait_for_timeout(1500)
            if not box.input_value().strip():
                return
        raise RuntimeError("Không gửi được tin nhắn (khung nhập vẫn còn chữ)")

    def wait_reply(self, timeout_s: float, grace_s: float,
                   on_progress: Callable[[str], None], should_cancel: Callable[[], bool]) -> dict:
        """Chờ Muse trả lời xong. Xong khi: có video và im lặng 15s, hoặc im lặng `grace_s` giây."""
        t0 = last_change = time.time()
        sig, last_text = None, ""
        while True:
            if should_cancel():
                raise Cancelled()
            self.page.wait_for_timeout(3000)
            snap = self.snapshot()
            videos = [m for m in snap["media"] if self._is_video(m)]
            new_sig = (snap["n_new"], len(snap["text"]), len(snap["media"]), snap["streaming"], snap["busy"])
            now = time.time()
            if new_sig != sig:
                sig, last_change = new_sig, now
                if snap["text"] and snap["text"] != last_text and not snap["streaming"]:
                    on_progress(snap["text"][len(last_text):].strip()[:500] or snap["text"][-500:])
                    last_text = snap["text"]
            replied = snap["n_new"] > 0 or videos
            idle = not snap["streaming"] and not snap["busy"]
            quiet = now - last_change
            if replied and idle and videos and quiet >= 15:
                break
            if replied and idle and quiet >= grace_s:
                break
            if now - t0 > timeout_s:
                on_progress("Hết thời gian chờ, lấy những gì đã có")
                snap["timeout"] = True
                break
        snap["videos"] = [m for m in snap["media"] if self._is_video(m)]
        return snap

    @staticmethod
    def _is_video(m: dict) -> bool:
        if m["kind"] in ("video", "link"):
            return True
        return m["kind"] == "card" and m.get("path", "").lower().endswith(VIDEO_EXT)

    # ---------- tải video ----------

    def download(self, media: dict, dest: Path) -> Path:
        if media["kind"] in ("video", "link"):
            return self._fetch_to(media["src"], dest)
        return self._download_card(media, dest)

    def _fetch_to(self, src: str, dest: Path) -> Path:
        data = base64.b64decode(self.page.evaluate(FETCH_B64_JS, src))
        if len(data) < 1024:
            raise RuntimeError(f"File tải về quá nhỏ ({len(data)} byte)")
        dest.write_bytes(data)
        return dest

    def _download_card(self, media: dict, dest: Path) -> Path:
        card = self.page.locator(f'[data-testid="{media["testid"]}"]').last
        card.scroll_into_view_if_needed()
        before = set(self.page.evaluate(
            "() => [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src)"))
        try:
            with self.page.expect_download(timeout=15000) as dl:
                card.click()
            dl.value.save_as(str(dest))
            return dest
        except Exception:
            pass
        # Không có sự kiện download: thẻ mở trình xem -> lấy <video> mới xuất hiện
        for _ in range(10):
            srcs = self.page.evaluate(
                "() => [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src).filter(Boolean)")
            new = [s for s in srcs if s not in before]
            if new:
                try:
                    return self._fetch_to(new[-1], dest)
                finally:
                    self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(1000)
        self.page.keyboard.press("Escape")
        raise RuntimeError(f"Không lấy được video từ thẻ file {media.get('path')}")
