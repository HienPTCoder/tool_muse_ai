"""Giai đoạn 0: ghi lại network request của muse.ai khi tạo video bằng tay.

Cách dùng:
    python3 recorder.py [url]

Một cửa sổ Chrome sẽ mở ra. Đăng nhập (chỉ cần lần đầu, session được lưu
trong ./browser_profile), tạo thử 1 video, chờ xong rồi tải về. Sau đó quay
lại terminal và nhấn Enter để dừng ghi.

Kết quả: ./capture/requests.jsonl (cookie/token đã được che, có thể gửi cho
người khác xem).
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / "browser_profile"
OUT_DIR = ROOT / "capture"
DEFAULT_URL = "https://muse.ai/thread/ddfa204d-e7b1-4876-92dd-ceed4512ca6b"

SKIP_TYPES = {"image", "stylesheet", "font", "media"}
SENSITIVE_HEADERS = {"cookie", "set-cookie", "authorization", "x-csrf-token", "x-api-key"}
MAX_BODY = 4000


def redact(headers: dict) -> dict:
    return {
        k: ("<redacted>" if k.lower() in SENSITIVE_HEADERS else v)
        for k, v in headers.items()
    }


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    OUT_DIR.mkdir(exist_ok=True)
    out = (OUT_DIR / "requests.jsonl").open("a", encoding="utf-8")

    def log(entry: dict) -> None:
        entry["ts"] = time.time()
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")
        out.flush()

    def on_response(resp) -> None:
        req = resp.request
        if req.resource_type in SKIP_TYPES or req.resource_type == "script":
            return
        body = None
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype or "text" in ctype:
            try:
                body = resp.text()[:MAX_BODY]
            except Exception:
                body = "<unreadable>"
        log({
            "kind": "http",
            "method": req.method,
            "url": req.url,
            "type": req.resource_type,
            "req_headers": redact(req.headers),
            "req_body": (req.post_data or "")[:MAX_BODY],
            "status": resp.status,
            "resp_type": ctype,
            "resp_body": body,
        })
        print(f"{req.method:6} {resp.status} {req.url[:120]}")

    def on_websocket(ws) -> None:
        print(f"WS     open {ws.url}")
        log({"kind": "ws_open", "url": ws.url})
        ws.on("framesent", lambda p: log({"kind": "ws_send", "url": ws.url, "data": str(p)[:MAX_BODY]}))
        ws.on("framereceived", lambda p: log({"kind": "ws_recv", "url": ws.url, "data": str(p)[:MAX_BODY]}))

    def on_download(dl) -> None:
        print(f"DOWNLOAD {dl.url}")
        log({"kind": "download", "url": dl.url, "filename": dl.suggested_filename})

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, channel="chrome", accept_downloads=True
        )
        ctx.on("response", on_response)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("websocket", on_websocket)
        page.on("download", on_download)
        page.goto(url)

        input("\n>>> Đăng nhập và tạo thử 1 video, xong thì nhấn Enter để dừng...\n")
        ctx.close()

    out.close()
    print(f"\nĐã lưu: {OUT_DIR / 'requests.jsonl'}")


if __name__ == "__main__":
    main()
