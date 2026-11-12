"""Lời bài hát chạy dưới video kiểu karaoke: cả câu hiện trước, từng chữ đổi màu và nảy nhẹ đúng lúc được hát.
ffmpeg trên máy không có drawtext/libass nên vẽ bằng Pillow ra dãy ảnh PNG trong suốt (1 ảnh cho mỗi trạng thái chữ),
rồi ghép thành lớp phủ qua concat demuxer + overlay."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"  # có đủ dấu tiếng Việt
SUNG = (255, 216, 77, 255)     # chữ đã hát: vàng
TODO = (255, 255, 255, 235)    # chữ chưa hát: trắng
STROKE = (0, 0, 0, 255)
LEAD, TAIL = 0.25, 0.35        # hiện câu sớm hơn / giữ lại sau khi hát xong (giây)


def word_times(line: dict) -> list[tuple[str, float]]:
    """Mốc bắt đầu từng chữ: chia thời lượng câu theo độ dài chữ (lời đã qua Muse sửa nên không khớp mốc chữ của Whisper)."""
    words = line["text"].split()
    if not words:
        return []
    span = max(0.3, line["end"] - line["start"]) * 0.92  # chữ cuối thường ngân dài
    weights = [len(w) + 2 for w in words]
    t, out = line["start"], []
    for w, k in zip(words, weights):
        out.append((w, t))
        t += span * k / sum(weights)
    return out


def _layout(words: list[str], font: ImageFont.FreeTypeFont, max_w: int) -> list[list[int]]:
    """Ngắt câu thành tối đa vài dòng vừa khung; trả về chỉ số chữ của từng dòng."""
    space = font.getlength(" ")
    rows, cur, w = [], [], 0.0
    for i, word in enumerate(words):
        ww = font.getlength(word)
        if cur and w + space + ww > max_w:
            rows.append(cur)
            cur, w = [], 0.0
        cur.append(i)
        w += (space if len(cur) > 1 else 0) + ww
    return rows + [cur] if cur else rows


def _draw(words: list[str], active: int, size: tuple[int, int], fs: int) -> Image.Image:
    """Ảnh dải chữ: chữ < active đã hát, chữ = active vừa hát (to hơn), còn lại chưa hát."""
    w, h = size
    font = ImageFont.truetype(FONT, fs)
    big = ImageFont.truetype(FONT, round(fs * 1.12))
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rows = _layout(words, font, int(w * 0.88))
    lh = fs * 1.3
    y = h - lh * len(rows) - fs * 0.2
    space = font.getlength(" ")
    for row in rows:
        x = (w - sum(font.getlength(words[i]) for i in row) - space * (len(row) - 1)) / 2
        for i in row:
            ww = font.getlength(words[i])
            f, col = (big, SUNG) if i == active else (font, SUNG if i < active else TODO)
            dx = (ww - f.getlength(words[i])) / 2  # chữ to hơn vẫn giữ tâm, không đẩy chữ bên cạnh
            d.text((x + dx, y + lh / 2), words[i], font=f, fill=col, anchor="lm",
                   stroke_width=max(2, fs // 12), stroke_fill=STROKE)
            x += ww + space
        y += lh
    return img


def build(lines: list[dict], total: float, frame: tuple[int, int], out_dir: Path) -> tuple[Path, int]:
    """Tạo các ảnh dải chữ + file danh sách concat. Trả về (file danh sách, toạ độ y đặt dải chữ trên khung)."""
    fw, fh = frame
    fs = max(22, round(min(fw, fh) * (0.058 if fh > fw else 0.05)))
    band = (fw, round(fs * 1.3 * 3 + fs * 0.6))  # đủ cho 3 dòng
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()
    blank = out_dir / "blank.png"
    Image.new("RGBA", band, (0, 0, 0, 0)).save(blank)

    sung = [l for l in lines if (l.get("text") or "").strip()]
    events: list[tuple[float, Path]] = [(0.0, blank)]
    for n, line in enumerate(sung):
        wt = word_times(line)
        words = [w for w, _ in wt]
        nxt = sung[n + 1]["start"] if n + 1 < len(sung) else total
        show, hide = max(0.0, line["start"] - LEAD), min(nxt - LEAD, line["end"] + TAIL)
        if events and show < events[-1][0]:
            show = events[-1][0]
        for k in range(-1, len(words)):  # -1: cả câu chưa hát
            t = show if k == -1 else max(show, wt[k][1])
            img = out_dir / f"l{n:03d}_{k + 1:02d}.png"
            _draw(words, k, band, fs).save(img)
            events.append((t, img))
        if hide < nxt - LEAD:
            events.append((max(hide, events[-1][0]), blank))

    lst = out_dir / "list.txt"
    rows = []
    for (t, img), nxt_ev in zip(events, events[1:] + [(total, None)]):
        d = nxt_ev[0] - t
        if d > 0.001:
            rows.append(f"file '{img}'\nduration {d:.3f}")
    rows.append(f"file '{events[-1][1]}'")  # concat demuxer bỏ qua duration của ảnh cuối
    lst.write_text("\n".join(rows) + "\n")
    return lst, fh - band[1] - round(fh * (0.06 if fh > fw else 0.04))
