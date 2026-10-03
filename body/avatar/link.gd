class_name AvatarLink
extends Node
## Connection to the Python brain (../brain/server.py).
## The brain decides what she does; this carries out its commands on the body
## parts and reports back what the body is doing. Commands arrive either on
## their own (do it now) or inside a speech clip, timed to its audio.
##
## Commands ({"cmd": ..., ...}; * = required; anything malformed is refused
## with an error, never guessed at):
##   model         name*   her body, res://models/<name>/<name>.tscn (AvatarModel).
##                 The brain sends it on every connect before anything else;
##                 every other command is refused until a model is loaded. The
##                 model already loaded stays, another one replaces it, an
##                 unknown name is refused (the error lists the models there are)
##   face_layer    layer* ("felt"/"display"/"leak"), slot*, shapes* {Fcl_ shape:
##                 weight}, intensity*, attack*, hold* (s, or -1 = until face_end),
##                 release*, curve* ("felt"/"deliberate"); max_hold (with hold -1),
##                 full_mouth, head [pitch, yaw, roll], chest, shoulders,
##                 head_attack, head_release   (a new entry in the same layer and
##                 slot crossfades out the old one; head/chest/shoulders ride on it)
##   face_end      layer*, slot*, fade    (let go of a face and its pose)
##   face_tonic    shapes*                (the resting face, absolute targets)
##   posture       pitch, yaw, roll, speed   (the resting head, a slow baseline)
##   look          target ("camera" or a child of `targets`) with offset [yaw,
##                 pitch], or yaw and pitch (degrees, relative to her body);
##                 mode "normal"/"eyes" (only the eyes move), glide (s)
##   nudge         yaw, pitch            shift the current gaze a little
##   blink         hold, open | blink_soon chance | wink side ("left"/"right")
##   blink_mode    mode*: "suppress" + seconds*, "burst" + count*, "slow",
##                 "flutter", "fail_wink" + variant* ("shut"/"squint") + side
##                 ("left"/"right", * for squint)
##   freeze        seconds*, double_blink, blink_hold, exhale, breath
##   hold_breath   seconds* | inhale strength | shift_weight
##   body          any of BODY_PARAMS (sets the base value)
##   body_ramp     param*, value*, seconds*, back_after*   (a multiplier that
##                 undoes itself)
##   head_pose     pitch*, yaw*, roll*, hold*, attack*, release*, slot, chest,
##                 shoulders   (a held attitude that isn't a face's)
##   gesture       name*, strength, duration
##   body_clip     name*, fade   (a body animation, looping: a file name from
##                 animations/mixamo/ like "hip_hop_1"; her own body fades out as
##                 it fades in over fade s, default 0.4; from another clip it
##                 crossfades)
##   body_clip_end fade          (back to her own body over fade s, default 0.4)
##   camera        shot (wide/medium/mcu/close/extreme), move (cut/move/snap),
##                 duration, yaw, yaw_offset, elevation, roll   (see CameraRig)
##   camera_shake  amount | camera_handheld amount

signal catalog_received(catalog: Dictionary)  ## what the debug dropdowns can test
signal mind_received(snapshot: Dictionary)  ## her mind, for the debug panel (ui/mind_panel.gd)
## Where a reply is in the brain: "appraiser", "mind" (with move, gist), "actor", "voice" (the demo's pipeline).
signal stage_received(stage: Dictionary)
signal executed(cmd: Dictionary)  ## a command was accepted and is being carried out (the demo's Body stage)

@export var server_url := "ws://127.0.0.1:8765"
@export var speech: Speech
@export var gaze: AvatarGaze
@export var face: AvatarFace
@export var blink: AvatarBlink
@export var gestures: AvatarGestures
@export var clips: AvatarClips
## Her body: loads the model the brain asks for.
@export var model: AvatarModel
## Things she can look at by name: every Node3D child, plus "camera".
@export var targets: Node3D

## The loaded model's rig (null until the brain sends `model`).
var rig: AvatarRig:
	get:
		return model.parts.rig if model.parts else null

var _socket := WebSocketPeer.new()
var _was_open := false
var _reconnect_in := 0.0
var _pending_clip: Dictionary = {}


func _ready() -> void:
	# Default inbound buffer is 64 KiB; one sentence of audio is bigger.
	_socket.inbound_buffer_size = 8 * 1024 * 1024
	_socket.connect_to_url(server_url)
	speech.command.connect(execute)
	speech.sentence_started.connect(_on_sentence_started)
	speech.finished.connect(func(): _send({"type": "event", "name": "finished"}))


## A chat message for her to reply to (the brain's LLM writes the answer).
func chat(text: String) -> void:
	_send({"type": "chat", "text": text})


## Make her say exactly this. Text may contain tags like [laugh] or [smile].
func say(text: String) -> void:
	_send({"type": "say", "text": text})


## Debug: act out one tag now ("skeptical", "nod", "laugh"...).
func perform(tag: String) -> void:
	_send({"type": "perform", "tag": tag})


## Debug: run one camera shot or tag move now ("close", "whispering", "base shot"...).
func camera_test(shot_name: String) -> void:
	_send({"type": "camera_test", "name": shot_name})


## Debug: set how she feels about someone in chat (liking, familiarity, threat).
func set_person(person: String, values: Dictionary) -> void:
	var msg := {"type": "set", "name": person}
	msg.merge(values)
	_send(msg)


## Forget the chat history in the brain (a fresh conversation).
func reset_chat() -> void:
	_send({"type": "reset"})


## Cut her off, here and in the brain.
func stop() -> void:
	_send({"type": "stop"})
	speech.stop()


## Body parameters: `body` sets their base values, `body_ramp` multiplies them for a while.
const BODY_PARAMS: PackedStringArray = ["head_share", "head_speed", "micro_saccade", "eye_range", "sway",
	"breaths_per_minute", "breath_depth", "shoulder_lift", "blinks_per_minute", "talking_blinks_per_minute",
	"lip_strength"]
## The fields each command may carry (besides type, cmd and t); the handlers check the required ones.
const FIELDS := {
	"model": ["name"],
	"face_layer": ["layer", "slot", "shapes", "intensity", "attack", "hold", "release", "curve", "max_hold",
		"full_mouth", "head", "chest", "shoulders", "head_attack", "head_release"],
	"face_end": ["layer", "slot", "fade"],
	"face_tonic": ["shapes"],
	"posture": ["pitch", "yaw", "roll", "speed"],
	"look": ["target", "offset", "yaw", "pitch", "mode", "glide"],
	"nudge": ["yaw", "pitch"],
	"blink": ["hold", "open"],
	"blink_soon": ["chance"],
	"wink": ["side"],
	"blink_mode": ["mode", "seconds", "count", "variant", "side"],
	"freeze": ["seconds", "double_blink", "blink_hold", "exhale", "breath"],
	"hold_breath": ["seconds"],
	"inhale": ["strength"],
	"shift_weight": [],
	"body": BODY_PARAMS,
	"body_ramp": ["param", "value", "seconds", "back_after"],
	"head_pose": ["pitch", "yaw", "roll", "hold", "attack", "release", "slot", "chest", "shoulders"],
	"gesture": ["name", "strength", "duration"],
	"body_clip": ["name", "fade"],
	"body_clip_end": ["fade"],
	"camera": ["shot", "move", "duration", "yaw", "yaw_offset", "elevation", "roll"],
	"camera_shake": ["amount"],
	"camera_handheld": ["amount"],
}


func execute(c: Dictionary) -> void:
	var cmd := String(c.get("cmd", ""))
	if not FIELDS.has(cmd):
		push_error("AvatarLink: unknown command %s" % c)
		return
	for key: String in c:
		if key not in ["type", "cmd", "t"] and key not in FIELDS[cmd]:
			push_error("AvatarLink: %s has no field '%s': %s" % [cmd, key, c])
			return
	if cmd != "model" and model.parts == null:
		push_error("AvatarLink: no model loaded yet (the brain sends 'model' first), refused: %s" % c)
		return
	executed.emit(c)
	match cmd:
		"model":
			if _has(c, ["name"]) and _is(c, "name", TYPE_STRING):
				model.load_model(c.name)
		"face_layer":
			_face_layer(c)
		"face_end":
			if _has(c, ["layer", "slot"]):
				var fade := float(c.get("fade", 0.2))
				face.end(String(c.layer), String(c.slot), fade)
				gestures.end_slot(_pose_slot(c), maxf(fade, 0.35))  # a head never snaps back
		"face_tonic":
			if _has(c, ["shapes"]) and _is(c, "shapes", TYPE_DICTIONARY):
				face.set_tonic(c.shapes)
		"posture":
			gestures.set_posture(Vector3(float(c.get("pitch", 0.0)), float(c.get("yaw", 0.0)), float(c.get("roll", 0.0))),
				float(c.get("speed", 0.6)))
		"look":
			_look(c)
		"nudge":
			gaze.nudge(Vector2(float(c.get("yaw", 0.0)), float(c.get("pitch", 0.0))))
		"blink":
			blink.blink(float(c.get("hold", AvatarBlink.HOLD)), float(c.get("open", AvatarBlink.OPEN)))
		"blink_soon":
			blink.blink_soon(float(c.get("chance", 1.0)))
		"wink":
			if not c.has("side") or _side(c, false) != "":
				blink.wink(c.get("side", "left") == "left")
		"blink_mode":
			_blink_mode(c)
		"freeze":
			if _has(c, ["seconds"]):
				var seconds := float(c.seconds)
				rig.freeze(seconds, float(c.get("breath", seconds)), float(c.get("exhale", 0.5)))
				gaze.freeze(seconds)
				blink.freeze(seconds, bool(c.get("double_blink", false)), float(c.get("blink_hold", AvatarBlink.HOLD)))
				gestures.calm(0.15)
		"hold_breath":
			if _has(c, ["seconds"]):
				rig.hold_breath(float(c.seconds))
		"inhale":
			rig.inhale()
			gestures.play("inhale", float(c.get("strength", 1.0)))
		"shift_weight":
			rig.shift_weight()
		"body":
			for key: String in c:
				if key in BODY_PARAMS:
					_body_part(key).set(key, float(c[key]))
		"body_ramp":
			if _has(c, ["param", "value", "seconds", "back_after"]):
				if String(c.param) not in BODY_PARAMS:
					push_error("AvatarLink: body_ramp of unknown parameter: %s" % c)
				else:
					_body_part(c.param).ramps.add(c.param, float(c.value), float(c.seconds), float(c.back_after))
		"head_pose":
			if _has(c, ["pitch", "yaw", "roll", "hold", "attack", "release"]):
				if float(c.hold) < 0.0:
					push_error("AvatarLink: head_pose needs a hold >= 0 (open poses ride on face_layer): %s" % c)
				else:
					gestures.hold_pose(Vector3(float(c.pitch), float(c.yaw), float(c.roll)), float(c.hold),
						float(c.attack), float(c.release), String(c.get("slot", "")), float(c.get("chest", 0.0)),
						float(c.get("shoulders", 0.0)))
		"gesture":
			if _has(c, ["name"]):
				gestures.play(String(c.name), float(c.get("strength", 1.0)), float(c.get("duration", -1.0)))
		"body_clip":
			if _has(c, ["name"]):
				clips.play(String(c.name), float(c.get("fade", AvatarClips.FADE)))
		"body_clip_end":
			clips.end(float(c.get("fade", AvatarClips.FADE)))
		"camera":
			var cam := _camera_rig()
			if cam:
				cam.frame(c.get("shot", cam.base_shot), c.get("move", "move"), float(c.get("duration", 1.5)),
					float(c.get("yaw", NAN)), float(c.get("elevation", NAN)), float(c.get("roll", 0.0)),
					float(c.get("yaw_offset", 0.0)))
		"camera_shake":
			var cam := _camera_rig()
			if cam:
				cam.shake(float(c.get("amount", 0.3)))
		"camera_handheld":
			var cam := _camera_rig()
			if cam:
				cam.set_handheld(float(c.get("amount", 0.15)))


## One face entry, and the head, chest and shoulders that ride on it (slot "face:<layer>/<slot>").
func _face_layer(c: Dictionary) -> void:
	if not _has(c, ["layer", "slot", "shapes", "intensity", "attack", "hold", "release", "curve"]) \
			or not _is(c, "shapes", TYPE_DICTIONARY):
		return
	var hold := float(c.hold)
	if c.has("max_hold") and hold != -1.0:
		push_error("AvatarLink: max_hold only goes with hold -1: %s" % c)
		return
	var head := Vector3.ZERO
	if c.has("head"):
		if not (c.head is Array and c.head.size() == 3):
			push_error("AvatarLink: head must be [pitch, yaw, roll]: %s" % c)
			return
		head = Vector3(float(c.head[0]), float(c.head[1]), float(c.head[2]))
	var attack := float(c.attack)
	var release := float(c.release)
	var max_hold := float(c.get("max_hold", 0.0))
	if not face.play(String(c.layer), String(c.slot), c.shapes, float(c.intensity), attack, hold, release,
			String(c.curve), bool(c.get("full_mouth", false)), max_hold):
		return
	if c.has("head") or c.has("chest") or c.has("shoulders"):
		gestures.hold_pose(head, hold, float(c.get("head_attack", maxf(attack, 0.15))),
			float(c.get("head_release", maxf(release, 0.35))), _pose_slot(c), float(c.get("chest", 0.0)),
			float(c.get("shoulders", 0.0)), max_hold)
	else:
		gestures.end_slot(_pose_slot(c), maxf(attack, 0.15))  # the face before it in the slot had a head


func _look(c: Dictionary) -> void:
	var mode := String(c.get("mode", "normal"))
	if mode not in AvatarGaze.MODES:
		push_error("AvatarLink: unknown look mode: %s" % c)
		return
	var glide := float(c.get("glide", 0.0))
	if c.has("target"):
		var node := _target(String(c.target))
		if node:
			gaze.look_at_node(node, _vec2(c.get("offset", [0, 0])), mode, glide)
	elif c.has("yaw") and c.has("pitch"):
		gaze.look_toward(float(c.yaw), float(c.pitch), mode, glide)
	else:
		push_error("AvatarLink: look needs a target, or yaw and pitch: %s" % c)


func _blink_mode(c: Dictionary) -> void:
	if not _has(c, ["mode"]):
		return
	match String(c.mode):
		"suppress":
			if _has(c, ["seconds"]):
				blink.suppress(float(c.seconds))
		"burst":
			if _has(c, ["count"]):
				blink.burst(int(c.count))
		"slow":
			blink.slow_blink()
		"flutter":
			blink.flutter()
		"fail_wink":
			if not _has(c, ["variant"]):
				return
			if c.variant == "squint":
				var side := _side(c, true)
				if side != "":
					blink.fail_wink("squint", side == "left")
			else:
				blink.fail_wink(String(c.variant), _side(c, false) != "right")
		_:
			push_error("AvatarLink: unknown blink mode: %s" % c)


## The required fields are there (pushes an error naming the missing one).
func _has(c: Dictionary, keys: Array) -> bool:
	for key: String in keys:
		if not c.has(key):
			push_error("AvatarLink: %s needs '%s': %s" % [c.get("cmd"), key, c])
			return false
	return true


func _is(c: Dictionary, key: String, type: int) -> bool:
	if typeof(c[key]) != type:
		push_error("AvatarLink: %s has a malformed '%s': %s" % [c.get("cmd"), key, c])
		return false
	return true


## "left" or "right"; "" (with an error) when it's missing and required, or malformed.
func _side(c: Dictionary, required: bool) -> String:
	if not c.has("side"):
		if required:
			push_error("AvatarLink: %s needs 'side': %s" % [c.get("cmd"), c])
		return ""
	if c.side not in ["left", "right"]:
		push_error("AvatarLink: side must be \"left\" or \"right\": %s" % c)
		return ""
	return c.side


func _pose_slot(c: Dictionary) -> String:
	return "face:%s/%s" % [c.layer, c.slot]


func _process(delta: float) -> void:
	_socket.poll()
	var state := _socket.get_ready_state()
	if state == WebSocketPeer.STATE_OPEN:
		if not _was_open:
			_was_open = true
			print("AvatarLink: connected to ", server_url)
			var names: Array = ["camera"]
			if targets:
				for child in targets.get_children():
					names.append(String(child.name).to_snake_case())
			_send({"type": "hello", "targets": names})
		while _socket.get_available_packet_count() > 0:
			var packet := _socket.get_packet()
			if _socket.was_string_packet():
				_on_message(JSON.parse_string(packet.get_string_from_utf8()))
			elif not _pending_clip.is_empty():
				speech.queue_clip(_pending_clip, packet)
				_pending_clip = {}
	elif state == WebSocketPeer.STATE_CLOSED:
		if _was_open:
			_was_open = false
			print("AvatarLink: disconnected, retrying...")
		_reconnect_in -= delta
		if _reconnect_in <= 0.0:
			_reconnect_in = 2.0
			_socket.connect_to_url(server_url)


func _on_message(msg: Variant) -> void:
	if not msg is Dictionary:
		return
	match msg.get("type"):
		"cmd":
			execute(msg)
		"cmds":
			for c: Dictionary in msg.get("list", []):
				execute(c)
		"clip":
			_pending_clip = msg  # the PCM follows as the next binary packet
		"end":
			speech.end_reply()
		"stop":
			speech.stop()
		"catalog":
			catalog_received.emit(msg)
		"mind":
			mind_received.emit(msg)
		"stage":
			stage_received.emit(msg)


func _on_sentence_started(info: Dictionary) -> void:
	_send({"type": "event", "name": "sentence_started", "utterance": info.get("utterance"),
		"index": info.get("index"), "duration": info.get("duration")})


func _send(msg: Dictionary) -> void:
	if _socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		_socket.send_text(JSON.stringify(msg))
	else:
		push_warning("AvatarLink: not connected to %s" % server_url)


func _target(target_name: String) -> Node3D:
	if target_name == "camera":
		return get_viewport().get_camera_3d()
	if targets:
		for child in targets.get_children():
			if String(child.name).to_snake_case() == target_name:
				return child
	push_error("AvatarLink: no look target '%s'" % target_name)
	return null


## The active camera, if it's a CameraRig (the stage owns the camera, not her).
func _camera_rig() -> CameraRig:
	return get_viewport().get_camera_3d() as CameraRig


## The part that owns a body parameter (its base value and its ramps).
func _body_part(param: String) -> Node:
	for part: Node in [gaze, rig, blink, speech]:
		if param in part:
			return part
	push_error("AvatarLink: no part owns body parameter '%s'" % param)
	return null


func _vec2(v: Variant) -> Vector2:
	if v is Array and v.size() == 2:
		return Vector2(float(v[0]), float(v[1]))
	push_error("AvatarLink: expected [yaw, pitch], got %s" % [v])
	return Vector2.ZERO
