class_name AvatarFace
extends Node
## The only thing that writes face blend shapes. Python decides every face
## (mimics.py builds them); this mixes them, every frame, bottom to top:
##   tonic    the resting face (face_tonic), smoothed toward its targets
##   felt     the engine's short displays of what she feels
##   display  faces she puts on, social smiles
##   leak     short pulses of a hidden feeling through one region
##   -> lip-sync visemes -> blinks and lids
## Each felt, display or leak entry has its own envelope (curve):
##   deliberate  a face made on purpose: snaps on, holds flat, drops quickly
##   felt        a real feeling: eases in, drifts a little at its peak, eases out
## Entries follow their envelopes exactly (a 0.07 s leak really peaks at 0.07 s);
## only the tonic is smoothed. A new entry in the same layer and slot crossfades
## out the one before it (a held face changing mid-sentence); hold -1 keeps an
## entry at its peak until end(), a crossfade or its max_hold. Where a felt or
## display face moves a region (brows, eyes, mouth), the resting face gives way
## there. While her lips move, mouth shapes that fight them are turned down
## (TALK_KEEP), and the part of an open smile the lips take moves to its corners.
## Shapes that fight each other are capped.
## Everything here speaks VRoid's face shapes (Fcl_*), lip sync included. The
## loaded model's face (bind(), from AvatarModel) is written at one point, at
## the end: a VRoid face has the Fcl shapes itself; any other face has a shape
## map (FaceShapeMap) that turns each one into its own blend shapes, or drops it.

const LAYERS: PackedStringArray = ["felt", "display", "leak"]
const CURVES: PackedStringArray = ["felt", "deliberate"]
const VISEMES: PackedStringArray = ["aa", "ih", "ou", "ee", "oh"]
## The mouth shape each viseme moves (VRoid's, as its VRM expressions aa .. oh bind them).
const VISEME_SHAPES: PackedStringArray = ["Fcl_MTH_A", "Fcl_MTH_I", "Fcl_MTH_U", "Fcl_MTH_E", "Fcl_MTH_O"]
## While her lips move, how much of each mouth shape stays (others: TALK_KEEP_OTHER).
const TALK_KEEP := {
	"Fcl_MTH_Fun": 0.75, "Fcl_MTH_Angry": 0.6, "Fcl_MTH_Large": 0.5, "Fcl_MTH_Sorrow": 0.45,
	"Fcl_MTH_I": 0.3, "Fcl_MTH_Small": 0.3, "Fcl_MTH_U": 0.3, "Fcl_MTH_Joy": 0.3, "Fcl_MTH_Surprised": 0.2,
}
const TALK_KEEP_OTHER := 0.2
## The part of these shapes the lips take moves to another shape (an open smile keeps its corners).
const TALK_MOVE := {"Fcl_MTH_Joy": "Fcl_MTH_Fun"}
## Lips count as moving while a viseme was above LIPS_ON within the last LIPS_HOLD seconds.
const LIPS_ON := 0.05
const LIPS_HOLD := 0.25
const TALK_SPEED := 8.0
## Shapes a region owns when an entry writes at least this much of them (weight x intensity).
const OWN_MIN := 0.05
## Lids: faces that each lower them (felt contempt, a reading check, a put-on deadpan) don't add up to shut
## eyes. Past LID_KNEE the extra that stacking adds counts LID_STACK; the most any one entry closes an eye
## always stays; leaks add on top (a leak is meant to show); nothing passes LID_MAX.
const LID_KNEE := 0.55
const LID_STACK := 0.25
const LID_MAX := 0.95

enum Region { BROWS, EYES, MOUTH, OTHER }

## Upper lids follow the eyes down a little when she looks down.
@export var gaze: AvatarGaze
## How fast the resting face follows its targets (per second).
@export var tonic_speed := 2.0

## The loaded model's face (bind()); null until a model loads.
var face_mesh: MeshInstance3D

var _entries: Array = []  # felt, display and leak entries, each with its own envelope
var _tonic_goal := {}  # shape index -> weight (face_tonic targets)
var _tonic_now := {}  # shape index -> weight (smoothed)
var _visemes := PackedFloat32Array([0, 0, 0, 0, 0])
var _blink := Vector2.ZERO
var _lid := 0.0
var _talk := 0.0  # 0..1, how much the lips are moving
var _since_lips := INF

var _shape := {}  # Fcl shape name -> index
var _names := PackedStringArray()  # index -> Fcl shape name
var _region := PackedInt32Array()  # index -> Region
var _visemes_at := PackedInt32Array()  # per viseme: its mouth shape's index
var _out: Array = []  # index -> [[face mesh blend shape, weight], ...] (the model's shape map)
var _shown := {}  # index -> value written this frame (before the shape map; read-out)
var _written := {}  # face mesh blend shape -> last written value
var _fighting := PackedInt32Array()  # eye shapes that fight a closed lid (fade during a blink)
var _lid_both := PackedInt32Array()  # EYE_Close, EYE_Joy: close both eyes
var _lid_left := PackedInt32Array()  # EYE_Close_L, EYE_Joy_L
var _lid_right := PackedInt32Array()  # EYE_Close_R, EYE_Joy_R


## Use a newly loaded model's face. `shape_map` turns the Fcl shapes into the
## mesh's own; null when the mesh has the Fcl shapes itself (a VRoid face).
## Everything playing on the face before (entries, the tonic) is dropped.
## Returns false (with errors, and no face) if the two don't fit.
func bind(mesh: MeshInstance3D, shape_map: FaceShapeMap) -> bool:
	face_mesh = null
	_shape.clear()
	_names.clear()
	_region.clear()
	_out.clear()
	_entries.clear()
	_tonic_goal.clear()
	_tonic_now.clear()
	_shown.clear()
	_written.clear()
	if shape_map:
		if not shape_map.check(mesh):
			return false
		for shape_name: String in shape_map.shapes:
			var targets := []
			for target: String in shape_map.shapes[shape_name]:
				targets.append([mesh.find_blend_shape_by_name(target), float(shape_map.shapes[shape_name][target])])
			_add_shape(shape_name, targets)
	else:
		for i in mesh.get_blend_shape_count():
			_add_shape(String(mesh.mesh.get_blend_shape_name(i)), [[i, 1.0]])
	for shape_name: String in VISEME_SHAPES + PackedStringArray(["Fcl_EYE_Close_L", "Fcl_EYE_Close_R"]):
		if _index(shape_name) < 0:
			push_error("AvatarFace: %s has no '%s'; a face that isn't VRoid's needs a shape map (ModelParts.shape_map)"
				% [mesh.name, shape_name])
			return false
	_fighting.clear()
	for shape_name in ["Fcl_EYE_Angry", "Fcl_EYE_Sorrow", "Fcl_EYE_Surprised", "Fcl_EYE_Spread", "Fcl_EYE_Fun",
			"Fcl_EYE_Natural"]:
		_fighting.append(_index(shape_name))
	_lid_both = PackedInt32Array([_index("Fcl_EYE_Close"), _index("Fcl_EYE_Joy")])
	_lid_left = PackedInt32Array([_index("Fcl_EYE_Close_L"), _index("Fcl_EYE_Joy_L")])
	_lid_right = PackedInt32Array([_index("Fcl_EYE_Close_R"), _index("Fcl_EYE_Joy_R")])
	_visemes_at.clear()
	for shape_name in VISEME_SHAPES:
		_visemes_at.append(_index(shape_name))
	face_mesh = mesh
	return true


## The face shapes this face speaks (Fcl names), by index. For the debug panel.
func shape_names() -> PackedStringArray:
	return _names


## What shape `i` was written at this frame, before the shape map (0 if untouched). For the debug panel.
func shown(i: int) -> float:
	return _shown.get(i, 0.0)


## One face entry with its own envelope. shapes: {Fcl shape: weight at intensity 1}.
## hold -1 keeps it at its peak until end(), a crossfade, or max_hold (s at the
## peak, 0 = no limit). A new entry in the same layer and slot crossfades out the
## old one over this entry's attack (at least 0.06 s). Returns false (and does
## nothing) if anything is wrong with it.
func play(layer: String, slot: String, shapes: Dictionary, intensity: float, attack: float, hold: float,
		release: float, curve: String, full_mouth := false, max_hold := 0.0) -> bool:
	if layer not in LAYERS:
		push_error("AvatarFace: unknown layer '%s'" % layer)
		return false
	if curve not in CURVES:
		push_error("AvatarFace: unknown curve '%s'" % curve)
		return false
	if intensity < 0.0 or intensity > 1.3 or attack < 0.0 or release < 0.0 or (hold < 0.0 and hold != -1.0) \
			or max_hold < 0.0:
		push_error("AvatarFace: bad envelope (intensity %s, attack %s, hold %s, release %s, max_hold %s)"
			% [intensity, attack, hold, release, max_hold])
		return false
	var indexed := {}
	var regions := [false, false, false]
	for shape_name: String in shapes:
		if not _shape.has(shape_name):
			push_error("AvatarFace: no face shape '%s'" % shape_name)
			return false
		var i: int = _shape[shape_name]
		var w := float(shapes[shape_name])
		indexed[i] = w
		if w * intensity >= OWN_MIN and _region[i] != Region.OTHER:
			regions[_region[i]] = true
	for e: Dictionary in _entries:
		if e.layer == layer and e.slot == slot:
			_fade_out(e, maxf(attack, 0.06), curve)
	_entries.append({"layer": layer, "slot": slot, "shapes": indexed, "intensity": intensity,
		"attack": maxf(attack, 0.001), "hold": hold, "release": maxf(release, 0.001), "curve": curve,
		"full_mouth": full_mouth, "max_hold": max_hold, "regions": regions, "t": 0.0,
		# a felt face lives a little at its peak (motor noise: drawn here, not in Python)
		"drift": randf_range(0.05, 0.08) * (1.0 if randf() < 0.5 else -1.0), "hz": randf_range(0.3, 0.6),
		"fading": false, "fade_from": 0.0, "fade_t": 0.0, "fade_len": 0.0, "fade_curve": ""})
	return true


## Fade out the entry in (layer, slot) from where it is now. No-op if nothing plays there.
func end(layer: String, slot: String, fade := 0.2) -> void:
	if layer not in LAYERS:
		push_error("AvatarFace: unknown layer '%s'" % layer)
		return
	for e: Dictionary in _entries:
		if e.layer == layer and e.slot == slot:
			_fade_out(e, fade, "")


## The resting face: absolute targets (a shape left out goes to 0), blended at tonic_speed.
func set_tonic(shapes: Dictionary) -> bool:
	var goal := {}
	for shape_name: String in shapes:
		if not _shape.has(shape_name):
			push_error("AvatarFace: no face shape '%s'" % shape_name)
			return false
		goal[_shape[shape_name]] = float(shapes[shape_name])
	_tonic_goal = goal
	return true


func set_visemes(weights: PackedFloat32Array) -> void:
	_visemes = weights


func set_blink(left: float, right: float) -> void:
	_blink = Vector2(left, right)


## The level (0..1, drift left out) of the entry in (layer, slot), 0 if none. For tests and the panel.
func level(layer: String, slot: String) -> float:
	var out := 0.0
	for e: Dictionary in _entries:
		if e.layer == layer and e.slot == slot:
			out = maxf(out, _level(e))
	return out


func _process(delta: float) -> void:
	if face_mesh == null:
		return
	if gaze:
		_lid = clampf((gaze.eye_angles.y - 6.0) / 30.0, 0.0, 0.3)
	_update_talk(delta)

	# 1. The tonic moves toward its targets.
	var k := 1.0 - exp(-tonic_speed * delta)
	for i: int in _tonic_goal:
		_tonic_now[i] = lerpf(_tonic_now.get(i, 0.0), _tonic_goal[i], k)
	for i: int in _tonic_now.keys():
		if not _tonic_goal.has(i):
			_tonic_now[i] = lerpf(_tonic_now[i], 0.0, k)
			if _tonic_now[i] < 0.0005:
				_tonic_now.erase(i)

	# 2. Entries follow their envelopes; 3. felt and display entries own the regions they move.
	for e: Dictionary in _entries:
		e.t += delta
		if e.fading:
			e.fade_t += delta
	_entries = _entries.filter(func(e: Dictionary) -> bool: return not _done(e))
	var own := [0.0, 0.0, 0.0]
	var values := {}  # shape index -> weight; talk-keep applies to its mouth shapes
	var whole := {}  # mouth shapes talk-keep leaves alone (full-mouth entries: laughs)
	var lid_most := Vector2.ZERO  # the most any one entry (or the tonic) closes each eye
	var lid_leak := Vector2.ZERO  # how much the leaks close each eye
	for e: Dictionary in _entries:
		var lv := _level(e)
		if e.layer != "leak":
			for r in 3:
				if e.regions[r]:
					own[r] = maxf(own[r], lv)
		var w: float = lv * e.intensity * _drift(e)
		var lid := Vector2.ZERO
		for i: int in e.shapes:
			var v: float = e.shapes[i] * w
			lid += _lid_of(i, v)
			if e.full_mouth and _region[i] == Region.MOUTH:
				whole[i] = whole.get(i, 0.0) + v
			else:
				values[i] = values.get(i, 0.0) + v
		if e.layer == "leak":
			lid_leak += lid
		else:
			lid_most = lid_most.max(lid)
	# 4. The sum: the tonic gives way where a felt or display face moves the same region.
	var tonic_lid := Vector2.ZERO
	for i: int in _tonic_now:
		var r := _region[i]
		var v: float = _tonic_now[i] * (1.0 - own[r] if r != Region.OTHER else 1.0)
		values[i] = values.get(i, 0.0) + v
		tonic_lid += _lid_of(i, v)
	lid_most = lid_most.max(tonic_lid)

	# 5. Talk-keep: while the lips move, mouth shapes that fight them are turned down.
	if _talk > 0.0005:
		for i: int in values.keys():
			if _region[i] != Region.MOUTH:
				continue
			var shape_name := _names[i]
			var keep := lerpf(1.0, float(TALK_KEEP.get(shape_name, TALK_KEEP_OTHER)), _talk)
			var lost: float = values[i] * (1.0 - keep)
			values[i] *= keep
			if TALK_MOVE.has(shape_name):
				var j := _index(TALK_MOVE[shape_name])
				whole[j] = whole.get(j, 0.0) + lost  # not reduced again
	for i: int in whole:
		values[i] = values.get(i, 0.0) + whole[i]

	# 6. Caps; 7. visemes; 8. blinks and lids.
	_cap(values, lid_most, lid_leak)
	for v in VISEMES.size():
		var i := _visemes_at[v]
		values[i] = values.get(i, 0.0) + _visemes[v]
	_apply_blinks(values)

	# 9. Write through the model's shape map: everything touched now, plus zeros
	# for anything touched before.
	_shown.clear()
	var mesh_values := {}
	for i: int in values:
		var value := clampf(values[i], 0.0, 1.0)
		_shown[i] = value
		for target: Array in _out[i]:
			mesh_values[target[0]] = mesh_values.get(target[0], 0.0) + value * target[1]
	for m: int in _written.keys():
		if not mesh_values.has(m):
			mesh_values[m] = 0.0
	for m: int in mesh_values:
		var value := clampf(mesh_values[m], 0.0, 1.0)
		if absf(_written.get(m, -1.0) - value) > 0.0005:
			face_mesh.set_blend_shape_value(m, value)
			_written[m] = value


## The talk factor follows the lips: 1 while a viseme moved within LIPS_HOLD s, smoothed.
func _update_talk(delta: float) -> void:
	var lips := 0.0
	for v in _visemes:
		lips = maxf(lips, v)
	_since_lips = 0.0 if lips > LIPS_ON else _since_lips + delta
	var target := 1.0 if _since_lips <= LIPS_HOLD else 0.0
	_talk = lerpf(_talk, target, 1.0 - exp(-TALK_SPEED * delta))


## An entry's level right now (0..1, without the drift).
func _level(e: Dictionary) -> float:
	if e.fading:
		return e.fade_from * (1.0 - _fall_fade(e.fade_curve, clampf(e.fade_t / e.fade_len, 0.0, 1.0)))
	var t: float = e.t
	if t < e.attack:
		return _rise(e.curve, t / e.attack)
	var top := _top(e)
	if t < e.attack + top:
		return 1.0
	return 1.0 - _fall(e.curve, clampf((t - e.attack - top) / e.release, 0.0, 1.0))


## A felt entry drifts +-5-8% at 0.3-0.6 Hz once it reaches its peak (continuous: it multiplies the level).
func _drift(e: Dictionary) -> float:
	if e.curve != "felt":
		return 1.0
	return 1.0 + e.drift * sin(TAU * e.hz * maxf(0.0, e.t - e.attack))


## Time at the peak: the hold, or max_hold (or forever) when held open.
func _top(e: Dictionary) -> float:
	if e.hold >= 0.0:
		return e.hold
	return e.max_hold if e.max_hold > 0.0 else INF


func _rise(curve: String, x: float) -> float:
	return ease(x, 0.4) if curve == "deliberate" else smoothstep(0.0, 1.0, x)  # on purpose: a fast start


func _fall(curve: String, x: float) -> float:
	return ease(x, 0.6) if curve == "deliberate" else smoothstep(0.0, 1.0, x)  # on purpose: a quick drop


## Fade from the current level over `fade` s. A crossfade uses the incoming entry's
## rise as its mirror image, so a shape both faces share moves straight from one
## weight to the other.
func _fade_out(e: Dictionary, fade: float, crossfade_curve: String) -> void:
	if _done(e):
		return
	e.fade_from = _level(e)
	e.fade_len = maxf(fade, 0.01)
	e.fade_t = 0.0
	e.fade_curve = "rise:" + crossfade_curve if crossfade_curve != "" else ""
	e.fading = true


func _done(e: Dictionary) -> bool:
	if e.fading:
		return e.fade_t >= e.fade_len
	return e.t >= e.attack + _top(e) + e.release


## Fades: 1 - rise of the incoming entry for a crossfade, smoothstep otherwise.
func _fall_fade(fade_curve: String, x: float) -> float:
	return _rise(fade_curve.substr(5), x) if fade_curve.begins_with("rise:") else smoothstep(0.0, 1.0, x)


## Shapes that fight each other: keep what the face is mostly doing.
## lid_most: the most any one entry closes each eye; lid_leak: what the leaks add (see LID_KNEE).
func _cap(values: Dictionary, lid_most: Vector2, lid_leak: Vector2) -> void:
	# Brows: raised and lowered brows share one pair (the worried inner brow, BRW_Sorrow, can join either:
	# with BRW_Angry it's the distress brow).
	_scale_sum(values, ["Fcl_BRW_Angry", "Fcl_BRW_Fun", "Fcl_BRW_Joy", "Fcl_BRW_Surprised"], 1.0)
	# Eyes can't be wide open and shut at once: the weaker side gives way.
	var open := _sum(values, ["Fcl_EYE_Spread", "Fcl_EYE_Surprised"])
	var shut := _weight(values, "Fcl_EYE_Close") + maxf(_weight(values, "Fcl_EYE_Close_L"), _weight(values, "Fcl_EYE_Close_R")) \
		+ _weight(values, "Fcl_EYE_Angry")
	if open > 0.1 and shut > 0.1:
		if open >= 0.7 * shut:
			_scale(values, ["Fcl_EYE_Close", "Fcl_EYE_Close_L", "Fcl_EYE_Close_R", "Fcl_EYE_Angry"], 0.3)
		else:
			_scale(values, ["Fcl_EYE_Spread", "Fcl_EYE_Surprised"], 0.3)
	# Lids: stacked faces saturate, and each eye closes at most LID_MAX (shared shapes scale for the fuller eye).
	var both := _sum(values, ["Fcl_EYE_Close", "Fcl_EYE_Joy"])
	var left := both + _sum(values, ["Fcl_EYE_Close_L", "Fcl_EYE_Joy_L"])
	var right := both + _sum(values, ["Fcl_EYE_Close_R", "Fcl_EYE_Joy_R"])
	var f_left := _lid_factor(left, lid_most.x, lid_leak.x)
	var f_right := _lid_factor(right, lid_most.y, lid_leak.y)
	if f_left < 1.0 or f_right < 1.0:
		_scale(values, ["Fcl_EYE_Close", "Fcl_EYE_Joy"], minf(f_left, f_right))
		_scale(values, ["Fcl_EYE_Close_L", "Fcl_EYE_Joy_L"], f_left)
		_scale(values, ["Fcl_EYE_Close_R", "Fcl_EYE_Joy_R"], f_right)
	# A pursed mouth and a wide one cancel by their overlap; the whole mouth stays believable.
	var small := _weight(values, "Fcl_MTH_Small")
	var large := _weight(values, "Fcl_MTH_Large")
	if small > 0.0 and large > 0.0:
		var overlap := minf(small, large)
		_put(values, "Fcl_MTH_Small", small - overlap)
		_put(values, "Fcl_MTH_Large", large - overlap)
	var mouth := 0.0
	for i: int in values:
		if _region[i] == Region.MOUTH:
			mouth += values[i]
	if mouth > 1.3:
		for i: int in values.keys():
			if _region[i] == Region.MOUTH:
				values[i] *= 1.3 / mouth


## How much of one eye's lid shapes stay. `total` is everything closing it, `most` the biggest single entry
## (it always keeps its closure), `leak` what leaks add (on top of the saturated rest).
func _lid_factor(total: float, most: float, leak: float) -> float:
	if total <= 0.0:
		return 1.0
	var rest := maxf(0.0, total - leak)
	var allowed := rest if rest <= LID_KNEE else LID_KNEE + (rest - LID_KNEE) * LID_STACK
	allowed = minf(maxf(allowed, most) + leak, LID_MAX)
	return minf(1.0, allowed / total)


## How much shape `i` at weight `v` closes each eye.
func _lid_of(i: int, v: float) -> Vector2:
	if i in _lid_both:
		return Vector2(v, v)
	if i in _lid_left:
		return Vector2(v, 0.0)
	if i in _lid_right:
		return Vector2(0.0, v)
	return Vector2.ZERO


## A blink closes what's still open of each eye; eye shapes that fight a closed lid
## fade with it. The lids also follow the eyes down a little.
func _apply_blinks(values: Dictionary) -> void:
	var both := _sum(values, ["Fcl_EYE_Close", "Fcl_EYE_Joy"])
	var closed := Vector2(both + _sum(values, ["Fcl_EYE_Close_L", "Fcl_EYE_Joy_L"]),
		both + _sum(values, ["Fcl_EYE_Close_R", "Fcl_EYE_Joy_R"]))
	var most := maxf(_blink.x, _blink.y)
	if most > 0.0:
		for i in _fighting:
			if i >= 0 and values.has(i):
				values[i] *= 1.0 - most
	var lids := Vector2(maxf(_blink.x, _lid), maxf(_blink.y, _lid))
	var i_left := _index("Fcl_EYE_Close_L")
	var i_right := _index("Fcl_EYE_Close_R")
	values[i_left] = values.get(i_left, 0.0) + lids.x * (1.0 - clampf(closed.x, 0.0, 1.0))
	values[i_right] = values.get(i_right, 0.0) + lids.y * (1.0 - clampf(closed.y, 0.0, 1.0))


func _add_shape(shape_name: String, targets: Array) -> void:
	_shape[shape_name] = _names.size()
	_names.append(shape_name)
	_region.append(Region.BROWS if shape_name.begins_with("Fcl_BRW_") else Region.EYES
		if shape_name.begins_with("Fcl_EYE_") else Region.MOUTH if shape_name.begins_with("Fcl_MTH_") else Region.OTHER)
	_out.append(targets)


func _index(shape_name: String) -> int:
	return _shape.get(shape_name, -1)


func _weight(values: Dictionary, shape_name: String) -> float:
	return values.get(_index(shape_name), 0.0)


func _put(values: Dictionary, shape_name: String, value: float) -> void:
	var i := _index(shape_name)
	if values.has(i):
		values[i] = value


func _sum(values: Dictionary, names: Array) -> float:
	var total := 0.0
	for shape_name: String in names:
		total += _weight(values, shape_name)
	return total


func _scale(values: Dictionary, names: Array, factor: float) -> void:
	for shape_name: String in names:
		_put(values, shape_name, _weight(values, shape_name) * factor)


func _scale_sum(values: Dictionary, names: Array, limit: float) -> void:
	var total := _sum(values, names)
	if total > limit:
		_scale(values, names, limit / total)

