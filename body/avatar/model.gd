class_name AvatarModel
extends Node3D
## Her body: the 3D model the brain picks (`uv run server.py --model lucy`).
## On every connect the brain sends {"cmd": "model", "name": ...} before
## anything else; this loads res://models/<name>/<name>.tscn here and binds the
## parts that move her (gaze, face, clips, speech) to its Parts (ModelParts).
## The model already loaded stays (the brain restarted with it); another one
## replaces it. An unknown name is refused. Until the first `model` command
## there is no body, and everything that moves her waits.

signal loaded(parts: ModelParts)  ## a model is in and her parts are bound to it

const MODELS := "res://models/"

@export var gaze: AvatarGaze
@export var gestures: AvatarGestures
@export var clips: AvatarClips
@export var face: AvatarFace
@export var speech: Speech

## The loaded model's parts; null until the first `model` command.
var parts: ModelParts
## The loaded model's name; "" until then.
var model_name := ""

var _scene: Node3D  # the loaded model scene


## Load the model `model` and bind her parts to it; the one already loaded
## stays. Returns false (and changes nothing) if there is no such model or its
## scene is missing a part.
func load_model(model: String) -> bool:
	if model == model_name:
		print("AvatarModel: keeping ", model)
		return true
	var path := "%s%s/%s.tscn" % [MODELS, model, model]
	if not model.is_valid_filename() or not ResourceLoader.exists(path):
		push_error("AvatarModel: no model '%s' (there are: %s)" % [model, ", ".join(available())])
		return false
	var scene := (load(path) as PackedScene).instantiate() as Node3D
	var new_parts := scene.get_node_or_null(^"Parts") as ModelParts
	if new_parts == null:
		push_error("AvatarModel: %s has no Parts node (ModelParts)" % path)
		scene.free()
		return false
	if not new_parts.check(path):
		scene.free()
		return false
	if _scene:
		remove_child(_scene)
		_scene.queue_free()
	_scene = scene
	parts = new_parts
	model_name = model
	# Bind before it enters the tree: its rig runs as soon as it does.
	parts.rig.gaze = gaze
	parts.rig.gestures = gestures
	parts.rig.clips = clips
	clips.bind(parts.clip_player, parts.skeleton())
	face.bind(parts.face_mesh, parts.shape_map)
	speech.rig = parts.rig
	add_child(scene)
	gaze.bind(parts.rig)  # needs her place in the world
	print("AvatarModel: loaded ", model)
	loaded.emit(parts)
	return true


## The models there are: folders in res://models/ with a scene of their name.
func available() -> PackedStringArray:
	var names := PackedStringArray()
	for folder in DirAccess.get_directories_at(MODELS):
		if ResourceLoader.exists("%s%s/%s.tscn" % [MODELS, folder, folder]):
			names.append(folder)
	return names
