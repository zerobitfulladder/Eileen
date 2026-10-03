extends HBoxContainer
## Debug bar: try any expression / reaction, camera shot / move or body clip on
## its own. The expression and camera lists come from the brain when it
## connects; the body clips are Godot assets, listed from AvatarClips once a
## model loads. Pick an item to play it; the play button repeats the current
## pick, the stop button ends the body clip.

@export var link: AvatarLink
@export var clips: AvatarClips
@export var model: AvatarModel

var _expressions := OptionButton.new()
var _camera := OptionButton.new()
var _animations := OptionButton.new()


func _ready() -> void:
	for pair: Array in [[_expressions, "Expression…"], [_camera, "Camera…"], [_animations, "Animation…"]]:
		var menu: OptionButton = pair[0]
		menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		menu.add_item(pair[1])
		menu.focus_mode = Control.FOCUS_NONE  # keep typing in the chat box
		add_child(menu)
		var again := Button.new()
		again.text = "▶"
		again.focus_mode = Control.FOCUS_NONE
		again.pressed.connect(_play.bind(menu))
		add_child(again)
	var stop := Button.new()
	stop.text = "■"
	stop.focus_mode = Control.FOCUS_NONE
	stop.pressed.connect(func(): clips.end())
	add_child(stop)
	_expressions.item_selected.connect(func(_i): _play(_expressions))
	_camera.item_selected.connect(func(_i): _play(_camera))
	_animations.item_selected.connect(func(_i): _play(_animations))
	link.catalog_received.connect(_on_catalog)
	model.loaded.connect(_on_model_loaded)


## The body clips the loaded model can play.
func _on_model_loaded(_parts: ModelParts) -> void:
	_animations.clear()
	_animations.add_item("Animation…")
	for clip in clips.names():
		_animations.add_item(clip)


func _on_catalog(catalog: Dictionary) -> void:
	_fill(_expressions, "Expression…", catalog.get("expressions", {}))
	_fill(_camera, "Camera…", catalog.get("camera", {}))


func _fill(menu: OptionButton, title: String, groups: Dictionary) -> void:
	menu.clear()
	menu.add_item(title)
	for group: String in groups:
		menu.add_separator(group)
		for item: String in groups[group]:
			menu.add_item(item)
	menu.select(0)


func _play(menu: OptionButton) -> void:
	if menu.selected <= 0:
		return
	var item := menu.get_item_text(menu.selected)
	if menu == _expressions:
		link.perform(item)
	elif menu == _camera:
		link.camera_test(item)
	else:
		clips.play(item)
