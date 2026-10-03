extends LineEdit
## Debug chat box, standing in for live stream chat.
##   anything      a chat message from `username`; she replies (via her mind and the LLM)
##   name: text    a chat message from someone else (e.g. "jo: hi"), to test other viewers
##   /say text     she says exactly this (tags work: [laugh], [smile], [nod]...)
##   /stop         cut her off
##   /reset        forget the chat history and start her mind fresh
##   /set jo liking 0.7 familiarity 0.8
##                 debug: how she feels about someone (liking, familiarity, threat)

@export var link: AvatarLink
## Who you are in chat; messages go out as "username: message". It's the
## project setting eileen/chat/username: project.godot has a neutral default,
## and your own name goes in override.cfg next to it, which git ignores.
var username: String = ProjectSettings.get_setting("eileen/chat/username")

## "name: text" at the start of a line: a short single word, then a colon and a space.
var _sender := RegEx.create_from_string("^([\\w.-]{1,24}): (.+)$")


func _ready() -> void:
	placeholder_text = "Chat as %s...  (jo: hi, /say text, /set jo liking 0.7, /stop, /reset)" % username
	text_submitted.connect(_on_text_submitted)
	visibility_changed.connect(_on_visibility_changed)
	grab_focus()


## Hiding the debug UI (F1) takes the focus away; showing it again gives it back,
## so typing goes on in the chat box.
func _on_visibility_changed() -> void:
	if is_visible_in_tree():
		grab_focus()


func _on_text_submitted(submitted: String) -> void:
	var line := submitted.strip_edges()
	clear()
	if line == "/stop":
		link.stop()
	elif line == "/reset":
		link.reset_chat()
	elif line.begins_with("/say "):
		link.say(line.trim_prefix("/say ").strip_edges())
	elif line.begins_with("/set "):
		_set_person(line.trim_prefix("/set ").strip_edges())
	elif not line.is_empty():
		if _sender.search(line) != null:
			link.chat(line)  # someone else in chat
		else:
			link.chat("%s: %s" % [username, line] if username else line)


## "/set jo liking 0.7 familiarity 0.8" (or liking=0.7): a debug shortcut so the
## things that need someone she likes can be tried without an hour of kind chat.
func _set_person(args: String) -> void:
	var words := args.replace("=", " ").split(" ", false)
	if words.size() < 3 or words.size() % 2 == 0:
		push_error("/set needs a name and field/value pairs, like: /set jo liking 0.7 familiarity 0.8")
		return
	var values := {}
	for i in range(1, words.size(), 2):
		var field := words[i].to_lower()
		if field not in ["liking", "familiarity", "threat"] or not words[i + 1].is_valid_float():
			push_error("/set: %s %s? Use liking, familiarity or threat with a number." % [words[i], words[i + 1]])
			return
		values[field] = words[i + 1].to_float()
	link.set_person(words[0], values)
