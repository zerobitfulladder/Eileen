class_name Speech
extends Node
## Plays the sentences the brain sends, drives lip sync, and fires each
## sentence's timed commands (reactions to [laugh], emphasis nods, ...) when
## the audio reaches them, so they line up with the sound.
## While audio plays she counts as talking: faster blinks, and she breathes like
## a speaker: an inhale in the pause before her first word and between
## sentences, long exhales while talking. (The face keeps the mouth free for the
## lips on its own: it watches the visemes.)

signal sentence_started(info: Dictionary)  ## clip header without the viseme frames, plus "duration"
signal finished  ## everything the brain sent for this reply has played
signal command(cmd: Dictionary)  ## a timed command whose moment has come

const VISEMES := 5
const Ramps := preload("res://avatar/ramps.gd")

@export var face: AvatarFace
@export var blink: AvatarBlink
@export_range(0.0, 2.0, 0.05) var lip_strength := 1.0
## Pause before the first sentence of a reply, long enough for an inhale.
@export var lead_in := 0.25
## How quickly the mouth relaxes after speech.
@export var release_speed := 15.0
## Temporary multipliers on lip_strength (body_ramp).
var ramps := Ramps.new()
## The loaded model's rig, which breathes as she talks (set by AvatarModel; null until a model loads).
var rig: AvatarRig:
	set(value):
		rig = value
		if rig:
			rig.speaking = _speaking

var _player: AudioStreamPlayer
var _clips: Array[Dictionary] = []
var _current: Dictionary = {}
var _command_index := 0
var _latency := 0.0
var _lead_in_left := 0.0
var _reply_open := false  # the brain may still send sentences for this reply
var _speaking := false
var _breathed_for_next := false
var _weights := PackedFloat32Array([0, 0, 0, 0, 0])


func _ready() -> void:
	_player = AudioStreamPlayer.new()
	add_child(_player)


func queue_clip(header: Dictionary, pcm: PackedByteArray) -> void:
	var wav := AudioStreamWAV.new()
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.mix_rate = int(header.sample_rate)
	wav.stereo = false
	wav.data = pcm
	var commands: Array = header.get("commands", [])
	commands.sort_custom(func(a, b): return float(a.t) < float(b.t))
	var info := header.duplicate()
	info.erase("visemes")
	info.erase("commands")
	info.duration = pcm.size() / 2.0 / float(header.sample_rate)
	_clips.append({"stream": wav, "visemes": header.visemes, "fps": float(header.fps),
		"commands": commands, "info": info})
	_reply_open = true
	if not _speaking:
		_speaking = true
		_lead_in_left = lead_in
		_set_talking(true)
		if rig:
			rig.inhale()  # in the pause before the first word


## The brain has sent the last sentence of this reply.
func end_reply() -> void:
	_reply_open = false
	if not _speaking and _clips.is_empty():
		finished.emit()  # a reply with nothing to say (only stage directions, or the LLM failed)


func stop() -> void:
	_clips.clear()
	_player.stop()
	_current = {}
	_reply_open = false


func is_speaking() -> bool:
	return _speaking


func _process(delta: float) -> void:
	ramps.advance(delta)
	if not _player.playing and not _clips.is_empty():
		if _lead_in_left > 0.0:
			_lead_in_left -= delta
		else:
			_start_clip(_clips.pop_front())

	var commands: Array = _current.get("commands", [])
	if _player.playing:
		var t := _player.get_playback_position() + AudioServer.get_time_since_last_mix() - _latency
		var target := _sample(t)
		while _command_index < commands.size() and float(commands[_command_index].t) <= t:
			command.emit(commands[_command_index])
			_command_index += 1
		# Another sentence is coming: catch a breath as this one ends.
		if rig and not _breathed_for_next and not _clips.is_empty() \
				and _player.stream.get_length() - t < 0.3:
			_breathed_for_next = true
			rig.inhale()
		var lips := lip_strength * ramps.factor("lip_strength")
		for i in VISEMES:
			_weights[i] = target[i] * lips
	else:
		# Fire anything the clip ended before reaching (e.g. a command at its very end).
		while _command_index < commands.size():
			command.emit(commands[_command_index])
			_command_index += 1
		var k := 1.0 - exp(-release_speed * delta)
		for i in VISEMES:
			_weights[i] = lerpf(_weights[i], 0.0, k)
		if _speaking and _clips.is_empty() and not _reply_open:
			_speaking = false
			_set_talking(false)
			finished.emit()
	if face:
		face.set_visemes(_weights)


func _start_clip(clip: Dictionary) -> void:
	_current = clip
	_command_index = 0
	_breathed_for_next = false
	_player.stream = clip.stream
	_player.play()
	_latency = AudioServer.get_output_latency()
	sentence_started.emit(clip.info)


func _set_talking(on: bool) -> void:
	if blink:
		blink.talking = on
	if rig:
		rig.speaking = on


## Viseme weights at time t (seconds into the clip), linearly interpolated.
func _sample(t: float) -> PackedFloat32Array:
	var out := PackedFloat32Array([0, 0, 0, 0, 0])
	var frames: Array = _current.get("visemes", [])
	if frames.is_empty() or t < 0.0:
		return out
	var f := t * float(_current.fps)
	var i := mini(int(f), frames.size() - 1)
	var j := mini(i + 1, frames.size() - 1)
	var a: Array = frames[i]
	var b: Array = frames[j]
	var frac := clampf(f - i, 0.0, 1.0)
	for c in VISEMES:
		out[c] = lerpf(a[c], b[c], frac)
	return out
