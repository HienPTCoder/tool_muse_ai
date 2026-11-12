import sqlite3, sys, os, json, numpy as np
import kokoro_onnx, soundfile as sf
C = os.path.expanduser("~/.cache/hyperframes/tts")
k = kokoro_onnx.Kokoro(f"{C}/models/kokoro-v1.0.onnx", f"{C}/voices/voices-v1.0.bin")
VOICE = os.environ.get("VOICE", "bm_george"); SPEED = float(os.environ.get("SPEED", "0.88"))
db = sqlite3.connect("data.db")
only = {int(x) for x in sys.argv[1:]} if len(sys.argv) > 1 else None
res = {}
for idx, text in db.execute("select idx, lyric from mv_shorts where project_id=61 order by idx"):
    if not text.strip() or (only and idx not in only): continue
    # slow, gentle delivery: commas/periods already pause; keep text as is
    samples, sr = k.create(text, voice=VOICE, speed=SPEED, lang="en-gb" if VOICE.startswith("b") else "en-us")
    sf.write(f"output/mv/61/narration/n{idx:02d}.wav", samples, sr)
    res[idx] = round(len(samples) / sr, 1)
print(json.dumps(res))
