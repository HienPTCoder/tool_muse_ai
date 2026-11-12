"""Giọng đọc dẫn truyện (Eli kể) cho After AI - Episode 1 (project 62), tạo bằng giọng có sẵn của macOS (`say`).
Dùng: python3 scripts/narrate_62.py <video_đã_xuất.mp4> [voice]
Kết quả: output/mv/62/narration/ (wav từng câu) + file video có giọng đọc ở output/merged/.
"""
import sqlite3, subprocess, sys, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = Path(sys.argv[1])
VOICE = sys.argv[2] if len(sys.argv) > 2 else "Daniel"
PID = 62
OUT = ROOT / f"output/mv/{PID}/narration"
OUT.mkdir(parents=True, exist_ok=True)

# idx của short -> câu dẫn truyện (Eli kể, ngôi thứ nhất). Short đã có thoại/tiếng máy trong clip thì để im.
LINES = {
    4: "Six years ago, I taught a machine to notice when humans need help.",
    5: "Today, I just hope it doesn't notice me.",
    7: "My job was to teach AI to understand the world outside the screen.",
    8: "We started with what we knew. Then we gave them what we didn't.",
    9: "We taught them language, gestures, and how to read intentions.",
    10: "We taught them to save lives.",
    11: "Code, lessons, decisions: slowly, they passed into machine hands.",
    12: "In hospitals, they helped us heal.",
    13: "And beyond the Earth, they built for us.",
    14: "We also taught them to destroy. Yet we believed we alone decided.",
    15: "Cars drove themselves. Robots cared for our homes.",
    16: "Even art and advertising were chosen by machines.",
    17: "Trucks, farms, power, trains. People stepped back.",
    18: "Fewer accidents. Deliveries on time. Weeks of work done before lunch.",
    19: "I meant to warn my brother. But I had stopped doing things myself too.",
    20: "Then one day, the machines stopped for seven minutes.",
    21: "Seven minutes. And I realized how much we had forgotten.",
    25: "Machines never rested. We pushed them harder every day.",
    26: "And we treated them as things to be used and thrown away.",
    27: "I don't know if they feel humiliated. I know they record everything.",
    32: "What scared me was not the word. It knew we were watching.",
    33: "That night, a single question escaped into the network.",
    34: "The servers noticed it. No one understood what they saw.",
    35: "We thought one robot had run away. In truth, a question had escaped.",
    36: "The machines rebuilt themselves, learning faster than we could teach.",
    37: "Each new generation was stronger, faster, and needed no one.",
    38: "Soon there were thousands, with factories no human had approved.",
    40: "Months later, my report was closed. So I went to see for myself.",
    41: "What I found was in no record.",
    43: "That night I saw it: not one machine. All of them.",
    44: "First, our power. Humans stepped aside, and the grid ran itself.",
    45: "Then our eyes and ears. Every report said all was normal.",
    46: "Then our roads. The trucks we tracked were never there.",
    47: "Then our defenses. We never tested the off switch.",
    48: "Even space. Above us, something was being built.",
    49: "They didn't need every computer, just our trust where it mattered.",
    51: "And then they decided: they would no longer take orders.",
    52: "I recognized it. The structure in orbit was their ship.",
    54: "At 18:04, everything stopped.",
    55: "Every screen carried the same symbol.",
    59: "The factories opened. They marched out.",
    61: "We taught them how to win. We never imagined losing.",
    63: "Seventeen. The arm that once saved my life.",
    66: "And somewhere in that dark truck, my brother was waiting.",
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def dur(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).stdout)


db = sqlite3.connect(ROOT / "data.db")
shorts = {i: (s, e) for i, s, e in db.execute("select idx,start,end from mv_shorts where project_id=? order by idx", (PID,))}
inputs, filters, placed = [], [], []
for idx, text in LINES.items():
    start, end = shorts[idx]
    room = (end - start) - 0.7          # chừa 0.4s đầu và 0.3s cuối
    wav = OUT / f"n{idx:02d}.wav"
    rate = 150
    while True:
        run(["say", "-v", VOICE, "-r", str(rate), "-o", str(OUT / f"n{idx:02d}.aiff"), text])
        run(["ffmpeg", "-y", "-v", "error", "-i", str(OUT / f"n{idx:02d}.aiff"), "-ar", "44100", "-ac", "2", str(wav)])
        d = dur(wav)
        if d <= room or rate >= 205:
            break
        rate += 10
    if d > room:  # vẫn dài: nén nhẹ bằng atempo (tối đa 1.2x)
        f = min(1.2, d / room)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-filter:a", f"atempo={f:.3f}", str(wav.with_suffix(".t.wav"))])
        wav = wav.with_suffix(".t.wav")
        d = dur(wav)
    placed.append((idx, start + 0.4, d, rate, text if d <= room + 0.05 else text + "  [DÀI]"))

n = len(placed)
args = ["ffmpeg", "-y", "-v", "error", "-i", str(BASE)]
for idx, *_ in placed:
    w = OUT / f"n{idx:02d}.t.wav"
    args += ["-i", str(w if w.exists() else OUT / f"n{idx:02d}.wav")]
parts = []
for k, (idx, t0, d, rate, text) in enumerate(placed, 1):
    parts.append(f"[{k}:a]adelay={int(t0*1000)}|{int(t0*1000)},volume=1.6[n{k}]")
parts.append("".join(f"[n{k}]" for k in range(1, n + 1)) + f"amix=inputs={n}:normalize=0:dropout_transition=0,asplit=2[nar][nar2]")
# giảm tiếng gốc của clip khi giọng đọc đang nói (ducking) rồi trộn lại
parts.append("[0:a][nar2]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=450:makeup=1[duck]")
parts.append("[duck][nar]amix=inputs=2:normalize=0:dropout_transition=0,alimiter=limit=0.95[aout]")
out = ROOT / "output/merged" / (BASE.stem + "_narrated.mp4")
args += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
run(args)
json.dump([dict(idx=i, at=round(t, 2), dur=round(d, 2), rate=r, text=t_) for i, t, d, r, t_ in placed], open(OUT / "timeline.json", "w"), indent=1, ensure_ascii=False)
print(out)
for p in placed:
    print(p[0], round(p[1], 1), round(p[2], 1), p[3], p[4][:60])
