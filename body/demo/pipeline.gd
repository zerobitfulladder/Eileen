extends HBoxContainer
## The demo's pipeline strip: one chip per stage a chat message goes through,
## lit by what really happens (the brain's "stage" events, her speech), with
## what each stage produced underneath (the appraiser's gist, her coping move,
## the sentence she's saying). A stage is idle, active (pulsing) or done.

const Style := preload("res://demo/style.gd")
const STAGES := [
	["chat", "Chat", "a viewer writes"],
	["appraiser", "Appraiser", "LLM · what it means to her"],
	["mind", "Mind", "code · feelings, coping"],
	["actor", "Actor", "LLM · writes her line"],
	["voice", "Voice", "TTS · one sentence at a time"],
	["body", "Body", "Godot · face, lips, gaze"],
]
const IDLE := 0
const ACTIVE := 1
const DONE := 2

var _chips := {}  # stage -> {"panel": PanelContainer, "style": StyleBoxFlat, "detail": Label, "state": int}
var _time := 0.0
var _sentences := 0


func _ready() -> void:
	add_theme_constant_override("separation", 6)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	for i in STAGES.size():
		var stage: Array = STAGES[i]
		if i > 0:
			var arrow := Style.label(22, Style.DIM)
			arrow.text = "›"
			arrow.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
			add_child(arrow)
		var style := Style.panel(Color(0.07, 0.05, 0.1, 0.9))
		style.content_margin_top = 7.0
		style.content_margin_bottom = 7.0
		style.border_width_bottom = 2
		var chip := PanelContainer.new()
		chip.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		chip.add_theme_stylebox_override("panel", style)
		chip.mouse_filter = Control.MOUSE_FILTER_IGNORE
		var box := VBoxContainer.new()
		box.add_theme_constant_override("separation", 0)
		var head := HBoxContainer.new()
		var title := Style.label(21, Style.TEXT, 700)
		title.text = stage[1]
		var what := Style.label(13, Style.DIM)
		what.text = "  " + stage[2]
		what.vertical_alignment = VERTICAL_ALIGNMENT_BOTTOM
		what.size_flags_vertical = Control.SIZE_SHRINK_END
		head.add_child(title)
		head.add_child(what)
		var detail := Style.label(15, Style.ACCENT)
		detail.text = " "
		detail.clip_text = true
		detail.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		box.add_child(head)
		box.add_child(detail)
		chip.add_child(box)
		add_child(chip)
		_chips[stage[0]] = {"panel": chip, "style": style, "title": title, "detail": detail, "state": IDLE}
	_paint_all()


## A viewer's message enters: the strip starts over at Chat.
func begin(line: String) -> void:
	_sentences = 0
	for stage: String in _chips:
		_light(stage, IDLE, " ")
	_light("chat", ACTIVE, line)


## She speaks first (dead air): the strip starts over, and Mind lights first.
func begin_own() -> void:
	_sentences = 0
	for stage: String in _chips:
		_light(stage, IDLE, " ")


## One of the brain's stage events ({"stage": "appraiser"/"mind"/"actor"/"voice", ...}).
func stage(msg: Dictionary) -> void:
	match String(msg.get("stage", "")):
		"appraiser":
			_light("chat", DONE)
			_light("appraiser", ACTIVE, "reading…")
		"mind":
			if _chips.appraiser.state == IDLE:  # she speaks first (begin_own): nothing was appraised
				_light("mind", ACTIVE, "on her own · " + _move(msg))
				return
			var gist := String(msg.get("gist", ""))
			_light("appraiser", DONE, gist if gist else "–")
			_light("mind", ACTIVE, "move · " + _move(msg))
		"actor":
			_light("mind", DONE)
			_light("actor", ACTIVE, "writing…")
		"voice":
			_light("actor", DONE, "done")
			_sentences += 1
			_light("voice", ACTIVE, "sentence %d" % _sentences)


## A sentence starts playing on her body.
func speaking() -> void:
	if _chips.actor.state == ACTIVE:
		_light("actor", DONE, "done")
	_light("voice", DONE)
	_light("body", ACTIVE, "speaking · lip sync")


## A command her body just carried out (AvatarLink.executed): the interesting
## ones show under Body (faces as their strongest blend shapes).
func body(cmd: Dictionary) -> void:
	var what := ""
	match String(cmd.get("cmd", "")):
		"face_layer":
			var shapes: Dictionary = cmd.get("shapes", {})
			var keys := shapes.keys()
			keys.sort_custom(func(a: Variant, b: Variant) -> bool: return float(shapes[a]) > float(shapes[b]))
			var parts := PackedStringArray()
			for key: Variant in keys.slice(0, 2):
				parts.append("%s %.2f" % [String(key).trim_prefix("Fcl_"), float(shapes[key]) * float(cmd.get("intensity", 1.0))])
			what = "face %s · %s" % [cmd.get("layer", ""), " ".join(parts)]
		"gesture":
			what = "gesture · %s" % cmd.get("name", "")
		"look":
			what = "look · %s" % cmd.get("target", "%s°, %s°" % [cmd.get("yaw", 0), cmd.get("pitch", 0)])
		"freeze":
			what = "freeze · %.1f s" % float(cmd.get("seconds", 0.0))
		"blink_mode":
			what = "blink · %s" % cmd.get("mode", "")
		"head_pose":
			what = "head pose · %+.0f° %+.0f°" % [float(cmd.get("pitch", 0.0)), float(cmd.get("yaw", 0.0))]
		_:
			return
	(_chips.body.detail as Label).text = what
	if _chips.body.state == IDLE:
		_light("body", DONE)  # her body reacts before she speaks (her face while she reads)


## Her reply has played: what lit up stays lit, as done, until the next begin().
func finish() -> void:
	for stage: String in _chips:
		if _chips[stage].state == ACTIVE:
			_light(stage, DONE)


func _move(msg: Dictionary) -> String:
	return String(msg.get("move", "?")).replace("_", " ")


func _light(stage: String, state: int, detail := "") -> void:
	var chip: Dictionary = _chips[stage]
	chip.state = state
	if detail:
		(chip.detail as Label).text = detail
	_paint(stage)


func _process(delta: float) -> void:
	_time += delta
	for stage: String in _chips:
		if _chips[stage].state == ACTIVE:
			_paint(stage)


func _paint_all() -> void:
	for stage: String in _chips:
		_paint(stage)


func _paint(stage: String) -> void:
	var chip: Dictionary = _chips[stage]
	var style: StyleBoxFlat = chip.style
	var title: Label = chip.title
	match int(chip.state):
		IDLE:
			style.bg_color = Color(0.07, 0.05, 0.1, 0.82)
			style.border_color = Color(1, 1, 1, 0.08)
			title.add_theme_color_override("font_color", Style.DIM)
			(chip.detail as Label).modulate.a = 0.0
		ACTIVE:
			var pulse := 0.5 + 0.5 * sin(_time * TAU * 1.4)
			style.bg_color = Color(0.2, 0.08, 0.17, 0.95).lerp(Color(0.3, 0.1, 0.23, 0.95), pulse)
			style.border_color = Style.ACCENT.lerp(Color.WHITE, pulse * 0.35)
			title.add_theme_color_override("font_color", Color.WHITE)
			(chip.detail as Label).modulate.a = 1.0
		DONE:
			style.bg_color = Color(0.12, 0.07, 0.17, 0.92)
			style.border_color = Style.TITLE * Color(1, 1, 1, 0.7)
			title.add_theme_color_override("font_color", Style.TITLE)
			(chip.detail as Label).modulate.a = 0.85
