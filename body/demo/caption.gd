extends PanelContainer
## The demo's explanation at the bottom: one or two lines that say what just
## happened inside her. A new caption fades the old one out first.

const Style := preload("res://demo/style.gd")
const FADE := 0.35

var _text := Style.rich(25)
var _tween: Tween


func _ready() -> void:
	var style := Style.panel(Color(0.06, 0.03, 0.09, 0.9), Style.ACCENT * Color(1, 1, 1, 0.45))
	style.border_width_left = 4
	style.content_margin_left = 20.0
	style.content_margin_right = 20.0
	style.content_margin_top = 12.0
	style.content_margin_bottom = 14.0
	add_theme_stylebox_override("panel", style)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_text.add_theme_constant_override("line_separation", 4)
	add_child(_text)
	modulate.a = 0.0
	visible = false


## Show this text ("" hides the caption).
func say(text: String) -> void:
	if _tween:
		_tween.kill()
	_tween = create_tween()
	if visible and modulate.a > 0.0:
		_tween.tween_property(self, "modulate:a", 0.0, FADE * modulate.a)
	if text.is_empty():
		_tween.tween_callback(hide)
		return
	_tween.tween_callback(func() -> void:
		_text.text = text
		offset_top = offset_bottom  # its height follows the new text (it grows up from the bottom edge)
		show())
	_tween.tween_property(self, "modulate:a", 1.0, FADE)
