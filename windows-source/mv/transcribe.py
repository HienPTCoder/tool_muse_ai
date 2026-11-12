"""Chép lời bài hát + timeline ngay trên máy bằng Whisper (faster-whisper, model large-v3-turbo).
Muse không xử lý được file nhạc dài (gửi bài 3 phút chờ 15 phút không có trả lời), nên phần
timeline làm ở máy; Muse chỉ được nhờ sửa chữ (bước lyrics_fix)."""

import subprocess
import threading

import numpy as np

MODEL = "large-v3-turbo"  # ~1.6GB, tải 1 lần về ~/.cache/huggingface
_model = None
_lock = threading.Lock()


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(path: str, log=print) -> tuple[list[dict], str]:
    """Trả về (các dòng lời, mã ngôn ngữ Whisper nhận ra, ví dụ "en")."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    dur = len(audio) / 16000
    with _lock:
        log("Đang nạp model Whisper (lần đầu phải tải ~1.6GB)…")
        m = _load()
        log("Đang nghe và chép lời…")
        segs, info = m.transcribe(audio, vad_filter=False, beam_size=5, condition_on_previous_text=False,
                               word_timestamps=True, hallucination_silence_threshold=2)
        lines = []
        for s in segs:
            lines.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(), "section": ""})
            if len(lines) % 10 == 0:
                log(f"Đã chép {len(lines)} câu ({s.end:.0f}/{dur:.0f}s)")
    return fill_gaps(lines, dur), info.language


def fill_gaps(lines: list[dict], dur: float, min_gap: float = 1.5) -> list[dict]:
    """Thêm dòng nhạc không lời vào các khoảng trống (intro, gian tấu, outro) để timeline phủ kín bài."""
    out, t = [], 0.0
    for l in sorted(lines, key=lambda l: l["start"]):
        if l["start"] - t >= min_gap:
            out.append({"start": round(t, 2), "end": l["start"], "text": "", "section": "nhạc"})
        elif out:
            out[-1]["end"] = l["start"]  # nối liền
        out.append(l)
        t = l["end"]
    if dur - t >= min_gap:
        out.append({"start": round(t, 2), "end": round(dur, 2), "text": "", "section": "nhạc"})
    elif out:
        out[-1]["end"] = round(dur, 2)
    return out
