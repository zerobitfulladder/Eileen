extends RefCounted
## One value drawn as a bar. The drawn bar glides to each new value (snapshots
## come 1 to 5 times a second), and changes leave traces, the way an audio
## meter holds its peaks:
##   ghost of a drop  the fill the bar just lost stays, faint (35%), for HOLD
##                    seconds, then slides down with a half-life of
##                    GHOST_HALF_LIFE. A slow fade shows as a thin ghost that
##                    trails the value; a sudden drop holds again.
##   glow of a rise   each part the fill gains flashes 60% brighter, with a white
##                    halo (so it shows on light colors too), and fades out over
##                    GLOW_TIME. A slow climb lights its tip a pixel at a time;
##                    nothing stays lit once the value stops rising.
## Bars whose range goes below 0 (mood) fill from 0, so moving toward 0 leaves
## a ghost and moving away from 0 glows.
## Emotions also have a slow tail: drawn darker, under the bright fast part.
## Used by ui/mind_bar.gd; it draws into any CanvasItem.

const HOLD := 1.2
const GHOST_HALF_LIFE := 2.5
const GHOST_ALPHA := 0.35
const GLOW_TIME := 0.6
const GLOW := 0.6  # how much brighter the gained part flashes
const HALO := 0.5  # alpha of the white halo around it, at the start of the flash
const GLIDE := 0.08  # seconds: how closely the drawn bar follows the value
const SUDDEN := 0.04  # a drop of this share of the range holds the ghost again
const MIN_PX := 1.0  # a glow starts, and a sliding ghost ends, at this many pixels
const TRACK := Color(1.0, 1.0, 1.0, 0.07)

var lo := 0.0
var hi := 1.0
var color := Color.WHITE
## Ghost, glow and glide. Off for values that move every frame (blend shapes).
var effects := true

var value := 0.0  ## the latest value
var drawn := 0.0  ## where the bar is drawn now
var tail := -1.0  ## the slow part of an emotion (< 0: none)
var tail_drawn := 0.0

var _ghost := 0.0
var _ghost_on := false
var _hold := 0.0
var _glows: Array = []  # [from, to, age]: the parts gained in the last GLOW_TIME, oldest first
var _climb_from := NAN  # start of a climb still too small to light up
var _px := 0.0  # pixels per unit of value, from the last draw (0: not drawn yet)
# What the last draw showed, in pixels (NAN: nothing yet / no ghost), so a bar
# only redraws when something moved enough to see.
var _drawn_px := NAN
var _tail_px := NAN
var _ghost_px := NAN
var _lit := false


func setup(low: float, high: float, bar_color: Color) -> void:
	lo = low
	hi = maxf(high, low + 0.0001)
	color = bar_color


## Where the fill starts: 0, or the end of the range nearest to 0.
func zero() -> float:
	return clampf(0.0, lo, hi)


## Jump to a value without ghost or glow (first snapshot, a new mind, or after being hidden).
func reset(v: float, slow := -1.0) -> void:
	value = v
	drawn = v
	tail = slow
	tail_drawn = maxf(slow, 0.0)
	_ghost_on = false
	_glows.clear()
	_climb_from = NAN


func set_value(v: float, slow := -1.0) -> void:
	if not effects:
		reset(v, slow)
		return
	tail = slow
	var old := value
	value = v
	if absf(v - old) < 0.0005:
		return
	var z := zero()
	var old_side := _side(old - z)
	var new_side := _side(v - z)
	var lost := old_side != 0 and (new_side != old_side or absf(v - z) < absf(old - z))
	var gained := new_side != 0 and (new_side != old_side or absf(v - z) > absf(old - z))
	if _ghost_on and _side(_ghost - z) == new_side and absf(v - z) >= absf(_ghost - z):
		_ghost_on = false  # back up to the old peak (or past it)
	if lost:
		_climb_from = NAN
		if not _ghost_on or _side(_ghost - z) != old_side or absf(_ghost - z) < absf(old - z):
			_ghost = old  # a new drop: hold where it was
			_ghost_on = true
			_hold = HOLD
		elif absf(old - v) >= SUDDEN * (hi - lo):
			_hold = HOLD  # a sudden drop under a ghost that was already sliding
	if gained:
		var from := old if old_side == new_side else z
		if not is_nan(_climb_from) and _side(_climb_from - z) in [0, new_side] \
				and absf(_climb_from - z) < absf(from - z):
			from = _climb_from  # a slow climb: it lights up once it adds up to a pixel
		if _px > 0.0 and absf(v - from) * _px < MIN_PX:
			_climb_from = from
		else:
			_glows.append([from, v, 0.0])
			_climb_from = NAN


## Pixels per unit of value on the last drawn bar (0 before the first draw).
func px_per_unit() -> float:
	return _px


## True when drawing now would look different from the last draw (something
## moved a quarter of a pixel or more, or a glow is fading).
func stale() -> bool:
	if is_nan(_drawn_px) or _lit or not _glows.is_empty():
		return true
	if absf(drawn * _px - _drawn_px) >= 0.25 or absf(tail_drawn * _px - _tail_px) >= 0.25:
		return true
	var had_ghost := not is_nan(_ghost_px)
	if _ghost_on != had_ghost:
		return true
	return _ghost_on and absf(_ghost * _px - _ghost_px) >= 0.25


## Moves the animation on. True while anything still moves.
func advance(delta: float) -> bool:
	var busy := false
	var k := 1.0 - exp(-delta / GLIDE)
	if absf(drawn - value) > 0.0005:
		drawn = lerpf(drawn, value, k)
		busy = true
	else:
		drawn = value
	var tail_goal := maxf(tail, 0.0)
	if absf(tail_drawn - tail_goal) > 0.0005:
		tail_drawn = lerpf(tail_drawn, tail_goal, k)
		busy = true
	else:
		tail_drawn = tail_goal
	if _ghost_on:
		busy = true
		if _hold > 0.0:
			_hold -= delta
		else:
			var z := zero()
			var to := drawn if _side(_ghost - z) == _side(drawn - z) else z
			_ghost = to + (_ghost - to) * pow(0.5, delta / GHOST_HALF_LIFE)
			# it ends within a pixel of the value (a thousandth of the range if never drawn)
			var close := MIN_PX / _px if _px > 0.0 else 0.001 * (hi - lo)
			if absf(_ghost - to) < close:
				_ghost_on = false
	if not _glows.is_empty():
		busy = true
		for glow: Array in _glows:
			glow[2] += delta
		while not _glows.is_empty() and float(_glows[0][2]) >= GLOW_TIME:
			_glows.pop_front()
	return busy


func draw(ci: CanvasItem, r: Rect2) -> void:
	_px = r.size.x / (hi - lo)
	_drawn_px = drawn * _px
	_tail_px = tail_drawn * _px
	_ghost_px = _ghost * _px if _ghost_on else NAN
	_lit = not _glows.is_empty()
	ci.draw_rect(r, TRACK)
	var z := zero()
	var x_zero := x_of(z, r)
	var x_value := x_of(drawn, r)
	# The glows, cut to the fill: [x0, x1, strength 1 -> 0 over GLOW_TIME].
	var lit: Array = []
	var fill_lo := minf(z, drawn)
	var fill_hi := maxf(z, drawn)
	for glow: Array in _glows:
		var a := maxf(minf(float(glow[0]), float(glow[1])), fill_lo)
		var b := minf(maxf(float(glow[0]), float(glow[1])), fill_hi)
		if (b - a) * _px >= 0.5:
			lit.append([x_of(a, r), x_of(b, r), 1.0 - smoothstep(0.0, 1.0, float(glow[2]) / GLOW_TIME)])
	for part: Array in lit:  # a white halo behind the fresh part: it shows even on a white bar
		ci.draw_rect(Rect2(float(part[0]), r.position.y - 2.0, float(part[1]) - float(part[0]), r.size.y + 4.0),
			Color(1.0, 1.0, 1.0, HALO * float(part[2])))
	if tail >= 0.0:  # an emotion: the slow tail darker, the fast part bright on top
		var x_tail := x_of(minf(tail_drawn, drawn), r)
		_fill(ci, r, x_zero, x_tail, color.darkened(0.45), lit)
		_fill(ci, r, x_tail, x_value, color, lit)
	else:
		_fill(ci, r, x_zero, x_value, color, lit)
	if lo < 0.0:  # zero, for bars centered on it
		ci.draw_line(Vector2(x_zero, r.position.y), Vector2(x_zero, r.end.y), Color(1, 1, 1, 0.22), 1.0)
	if _ghost_on:  # the ghost of a drop, with a faint edge where the value was
		var from := drawn if _side(_ghost - z) == _side(drawn - z) else z
		var x_ghost := x_of(_ghost, r)
		_span(ci, r, x_of(from, r), x_ghost, Color(color, GHOST_ALPHA))
		if absf(x_ghost - x_of(from, r)) >= 2.0:
			ci.draw_line(Vector2(x_ghost, r.position.y), Vector2(x_ghost, r.end.y), Color(color.lightened(0.25), 0.7), 1.0)


func x_of(v: float, r: Rect2) -> float:
	return r.position.x + clampf((v - lo) / (hi - lo), 0.0, 1.0) * r.size.x


## The color of a fresh rise: 60% brighter.
static func bright(c: Color) -> Color:
	var b := 1.0 + GLOW
	return Color(minf(c.r * b, 1.0), minf(c.g * b, 1.0), minf(c.b * b, 1.0), c.a).lerp(Color.WHITE, 0.15)


## A part of the fill; where it overlaps a glow, it's drawn brighter.
func _fill(ci: CanvasItem, r: Rect2, x0: float, x1: float, c: Color, lit: Array) -> void:
	_span(ci, r, x0, x1, c)
	for part: Array in lit:
		var a := maxf(minf(x0, x1), float(part[0]))
		var b := minf(maxf(x0, x1), float(part[1]))
		if b > a:
			_span(ci, r, a, b, c.lerp(bright(c), float(part[2])))


func _span(ci: CanvasItem, r: Rect2, x0: float, x1: float, c: Color) -> void:
	if absf(x1 - x0) >= 0.05:
		ci.draw_rect(Rect2(minf(x0, x1), r.position.y, absf(x1 - x0), r.size.y), c)


static func _side(x: float) -> int:
	return 1 if x > 0.0005 else (-1 if x < -0.0005 else 0)
