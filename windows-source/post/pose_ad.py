"""Dựng video quảng cáo app tạo dáng (kiểu POSTYLE): ảnh dáng sai + dấu X -> điện thoại mở app, chọn pose, hiện khung
viền pose -> bấm chụp -> ảnh đẹp; lặp lại từng pose -> màn kết logo của app.
Giao diện app (tay cầm điện thoại, thanh trên/dưới, nút Pose AI, bánh răng, icon app, dấu X, màn kết) cắt từ video gốc
của người dùng bằng prepare(); phần màn hình camera, khung viền và ảnh pose được vẽ mới bằng ảnh Muse tạo.
Chạy hoàn toàn trên máy (PIL + ffmpeg + Apple Vision tách người)."""

import math
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
ASSETS = HERE / "pose_ad_assets"
MASK_BIN = HERE / "person_mask"
FPS = 30
W, H = 1080, 1920
S = W / 1440  # toạ độ đo trên khung gốc 1440x2558 -> khung xuất 1080x1920
# vùng màn hình camera trong khung điện thoại gốc (khung 20.0s)
VF = (303, 450, 1271, 2056)
THUMB_W, THUMB_H, THUMB_STEP, THUMB_Y, THUMB_SEL_X = 113, 145, 159, 1890, 719
SHUTTER = (783, 2161)
GREEN = (200, 232, 60)
# thời lượng từng đoạn (giây)
T_HOOK, T_PHONE_FIRST, T_PHONE, T_RESULT = 1.7, 3.0, 2.0, 2.3
T_LIVE_FIRST, T_LIVE = 4.6, 4.0  # đoạn điện thoại có video Muse: chọn pose -> người mẫu vào dáng -> bấm chụp
T_GEN = 3.6  # kiểu "ai": bấm nút Pose AI -> AI quét cảnh, tạo pose -> thumbnail hiện dần -> huy hiệu N POSES
# kiểu hiển thị pose khi chụp: viền trắng quanh người / ảnh pose nguyên vẹn ở góc trên / pose tách nền đứng cạnh người mẫu
OVERLAYS = ("line", "corner", "ghost")
FONT = "/System/Library/Fonts/Avenir Next.ttc"
EMOJI = "/System/Library/Fonts/Apple Color Emoji.ttc"


def R(v: float) -> int:
    return round(v * S)


def _frame(src: Path, t: float, out: Path) -> Image.Image:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(src), "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def _round_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return m


def prepare(src: Path, out: Path = ASSETS) -> None:
    """Cắt giao diện app từ video quảng cáo gốc (chỉ cần chạy 1 lần)."""
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_tmp.png"
    f20, f2, f08 = _frame(src, 20.0, tmp), _frame(src, 2.0, tmp), _frame(src, 0.8, tmp)
    f20.save(out / "phone.png")  # nền: tay cầm điện thoại (vùng VF sẽ được vẽ đè)
    pill = f20.crop((337, 1760, 587, 1863))
    pill.putalpha(_round_mask(pill.size, pill.size[1] // 2))
    pill.save(out / "pose_ai.png")
    eye = f20.crop((1128, 1760, 1232, 1864))
    m = Image.new("L", eye.size, 0)
    ImageDraw.Draw(m).ellipse((1, 1, eye.size[0] - 2, eye.size[1] - 2), fill=255)
    eye.putalpha(m)
    eye.save(out / "eye.png")
    gear = f20.crop((482, 1875, 529, 1922))
    m = Image.new("L", gear.size, 0)
    ImageDraw.Draw(m).ellipse((1, 1, gear.size[0] - 2, gear.size[1] - 2), fill=255)
    gear.putalpha(m)
    gear.save(out / "gear.png")
    icon = f2.crop((907, 659, 1077, 829))
    icon.putalpha(_round_mask(icon.size, 38))
    icon.save(out / "app_icon.png")
    # dấu X đỏ: lấy điểm đỏ + viền trắng bao quanh nó
    x = f08.crop((440, 970, 1180, 1590))
    a = np.asarray(x).astype(int)
    red = (a[..., 0] > 140) & (a[..., 1] < 100) & (a[..., 2] < 100)
    near = np.asarray(Image.fromarray((red * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(31))) > 0
    white = near & (a.min(2) > 185)
    alpha = Image.fromarray(((red | white) * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))
    x.putalpha(alpha)
    x.crop(x.getbbox()).save(out / "red_x.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "23.07", "-i", str(src), "-t", "4.56", "-an",
                    "-vf", f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                    str(out / "endcard.mp4")], check=True)
    tmp.unlink(missing_ok=True)


def person_mask(img: Path, cache: Path) -> Image.Image:
    """Mask người (L, cùng cỡ ảnh) bằng Apple Vision."""
    out = cache / (img.stem + "_mask.png")
    if not out.exists():
        r = subprocess.run([str(MASK_BIN), str(img), str(out)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"Không tách được người trong {img.name}: {r.stderr.strip()}")
    return Image.open(out).convert("L").point(lambda v: 255 if v > 110 else 0).filter(ImageFilter.GaussianBlur(1))


def cover_box(im: Image.Image, size: tuple[int, int], zoom: float = 1.0, focus: tuple[float, float] = (0.5, 0.5)):
    """Vùng ảnh (x0, y0, scale) được lấy khi phủ kín khung `size` (object-fit: cover), phóng `zoom` quanh `focus`."""
    sw, sh = size
    scale = max(sw / im.width, sh / im.height) * zoom
    cw, ch = sw / scale, sh / scale
    cx = min(max(focus[0] * im.width, cw / 2), im.width - cw / 2)
    cy = min(max(focus[1] * im.height, ch / 2), im.height - ch / 2)
    return cx - cw / 2, cy - ch / 2, scale


def cover(im: Image.Image, size: tuple[int, int], zoom: float = 1.0, focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    x0, y0, scale = cover_box(im, size, zoom, focus)
    return im.resize(size, Image.BILINEAR, box=(x0, y0, x0 + size[0] / scale, y0 + size[1] / scale))


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def finger_sprite(size: int) -> Image.Image:
    f = ImageFont.truetype(EMOJI, 160)
    c = Image.new("RGBA", (200, 200))
    ImageDraw.Draw(c).text((0, 0), "👆", font=f, embedded_color=True)
    c = c.crop(c.getbbox())
    hsv = np.asarray(c.convert("RGB").convert("HSV")).astype(int)
    hsv[..., 0] = (hsv[..., 0] - 22) % 256  # vàng -> cam hồng
    hsv[..., 1] = hsv[..., 1] * 55 // 100
    rgb = Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")
    rgb.putalpha(c.getchannel("A"))
    c = rgb
    # viền trắng như sticker
    a = c.getchannel("A").filter(ImageFilter.MaxFilter(9))
    st = Image.new("RGBA", c.size, (255, 255, 255, 0))
    st.putalpha(a)
    st.alpha_composite(c)
    return st.resize((size, round(size * st.height / st.width)), Image.LANCZOS)


def solid_bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    """Khung bao người, bỏ các đốm nhiễu nhỏ của mask (chỉ tính hàng/cột có đủ điểm)."""
    m = np.asarray(mask) > 128
    rows, cols = m.sum(1), m.sum(0)
    if not rows.any():
        return None
    ys = np.where(rows > max(2, rows.max() * 0.04))[0]
    xs = np.where(cols > max(2, cols.max() * 0.04))[0]
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


class Pose:
    """1 pose: ảnh gốc, mask người, khung viền + cutout đặt trên màn hình camera, thumbnail."""

    def __init__(self, path: Path, cache: Path):
        self.img = Image.open(path).convert("RGB")
        self.mask = person_mask(path, cache).resize(self.img.size)
        self.bbox = solid_bbox(self.mask) or (0, 0, *self.img.size)
        x0, y0, x1, y1 = self.bbox
        self.focus = ((x0 + x1) / 2 / self.img.width, (y0 + y1) / 2 / self.img.height)

    def thumb(self) -> Image.Image:
        x0, y0, x1, y1 = self.bbox
        bh = (y1 - y0) * 1.25
        bw = bh * THUMB_W / THUMB_H
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        cx = min(max(cx, bw / 2), self.img.width - bw / 2) if bw < self.img.width else self.img.width / 2
        cy = min(max(cy, bh / 2), self.img.height - bh / 2) if bh < self.img.height else self.img.height / 2
        box = tuple(round(v) for v in (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))
        return self.img.crop(box).resize((R(THUMB_W), R(THUMB_H)), Image.LANCZOS)

    def overlay(self, height: int) -> tuple[Image.Image, Image.Image]:
        """(viền trắng rỗng, cutout có viền trắng) cao `height` px."""
        cut = self.img.crop(self.bbox).convert("RGBA")
        m = self.mask.crop(self.bbox)
        k = height / cut.height
        size = (max(1, round(cut.width * k)), height)
        cut, m = cut.resize(size, Image.LANCZOS), m.resize(size, Image.LANCZOS)
        pad = 12
        big = Image.new("L", (size[0] + 2 * pad, size[1] + 2 * pad))
        big.paste(m, (pad, pad))
        grow = big.filter(ImageFilter.MaxFilter(9))
        ring = Image.fromarray(np.clip(np.asarray(grow, int) - np.asarray(big, int), 0, 255).astype(np.uint8))
        outline = Image.new("RGBA", big.size, (255, 255, 255, 0))
        outline.putalpha(ring.filter(ImageFilter.GaussianBlur(0.8)))
        filled = Image.new("RGBA", big.size, (255, 255, 255, 0))
        filled.putalpha(grow.filter(ImageFilter.GaussianBlur(0.8)))
        cut.putalpha(m)
        filled.alpha_composite(cut, (pad, pad))
        return outline, filled


def fade(im: Image.Image, a: float) -> Image.Image:
    if a >= 1:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: round(v * max(a, 0))))
    return im


def badge(n: int, icon: Image.Image) -> Image.Image:
    w, h = R(658), R(243)
    b = Image.new("RGBA", (w, h))
    ImageDraw.Draw(b).rounded_rectangle((0, 0, w - 1, h - 1), R(40), fill=(12, 12, 12, 225))
    f = ImageFont.truetype(FONT, R(82), index=0)  # Avenir Next Bold
    ic = icon.resize((R(170), R(170)), Image.LANCZOS)
    d = ImageDraw.Draw(b)
    text = f"{n} POSES"
    tw = d.textlength(text, font=f)
    x = (w - tw - ic.width - R(30)) / 2
    d.text((x, h / 2), text, font=f, fill="white", anchor="lm")
    b.alpha_composite(ic, (round(x + tw + R(30)), (h - ic.height) // 2))
    return b


class LiveReader:
    """Đọc lần lượt từng khung hình của video Muse, đã phủ kín màn hình camera (size)."""

    def __init__(self, path: Path, size: tuple[int, int]):
        self.path, self.size = path, size
        self.vf = f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=increase,crop={size[0]}:{size[1]},fps={FPS}"
        self.proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", self.vf, "-f", "rawvideo",
                                      "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last = None

    def next(self) -> Image.Image:
        n = self.size[0] * self.size[1] * 3
        buf = self.proc.stdout.read(n)
        if len(buf) == n:
            self.last = Image.frombytes("RGB", self.size, buf)
        return self.last

    def frame_at(self, t: float, out: Path) -> None:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t, 0):.2f}", "-i", str(self.path), "-vf", self.vf,
                        "-frames:v", "1", str(out)], check=True)

    def close(self) -> None:
        self.proc.stdout.close()
        self.proc.kill()


def outline_ring(mask: Image.Image, width: int = 9) -> Image.Image:
    """Viền rỗng quanh người (L): nở mask ra rồi trừ đi mask."""
    m = mask.point(lambda v: 255 if v > 128 else 0)
    grow = m.filter(ImageFilter.MaxFilter(width))
    ring = np.clip(np.asarray(grow, int) - np.asarray(m, int), 0, 255).astype(np.uint8)
    return Image.fromarray(ring).filter(ImageFilter.GaussianBlur(0.8))


def tint(alpha: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGBA", alpha.size, color + (0,))
    im.putalpha(alpha)
    return im


def sparkle(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    """Ngôi sao 4 cánh lấp lánh."""
    k = r * 0.28
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r), (cx - k, cy + k),
               (cx - r, cy), (cx - k, cy - k)], fill=fill)


def card(img: Image.Image, focus: tuple[float, float], size: tuple[int, int], border) -> Image.Image:
    """Ảnh pose nguyên vẹn dạng thẻ bo góc, viền màu `border`, có bóng đổ."""
    w, h = size
    pad, rad, bw = 14, 22, 5
    out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad))
    sh = Image.new("L", out.size)
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 4, pad + w, pad + h + 4), rad, fill=150)
    out.putalpha(sh.filter(ImageFilter.GaussianBlur(7)))
    out = Image.composite(out, Image.new("RGBA", out.size), out.getchannel("A"))
    frame = Image.new("RGBA", (w, h), tuple(border) + (255,))
    frame.putalpha(_round_mask((w, h), rad))
    out.alpha_composite(frame, (pad, pad))
    ph = cover(img, (w - 2 * bw, h - 2 * bw), 1.0, focus).convert("RGBA")
    ph.putalpha(_round_mask(ph.size, rad - bw))
    out.alpha_composite(ph, (pad + bw, pad + bw))
    return out


def render(wrong: Path, poses: list[Path], out: Path, cache: Path, music: Path | None = None,
           log: Callable[[str], None] = print, lives: list[Path | None] | None = None, bg: Path | None = None,
           style: str = "classic", overlay_shift: int = 0) -> Path:
    """style "classic": như video gốc. style "ai": thêm đoạn bấm Pose AI tạo pose, và mỗi pose dùng 1 kiểu hiển thị
    trong OVERLAYS (lần lượt, lệch `overlay_shift` để các video khác nhau mở đầu bằng kiểu khác nhau)."""
    ai = style == "ai"
    if not (ASSETS / "phone.png").exists():
        raise RuntimeError("Chưa có giao diện app — chạy pose_ad.prepare(video_gốc) trước")
    cache.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    log("Tách người trong ảnh (Apple Vision)…")
    wp = Pose(wrong, cache)
    ps = [Pose(p, cache) for p in poses]
    phone = Image.open(ASSETS / "phone.png").convert("RGB").resize((W, H), Image.LANCZOS)
    if bg and bg.exists() and (ASSETS / "phone_mask.png").exists():
        # nền sau tay cầm điện thoại = bối cảnh của video này (mờ như hậu cảnh ảnh chụp), thay cho sân vận động gốc
        back = cover(Image.open(bg).convert("RGB"), (W, H), 1.15).filter(ImageFilter.GaussianBlur(6))
        phone = Image.composite(phone, back, Image.open(ASSETS / "phone_mask.png").convert("L").resize((W, H)))
    pill = Image.open(ASSETS / "pose_ai.png")
    pill = pill.resize((R(pill.width), R(pill.height)), Image.LANCZOS)
    eye = Image.open(ASSETS / "eye.png")
    eye = eye.resize((R(eye.width), R(eye.height)), Image.LANCZOS)
    gear = Image.open(ASSETS / "gear.png")
    gear = gear.resize((R(gear.width), R(gear.height)), Image.LANCZOS)
    red_x = Image.open(ASSETS / "red_x.png")
    bdg = badge(len(ps), Image.open(ASSETS / "app_icon.png"))
    finger = finger_sprite(R(250))
    tip = (finger.width * 0.40, finger.height * 0.04)  # đầu ngón tay trong sprite
    thumbs = [p.thumb() for p in ps]
    vx0, vy0, vx1, vy1 = (R(v) for v in VF)
    vw, vh = vx1 - vx0, vy1 - vy0

    def fit_zoom(size: tuple[int, int], share: float) -> float:
        """Phóng ảnh dáng sai để người chiếm ít nhất `share` chiều cao khung (ảnh Muse đôi khi để người quá nhỏ)."""
        ph = (wp.bbox[3] - wp.bbox[1]) * cover_box(wp.img, size)[2]
        return min(max(share * size[1] / max(ph, 1), 1.0), 1.8)
    zh, zv = fit_zoom((W, H), 0.45), fit_zoom((vw, vh), 0.42)

    # màn hình camera: nền (ảnh dáng sai hoặc video Muse) + lớp giao diện: lưới 1/3, thước cân bằng, nút Pose AI, nút mắt
    vf_bg = cover(wp.img, (vw, vh), zv, wp.focus)
    ui = Image.new("RGBA", (vw, vh))
    d = ImageDraw.Draw(ui)
    for k in (1, 2):
        d.line((vw * k / 3, 0, vw * k / 3, vh), fill=(255, 255, 255, 110), width=2)
        d.line((0, vh * k / 3, vw, vh * k / 3), fill=(255, 255, 255, 110), width=2)
    d.line((vw * 0.31, vh / 2, vw * 0.69, vh / 2), fill=(255, 255, 255, 230), width=3)
    d.line((vw * 0.45, vh / 2, vw * 0.55, vh / 2), fill=GREEN + (255,), width=3)
    ui.alpha_composite(pill, (R(337) - vx0, R(1760) - vy0))
    ui.alpha_composite(eye, (R(1128) - vx0, R(1760) - vy0))
    # chỗ đứng của người trong khung camera -> đặt khung viền pose cạnh đó, chân cùng mặt đất
    bx, by, sc = cover_box(wp.img, (vw, vh), zv, wp.focus)
    wy1 = (wp.bbox[3] - by) * sc
    wh = (wp.bbox[3] - wp.bbox[1]) * sc
    def strip(sel: int, shown: float | None = None, hi: bool = True) -> Image.Image:
        """Dải thumbnail pose dưới màn hình camera, pose `sel` ở ô được chọn (viền xanh).
        `shown`: số thumbnail đã hiện (đoạn AI đang tạo pose, phần lẻ = ô đang bật ra)."""
        layer = Image.new("RGBA", (vw, vh))
        dd = ImageDraw.Draw(layer)
        cells = thumbs + [None] if shown is None else thumbs[:math.ceil(shown)] + [None]
        for k, th in enumerate(cells):
            x = R(THUMB_SEL_X + (k - sel) * THUMB_STEP) - vx0
            y = R(THUMB_Y) - vy0
            if x + R(THUMB_W) < 0 or x > vw:
                continue
            box = (x, y, x + R(THUMB_W), y + R(THUMB_H))
            if th is not None and shown is not None and k == math.ceil(shown) - 1 and shown % 1:
                q = shown % 1  # ô đang bật ra: phóng từ nhỏ, hơi nảy
                kk = max(0.05, ease(q / 0.7) + 0.12 * math.sin(min(q, 1) * math.pi))
                t = th.resize((max(1, round(th.width * kk)), max(1, round(th.height * kk))), Image.BILINEAR).convert("RGBA")
                t.putalpha(_round_mask(t.size, max(1, round(R(12) * kk))))
                layer.alpha_composite(t, (round(x + (R(THUMB_W) - t.width) / 2), round(y + (R(THUMB_H) - t.height) / 2)))
                continue
            if th is None:  # ô "+" thêm pose
                dd.rounded_rectangle(box, R(12), fill=(20, 20, 20, 235), outline=(200, 200, 200, 255), width=2)
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                dd.line((cx - R(18), cy, cx + R(18), cy), fill="white", width=4)
                dd.line((cx, cy - R(18), cx, cy + R(18)), fill="white", width=4)
                continue
            t = th.convert("RGBA")
            t.putalpha(_round_mask(t.size, R(12)))
            layer.alpha_composite(t, (x, y))
            on = hi and k == sel and shown is None
            dd.rounded_rectangle(box, R(12), outline=GREEN + (255,) if on else (230, 230, 230, 200), width=5 if on else 2)
            layer.alpha_composite(gear, (x + R(THUMB_W) - gear.width // 2 - R(4), y - gear.height // 2 + R(4)))
        return layer

    lives = lives or [None] * len(ps)
    seg = [(T_LIVE_FIRST if n == 0 else T_LIVE) if lives[n] else (T_PHONE_FIRST if n == 0 else T_PHONE) for n in range(len(ps))]
    total = T_HOOK + sum(seg) + T_RESULT * len(ps) + (T_GEN if ai else 0)
    modes = [OVERLAYS[(n + overlay_shift) % 3] if ai else "line" for n in range(len(ps))]
    main = cache / "main.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                            "-pix_fmt", "yuv420p", str(main)], stdin=subprocess.PIPE)

    def emit(im: Image.Image, zoom: float = 1.0) -> None:
        if zoom != 1.0:
            im = cover(im, (W, H), zoom)
        enc.stdin.write(im.convert("RGB").tobytes())

    rnd = np.random.default_rng(7)
    ph = rnd.uniform(0, 2 * math.pi, 6)

    def emit_hand(im: Image.Image, t: float, zoom: float) -> None:
        """Rung tay người cầm điện thoại: lệch, xoay nhẹ, mượt (tổng vài sóng sin chậm)."""
        dx = 9 * math.sin(2 * math.pi * 0.55 * t + ph[0]) + 4 * math.sin(2 * math.pi * 1.7 * t + ph[1])
        dy = 8 * math.sin(2 * math.pi * 0.45 * t + ph[2]) + 3.5 * math.sin(2 * math.pi * 1.9 * t + ph[3])
        a = math.radians(0.55 * math.sin(2 * math.pi * 0.35 * t + ph[4]) + 0.2 * math.sin(2 * math.pi * 1.3 * t + ph[5]))
        k = 1.045 * zoom
        ca, sa, cx, cy = math.cos(a) / k, math.sin(a) / k, W / 2, H / 2
        # ánh xạ ngược: điểm ra (x, y) lấy từ điểm vào
        data = (ca, sa, cx - ca * (cx + dx) - sa * (cy + dy), -sa, ca, cy + sa * (cx + dx) - ca * (cy + dy))
        enc.stdin.write(im.convert("RGB").transform((W, H), Image.AFFINE, data, Image.BILINEAR).tobytes())

    # 1) mở đầu: ảnh dáng sai + dấu X bật ra
    base = cover(wp.img, (W, H), zh, wp.focus)
    xw = round(min(W * 0.62, (wp.bbox[3] - wp.bbox[1]) * cover_box(wp.img, (W, H), zh, wp.focus)[2] * 0.75))
    for i in range(round(T_HOOK * FPS)):
        t = i / FPS
        im = cover(wp.img, (W, H), zh * (1.0 + 0.03 * t / T_HOOK), wp.focus).convert("RGBA") if t else base.convert("RGBA")
        if t >= 0.2:
            k = 1.35 - 0.35 * ease((t - 0.2) / 0.15)
            xs = red_x.resize((round(xw * k), round(xw * k * red_x.height / red_x.width)), Image.BILINEAR)
            bx, by, sc = cover_box(wp.img, (W, H), zh, wp.focus)
            x0, y0, x1, y1 = wp.bbox
            cx, cy = ((x0 + x1) / 2 - bx) * sc, (y0 + (y1 - y0) * 0.33 - by) * sc
            im.alpha_composite(xs, (round(cx - xs.width / 2), round(cy - xs.height / 2)))
        emit(im)
    log("Đoạn mở đầu xong")

    tg = 0.0  # thời điểm trong video (cho rung tay liền mạch)
    start = (W * 0.95, H * 1.05)  # ngón tay vào từ góc dưới phải
    if ai:
        # 1b) bấm nút Pose AI: AI quét bối cảnh + người, tạo pose -> thumbnail hiện dần -> huy hiệu N POSES
        if lives[0]:
            f0 = cache / f"{lives[0].stem}_first.png"
            LiveReader(lives[0], (vw, vh)).frame_at(0, f0)
            gen_bg = Image.open(f0).convert("RGB")
        else:
            gen_bg = vf_bg
        pill_c = (R(337) + pill.width / 2, R(1760) + pill.height / 2)
        prof = np.exp(-((np.arange(220) - 160) / 38.0) ** 2) * (np.arange(220) < 172) + \
            np.exp(-((np.arange(220) - 160) / 6.0) ** 2) * 0.6
        band = Image.new("RGBA", (vw, 220), GREEN + (0,))
        band.putalpha(Image.fromarray(np.repeat((np.clip(prof, 0, 1) * 150)[:, None], vw, 1).astype(np.uint8)))
        stars = [(rnd.uniform(0.08, 0.92) * vw, rnd.uniform(0.08, 0.78) * vh, rnd.uniform(14, 30), rnd.uniform(0.9, 2.4))
                 for _ in range(14)]
        fbig = ImageFont.truetype(FONT, R(56), index=0)
        t_tap, t_gen0, t_gen1, t_badge = 0.75, 0.95, 2.65, 2.6
        for i in range(round(T_GEN * FPS)):
            t = i / FPS
            screen = gen_bg.convert("RGBA")
            screen.alpha_composite(ui)
            shown = len(ps) * ease((t - 1.25) / 1.4) if t < 2.65 else None
            screen.alpha_composite(strip(0, shown, hi=False))
            if t_gen0 <= t < t_gen1 + 0.25:  # quét AI: tối nhẹ, dải sáng xanh chạy dọc, sao lấp lánh, thanh tiến trình
                a = min(1, (t - t_gen0) / 0.2, (t_gen1 + 0.25 - t) / 0.25)
                ov = Image.new("RGBA", (vw, vh), (0, 0, 0, round(70 * a)))
                ph_ = ((t - t_gen0) / 0.85) % 1
                ov.alpha_composite(fade(band, a), (0, round(ph_ * (vh + 120)) - 220))
                dd = ImageDraw.Draw(ov)
                for sx, sy, sr, sp in stars:
                    tw = max(0.0, math.sin((t - t_gen0) * sp * math.pi * 2 + sx))
                    if tw > 0.05:
                        sparkle(dd, sx, sy, sr * (0.5 + 0.5 * tw), (255, 255, 255, round(230 * tw * a)))
                text = "Pose AI is creating poses" + "." * (1 + int(t * 4) % 3)
                tw_ = dd.textlength("Pose AI is creating poses...", font=fbig)
                cx, cy = vw / 2, vh * 0.42
                dd.rounded_rectangle((cx - tw_ / 2 - 70, cy - 62, cx + tw_ / 2 + 40, cy + 70), 34,
                                     fill=(12, 12, 12, round(200 * a)))
                sparkle(dd, cx - tw_ / 2 - 30, cy - 18, 20, GREEN + (round(255 * a),))
                sparkle(dd, cx - tw_ / 2 - 14, cy + 6, 9, (255, 255, 255, round(255 * a)))
                dd.text((cx - tw_ / 2 + 10, cy - 18), text, font=fbig, fill=(255, 255, 255, round(255 * a)), anchor="lm")
                pw = tw_ + 40
                prog = ease((t - t_gen0) / (t_gen1 - t_gen0))
                dd.rounded_rectangle((cx - pw / 2, cy + 30, cx + pw / 2, cy + 42), 6, fill=(255, 255, 255, round(70 * a)))
                dd.rounded_rectangle((cx - pw / 2, cy + 30, cx - pw / 2 + max(12, pw * prog), cy + 42), 6,
                                     fill=GREEN + (round(255 * a),))
                screen.alpha_composite(ov)
            im = phone.copy().convert("RGBA")
            im.paste(screen, (vx0, vy0))
            if t_tap <= t < t_gen1:  # nút Pose AI phát sáng xanh khi đang tạo
                g = Image.new("RGBA", (W, H))
                pulse = 0.5 + 0.5 * math.sin((t - t_tap) * 2 * math.pi * 1.6)
                e = 6 + 10 * pulse
                ImageDraw.Draw(g).rounded_rectangle((R(337) - e, R(1760) - e, R(337) + pill.width + e, R(1760) + pill.height + e),
                                                    pill.height / 2 + e, outline=GREEN + (round(140 + 110 * pulse),), width=6)
                im.alpha_composite(g.filter(ImageFilter.GaussianBlur(1.5)))
            if t >= t_badge:  # huy hiệu "N POSES"
                k = 0.6 + 0.4 * ease((t - t_badge) / 0.2) + 0.06 * math.sin(min(1, (t - t_badge) / 0.35) * math.pi)
                b = bdg.resize((round(bdg.width * k), round(bdg.height * k)), Image.BILINEAR)
                im.alpha_composite(fade(b, 1 - ease((t - (T_GEN - 0.3)) / 0.3)), (W // 2 - b.width // 2, R(752) - b.height // 2))
            # ngón tay: tới nút Pose AI -> chạm -> rút ra ngoài
            if t < t_tap:
                q = ease(t / t_tap)
                pos = (start[0] + (pill_c[0] - start[0]) * q, start[1] + (pill_c[1] - start[1]) * q)
            else:
                q = ease((t - t_tap - 0.25) / 0.5)
                pos = (pill_c[0] + (start[0] - pill_c[0]) * q, pill_c[1] + (start[1] - pill_c[1]) * q)
            press = 0 <= t - t_tap < 0.15
            kk = 0.9 if press else 1.0
            fg = finger.resize((round(finger.width * kk), round(finger.height * kk))) if press else finger
            if t < t_tap + 0.8:
                im.alpha_composite(fg, (round(pos[0] - tip[0] * kk), round(pos[1] - tip[1] * kk)))
            emit_hand(im, tg + t, 1.0)
        tg += T_GEN
        log("Đoạn Pose AI tạo pose xong")
    for n, p in enumerate(ps):
        live, dur = lives[n], seg[n]
        mode = modes[n]
        before = ui.copy()
        before.alpha_composite(strip(max(n - 1, 0) if n else 0, hi=not (ai and n == 0)))
        after = ui.copy()
        after.alpha_composite(strip(n))
        t_tap = 0.9 if n == 0 else 0.45
        t_shut = dur - (0.55 if live else (0.75 if n == 0 else 0.45))
        play = t_tap + 0.25  # video người mẫu bắt đầu chuyển dáng sau khi chọn pose
        if live:  # khung viền = dáng của người mẫu trong video lúc bấm chụp (cô ấy chuyển dáng khớp vào khung)
            reader = LiveReader(live, (vw, vh))
            snap = cache / f"{live.stem}_snap.png"
            reader.frame_at(t_shut - play, snap)
            ring = outline_ring(person_mask(snap, cache).resize((vw, vh)))
            ring_w, ring_g = tint(ring, (255, 255, 255)), tint(ring, GREEN)
            fit_at = play + min(2.6, t_shut - play - 0.3)
            if mode == "ghost":  # pose tách nền đứng cạnh người mẫu, chân cùng mặt đất
                sb = solid_bbox(person_mask(snap, cache).resize((vw, vh))) or (vw // 3, vh // 4, vw * 2 // 3, vh * 3 // 4)
                x0, y0, x1, y1 = p.bbox
                gh = round(min((sb[3] - sb[1]) * 0.8, vh * 0.6, vw * 0.42 * (y1 - y0) / max(x1 - x0, 1)))
                outline, filled = p.overlay(gh)
                left, right = sb[0], vw - sb[2]
                gcx = (sb[0] - outline.width * 0.32) if left > right else (sb[2] + outline.width * 0.32)
                ox = min(max(round(gcx - outline.width / 2), R(6)), vw - outline.width - R(6))
                oy = min(round(sb[3] - outline.height + 12), vh - outline.height)
                edge_g = tint(outline.getchannel("A"), GREEN)
        else:  # không có video: khung viền + cutout của ảnh pose đặt cạnh người đứng
            x0, y0, x1, y1 = p.bbox
            oh = round(min(wh * 0.85 * min(1.0, max(0.55, (y1 - y0) / (0.8 * p.img.height))),
                           vh * 0.58, vw * 0.46 * (y1 - y0) / max(x1 - x0, 1)))
            outline, filled = p.overlay(oh)
            ox = min(max(round(vw * 0.74 - outline.width / 2), R(10)), vw - outline.width - R(10))
            oy = round(wy1 - outline.height + 12)
            edge_g = tint(outline.getchannel("A"), GREEN)
            fit_at = t_shut - 0.35
        if mode == "corner":  # ảnh pose nguyên vẹn bay từ thumbnail lên góc trên phải
            cw = round(vw * 0.34)
            ch = round(cw * min(p.img.height / p.img.width, 1.9))
            card_w, card_g = card(p.img, p.focus, (cw, ch), (255, 255, 255)), card(p.img, p.focus, (cw, ch), GREEN)
            c_end = (vw - card_w.width - R(8), R(14))
            c_start = (R(THUMB_SEL_X) - vx0 - 14, R(THUMB_Y) - vy0 - 14)
        thumb_c = (R(THUMB_SEL_X + THUMB_W / 2), R(THUMB_Y + THUMB_H / 2))
        cur = None
        for i in range(round(dur * FPS)):
            t = i / FPS
            if live:
                cur = reader.next() if (t >= play or cur is None) else cur
                screen = cur.convert("RGBA")
            else:
                screen = vf_bg.convert("RGBA")
            screen.alpha_composite(after if t >= t_tap else before)
            if t >= t_tap and mode == "line":
                if live:
                    ov = ring_g if t >= fit_at else ring_w
                    screen.alpha_composite(fade(ov, (t - t_tap) / 0.25))
                else:
                    screen.alpha_composite(fade(outline, (t - t_tap) / 0.25), (ox, oy))
                    if t >= t_tap + 0.45:
                        screen.alpha_composite(fade(filled, (t - t_tap - 0.45) / 0.3), (ox, oy))
            elif t >= t_tap and mode == "ghost":
                q = ease((t - t_tap) / 0.35)
                gy = oy + round(40 * (1 - q))
                screen.alpha_composite(fade(filled, 0.93 * q), (ox, gy))
                if t >= fit_at:
                    screen.alpha_composite(edge_g, (ox, gy))
            elif t >= t_tap and mode == "corner":
                q = ease((t - t_tap) / 0.4)
                cimg = card_g if t >= fit_at else card_w
                if q < 1:
                    k0 = R(THUMB_W) / cw
                    kk = k0 + (1 - k0) * q
                    cimg = cimg.resize((max(1, round(cimg.width * kk)), max(1, round(cimg.height * kk))), Image.BILINEAR)
                pos_c = (round(c_start[0] + (c_end[0] - c_start[0]) * q), round(c_start[1] + (c_end[1] - c_start[1]) * q))
                screen.alpha_composite(cimg, pos_c)
            if live and mode != "line" and t >= fit_at:  # người mẫu khớp dáng: viền xanh quanh người
                screen.alpha_composite(fade(ring_g, (t - fit_at) / 0.2))
            im = phone.copy().convert("RGBA")
            im.paste(screen, (vx0, vy0))
            if n == 0 and t >= 0.15 and not ai:  # huy hiệu "N POSES" (kiểu ai đã hiện ở đoạn Pose AI)
                k = 0.6 + 0.4 * ease((t - 0.15) / 0.2) + 0.06 * math.sin(min(1, (t - 0.15) / 0.35) * math.pi)
                k *= 1 - 0.25 * ease((t - (t_tap + 0.6)) / 0.4) if live else 1
                b = bdg.resize((round(bdg.width * k), round(bdg.height * k)), Image.BILINEAR)
                im.alpha_composite(fade(b, 1 - ease((t - (t_tap + 0.9)) / 0.3)) if live else b,
                                   (W // 2 - b.width // 2, R(752) - b.height // 2))
            # ngón tay: đi tới thumbnail -> chạm -> rời ra chờ người mẫu vào dáng -> tới nút chụp -> chạm
            rest_pos = (thumb_c[0] + R(260), thumb_c[1] + R(330))
            if t < t_tap:
                q = ease(t / t_tap)
                pos = (start[0] + (thumb_c[0] - start[0]) * q, start[1] + (thumb_c[1] - start[1]) * q)
            elif t < t_tap + 0.3 or not live:
                pos = thumb_c if (t < t_shut - 0.35 or live) else None
                if pos is None:
                    q = ease((t - (t_shut - 0.35)) / 0.35)
                    pos = (thumb_c[0] + (R(SHUTTER[0]) - thumb_c[0]) * q, thumb_c[1] + (R(SHUTTER[1]) - thumb_c[1]) * q)
            elif t < t_shut - 0.4:
                q = ease((t - t_tap - 0.3) / 0.4)
                pos = (thumb_c[0] + (rest_pos[0] - thumb_c[0]) * q, thumb_c[1] + (rest_pos[1] - thumb_c[1]) * q)
            else:
                q = ease((t - (t_shut - 0.4)) / 0.4)
                pos = (rest_pos[0] + (R(SHUTTER[0]) - rest_pos[0]) * q, rest_pos[1] + (R(SHUTTER[1]) - rest_pos[1]) * q)
            press = any(0 <= t - tt < 0.15 for tt in (t_tap, t_shut))
            fg = finger.resize((round(finger.width * 0.9), round(finger.height * 0.9))) if press else finger
            kk = 0.9 if press else 1.0
            im.alpha_composite(fg, (round(pos[0] - tip[0] * kk), round(pos[1] - tip[1] * kk)))
            if t >= t_shut:  # vòng sáng nút chụp
                r = R(70) + R(60) * (t - t_shut) / 0.3
                a = max(0, 1 - (t - t_shut) / 0.3)
                ov = Image.new("RGBA", (W, H))
                ImageDraw.Draw(ov).ellipse((R(SHUTTER[0]) - r, R(SHUTTER[1]) - r, R(SHUTTER[0]) + r, R(SHUTTER[1]) + r),
                                           outline=(255, 255, 255, round(220 * a)), width=6)
                im.alpha_composite(ov)
            emit_hand(im, tg + t, 1.0 + 0.025 * t / dur)
        if live:
            reader.close()
        tg += dur
        # 2) ảnh kết quả: chớp trắng như bấm máy, rồi đẩy vào chậm
        for i in range(round(T_RESULT * FPS)):
            t = i / FPS
            im = cover(p.img, (W, H), 1.0 + 0.045 * t / T_RESULT, p.focus)
            if t < 0.12:
                im = Image.blend(im, Image.new("RGB", (W, H), "white"), 0.75 * (1 - t / 0.12))
            emit(im)
        log(f"Pose {n + 1}/{len(ps)} xong")
    enc.stdin.close()
    if enc.wait():
        raise RuntimeError("ffmpeg lỗi khi ghi video")

    # ghép màn kết logo gốc + nhạc (cắt đúng độ dài, giảm dần cuối video)
    end = ASSETS / "endcard.mp4"
    full = total + 4.56
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(main), "-i", str(end)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-filter_complex", f"[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a]atrim=0:{full:.2f},afade=t=out:st={full - 1.2:.2f}:d=1.2[a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{full:.2f}", str(out)]
    subprocess.run(cmd, check=True)
    log(f"Đã xuất {out.name} ({full:.1f}s)")
    return out
