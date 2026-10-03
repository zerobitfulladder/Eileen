class_name ModelParts
extends Node
## What the avatar needs from one model scene (models/<name>/<name>.tscn): her
## rig, her face mesh, her clip player and, for a face that isn't VRoid's, its
## shape map. AvatarModel binds the parts that move her to these when it loads
## the model. Everything else about the model (its skeleton, spring bones,
## materials) stays inside the model scene.

## The AvatarRig under the model's GeneralSkeleton (its inspector holds this
## model's standing pose and eye values).
@export var rig: AvatarRig
## The mesh with the face's blend shapes.
@export var face_mesh: MeshInstance3D
## The AnimationPlayer with the body clips (animations/clips.res), its root the model's root.
@export var clip_player: AnimationPlayer
## How this face makes the VRoid Fcl shapes; empty for a VRoid face, which has them.
@export var shape_map: FaceShapeMap


## The model's skeleton (the rig is one of its modifiers).
func skeleton() -> Skeleton3D:
	return rig.get_parent() as Skeleton3D


## Every part is there and in place. Pushes an error for each problem (`scene` names the model).
func check(scene: String) -> bool:
	var ok := true
	for part: String in ["rig", "face_mesh", "clip_player"]:
		if get(part) == null:
			push_error("ModelParts %s: assign %s" % [scene, part])
			ok = false
	if rig and skeleton() == null:
		push_error("ModelParts %s: the AvatarRig must be a child of the model's skeleton" % scene)
		ok = false
	if rig and rig.eye_offset == Vector3.ZERO:
		push_error("ModelParts %s: set the AvatarRig's eye_offset (the VRM's lookAt offset from the head bone)" % scene)
		ok = false
	return ok
