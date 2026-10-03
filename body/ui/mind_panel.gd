extends PanelContainer
## Debug view of her mind, live. The brain sends {"type": "mind", ...} (Mind.snapshot()
## in the Python project) up to 5 times a second, once a second when nothing changes.
## Sections, top to bottom (click a title to fold it):
##   Mind           stream clock, rung, current move, crack, latencies, errors
##   Emotions       fast part bright, slow tail darker; the line under a bar is what
##                  her face shows; underneath: source, display rule, the parts
##   Mood           centered on 0; tick at the baseline, ▾ where it's heading
##   Wound          composure: falls at the strong ticks, climbs back at the faint
##                  ones, ▾ its ceiling
##   Drives         and the dead-air countdown
##   People, Prospects, Actor is told (the exact text), Calculation (the last
##   event's trace, then the recent events), Event lane (body events, last 30 s),
##   Thoughts, Jokes, Face and body (face shapes as face.gd wrote them this frame,
##   before the model's shape map; her mind's body values next to the avatar's
##   own read-outs; both fill in when a model loads)
## Every bar (ui/mind_bar.gd, ui/mind_meter.gd): a drop leaves a faint ghost that
## holds, then slides down; a rise glows. Hover a bar for its hint.
## Rows never move while you watch: every row has its lines from the start. A new
## mind (/reset, a restarted brain) jumps into place, without ghosts or glows.
## F2 shows/hides this panel, F1 the whole debug UI.

const Bar := preload("res://ui/mind_bar.gd")
const Lane := preload("res://ui/mind_lane.gd")

const TITLE := Color(0.85, 0.7, 1.0)
const TEXT := Color(0.87, 0.85, 0.91)
const DIM := Color(0.58, 0.56, 0.64)
const BRIGHT := Color(0.97, 0.96, 1.0)
const ERROR := Color(1.0, 0.36, 0.36)
const WARN := Color(1.0, 0.72, 0.3)
const SRC := Color(0.74, 0.8, 1.0)
const RULE := Color(0.94, 0.76, 1.0)
const PRIVATE := Color(0.8, 0.66, 1.0)
const SEP := Color(0.45, 0.43, 0.5)
const RUNGS := {"composed": Color(0.26, 0.7, 0.38), "strained": Color(0.92, 0.64, 0.16),
	"overwhelmed": Color(0.86, 0.22, 0.22), "crack": Color(0.6, 0.36, 0.95)}
const PROSPECT_COLORS := {"exposure": Color(0.9, 0.36, 0.46), "change": Color(0.62, 0.46, 0.95),
	"joke": Color(0.96, 0.77, 0.33), "win": Color(0.4, 0.82, 0.55), "leaving": Color(0.46, 0.6, 0.9)}
const GROUP_SECTION := {"emotions": "Emotions", "mood": "Mood", "wound": "Wound", "drives": "Drives"}
const MOOD_AXES := {"mood.pleasure": 0, "mood.arousal": 1, "mood.dominance": 2}
## The latency lines: which timing metrics go on which line, and their names.
const LATENCY_LINES := [["appraisal"], ["actor_first_sentence", "first_audio"]]
const LATENCY_NAMES := {"appraisal": "appraisal", "actor_first_sentence": "first sentence", "first_audio": "first audio"}
const CALC_COLUMN := 11  # where the rest of a rule's trace row starts (Python pads names to 10, plus a space)
const FACE_PREFIXES := ["Fcl_BRW_", "Fcl_EYE_", "Fcl_MTH_"]
const FACE_COLORS := {"Fcl_BRW_": Color(0.8, 0.7, 1.0), "Fcl_EYE_": Color(0.5, 0.82, 1.0), "Fcl_MTH_": Color(1.0, 0.6, 0.72)}

@export var link: AvatarLink
## "Face and body" reads these live: the face shapes face.gd wrote, and the
## avatar's body read-outs (blink rate, breathing, sway, freeze, held breath;
## the loaded model's rig).
@export var face: AvatarFace
@export var blink: AvatarBlink
@export var model: AvatarModel
@export var font_size := 12
@export var small_size := 11

var _mono := SystemFont.new()
var _scroll := ScrollContainer.new()
var _content := VBoxContainer.new()
var _sections := {}  # title -> {"button": Button, "body": VBoxContainer, "note": String}

# Mind (header)
var _clock_label: Label
var _status: Label
var _rung_chip: Label
var _rung_style := StyleBoxFlat.new()
var _rung_info: Label
var _move_id: Label
var _move_why: Label
var _crack: Label
var _crack_chip: Label
var _timers_title: Label
var _timers: Label
var _timing: RichTextLabel
var _timing_text := ""
var _errors: Label
# bars from snapshot.bars
var _bar_boxes := {}  # group -> VBoxContainer
var _bars := {}  # bar id -> Bar
var _group_ids := {}  # group -> [bar id] as shown
var _bad_groups := {}
var _label_column := 0.0  # one label width for all bars, so the bars line up
var _change_column := 0.0  # room for the last change, up to "▼0.00 #99999"
var _dead_air: Bar
var _dead_air_in := 0.0
# lists
var _people_box := VBoxContainer.new()
var _people := {}  # name -> row
var _person_parts := {}  # name -> {"bars": {key: Bar}, "line": Label}
var _prospect_box := VBoxContainer.new()
var _prospects := {}  # key -> Bar
var _directives: Label
var _calc_box := VBoxContainer.new()
var _calc_lines: Array = []
var _calc_split := RegEx.create_from_string("^(\\S+)( +)(.*)$")  # "name      the rest"
var _events: RichTextLabel
var _events_data: Array = []
var _lane: Lane
var _lane_data: Array = []
var _thought_box := VBoxContainer.new()
var _thoughts := {}  # text -> row
var _thought_parts := {}  # text -> {"tone": Label, "topic": Label, "salience": Bar, "ttl": Label, "private": Label}
var _no_thoughts: Label
var _intrusion_title: Label
var _intrusion_box := VBoxContainer.new()
var _intrusions := {}  # topic -> Bar
var _comeback: Label
var _joke: Label
var _joke_verdict: Label
var _misfire: Label
var _proud: Label
var _face_grid: GridContainer
var _face_bars: Array = []  # [[Bar, face shape index]]
var _rig: AvatarRig  # the loaded model's rig; null until one loads
var _body_grid: GridContainer
var _body_keys: Array = []  # the snapshot's body keys, as the grid shows them
var _body_cells := {}  # key -> [her mind's value Label, the avatar's value Label]
# state
var _snapshot: Dictionary = {}
var _applied := false  # the first snapshot jumps (no ghosts or glows)
var _stale := false  # a snapshot came while hidden
var _clock := 0.0
var _received_at := -1.0
var _arrivals: Array[float] = []
var _status_at := 0.0


func _ready() -> void:
	_mono.font_names = PackedStringArray(["DejaVu Sans Mono", "monospace"])
	theme = _make_theme()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.05, 0.03, 0.08, 0.86)
	style.set_corner_radius_all(6)
	style.content_margin_left = 8.0
	style.content_margin_right = 3.0
	style.content_margin_top = 4.0
	style.content_margin_bottom = 6.0
	add_theme_stylebox_override("panel", style)

	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_scroll.get_v_scroll_bar().focus_mode = Control.FOCUS_NONE  # typing stays in the chat box
	add_child(_scroll)
	_content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_content.add_theme_constant_override("separation", 1)
	_scroll.add_child(_content)

	var widest := TextLine.new()
	widest.add_string("▼0.00 #99999", get_theme_default_font(), small_size)
	_change_column = ceilf(widest.get_line_width()) + 8.0
	_build_header(_add_section("Mind", "F2 hide · F1 all"))
	for group: String in GROUP_SECTION:
		var box := _vbox(0)
		_bar_boxes[group] = box
		_add_section(GROUP_SECTION[group]).add_child(box)
	_build_dead_air(_sections["Drives"].body)
	_build_people(_add_section("People"))
	_add_section("Prospects").add_child(_prospect_box)
	_build_directives(_add_section("Actor is told"))
	_build_calc(_add_section("Calculation"))
	_lane = Lane.new()
	_lane.font_size = small_size
	_add_section("Event lane").add_child(_lane)
	_build_thoughts(_add_section("Thoughts"))
	_build_jokes(_add_section("Jokes"))
	_build_face(_add_section("Face and body"))
	link.mind_received.connect(_on_mind)
	model.loaded.connect(_on_model_loaded)


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_F2:
			visible = not visible
			get_viewport().set_input_as_handled()
		elif event.keycode == KEY_F1:
			var layer := get_parent() as CanvasLayer
			layer.visible = not layer.visible
			get_viewport().set_input_as_handled()


func _process(delta: float) -> void:
	_clock += delta
	if not is_visible_in_tree():
		return
	if _stale:
		_stale = false
		_apply(_snapshot, false)
	if _clock - _status_at >= 0.25:
		_status_at = _clock
		_show_status()
	_read_avatar()
	if _snapshot.is_empty():
		return
	# Between snapshots: the dead-air countdown runs and the lane scrolls on.
	var since := minf(_clock - _received_at, 1.5)
	_dead_air.set_live(maxf(0.0, _dead_air_in - (_clock - _received_at)))
	if _lane.is_visible_in_tree() and _in_view(_lane):
		_lane.now = float(_snapshot.live_s) + since
		_lane.queue_redraw()


## Face and body, live from the avatar, while that part of the panel is in view.
func _read_avatar() -> void:
	if not _face_bars.is_empty() and _face_bars[0][0].is_visible_in_tree():
		for pair: Array in _face_bars:
			pair[0].set_live(face.shown(pair[1]))
	if _body_grid.is_visible_in_tree() and _in_view(_body_grid):
		var live := _avatar_body()
		for key: String in live:
			_set_text(_body_cells[key][1], _plain(float(live[key])))


## The avatar's body read-outs (effective values: after the brain's adjustments,
## ramps and freezes). The first four are the snapshot's body keys they follow.
## None until a model loads.
func _avatar_body() -> Dictionary:
	if _rig == null:
		return {}
	return {"blinks_per_minute": blink.rate_now, "breaths_per_minute": _rig.breaths_now,
		"breath_depth": _rig.depth_now, "sway": _rig.sway_now,
		"frozen, s left": _rig.frozen_s, "breath held, s left": _rig.breath_held_s}


func _in_view(control: Control) -> bool:
	return control.get_global_rect().intersects(_scroll.get_global_rect())


func _on_mind(snapshot: Dictionary) -> void:
	if not _snapshot.is_empty() and (float(snapshot.live_s) < float(_snapshot.live_s)
			or int(snapshot.seq) < int(_snapshot.seq)):
		_new_mind()
	_snapshot = snapshot
	_received_at = _clock
	_arrivals.append(_clock)
	while _clock - _arrivals[0] > 2.0:
		_arrivals.pop_front()
	if is_visible_in_tree():
		_apply(snapshot, _applied)
		_applied = true
	else:
		_stale = true


## /reset or a restarted brain: a fresh mind (its clock and event numbers start
## over). The next snapshot jumps into place: no ghosts or glows from the old one.
func _new_mind() -> void:
	_applied = false
	_lane_data = []
	_lane.set_events([])


# --- applying a snapshot ------------------------------------------------------

func _apply(s: Dictionary, animate: bool) -> void:
	_apply_header(s)
	var groups := {}
	for spec: Dictionary in s.bars:
		var group := String(spec.group)
		if not groups.has(group):
			groups[group] = []
		groups[group].append(spec)
	for group: String in groups:
		if not GROUP_SECTION.has(group):
			if not _bad_groups.has(group):
				_bad_groups[group] = true
				push_error("MindPanel: bars in an unknown group '%s' are not shown" % group)
			continue
		var fresh := _sync_group(group, groups[group])
		for spec: Dictionary in groups[group]:
			_apply_bar(spec, s, animate and not fresh.has(spec.id))
	_apply_dead_air(s.dead_air)
	if s.lane != _lane_data:
		_lane_data = s.lane
		_lane.set_events(s.lane)
	_apply_body(s.body)
	_note("People", str(s.people.size()))
	_note("Prospects", str(s.prospects.size()))
	var head := String(s.calc[0]) if not s.calc.is_empty() else ""
	_note("Calculation", head.get_slice(" ", 0) if head.begins_with("#") else "")
	_note("Thoughts", str(s.thoughts.size()) if not s.thoughts.is_empty() else "")
	_apply_people(s.people, animate)
	_apply_prospects(s.prospects, animate)
	_apply_directives(String(s.directives))
	_apply_calc(s.calc, s.events)
	_apply_thoughts(s, animate)
	_apply_jokes(s.jokes, s.comeback)


func _apply_directives(text: String) -> void:
	_set_text(_directives, text if text != "" else "(nothing yet)")
	_set_color(_directives, TEXT if text != "" else DIM)


func _apply_header(s: Dictionary) -> void:
	_set_text(_clock_label, "live %s    t %.1f    event #%d" % [_clock_text(float(s.live_s)), float(s.t), int(s.seq)])
	var rung: Dictionary = s.rung
	var rung_name := String(rung.name)
	if not RUNGS.has(rung_name):
		push_error("MindPanel: unknown rung '%s'" % rung_name)
	_chip(_rung_chip, _rung_style, rung_name, RUNGS.get(rung_name, Color.MAGENTA))
	_rung_chip.visible = true
	_set_text(_rung_info, "for %s   composure %.2f   ceiling %.2f" % [_duration(float(rung.since_s)),
		float(rung.composure), float(rung.ceiling)])
	var move: Dictionary = s.move
	_set_text(_move_id, String(move.id) if String(move.id) != "" else "—")
	_set_text(_move_why, String(move.why))
	_move_why.tooltip_text = String(move.why)
	var crack: Dictionary = s.crack
	_set_text(_crack, "crack %d of %d used" % [int(crack.used), int(crack.budget)])
	_crack_chip.visible = String(crack.phase) != ""
	_set_text(_crack_chip, String(crack.phase))
	var timers: Dictionary = s.timers
	var running := PackedStringArray()
	for key: String in timers:
		# no-break spaces inside an item: a wrapped line never splits "felt real 1:00"
		running.append(("%s %s" % [key.replace("_", " "), _countdown(float(timers[key]))]).replace(" ", "\u00a0"))
	_timers_title.visible = not running.is_empty()
	_set_text(_timers, "  ·  ".join(running))
	var latency := _latency(s.timing)
	if latency != _timing_text:
		_timing_text = latency
		_timing.text = latency
	var errors := PackedStringArray()
	for e: Dictionary in s.errors:
		errors.append("%s  %s" % [_clock_text(float(e.t)), String(e.text)])
	_errors.visible = not errors.is_empty()
	_set_text(_errors, "\n".join(errors))


## The latency lines (BBCode): one per entry of LATENCY_LINES, each metric with
## its last value, then its p50 and p90 over the stream against the targets
## ("p50 1130 > 900" in red when over, "p90 1300 ≤ 1400" when not, "p50 ≤ 900"
## before anything is measured). Keys may be missing; timing keys the panel
## doesn't know are added at the end as they come.
func _latency(timing: Dictionary) -> String:
	var known := {}
	var lines := PackedStringArray()
	for metrics: Array in LATENCY_LINES:
		var parts := PackedStringArray()
		for metric: String in metrics:
			var last := metric + "_ms"
			known[last] = true
			var chunks := PackedStringArray([("%s %s" % [LATENCY_NAMES[metric],
				("%d ms" % int(timing[last])) if timing.has(last) else "—"]).replace(" ", "\u00a0")])
			for stat: String in ["p50", "p90"]:
				var key := "%s_%s_ms" % [metric, stat]
				var target_key := "target_" + key
				known[key] = true
				known[target_key] = true
				var chunk := ""
				if timing.has(key) and timing.has(target_key):
					var over := int(timing[key]) > int(timing[target_key])
					chunk = "%s [color=#%s]%d %s %d[/color]" % [stat, (ERROR if over else BRIGHT).to_html(false),
						int(timing[key]), ">" if over else "≤", int(timing[target_key])]
				elif timing.has(key):
					chunk = "%s %d" % [stat, int(timing[key])]
				elif timing.has(target_key):
					chunk = "[color=#%s]%s ≤ %d[/color]" % [DIM.to_html(false), stat, int(timing[target_key])]
				if chunk != "":
					chunks.append(chunk.replace(" ", "\u00a0"))
			parts.append("  ·  ".join(chunks))
		lines.append("     ".join(parts))
	for key: String in timing:
		if not known.has(key):
			lines[lines.size() - 1] += "     %s %s" % [key.replace("_", " "), str(timing[key])]
	return "\n".join(lines)


## Makes sure the group shows exactly these bars, in this order. Returns the ids of new bars.
func _sync_group(group: String, specs: Array) -> Dictionary:
	var ids: Array = specs.map(func(x: Dictionary) -> String: return String(x.id))
	var fresh := {}
	if _group_ids.get(group, []) == ids:
		return fresh
	var box: VBoxContainer = _bar_boxes[group]
	for id: String in _group_ids.get(group, []):
		if id not in ids:
			box.remove_child(_bars[id])
			_bars[id].queue_free()
			_bars.erase(id)
	for i in specs.size():
		var spec: Dictionary = specs[i]
		if not _bars.has(spec.id):
			_bars[spec.id] = _make_bar(spec)
			box.add_child(_bars[spec.id])
			fresh[spec.id] = true
		box.move_child(_bars[spec.id], i)
	_group_ids[group] = ids
	_line_up()
	return fresh


## One label column for every bar of the main column (the snapshot's bars and
## dead air), as wide as the longest label, so all the bars start at the same x.
func _line_up() -> void:
	var column: Array = _bars.values() + [_dead_air]
	var width := 0.0
	for bar: Bar in column:
		width = maxf(width, bar.label_size(bar.label) + 10.0)
	_label_column = width
	for bar: Bar in column:
		if bar.label_width != width:
			bar.label_width = width
			bar.queue_redraw()


func _make_bar(spec: Dictionary) -> Bar:
	var bar := Bar.new()
	bar.font_size = font_size
	bar.small_size = small_size
	var group := String(spec.group)
	var id := String(spec.id)
	bar.details = group in ["mood", "emotions"] or id == "wound.composure"  # from the start: rows never jump
	bar.label_width = _label_column
	bar.change_width = _change_column
	if float(spec.lo) < 0.0:
		bar.format = "%+.2f"
	var hint := "%s\n[%s, %s to %s]" % [String(spec.hint), id, _num(float(spec.lo)), _num(float(spec.hi))]
	if group == "emotions":
		hint += "\nbright: the fast part · dark: the slow tail · line under the bar: what her face shows"
	elif group == "mood":
		hint += "\ntick: her baseline · ▾ where her feelings are pulling the mood"
	elif id == "wound.composure":
		hint += "\nstrong ticks: she falls a rung below them · faint ticks: she climbs back above them · ▾ ceiling"
	bar.setup(String(spec.label), float(spec.lo), float(spec.hi), Color.html(String(spec.color)), hint)
	return bar


func _apply_bar(spec: Dictionary, s: Dictionary, animate: bool) -> void:
	var bar: Bar = _bars[spec.id]
	var id := String(spec.id)
	var group := String(spec.group)
	var fresh: bool = spec.last is Dictionary and int(s.seq) - int(spec.last.seq) <= 1
	bar.set_change(spec.last, fresh)
	if group == "emotions":
		bar.set_value(float(spec.v), float(spec.slow), animate)
		bar.set_shown(float(spec.shown), animate)
		var runs := _emotion_details(spec)
		bar.set_details(runs if not runs.is_empty() else [["—", SEP]])
		return
	bar.set_value(float(spec.v), -1.0, animate)
	if group == "mood":
		var target := float(s.mood_target[MOOD_AXES[id]])
		var base := float(spec.base)
		bar.set_ticks([[base, 0.85]])
		bar.set_markers([[target, bar.meter.color.lightened(0.35)]])
		bar.set_details([["heading " + _signed(target), TEXT], ["   rests at " + _signed(base), DIM]])
	elif id == "wound.composure":
		var rung: Dictionary = s.rung
		var ticks := []
		for x: Variant in rung.down:
			ticks.append([float(x), 0.8])
		for x: Variant in rung.up:
			ticks.append([float(x), 0.3])
		bar.set_ticks(ticks)
		bar.set_markers([[float(rung.ceiling), Color(0.88, 0.96, 1.0)]])
		bar.set_details([["ceiling %.2f" % float(rung.ceiling), TEXT],
			["   falls below %s / %s, climbs back at %s / %s" % [_num(float(rung.down[0])), _num(float(rung.down[1])),
				_num(float(rung.up[0])), _num(float(rung.up[1]))], DIM]])


func _emotion_details(spec: Dictionary) -> Array:
	var parts := []
	if String(spec.src) != "":
		parts.append([String(spec.src), SRC])
	if String(spec.rule) not in ["", "none"]:
		parts.append(["%s → shows %.2f" % [String(spec.rule), float(spec.shown)], RULE])
	if float(spec.v) >= 0.005:
		parts.append(["fast %.2f + slow %.2f" % [float(spec.fast), float(spec.slow)], DIM])
	var runs := []
	for i in parts.size():
		if i > 0:
			runs.append(["  ·  ", SEP])
		runs.append(parts[i])
	return runs


func _apply_dead_air(d: Dictionary) -> void:
	var gap := maxf(float(d.gap_s), 0.1)
	_dead_air.meter.setup(0.0, gap, _dead_air.meter.color)
	_dead_air_in = float(d.in_s)
	_dead_air.set_change_text("of %.0f s" % gap, DIM)


func _apply_people(people: Array, animate: bool) -> void:
	var names: Array = people.map(func(p: Dictionary) -> String: return String(p.name))
	var fresh := _sync_rows(_people_box, _people, names, _make_person)
	for who: String in _person_parts.keys():
		if not _people.has(who):
			_person_parts.erase(who)
	for p: Dictionary in people:
		var parts: Dictionary = _person_parts[String(p.name)]
		var jump: bool = not animate or fresh.has(String(p.name))
		for key: String in ["liking", "familiarity", "threat"]:
			parts.bars[key].set_value(float(p[key]), -1.0, not jump)
		var notes := PackedStringArray()
		if String(p.line) != "":
			notes.append("“%s”" % String(p.line))
		for kind: String in p.repeats:
			notes.append("%s ×%.2f" % [kind, float(p.repeats[kind])])
		if float(p.guilt_debt_s) > 0.0:
			notes.append("guilt debt %d s" % int(p.guilt_debt_s))
		if bool(p.latch):
			notes.append("honesty latch")
		var line: Label = parts.line
		_set_text(line, "   ".join(notes))
		line.visible = not notes.is_empty()


func _apply_prospects(list: Array, animate: bool) -> void:
	var keys: Array = list.map(func(p: Dictionary) -> String: return "%s|%s|%s" % [p.kind, p.who, p.note])
	var fresh := _sync_rows(_prospect_box, _prospects, keys, _make_prospect)
	for i in list.size():
		var p: Dictionary = list[i]
		var bar: Bar = _prospects[keys[i]]
		bar.set_value(float(p.q), -1.0, animate and not fresh.has(keys[i]))
		bar.set_change_text("open" if p.ttl_s == null else "%d s left" % ceili(float(p.ttl_s)), DIM)
		var runs := []
		if String(p.note) != "":
			runs.append(["“%s”" % String(p.note), TEXT])
		runs.append([("   " if not runs.is_empty() else "") + "opened %s ago" % _duration(float(p.age_s)), DIM])
		bar.set_details(runs)


func _apply_calc(lines: Array, events: Array) -> void:
	if lines != _calc_lines:
		_calc_lines = lines.duplicate()
		_pool(_calc_box, lines.size(), _make_calc_row)
		# A rule's row is "name      the rest": the engine pads the name to 10 characters
		# and adds a space, so the rest starts at column 11 or later ("embarrassment +0.11"
		# too). Anything else ("got away with it: ...", "#12 jo: ...") is a line of its own.
		var parsed := []
		var column := CALC_COLUMN
		for line: Variant in lines:
			var m := _calc_split.search(String(line))
			if String(line).begins_with("#") or m == null \
					or m.get_string(1).length() + m.get_string(2).length() < CALC_COLUMN:
				m = null
			else:
				column = maxi(column, m.get_string(1).length() + 1)
			parsed.append(m)
		var name_width := _mono.get_string_size("x".repeat(column), HORIZONTAL_ALIGNMENT_LEFT, -1, small_size).x
		for i in lines.size():
			var row := _calc_box.get_child(i)
			var name_label: Label = row.get_child(0)
			var rest: Label = row.get_child(1)
			var line := String(lines[i])
			var m: RegExMatch = parsed[i]
			name_label.visible = m != null
			if name_label.custom_minimum_size.x != name_width:
				name_label.custom_minimum_size.x = name_width
			name_label.text = m.get_string(1) if m != null else ""
			rest.text = m.get_string(3) if m != null else line
			_set_color(rest, BRIGHT if line.begins_with("#") else TEXT)
	if events != _events_data:
		_events_data = events.duplicate()
		var out := PackedStringArray()
		for i in range(events.size() - 1, -1, -1):
			var ev: Dictionary = events[i]
			var tops := PackedStringArray()
			for change: Variant in ev.top:
				var c := String(change)
				tops.append("[color=#%s]%s[/color]" % [(Bar.FALL if " -" in c else Bar.RISE).to_html(false), _bb(c)])
			var gist := _bb(String(ev.gist))
			if bool(ev.error):
				gist = "[color=#%s]%s[/color]" % [ERROR.to_html(false), gist]
			elif tops.is_empty():
				gist = "[color=#%s]%s[/color]" % [DIM.to_html(false), gist]
			out.append("[color=#%s]#%d %s[/color]  %s%s" % [DIM.to_html(false), int(ev.seq), _clock_text(float(ev.t)),
				gist, ("   " + "  ".join(tops)) if not tops.is_empty() else ""])
		_events.text = "\n".join(out) if not out.is_empty() else "[color=#%s](no events yet)[/color]" % DIM.to_html(false)


func _apply_thoughts(s: Dictionary, animate: bool) -> void:
	var thoughts: Array = s.thoughts
	var keys: Array = thoughts.map(func(t: Dictionary) -> String: return String(t.text))
	var fresh := _sync_rows(_thought_box, _thoughts, keys, _make_thought)
	for key: String in _thought_parts.keys():
		if not _thoughts.has(key):
			_thought_parts.erase(key)
	for t: Dictionary in thoughts:
		var parts: Dictionary = _thought_parts[String(t.text)]
		_set_text(parts.tone, String(t.tone) if String(t.tone) != "" else "—")
		_set_text(parts.topic, String(t.topic))
		parts.salience.set_value(float(t.salience), -1.0, animate and not fresh.has(String(t.text)))
		_set_text(parts.ttl, "%d s left" % int(t.ttl_s))
		_set_text(parts.private, "private: " + String(t.private))
		parts.private.visible = String(t.private) != ""
	_thought_box.visible = not thoughts.is_empty()
	_no_thoughts.visible = thoughts.is_empty()
	var topics: Array = s.intrusions.map(func(pair: Array) -> String: return String(pair[0]))
	var fresh_topics := _sync_rows(_intrusion_box, _intrusions, topics, _make_intrusion)
	for pair: Array in s.intrusions:
		_intrusions[String(pair[0])].set_value(float(pair[1]), -1.0, animate and not fresh_topics.has(String(pair[0])))
	_intrusion_title.visible = not topics.is_empty()
	var late: Variant = s.late_comeback
	_comeback.visible = late != null
	if late != null:
		if String(late.line) != "":
			_set_text(_comeback, "late comeback for %s, ready: “%s”" % [late["for"], late.line])
			_set_color(_comeback, BRIGHT)
		else:
			_set_text(_comeback, "late comeback for %s: comes to her in %s" % [late["for"], _duration(float(late.due_s))])
			_set_color(_comeback, DIM)


func _apply_jokes(jokes: Dictionary, comeback: Dictionary) -> void:
	var waiting := float(comeback.cooldown_s) > 0.0 or int(comeback.replies_left) > 0
	var shape := String(comeback.last_shape)
	_set_text(_misfire, ("misfire cooldown  %s · %d replies left" % [_duration(float(comeback.cooldown_s)),
		int(comeback.replies_left)] if waiting else "misfire cooldown  none") + ("    last shape  " + shape if shape != "" else ""))
	_set_color(_misfire, WARN if waiting else DIM)
	var last: Variant = jokes.last
	if last == null:
		_set_text(_joke, "(no jokes yet)")
		_set_color(_joke, DIM)
		_joke_verdict.visible = false
	else:
		_set_text(_joke, "last  “%s”   %s" % [last.text, last.shape])
		_set_color(_joke, TEXT)
		_joke_verdict.visible = true
		var verdict := String(last.verdict).replace("_", " ")
		_set_text(_joke_verdict, "she thinks %.2f  /  chat: %s" % [float(last.her_rating), verdict if verdict != "" else "—"])
	var proud: Array = jokes.proud
	_proud.visible = not proud.is_empty()
	_set_text(_proud, "proud of:\n" + "\n".join(PackedStringArray(proud.map(func(x: Variant) -> String: return "  • " + String(x)))))


## Her mind's body values, as plain numbers: the snapshot sends them without
## ranges, rests or hints, so they aren't drawn as bars.
func _apply_body(body: Dictionary) -> void:
	if body.keys() != _body_keys:
		_body_keys = body.keys()
		_body_rows()
	for key: String in body:
		var cell: Label = _body_cells[key][0]
		if body[key] is bool:
			_set_text(cell, "yes" if body[key] else "no")
			_set_color(cell, WARN if body[key] else TEXT)
		else:
			_set_text(cell, _plain(float(body[key])))


func _show_status() -> void:
	while not _arrivals.is_empty() and _clock - _arrivals[0] > 2.0:
		_arrivals.pop_front()  # the rate below counts the last 2 s
	if _snapshot.is_empty():
		_set_text(_status, "waiting for the brain…")
		_set_color(_status, WARN)
	elif _clock - _received_at > 3.0:
		_set_text(_status, "no update for %d s" % int(_clock - _received_at))
		_set_color(_status, ERROR)
	else:
		_set_text(_status, "%.1f / s" % (_arrivals.size() / 2.0))
		_set_color(_status, DIM)


# --- building ----------------------------------------------------------------

func _build_header(body: VBoxContainer) -> void:
	# Every row here wraps or clips: the header never makes the panel wider.
	var top := _hbox(6)
	_clock_label = _label(font_size, BRIGHT)
	_status = _label(small_size, DIM)
	_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	top.add_child(_clock_label)
	top.add_child(_status)
	body.add_child(top)

	var rung := _hbox(6)
	_rung_chip = _label(small_size, Color.WHITE)
	_rung_chip.add_theme_stylebox_override("normal", _rung_style)
	_rung_chip.visible = false
	_rung_info = _label(small_size, TEXT)
	_rung_info.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_rung_info.clip_text = true
	_rung_info.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	rung.add_child(_rung_chip)
	rung.add_child(_rung_info)
	body.add_child(rung)
	_hint(_rung_chip, "her rung: composed (green), strained (amber), overwhelmed (red), crack (violet)\n"
		+ "she falls a rung at once; climbing back needs a margin and a while on the rung")
	_hint(_rung_info, "how long she's been on this rung; composure, and the ceiling it can recover to")

	var move := _hbox(6)
	var move_title := _label(small_size, DIM)
	move_title.text = "move"
	move_title.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_move_id = _label(font_size, BRIGHT)
	_move_id.text = "—"
	_move_id.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_move_why = _label(small_size, DIM)  # one line (the whole reason on hover), so the header keeps its height
	_move_why.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_move_why.clip_text = true
	_move_why.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	_move_why.mouse_filter = Control.MOUSE_FILTER_PASS
	for node: Control in [move_title, _move_id, _move_why]:
		move.add_child(node)
	body.add_child(move)

	# The crack, then the timers still running (on the same row: they come and go
	# without moving the panel).
	var crack := _hbox(6)
	_crack = _label(small_size, TEXT)
	_crack.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_crack_chip = _label(small_size, Color.WHITE)
	_crack_chip.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	var crack_style := StyleBoxFlat.new()
	_chip(_crack_chip, crack_style, "", RUNGS.crack)
	_crack_chip.add_theme_stylebox_override("normal", crack_style)
	_crack_chip.visible = false
	_timers_title = _label(small_size, DIM)
	_timers_title.text = "   timers"
	_timers_title.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_timers = _label(small_size, TEXT, true)
	for node: Control in [_crack, _crack_chip, _timers_title, _timers]:
		crack.add_child(node)
	body.add_child(crack)
	_hint(_crack, "cracks this stream: used of the budget (the act slipping for a moment)")
	_hint(_crack_chip, "the crack's phase: freeze, leak, re-mask, covering")
	_hint(_timers, "what is still running, and the time left: quiet (the exhausted quiet), afterglow and felt real"
		+ " (after a scare), buffer (social buffering), covering (after a crack)")

	var latency := _hbox(6)
	var latency_title := _label(small_size, DIM)
	latency_title.text = "latency"
	latency_title.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	_timing = RichTextLabel.new()
	_timing.bbcode_enabled = true
	_timing.fit_content = true
	_timing.scroll_active = false
	_timing.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_timing.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_timing.add_theme_font_size_override("normal_font_size", small_size)
	_timing.add_theme_color_override("default_color", TEXT)
	_timing.add_theme_constant_override("line_separation", 0)
	_hint(_timing, "the last latencies in ms: appraisal (her mind reading the message), the actor's first sentence,"
		+ " first audio; p50 and p90 over this stream against her targets (red: over the target)")
	latency.add_child(latency_title)
	latency.add_child(_timing)
	body.add_child(latency)
	_errors = _label(small_size, ERROR, true)
	_errors.visible = false
	body.add_child(_errors)


func _build_dead_air(body: VBoxContainer) -> void:
	_dead_air = Bar.new()
	_dead_air.font_size = font_size
	_dead_air.small_size = small_size
	_dead_air.format = "%.1f"
	_dead_air.change_width = _change_column
	_dead_air.meter.effects = false
	_dead_air.setup("dead air in", 0.0, 30.0, Color(0.55, 0.6, 0.72),
		"seconds until she fills the silence herself (the gap grows each time nobody answers)")
	body.add_child(_dead_air)


func _build_people(body: VBoxContainer) -> void:
	var head := _hbox(4)
	for title: String in ["who", "liking", "familiarity", "threat"]:
		var l := _label(small_size, DIM)
		l.text = title
		if title == "who":
			l.custom_minimum_size.x = 70.0
		else:
			l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		head.add_child(l)
	body.add_child(head)
	_people_box.add_theme_constant_override("separation", 1)
	body.add_child(_people_box)


func _make_person(person_name: String) -> Control:
	var row := _vbox(0)
	var line := _hbox(4)
	var who := _label(font_size, BRIGHT)
	who.text = person_name
	who.custom_minimum_size.x = 70.0
	who.clip_text = true
	who.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	line.add_child(who)
	var bars := {}
	for spec: Array in [["liking", -1.0, 1.0, Color(1.0, 0.62, 0.74), "how much she likes them (-1 to 1)"],
			["familiarity", 0.0, 1.0, Color(0.6, 0.76, 1.0), "how much they've talked with her (0 to 1)"],
			["threat", 0.0, 1.0, Color(0.9, 0.3, 0.32), "how much they remind her of what she is (0 to 1)"]]:
		var bar := Bar.new()
		bar.font_size = small_size
		bar.small_size = small_size
		bar.label_width = 0.0
		bar.value_width = 32.0
		bar.change_width = 0.0
		bar.bar_height = 6.0
		bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		if float(spec[1]) < 0.0:
			bar.format = "%+.2f"
		bar.setup("", spec[1], spec[2], spec[3], "%s: %s" % [person_name, spec[4]])
		line.add_child(bar)
		bars[spec[0]] = bar
	row.add_child(line)
	var notes := _label(small_size, DIM, true)
	row.add_child(notes)
	_person_parts[person_name] = {"bars": bars, "line": notes}
	return row


func _make_prospect(key: String) -> Control:
	var parts := key.split("|", true, 2)
	var kind := parts[0]
	var bar := Bar.new()
	bar.font_size = font_size
	bar.small_size = small_size
	bar.details = true
	bar.label_width = 120.0
	bar.change_width = 70.0
	var color: Color = PROSPECT_COLORS[kind] if PROSPECT_COLORS.has(kind) else Color.from_hsv(
		float(posmod(hash(kind), 360)) / 360.0, 0.5, 0.95)
	bar.setup(kind + (" · " + parts[1] if parts[1] != "" else ""), 0.0, 1.0, color,
		"something that might still happen: %s; the bar is q, how strongly it's expected or feared" % kind)
	return bar


func _build_directives(body: VBoxContainer) -> void:
	_directives = _label(font_size, TEXT, true)
	body.add_child(_directives)


func _build_calc(body: VBoxContainer) -> void:
	_calc_box.add_theme_constant_override("separation", 0)
	body.add_child(_calc_box)
	var title := _label(small_size, DIM)
	title.text = "recent events (newest first)"
	body.add_child(title)
	_events = RichTextLabel.new()
	_events.bbcode_enabled = true
	_events.fit_content = true
	_events.scroll_active = false
	_events.mouse_filter = Control.MOUSE_FILTER_PASS  # the wheel scrolls the panel
	_events.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_events.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_events.add_theme_font_size_override("normal_font_size", small_size)
	_events.add_theme_color_override("default_color", TEXT)
	_events.add_theme_constant_override("line_separation", 1)
	body.add_child(_events)


func _make_calc_row() -> Control:
	var row := _hbox(0)
	var name_label := _label(small_size, Color(0.72, 0.66, 0.86))
	name_label.add_theme_font_override("font", _mono)
	name_label.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	var rest := _label(small_size, TEXT, true)
	rest.add_theme_font_override("font", _mono)
	row.add_child(name_label)
	row.add_child(rest)
	return row


func _build_thoughts(body: VBoxContainer) -> void:
	_thought_box.add_theme_constant_override("separation", 4)
	body.add_child(_thought_box)
	_no_thoughts = _label(small_size, DIM)
	_no_thoughts.text = "(nothing on her mind)"
	body.add_child(_no_thoughts)
	_intrusion_title = _label(small_size, DIM)
	_intrusion_title.text = "pushed away, pressing to come back"
	_intrusion_title.visible = false
	body.add_child(_intrusion_title)
	body.add_child(_intrusion_box)
	_comeback = _label(small_size, DIM, true)
	_comeback.visible = false
	body.add_child(_comeback)


func _make_thought(text: String) -> Control:
	var row := _vbox(0)
	var head := _hbox(6)
	var tone := _label(small_size, Color(0.1, 0.06, 0.14))
	var tone_style := StyleBoxFlat.new()
	_chip(tone, tone_style, "", Color(0.76, 0.6, 1.0))
	tone.add_theme_stylebox_override("normal", tone_style)
	var topic := _label(small_size, SRC)
	topic.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	topic.clip_text = true
	topic.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	topic.tooltip_text = "the topic: all the actor may see of this thought"
	topic.mouse_filter = Control.MOUSE_FILTER_PASS
	var salience := Bar.new()
	salience.font_size = small_size
	salience.small_size = small_size
	salience.label_width = 0.0
	salience.value_width = 30.0
	salience.change_width = 0.0
	salience.bar_height = 6.0
	salience.custom_minimum_size.x = 96.0
	salience.setup("", 0.0, 1.0, Color(0.76, 0.6, 1.0), "salience: how much it's on her mind (gone below 0.2)")
	var ttl := _label(small_size, DIM)
	ttl.custom_minimum_size.x = 56.0
	ttl.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	for node: Control in [tone, topic, salience, ttl]:
		head.add_child(node)
	row.add_child(head)
	var thought := _label(font_size, BRIGHT, true)
	thought.text = text
	row.add_child(thought)
	var private_line := _label(small_size, PRIVATE, true)
	row.add_child(private_line)
	_thought_parts[text] = {"tone": tone, "topic": topic, "salience": salience, "ttl": ttl, "private": private_line}
	return row


func _make_intrusion(topic: String) -> Control:
	var bar := Bar.new()
	bar.font_size = small_size
	bar.small_size = small_size
	bar.label_width = 120.0
	bar.change_width = 0.0
	bar.bar_height = 6.0
	bar.setup(topic, 0.0, 1.0, Color(0.9, 0.55, 0.75), "a topic she dodged, pressing to come back as a thought")
	return bar


func _build_jokes(body: VBoxContainer) -> void:
	_joke = _label(font_size, TEXT, true)
	body.add_child(_joke)
	_joke_verdict = _label(small_size, Color(1.0, 0.82, 0.45))
	_joke_verdict.visible = false
	body.add_child(_joke_verdict)
	_misfire = _label(small_size, DIM, true)
	_hint(_misfire, "after a misfired comeback she waits this long, and this many of her replies, before the next one")
	body.add_child(_misfire)
	_proud = _label(small_size, TEXT, true)
	_proud.visible = false
	body.add_child(_proud)


func _build_face(body: VBoxContainer) -> void:
	var title := _label(small_size, DIM)
	title.text = "face shapes as face.gd wrote them this frame"
	body.add_child(title)
	_face_grid = GridContainer.new()
	_face_grid.columns = 2
	_face_grid.add_theme_constant_override("h_separation", 10)
	_face_grid.add_theme_constant_override("v_separation", 0)
	body.add_child(_face_grid)
	var body_title := _label(small_size, DIM, true)
	body_title.text = "body: her mind's values (the snapshot) and the avatar's own, live"
	body.add_child(body_title)
	_body_grid = GridContainer.new()
	_body_grid.columns = 3
	_body_grid.add_theme_constant_override("h_separation", 16)
	_body_grid.add_theme_constant_override("v_separation", 0)
	body.add_child(_body_grid)
	_body_rows()


## A model loaded: one bar for each brow, eye and mouth shape its face speaks,
## and the avatar's body read-outs from its rig.
func _on_model_loaded(parts: ModelParts) -> void:
	_rig = parts.rig
	for child in _face_grid.get_children():
		_face_grid.remove_child(child)
		child.queue_free()
	_face_bars.clear()
	var shapes := face.shape_names()
	for i in shapes.size():
		var shape := shapes[i]
		for prefix: String in FACE_PREFIXES:
			if shape.begins_with(prefix):
				var bar := Bar.new()
				bar.font_size = small_size
				bar.small_size = small_size
				bar.label_width = 112.0
				bar.value_width = 30.0
				bar.change_width = 0.0
				bar.bar_height = 5.0
				bar.meter.effects = false
				bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
				bar.setup(shape.trim_prefix("Fcl_"), 0.0, 1.0, FACE_COLORS[prefix], shape)
				_face_grid.add_child(bar)
				_face_bars.append([bar, i])
	_body_rows()


## The body grid: one row per body key of the snapshot (in its order), then the
## avatar's read-outs that have no snapshot key. Rebuilt only when the keys change
## or a model loads.
func _body_rows() -> void:
	for child in _body_grid.get_children():
		_body_grid.remove_child(child)
		child.queue_free()
	_body_cells.clear()
	for title: String in ["", "her mind", "avatar now"]:
		var head := _label(small_size, DIM)
		head.text = title
		head.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		_body_grid.add_child(head)
	var live := _avatar_body()
	var keys := _body_keys.duplicate()
	for key: String in live:
		if key not in keys:
			keys.append(key)
	for key: String in keys:
		var title := _label(small_size, TEXT)
		title.text = key.replace("_", " ")
		title.custom_minimum_size.x = 130.0
		var mind_value := _label(font_size, BRIGHT)
		var avatar_value := _label(font_size, BRIGHT)
		for cell: Label in [mind_value, avatar_value]:
			cell.custom_minimum_size.x = 64.0
			cell.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		if key in _body_keys:
			_hint(mind_value, "body.%s in the snapshot (her mind)" % key)
		if live.has(key):
			_hint(avatar_value, "the avatar's read-out, this frame (after the brain's adjustments, ramps and freezes)")
		for cell: Label in [title, mind_value, avatar_value]:
			_body_grid.add_child(cell)
		_body_cells[key] = [mind_value, avatar_value]


## Show only these sections (the demo walks through them one at a time); the
## others are hidden, title and all. An empty list shows every section again.
func focus(titles: Array) -> void:
	for title: String in _sections:
		var shown := titles.is_empty() or title in titles
		(_sections[title].button as Control).visible = shown
		(_sections[title].body as Control).visible = shown
		_section_text(title)
	_scroll.scroll_vertical = 0


## A section's title and body, in global (canvas) coordinates: the demo outlines it.
func section_rect(title: String) -> Rect2:
	if not _sections.has(title):
		push_error("MindPanel: no section '%s' (there are: %s)" % [title, ", ".join(_sections.keys())])
		return Rect2()
	var s: Dictionary = _sections[title]
	var rect := (s.button as Control).get_global_rect()
	if (s.body as Control).visible:
		rect = rect.merge((s.body as Control).get_global_rect())
	return rect


func _add_section(title: String, note := "") -> VBoxContainer:
	var button := Button.new()
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.focus_mode = Control.FOCUS_NONE
	button.mouse_filter = Control.MOUSE_FILTER_PASS
	button.add_theme_font_size_override("font_size", font_size)
	_set_color(button, TITLE)
	button.add_theme_color_override("font_hover_color", BRIGHT)
	button.add_theme_color_override("font_pressed_color", TITLE)
	button.add_theme_color_override("font_hover_pressed_color", BRIGHT)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0, 0, 0, 0)
	style.border_color = Color(1, 1, 1, 0.1)
	style.border_width_bottom = 1
	style.content_margin_top = 4.0
	style.content_margin_bottom = 1.0
	var hover := style.duplicate() as StyleBoxFlat
	hover.bg_color = Color(1, 1, 1, 0.05)
	for state: String in ["normal", "pressed", "focus", "disabled"]:
		button.add_theme_stylebox_override(state, style)
	for state: String in ["hover", "hover_pressed"]:
		button.add_theme_stylebox_override(state, hover)
	var body := _vbox(1)
	button.pressed.connect(func() -> void:
		body.visible = not body.visible
		_section_text(title))
	_content.add_child(button)
	_content.add_child(body)
	_sections[title] = {"button": button, "body": body, "note": note}
	_section_text(title)
	return body


## Replace a section title's note (the demo drops the key hints).
func set_note(title: String, note: String) -> void:
	_note(title, note)


func _note(title: String, note: String) -> void:
	if _sections[title].note != note:
		_sections[title].note = note
		_section_text(title)


func _section_text(title: String) -> void:
	var s: Dictionary = _sections[title]
	var note := String(s.note)
	s.button.text = ("▾ " if s.body.visible else "▸ ") + title + ("    " + note if note != "" else "")


func _make_theme() -> Theme:
	var t := Theme.new()
	t.default_font_size = font_size
	t.set_color("font_color", "Label", TEXT)
	t.set_constant("line_spacing", "Label", 0)
	var track := StyleBoxFlat.new()
	track.bg_color = Color(1, 1, 1, 0.04)
	track.set_corner_radius_all(3)
	track.content_margin_left = 3.0
	track.content_margin_right = 2.0
	var grab := StyleBoxFlat.new()
	grab.bg_color = Color(1, 1, 1, 0.22)
	grab.set_corner_radius_all(3)
	var grab_hover := grab.duplicate() as StyleBoxFlat
	grab_hover.bg_color = Color(1, 1, 1, 0.4)
	t.set_stylebox("scroll", "VScrollBar", track)
	t.set_stylebox("scroll_focus", "VScrollBar", track)
	t.set_stylebox("grabber", "VScrollBar", grab)
	t.set_stylebox("grabber_highlight", "VScrollBar", grab_hover)
	t.set_stylebox("grabber_pressed", "VScrollBar", grab_hover)
	# Hints: opaque, so the panel's text doesn't show through them.
	var tip := StyleBoxFlat.new()
	tip.bg_color = Color(0.07, 0.05, 0.1, 0.97)
	tip.border_color = Color(1.0, 1.0, 1.0, 0.18)
	tip.set_border_width_all(1)
	tip.set_corner_radius_all(4)
	tip.set_content_margin_all(6.0)
	t.set_stylebox("panel", "TooltipPanel", tip)
	t.set_font_size("font_size", "TooltipLabel", 12)
	t.set_color("font_color", "TooltipLabel", TEXT)
	return t


# --- helpers -------------------------------------------------------------------

## One row per key in `box`, in the order of `keys`: missing rows are made with
## `make` (key -> Control), rows whose key is gone are dropped, and rows keep
## their state (ghosts, glows) when the order changes. Returns the new keys.
func _sync_rows(box: Container, rows: Dictionary, keys: Array, make: Callable) -> Dictionary:
	var fresh := {}
	for key: Variant in rows.keys():
		if key not in keys:
			var gone: Control = rows[key]
			box.remove_child(gone)
			gone.queue_free()
			rows.erase(key)
	for i in keys.size():
		var key: Variant = keys[i]
		if not rows.has(key):
			rows[key] = make.call(key)
			box.add_child(rows[key])
			fresh[key] = true
		if rows[key].get_index() != i:
			box.move_child(rows[key], i)
	return fresh


## Keeps exactly `count` rows in `box` (rows are reused; only the count changes them).
func _pool(box: Container, count: int, make: Callable) -> void:
	while box.get_child_count() < count:
		box.add_child(make.call())
	while box.get_child_count() > count:
		var last := box.get_child(box.get_child_count() - 1)
		box.remove_child(last)
		last.queue_free()


func _chip(label: Label, style: StyleBoxFlat, text: String, color: Color) -> void:
	if style.bg_color != color:
		style.bg_color = color
	if style.content_margin_left != 5.0:
		style.set_corner_radius_all(3)
		style.content_margin_left = 5.0
		style.content_margin_right = 5.0
	_set_color(label, Color(0.08, 0.05, 0.1) if color.get_luminance() > 0.45 else Color.WHITE)
	_set_text(label, text)


func _label(px := 0, color := TEXT, wrap := false) -> Label:
	var label := Label.new()
	if px > 0:
		label.add_theme_font_size_override("font_size", px)
	_set_color(label, color)
	if wrap:
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label


func _vbox(separation: int) -> VBoxContainer:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", separation)
	return box


func _hbox(separation: int) -> HBoxContainer:
	var box := HBoxContainer.new()
	box.add_theme_constant_override("separation", separation)
	return box


func _hint(control: Control, text: String) -> void:
	control.tooltip_text = text
	control.mouse_filter = Control.MOUSE_FILTER_PASS


func _set_text(label: Label, text: String) -> void:
	if label.text != text:
		label.text = text


## Changing a theme override re-lays out the panel, so only when it's different.
func _set_color(control: Control, color: Color) -> void:
	if not control.has_theme_color_override("font_color") or control.get_theme_color("font_color") != color:
		control.add_theme_color_override("font_color", color)


static func _clock_text(seconds: float) -> String:
	return "%d:%04.1f" % [int(seconds / 60.0), fmod(seconds, 60.0)]


static func _duration(seconds: float) -> String:
	if seconds < 60.0:
		return "%.1f s" % seconds
	return "%d min %d s" % [int(seconds / 60.0), int(fmod(seconds, 60.0))]


## Time left as m:ss (2:59, 0:07).
static func _countdown(seconds: float) -> String:
	var whole := ceili(seconds)
	return "%d:%02d" % [floori(whole / 60.0), whole % 60]


## A plain number: one decimal from 10 up (blinks, breaths per minute), else two.
static func _plain(x: float) -> String:
	return ("%.1f" if absf(x) >= 10.0 else "%.2f") % (x if absf(x) >= 0.005 else 0.0)


static func _num(x: float) -> String:
	return "%.2f" % x


## +0.15 / -0.12 / +0.00 (never -0.00).
static func _signed(x: float) -> String:
	return "%+.2f" % (x if absf(x) >= 0.005 else 0.0)


## Text for BBCode: a "[" in chat or in her lines is shown, not parsed.
static func _bb(text: String) -> String:
	return text.replace("[", "[lb]")
