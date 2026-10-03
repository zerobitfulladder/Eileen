extends ColorRect
## The demo's title and end card: the whole frame, a big name, a line under it.

const Style := preload("res://demo/style.gd")

var _title := Style.label(120, Color.WHITE, 300)
var _sub := Style.label(34, Style.TITLE, 400)
var _small := Style.label(20, Style.DIM, 400)


func _ready() -> void:
	color = Color(0.035, 0.02, 0.055, 1.0)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var box := VBoxContainer.new()
	box.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	box.grow_horizontal = Control.GROW_DIRECTION_BOTH
	box.grow_vertical = Control.GROW_DIRECTION_BOTH
	box.alignment = BoxContainer.ALIGNMENT_CENTER
	box.add_theme_constant_override("separation", 14)
	for l: Label in [_title, _sub, _small]:
		l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		box.add_child(l)
	_title.add_theme_constant_override("outline_size", 0)
	add_child(box)
	visible = false


## Show the card (fading in when it wasn't up).
func show_card(title: String, sub: String, small: String) -> void:
	_title.text = title
	_sub.text = sub
	_small.text = small
	if not visible:
		modulate.a = 0.0
		show()
		create_tween().tween_property(self, "modulate:a", 1.0, 0.8)


## Fade it out.
func hide_card(fade: float) -> void:
	var tween := create_tween()
	tween.tween_property(self, "modulate:a", 0.0, fade)
	tween.tween_callback(hide)
