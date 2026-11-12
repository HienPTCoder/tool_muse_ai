"""Tách file giọng đọc dài của AI Studio thành từng câu (theo chỗ nghỉ) để đặt vào đúng short.
Dùng: python3 scripts/split_ai_narration.py   (đọc output/mv/62/narration_ai/{ai.wav,ai_text.json})
Ra: output/mv/62/narration_ai/spans.json  {idx: [start,end]} tính theo giây trong ai.wav.
Cách làm: tìm các đoạn có tiếng (silencedetect) rồi quy hoạch động chia chúng thành các câu theo số từ dự kiến của mỗi câu
và thưởng điểm khi ranh giới câu rơi vào chỗ nghỉ dài."""
import json, re, subprocess
import os, sys
from pathlib import Path

D = Path(os.environ.get("NARR_DIR") or Path(__file__).resolve().parent.parent / "output/mv/62/narration_ai")
WAV = sys.argv[1] if len(sys.argv) > 1 else "ai.wav"
TXT = sys.argv[2] if len(sys.argv) > 2 else "ai_text.json"
SPANS = sys.argv[3] if len(sys.argv) > 3 else "spans.json"
text = {int(k): v for k, v in json.loads((D / TXT).read_text()).items()}
idxs = sorted(text)
words = [len(re.findall(r"[A-Za-z0-9']+", text[i])) for i in idxs]

out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(D / WAV), "-af", "silencedetect=noise=-38dB:d=0.3", "-f", "null", "-"],
                     capture_output=True, text=True).stderr
total = float(re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).expand(r"\1") and 0) or 0
m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
total = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
sil = []
cur = None
for l in out.splitlines():
    a = re.search(r"silence_start: ([\d.]+)", l)
    if a:
        cur = float(a[1])
    b = re.search(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", l)
    if b and cur is not None:
        sil.append((cur, float(b[1])))
        cur = None
if cur is not None:
    sil.append((cur, total))
# đoạn có tiếng = khoảng giữa các đoạn im lặng
chunks = []
t = 0.0
for s, e in sil:
    if s - t > 0.15:
        chunks.append((t, s))
    t = e
if total - t > 0.15:
    chunks.append((t, total))
C, L = len(chunks), len(idxs)
speech = sum(e - s for s, e in chunks)
wps = sum(words) / speech
gap = [chunks[i + 1][0] - chunks[i][1] for i in range(C - 1)] + [0.0]
INF = 1e18
best = [[INF] * (C + 1) for _ in range(L + 1)]
back = [[0] * (C + 1) for _ in range(L + 1)]
best[0][0] = 0.0
for j in range(1, L + 1):
    for b in range(j, C + 1):
        for a in range(j - 1, b):
            if best[j - 1][a] >= INF:
                continue
            d = chunks[b - 1][1] - chunks[a][0]
            exp_w = d * wps
            cost = (exp_w - words[j - 1]) ** 2 / max(words[j - 1], 4) - 1.2 * min(gap[b - 1], 2.0)
            v = best[j - 1][a] + cost
            if v < best[j][b]:
                best[j][b], back[j][b] = v, a
spans = {}
b = C
for j in range(L, 0, -1):
    a = back[j][b]
    spans[idxs[j - 1]] = [round(max(0, chunks[a][0] - 0.05), 3), round(chunks[b - 1][1] + 0.08, 3)]
    b = a
(D / SPANS).write_text(json.dumps(spans, indent=1))
print("chunks", C, "lines", L, "wps", round(wps, 2))
for i in idxs:
    s, e = spans[i]
    print(i, round(s, 1), round(e, 1), round(e - s, 1), "words", words[idxs.index(i)])
