extends Control
## One row of the mind panel: label, bar (ui/mind_meter.gd: the ghost of a
## drop, the glow of a rise), value, and the last change (▲ green / ▼ red with
## the event number). Optional:
##   details   a smaller second line (emotions: source, display rule, what
##             the face shows, fast and slow parts). Set it before the row is
##             shown: it's there from the start, so rows never jump.
##   shown     a thin line under the bar: what her face shows of an emotion
##   ticks     thin marks on the bar: [[value, alpha], ...]
##   markers   small ▾ above the bar: [[value, color], ...]
## Hovering the row shows its hint.
## Text is shaped once per change (cached TextLines): many bars redraw every
## frame while they animate, far more strings than the font's own cache holds.
## While it animates, a row redraws only when something moved a quarter of a
## pixel or more, and not while it's scrolled out of the panel's view.

const Meter := preload("res://ui/mind_meter.gd")

const LABEL := Color(0.87, 0.85, 0.91)
const VALUE := Color(0.97, 0.97, 1.0)
const DIM := Color(0.58, 0.56, 0.64)
const RISE := Color(0.42, 0.88, 0.48)
const FALL := Color(1.0, 0.42, 0.42)

var label := ""
var label_width := 96.0
var value_width := 34.0
var change_width := 66.0
var font_size := 12
var small_size := 11
var bar_height := 8.0
## How the value is printed ("%.2f", "%+.2f", "%.1f s"...).
var format := "%.2f"
## Label and value in a dim color while the value is at 0 (not for bars centered on 0),
## so what's active stands out.
var dim_zero := true
## A second, smaller line under the bar (set_details).
var details := false
var meter := Meter.new()

var _value_text := ""
var _change_text := ""
var _change_color := RISE
var _details: Array = []  # [[text, color], ...]
var _shown := -1.0  # < 0: no shown line
var _shown_drawn := 0.0
var _shown_at_draw := NAN
var _ticks: Array = []
var _markers: Array = []
var _font: Font
var _text_cache := {}  # slot -> [text, font size, width, alignment, TextLine]
var _line := 18.0  # first line's height
var _small_line := 13.0
var _clip: Control  # the scroll container this row sits in (rows out of its view don't redraw)


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_PASS  # hint on hover; the panel still scrolls
	_font = get_theme_default_font()
	_line = ceilf(_font.get_height(font_size)) + 1.0
	_small_line = ceilf(_font.get_height(small_size)) - 2.0
	var node := get_parent()
	while node != null and not node is ScrollContainer:
		node = node.get_parent()
	_clip = node as Control
	_fit()


func setup(bar_label: String, low: float, high: float, bar_color: Color, hint := "") -> void:
	label = bar_label
	meter.setup(low, high, bar_color)
	tooltip_text = hint
	_value_text = _format(meter.value)
	queue_redraw()


## A new value from a snapshot. animate false: jump there (no ghost, no glow).
## The row redraws now only if that shows (new text, a ghost or a glow starting);
## the glide redraws it as it moves.
func set_value(v: float, slow := -1.0, animate := true) -> void:
	if animate and absf(v - meter.value) < 0.0005 and absf(slow - meter.tail) < 0.0005:
		return  # the same as before: nothing to redraw
	if animate:
		meter.set_value(v, slow)
	else:
		meter.reset(v, slow)
	set_process(true)
	var text := _format(v)
	if text != _value_text or not animate or meter.stale():
		_value_text = text
		queue_redraw()


## A value read every frame (blend shapes): no ghost, glow or glide. Out of view,
## the row keeps its old value (and redraws once it's back in view and differs).
func set_live(v: float) -> void:
	if absf(v - meter.value) < 0.001 or not on_screen():
		return
	meter.reset(v)
	_value_text = _format(v)
	queue_redraw()


func set_value_text(text: String) -> void:
	if text != _value_text:
		_value_text = text
		queue_redraw()


## The last change, from a bar's `last` {seq, d}; fresh: from the latest event.
func set_change(last: Variant, fresh: bool) -> void:
	var text := ""
	var color := RISE
	if last is Dictionary:
		var d := float(last.d)
		text = "%s%.2f #%d" % ["▲" if d > 0.0 else "▼", absf(d), int(last.seq)]
		color = RISE if d > 0.0 else FALL
		if not fresh:
			color = Color(color, 0.5)
	set_change_text(text, color)


func set_change_text(text: String, color: Color) -> void:
	if text != _change_text or color != _change_color:
		_change_text = text
		_change_color = color
		queue_redraw()


## The second line: [[text, color], ...], drawn one after another.
func set_details(runs: Array) -> void:
	if runs != _details:
		_details = runs
		queue_redraw()


## What her face shows of this emotion (a thin line under the bar; it glides too).
func set_shown(v: float, animate := true) -> void:
	if not animate or _shown < 0.0:
		_shown_drawn = v
		queue_redraw()
	_shown = v
	set_process(true)


func set_ticks(ticks: Array) -> void:
	if ticks != _ticks:
		_ticks = ticks
		queue_redraw()


func set_markers(markers: Array) -> void:
	if markers != _markers:
		_markers = markers
		queue_redraw()


## The value as text; a value that rounds to zero prints as 0 (no "-0.00").
func _format(v: float) -> String:
	return format % (v if absf(v) >= 0.005 else 0.0)


func _fit() -> void:
	if _font:
		custom_minimum_size.y = _line + (_small_line if details else 0.0)


func _process(delta: float) -> void:
	var busy := meter.advance(delta)
	if _shown >= 0.0 and absf(_shown_drawn - _shown) > 0.0005:
		_shown_drawn = lerpf(_shown_drawn, _shown, 1.0 - exp(-delta / Meter.GLIDE))
		busy = true
	else:
		_shown_drawn = _shown
	if not busy:
		set_process(false)
		queue_redraw()  # the final state, in view or not
	elif (meter.stale() or not absf(_shown_drawn - _shown_at_draw) * meter.px_per_unit() < 0.25) and on_screen():
		queue_redraw()


## Whether any of the row is inside the panel's scrolled view.
func on_screen() -> bool:
	return _clip == null or get_global_rect().intersects(_clip.get_global_rect())


## Width of a label in this bar's font (for lining up a column of bars).
func label_size(text: String) -> float:
	var line := TextLine.new()
	line.add_string(text, get_theme_default_font(), font_size)
	return line.get_line_width()


func track_rect() -> Rect2:
	var x1 := size.x - value_width - change_width
	var y := floorf((_line - bar_height) * 0.5) + 1.0
	return Rect2(label_width, y, maxf(8.0, x1 - label_width - 6.0), bar_height)


func _draw() -> void:
	var track := track_rect()
	var mid := track.position.y + track.size.y * 0.5
	var baseline := roundf(mid + (_font.get_ascent(font_size) - _font.get_descent(font_size)) * 0.5)
	var idle := dim_zero and meter.lo >= 0.0 and absf(meter.value - meter.lo) < 0.005
	if label_width > 0.0:
		_text("label", label, font_size, label_width - 4.0, Vector2(0.0, baseline), DIM if idle else LABEL)
	meter.draw(self, track)
	for tick: Array in _ticks:
		var x := roundf(meter.x_of(float(tick[0]), track)) + 0.5
		draw_line(Vector2(x, track.position.y - 2.0), Vector2(x, track.end.y + 2.0), Color(1, 1, 1, float(tick[1])),
			1.0)
	for marker: Array in _markers:
		var x := meter.x_of(float(marker[0]), track)
		var top := track.position.y - 5.0
		draw_colored_polygon(PackedVector2Array([Vector2(x - 3.5, top), Vector2(x + 3.5, top),
			Vector2(x, track.position.y)]), marker[1])
	_shown_at_draw = _shown_drawn
	if _shown >= 0.0:  # what her face shows, under the bar
		var x0 := meter.x_of(meter.zero(), track)
		var x1 := meter.x_of(_shown_drawn, track)
		if x1 - x0 >= 0.5:
			draw_rect(Rect2(x0, track.end.y + 1.0, x1 - x0, 2.0), meter.color.lightened(0.55))
	var x_value := track.end.x + 4.0
	_text("value", _value_text, font_size, value_width - 2.0, Vector2(x_value, baseline), DIM if idle else VALUE,
		HORIZONTAL_ALIGNMENT_RIGHT)
	if change_width > 0.0 and _change_text != "":
		_text("change", _change_text, small_size, change_width - 6.0, Vector2(x_value + value_width + 4.0, baseline),
			_change_color)
	if details and not _details.is_empty():
		var x := 10.0
		var y := _line + _font.get_ascent(small_size) - 2.0
		for i in _details.size():
			var room := size.x - x
			if room < 12.0:
				break
			var run: Array = _details[i]
			x += _text("detail%d" % i, String(run[0]), small_size, room, Vector2(x, y), run[1])


## Draws text with its baseline at `at` (shaped once, then reused while it's the
## same); returns its width.
func _text(slot: String, text: String, px: int, width: float, at: Vector2, color: Color,
		align := HORIZONTAL_ALIGNMENT_LEFT) -> float:
	var entry: Array = _text_cache.get(slot, [])
	if entry.is_empty() or entry[0] != text or entry[1] != px or entry[2] != width or entry[3] != align:
		var line := TextLine.new()
		line.add_string(text, _font, px)
		line.width = width
		line.alignment = align
		line.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		entry = [text, px, width, align, line]
		_text_cache[slot] = entry
	var shaped: TextLine = entry[4]
	shaped.draw(get_canvas_item(), Vector2(at.x, at.y - shaped.get_line_ascent()), color)
	return shaped.get_line_width()
