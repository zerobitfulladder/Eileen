class_name AvatarGaze
extends Node
## Where she looks.
## Eyes jump between fixation points (saccades: fast, duration grows with
## distance) and then hold still apart from tiny micro-saccades. The head
## starts a beat later, moves slower and only takes part of the turn, so eyes
## and head never move in lockstep. A look can move only the eyes (mode
## "eyes": a side eye, an eye roll; the head stays until the next normal look)
## or glide the eyes smoothly instead of jumping (a slow slide back). All angles
## are relative to her body: yaw + = her left, pitch + = down, in degrees as a
## person would perceive them. Her eyes are where the loaded model's rig says
## (bind(), from AvatarModel); until a model loads there's nothing to aim.

const Ramps := preload("res://avatar/ramps.gd")
const MODES: PackedStringArray = ["normal", "eyes"]
## A freeze cuts the micro-saccades to this (and lets them back over FREEZE_OUT s).
const FREEZE_MICRO := 0.3
const FREEZE_IN := 0.08
const FREEZE_OUT := 0.3

signal saccade_started(amplitude: float)  ## degrees; big ones often come with a blink

## Fraction of a gaze shift the head takes on; the eyes cover the rest.
@export_range(0.0, 1.0) var head_share := 0.65
## Furthest the eyes sit off the head direction before the head has to follow.
@export var eye_range := 18.0
## Head spring speed (higher = snappier head turns).
@export var head_speed := 7.0
## Size of the small fixational eye jumps, degrees.
@export var micro_saccade := 2.0

## Temporary multipliers on head_share, head_speed, micro_saccade and eye_range (body_ramp).
var ramps := Ramps.new()
## The loaded model's rig and skeleton (bind()); null until a model loads.
var rig: AvatarRig
var skeleton: Skeleton3D

## Outputs, read by AvatarRig.
var head_yaw := 0.0
var head_pitch := 0.0
var eye_point := Vector3.ZERO  ## global point the eyes converge on
var eye_angles := Vector2.ZERO  ## current eye direction (yaw, pitch), body-relative degrees

var _node: Node3D
var _point := Vector3.ZERO  # global target when there's no node
var _offset := Vector2.ZERO  # yaw/pitch offset on top of the target (reading, etc.)

var _eyes := Vector2.ZERO  # current eye direction (yaw, pitch)
var _sacc_from := Vector2.ZERO
var _sacc_to := Vector2.ZERO
var _sacc_t := 1.0
var _sacc_dur := 0.05
var _micro := Vector2.ZERO
var _micro_in := 0.6

var _head := Vector2.ZERO
var _head_vel := Vector2.ZERO
var _head_goal := Vector2.ZERO
var _head_delay := 0.0
var _distance := 1.5
var _eyes_only := false  # the head stays where it is (a side eye, an eye roll)
var _glide_next := 0.0  # the next eye movement glides over this many seconds (0 = a saccade)
var _gliding := false
var _frozen := 0.0  # seconds left in a freeze
var _freeze_level := 0.0


## Aim from a newly loaded model's eyes, looking straight ahead.
func bind(model_rig: AvatarRig) -> void:
	rig = model_rig
	skeleton = rig.get_skeleton()
	_node = null
	_offset = Vector2.ZERO
	_point = _eye_center() + _body_basis() * Vector3.BACK * 1.5


## Look at a node (follows it if it moves). `offset` shifts the gaze by yaw/pitch degrees.
## mode "eyes": only the eyes go there. glide > 0: the eyes travel smoothly over that many seconds.
func look_at_node(node: Node3D, offset := Vector2.ZERO, mode := "normal", glide := 0.0) -> void:
	_node = node
	_offset = offset
	_set_mode(mode, glide)


## Look in a direction relative to her body (e.g. up-left while thinking).
func look_toward(yaw: float, pitch: float, mode := "normal", glide := 0.0) -> void:
	_node = null
	_offset = Vector2.ZERO
	_point = _eye_center() + _body_basis() * _direction(Vector2(yaw, pitch)) * 1.5
	_set_mode(mode, glide)


## A freeze: micro-saccades drop to FREEZE_MICRO for `seconds`, then come back.
func freeze(seconds: float) -> void:
	_frozen = maxf(_frozen, seconds)


func _set_mode(mode: String, glide: float) -> void:
	if mode not in MODES:
		push_error("AvatarGaze: unknown look mode '%s'" % mode)
	_eyes_only = mode == "eyes"
	_glide_next = maxf(glide, 0.0)


## Shift the gaze relative to the current target (reading along a line, etc.).
func nudge(delta_deg: Vector2) -> void:
	_offset += delta_deg


func set_offset(offset: Vector2) -> void:
	_offset = offset


func get_offset() -> Vector2:
	return _offset


func is_looking_at(node: Node3D) -> bool:
	return _node == node


func _process(delta: float) -> void:
	if skeleton == null:
		return
	ramps.advance(delta)
	_frozen = maxf(0.0, _frozen - delta)
	_freeze_level = move_toward(_freeze_level, 1.0 if _frozen > 0.0 else 0.0,
		delta / (FREEZE_IN if _frozen > 0.0 else FREEZE_OUT))
	var micro_size := micro_saccade * ramps.factor("micro_saccade") * lerpf(1.0, FREEZE_MICRO, _freeze_level)
	var share_now := head_share * ramps.factor("head_share")
	var speed := head_speed * ramps.factor("head_speed")
	var reach := eye_range * ramps.factor("eye_range")
	var goal := _target_angles() + _offset

	# Start a saccade (or a glide) when the target moved more than a degree;
	# smaller moves (target drifting, body sway) are followed smoothly.
	var amplitude := goal.distance_to(_sacc_to)
	if amplitude > 1.0:
		_sacc_from = _eyes
		_sacc_to = goal
		_sacc_t = 0.0
		_micro = Vector2.ZERO
		_head_delay = randf_range(0.04, 0.1)
		_gliding = _glide_next > 0.0
		if _gliding:
			_sacc_dur = _glide_next
		else:
			_sacc_dur = 0.025 + 0.0022 * amplitude  # "main sequence": bigger jumps take longer
			saccade_started.emit(amplitude)
	elif _sacc_t >= 1.0 or _gliding:
		_sacc_to = goal  # a glide follows a slowly moving target too
	_glide_next = 0.0  # a glide belongs to the move its look started

	if _sacc_t < 1.0:
		_sacc_t = minf(1.0, _sacc_t + delta / _sacc_dur)
		_eyes = _sacc_from.lerp(_sacc_to, smoothstep(0.0, 1.0, _sacc_t))
		if _sacc_t >= 1.0:
			_gliding = false
	else:
		_micro_in -= delta
		if _micro_in <= 0.0:
			_micro_in = randf_range(0.35, 1.2)
			_micro = Vector2(randfn(0.0, 1.0), randfn(0.0, 0.6)) * 0.5
		_eyes = _sacc_to + _micro * micro_size

	# Head: takes `head_share` of the turn, but never leaves the eyes more
	# than `eye_range` off-center. Critically damped spring, after a delay.
	var share := Vector2(share_now, share_now * 0.6)  # eyes do more of vertical shifts
	var head_goal := _sacc_to * share
	var off := (_sacc_to - head_goal).clamp(Vector2(-reach, -reach * 0.6), Vector2(reach, reach * 0.6))
	head_goal = _sacc_to - off
	if _head_delay > 0.0:
		_head_delay -= delta
	elif not _eyes_only:
		_head_goal = head_goal
	# The spring's exact step, stable at any frame time: a slow frame (the GPU busy
	# with her voice) must not throw the head around.
	var x0 := _head - _head_goal
	var c := _head_vel + x0 * speed
	var decay := exp(-speed * delta)
	_head = _head_goal + (x0 + c * delta) * decay
	_head_vel = (c - (x0 + c * delta) * speed) * decay
	head_yaw = _head.x
	head_pitch = _head.y

	eye_angles = _eyes
	eye_point = _eye_center() + _body_basis() * _direction(_eyes) * _distance


func _target_angles() -> Vector2:
	var target := _node.global_position if is_instance_valid(_node) else _point
	var local := _body_basis().inverse() * (target - _eye_center())
	_distance = clampf(local.length(), 0.3, 5.0)
	return Vector2(rad_to_deg(atan2(local.x, local.z)), rad_to_deg(atan2(-local.y, Vector2(local.x, local.z).length())))


func _direction(angles: Vector2) -> Vector3:
	var yaw := deg_to_rad(angles.x)
	var pitch := deg_to_rad(angles.y)
	return Vector3(sin(yaw) * cos(pitch), -sin(pitch), cos(yaw) * cos(pitch))


func _eye_center() -> Vector3:
	var head := skeleton.find_bone("Head")
	var rest := skeleton.get_bone_global_rest(head).origin + rig.eye_offset
	return skeleton.global_transform * rest


func _body_basis() -> Basis:
	return skeleton.global_basis.orthonormalized()
