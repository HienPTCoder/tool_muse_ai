"""Hậu kỳ bằng ffmpeg: đọc thông tin, tạo thumbnail, ghép clip."""

import json
import subprocess
from pathlib import Path

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080), "1080p": (1920, 1080)}


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe lỗi: {out.stderr.strip()[:300]}")
    info = json.loads(out.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not v:
        raise RuntimeError("File không có luồng video")
    return {
        "duration": float(info["format"].get("duration", 0)),
        "width": v.get("width"), "height": v.get("height"),
        "size": path.stat().st_size,
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
    }


def thumbnail(video: Path, out: Path) -> Path | None:
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=480:-2", str(out)],
        capture_output=True,
    )
    return out if r.returncode == 0 and out.exists() else None


def last_frame(video: Path, out: Path, size: int = 1024) -> Path | None:
    """Lấy khung hình hiển thị cuối clip để làm ảnh tham chiếu cho cảnh tiếp theo."""
    try:
        duration = probe(video)["duration"]
        at = max(0.0, duration - 0.12)
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
             "-vf", f"scale='min({size},iw)':-2", "-q:v", "4", str(out)],
            capture_output=True,
        )
        return out if r.returncode == 0 and out.exists() else None
    except Exception:
        return None


def merge(clips: list[Path], out: Path, aspect: str = "16:9", xfade: float = 0.0,
          music: Path | None = None, music_volume: float = 0.3, keep_audio: bool = True) -> Path:
    """Ghép clip, chuẩn hóa về cùng khung hình/fps. xfade > 0 thì chuyển cảnh mờ dần."""
    if not clips:
        raise ValueError("Chưa chọn clip nào")
    w, h = ASPECTS.get(aspect, ASPECTS["16:9"])
    metas = [probe(c) for c in clips]

    args = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        args += ["-i", str(c)]
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]

    n = len(clips)
    f = []
    for i, m in enumerate(metas):
        f.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[v{i}]")
        if keep_audio and m["has_audio"]:
            f.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:
            f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{m['duration']}[a{i}]")

    if xfade > 0 and n > 1:
        xfade = min(xfade, *(m["duration"] / 2 for m in metas))
        vprev, aprev, offset = "[v0]", "[a0]", 0.0
        for i in range(1, n):
            offset += metas[i - 1]["duration"] - xfade
            f.append(f"{vprev}[v{i}]xfade=transition=fade:duration={xfade}:offset={offset:.3f}[vx{i}]")
            f.append(f"{aprev}[a{i}]acrossfade=d={xfade}[ax{i}]")
            vprev, aprev = f"[vx{i}]", f"[ax{i}]"
        vout, aout = vprev, aprev
    else:
        f.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
        vout, aout = "[vc]", "[ac]"

    if music:
        f.append(f"[{n}:a]volume={music_volume}[mus]")
        f.append(f"{aout}[mus]amix=inputs=2:duration=first:dropout_transition=0[afinal]")
        aout = "[afinal]"

    args += ["-filter_complex", ";".join(f), "-map", vout, "-map", aout,
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", "-shortest", str(out)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Ghép video lỗi: {r.stderr.strip()[-600:]}")
    return out


def _run(args: list[str], what: str) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{what} lỗi: {r.stderr.strip()[-600:]}")


def audio_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RuntimeError("Không đọc được file nhạc")


def video_small(src: Path, out: Path, max_bytes: int = 7 * 1024 * 1024) -> Path:
    """Nén video mẫu để đính kèm gửi Muse (giới hạn ~8MB): bỏ tiếng, tối đa 2 phút, giảm dần chất lượng tới khi vừa."""
    for height, crf in ((480, 30), (360, 34), (270, 38)):
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", "120", "-an", "-vf", f"scale=-2:'min({height},ih)',fps=24",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(out)], "Nén video")
        if out.stat().st_size <= max_bytes:
            return out
    raise RuntimeError("Video mẫu quá dài/nặng để gửi Muse — hãy cắt ngắn còn dưới 2 phút")


def extract_audio(src: Path, out: Path) -> Path | None:
    """Tách tiếng của video (nhạc MV gốc) ra file m4a; video không có tiếng thì trả None."""
    if not any(st.get("codec_type") == "audio" for st in json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(src)],
            capture_output=True, text=True).stdout or "{}").get("streams", [])):
        return None
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "192k", str(out)], "Tách nhạc")
    return out


def clip_small(src: Path, start: float, dur: float, out: Path, max_bytes: int = 3 * 1024 * 1024) -> Path:
    """Cắt 1 đoạn video gốc (không tiếng, nhỏ) để gửi Muse làm mẫu chuyển động."""
    for height, crf in ((480, 30), (360, 34), (270, 38)):
        _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}", "-an",
              "-vf", f"scale=-2:'min({height},ih)',fps=24", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
              "-pix_fmt", "yuv420p", str(out)], "Cắt đoạn video gốc")
        if out.stat().st_size <= max_bytes:
            return out
    return out


def cut(src: Path, start: float, dur: float, out: Path) -> Path:
    """Cắt 1 đoạn video giữ chất lượng cao (không tiếng)."""
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{dur:.2f}", "-an",
          "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(out)], "Cắt đoạn video")
    return out


def frame(video: Path, t: float, out: Path) -> Path:
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
         "Lấy khung hình")
    return out


def apply_lut(src: Path, lut: Path, out: Path) -> Path:
    """Áp LUT màu (.cube) cho ảnh hoặc video; video thêm hạt rất nhẹ cho bớt mịn kiểu AI."""
    if out.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"lut3d=file={lut}", "-frames:v", "1", "-q:v", "2", str(out)],
             "Khớp màu ảnh")
    else:
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"lut3d=file={lut},noise=c0s=4:c0f=t+u",
              "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)],
             "Khớp màu video")
    return out


def small_jpeg(src: Path, out: Path, size: int = 1024) -> Path:
    """Ảnh tham chiếu thu nhỏ để đính kèm (cạnh dài tối đa `size`)."""
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf",
          f"scale='min({size},iw)':'min({size},ih)':force_original_aspect_ratio=decrease", "-q:v", "3", str(out)],
         "Thu nhỏ ảnh")
    return out


def has_audio(path) -> bool:
    try:
        o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        return o.returncode == 0 and "audio" in o.stdout
    except Exception:
        return False


def export_mv(segments: list[dict], audio: Path | None, out: Path, aspect: str = "16:9",
              lyrics: tuple[Path, int] | None = None, clip_audio: bool = False) -> Path:
    """Ghép các short: mỗi đoạn {path|None, duration} được cắt/kéo dài đúng thời lượng (thiếu thì giữ khung cuối,
    chưa có video thì màn đen), rồi lồng `audio` làm âm thanh (None = im lặng).
    lyrics: (danh sách concat ảnh dải chữ, toạ độ y) từ post/lyrics_overlay.build — phủ lời karaoke lên video."""
    w, h = ASPECTS.get(aspect, ASPECTS["16:9"])
    args, f, n_in = ["ffmpeg", "-y", "-v", "error"], [], 0
    clip_a: list[str] = []
    for i, s in enumerate(segments):
        d = s["duration"]
        if s.get("path"):
            args += ["-i", str(s["path"])]
            if clip_audio:
                # giữ âm thanh gốc của từng short (thoại, tiếng động, nhạc nền Muse tạo); short không có tiếng thì chèn im lặng đúng độ dài
                if has_audio(s["path"]):
                    f.append(f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={d:.3f},"
                             f"atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{i}]")
                else:
                    f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{i}]")
                clip_a.append(f"[a{i}]")
            f.append(f"[{n_in}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
                     f"setsar=1,fps=30,tpad=stop_mode=clone:stop_duration={d:.3f},trim=0:{d:.3f},setpts=PTS-STARTPTS,"
                     f"format=yuv420p[v{i}]")
            n_in += 1
        else:
            f.append(f"color=black:s={w}x{h}:r=30:d={d:.3f},setsar=1,format=yuv420p[v{i}]")
            if clip_audio:
                f.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{i}]")
                clip_a.append(f"[a{i}]")
    if clip_audio:
        a_in = n_in - 1   # không có đầu vào âm thanh riêng; chỉ số này chỉ dùng để tính vị trí đầu vào lời bài hát
        f.append("".join(clip_a) + f"concat=n={len(segments)}:v=0:a=1[aout]")
    else:
        args += ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        a_in = n_in
    f.append("".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[vc]")
    vout = "[vc]"
    if lyrics:
        args += ["-f", "concat", "-safe", "0", "-i", str(lyrics[0])]
        f.append(f"[{a_in + 1}:v]fps=30,format=rgba[ly];[vc][ly]overlay=0:{lyrics[1]}:eof_action=pass,format=yuv420p[vl]")
        vout = "[vl]"
    args += ["-filter_complex", ";".join(f), "-map", vout, "-map", ("[aout]" if clip_audio else f"{a_in}:a"),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", "-shortest", str(out)]
    _run(args, "Xuất MV")
    return out
