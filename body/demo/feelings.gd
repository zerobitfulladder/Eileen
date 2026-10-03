extends PanelContainer
## The demo's feelings, big: every emotion she has right now (the strongest
## first), from her mind's snapshots. The bar is what she feels, its slow tail
## darker under the fast part (lengths on a square-root scale, so small feelings
## still read; the numbers are the real values); the white tick is how much of it her face shows
## (her display rules: a hidden feeling sits far below its tick, a loved thing
## can show more than it is). Under each: where it came from, and the rule.

const Style := preload("res://demo/style.gd")
const MIN := 0.02  # weaker feelings aren't listed
const ROWS := 6
const EASE := 10.0  # per second: bars glide to the snapshot's values

var _list := VBoxContainer.new()
var _none := Style.label(17, Style.DIM)
var _rows := {}  # emotion -> {"row": VBoxContainer, "bar": Control, "value": Label, "why": Label, "goal": Dictionary, "now": Dictionary}
var _mono := SystemFont.new()


func _ready() -> void:
	_mono.font_names = PackedStringArray(["DejaVu Sans Mono"])
	add_theme_stylebox_override("panel", Style.panel())
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	var head := HBoxContainer.new()
	var title := Style.label(16, Style.TITLE, 700)
	title.text = "FEELINGS"
	var key := Style.label(13, Style.DIM)
	key.text = "    bar: felt (√ scale)    tick: shown on her face"
	head.add_child(title)
	head.add_child(key)
	box.add_child(head)
	_list.add_theme_constant_override("separation", 7)
	box.add_child(_list)
	_none.text = "nothing felt right now"
	box.add_child(_none)
	add_child(box)


## A {"type": "mind"} snapshot from the brain.
func update(snapshot: Dictionary) -> void:
	var active := []
	for bar: Dictionary in snapshot.get("bars", []):
		if bar.get("group") == "emotions" and float(bar.v) >= MIN:
			active.append(bar)
	active.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return float(a.v) > float(b.v))
	active = active.slice(0, ROWS)
	var names := active.map(func(bar: Dictionary) -> String: return String(bar.label))
	for emotion: String in _rows.keys():
		if emotion not in names:
			(_rows[emotion].row as Node).queue_free()
			_rows.erase(emotion)
	for i in active.size():
		var bar: Dictionary = active[i]
		var emotion := String(bar.label)
		if not _rows.has(emotion):
			_rows[emotion] = _make_row(emotion, Color.html(String(bar.color)))
		var r: Dictionary = _rows[emotion]
		r.goal = {"v": float(bar.v), "fast": float(bar.get("fast", 0.0)), "slow": float(bar.get("slow", 0.0)),
			"shown": float(bar.get("shown", 0.0))}
		var src := String(bar.get("src", ""))
		var rule := String(bar.get("rule", ""))
		(r.why as Label).text = "%s%s" % [src if src else "–", ("   · " + rule) if rule else ""]
		_list.move_child(r.row, i)
	_none.visible = active.is_empty()


func _make_row(emotion: String, color: Color) -> Dictionary:
	var row := VBoxContainer.new()
	row.add_theme_constant_override("separation", 1)
	var line := HBoxContainer.new()
	line.add_theme_constant_override("separation", 10)
	var name_label := Style.label(20, color.lightened(0.25), 700)
	name_label.text = emotion
	name_label.custom_minimum_size.x = 150.0
	var bar := Control.new()
	bar.custom_minimum_size = Vector2(0, 22)
	bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bar.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	var value := Style.label(18, Style.TEXT, 600)
	value.custom_minimum_size.x = 52.0
	value.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	line.add_child(name_label)
	line.add_child(bar)
	line.add_child(value)
	var why := Label.new()
	why.add_theme_font_override("font", _mono)
	why.add_theme_font_size_override("font_size", 12)
	why.add_theme_color_override("font_color", Style.DIM)
	why.clip_text = true
	why.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	row.add_child(line)
	row.add_child(why)
	_list.add_child(row)
	var r := {"row": row, "bar": bar, "value": value, "why": why, "color": color,
		"goal": {"v": 0.0, "fast": 0.0, "slow": 0.0, "shown": 0.0},
		"now": {"v": 0.0, "fast": 0.0, "slow": 0.0, "shown": 0.0}}
	bar.draw.connect(_draw_bar.bind(r))
	return r


func _process(delta: float) -> void:
	var k := 1.0 - exp(-EASE * delta)
	for emotion: String in _rows:
		var r: Dictionary = _rows[emotion]
		for key: String in r.now:
			r.now[key] = lerpf(r.now[key], r.goal[key], k)
		(r.value as Label).text = "%.2f" % r.now.v
		(r.bar as Control).queue_redraw()


func _draw_bar(r: Dictionary) -> void:
	var bar: Control = r.bar
	var w := bar.size.x
	var h := bar.size.y
	var color: Color = r.color
	bar.draw_rect(Rect2(0, 0, w, h), Color(1, 1, 1, 0.06))
	var v := sqrt(clampf(r.now.v, 0.0, 1.0))
	var slow := v * clampf(r.now.slow / maxf(r.now.v, 0.001), 0.0, 1.0)  # the slow tail's share of the bar
	bar.draw_rect(Rect2(0, 0, w * slow, h), color.darkened(0.45))
	bar.draw_rect(Rect2(w * slow, 0, w * (v - slow), h), color.lightened(0.1))
	var shown := sqrt(clampf(r.now.shown, 0.0, 1.0))
	bar.draw_rect(Rect2(w * shown - 1.5, -4, 3, h + 8), Color(1, 1, 1, 0.95))
