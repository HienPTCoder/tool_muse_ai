"""Gộp prompt của nhiều short thành MỘT prompt gửi vào MỘT khung chat Muse.

Điểm quan trọng: ảnh tham chiếu nhân vật/bối cảnh của MỌI short được gộp (loại trùng, đổi tên khi trùng tên
khác nội dung) và prompt có khối KHOÁ THAM CHIẾU bắt buộc, để mọi short đều đúng nhân vật + bối cảnh đã cho.
"""

import hashlib
import math
import re

MAX_ATTACHMENTS = 10
MAX_BYTES = int(7.5 * 1024 * 1024)  # dữ liệu base64 ~ 4/3 kích thước thật, giữ dưới giới hạn đính kèm
_DROP_LINE = re.compile(r"\s*Output only 1 video file\.?", re.I)


def _priority(name: str) -> int:
    n = re.sub(r"^s\d+_", "", name.lower())
    if n.startswith(("character", "anh_nhan_vat", "model")):
        return 0  # nhân vật: giữ cuối cùng
    if n.startswith(("location", "anh_boi_canh")):
        return 1  # bối cảnh
    if n.startswith(("anh_san_pham", "product")):
        return 2
    if n.startswith(("first_frame", "khung_dau")):
        return 3
    return 4  # style_ref và các ảnh phụ: bỏ trước


def merge_attachments(items: list[tuple[str, list[dict]]]) -> tuple[list[tuple[str, list[str]]], list[dict], list[str]]:
    """items: [(prompt, atts)]. Trả (prompt đã đổi tên ảnh, danh sách ảnh gộp, nhật ký cảnh báo)."""
    notes, by_hash, used_names, merged = [], {}, {}, []
    out_prompts = []
    for i, (text, atts) in enumerate(items, 1):
        for att in atts:
            digest = hashlib.sha1(att["dataBase64"].encode()).hexdigest()
            if digest in by_hash:
                new = by_hash[digest]
            else:
                name = att["filename"]
                new = name
                if used_names.get(name) not in (None, digest):
                    stem, dot, ext = name.rpartition(".")
                    new = f"s{i}_{stem}.{ext}" if dot else f"s{i}_{name}"
                by_hash[digest] = new
                used_names[new] = digest
                merged.append({**att, "filename": new})
            if new != att["filename"]:
                text = re.sub(re.escape(att["filename"]), new, text)
        out_prompts.append(text)

    # vượt giới hạn: bỏ ảnh phụ (style/khung đầu) trước, không bao giờ bỏ nhân vật/bối cảnh trước
    def size(lst):
        return sum(len(a["dataBase64"]) for a in lst)
    while merged and (len(merged) > MAX_ATTACHMENTS or size(merged) > MAX_BYTES):
        victim = max(range(len(merged)), key=lambda k: (_priority(merged[k]["filename"]), k))
        if _priority(merged[victim]["filename"]) <= 1:
            notes.append("Ảnh tham chiếu nhân vật/bối cảnh vượt giới hạn dung lượng — giữ nguyên, có thể bị Muse từ chối")
            break
        notes.append(f"Bỏ ảnh phụ {merged[victim]['filename']} để không vượt giới hạn đính kèm")
        merged.pop(victim)
    return out_prompts, merged, notes


def build_en(shorts: list[dict], max_sec: int, merge_final: bool = False) -> tuple[str, list[dict], list[str]]:
    """shorts: [{prompt, atts, duration}]. Trả (prompt tổng, ảnh đính kèm, cảnh báo)."""
    n = len(shorts)
    texts, atts, notes = merge_attachments([(s["prompt"], s["atts"]) for s in shorts])
    refs = [a["filename"] for a in atts if _priority(a["filename"]) <= 2]
    head = [
        f"Work ONLY in this chat. Create {n} separate video{'s' if n > 1 else ''}, in strict order SHORT 1 to SHORT {n}.",
        f"- Every short is AT MOST {max_sec} seconds (each short states its own duration — obey it).",
        "- REFERENCE LOCK (MANDATORY): all attached reference images are the ONLY valid designs for the characters and "
        "locations" + (f" ({', '.join(refs)})" if refs else "") + ". EVERY short must show exactly these characters and these "
        "locations — same face, hairstyle, skin tone, body build, outfit, colours, art style and the same place design. "
        "Never redesign, swap, age, restyle or invent a different person/place. When a short names an attached file, use that exact file.",
        "- FRAME-CHAINING (MANDATORY): make the shorts ONE AFTER ANOTHER, never all at once. Before starting short k (k>=2), take the LAST FRAME "
        "of the video you just made for short k-1 and analyse it (exact people, pose, hand/prop positions, product state, camera framing, "
        "lighting, location). Use that frame as the FIRST FRAME / visual reference of short k: open on that exact state, then perform only the next "
        "step of the script. Never restart, never rewind, never jump in time or place, so the shorts cut together seamlessly.",
        f"- Deliver exactly {n} video file{'s' if n > 1 else ''}, one per short, in order. Never skip a short, never put two shorts "
        "in one file, never reply with text only, never ask questions.",
    ]
    if merge_final and n > 1:
        head.append(f"- AFTER all {n} shorts exist, also MERGE them in order into ONE final clip (about "
                    f"{int(sum(s['duration'] for s in shorts))} seconds): straight cuts, nothing added or removed, keep the sound. "
                    "Deliver the merged clip as the LAST file.")
    body = []
    for i, (s, text) in enumerate(zip(shorts, texts), 1):
        text = _DROP_LINE.sub("", text).strip()
        body.append(f"=== SHORT {i}/{n} — {math.ceil(s['duration'])} seconds ===\n{text}")
    return "\n".join(head) + "\n\n" + "\n\n".join(body), atts, notes


def build_vi(scene_prompts: list[str], max_sec: int = 10, total_sec: int | None = None) -> str:
    """Bản tiếng Việt cho video affiliate: các cảnh trong 1 chat rồi gộp thành 1 clip."""
    n = len(scene_prompts)
    total = total_sec or n * max_sec
    head = [
        f"Làm việc CHỈ trong khung chat này theo 2 bước.",
        f"BƯỚC 1 — Tạo {n} short riêng, đúng thứ tự SHORT 1 → SHORT {n}. Mỗi short TỐI ĐA {max_sec} giây (không dài hơn).",
        "KHOÁ THAM CHIẾU (BẮT BUỘC): mọi ảnh đính kèm (sản phẩm, nhân vật, bối cảnh) là thiết kế DUY NHẤT hợp lệ. "
        "Mọi short phải dùng đúng sản phẩm, đúng người dẫn và đúng bối cảnh trong ảnh: giữ nguyên hình dáng, màu, nhãn, bao bì, "
        "khuôn mặt, trang phục, phong cách hình. Không thiết kế lại, không thay bằng món/nhân vật/bối cảnh khác.",
        "NỐI KHUNG HÌNH CUỐI (BẮT BUỘC): tạo các short LẦN LƯỢT từng cái, không làm cùng lúc. Trước khi làm short k (k ≥ 2), lấy KHUNG HÌNH CUỐI "
        "của video short k-1 vừa tạo và phân tích (người, tư thế, vị trí tay/đạo cụ, trạng thái sản phẩm, góc máy, ánh sáng, bối cảnh). "
        "Dùng khung đó làm KHUNG ĐẦU / ảnh tham chiếu của short k: mở đúng trạng thái đó rồi chỉ làm bước tiếp theo trong kịch bản. "
        "Không bắt đầu lại, không tua lại, không nhảy thời gian/địa điểm để các short ghép liền mạch, đồng nhất.",
        f"BƯỚC 2 — Khi đủ {n} short, GỘP đúng thứ tự thành MỘT clip duy nhất dài khoảng {total} giây "
        f"(tối đa {max(60, total)} giây): cắt thẳng, không thêm/bớt cảnh, giữ nguyên âm thanh.",
        f"KẾT QUẢ: trả về {n} file video short riêng theo thứ tự, rồi clip đã gộp là file CUỐI CÙNG. "
        "Không hỏi lại, không chỉ trả lời bằng chữ, không bỏ short nào.",
    ]
    body = [f"=== SHORT {i}/{n} (tối đa {max_sec}s) ===\n{p.strip()}" for i, p in enumerate(scene_prompts, 1)]
    return "\n".join(head) + "\n\n" + "\n\n".join(body)
