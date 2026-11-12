"""Ghép giọng đọc do Google AI Studio (Gemini TTS) tạo ra vào video After AI (project 62).
Dùng: python3 scripts/narrate_62_ai.py <video_đã_xuất.mp4> <ai.wav>   (cần spans.json từ split_ai_narration.py)
- ai_words.json: kết quả whisper-cli -ml 1 -sow -ojf (mốc thời gian từng từ) của file giọng đọc.
- Căn từng câu theo mốc từ (difflib), cắt thành clip riêng, đặt vào đầu short tương ứng, nén nhẹ nếu quá dài,
  rồi trộn có ducking (hạ tiếng gốc khi giọng đọc nói).
"""
import ast, difflib, json, re, sqlite3, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE, AI = Path(sys.argv[1]), Path(sys.argv[2])
PID = 62
OUT = ROOT / f"output/mv/{PID}/narration_ai"
OUT.mkdir(parents=True, exist_ok=True)

# lấy LINES (idx -> câu) từ narrate_62.py, nhưng dùng đúng văn bản đã gửi AI Studio (bỏ dấu ... để khớp từ)
src = (ROOT / "scripts/narrate_62.py").read_text()
LINES = ast.literal_eval(re.search(r"LINES = (\{.*?\n\})", src, re.S).group(1))
AI_TEXT = json.loads((OUT / "ai_text.json").read_text())  # {idx: câu đã gửi AI Studio}
LINES = {int(k): v for k, v in AI_TEXT.items()}
for _f in (OUT / "ai_text2.json", OUT / "ai_text3.json"):
    if _f.exists():
        LINES.update({int(k): v for k, v in json.loads(_f.read_text()).items()})


def norm(w):
    w = w.lower().replace("eighteen-oh-four", "1804")
    return re.sub(r"[^a-z0-9]", "", w)


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).stdout)


SOURCES = [("ai.wav", "spans.json"), ("ai2.wav", "spans2.json"), ("ai3.wav", "spans3.json")]  # spans từ scripts/split_ai_narration.py
span, src_of = {}, {}
for wav_name, spans_name in SOURCES:
    f = OUT / spans_name
    if f.exists():
        for k, v in json.loads(f.read_text()).items():
            span[int(k)] = v
            src_of[int(k)] = OUT / wav_name
DIALOGUE = {2, 22, 24, 29, 31, 50, 53, 56, 57, 58, 60, 64, 65}  # short để im cho nhân vật/máy thoại
START_OFFSET = {6: 5.8}  # short 6: chờ thẻ tiêu đề "SIX YEARS EARLIER" xong rồi mới kể

db = sqlite3.connect(ROOT / "data.db")
shorts = {i: (s, e) for i, s, e in db.execute("select idx,start,end from mv_shorts where project_id=?", (PID,))}
order = sorted(i for i in LINES if i in span)
missing = [i for i in LINES if i not in span]

placed = []
for pos, idx in enumerate(order):
    AI = src_of[idx]
    s0, s1 = span[idx]
    start, end = shorts[idx]
    nxt = shorts[order[pos + 1]][0] if pos + 1 < len(order) else end
    start = start + START_OFFSET.get(idx, 0.0)
    if (idx + 1) in DIALOGUE:  # short kế tiếp là thoại nhân vật: giọng dẫn không được lấn sang
        nxt = min(nxt, end)
    room = max(nxt - (start + 0.35) - 0.25, 1.0)  # có thể kéo sang short kế tiếp nếu nó không có lời dẫn
    clip = OUT / f"a{idx:02d}.wav"
    a0, a1 = max(0, s0 - 0.12), s1 + 0.18
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a0:.3f}", "-to", f"{a1:.3f}", "-i", str(AI),
         "-af", f"afade=t=in:d=0.04,afade=t=out:st={max(0, a1 - a0 - 0.08):.3f}:d=0.08", "-ar", "44100", "-ac", "2", str(clip)])
    d = dur(clip)
    tempo = 1.0
    if d > room:  # trước hết rút ngắn các quãng nghỉ dài bên trong câu (giữ nhịp thở ~0.2s), rồi mới tăng tốc
        pz = clip.with_suffix(".p.wav")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-af",
             "silenceremove=start_periods=0:stop_periods=-1:stop_duration=0.45:stop_threshold=-40dB:stop_silence=0.22", str(pz)])
        if dur(pz) > 0.8:
            clip, d = pz, dur(pz)
    if d > room:
        tempo = min(1.25, d / room)
        t = clip.with_suffix(".t.wav")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-filter:a", f"atempo={tempo:.3f}", str(t)])
        clip, d = t, dur(t)
    placed.append((idx, start + 0.35, d, tempo, clip, d > room + 0.05))

# không cho 2 câu chồng lên nhau: câu sau lùi lại cho tới khi câu trước nói xong (+0.15s)
shift = []
prev_end = 0.0
for k, p_ in enumerate(placed):
    st = max(p_[1], prev_end + 0.15)
    shift.append(round(st - p_[1], 2))
    placed[k] = (p_[0], st, p_[2], p_[3], p_[4], p_[5])
    prev_end = st + p_[2]
print("lùi tối đa", max(shift), "giây")
ENV_GAIN = 0.5   # tiếng gốc của short còn 50% trong lúc người dẫn chuyện nói
RAMP = 0.15
import array, wave
SR = 8000
total_s = dur(BASE)
env = array.array("h", [32767]) * int(total_s * SR + SR)
for (_i, st, d_, _t, _c, _f) in placed:
    a, b = max(0.0, st - 0.1), st + d_ + 0.2
    lo = int(32767 * ENV_GAIN)
    i0, i1, r = int(a * SR), int(b * SR), int(RAMP * SR)
    for k in range(max(0, i0 - r), min(len(env), i1 + r)):
        if k < i0:
            g = 1 - (1 - ENV_GAIN) * (k - (i0 - r)) / r
        elif k >= i1:
            g = ENV_GAIN + (1 - ENV_GAIN) * (k - i1) / r
        else:
            g = ENV_GAIN
        v = int(32767 * g)
        if v < env[k]:
            env[k] = v
ENV_WAV = OUT / "orig_gain_env.wav"
with wave.open(str(ENV_WAV), "wb") as w_:
    w_.setnchannels(1); w_.setsampwidth(2); w_.setframerate(SR); w_.writeframes(env.tobytes())
args = ["ffmpeg", "-y", "-v", "error", "-i", str(BASE)]
for p in placed:
    args += ["-i", str(p[4])]
args += ["-i", str(ENV_WAV)]
parts = [f"[{k}:a]adelay={int(p[1]*1000)}|{int(p[1]*1000)},volume=1.5[n{k}]" for k, p in enumerate(placed, 1)]
n = len(placed)
parts.append("".join(f"[n{k}]" for k in range(1, n + 1)) + f"amix=inputs={n}:normalize=0:dropout_transition=0[nar]")
parts.append(f"[{n + 1}:a]aresample=48000,pan=stereo|c0=c0|c1=c0[envf]")
parts.append("[0:a]aresample=48000,aformat=channel_layouts=stereo[o48]")
parts.append("[o48][envf]amultiply[orig]")  # tiếng gốc x đường bao (30% khi có người dẫn chuyện, 100% còn lại)
parts.append("[orig][nar]amix=inputs=2:normalize=0:dropout_transition=0,alimiter=limit=0.95:level=disabled[aout]")
out = ROOT / "output/merged" / (BASE.stem.replace("_narrated", "") + "_aistudio_narrated.mp4")
args += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
run(args)
print(out)
print("không khớp được:", missing)
for p in placed:
    print(p[0], round(p[1], 1), "dài", round(p[2], 1), "tempo", round(p[3], 2), "QUÁ DÀI" if p[5] else "")
