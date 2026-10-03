extends Node
## The demo video (res://demo/demo.tscn, recorded with demo/record.sh): her real
## stage (main.tscn) with a presentation layer on top, run by demo/steps.gd.
## Only the chat lines are scripted, typed into the chat box like a viewer
## would; her mind, her lines, her voice and her body come live from the brain
## (`uv run server.py --model eileen`). Around her: her mind panel (state) on
## the left; on the right what she feels against what her face shows, the
## mind's calculation trace and the chat (viewers only: she's heard, not
## read); a pipeline strip on top lit by the brain's real stage events and her
## body's commands; captions; a glow around whatever a caption is about.
##
## Under the movie writer (--write-movie) frames come at a fixed rate; each
## frame is held back to the wall clock so the brain's timing stays true. The
## times of the beats go to <movie>.markers.json (the silence is sped up afterwards).
## `-- --stop-after=40` ends a take after 40 s (to check the layout).

const Steps := preload("res://demo/steps.gd")
const Style := preload("res://demo/style.gd")
const MindPanel := preload("res://ui/mind_panel.gd")
const Pipeline := preload("res://demo/pipeline.gd")
const Caption := preload("res://demo/caption.gd")
const ChatFeed := preload("res://demo/chat_feed.gd")
const Outline := preload("res://demo/outline.gd")
const Card := preload("res://demo/card.gd")
const Feelings := preload("res://demo/feelings.gd")
const Trace := preload("res://demo/trace.gd")

const SIZE := Vector2i(1920, 1080)
const MARGIN := 16.0
const TOP := 104.0  # below the pipeline strip
const SIDE := 560.0  # the left and right columns
const FEELINGS_HEIGHT := 392.0
const TRACE_HEIGHT := 330.0
const CHAT_HEIGHT := 52.0
const GAP := 12.0
## The mind panel's sections (the state); emotions are on the right, big.
const PANEL_SECTIONS := ["Mind", "Mood", "Wound", "Drives", "People", "Actor is told"]
## Typing: seconds per character (more after a space), then a beat before Enter.
const KEY_TIME := Vector2(0.035, 0.09)
const ENTER_PAUSE := 0.5
const REPLY_TIMEOUT := 60.0
## The silence plays at normal speed this long before the sped-up part starts.
const FAST_LEAD := 3.0

var _link: AvatarLink
var _speech: Speech
var _model: AvatarModel
var _panel: MindPanel
var _chat_box: LineEdit
var _pipeline := Pipeline.new()
var _caption := Caption.new()
var _feed := ChatFeed.new()
var _outline := Outline.new()
var _card := Card.new()
var _feelings := Feelings.new()
var _trace := Trace.new()
var _badge := Style.label(22, Style.ACCENT, 700)

var _movie := ""
var _start_us := 0
var _game_time := 0.0
var _pending := 0  # replies on their way or playing (chat messages sent, turns she took on her own)
var _spoke_on_own := false
var _appraising := false  # her mind is reading a chat message (between "appraiser" and "mind")
var _markers: Array[Dictionary] = []


func _ready() -> void:
	var window := get_window()
	window.content_scale_mode = Window.CONTENT_SCALE_MODE_VIEWPORT
	window.content_scale_aspect = Window.CONTENT_SCALE_ASPECT_KEEP
	window.content_scale_size = SIZE
	_movie = Engine.get_write_movie_path()
	var main := (load("res://main.tscn") as PackedScene).instantiate()
	_panel = main.get_node("DebugUI/MindPanel")
	_panel.font_size = 14
	_panel.small_size = 12
	add_child(main)
	_panel.set_note("Mind", "")
	_link = main.get_node("Avatar/Link")
	_speech = main.get_node("Avatar/Speech")
	_model = main.get_node("Model")
	_chat_box = main.get_node("DebugUI/ChatBox")
	_layout(main)
	_build_overlay()
	_link.stage_received.connect(_on_stage)
	_link.executed.connect(_pipeline.body)
	_link.mind_received.connect(_feelings.update)
	_link.mind_received.connect(_trace.update)
	_speech.sentence_started.connect(func(_info: Dictionary) -> void: _pipeline.speaking())
	_speech.finished.connect(_on_finished)
	_start_us = Time.get_ticks_usec()
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--stop-after="):
			get_tree().create_timer(arg.trim_prefix("--stop-after=").to_float()).timeout.connect(_end)
	_run()


func _process(delta: float) -> void:
	_game_time += delta
	if _movie.is_empty():
		return
	var ahead := _game_time - (Time.get_ticks_usec() - _start_us) / 1e6
	if ahead > 0.0:
		OS.delay_usec(int(ahead * 1e6))


# --- the stage -----------------------------------------------------------------

func _layout(main: Node) -> void:
	(main.get_node("DebugUI/DebugBar") as Control).hide()
	_place(_panel, Rect2(MARGIN, TOP, SIDE, SIZE.y - TOP - MARGIN))
	_panel.focus(PANEL_SECTIONS)
	_place(_chat_box, Rect2(SIZE.x - MARGIN - SIDE, SIZE.y - MARGIN - CHAT_HEIGHT, SIDE, CHAT_HEIGHT))
	_chat_box.placeholder_text = "Send a message"
	_chat_box.add_theme_font_override("font", Style.font())
	_chat_box.add_theme_font_size_override("font_size", 19)


func _build_overlay() -> void:
	var layer := CanvasLayer.new()
	layer.layer = 20
	add_child(layer)
	var root := Control.new()
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	layer.add_child(root)
	root.add_child(_pipeline)
	_place(_pipeline, Rect2(MARGIN, MARGIN, SIZE.x - 2.0 * MARGIN, TOP - 2.0 * MARGIN))
	var right := SIZE.x - MARGIN - SIDE
	root.add_child(_feelings)
	_place(_feelings, Rect2(right, TOP, SIDE, FEELINGS_HEIGHT))
	root.add_child(_trace)
	var trace_y := TOP + FEELINGS_HEIGHT + GAP
	_place(_trace, Rect2(right, trace_y, SIDE, TRACE_HEIGHT))
	root.add_child(_feed)
	var feed_y := trace_y + TRACE_HEIGHT + GAP
	_place(_feed, Rect2(right, feed_y, SIDE, SIZE.y - MARGIN - CHAT_HEIGHT - GAP - feed_y))
	root.add_child(_caption)
	var left := MARGIN + SIDE + 24.0
	_caption.set_anchors_preset(Control.PRESET_TOP_LEFT)
	_caption.grow_vertical = Control.GROW_DIRECTION_BEGIN  # it grows up from the bottom edge
	_caption.offset_left = left
	_caption.offset_right = right - 24.0
	_caption.offset_top = SIZE.y - MARGIN
	_caption.offset_bottom = SIZE.y - MARGIN
	root.add_child(_outline)
	var badge_style := Style.panel(Color(0.06, 0.03, 0.09, 0.9), Style.ACCENT * Color(1, 1, 1, 0.6))
	badge_style.set_content_margin_all(8.0)
	_badge.add_theme_stylebox_override("normal", badge_style)
	_badge.text = "▶▶"
	root.add_child(_badge)
	_badge.position = Vector2(SIZE.x / 2.0 - 40.0, TOP + 8.0)
	_badge.hide()
	root.add_child(_card)


func _place(control: Control, rect: Rect2) -> void:
	control.set_anchors_preset(Control.PRESET_TOP_LEFT)
	control.position = rect.position
	control.size = rect.size


# --- what happens live ---------------------------------------------------------

func _on_stage(msg: Dictionary) -> void:
	var stage := String(msg.get("stage", ""))
	if stage == "mind" and _own_turn(msg):  # she speaks on her own
		_pending += 1
		_spoke_on_own = true
		_pipeline.begin_own()
		_mark("her own turn")
	_appraising = stage == "appraiser"
	_pipeline.stage(msg)


## A "mind" stage that no chat message started: her mind's turn came from a drive.
func _own_turn(msg: Dictionary) -> bool:
	return String(msg.get("gist", "")).is_empty() and not _appraising


func _on_finished() -> void:
	_pipeline.finish()
	_pending = maxi(0, _pending - 1)


# --- the script ----------------------------------------------------------------

func _run() -> void:
	for step: Dictionary in Steps.STEPS:
		await _do(step)
	_end()


func _end() -> void:
	_mark("end")
	_save_markers()
	get_tree().quit()


func _do(step: Dictionary) -> void:
	if step.has("card"):
		_card.show_card(step.card, step.get("sub", ""), step.get("small", ""))
		await _sleep(float(step.get("hold", 0.0)))
	elif step.has("uncard"):
		_card.hide_card(float(step.uncard))
	elif step.has("wait"):
		await _wait_model()
	elif step.has("outline"):
		_outline.track(_rect_of.bind(step.outline))
	elif step.has("caption"):
		_caption.say(step.caption)
	elif step.has("pause"):
		await _sleep(float(step.pause))
	elif step.has("chat"):
		await _chat(step.chat)
	elif step.has("silence"):
		await _silence(float(step.silence), float(step.get("speed", 1.0)))
	else:
		push_error("DemoDirector: unknown step %s" % step)


## The brain connects and loads her body; then a fresh mind for this take.
func _wait_model() -> void:
	if _model.parts == null:
		await _model.loaded
	_link.reset_chat()
	_mark("model")
	await _sleep(1.5)


## Type a chat line like a viewer, send it, and wait until her reply has played.
func _chat(line: String) -> void:
	await _until_idle(REPLY_TIMEOUT)
	var colon := line.find(": ")
	if colon <= 0 or line.left(colon).contains(" "):
		push_error("DemoDirector: a chat line needs its viewer, like \"mira: hi\": %s" % line)
		return
	var sender := line.left(colon)
	var text := line.substr(colon + 2)
	_chat_box.clear()
	for c in line:
		_chat_box.insert_text_at_caret(c)
		await _sleep(randf_range(KEY_TIME.x, KEY_TIME.y) * (1.8 if c == " " else 1.0))
	await _sleep(ENTER_PAUSE)
	await _until_idle(REPLY_TIMEOUT)  # she started talking on her own while it was typed: Enter once she's done
	_pending += 1
	_mark("chat: " + line)
	_chat_box.text_submitted.emit(_chat_box.text)
	_feed.viewer(sender, text)
	_pipeline.begin("%s: %s" % [sender, text])
	await _until_idle(REPLY_TIMEOUT)


## Nobody writes until she speaks on her own (at most `longest` s); the wait is
## marked to be sped up `speed` times, with a badge on screen while it lasts.
func _silence(longest: float, speed: float) -> void:
	await _until_idle(REPLY_TIMEOUT)
	_spoke_on_own = false
	await _sleep(FAST_LEAD)
	var from := _game_time
	_badge.text = "▶▶ %d×" % int(speed)
	_badge.show()
	var waited := 0.0
	while not _spoke_on_own and waited < longest:
		await get_tree().process_frame
		waited += get_process_delta_time()
	_badge.hide()
	_markers.append({"fast_from": from, "fast_to": _game_time, "speed": speed})
	if not _spoke_on_own:
		push_error("DemoDirector: she didn't speak on her own within %.0f s" % longest)
		return
	await _until_idle(REPLY_TIMEOUT)
	await _sleep(1.5)


## Where these are on screen, together: mind panel sections by title, or the
## demo's own parts ("feelings", "trace", "pipeline", "chat"). Empty: nothing.
func _rect_of(names: Array) -> Rect2:
	var parts := {"feelings": _feelings, "trace": _trace, "pipeline": _pipeline, "chat": _feed}
	var rect := Rect2()
	for name: String in names:
		var r := (parts[name] as Control).get_global_rect() if parts.has(name) else _panel.section_rect(name)
		rect = r if rect.size == Vector2.ZERO else rect.merge(r)
	return rect


func _until_idle(timeout: float) -> void:
	var waited := 0.0
	while _pending > 0:
		await get_tree().process_frame
		waited += get_process_delta_time()
		if waited > timeout:
			push_error("DemoDirector: her replies didn't finish within %.0f s" % timeout)
			_pending = 0


func _sleep(seconds: float) -> void:
	if seconds > 0.0:
		await get_tree().create_timer(seconds).timeout


func _mark(what: String) -> void:
	_markers.append({"t": _game_time, "what": what})


func _save_markers() -> void:
	var path := (_movie.get_basename() if _movie else "user://demo") + ".markers.json"
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("DemoDirector: can't write %s" % path)
		return
	file.store_string(JSON.stringify(_markers, "  "))
