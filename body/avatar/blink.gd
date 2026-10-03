class_name AvatarBlink
extends Node
## Blinking. Intervals are irregular (log-normal around the rate), blinks close
## fast and open slower, the two eyes are a few ms apart, some blinks come in
## pairs, and big gaze shifts tend to trigger one.
## Modes the brain asks for (blink_mode): suppress (no blinks for a while: a
## stare, a line she's working to get right), burst (a few quick ones right
## after), slow (a long, heavy blink: bored, tired, or soft toward someone),
## flutter (three quick ones: the onset of embarrassment) and fail_wink (her
## clumsy wink: both eyes shut, or a lopsided squint). A freeze holds blinks
## and ends with one (or two) held blinks.

const Ramps := preload("res://avatar/ramps.gd")

@export var face: AvatarFace
@export var gaze: AvatarGaze
@export var blinks_per_minute := 16.0
@export var talking_blinks_per_minute := 24.0
@export_range(0.0, 1.0) var double_blink_chance := 0.12

const CLOSE := 0.07
const HOLD := 0.04
const OPEN := 0.16

## Set by Speech while she talks.
var talking := false
## Temporary multipliers on blinks_per_minute and talking_blinks_per_minute (body_ramp).
var ramps := Ramps.new()
## Read-out: the blinks per minute she's running at right now (0 while blinks are held).
var rate_now := 16.0

var _next := 0.5  # blink units (one unit = one mean interval) until the next spontaneous blink
var _t := -1.0  # time into the current blink; < 0 when not blinking
var _right_lag := 0.0
var _double_pending := false
var _amount := Vector2.ONE  # how far each eye closes in this blink (a wink, a squint)
var _close := CLOSE
var _hold := HOLD  # this blink's closed time
var _open := OPEN  # this blink's opening time
var _suppressed := 0.0  # seconds left without spontaneous blinks
var _queue: Array = []  # blinks asked for: {at, close, hold, open, amount}


func _ready() -> void:
	if gaze:
		gaze.saccade_started.connect(_on_saccade)


## One blink, both eyes: closed for `hold` s, opening over `open` s.
func blink(hold := HOLD, open := OPEN) -> void:
	_start(Vector2.ONE, CLOSE, hold, open, randf_range(0.0, 0.012))


## No spontaneous blinks for `seconds`.
func suppress(seconds: float) -> void:
	_suppressed = maxf(_suppressed, seconds)


## A few quick blinks in a row, 0.25-0.4 s apart.
func burst(count: int) -> void:
	_suppressed = 0.0
	var at := 0.0
	for i in count:
		_queue.append(_queued(at, Vector2.ONE, CLOSE, HOLD, OPEN))
		at += randf_range(0.25, 0.4)


## One long, heavy blink: close 0.15 s, hold 0.15, open 0.3.
func slow_blink() -> void:
	_t = -1.0
	_start(Vector2.ONE, 0.15, 0.15, 0.3, randf_range(0.0, 0.012))


## Three quick blinks in 0.9 s.
func flutter() -> void:
	for at: float in [0.0, 0.3, 0.6]:
		_queue.append(_queued(at, Vector2.ONE, CLOSE, HOLD, OPEN))


## Her wink failing. "shut": both eyes close for 0.25 s. "squint": the lids close
## lopsided, the `left` side eye 0.7 and the other 0.4, for 0.35 s.
func fail_wink(variant: String, left: bool) -> void:
	_t = -1.0
	match variant:
		"shut":
			_start(Vector2.ONE, CLOSE, 0.25, OPEN, 0.0)
		"squint":
			_start(Vector2(0.7, 0.4) if left else Vector2(0.4, 0.7), 0.06, 0.35, 0.2, 0.0)
		_:
			push_error("AvatarBlink: unknown fail_wink variant '%s'" % variant)


## A freeze: no blinks for `seconds`, then a held blink (two, 0.25-0.4 s apart, with double_blink).
func freeze(seconds: float, double_blink: bool, blink_hold: float) -> void:
	_queue.clear()
	suppress(seconds)
	_queue.append(_queued(seconds, Vector2.ONE, CLOSE, blink_hold, OPEN))
	if double_blink:
		_queue.append(_queued(seconds + randf_range(0.25, 0.4), Vector2.ONE, CLOSE, blink_hold, OPEN))


## Blink very soon with the given probability (gaze shifts, end of a sentence...).
func blink_soon(chance := 1.0) -> void:
	if randf() < chance:
		_next = minf(_next, randf_range(0.0, 0.1) * _rate() / 60.0)


func wink(left := true) -> void:
	_t = -1.0
	_start(Vector2(1.0, 0.0) if left else Vector2(0.0, 1.0), CLOSE, 0.25, OPEN, 0.0)


func _process(delta: float) -> void:
	ramps.advance(delta)
	var left := 0.0
	var right := 0.0
	for q: Dictionary in _queue:
		q.at -= delta
	if _t < 0.0 and not _queue.is_empty():
		var due := -1
		for i in _queue.size():
			if _queue[i].at <= 0.0 and (due < 0 or _queue[i].at < _queue[due].at):
				due = i
		if due >= 0:
			var q: Dictionary = _queue[due]
			_queue.remove_at(due)
			_start(q.amount, q.close, q.hold, q.open, randf_range(0.0, 0.012))
	_suppressed = maxf(0.0, _suppressed - delta)
	rate_now = 0.0 if _suppressed > 0.0 else _rate()
	if _t >= 0.0:
		_t += delta
		left = _curve(_t) * _amount.x
		right = _curve(_t - _right_lag) * _amount.y
		if _t > _close + _hold + _open + _right_lag:
			_t = -1.0
			if _double_pending:
				_double_pending = false
				_next = randf_range(0.05, 0.12) * _rate() / 60.0
	else:
		_next -= delta * _rate() / 60.0
		if _next <= 0.0 and _suppressed <= 0.0:
			_start(Vector2.ONE, CLOSE, HOLD, OPEN, randf_range(0.0, 0.012))
			_double_pending = randf() < double_blink_chance
	if face:
		face.set_blink(left, right)


## Spontaneous blinks per minute right now (base x ramps).
func _rate() -> float:
	if talking:
		return talking_blinks_per_minute * ramps.factor("talking_blinks_per_minute")
	return blinks_per_minute * ramps.factor("blinks_per_minute")


## Every blink, spontaneous or asked for, restarts the wait for the next spontaneous one
## (a freeze's closing blink doesn't get a spontaneous one right behind it).
func _start(amount: Vector2, close: float, hold: float, open: float, lag: float) -> void:
	if _t >= 0.0:
		return
	_next = clampf(exp(randfn(-0.1, 0.45)), 0.16, 3.0)  # blink units: log-normal around one mean interval
	_t = 0.0
	_amount = amount
	_close = maxf(close, 0.01)
	_hold = maxf(hold, 0.0)
	_open = maxf(open, 0.01)
	_right_lag = lag


func _queued(at: float, amount: Vector2, close: float, hold: float, open: float) -> Dictionary:
	return {"at": at, "amount": amount, "close": close, "hold": hold, "open": open}


func _curve(t: float) -> float:
	if t < 0.0:
		return 0.0
	if t < _close:
		return ease(t / _close, 2.0)  # accelerate shut
	if t < _close + _hold:
		return 1.0
	return 1.0 - ease(clampf((t - _close - _hold) / _open, 0.0, 1.0), 0.5)  # quick start, slow finish


func _on_saccade(amplitude: float) -> void:
	if amplitude > 15.0 and _suppressed <= 0.0:
		blink_soon(clampf(0.3 + (amplitude - 15.0) / 60.0, 0.0, 0.8))
