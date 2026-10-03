class_name AvatarGestures
extends Node
## Short additive motions (nods, tilts, laughs, sighs...) and held attitudes.
## Several gestures can run at once; AvatarRig adds their sum on top of the pose
## and gaze every frame. Held attitudes (poses) carry a face's head, a phrase's
## stance or tensing: a new pose in the same slot crossfades out the one before
## it, and a pose held open (hold -1) stays until end_slot() or its max_hold.
## The posture is a slow baseline under everything: the resting face's head
## (chin up when she feels on top, head low when she's down).
## Angles in degrees: pitch + = head/chest down, yaw + = her left, roll + = tilt to her right.

## Current sum, read by AvatarRig.
var head := Vector3.ZERO  # pitch, yaw, roll
var chest := Vector3.ZERO  # pitch, yaw, roll
var shoulders := 0.0  # lift

## Default durations, seconds.
const DURATIONS := {
	"beat": 0.32, "lift": 0.4, "turn": 0.5, "tilt_beat": 0.45, "nod": 0.5, "double_nod": 0.85, "shake": 0.9, "tilt": 2.2,
	"laugh": 1.4, "chuckle": 0.7, "sigh": 2.0, "gasp": 1.4, "lean_in": 2.5,
	"shrug": 1.0, "cough": 0.9, "sniff": 0.6, "recoil": 1.2, "head_back": 1.6,
	"inhale": 0.45, "exhale": 0.6, "shaky_exhale": 1.2,
}

## Slow baseline head offset (pitch, yaw, roll), see set_posture().
var posture := Vector3.ZERO

var _gestures := []  # {name, s, t, d, calm_t, calm_len}
var _poses := []  # {slot, head, chest, shoulders, t, attack, hold, release, max_hold, fading, fade_from, fade_t, fade_len}
var _posture_goal := Vector3.ZERO
var _posture_speed := 0.6


## Hold an attitude on top of where she looks (her eyes keep tracking their
## target, so a turned head with the eyes on the viewer reads as a side glance).
## hold -1 keeps it until end_slot(), a new pose in the slot, or max_hold (s at
## the peak; 0 = no limit). A new pose in the same slot crossfades out the old
## one over this one's attack.
func hold_pose(head_offset: Vector3, hold: float, attack: float, release: float, slot := "", chest_pitch := 0.0,
		shoulder_lift := 0.0, max_hold := 0.0) -> void:
	if slot != "":
		end_slot(slot, attack)
	_poses.append({"slot": slot, "head": head_offset, "chest": chest_pitch, "shoulders": shoulder_lift, "t": 0.0,
		"attack": maxf(attack, 0.01), "hold": hold, "release": maxf(release, 0.01), "max_hold": max_hold,
		"fading": false, "fade_from": 0.0, "fade_t": 0.0, "fade_len": 0.0})


## Let go of the pose in `slot`, from where it is now.
func end_slot(slot: String, fade: float) -> void:
	for p: Dictionary in _poses:
		if p.slot == slot and not _pose_done(p):
			p.fade_from = _pose_level(p)
			p.fade_len = maxf(fade, 0.05)
			p.fade_t = 0.0
			p.fading = true


## Running gestures fade out over `fade` seconds (a freeze); held poses stay.
func calm(fade: float) -> void:
	for g: Dictionary in _gestures:
		if g.calm_len <= 0.0:
			g.calm_len = maxf(fade, 0.01)
			g.calm_t = 0.0


## Drift the baseline head attitude toward `offset` (degrees), `speed` per second.
func set_posture(offset: Vector3, speed := 0.6) -> void:
	_posture_goal = offset
	_posture_speed = maxf(speed, 0.01)


## `strength` scales the motion; negative mirrors side-to-side gestures (tilt, recoil...).
## Returns false for an unknown gesture.
func play(gesture: String, strength := 1.0, duration := -1.0) -> bool:
	if not DURATIONS.has(gesture):
		push_error("AvatarGestures: unknown gesture '%s'" % gesture)
		return false
	_gestures.append({"name": gesture, "s": strength, "t": 0.0,
		"d": duration if duration > 0.0 else DURATIONS[gesture], "calm_t": 0.0, "calm_len": 0.0})
	return true


func stop_all() -> void:
	_gestures.clear()
	_poses.clear()


func _process(delta: float) -> void:
	posture = posture.lerp(_posture_goal, 1.0 - exp(-_posture_speed * delta))
	head = posture
	chest = Vector3.ZERO
	shoulders = 0.0
	for p: Dictionary in _poses:
		p.t += delta
		if p.fading:
			p.fade_t += delta
	_poses = _poses.filter(func(p: Dictionary) -> bool: return not _pose_done(p))
	for p: Dictionary in _poses:
		var level := _pose_level(p)
		head += p.head * level
		chest.x += p.chest * level
		shoulders += p.shoulders * level
	for g: Dictionary in _gestures:
		g.t += delta
		if g.calm_len > 0.0:
			g.calm_t += delta
	_gestures = _gestures.filter(func(g: Dictionary) -> bool:
		return g.t < g.d and (g.calm_len <= 0.0 or g.calm_t < g.calm_len))
	for g: Dictionary in _gestures:
		var calm := 1.0 - smoothstep(0.0, 1.0, g.calm_t / g.calm_len) if g.calm_len > 0.0 else 1.0
		_add(g.name, g.t, g.d, g.s * calm)


func _pose_level(p: Dictionary) -> float:
	if p.fading:
		return p.fade_from * (1.0 - smoothstep(0.0, 1.0, p.fade_t / p.fade_len))
	if p.t < p.attack:
		return smoothstep(0.0, 1.0, p.t / p.attack)
	var top := _pose_top(p)
	if p.t < p.attack + top:
		return 1.0
	return 1.0 - smoothstep(0.0, 1.0, (p.t - p.attack - top) / p.release)


func _pose_top(p: Dictionary) -> float:
	if p.hold >= 0.0:
		return p.hold
	return p.max_hold if p.max_hold > 0.0 else INF


func _pose_done(p: Dictionary) -> bool:
	if p.fading:
		return p.fade_t >= p.fade_len
	return p.t >= p.attack + _pose_top(p) + p.release


func _add(gesture: String, t: float, d: float, s: float) -> void:
	var x := clampf(t / d, 0.0, 1.0)
	match gesture:
		"beat":  # small emphasis nod: quick down, slower up
			head.x += 3.0 * s * sin(PI * pow(x, 0.6))
		"lift":  # emphasis with the chin coming up instead of down
			head.x -= 3.0 * absf(s) * sin(PI * pow(x, 0.6))
		"turn":  # a little turn to one side on the word, then back (sign = side)
			var e := sin(PI * pow(x, 0.7))
			head.y += 5.0 * s * e
			head.z += 1.5 * s * e
		"tilt_beat":  # the head tips to one side on the word (sign = side)
			head.z += 4.0 * s * sin(PI * pow(x, 0.7))
		"nod":
			head.x += 7.0 * s * sin(PI * x)
		"double_nod":
			head.x += 5.0 * s * absf(sin(TAU * x))
		"shake":
			head.y += 8.0 * s * sin(TAU * 2.0 * x) * (1.0 - x)
		"tilt":
			head.z += 8.0 * s * _env(t, d, 0.35, 0.6)
			head.x += 1.5 * absf(s) * _env(t, d, 0.35, 0.6)
		"laugh":  # head tips back, chest and shoulders heave a few times, fading out
			var e := _env(t, d, 0.15, 0.45)
			var fade := 1.0 - 0.6 * x  # the first heaves are the biggest
			var heave := _heave(t, 3.0) * fade
			var heave_late := _heave(t - 0.07, 3.0) * fade  # the head trails the chest
			chest.x += (-1.2 - 1.0 * heave) * s * e
			shoulders += (0.8 + 1.4 * heave) * s * e
			head.x += (-4.0 + 1.2 * heave_late) * s * e
		"chuckle":  # a couple of soft breaths of laughter, head dips a little
			var e := _env(t, d, 0.1, 0.3)
			var heave := _heave(t, 2.6)
			shoulders += (0.4 + 0.8 * heave) * s * e
			head.x += (1.5 + 0.8 * _heave(t - 0.06, 2.6)) * s * e
		"sigh":  # breathe in (shoulders up), then let it all drop
			var inhale := smoothstep(0.0, 0.3, x) * (1.0 - smoothstep(0.3, 0.55, x))
			var slump := smoothstep(0.3, 0.6, x) * (1.0 - smoothstep(0.75, 1.0, x))
			shoulders += (4.0 * inhale - 2.5 * slump) * s
			chest.x += (-1.5 * inhale + 2.5 * slump) * s
			head.x += (-1.5 * inhale + 6.0 * slump) * s
		"gasp":
			var e := _env(t, d, 0.1, 0.8)
			head.x -= 6.0 * s * e
			chest.x -= 3.0 * s * e
			shoulders += 3.0 * s * e
		"lean_in":  # toward the viewer, head stays level
			var e := _env(t, d, 0.4, 0.6)
			chest.x += 5.0 * s * e
			head.x -= 2.0 * s * e
		"shrug":
			var e := sin(PI * x)
			shoulders += 7.0 * absf(s) * e
			head.z += 4.0 * s * e
		"cough":
			var e := maxf(_pulse(t, 0.1, 0.18), _pulse(t, 0.45, 0.18))
			head.x += 6.0 * s * e
			chest.x += 3.0 * s * e
		"sniff":
			var e := _pulse(t, 0.12, 0.3)
			head.x -= 3.0 * s * e
			shoulders += 2.0 * s * e
		"recoil":  # pull back and turn away a little
			var e := _env(t, d, 0.12, 0.6)
			head.x -= 4.0 * absf(s) * e
			head.y += 6.0 * s * e
			chest.x -= 2.0 * absf(s) * e
		"head_back":
			head.x -= 8.0 * s * _env(t, d, 0.3, 0.7)
		"inhale":  # the small lift right before speaking
			var e := sin(PI * x)
			shoulders += 2.0 * s * e
			chest.x -= 1.2 * s * e
			head.x -= 1.0 * s * e
		"exhale":  # a breath out: shoulders drop, chest settles, head dips, then they recover
			_breath_out(_settle(x, 0.3), s)
		"shaky_exhale":  # the same breath out in three small steps, then the recovery
			var steps := 0.0
			for at: float in [0.0, 0.25, 0.5]:  # 0, 0.3 and 0.6 s of 1.2 s
				steps += smoothstep(at, at + 0.1, x) / 3.0
			_breath_out(steps * (1.0 - smoothstep(0.7, 1.0, x)), s)


## A breath out of `level` (0..1): shoulders drop 1.2 deg, chest settles 1, head dips 1.
func _breath_out(level: float, s: float) -> void:
	shoulders -= 1.2 * s * level
	chest.x += 1.0 * s * level
	head.x += 1.0 * s * level


## Down quickly over the first `down` of the time, then back up smoothly.
func _settle(x: float, down: float) -> float:
	return smoothstep(0.0, 1.0, x / down) if x < down else 1.0 - smoothstep(0.0, 1.0, (x - down) / (1.0 - down))


## 0 -> 1 -> 0 over `d` seconds with the given attack and release.
func _env(t: float, d: float, attack: float, release: float) -> float:
	if t < attack:
		return smoothstep(0.0, 1.0, t / attack)
	if t > d - release:
		return 1.0 - smoothstep(0.0, 1.0, (t - (d - release)) / release)
	return 1.0


## Smooth 0..1 pulses at `rate` per second (no sharp turnarounds, unlike abs(sin)).
func _heave(t: float, rate: float) -> float:
	return 0.5 - 0.5 * cos(TAU * rate * maxf(t, 0.0))


## Short bump centered at `at`, `width` seconds wide.
func _pulse(t: float, at: float, width: float) -> float:
	var x := (t - at) / width + 0.5
	return sin(PI * x) if x > 0.0 and x < 1.0 else 0.0
