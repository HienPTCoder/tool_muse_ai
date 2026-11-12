"""Khớp màu clip Muse theo video mẫu của người dùng (chuyển thống kê màu trong không gian Lab, kiểu Reinhard),
xuất ra LUT 3D (.cube) cho ffmpeg lut3d. Không cần OpenCV, chỉ numpy + ffmpeg."""

import subprocess
from pathlib import Path

import numpy as np

SIZE = 33  # số điểm mỗi chiều của LUT

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_MI = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def _rgb2lab(rgb: np.ndarray) -> np.ndarray:
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _M.T / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _lab2rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787) * _WHITE
    lin = np.clip(xyz @ _MI.T, 0, 1)
    return np.clip(np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055), 0, 1)


def _frames(video: Path, n: int = 8) -> np.ndarray:
    """Lấy mẫu n khung hình nhỏ (96px) đều trong video, trả về mảng pixel RGB 0..1."""
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(video)], capture_output=True, text=True).stdout.strip())
    except ValueError:  # ảnh tĩnh
        dur = 0
    vf = f"fps={n / max(dur, 0.5):.4f},scale=96:96" if dur > 0.5 else "scale=96:96"
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", vf,
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    px = np.frombuffer(out, np.uint8).reshape(-1, 3).astype(np.float64) / 255
    if not len(px):
        raise RuntimeError(f"Không đọc được khung hình từ {video.name}")
    return px


def _stats(video: Path) -> tuple[np.ndarray, np.ndarray]:
    lab = _rgb2lab(_frames(video))
    return lab.mean(0), lab.std(0) + 1e-6


def match_lut(src: Path, ref: Path, out: Path, strength: float = 0.85) -> Path:
    """LUT đưa màu của `src` về giống `ref`: độ sáng, tương phản, cân bằng trắng và độ bão hoà.
    Giới hạn tỉ lệ để không làm hỏng clip khi bối cảnh khác hẳn video mẫu."""
    ms, ss = _stats(src)
    mr, sr = _stats(ref)
    ratio = np.clip(sr / ss, [0.75, 0.6, 0.6], [1.25, 1.3, 1.3])
    g = np.linspace(0, 1, SIZE)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")  # .cube: R chạy nhanh nhất
    grid = np.stack([r, gg, b], -1).reshape(-1, 3)
    lab = _rgb2lab(grid)
    moved = (lab - ms) * ratio + ms + (mr - ms) * np.array([0.8, 1.0, 1.0])
    rgb = _lab2rgb(lab + (moved - lab) * strength)
    out.write_text(f"LUT_3D_SIZE {SIZE}\n" + "\n".join(f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in rgb))
    return out
