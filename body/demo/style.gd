extends RefCounted
## The demo layer's look: fonts, colors, panels (the mind panel's palette, plus a rose accent).

const ACCENT := Color(1.0, 0.56, 0.76)
const TITLE := Color(0.85, 0.7, 1.0)
const TEXT := Color(0.9, 0.88, 0.94)
const DIM := Color(0.6, 0.57, 0.67)
const BG := Color(0.05, 0.03, 0.08, 0.86)
const VIEWER_COLORS := [Color(0.55, 0.85, 1.0), Color(0.6, 0.95, 0.65), Color(1.0, 0.8, 0.45),
	Color(0.85, 0.7, 1.0), Color(1.0, 0.6, 0.55)]


static func font(weight := 400) -> SystemFont:
	var f := SystemFont.new()
	f.font_names = PackedStringArray(["Adwaita Sans"])
	f.font_weight = weight
	return f


static func panel(bg := BG, border := Color(1, 1, 1, 0.08)) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = bg
	s.border_color = border
	s.set_border_width_all(1)
	s.set_corner_radius_all(8)
	s.set_content_margin_all(12.0)
	return s


static func label(size: int, color := TEXT, weight := 400) -> Label:
	var l := Label.new()
	l.add_theme_font_override("font", font(weight))
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return l


static func rich(size: int) -> RichTextLabel:
	var r := RichTextLabel.new()
	r.bbcode_enabled = true
	r.fit_content = true
	r.scroll_active = false
	r.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	r.mouse_filter = Control.MOUSE_FILTER_IGNORE
	r.add_theme_font_override("normal_font", font(400))
	r.add_theme_font_override("bold_font", font(700))
	for kind: String in ["normal_font_size", "bold_font_size"]:
		r.add_theme_font_size_override(kind, size)
	r.add_theme_color_override("default_color", TEXT)
	return r
