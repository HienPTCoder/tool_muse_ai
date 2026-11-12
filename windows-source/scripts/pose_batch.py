"""Chạy hàng loạt "Video hướng dẫn tạo dáng" theo kế hoạch JSON (output/plans/pose_ads_10.json), qua API của tool.

Các giai đoạn (mỗi giai đoạn chỉ xếp việc vào hàng đợi Muse, xem kết quả trên giao diện hoặc bằng `status`):
  create  — tạo dự án, Muse thiết kế người mẫu (2 phương án) + vẽ bối cảnh
  poses   — Muse đề xuất 5 pose + vẽ ảnh (dáng sai + 5 pose) cho dự án đã có người mẫu & bối cảnh
  videos  — Muse tạo video chuyển động cho từng pose
  render  — dựng video trên máy (lần lượt từng dự án)
  status  — tình trạng từng dự án
Chạy: .venv/bin/python scripts/pose_batch.py <giai đoạn> [plan.json]
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8765/api/mv"
ROOT = Path(__file__).resolve().parent.parent


def call(method: str, url: str, body: dict | None = None, form: dict | None = None):
    if form is not None:
        boundary = "----posebatch"
        data = "".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
                       for k, v in form.items()) + f"--{boundary}--\r\n"
        req = urllib.request.Request(API + url, data=data.encode(), method=method,
                                     headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(API + url, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:300]}


def load(plan: Path) -> tuple[list[dict], dict, Path]:
    state_file = plan.with_suffix(".state.json")
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    return json.loads(plan.read_text()), state, state_file


def spec(e: dict) -> dict:
    keys = ("gender", "region", "age", "aesthetic", "hair", "makeup", "body", "sexy", "style", "notes")
    return {"source": "new", **{k: e.get(k, "") for k in keys}}


def create(plan: list[dict], state: dict) -> None:
    for i, e in enumerate(plan):
        if str(i) in state:
            continue
        pid = call("POST", "", form={"kind": "pose", "title": e["title"]})["id"]
        call("PATCH", f"/{pid}", {"model_spec": {**spec(e), "pose": "photo"}})
        print(e["title"], "->", call("POST", f"/{pid}/task/model_design", {**spec(e), "outfit": "", "variants": 2}))
        loc = call("POST", f"/{pid}/assets", {"kind": "location", **e["location"]})["id"]
        call("PATCH", f"/{pid}", {"sel_location": loc})
        call("POST", f"/assets/{loc}/generate", {})
        state[str(i)] = pid


def poses(plan: list[dict], state: dict) -> None:
    for i, e in enumerate(plan):
        pid = state.get(str(i))
        p = pid and call("GET", f"/{pid}")
        if not p:
            continue
        ok = all(a["image_url"] for a in p["assets"] if a["id"] in (p["sel_model"], p["sel_location"]))
        if not (p["sel_model"] and p["sel_location"] and ok):
            print(e["title"], ": chưa có người mẫu/bối cảnh có ảnh — bỏ qua")
            continue
        if not p["shorts"]:
            print(e["title"], call("POST", f"/{pid}/task/pose_list", {"count": 5, "notes": e.get("pose_notes", "")}))
        print(e["title"], call("POST", f"/{pid}/task/pose_images", {}))


def videos(plan: list[dict], state: dict) -> None:
    for i, e in enumerate(plan):
        pid = state.get(str(i))
        if pid:
            print(e["title"], call("POST", f"/{pid}/task/pose_videos", {}))


def render(plan: list[dict], state: dict) -> None:
    for i, e in enumerate(plan):
        pid = state.get(str(i))
        if not pid:
            continue
        p = call("GET", f"/{pid}")
        if not p["shorts"] or not all(s["thumb_url"] for s in p["shorts"]):
            print(e["title"], ": còn pose chưa có ảnh — bỏ qua")
            continue
        r = call("POST", f"/{pid}/task/pose_render", {"music": p.get("audio_path") or "", "style": e.get("render", "classic")})
        tid = r.get("task")
        while tid:
            t = next(t for t in call("GET", f"/{pid}")["tasks"] if t["id"] == tid)
            if t["status"] in ("done", "failed", "cancelled"):
                print(e["title"], t["status"], t.get("error") or "", call("GET", f"/{pid}")["exported_path"])
                break
            time.sleep(5)


def status(plan: list[dict], state: dict) -> None:
    for i, e in enumerate(plan):
        pid = state.get(str(i))
        if not pid:
            print(f"{i + 1:2}. {e['title']}: chưa tạo")
            continue
        p = call("GET", f"/{pid}")
        chars = [a for a in p["assets"] if a["kind"] == "character"]
        loc = next((a for a in p["assets"] if a["id"] == p["sel_location"]), None)
        rows = p["shorts"]
        busy = [t["kind"] for t in p["tasks"] if t["status"] in ("queued", "running")]
        failed = [f"{t['kind']}: {(t.get('error') or '')[:80]}" for t in p["tasks"][:3] if t["status"] == "failed"]
        print(f"{i + 1:2}. #{pid} {e['title']}: người mẫu {sum(bool(a['image_url']) for a in chars)}/{len(chars)} ảnh"
              f" (chọn {p['sel_model']}), bối cảnh {'có ảnh' if loc and loc['image_url'] else 'chưa'},"
              f" pose {max(0, len(rows) - 1)} · ảnh {sum(bool(s['thumb_url']) for s in rows)}/{len(rows)}"
              f" · video {sum(bool(s['video_url']) for s in rows[1:])}/{max(0, len(rows) - 1)}"
              f" · xuất {'✓' if p['exported_url'] else '—'}"
              + (f" · đang chạy: {', '.join(busy)}" if busy else "") + (f" · LỖI {failed}" if failed else ""))


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "status"
    plan, state, state_file = load(Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "output" / "plans" / "pose_ads_10.json")
    {"create": create, "poses": poses, "videos": videos, "render": render, "status": status}[stage](plan, state)
    state_file.write_text(json.dumps(state, indent=1))
