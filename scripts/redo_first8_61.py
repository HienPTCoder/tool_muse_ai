import json, urllib.request, sys
sys.path.insert(0, "scripts")
import importlib.util
spec = importlib.util.spec_from_file_location("bp", "scripts/build_full_plan_61.py"); bp = importlib.util.module_from_spec(spec)
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(bp)
MOOD = (" MOOD RULE (very important): deeply melancholic and lonely. Muted desaturated blue-grey palette with deep soft shadows, a gentle vignette "
        "and faint film grain; lots of empty negative space so Bo looks small and isolated in the frame; soft light with no warm tones; quiet "
        "atmospheric ambient sound (distant rain, faint city hum, a ticking clock). Long held stillness, tiny movements only, as if time is heavy.")
TAIL = bp.NO_TEXT + bp.FRESH + bp.SLOW + bp.CLEAR + bp.PURPOSE + MOOD
NEW = [
 ("Do you believe loneliness can make a person truly disappear?",
  "One slow continuous high-angle shot of a crowded city crossroads at cold dusk; a stream of stick-figure strangers flows past. In the middle stands Bo, faint and about 60 percent see-through, utterly still. He slowly lifts one translucent hand toward a passing stranger, hoping to be noticed; the stranger walks straight through his arm without a glance and the crowd flows on. Bo's hand hangs in the air, then sinks slowly. Ends with Bo small and alone in the middle of the crowd, head lowered."),
 ("There is something Bo has suspected for months. That he is fading. Literally.",
  "Slow wide static shot of the same dusk crossroads, Bo standing alone in the empty middle of the frame. A large bus glides slowly toward him, passes straight through his body like air, and nobody reacts. When it has passed, Bo slowly looks down at his own chest, now see-through where the bus went, and his shoulders sink. Ends holding on Bo's quiet, sad face."),
 ("And the scariest part is not the fading. It is that Bo is not the only one.",
  "Very slow extreme close-up: Bo lifts his hand in front of a street lamp; the lamp light shines through half of his palm, with a thin cold rim of light around the fingers and a faint breath cloud in the cold air. He studies his hand for a long moment, then slowly turns his head toward something far away, his eyes widening a little. Ends holding that curious, fearful look."),
 ("",
  "Slow push-in on Bo's profile, his eyes fixed on a dark narrow alley at the edge of the street; thin mist drifts across the frame and gently dissolves like a title card with no letters. Bo hesitates with a small breath, tempted and afraid. Ends on his eyes reflecting the faint pale glow deep inside the alley."),
 ("Nobody hates Bo. There was no fight. The scary thing about loneliness is that nothing happens. Just a gap that grows a little wider each day.",
  "Slow static wide shot of Bo's small cold room, grey rain-light through a single window onto a brick wall. Bo, small in the corner of the frame, sits on the edge of a single narrow bed with his hands between his knees and his head down. A cold untouched cup stands on the desk with no steam, one empty chair beside it, a clock ticking on the wall. Camera very slowly pushes in, leaving wide empty space around him. Ends with Bo motionless in the silence."),
 ("",
  "Slow over-the-shoulder shot: Bo holds his phone, its cold blue glow on his tired face; the inbox is empty and he swipes up, then down, hoping for something. Under his door a thin line of warm light flickers from the neighbor's room and faint laughter drifts through the wall. Bo slowly looks at the warm line, then back at the cold screen, and lowers the phone to his lap. Ends with Bo staring at the dark."),
 ("",
  "One slow continuous shot of Bo lying on his back on the narrow bed, staring at the ceiling, while the window light slowly changes from grey morning to pale evening to dark night to a new grey morning, showing days passing. A few simple tally marks appear one by one on the wall board behind him. A phone lies on his chest, lighting and going dark again and again. Ends with Bo staring at the ceiling, the room cold and silent."),
 ("Day fourteen. Bo has typed and deleted the same message eleven times. Afraid to bother anyone.",
  "Slow close-up at night: Bo sits at his desk under a dim lamp, the blue phone glow on his face and fingers. He types a few words (only illegible marks appear), pauses with his thumb hovering over the send button, afraid, then slowly erases the words one by one. He types a shorter line and hesitates again. Ends with Bo's thumb still hovering over the phone, face lit cold blue, a lonely silence around him."),
]
req = lambda u, m, b=None: json.load(urllib.request.urlopen(urllib.request.Request(u, data=json.dumps(b).encode() if b is not None else None, method=m, headers={"Content-Type": "application/json"})))
d = req("http://127.0.0.1:8765/api/mv/61", "GET")
shorts = d["shorts"]; t = 0.0; out = []
for i, s in enumerate(shorts):
    x = {k: s[k] for k in ("id", "lyric", "description", "lipsync", "characters", "location", "cont", "video_path", "thumb_path")}
    dur = 10.0 if i < 8 else s["end"] - s["start"]
    if i < 8:
        x["lyric"] = NEW[i][0]; x["description"] = NEW[i][1] + TAIL
    x["start"] = t; x["end"] = t + dur; t += dur; out.append(x)
print(req("http://127.0.0.1:8765/api/mv/61/plan", "PUT", out) and "plan ok")
print(req("http://127.0.0.1:8765/api/mv/61/generate", "POST", {"ids": [s["id"] for s in shorts[:8]]}))
