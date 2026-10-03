extends PanelContainer
## The demo's stream chat: viewers' messages as they're sent (newest at the
## bottom). Her words aren't written out: she's heard, not read.

const Style := preload("res://demo/style.gd")
const MAX_ROWS := 14

var _rows := VBoxContainer.new()
var _colors := {}  # viewer -> color


func _ready() -> void:
	add_theme_stylebox_override("panel", Style.panel())
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	var title := Style.label(16, Style.DIM, 600)
	title.text = "CHAT"
	box.add_child(title)
	var scroll := Control.new()  # rows hang from the bottom; old ones slide off the top
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.clip_contents = true
	box.add_child(scroll)
	_rows.add_theme_constant_override("separation", 12)
	_rows.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	_rows.grow_vertical = Control.GROW_DIRECTION_BEGIN
	scroll.add_child(_rows)
	add_child(box)


## A viewer's message.
func viewer(who: String, text: String) -> void:
	if not _colors.has(who):
		_colors[who] = Style.VIEWER_COLORS[_colors.size() % Style.VIEWER_COLORS.size()]
	var color: Color = _colors[who]
	_add("[color=#%s][b]%s[/b][/color]  %s" % [color.to_html(false), who, _escape(text)])


func _add(bbcode: String) -> void:
	var row := Style.rich(18)
	row.text = bbcode
	_rows.add_child(row)
	while _rows.get_child_count() > MAX_ROWS:
		_rows.get_child(0).free()


func _escape(text: String) -> String:
	return text.replace("[", "[lb]")
