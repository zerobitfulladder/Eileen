@tool
extends RefCounted
## Temporary multipliers on one body part's parameters (the body_ramp command).
## Each ramp eases in over `seconds`, holds, and eases back out starting
## `back_after` seconds after it began, so it always undoes itself. A
## parameter's effective value is its base times the product of its ramps.
## Each part that owns body parameters keeps one of these and advances it
## every frame.

var _ramps: Array = []  # {param, value, seconds, back, t}


func add(param: String, value: float, seconds: float, back_after: float) -> void:
	_ramps.append({"param": param, "value": value, "seconds": maxf(seconds, 0.01), "back": maxf(back_after, 0.0),
		"t": 0.0})


func advance(delta: float) -> void:
	if _ramps.is_empty():
		return
	for r: Dictionary in _ramps:
		r.t += delta
	_ramps = _ramps.filter(func(r: Dictionary) -> bool: return r.t < r.back + r.seconds)


## The product of the active ramps on `param` (1 when there are none).
func factor(param: String) -> float:
	var f := 1.0
	for r: Dictionary in _ramps:
		if r.param == param:
			# In from the start, out from back_after; whichever is lower, so an early return is smooth too.
			var level := minf(smoothstep(0.0, r.seconds, r.t), 1.0 - smoothstep(r.back, r.back + r.seconds, r.t))
			f *= lerpf(1.0, r.value, maxf(level, 0.0))
	return f


func is_empty() -> bool:
	return _ramps.is_empty()
