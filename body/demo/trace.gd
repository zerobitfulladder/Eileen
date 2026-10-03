extends PanelContainer
## The demo's calculation trace: the brain's own lines for the latest event,
## exactly as her mind wrote them (the appraisal, each rule that fired and by
## how much, the wound, the coping move and its odds), from her mind's snapshots.

const Style := preload("res://demo/style.gd")
const LINES := 24  # the newest lines kept; what doesn't fit is cut off at the bottom

var _text := RichTextLabel.new()
var _lines: Array = []


func _ready() -> void:
	add_theme_stylebox_override("panel", Style.panel())
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 6)
	box.clip_contents = true
	var title := Style.label(16, Style.TITLE, 700)
	title.text = "CALCULATION   the mind's trace for the last event"
	box.add_child(title)
	var mono := SystemFont.new()
	mono.font_names = PackedStringArray(["DejaVu Sans Mono"])
	_text.bbcode_enabled = true
	_text.scroll_active = false
	_text.fit_content = false  # a fixed box: long traces are cut at the bottom, never spill out
	_text.clip_contents = true
	_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_text.add_theme_font_override("normal_font", mono)
	_text.add_theme_font_size_override("normal_font_size", 13)
	_text.add_theme_color_override("default_color", Style.TEXT)
	_text.add_theme_constant_override("line_separation", 2)
	box.add_child(_text)
	add_child(box)


## A {"type": "mind"} snapshot from the brain.
func update(snapshot: Dictionary) -> void:
	var lines: Array = snapshot.get("calc", [])
	if lines == _lines:
		return
	_lines = lines.duplicate()
	var out := PackedStringArray()
	for line: Variant in lines.slice(maxi(0, lines.size() - LINES)):
		var s := String(line).replace("[", "[lb]")
		if s.begins_with("#"):
			out.append("[color=#%s]%s[/color]" % [Style.ACCENT.to_html(false), s])
			continue
		var space := s.find(" ")
		if space > 0:
			out.append("[color=#%s]%s[/color]%s" % [Style.TITLE.to_html(false), s.left(space), s.substr(space)])
		else:
			out.append(s)
	_text.text = "\n".join(out)
