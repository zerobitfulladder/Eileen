extends Control
## The demo's pointer: a soft, pulsing outline around what a caption is about
## (sections of the mind panel, the demo's own widgets). It follows its target
## as it grows and glides between targets.

const Style := preload("res://demo/style.gd")
const PAD := 6.0
const GLIDE := 8.0  # per second

var _target: Callable  # () -> Rect2 in canvas coordinates; Rect2() = nothing
var _rect := Rect2()
var _alpha := 0.0
var _time := 0.0
var _box := StyleBoxFlat.new()


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_box.draw_center = false
	_box.set_border_width_all(3)
	_box.set_corner_radius_all(10)
	_box.shadow_size = 14


## Outline what `target` returns each frame (an empty Rect2 hides the outline).
func track(target: Callable) -> void:
	if _alpha <= 0.0:
		_rect = (target.call() as Rect2).grow(PAD)  # appears in place; only moves between targets glide
	_target = target


func _process(delta: float) -> void:
	_time += delta
	var target := (_target.call() as Rect2) if _target.is_valid() else Rect2()
	var goal := 0.0 if target.size == Vector2.ZERO else 1.0
	_alpha = move_toward(_alpha, goal, delta * 3.0)
	if goal > 0.0:
		target = target.grow(PAD)
		var k := 1.0 - exp(-GLIDE * delta)
		_rect = Rect2(_rect.position.lerp(target.position, k), _rect.size.lerp(target.size, k))
	queue_redraw()


func _draw() -> void:
	if _alpha <= 0.0:
		return
	var pulse := 0.5 + 0.5 * sin(_time * TAU * 0.8)
	var color := Style.ACCENT
	color.a = _alpha * (0.65 + 0.35 * pulse)
	_box.border_color = color
	_box.shadow_color = Style.ACCENT * Color(1, 1, 1, _alpha * 0.25 * (0.6 + 0.4 * pulse))
	draw_style_box(_box, _rect)
