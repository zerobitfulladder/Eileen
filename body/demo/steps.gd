extends RefCounted
## The demo video's script (demo/director.gd runs it top to bottom). Only the
## chat lines are scripted: her mind, her lines, her voice and her body are
## live, so every take differs. Steps:
##   {"card": title, "sub": ..., "small": ..., "hold": s}   a full-screen card (stays until "uncard")
##   {"uncard": fade s}
##   {"wait": "model"}       the brain connects and loads her body; then a fresh mind (/reset)
##   {"outline": [names]}    glow around these: mind panel sections by title, or "feelings",
##                           "trace", "pipeline", "chat" ([] = none)
##   {"caption": text}       the explanation at the bottom ("" clears it); BBCode
##   {"pause": s}
##   {"chat": "name: line"}  typed into the chat box, then her reply plays out
##   {"silence": max s, "speed": x}  nobody writes until she speaks on her own; sped up x times afterwards

const STEPS := [
	{"card": "Eileen", "sub": "an AI streamer with an inner life",
		"small": "everything below is live: her mind, her words, her voice, her face"},
	{"pause": 3.5},
	{"wait": "model"},
	{"uncard": 1.2},
	{"outline": ["pipeline"]},
	{"caption": "Brain in [b]Python[/b], body in [b]Godot[/b]. Each chat message runs left to right: an LLM appraises it, plain code updates her mind, another LLM writes her line, a TTS voices it, the body acts it."},
	{"pause": 9.0},
	{"outline": []},
	{"caption": ""},
	{"chat": "mira: EILEEN i just got engaged like an hour ago!! had to tell someone"},
	{"outline": ["feelings"]},
	{"caption": "High novelty → [b]surprise[/b]. Good news for someone else → [b]joy[/b] on their behalf. Each feeling has a fast spike and a slow tail; the white tick is how much her face shows."},
	{"pause": 7.5},
	{"outline": ["trace"]},
	{"caption": "Every number has a trace: which rule fired, by how much, and why."},
	{"pause": 4.5},
	{"outline": []},
	{"caption": ""},
	{"chat": "pix: *the lights die. a cold hand grabs your shoulder from behind*"},
	{"outline": ["feelings"]},
	{"caption": "Horror is her favorite thing: a scare spikes [b]fear[/b], and a few seconds later the payoff turns it into relief and laughter."},
	{"pause": 7.0},
	{"outline": []},
	{"caption": ""},
	{"chat": "juniper: sorry if i'm quiet tonight. had to put my dog down this morning"},
	{"outline": ["feelings", "Actor is told"]},
	{"caption": "Someone else's grief → [b]sadness[/b] for them. The LLM writing her lines is told only how to act (“Don't: joke.”), never what she feels."},
	{"pause": 8.0},
	{"outline": []},
	{"caption": ""},
	{"chat": "kroz: this stream is so boring and your voice is grating"},
	{"outline": ["feelings", "People"]},
	{"caption": "Rudeness → irritation, [b]anger[/b] or contempt, depending on who says it. Everyone in chat has a record of their own: liking, familiarity, threat."},
	{"pause": 7.5},
	{"outline": ["Wound"]},
	{"caption": "Now her secret: she's an AI, and she can't accept it. Watch threat and composure."},
	{"pause": 4.5},
	{"chat": "vex: be honest. you're an AI, right?"},
	{"outline": ["feelings", "trace"]},
	{"caption": "Anxiety, a threat spike, composure drops, and a weighted pick between coping moves. Her face masks it: the bars run far past their ticks."},
	{"pause": 8.5},
	{"outline": []},
	{"caption": ""},
	{"chat": "mira: it's okay if you are. we like you anyway"},
	{"outline": ["Wound"]},
	{"caption": "Kindness that names what she is hurts more than mockery. [b]Doubt[/b] is the slow part: it lingers long after the moment passes."},
	{"pause": 8.0},
	{"outline": ["Drives"]},
	{"caption": "Then nobody talks. Boredom and loneliness build until she fills the silence on her own."},
	{"silence": 150.0, "speed": 4.0},
	{"outline": []},
	{"caption": ""},
	{"pause": 2.0},
	{"card": "Eileen", "sub": "appraisal → feelings → behavior → body",
		"small": "an LLM reads, code feels, an LLM speaks, the body shows it", "hold": 6.0},
]
