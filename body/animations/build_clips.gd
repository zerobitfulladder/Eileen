@tool
extends EditorScript
## Builds her body clips (animations/clips.res, played by AvatarClips) from
## every Mixamo FBX in animations/mixamo/. Run it in the script editor
## (File > Run, Ctrl+Shift+X) after adding or changing a clip. It:
##   1. writes the retargeting settings below into each FBX's .import and
##      reimports them (edit RETARGET here, not in the import dialog),
##   2. keeps each clip in place (hip travel across the floor taken out; sway,
##      steps and height kept), makes it loop, and gives it a track for every
##      mapped bone,
##   3. saves them as one AnimationLibrary, each clip named after its file,
##      plus RESET (her rest pose), which the editor applies before saving a
##      scene so a clip previewed there never gets saved into her pose.
## To add a clip: download it from Mixamo as FBX, Without Skin, save it as
## animations/mixamo/<name>.fbx (snake_case: the name is what the brain sends),
## let the editor import it, then run this.

const SOURCES := "res://animations/mixamo/"
const BONE_MAP := "res://animations/mixamo/bone_map.tres"
const LIBRARY := "res://animations/clips.res"
## The skeleton the rest tracks and hip height come from. Every model gets the
## same rest rotations from the VRM importer (Overwrite Axis) and position
## tracks scale by each skeleton's motion_scale, so the clips fit all of them.
const AVATAR := "res://models/eileen/eileen.vrm"
const HIPS := &"Hips"
## Import settings besides the retargeting (tracks that never leave the rest pose are dropped).
const ANIMATION := {"animation/import": true, "animation/remove_immutable_tracks": true}
## Retargeting onto SkeletonProfileHumanoid with the axes the VRM importer gave
## her skeleton (Overwrite Axis), so a clip's bone rotations fit her bones.
const RETARGET := {
	"retarget/bone_renamer/rename_bones": true,
	"retarget/bone_renamer/unique_node/make_unique": true,
	"retarget/bone_renamer/unique_node/skeleton_name": "GeneralSkeleton",
	# Off: on these files (Godot 4.7.2) it also drops every rotation track; the
	# build keeps only bone transform tracks itself.
	"retarget/remove_tracks/except_bone_transform": false,
	"retarget/remove_tracks/unimportant_positions": true,
	"retarget/remove_tracks/unmapped_bones": true,
	"retarget/rest_fixer/apply_node_transforms": true,
	"retarget/rest_fixer/normalize_position_tracks": true,  # her skeleton's motion_scale scales them back
	"retarget/rest_fixer/reset_all_bone_poses_after_import": true,
	"retarget/rest_fixer/retarget_method": 1,  # Overwrite Axis
	# Turns bones that sit more than `threshold` degrees off the reference T-pose
	# toward it (Mixamo's thumbs and shoulders). The feet stay out: Mixamo's
	# foot bone points 53 degrees down, hers 30, a difference of build, not
	# pose, and straightening it would tilt her feet in every frame.
	"retarget/rest_fixer/fix_silhouette/enable": true,
	"retarget/rest_fixer/fix_silhouette/filter": [&"LeftFoot", &"RightFoot", &"LeftToes", &"RightToes"],
	"retarget/rest_fixer/fix_silhouette/threshold": 15.0,
	"retarget/rest_fixer/fix_silhouette/base_height_adjustment": 0.0,
}
## Hip travel slower than this is taken out (seconds: the width of the
## Gaussian whose smoothed path is subtracted). Quicker sway and steps stay.
const IN_PLACE := 0.5
## Warn when a clip's last frame is this far from its first (it jumps on every loop).
const SEAM_DEGREES := 5.0
const SEAM_METERS := 0.03


func _run() -> void:
	var sources := PackedStringArray()
	for file in DirAccess.get_files_at(SOURCES):
		if file.get_extension() == "fbx":
			sources.append(SOURCES + file)
	if sources.is_empty():
		push_error("build_clips: no .fbx files in %s" % SOURCES)
		return
	sources.sort()
	for fbx in sources:
		if not _write_import_settings(fbx):
			return
	EditorInterface.get_resource_filesystem().reimport_files(sources)
	_build(sources)


## Sets the FBX's import settings (Advanced Import Settings > Skeleton3D shows the retargeting).
func _write_import_settings(fbx: String) -> bool:
	var config := ConfigFile.new()
	if config.load(fbx + ".import") != OK:
		push_error("build_clips: %s has no .import yet; let the editor import it first" % fbx)
		return false
	for key: String in ANIMATION:
		config.set_value("params", key, ANIMATION[key])
	var skeleton := RETARGET.duplicate()
	skeleton["retarget/bone_map"] = load(BONE_MAP)
	config.set_value("params", "_subresources", {"nodes": {"PATH:Skeleton3D": skeleton}})
	return config.save(fbx + ".import") == OK


func _build(sources: PackedStringArray) -> void:
	var avatar: Node = load(AVATAR).instantiate()
	var her: Skeleton3D = avatar.get_node("GeneralSkeleton")
	# Every clip moves the same bones: all that the bone map maps.
	var bone_map: BoneMap = load(BONE_MAP)
	var bones := PackedStringArray()
	for i in bone_map.profile.bone_size:
		var bone := bone_map.profile.get_bone_name(i)
		if bone_map.get_skeleton_bone_name(bone) == &"":
			continue
		if her.find_bone(bone) < 0:
			push_error("build_clips: her skeleton has no bone '%s'" % bone)
			avatar.free()
			return
		bones.append(bone)
	var clips := {}
	for fbx in sources:
		var anim := _clip(fbx, her, bones)
		if anim == null:
			avatar.free()
			return
		clips[fbx.get_file().get_basename()] = anim
	clips["RESET"] = _fill_rest(Animation.new(), her, bones)
	avatar.free()
	# Rebuild the library in place, so the scene that plays it sees the new clips.
	var library := AnimationLibrary.new()
	if ResourceLoader.exists(LIBRARY):
		library = load(LIBRARY)
	for clip in library.get_animation_list():
		library.remove_animation(clip)
	for clip: String in clips:
		library.add_animation(clip, clips[clip])
	var err := ResourceSaver.save(library, LIBRARY)
	if err != OK:
		push_error("build_clips: couldn't save %s (%s)" % [LIBRARY, error_string(err)])
		return
	EditorInterface.get_resource_filesystem().update_file(LIBRARY)
	print("build_clips: saved %d clips to %s" % [clips.size() - 1, LIBRARY])


## One retargeted clip, cleaned up; null (with an error) if it can't be used.
func _clip(fbx: String, her: Skeleton3D, bones: PackedStringArray) -> Animation:
	var source: PackedScene = ResourceLoader.load(fbx, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	var scene := source.instantiate()
	var players := scene.find_children("*", "AnimationPlayer", true, false)
	if players.size() != 1 or (players[0] as AnimationPlayer).get_animation_list().size() != 1:
		push_error("build_clips: %s should hold exactly one animation" % fbx)
		scene.free()
		return null
	var player := players[0] as AnimationPlayer
	var anim := player.get_animation(player.get_animation_list()[0]).duplicate(true) as Animation
	scene.free()
	# Only the bone transforms of her mapped bones.
	for t in range(anim.get_track_count() - 1, -1, -1):
		if anim.track_get_type(t) not in [Animation.TYPE_POSITION_3D, Animation.TYPE_ROTATION_3D, Animation.TYPE_SCALE_3D]:
			anim.remove_track(t)
			continue
		var path := anim.track_get_path(t)
		var bone := String(path.get_concatenated_subnames())
		if String(path.get_concatenated_names()) != "%GeneralSkeleton" or bone not in bones:
			push_error("build_clips: %s moves %s, which isn't a retargeted bone of hers (is the bone map right?)"
				% [fbx, path])
			return null
	var seam := _seam(anim)
	if seam.x > SEAM_DEGREES or seam.y * her.motion_scale > SEAM_METERS:
		push_warning("build_clips: %s ends %.0f degrees / %.2f m away from its start; it will jump each time it loops"
			% [fbx, seam.x, seam.y * her.motion_scale])
	var rest := her.get_bone_rest(her.find_bone(HIPS)).origin / her.motion_scale
	var travel := _keep_in_place(anim, Vector2(rest.x, rest.z))
	_fill_rest(anim, her, bones)
	anim.loop_mode = Animation.LOOP_LINEAR
	print("build_clips: %s, %.1f s, hip travel of up to %.2f m taken out"
		% [fbx.get_file().get_basename(), anim.length, travel * her.motion_scale])
	return anim


## How far the last frame is from the first: (largest bone turn in degrees,
## hip distance in the clip's normalized units).
func _seam(anim: Animation) -> Vector2:
	var seam := Vector2.ZERO
	for t in anim.get_track_count():
		if anim.track_get_type(t) == Animation.TYPE_ROTATION_3D:
			var turn := anim.rotation_track_interpolate(t, 0.0).angle_to(anim.rotation_track_interpolate(t, anim.length))
			seam.x = maxf(seam.x, rad_to_deg(turn))
		elif anim.track_get_type(t) == Animation.TYPE_POSITION_3D:
			var gap := anim.position_track_interpolate(t, 0.0).distance_to(anim.position_track_interpolate(t, anim.length))
			seam.y = maxf(seam.y, gap)
	return seam


## Takes the hips' slow travel across the floor out of a looping clip, so she
## dances where she stands: subtracts a Gaussian-smoothed copy of the hips'
## horizontal path (wrapping around the loop) and centers what's left on
## `center`. Height is untouched. Returns the largest travel taken out.
func _keep_in_place(anim: Animation, center: Vector2) -> float:
	var track := anim.find_track(NodePath("%GeneralSkeleton:" + HIPS), Animation.TYPE_POSITION_3D)
	if track < 0:
		return 0.0  # the hips never leave their rest position
	var smooth := PackedVector2Array()
	for k in anim.track_get_key_count(track):
		smooth.append(_smoothed_path(anim, track, anim.track_get_key_time(track, k)))
	var travel := 0.0
	for k in anim.track_get_key_count(track):
		var p: Vector3 = anim.track_get_key_value(track, k)
		var flat := Vector2(p.x, p.z) - smooth[k] + center
		anim.track_set_key_value(track, k, Vector3(flat.x, p.y, flat.y))
		travel = maxf(travel, smooth[k].distance_to(center))
	return travel


## The hips' horizontal position around `time`, Gaussian-smoothed over IN_PLACE seconds.
func _smoothed_path(anim: Animation, track: int, time: float) -> Vector2:
	var sum := Vector2.ZERO
	var weights := 0.0
	var step := 1.0 / 60.0
	var offset := -3.0 * IN_PLACE
	while offset <= 3.0 * IN_PLACE:
		var w := exp(-0.5 * pow(offset / IN_PLACE, 2.0))
		var p := anim.position_track_interpolate(track, fposmod(time + offset, anim.length))
		sum += Vector2(p.x, p.z) * w
		weights += w
		offset += step
	return sum / weights


## Adds a one-key rest track for each of `bones` that `anim` doesn't move
## (rotation, plus position for the hips), so every clip writes the same bones
## and a crossfade into a clip that doesn't move a bone takes it back to rest.
func _fill_rest(anim: Animation, her: Skeleton3D, bones: PackedStringArray) -> Animation:
	for bone in bones:
		var rest := her.get_bone_rest(her.find_bone(bone))
		var path := NodePath("%GeneralSkeleton:" + bone)
		if bone == HIPS and anim.find_track(path, Animation.TYPE_POSITION_3D) < 0:
			var t := anim.add_track(Animation.TYPE_POSITION_3D)
			anim.track_set_path(t, path)
			anim.position_track_insert_key(t, 0.0, rest.origin / her.motion_scale)  # played back times motion_scale
		if anim.find_track(path, Animation.TYPE_ROTATION_3D) < 0:
			var t := anim.add_track(Animation.TYPE_ROTATION_3D)
			anim.track_set_path(t, path)
			anim.rotation_track_insert_key(t, 0.0, rest.basis.get_rotation_quaternion())
	return anim
