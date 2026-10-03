extends Control
## The event lane of the mind panel: her body events of the last 30 s
## (understanding, freeze, felt display, leak, thought, glitch...) as ticks on
## a timeline, now at the right edge. Each tick is labeled with its kind and
## name; a label sits left of its tick, in the first of ROWS rows where it
## doesn't run into another label, and keeps that row while it scrolls by.

const SPAN := 30.0
const ROWS := 3
const KIND_COLORS := {
	"understanding": Color(0.45, 0.85, 1.0), "freeze": Color(0.85, 0.92, 1.0), "felt": Color(1.0, 0.76, 0.32),
	"leak": Color(1.0, 0.48, 0.7), "squelch": Color(0.7, 0.7, 0.75), "put_on": Color(0.55, 0.9, 0.55),
	"hesitation": Color(0.62, 0.7, 0.86), "slip": Color(1.0, 0.6, 0.3), "thought": Color(0.76, 0.6, 1.0),
	"glitch": Color(1.0, 0.32, 0.32), "flinch": Color(0.95, 0.9, 0.55), "social": Color(0.5, 0.9, 0.8),
}
const NAME := Color(0.8, 0.78, 0.84)
const GRID := Color(1.0, 1.0, 1.0, 0.08)
const AXIS := Color(0.55, 0.53, 0.6)
const BACKING := Color(0.05, 0.03, 0.08, 0.8)

var font_size := 11
## Stream time at the right edge (seconds since the stream started).
var now := 0.0

var _events: Array = []  # [{t, kind, name}]
var _rows := {}  # "t|kind|name" -> row of its label (-1: no room, tick only)
var _shaped := {}  # "size|text" -> TextLine (text is shaped once, not every frame)
var _used := {}
var _font: Font


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_PASS
	clip_contents = true
	_font = get_theme_default_font()
	custom_minimum_size.y = ROWS * (font_size + 4) + font_size + 8
	tooltip_text = "Her body events of the last 30 s, now at the right."


func set_events(events: Array) -> void:
	_events = events
	var keys := {}
	for ev: Dictionary in events:
		keys[_key(ev)] = true
	for key: String in _rows.keys():
		if not keys.has(key):
			_rows.erase(key)
	queue_redraw()


func _draw() -> void:
	if size.x < 40.0:
		return
	_assign_rows()
	_used.clear()
	var axis_y := size.y - font_size - 5.0
	var row_h := (axis_y - 2.0) / ROWS
	draw_rect(Rect2(0.0, 0.0, size.x, axis_y), Color(1, 1, 1, 0.03))
	for s: float in [0.0, 10.0, 20.0, 30.0]:
		var x := clampf(roundf(size.x - s / SPAN * size.x) + 0.5, 0.5, size.x - 0.5)
		draw_line(Vector2(x, 0.0), Vector2(x, axis_y), GRID, 1.0)
		var tick_label := _line("now" if s == 0.0 else "-%ds" % int(s), font_size - 1)
		var w := tick_label.get_line_width()
		var x_text := x - w if s == 0.0 else (x + 1.0 if s == SPAN else x - w * 0.5)
		tick_label.draw(get_canvas_item(), Vector2(x_text, size.y - 3.0 - tick_label.get_line_ascent()), AXIS)
	# The ticks first, then the labels on a dark backing, so no tick runs through a label.
	var shown: Array = []  # [event, x]
	for ev: Dictionary in _events:
		var age := now - float(ev.t)
		if age < -1.0 or age > SPAN:
			continue
		var x := size.x - clampf(age, 0.0, SPAN) / SPAN * size.x
		draw_line(Vector2(x, 0.0), Vector2(x, axis_y), _color(String(ev.kind)), 1.5)
		shown.append([ev, x])
	for pair: Array in shown:
		var ev: Dictionary = pair[0]
		var x: float = pair[1]
		var row: int = _rows.get(_key(ev), -1)
		if row < 0:
			continue
		var top := 1.0 + row * row_h
		var kind := String(ev.kind)
		var kind_line := _line(kind, font_size)
		var rest := " " + String(ev.name) if String(ev.name) != "" else ""
		var rest_line := _line(rest, font_size)
		var width := kind_line.get_line_width() + (rest_line.get_line_width() if rest != "" else 0.0)
		var x0 := x - 3.0 - width
		draw_rect(Rect2(x0 - 1.0, top, width + 2.0, kind_line.get_size().y), BACKING)
		kind_line.draw(get_canvas_item(), Vector2(x0, top), _color(kind))
		if rest != "":
			rest_line.draw(get_canvas_item(), Vector2(x0 + kind_line.get_line_width(), top), NAME)
	for key: String in _shaped.keys():
		if not _used.has(key):
			_shaped.erase(key)


func _line(text: String, px: int) -> TextLine:
	var key := "%d|%s" % [px, text]
	_used[key] = true
	if not _shaped.has(key):
		var line := TextLine.new()
		line.add_string(text, _font, px)
		_shaped[key] = line
	return _shaped[key]


## New events get the first row where their label doesn't run into a later
## label (labels sit left of their tick, so only later ticks can collide).
func _assign_rows() -> void:
	var sorted := _events.duplicate()
	sorted.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return float(a.t) < float(b.t))
	var row_end: Array[float] = []
	for row in ROWS:
		row_end.append(-INF)
	var per_second := size.x / SPAN
	for ev: Dictionary in sorted:
		var key := _key(ev)
		var t := float(ev.t)
		if not _rows.has(key):
			var width_s := (_label_width(ev) + 10.0) / per_second
			_rows[key] = -1
			for row in ROWS:
				if row_end[row] <= t - width_s:
					_rows[key] = row
					break
		var placed: int = _rows[key]
		if placed >= 0:
			row_end[placed] = t


func _label_width(ev: Dictionary) -> float:
	var rest := " " + String(ev.name) if String(ev.name) != "" else ""
	return _line(String(ev.kind), font_size).get_line_width() + (_line(rest, font_size).get_line_width() if rest != "" else 0.0)


## A kind not listed in KIND_COLORS gets a steady color of its own.
func _color(kind: String) -> Color:
	if KIND_COLORS.has(kind):
		return KIND_COLORS[kind]
	return Color.from_hsv(float(posmod(hash(kind), 360)) / 360.0, 0.45, 1.0)


func _key(ev: Dictionary) -> String:
	return "%s|%s|%s" % [ev.t, ev.kind, ev.name]
