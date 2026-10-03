@tool
class_name AvatarRig
extends SkeletonModifier3D
## Writes her bone rotations every frame, on top of whatever pose a body clip
## gives the skeleton (VRM hair physics runs after it). Layers, in order:
##   body clip -> standing pose -> weight shift & sway -> breathing -> gestures -> head look -> eyes
## Behavior nodes (gaze, gestures, clips, director) only set inputs; this applies them.
## A body clip's AnimationPlayer poses the bones before any modifier runs (the
## skeleton updates its modifiers after all nodes have processed); the clip
## layer fades that pose in over the rest pose by AvatarClips.weight, and the
## procedural body layers fade out by the same weight. The head look stays at
## clip_head_look on top of the clip; the eyes always run in full.
## Each model scene has its own (under its GeneralSkeleton): the inspector holds
## that model's standing pose and eye values. AvatarModel hands it the behavior
## nodes when it loads the model.
## In the editor only the standing pose runs, so framing the shot shows the real pose.

const Ramps := preload("res://avatar/ramps.gd")
## A freeze slows her idle motion (sway, drift, weight shift) to this, within
## FREEZE_IN s, and lets it come back over FREEZE_OUT s. Slowing it rather than
## shrinking it keeps her exactly where she was when it hit.
const FREEZE_MOTION := 0.2
const FREEZE_IN := 0.08
const FREEZE_OUT := 0.3

## The behavior nodes (set by AvatarModel when it loads this model; null in the editor).
var gaze: AvatarGaze
var gestures: AvatarGestures
var clips: AvatarClips

@export_group("Standing pose")
## 1 = procedural pose. A body clip fades it out on its own while it plays.
@export_range(0.0, 1.0) var pose_weight := 1.0
@export_range(0.0, 90.0) var arms_down := 82.0
@export_range(-20.0, 30.0) var arms_forward := 16.0
@export_range(0.0, 60.0) var elbow_bend := 25.0
## Turns the forearms so the palms face the thighs, like relaxed arms do.
@export_range(-90.0, 90.0) var forearm_twist := 55.0
@export_range(0.0, 40.0) var finger_curl := 16.0

@export_group("Life")
@export var breaths_per_minute := 14.0
@export_range(0.0, 3.0) var breath_depth := 1.0
@export_range(0.0, 3.0) var sway := 1.0
## Degrees both shoulders are held up (tension while she hides something); followed at 1/s.
@export_range(0.0, 10.0) var shoulder_lift := 0.0

@export_group("Body clips")
## How much of her head look (gaze turns, not gestures) stays on top of a body
## clip. The clip moves her head with the dance; this keeps a hint of her
## turning toward what she looks at. Her eyes keep tracking in full either way.
@export_range(0.0, 1.0) var clip_head_look := 0.35

@export_group("Eyes")
## Where her eyes sit from the head bone (head bone space, +Z forward): the
## VRM's lookAt offset. Gaze aims from here; the camera frames it.
@export var eye_offset := Vector3.ZERO
## VRM lookAt range maps (degrees of eye bone rotation at a 90 degree target).
@export var eye_outer := 12.0
@export var eye_inner := 8.0
@export var eye_up := 10.0
@export var eye_down := 10.0
## The VRM range map moves the eyes very little; these make a look to the side
## or up read on stream. Bone limits keep the iris inside the eye white.
@export var eye_gain := 1.8
@export var eye_gain_vertical := 2.0
@export var eye_limit_out := 8.0
@export var eye_limit_in := 6.0
@export var eye_limit_up := 7.0
@export var eye_limit_down := 6.0

## Set by Speech while she talks: exhales stretch out, inhales happen in pauses.
var speaking := false
## Temporary multipliers on sway, breaths_per_minute, breath_depth and shoulder_lift (body_ramp).
var ramps := Ramps.new()

## Read-outs for the debug panel (effective values, after ramps and the freeze).
var sway_now := 1.0
var breaths_now := 14.0
var depth_now := 1.0
var breath_held_s := 0.0  # seconds of held breath left
var frozen_s := 0.0  # seconds of freeze left

var _clip := 0.0  # how much a body clip drives her body (AvatarClips.weight)
var _held_breath := 0.0  # seconds left holding her breath
var _freeze_level := 0.0  # 0 moving freely .. 1 frozen
var _freeze_exhale := 0.0  # gesture strength of the exhale that ends the freeze
var _shoulders_now := 0.0

var _bones := {}
var _time := 0.0
var _breath_phase := 0.3
var _weight := 0.0
var _weight_goal := 0.0
var _noise := FastNoiseLite.new()


func _init() -> void:
	_noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_noise.seed = randi()


## Breathe in now (before speaking, between sentences). Continues from the
## current breath level, so there's never a jump.
func inhale() -> void:
	if _breath_phase < 0.4:
		return  # already breathing in
	# Start the inhale at the current level: x = inverse smoothstep(level).
	var level := clampf(_breath(), 0.0, 1.0)
	_breath_phase = 0.4 * (0.5 - sin(asin(1.0 - 2.0 * level) / 3.0))


## Hold her breath for a moment (a hit, a fright): the chest stays where it is.
func hold_breath(seconds: float) -> void:
	_held_breath = maxf(_held_breath, seconds)


## Freeze for `seconds`: idle motion slows to FREEZE_MOTION, the breath is held
## for `breath` s, and at the end she exhales (gesture strength `exhale`, 0 = none).
## A freeze that arrives during one extends it; one exhale ends it.
func freeze(seconds: float, breath: float, exhale: float) -> void:
	frozen_s = maxf(frozen_s, seconds)
	_freeze_exhale = exhale
	hold_breath(breath)


## Move her weight to the other leg (posture shift).
func shift_weight() -> void:
	_weight_goal = -signf(_weight_goal if _weight_goal != 0.0 else randf() - 0.5) * randf_range(0.5, 1.0)


func _skeleton_changed(_old: Skeleton3D, _new: Skeleton3D) -> void:
	_bones.clear()


func _process_modification_with_delta(delta: float) -> void:
	var skel := get_skeleton()
	if skel == null:
		return
	if _bones.is_empty():
		_cache_bones(skel)
	if not Engine.is_editor_hint() and clips:
		_clip = clips.weight
		_apply_clip(skel)
	_apply_pose(skel)
	if Engine.is_editor_hint():
		return

	ramps.advance(delta)
	if frozen_s > 0.0:
		frozen_s = maxf(0.0, frozen_s - delta)
		if frozen_s == 0.0 and _freeze_exhale > 0.0 and gestures:
			gestures.play("exhale", _freeze_exhale)
	_freeze_level = move_toward(_freeze_level, 1.0 if frozen_s > 0.0 else 0.0,
		delta / (FREEZE_IN if frozen_s > 0.0 else FREEZE_OUT))
	var motion := lerpf(1.0, FREEZE_MOTION, _freeze_level)
	_time += delta * motion
	# Speech breathing: a quick inhale before talking, a long exhale through the sentence.
	breaths_now = breaths_per_minute * ramps.factor("breaths_per_minute")
	var rate := breaths_now / 60.0
	if speaking:
		rate *= 4.0 if _breath_phase < 0.4 else 0.45
	if _held_breath > 0.0:
		_held_breath = maxf(0.0, _held_breath - delta)
		rate = 0.0
	breath_held_s = _held_breath
	_breath_phase = fmod(_breath_phase + delta * rate, 1.0)
	_weight = lerpf(_weight, _weight_goal, 1.0 - exp(-1.5 * delta * motion))
	sway_now = sway * ramps.factor("sway") * motion
	depth_now = breath_depth * ramps.factor("breath_depth")
	_shoulders_now = lerpf(_shoulders_now, shoulder_lift * ramps.factor("shoulder_lift"), 1.0 - exp(-delta))
	_apply_body(skel)
	_apply_head(skel)
	_apply_eyes(skel)


# --- body clip ---------------------------------------------------------------

## The clip's pose (already on the bones) faded over the rest pose; at weight 0
## the bones are back at rest, where the layers below expect them.
func _apply_clip(skel: Skeleton3D) -> void:
	if _clip >= 1.0:
		return
	for bone in clips.bones:
		var rest := skel.get_bone_rest(bone)
		skel.set_bone_pose_position(bone, rest.origin.lerp(skel.get_bone_pose_position(bone), _clip))
		skel.set_bone_pose_rotation(bone, rest.basis.get_rotation_quaternion().slerp(skel.get_bone_pose_rotation(bone), _clip))


# --- standing pose -----------------------------------------------------------

func _apply_pose(skel: Skeleton3D) -> void:
	var w := pose_weight * (1.0 - _clip)
	if w <= 0.0:
		return
	for side: float in [1.0, -1.0]:  # 1 = her left (+X), -1 = her right
		var s := "Left" if side > 0.0 else "Right"
		# Relaxed shoulders, arms hanging slightly forward with a soft elbow.
		_rotate_global(skel, _b(s + "Shoulder"), Basis(Vector3.BACK, deg_to_rad(-4.0 * side * w)))
		var down := Basis(Vector3.BACK, deg_to_rad(-arms_down * side * w))
		var forward := Basis(Vector3.RIGHT, deg_to_rad(-arms_forward * w))
		_rotate_global(skel, _b(s + "UpperArm"), forward * down)
		var lower := _b(s + "LowerArm")
		var hand := _b(s + "Hand")
		_rotate_global(skel, lower, Basis(Vector3.RIGHT, deg_to_rad(-elbow_bend * w)))
		if lower >= 0:
			# Turn the palm toward the thigh around the forearm's length. Most of it
			# happens at the wrist: VRoid has no twist bones, so turning at the elbow
			# wrings the skin there and the black outline shows through the crease.
			var along := (skel.get_bone_global_pose(lower).basis * Vector3.UP).normalized()
			_rotate_global(skel, lower, Basis(along, deg_to_rad(forearm_twist * 0.25 * side * w)))
			_rotate_global(skel, hand, Basis(along, deg_to_rad(forearm_twist * 0.75 * side * w)))
		_rotate_global(skel, hand, Basis(Vector3.BACK, deg_to_rad(6.0 * side * w)))
		# Fingers curl more toward the little finger, like a resting hand.
		var spread := {"Index": 0.8, "Middle": 1.0, "Ring": 1.15, "Little": 1.3}
		for finger: String in spread:
			for joint: String in ["Proximal", "Intermediate", "Distal"]:
				var amount: float = finger_curl * spread[finger] * (1.4 if joint == "Intermediate" else 1.0) * w
				_rotate_local(skel, _b(s + finger + joint), Quaternion(Vector3.RIGHT, deg_to_rad(amount)))
		for joint: String in ["Proximal", "Distal"]:
			_rotate_local(skel, _b(s + "Thumb" + joint), Quaternion(Vector3.BACK, deg_to_rad(finger_curl * 0.8 * side * w)))


# --- weight shift, sway, breathing, body gestures ---------------------------

func _apply_body(skel: Skeleton3D) -> void:
	var t := _time
	var own := 1.0 - _clip  # a body clip takes over all of it
	var amount := sway * ramps.factor("sway") * own

	# Weight shift: hips slide and tilt toward the standing leg, spine
	# counter-tilts so the upper body stays upright.
	var hips := _b("Hips")
	var lean := _weight + _n(1, t * 0.05) * 0.35
	if hips >= 0:
		var offset := Vector3(lean * 0.012 + _n(2, t * 0.11) * 0.003, 0.0, _n(3, t * 0.07) * 0.004) * amount
		skel.set_bone_pose_position(hips, skel.get_bone_pose_position(hips) + offset)
	var hip_roll := lean * 1.6 * amount
	_rotate_local(skel, hips, _euler(0.0, _n(4, t * 0.06) * 1.2 * amount, hip_roll))
	_rotate_local(skel, _b("Spine"), _euler(_n(5, t * 0.08) * 0.8 * amount, 0.0, -hip_roll * 0.6))
	_rotate_local(skel, _b("Chest"), _euler(0.0, _n(6, t * 0.07) * 1.0 * amount, -hip_roll * 0.35))

	var breath := _breath() * depth_now * own
	var g_chest := gestures.chest * own if gestures else Vector3.ZERO
	var g_shoulders := gestures.shoulders * own if gestures else 0.0
	_rotate_local(skel, _b("UpperChest"), _euler(-1.1 * breath + g_chest.x * 0.6, g_chest.y * 0.6, g_chest.z * 0.6))
	_rotate_local(skel, _b("Chest"), _euler(-0.5 * breath + g_chest.x * 0.4, g_chest.y * 0.4, g_chest.z * 0.4))
	for side: float in [1.0, -1.0]:
		var lift := 1.4 * breath + g_shoulders + _shoulders_now * own
		_rotate_global(skel, _b(("Left" if side > 0.0 else "Right") + "Shoulder"), Basis(Vector3.BACK, deg_to_rad(lift * side)))


## 0 (breathed out) .. 1 (breathed in): quick inhale (40% of the cycle), slow exhale.
func _breath() -> float:
	var p := _breath_phase
	return smoothstep(0.0, 1.0, p / 0.4) if p < 0.4 else 1.0 - smoothstep(0.0, 1.0, (p - 0.4) / 0.6)


# --- head and eyes -----------------------------------------------------------

func _apply_head(skel: Skeleton3D) -> void:
	var t := _time
	var own := 1.0 - _clip
	var look := Vector3.ZERO  # pitch (down +), yaw (her left +), roll, in degrees
	if gaze:
		look = Vector3(gaze.head_pitch, gaze.head_yaw, 0.0) * lerpf(1.0, clip_head_look, _clip)
	if gestures:
		look += gestures.head * own
	# Slow head drift so she's never perfectly still (eyes compensate).
	look += Vector3(_n(7, t * 0.13) * 1.2, _n(8, t * 0.11) * 1.5, _n(9, t * 0.09) * 1.2) * sway * ramps.factor("sway") * own
	# Spread the turn over the chain: chest a little, neck more, head most.
	_rotate_local(skel, _b("UpperChest"), _euler(look.x * 0.1, look.y * 0.12, look.z * 0.1))
	_rotate_local(skel, _b("Neck"), _euler(look.x * 0.4, look.y * 0.38, look.z * 0.4))
	_rotate_local(skel, _b("Head"), _euler(look.x * 0.5, look.y * 0.5, look.z * 0.5))


func _apply_eyes(skel: Skeleton3D) -> void:
	if gaze == null:
		return
	var head := skel.get_bone_global_pose(_b("Head"))
	var target := skel.global_transform.affine_inverse() * gaze.eye_point
	# Target direction in head space -> perceived yaw/pitch.
	var d := head.basis.orthonormalized().inverse() * (target - head * eye_offset)
	var yaw := rad_to_deg(atan2(d.x, d.z))
	var pitch := rad_to_deg(atan2(-d.y, Vector2(d.x, d.z).length()))
	var v_scale := (eye_down if pitch > 0.0 else eye_up) / 90.0
	var bone_pitch := clampf(clampf(pitch, -90.0, 90.0) * v_scale * eye_gain_vertical, -eye_limit_up, eye_limit_down)
	for side: float in [1.0, -1.0]:
		var bone := _b("LeftEye" if side > 0.0 else "RightEye")
		if bone < 0:
			continue
		# VRM range map: looking 90 degrees aside = only eye_outer degrees of bone.
		var outward := yaw * side > 0.0
		var bone_yaw := clampf(yaw, -90.0, 90.0) * (eye_outer if outward else eye_inner) / 90.0 * eye_gain
		bone_yaw = clampf(bone_yaw, -eye_limit_in, eye_limit_out) if side > 0.0 else clampf(bone_yaw, -eye_limit_out, eye_limit_in)
		var rest := skel.get_bone_rest(bone).basis.get_rotation_quaternion()
		skel.set_bone_pose_rotation(bone, _euler(bone_pitch, bone_yaw, 0.0) * rest)


# --- helpers -----------------------------------------------------------------

func _cache_bones(skel: Skeleton3D) -> void:
	for i in skel.get_bone_count():
		_bones[skel.get_bone_name(i)] = i


func _b(bone_name: String) -> int:
	return _bones.get(bone_name, -1)


## Rotate a bone by `rot`, given in skeleton space, on top of its current pose.
func _rotate_global(skel: Skeleton3D, bone: int, rot: Basis) -> void:
	if bone < 0:
		return
	var parent := skel.get_bone_parent(bone)
	var parent_basis := skel.get_bone_global_pose(parent).basis.orthonormalized() if parent >= 0 else Basis()
	var current := parent_basis * Basis(skel.get_bone_pose_rotation(bone))
	skel.set_bone_pose_rotation(bone, (parent_basis.inverse() * rot * current).get_rotation_quaternion())


## Rotate a bone in its own local frame.
func _rotate_local(skel: Skeleton3D, bone: int, rot: Quaternion) -> void:
	if bone >= 0:
		skel.set_bone_pose_rotation(bone, skel.get_bone_pose_rotation(bone) * rot)


## Degrees -> quaternion. Pitch + looks down, yaw + turns to her left, roll + tilts to her right.
func _euler(pitch: float, yaw: float, roll: float) -> Quaternion:
	return Quaternion.from_euler(Vector3(deg_to_rad(pitch), deg_to_rad(yaw), deg_to_rad(roll)))


## Smooth noise in -1..1, one independent channel per `channel`.
func _n(channel: int, t: float) -> float:
	return _noise.get_noise_2d(t * 100.0, channel * 1000.0)
