class_name CameraRig
extends Camera3D
## A camera operator for one subject. Shots are described the way a film crew
## would: size (wide .. extreme close-up), horizontal angle around her, height
## angle (low = looking up at her, high = looking down) and dutch tilt. Her eyes
## always sit on the upper-third line. Changes can cut, move smoothly (push in /
## pull out) or snap (crash zoom). On top: a gentle handheld drift and a
## decaying shake. The brain decides the shots; this performs them.
## It films whichever model her body has loaded (it picks up a new one when
## AvatarModel loads it); until then it holds its editor transform. Once she's
## there, the node's own transform in the editor is ignored.

## Frame height in meters for each shot size (with this camera's fov).
const SHOTS := {"wide": 1.15, "medium": 0.78, "mcu": 0.52, "close": 0.34, "extreme": 0.2}

## Her body: the camera follows the eyes of the model it has loaded.
@export var model: AvatarModel
@export var base_shot := "medium"
## Degrees around her, + = to her left.
@export var base_yaw := 14.0
## Degrees, + = camera above her eyes, looking down.
@export var base_elevation := 1.0
## Constant subtle drift (0 = locked off, 1 = loose handheld).
@export_range(0.0, 1.0) var handheld := 0.15
## How quickly the operator re-centers on her when she moves (per second).
@export var follow_speed := 3.0
## How fast a shake dies down (per second).
@export var shake_decay := 1.4

var subject: Skeleton3D  # the loaded model's skeleton; null until one loads

var _from := {}
var _to := {}
var _t := 1.0
var _duration := 0.0
var _move := "move"
var _handheld_goal := 0.15
var _trauma := 0.0
var _eyes := Vector3.ZERO
var _head_pose := Transform3D()
var _head := -1
var _rig: AvatarRig  # the loaded model's rig: where her eyes sit
var _time := 0.0
var _noise := FastNoiseLite.new()


func _ready() -> void:
	_noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_noise.seed = randi()
	_handheld_goal = handheld
	_to = _shot(base_shot, base_yaw, base_elevation, 0.0)
	model.loaded.connect(_on_model_loaded)


## A new model: follow its eyes, framed at once.
func _on_model_loaded(parts: ModelParts) -> void:
	_rig = parts.rig
	subject = parts.skeleton()
	_head = subject.find_bone("Head")
	_head_pose = subject.get_bone_global_pose(_head)
	_eyes = Vector3.ZERO
	# The final pose (after her rig moves the head) is only readable here.
	subject.skeleton_updated.connect(_on_skeleton_updated.bind(subject))


func _on_skeleton_updated(skeleton: Skeleton3D) -> void:
	if skeleton == subject:
		_head_pose = subject.get_bone_global_pose(_head)


## Change the shot. move: "cut", "move" (push in / pull out) or "snap" (crash zoom).
## yaw / elevation are absolute degrees (NAN = base); yaw_offset is added to it.
func frame(shot: String, move := "move", duration := 1.5, yaw := NAN, elevation := NAN, roll := 0.0,
		yaw_offset := 0.0) -> void:
	var target := _shot(shot, (base_yaw if is_nan(yaw) else yaw) + yaw_offset,
		base_elevation if is_nan(elevation) else elevation, roll)
	_from = _state()
	_to = target
	_move = move
	_duration = 0.0 if move == "cut" else maxf(duration, 0.05)
	_t = 1.0 if move == "cut" else 0.0


## Add a jolt (0..1). Several add up; the shake fades on its own.
func shake(amount: float) -> void:
	_trauma = minf(1.0, _trauma + amount)


## Blend the handheld drift to a new amount.
func set_handheld(amount: float) -> void:
	_handheld_goal = clampf(amount, 0.0, 1.0)


func _process(delta: float) -> void:
	if subject == null:
		return
	_time += delta
	if _t < 1.0:
		_t = minf(1.0, _t + delta / _duration)
	handheld = lerpf(handheld, _handheld_goal, 1.0 - exp(-1.5 * delta))
	_trauma = maxf(0.0, _trauma - shake_decay * delta)
	var shot := _state()

	# Follow her eyes with a little lag, like an operator keeping her framed.
	var eyes := subject.global_transform * (_head_pose * _rig.eye_offset)
	_eyes = eyes if _eyes == Vector3.ZERO else _eyes.lerp(eyes, 1.0 - exp(-follow_speed * delta))

	var distance: float = shot.height / (2.0 * tan(deg_to_rad(fov) * 0.5))
	var around := Basis(Vector3.UP, deg_to_rad(shot.yaw)) * Basis(Vector3.RIGHT, deg_to_rad(-shot.elevation))
	var pos := _eyes + subject.global_basis.orthonormalized() * (around * Vector3.BACK) * distance
	# Aim a sixth of the frame below her eyes: that puts them on the upper third.
	var aim := _eyes - Vector3.UP * distance * tan(deg_to_rad(fov) / 6.0)
	var xform := Transform3D(Basis(), pos).looking_at(aim, Vector3.UP)

	# Handheld drift (slow) and shake (fast), as small turns of the camera.
	var turn := Vector3(_n(1, 0.35) * 0.5, _n(2, 0.3) * 0.6, _n(3, 0.25) * 0.4) * handheld
	var jolt := _trauma * _trauma
	turn += Vector3(_n(4, 11.0) * 2.0, _n(5, 12.0) * 2.5, _n(6, 9.0) * 3.0) * jolt
	turn.z += shot.roll
	xform.basis = xform.basis * Basis.from_euler(Vector3(deg_to_rad(turn.x), deg_to_rad(turn.y), deg_to_rad(turn.z)))
	global_transform = xform


func _shot(shot: String, yaw: float, elevation: float, roll: float) -> Dictionary:
	if not SHOTS.has(shot):
		push_warning("CameraRig: unknown shot '%s'" % shot)
	return {"height": SHOTS.get(shot, SHOTS[base_shot]), "yaw": yaw, "elevation": elevation, "roll": roll}


## Where the camera is right now between the last shot and the next.
func _state() -> Dictionary:
	if _t >= 1.0 or _from.is_empty():
		return _to
	# Moves ease in and out; a snap starts fast and settles.
	var s := 1.0 - pow(1.0 - _t, 3.0) if _move == "snap" else smoothstep(0.0, 1.0, _t)
	return {
		"height": exp(lerpf(log(_from.height), log(_to.height), s)),  # size changes evenly
		"yaw": lerpf(_from.yaw, _to.yaw, s),
		"elevation": lerpf(_from.elevation, _to.elevation, s),
		"roll": lerpf(_from.roll, _to.roll, s),
	}


func _n(channel: int, hz: float) -> float:
	return _noise.get_noise_2d(_time * hz * 100.0, channel * 1000.0)
