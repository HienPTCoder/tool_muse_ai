"""Build the full 7:35 (455 s) English short plan for project 61 and PUT it to the tool."""
import json, math, urllib.request

NO_TEXT = (" NO TEXT RULE (mandatory): do not render any letters, words, numbers, signs, captions, subtitles, chat messages or writing "
           "anywhere in the video; every sign, board, calendar, wall and phone screen must show only blank shapes, simple icons or illegible "
           "scribbles. No speech, no voice-over, no singing; ambient sound only (English text and narration are added in post).")
FRESH = (" FRESH GENERATION REQUIRED: render a brand-new video for this exact request from scratch. Do NOT reuse, copy or return any "
         "previously generated or existing video file from earlier chats or earlier versions. Save it under a new unique filename.")
SLOW = (" PACING RULE (very important): extremely slow, calm, contemplative, like a quiet arthouse film. Every movement is in slow motion "
        "feel: Bo walks, turns and gestures at about half normal speed, with long pauses between actions. The camera barely moves: one slow "
        "smooth push-in or gentle drift for the whole clip, a single continuous take with NO cuts. Only the first action of the description "
        "gets full attention; if there are two actions, spread them out with a long still pause between them. Linger on faces, hands and the "
        "environment. Hold the final pose and expression completely still for the last 2 seconds. Never rush, never add extra events.")
CLEAR = (" CLARITY RULE: make the story instantly understandable to a first-time viewer with the sound off. One clear subject and one clear "
         "action per moment, centered and uncluttered; exaggerate emotion with big readable body language and face (sad = slumped shoulders and "
         "lowered head, hopeful = lifted head, afraid = wide eyes and stiff body); show cause and effect in order (what happens, then how Bo "
         "reacts); keep the background simple with only the props that matter to the story; use obvious visual metaphors (fading = Bo becomes "
         "see-through, connection = warm amber glow between people, loneliness = cold blue-grey and empty space around Bo).")
PURPOSE = (" PURPOSE RULE: every action by every character must have a clear motive and meaning in the story; no idle, random or filler movement. "
           "Before each action show the intention (Bo looks at the thing he is about to touch, reach for or walk toward, then acts), and make the "
           "action express his inner state or move the story forward (reaching = longing for connection, turning away = avoidance, hesitating "
           "before pressing a button = fear of rejection, looking up at someone = noticing them). Background characters also act with a clear "
           "reason, and each gesture ends with a visible result or reaction.")
QUICK = (" PACING RULE: a brisk, energetic beat for this moment only, but still smooth and readable, not frantic; hold the last frame steady for 1 second.")

ROOM, CROSS, CAFE, ALLEY, KITCHEN = "Bo's Small Room", "City Crossroads at Dusk", "Coffee Shop at Night", "Alley of Fading People", "Mother's Small Kitchen"
BO, MOM, GIRL, HERMIT = "Bo", "Bo's Mother", "Young Girl", "Hermit with Straw Hat"
COLD = "cold grey-blue palette"

# (duration, location, characters, speed, narration, [beats])
SC = [
 (6, ROOM, [BO], "Q", "Do you believe loneliness can make a person truly disappear?", [
  "Four ultra-fast cuts in flat 2D with a desaturated cold palette: Bo's near-transparent hand reaches out for help; a grey-blue stick-figure doctor walks straight through Bo without a glance; Bo's mouth opens in a silent scream; two stick figures pack Bo's room into boxes as if he were gone. Ends on the empty room."]),
 (6, CROSS, [BO], "Q", "There is something Bo has suspected for months. That he is fading. Literally.", [
  "High-angle wide shot of a busy city crossroads at dusk with a stick-figure crowd; Bo stands perfectly still, about 60 percent opaque; a bus drives straight through his body like air and nobody reacts. Ends with Bo still standing in the middle, cold street lamps glowing."]),
 (8, CROSS, [BO], "S", "And the scariest part is not the fading. It is that Bo is not the only one.", [
  "Extreme close-up of Bo's hand raised before a street lamp; the lamp light passes through half of his palm, a thin cold rim of light around the fingers.",
  "The hand lowers slowly; Bo turns his head, breath faintly visible, eyes widening as if he has noticed something far away. Ends holding that look."]),
 (10, ALLEY, [BO], "S", "", [
  "Slow push-in on Bo's profile face, looking toward a dark alley, curiosity mixed with fear; faint wind moves his hood. Cold palette.",
  "Continue the push-in on Bo's face; a soft ghostly light mist drifts across the frame and dissolves like a title card without any text. Ends on Bo's eyes fixed on the alley."]),
 (10, ROOM, [BO], "S", "Nobody hates Bo. There was no fight. The scary thing about loneliness is that nothing happens. Just a gap that grows a little wider each day.", [
  "Static wide shot of Bo's small room, cold window light: Bo, fully opaque, sits on the edge of a single bed; a blank wall board with a single tally mark hangs on the wall, a small clock ticks.",
  "Same wide shot, very slow push-in; Bo stares at the floor, shoulders low, nothing else changes in the room. Ends with Bo motionless."]),
 (10, ROOM, [BO], "S", "", [
  "Over-the-shoulder shot of Bo holding his phone; the screen glows cold blue and shows only a blank empty inbox; he swipes up, then down.",
  "Bo slowly lowers the phone and sets it on the desk; from the next room a faint notification glow flickers on the wall, not his. Ends with Bo looking at the phone."]),
 (10, ROOM, [BO], "Q", "", [
  "Quick inserts: the wall board shows three tally marks; Bo lies staring at the ceiling.",
  "Quick inserts: the board shows seven marks; Bo unlocks his phone, locks it, unlocks it again, repeating ten times, clock ticking faster."]),
 (15, ROOM, [BO], "S", "Day fourteen. Bo has typed and deleted the same message eleven times. Afraid to bother anyone.", [
  "Close-up of Bo's fingers typing on a phone, cold blue glow on his hand; symbols appear in the message box as illegible scribbles.",
  "The typed symbols are erased one by one with a backspace motion; Bo types a shorter line, pauses, erases it again.",
  "Bo turns the phone face-down on the desk and sits in silence. Ends on the face-down phone and his still hand."]),
 (15, ROOM, [BO], "S", "The brain processes being ignored close to where it processes physical pain.", [
  "Close-up of Bo's fingertips on the desk; the tips slowly fade toward transparency, a subtle glass-crack shimmer on the edge.",
  "The fading creeps up from the fingers across the whole hand, opacity dropping to about 70 percent; Bo looks at it in quiet shock.",
  "Slow pull back to reveal Bo's whole body slightly translucent, sitting alone in the cold room. Ends holding the wide shot."]),
 (15, None, [BO], "S", "Loneliness has a cruel trap. It makes you more sensitive to rejection, and makes you avoid exactly what could heal it.", [
  "Simple dark teal background: Bo sits alone in the center; four glowing circles around him, joined by arrows in a loop, each holding a clear icon (a sad face, a thought bubble, a figure walking away, an empty chair); they light up one by one in that order.",
  "The loop turns again; each circle glows in turn and the tiny Bo in the center shrinks a little with each pass.",
  "The loop turns once more; Bo has become a very small dot in the center of the glowing circles. Ends on the tiny figure."]),
 (20, CAFE, [BO], "S", "Someone lonely for a long time tends to read every ambiguous thing in the worst way.", [
  "Night street seen through a cafe's glass window: a group of four stick figures laughs inside, warm light stays inside the glass; Bo stands outside on the left, in the cold zone, the warm glow not touching him.",
  "Over Bo's shoulder: the group laughs, their cheerful silhouettes blurred through the glass; Bo's head tilts slightly.",
  "A distorted dark thought-cloud of scribbles floats over Bo's head as he watches, shoulders curling inward.",
  "The cloud dissolves; the group inside is simply laughing about their own conversation. Ends with Bo alone outside the glass."]),
 (20, CAFE, [BO], "S", "", [
  "Side tracking shot of Bo walking head down along shop windows at night, in profile, at the left third of the frame; cold light.",
  "Continue the tracking walk; his reflection in the shop windows is fainter than he is; opacity drops to about 50 percent.",
  "The street lamps stretch his long shadow, which is also faint; the street sounds drift away.",
  "Bo keeps walking, small in the wide frame. Ends as he nears the mouth of a dark alley."]),
 (15, ALLEY, [BO], "S", "And then, in that moment, Bo heard a sound that felt strangely familiar.", [
  "Close-up of Bo's face freezing as he hears a very faint sigh; his head turns slowly to the side.",
  "POV shot toward the mouth of a dark narrow alley, darker than the street, with a faint pale light deep inside.",
  "Bo's face in profile, eyes lifting; a hesitant half-step toward the alley. Ends mid-step."]),
 (15, ALLEY, [BO], "S", "Bo had assumed he was the only one forgotten. It turned out there was a whole city of faded people.", [
  "Behind-the-shoulder follow shot: translucent Bo walks into a narrow brick alley with cardboard boxes, a pale neon tube flickering above.",
  "Continue following Bo deeper; drips of water, flickering pale neon; the alley stretches ahead.",
  "The neon steadies for a moment, revealing faint shapes of figures farther in. Ends on Bo stopping."]),
 (15, ALLEY, [BO], "S", "", [
  "Low-angle shot of an elderly stick-figure woman with a grey bun and a cane, about 50 percent translucent, sitting against the alley wall with an old phone beside her.",
  "Close-up of the brick wall calendar behind her: nearly all days are blank, only two dates circled (illegible marks); her old phone vibrates twice, far apart.",
  "The old woman gives a small gentle shrug and a tired smile at Bo. Ends on her face."]),
 (15, ALLEY, [BO], "S", "", [
  "A stick-figure man in a suit and tie, only 35 percent opaque, his round head blurred like smoke, stands holding a phone.",
  "Close-up of his phone: a contacts list scrolls extremely fast, a counter of likes jumping wildly in the corner, no names legible.",
  "The scrolling stops; his thumb hovers over the phone, he lowers it slowly. Ends on his smoky head, bowed."]),
 (15, ALLEY, [GIRL], "S", "Some people smile in every photo, but have never told anyone they are sad.", [
  "Symmetrical medium shot: a nearly invisible outline of a young girl (about 20 percent opacity) holds a smiling mask in her hands.",
  "She lifts the mask over her face; a cheerful girl in a bright photo frame appears in place of the outline.",
  "She lowers the mask; the frame shows only an empty outline in shadow. Ends on the empty outline."]),
 (10, ALLEY, [BO], "S", "Bo realized: fading does not depend on how many people know you. It depends on how many truly see you.", [
  "Wide shot, slow pull back: four translucent figures of different opacity stand together in the alley, Bo in the middle; the neon stops flickering and holds steady.",
  "Hold the symmetrical wide composition; a single quiet beat, no motion except a gentle breath. Ends holding the group."]),
 (15, ALLEY, [BO], "S", "All this time, Bo waited to be seen. And never looked at anyone.", [
  "Close-up of a faded brick wall with pale chalk handwriting made of illegible chalk strokes; a cold light sweeps slowly across it.",
  "The old woman raises her cane to point at the wall; Bo reads, his eyes widening.",
  "Bo looks down at his own faint hands, then slowly up at the others. Ends on his thoughtful face."]),
 (35, None, [BO], "Q", "This invisibility goes both ways. Bo faded in the world's eyes, and the world faded in his.", [
  "Desaturated, slightly shaky memory shot: Bo walks past a coffee counter eyes glued to his phone while a smiling barista waves; Bo does not look up.",
  "Desaturated memory continues: the barista's smile fades as Bo walks on, head down, in the street.",
  "Desaturated memory: Bo's phone screen shows a missed call icon with a tiny count that rises from one, to two, to three (shown only as simple dots).",
  "Desaturated memory: Bo turns the phone face-down on a table, jaw tight, ignoring the missed calls from Mom.",
  "Desaturated memory: a friend's chat bubble appears on his phone (illegible scribble); Bo reads it, a 'seen' tick appears, he puts it away saying nothing.",
  "Return to the cold alley: Bo holds his head, realizing, the memories fading around him. Ends on him standing still."]),
 (10, ALLEY, [BO], "S", "Feeling seen needs two directions, not only receiving.", [
  "A broken mirror shard stands upright in the alley; Bo steps forward in front of it.",
  "In the mirror, Bo's reflection looks clearer than he is, while the city behind him is blurred and smeared. Ends holding on the mirror."]),
 (15, None, [HERMIT], "S", "", [
  "Dolly from the dark alley out into a small sunlit courtyard with a huge tree; soft jade-green light (#9BCFC0) covers everything.",
  "A translucent hermit with a long beard and straw conical hat sits calmly under the tree, smiling gently, chimes and birds around.",
  "The hermit looks at Bo with serene eyes. Ends on the hermit's face."]),
 (10, None, [HERMIT], "S", "In Taoism, this is called hiding in plain sight. When you choose it, it is freedom. When it is forced on you, it is a prison.", [
  "Misty mountains, ink-wash feel: a small translucent hermit stick figure walks lightly, like smoke in the wind, jade tones.",
  "Wide slow drift over the mist as the hermit walks on, free and unhurried. Ends on the hermit disappearing into the mist."]),
 (10, None, [], "S", "Buddhism reminds us that the self separated from everything is an illusion. We exist through our connections.", [
  "Top-down view: many tiny stick figures standing apart, then thin glowing threads connect them one by one into a web, a calm singing-bowl feeling.",
  "One thread is gently pulled and the entire web ripples and glows. Ends on the glowing web."]),
 (15, None, [], "S", "In the Bible, Hagar in the wilderness called God the One who sees me. Whatever you believe, traditions agree: no human was meant to fade alone.", [
  "Wide desert in warm sand tones: a lone stick figure sits on a dune in the wind.",
  "A single beam of light falls from above onto the figure; camera slowly tilts up following the beam.",
  "The faint chorus-like glow of the beam settles around the figure, who looks up. Ends on the figure bathed in light."]),
 (15, ROOM, [BO], "S", "", [
  "Early morning light in Bo's small room: close-up of Bo's hand tapping a long-forgotten chat in his phone.",
  "The phone shows a list of old unanswered messages (only illegible shapes); the screen begins to glow warm amber for the first time; opacity 45 percent.",
  "Bo's face lit softly warm amber; he takes a slow breath, resolve forming. Ends on his face."]),
 (10, ROOM, [BO], "S", "", [
  "Close-up of Bo's fingers typing slowly this time without deleting, warm amber light on his hand.",
  "Bo presses send; a soft whoosh of light leaves the phone. Ends on his hand and the glowing phone."]),
 (10, KITCHEN, [MOM], "S", "", [
  "Warm small kitchen in another city, yellow light bulb, a rice cooker steaming: Bo's mother, a stick figure with a bun, picks up her phone.",
  "She reads, begins to cry softly, and hugs the phone to her chest. Ends on her tearful smile, amber light."]),
 (10, ROOM, [BO], "S", "", [
  "Back in Bo's room, close-up: a fingertip of Bo's gets one line darker, ringing a clear bell tone.",
  "The darkness spreads across the whole hand, opacity rising from 45 to 60 percent, warm amber light. Ends on the solid hand."]),
 (15, CROSS, [BO, GIRL], "S", "Bo did not demand that anyone see him. He simply saw them first.", [
  "Street scene: Bo nods at the cafe barista; the barista smiles and nods back; a small amber glow appears; Bo's opacity rises to 70 percent.",
  "Alley scene: Bo offers a cup to the faint-outline girl, kindly; she looks up and her outline gains a little darkness.",
  "A tiny warm amber glow shines between the two; Bo's opacity reaches 85 percent. Ends on the two together."]),
 (15, CROSS, [], "S", "", [
  "Crane up over the city at night: a few windows turn warm amber.",
  "The crane keeps rising; more windows light up one by one, pairs of stick figures sit side by side in them.",
  "Wide view of the whole city glowing amber, translucent shadows becoming solid. Ends on the full warm skyline."]),
 (15, CROSS, [BO], "S", "Bo has not fully appeared yet. Maybe no one ever fully does. But the light does not come from being seen. It comes from seeing.", [
  "Side tracking shot: Bo walks confidently down the street in profile at 85 percent opacity, one arm still slightly translucent; warm amber window light on one side.",
  "Continue tracking; the amber glow lights his hoodie; he looks calm.",
  "Bo slows his walk as the glow follows him. Ends mid-step into the amber light."]),
 (15, CROSS, [BO], "S", "And you. When did you last ask someone how they were, and really listen? Is anyone in your contacts quietly fading?", [
  "Bo stops and turns to look straight into the camera, medium close-up, calm and steady, warm soft light on his face.",
  "Static hold: Bo stays still, gently looking at the viewer; his breathing is barely visible.",
  "Bo gives a small, slow nod. Ends holding the direct gaze."]),
 (10, None, [], "S", "Today, message someone.", [
  "Close-up of a glowing amber phone screen on a black background; a single message bubble appears as a soft shape; a warm notification chime pulse.",
  "The screen glow slowly settles, then fades to black. Ends in a quiet black frame."]),
]

shorts = []
t = 0.0
for dur, loc, chars, speed, vo, beats in SC:
    k = max(1, math.ceil(dur / 10))
    k = min(k, len(beats))
    groups = [beats[round(i * len(beats) / k):round((i + 1) * len(beats) / k)] for i in range(k)]
    base = dur / k
    for i, g in enumerate(groups):
        d = round(base * 2) / 2
        assert d <= 10
        body = " Then, in the same continuous shot: ".join(x.rstrip() for x in g) if len(g) > 1 else g[0]
        desc = body + NO_TEXT + FRESH + (QUICK if speed == "Q" else SLOW) + CLEAR + PURPOSE
        shorts.append({"start": t, "end": t + d, "lyric": vo if i == 0 else "", "description": desc,
                       "characters": chars, "location": loc or "", "cont": 1, "lipsync": 0})
        t += d
print(len(shorts), "shorts,", t, "s")
if __name__ == "__main__":
    import sys
    if "--put" in sys.argv:
        req = urllib.request.Request("http://127.0.0.1:8765/api/mv/61/plan", data=json.dumps(shorts).encode(),
                                     method="PUT", headers={"Content-Type": "application/json"})
        print(urllib.request.urlopen(req).status)
