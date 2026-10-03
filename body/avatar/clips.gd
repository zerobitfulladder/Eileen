class_name AvatarClips
extends Node
## Body animation clips (dances, a sitting idle) on her skeleton. `player`
## (the loaded model's ClipPlayer, bind()) holds animations/clips.res (built by
## animations/build_clips.gd) and poses the bones; AvatarRig reads `weight`
## and, by it, fades the clip in over her rest pose and her procedural body
## (standing pose, sway, breathing, gestures) out, and back when the clip
## ends. Her face, blinks and eyes keep going. A clip loops until end(); one
## started while another plays crossfades from it. The clips are retargeted to
## the humanoid profile, so they fit every model; a model without one of the
## bones they move (Miku has no UpperChest) just doesn't move it.

## Default fade, seconds.
const FADE := 0.4

## The loaded model's clip player and skeleton (bind()); null until a model loads.
var player: AnimationPlayer
var skeleton: Skeleton3D

## Read by AvatarRig: how much the clip drives her body, 0 (her own) .. 1 (all clip), eased.
var weight := 0.0
## Bones the clips move (AvatarRig fades exactly these).
var bones := PackedInt32Array()

var _level := 0.0  # weight before easing
var _goal := 0.0
var _fade := FADE


## Play clips on a newly loaded model: its ClipPlayer and skeleton. Starts
## with her own body (no clip). Warns once about bones the clips move that
## this model doesn't have.
func bind(clip_player: AnimationPlayer, model_skeleton: Skeleton3D) -> void:
	player = clip_player
	skeleton = model_skeleton
	bones.clear()
	_level = 0.0
	_goal = 0.0
	weight = 0.0
	var root := player.get_node(player.root_node)
	var missing := {}
	for clip in player.get_animation_list():
		var anim := player.get_animation(clip)
		for t in anim.get_track_count():
			var path := anim.track_get_path(t)
			var bone_name := path.get_concatenated_subnames()
			var bone := skeleton.find_bone(bone_name)
			if root.get_node_or_null(NodePath(path.get_concatenated_names())) != skeleton:
				push_error("AvatarClips: clip '%s' moves something that isn't one of her bones: %s" % [clip, path])
			elif bone < 0:
				missing[bone_name] = true
			elif bone not in bones:
				bones.append(bone)
	if not missing.is_empty():
		push_warning("AvatarClips: %s has no %s; the clips' tracks for it do nothing"
			% [root.name, ", ".join(PackedStringArray(missing.keys()))])


## The clips she can play, by name (none until a model loads).
func names() -> PackedStringArray:
	var list := PackedStringArray()
	if player == null:
		return list
	for clip in player.get_animation_list():
		if clip != "RESET":
			list.append(clip)
	list.sort()
	return list


## Play a clip, looping, until end(): from her own body it fades in over
## `fade` s, from another clip it crossfades; the clip already playing just
## goes on. Returns false (and does nothing) for an unknown clip or a negative fade.
func play(clip: String, fade := FADE) -> bool:
	if player == null:
		push_error("AvatarClips: no model loaded yet, can't play '%s'" % clip)
		return false
	if clip not in names():
		push_error("AvatarClips: no clip '%s' (there are: %s)" % [clip, ", ".join(names())])
		return false
	if fade < 0.0:
		push_error("AvatarClips: fade must be >= 0, got %s" % fade)
		return false
	if player.is_playing():
		player.play(clip, fade)
	else:
		player.play(clip)
	player.advance(0.0)  # pose its first frame now, before AvatarRig fades it in
	_goal = 1.0
	_fade = fade
	return true


## Back to her own body: the clip fades out over `fade` s, then stops.
## Nothing playing: no-op. Returns false (and does nothing) for a negative fade.
func end(fade := FADE) -> bool:
	if fade < 0.0:
		push_error("AvatarClips: fade must be >= 0, got %s" % fade)
		return false
	_goal = 0.0
	_fade = fade
	return true


func _process(delta: float) -> void:
	if player == null:
		return
	_level = move_toward(_level, _goal, delta / maxf(_fade, 0.001))
	weight = smoothstep(0.0, 1.0, _level)
	if _level == 0.0 and player.is_playing():
		player.stop(true)  # her bones are already back at rest (AvatarRig, weight 0)
