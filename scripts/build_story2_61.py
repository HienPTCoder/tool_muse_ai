"""Story v2 for project 61: clear cause->effect story, several characters, narration per short (44 x 10 s)."""
import json, io, contextlib, importlib.util, urllib.request, sys
spec = importlib.util.spec_from_file_location("bp", "scripts/build_full_plan_61.py"); bp = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(bp)
ROOM, CROSS, CAFE, ALLEY, KITCHEN = bp.ROOM, bp.CROSS, bp.CAFE, bp.ALLEY, bp.KITCHEN
BO, MOM, GIRL, HERMIT = bp.BO, bp.MOM, bp.GIRL, bp.HERMIT
MOODS = {
 "cold": " MOOD: deeply melancholic and lonely; muted desaturated blue-grey palette, soft deep shadows, gentle vignette, faint film grain, lots of empty negative space so the characters look small and isolated; no warm tones; quiet ambient sound (distant rain, faint city hum, a ticking clock); long held stillness.",
 "neutral": " MOOD: an ordinary, slightly tired everyday feel; soft muted neutral palette with gentle daylight, calm and quiet, a touch of melancholy; faint film grain; quiet ambient sound.",
 "warm": " MOOD: tender, hopeful and warm; soft amber glow growing against the muted blue-grey surroundings; gentle vignette, faint film grain; soft quiet ambient sound.",
 "jade": " MOOD: serene and peaceful; soft pale jade-green light (#9BCFC0), misty and calm; gentle ambient sound of wind chimes and birds.",
}
FADE = (" FADE RULE (important): make Bo's fading unmistakable. The lower his stated opacity, the more clearly the background (wall, window, street, crowd) shows THROUGH his body, head and hoodie; at 60 percent he is clearly ghost-like, at 30 percent only a faint outline and a pale red tint remain, at 0 percent he is completely gone. Keep his fade level exactly as stated and let it change gradually on screen.")
LOOK = " Style: flat 2D stick-figure animation with clean outlines and a consistent muted color palette, 9:16 vertical."
def S(loc, chars, mood, vo, desc, quick=False):
    return dict(loc=loc, chars=chars, mood=mood, vo=vo, desc=desc, quick=quick)
HOOK = "Bo is about 60 percent see-through."
P = [
 S(CROSS,[BO],"cold","This is Bo. And Bo is disappearing. Not as a figure of speech. Slowly, and for real.",
   "Slow high-angle wide shot of a crowded city crossroads at cold dusk. Bo, faint and about 60 percent see-through, stands still in the middle. He slowly raises a translucent hand toward a passing stranger hoping to be noticed; the stranger walks straight through his arm without a glance. Ends with Bo's hand sinking, small and alone in the crowd."),
 S(CROSS,[BO],"cold","Nobody pushed him out. Nobody was cruel to him. So how does a person fade without anyone noticing? It starts much earlier, with something very small.",
   "Slow shot: Bo lifts his hand before a street lamp; the light shines through half of his palm with a thin cold rim of light. He looks at it, then slowly looks back along the street the way he came, remembering. Ends on his thoughtful, worried face."),
 S(ROOM,[BO],"neutral","Three months earlier, Bo was completely solid. An ordinary life. Busy and tired, like most of us.",
   "Bo is fully solid and opaque (100 percent). Daytime in his small room: he sits at a desk, headphones on, eyes on a laptop and a phone, typing quickly; a half-eaten sandwich beside him. Camera slowly pushes in. Ends with Bo absorbed in his screens, unaware of anything around him."),
 S(CROSS,[BO,GIRL],"neutral","One afternoon, his friend Lily invites him for coffee.",
   "Daytime street outside a cafe: Lily, a young girl stick figure, walks up to Bo holding two coffee cups, smiling. Bo, still fully solid, is looking down at his phone. She gently holds out one cup and points toward the cafe with a hopeful look. Ends with Lily's smile and outstretched cup."),
 S(CROSS,[BO,GIRL],"neutral","Bo says: maybe next time. It sounds harmless. But watch closely: a tiny piece of him has just gone faint.",
   "Bo glances up from his phone, gives a small dismissive wave and shakes his head, then looks back at his phone. Lily's smile fades slowly and she lowers the cup. As Bo turns away, his outline becomes slightly fainter (about 90 percent opaque), a subtle shimmer. Ends on Lily watching him walk away, holding both cups."),
 S(ROOM,[BO],"neutral","Then his mom calls. Bo looks at the screen, and thinks: I will call back tomorrow.",
   "Bo's room in the evening: his phone lights up and vibrates on the desk with a simple icon of a woman with a bun. Bo looks at it, hesitates, sighs, and turns the phone face-down to let it ring out. He slowly puts his headphones back on. Ends with the face-down phone still glowing at its edges."),
 S(KITCHEN,[MOM],"warm","In another city, his mother puts the phone down, and sets the table for one.",
   "A small warm kitchen, yellow light bulb: Bo's mother, a stick figure with a bun, holds her phone to her ear, waiting; no answer. She lowers it slowly, then sets down a single bowl and one pair of chopsticks at the table, next to an empty second chair. Ends with her sitting alone, looking at the empty chair."),
 S(CROSS,[BO],"neutral","A group of friends waves him over to come out with them. He is tired, so he says no. Each later feels small. But each one quietly closes a door.",
   "Evening street: three stick-figure friends wave Bo over, gesturing toward a bright restaurant. Bo shakes his head, mimes tiredness, and turns the other way. The friends shrug and walk off together. Bo, now about 75 percent opaque and slightly faded, walks away alone. Ends with Bo walking in the opposite direction from the glowing restaurant."),
 S(ROOM,[BO],"cold","And one day, the invitations stop. Not out of anger. People simply believe you do not want to come.",
   "Bo's room, window light changing slowly from morning to dusk to night. Bo, about 70 percent opaque, sits on the bed with his phone, which stays dark; a notification icon that used to blink now does not. Ends with Bo staring at the silent phone."),
 S(ROOM,[BO],"cold","Day three. Day seven. Day fourteen. Bo waits for someone to reach out first. But waiting to be noticed is a trap.",
   "One slow continuous shot: Bo sits at the edge of the bed in his cold room, small in the corner of the frame; a wall board behind him gets simple tally marks, one by one, as the window light shifts through several days. Beside him is a cold untouched cup and an empty chair. Ends with Bo motionless and the board full of marks."),
 S(None,[BO],"cold","Because loneliness protects itself. You feel unwanted, so you pull back. The more you pull back, the fewer people reach you, and the lonelier you feel.",
   "Simple dark teal background: Bo sits alone in the center, small. Around him, four glowing circles joined by arrows in a loop, each holding a clear icon: a sad face, a thought bubble, a figure walking away, an empty chair. They light up one by one in that order, and each time around Bo shrinks a little. Ends with Bo tiny in the middle of the loop."),
 S(ROOM,[BO],"cold","Day fourteen. Bo types a message to a friend, and deletes it. Eleven times. Afraid to be a bother.",
   "Night, close-up: Bo at his desk under a dim lamp, blue phone glow on his face and fingers. He types a few words (only illegible marks appear), his thumb hovers over send, afraid, then slowly erases the words one by one. Ends with Bo's thumb still hovering, a silence around him."),
 S(ROOM,[BO],"cold","And that is when it begins. His fingertips go faint first. Scientists say that being ignored hurts the brain almost like physical pain.",
   "Extreme close-up of Bo's fingertips on the desk fading toward transparency with a faint glass-crack shimmer, the fade creeping across the hand (about 60 percent opacity). Bo looks at his hand in quiet shock. Slow pull back to reveal his whole body slightly see-through. Ends holding the wide shot."),
 S(CAFE,[BO],"cold","Out in the street, everyone else seems to belong somewhere. Bo stands outside the glass.",
   "Night street viewed through a cafe window: four stick figures laugh together inside; the warm light stays inside the glass and does not reach Bo, who stands outside on the left in the cold zone, about 55 percent opaque. Camera slowly pushes in on Bo's face. Ends with Bo looking in, his shoulders slumped."),
 S(CROSS,[BO],"cold","People walk right through him. Not because they are cruel. Because he is no longer visible to anyone.",
   "Side tracking shot at night of Bo walking head down along shop windows at the left third of the frame (about 50 percent opaque); a passer-by bumps straight through him without noticing; his reflection in the windows is fainter than he is. Ends with Bo walking on, smaller in the wide frame, nearing the mouth of a dark alley."),
 S(ALLEY,[BO],"cold","Then Bo hears something. A soft sigh from a dark alley.",
   "Close-up of Bo freezing as he hears a very faint sigh; he turns his head slowly toward a dark narrow alley, darker than the street, with a faint pale light deep inside. He takes a hesitant step toward it. Ends mid-step, eyes wide, curious and afraid."),
 S(ALLEY,[BO],"cold","An old woman. Her children are busy, and they call only on holidays.",
   "Bo enters the narrow brick alley under a flickering pale neon tube. Low-angle shot: an elderly stick-figure woman with a grey bun and a cane, about 50 percent translucent, sits against the wall with an old phone beside her; behind her a wall calendar is blank except two circled dates (illegible marks). Ends on her small, patient figure."),
 S(ALLEY,[BO],"cold","Her phone rings twice a year. She tells herself: they are busy. And she fades a little more every year.",
   "The old woman's phone vibrates twice, far apart; each time she picks it up with hope, then smiles tiredly and places it back. She gives Bo a small gentle shrug and looks at the wall. Her outline is slightly fainter at the end. Ends on her face."),
 S(ALLEY,[BO],"cold","A man in a suit with five thousand contacts. Everyone knows his name. Nobody knows him.",
   "A stick-figure man in a suit and tie, only 35 percent opaque, his round head blurred like smoke, stands holding a phone. Close-up of his phone: a contacts list scrolls fast, a like counter jumps wildly in the corner, no names legible; he stops scrolling, thumb hovering with nobody to call, then lowers the phone. Ends on his bowed, smoky head."),
 S(ALLEY,[BO,GIRL],"cold","And in the corner, someone Bo recognizes. Lily.",
   "In the deepest corner of the alley, a nearly invisible outline of a young girl (about 20 percent opacity) sits on a crate, holding a coffee cup in each hand. Bo walks toward her slowly and stops, recognizing her; his eyes widen. Ends with Bo and Lily facing each other in silence."),
 S(ALLEY,[BO,GIRL],"cold","The friend he brushed off. She kept waiting for him. And she faded too.",
   "Lily slowly looks up at Bo; her eyes are sad but not angry. Bo's face drops; over his shoulder a soft desaturated memory flashes of him waving away her coffee. Bo bows his head in shame. Ends with Bo looking at his own faint hands."),
 S(ALLEY,[BO],"cold","Bo finally understands. Fading is not about how many people know you. It is about how many people truly see you. And whether you see them.",
   "Wide slow pull-back: Bo, the old woman, the man in the suit and Lily stand together in the alley, each at a different opacity; the neon stops flickering and holds steady. Symmetrical composition, a single quiet beat. Ends holding the group."),
 S(ALLEY,[BO],"cold","On the wall, old chalk words: You only appear to the people you are willing to see.",
   "Close-up of a faded brick wall with pale chalk handwriting made of illegible chalk strokes; a cold light sweeps slowly across it. The old woman raises her cane to point at the wall and Bo reads, eyes widening. Ends on Bo's face, understanding."),
 S(None,[HERMIT],"jade","Some people vanish on purpose. A hermit who steps away to find peace is free. That is solitude. Bo's invisibility was not a choice. That is loneliness.",
   "Dolly from a dark alley into a small sunlit courtyard with a huge tree, soft jade-green light. A translucent hermit with a long beard and a straw conical hat sits calmly under the tree, smiling gently, peaceful; wind chimes. Ends on the hermit's serene face."),
 S(None,[],"jade","And many traditions say the same thing: no person was made to exist alone. We are held in place by one another.",
   "Top-down view: many tiny stick figures stand apart, then thin glowing threads connect them one by one into a web; one thread is gently pulled and the whole web ripples and glows. Calm singing-bowl feeling. Ends on the glowing web."),
 S(ROOM,[BO],"cold","But understanding is not enough. Alone again in his room, the fading speeds up. His arms. His shoulders. His face.",
   "Bo's cold room at night. Bo (about 40 percent opaque, the bed and wall clearly visible through his body) sits looking at his hands; the fade spreads slowly up his arms, across his shoulders and face until only a faint ghost outline and a pale red tint of his hoodie remain (about 20 percent). Bo closes his eyes, resigned. Ends on the faint ghost sitting on the bed."),
 S(ROOM,[BO],"cold","And then, he is gone. Completely. Invisible to everyone. Even to himself.",
   "Slow close-up of Bo's face and red hoodie dissolving into nothing: the faint outline disappears completely, the hoodie's tint fades, leaving only the bed, the wall and the empty cold light where he sat (0 percent, fully gone). The cushion slowly un-dents. Ends on the empty bed and the quiet room."),
 S(ROOM,[MOM],"cold","No one notices. No one calls. The cup grows cold. The room looks like nobody ever lived in it.",
   "Slow static wide shot of the completely empty room: untouched cold cup, empty chair, unmade bed, rain-light on the wall, a phone lying dark on the desk, no Bo anywhere. Time passes: the window light shifts from dusk to dawn to dusk, dust floats, and nothing moves. Ends on the empty room in perfect silence."),
 S(ROOM,[BO],"warm","But in the silence, something small remains. A choice. Bo will reach out first.",
   "In the empty room at early morning light, the dark phone on the desk slowly lights up warm amber by itself; a faint, nearly invisible outline of Bo's hand appears for a moment above it, trembling, as if reaching toward the screen; an old chat with his mom opens (illegible shapes). Ends on the glowing amber screen and the faint hand."),
 S(ROOM,[BO],"warm","He writes to his mother. And this time, he does not delete it.",
   "Close-up: Bo, still invisible (0 percent) but his typing is visible as the screen glow and the keys pressing by themselves; a faint outline of his fingers begins to appear as he types slowly without deleting, warm amber light on his hand; he takes a breath and presses send; a soft glowing whoosh of light leaves the phone. Ends on his hand and the glowing phone."),
 S(KITCHEN,[MOM],"warm","On the other side of the city, a mother has waited a long time for this one message.",
   "The warm small kitchen: Bo's mother is eating alone; her phone lights up on the table; she picks it up, reads, starts crying softly, then smiles and hugs the phone to her chest. Ends on her tearful smile in amber light."),
 S(ROOM,[BO],"warm","And Bo's fingertips start to come back. Out of nothing.",
   "Back in Bo's room, close-up: from empty air, a fingertip of Bo's appears as one faint line with a clear bell tone, then the colour spreads across the hand (about 35 percent opacity, the desk still visible through it), warm amber light. Bo looks up in wonder. Ends on his solid hand."),
 S(CROSS,[BO],"warm","Then he does something he forgot to do. He looks up from his phone, and truly sees the people around him.",
   "Daytime street: Bo puts his phone in his pocket, looks up, and nods at the cafe barista; the barista smiles and nods back; a small amber glow appears between them; Bo is now about 50 percent opaque. Ends on the two exchanging a smile."),
 S(ALLEY,[BO],"warm","He sits down beside the old woman, and for the first time, he just listens.",
   "In the alley, Bo sits next to the old woman and turns his body toward her, listening attentively as she gestures and smiles while showing an old photo (a blurred shape). A small amber glow forms between them and her outline darkens a little. Ends on Bo's attentive face."),
 S(ALLEY,[BO],"warm","He asks the man in the suit a question no one has asked him in years: how are you, really?",
   "Bo approaches the man in the suit, gently touches the air near his shoulder and asks him a question (mouth moving with no sound); the man looks up, the smoky blur on his head clears into a clear round face, and his posture eases. Ends with the man's now visible face, surprised."),
 S(ALLEY,[BO,GIRL],"warm","And Bo goes back to Lily. With two cups of coffee.",
   "Bo walks into the alley holding two coffee cups, a little nervous, and kneels in front of Lily, holding one out to her. Ends with Bo's hand outstretched and a soft amber glow in the dark alley."),
 S(ALLEY,[BO,GIRL],"warm","Lily takes the cup. You asked, she says. One small question, and she begins to reappear.",
   "Lily takes the cup, smiles for the first time, and her outline gains a little darkness and colour; Bo's opacity rises to about 85 percent; a small amber glow shines between them. Ends on the two smiling together."),
 S(CAFE,[BO,GIRL],"warm","Bo, Lily and the old woman. Ordinary people. Sitting at the same table.",
   "Inside the warm cafe: Bo, Lily and the old woman sit at the same table with cups of coffee, talking and smiling; the warm light now touches Bo's face; a barista in the background smiles. Camera slowly pushes in. Ends on the three of them laughing quietly."),
 S(CROSS,[],"warm","Little by little, people start to see each other. And the city lights up, one window at a time.",
   "Crane up over the city at night: windows turn warm amber one by one, pairs of stick figures sit together inside; translucent shadows in the street become solid. Ends on the whole warm skyline."),
 S(CROSS,[BO],"warm","Bo is not fully visible yet. Maybe no one ever is. But he has learned where the light comes from. It does not come from being seen. It comes from seeing.",
   "Side tracking shot: Bo walks calmly down the street in profile at 85 percent opacity, one arm still faintly translucent; warm amber window light on one side of his body. Ends mid-step in the amber light."),
 S(CROSS,[BO],"warm","And you? When did you last say: maybe next time? Is someone in your contacts quietly fading?",
   "Bo stops, turns to look straight into the camera in a calm medium close-up, warm soft light on his face, with a small slow nod. Ends holding the direct gaze."),
 S(None,[],"warm","Today, message someone.",
   "Close-up of a glowing amber phone screen on a black background; a single soft message bubble appears; a warm notification chime pulse; the glow slowly settles and fades to black. Ends in a quiet black frame."),
]

EXTRA = {
 "A group of friends": [S(CAFE,[BO],"neutral","He stops looking up. He no longer notices the barista who greets him every morning.",
   "Morning at a cafe counter: the smiling barista waves hello to Bo, who walks past with his eyes glued to his phone and does not look up; the barista's smile fades slowly and the barista goes back to work. Bo is about 75 percent opaque. Ends on the barista watching Bo leave.")],
 "Day fourteen. Bo types": [],
 "People walk right through": [S(CROSS,[BO],"cold","Bo tries to say hello. But nobody turns around.",
   "Night street: Bo steps toward a passing stranger and raises a hand to greet him, mouth moving without sound; the stranger looks straight past him as if he were air and keeps walking. Bo lowers his hand, then the camera slowly pulls back to show him standing alone. Ends with Bo small and still.")],
 "Her phone rings": [S(ALLEY,[BO],"cold","She tells Bo: everyone is waiting for someone else to make the first move. So nobody moves.",
   "The old woman speaks gently to Bo (mouth moving, no sound) and draws a small circle in the dust with her cane, with several tiny stick figures standing around it all looking at each other, none moving. Bo nods slowly as he understands. Ends on Bo's face, thoughtful.")],
 "And Bo's fingertips start": [],
 "On the other side": [S(ROOM,[BO,MOM],"warm","They talk for an hour. About nothing. About everything.",
   "A split view: Bo in his room on a video call and his mother in her warm kitchen, both smiling and talking, the amber glow filling both frames; Bo wipes a tear. Ends on the two smiling at each other through their screens.")],
 "He sits down beside": [S(CROSS,[BO],"warm","He texts the friends he turned down. Their answers come back in seconds: finally!",
   "Bo sits on a bench at dusk with his phone; he sends a message and glowing reply bubbles pop up one after another (shapes only), each with a small happy icon; Bo laughs quietly, relieved. His opacity is about 80 percent. Ends on Bo's smile lit amber.")],
 "Little by little": [],
 "Today, message": [],
}

EXTRA2 = {
 "In another city, his mother": [
  S(CAFE,[BO],"neutral","At dinner, his girlfriend Mia tells him about her day. Bo nods, with his eyes on his phone.",
    "Evening at a quiet restaurant table: MIA is a stick figure girl with a short bob haircut and a yellow scarf, sitting across from Bo, telling him something excitedly (gesturing, mouth moving, no sound). Bo, about 90 percent opaque, nods without looking up, scrolling his phone. Mia's smile slowly fades and she lowers her hands. Ends on Mia looking at the top of Bo's bowed head."),
  S(CROSS,[BO],"neutral","His best friend Sam shares good news. Bo sends a thumbs-up instead of showing up.",
    "Daytime: SAM is a stick figure with a green beanie, standing at a distance waving excitedly with a small cake and a party balloon; Bo, about 85 percent opaque, sits on a bench and only taps a small thumbs-up icon on his phone without looking up. Sam's grin falters and he lowers the balloon slowly. Ends on Sam standing alone with the balloon."),
  S(KITCHEN,[BO,MOM],"neutral","At the family dinner, his dad saves him a seat. Bo says he is too busy. The seat stays empty.",
    "A family dinner at the warm small kitchen table: Bo's mother and Bo's father (a tall stick figure man with round glasses and a grey cardigan) sit with a young relative; one chair is empty with a bowl set in front of it; the father looks at the door, then at the empty chair, and slowly lowers his chopsticks. Ends on the empty chair in warm light, Bo absent."),
 ],
 "And one day, the invitations": [
  S(CROSS,[BO],"cold","Then Mia says: I feel alone, even when I am with you. She walks away. And Bo does not even know what he did.",
    "Dusk street: MIA (stick figure girl with a short bob haircut and a yellow scarf) stands in front of Bo and says something quietly, tears in her eyes (mouth moving, no sound); Bo, about 70 percent opaque and clearly faint, stares at her, confused, phone in hand. She slowly turns and walks away, getting smaller. Ends on Bo alone in the middle of the street with his hand half raised."),
 ],
 "A man in a suit": [
  S(ALLEY,[BO],"cold","A father who worked so hard to provide for his family, he missed every word his kids said.",
    "In the alley, a stick figure father with a briefcase and a tired stoop, about 30 percent translucent, sits on a crate; a faded family photo (blurred shapes) in his hand shows two small children; he looks at it with regret, then puts it away. Ends on the father's lowered, nearly invisible face."),
 ],
 "He texts the friends": [
  S(CROSS,[BO],"warm","He walks up to Sam, with a small cake. Sorry I only sent a thumbs-up.",
    "Daytime street: Bo, now more solid (about 55 percent), walks up to SAM (stick figure with a green beanie) holding a small cake and a party balloon, apologetic; Sam looks surprised, then grins and hugs him tightly; amber warmth surrounds them. Ends on the hug."),
  S(CROSS,[BO],"warm","He finds Mia. No excuses. Just: tell me about your day. And this time, he really listens.",
    "Dusk, on the steps of a building: Bo sits next to MIA (stick figure girl with a short bob haircut and a yellow scarf), his phone put away in his pocket; he turns to face her and listens attentively as she talks, and she slowly begins to smile again. A small amber glow forms between them. Ends on the two sitting side by side."),
  S(KITCHEN,[BO,MOM],"warm","And at the family table, the empty seat is finally filled.",
    "The warm small kitchen: the whole family at the table, Bo's mother, his father (a tall stick figure man with round glasses and a grey cardigan) and the relative; Bo steps in and sits in the empty chair; the father pats his shoulder and the mother serves him a bowl; amber light fills the room. Ends on the family smiling around the full table."),
 ],
}
for k,v in EXTRA2.items():
    EXTRA[k]=EXTRA.get(k,[])+v

# insert extras
def _expand(items):
    out=[]
    for p_ in items:
        out.append(p_)
        for k,v in EXTRA.items():
            if p_["vo"].startswith(k): out.extend(_expand(v))
    return out
_P=_expand(P)
P=_P
shorts=[]; t=0.0
for p in P:
    sp = bp.QUICK if p["quick"] else bp.SLOW
    desc = p["desc"] + LOOK + bp.NO_TEXT + bp.FRESH + sp + bp.CLEAR + bp.PURPOSE + (FADE if BO in p["chars"] else "") + MOODS[p["mood"]]
    shorts.append({"start":t,"end":t+10.0,"lyric":p["vo"],"description":desc,"characters":p["chars"],"location":p["loc"] or "","cont":1,"lipsync":0}); t+=10.0
print(len(shorts), t)
if "--put" in sys.argv:
    r=lambda u,m,b=None: json.load(urllib.request.urlopen(urllib.request.Request(u,data=json.dumps(b).encode() if b is not None else None,method=m,headers={"Content-Type":"application/json"})))
    script="THE FADING MAN\n\n"+"\n".join(f"{i+1}. {p['vo']}" for i,p in enumerate(P) if p['vo'])
    r("http://127.0.0.1:8765/api/mv/61","PATCH",{"script":script,"max_short_sec":10})
    r("http://127.0.0.1:8765/api/mv/61/plan","PUT",shorts)
    print(r("http://127.0.0.1:8765/api/mv/61/generate","POST",{"reset_all":True}))
