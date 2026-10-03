class_name FaceShapeMap
extends Resource
## How a face that isn't VRoid's makes the VRoid face shapes everything else
## speaks (Fcl_*: the recipes in mimics.py, avatar/face.gd, blinks, lip sync).
## AvatarFace mixes in Fcl shapes as always and writes each one through the map
## onto the model's own blend shapes, at its single write point. A VRoid face
## needs no map: it has the Fcl shapes itself.
## A model's map is a script in its folder that extends this and fills `shapes`
## in _init (models/miku/miku_shapes.gd), so every choice keeps its comment;
## the model's Parts node holds it (ModelParts.shape_map).

## Every face shape the face system speaks, as VRoid names them. A map has all
## of them: a shape with no counterpart maps to {} and is dropped on purpose.
const FCL: PackedStringArray = [
	"Fcl_ALL_Neutral", "Fcl_ALL_Angry", "Fcl_ALL_Fun", "Fcl_ALL_Joy", "Fcl_ALL_Sorrow", "Fcl_ALL_Surprised",
	"Fcl_BRW_Angry", "Fcl_BRW_Fun", "Fcl_BRW_Joy", "Fcl_BRW_Sorrow", "Fcl_BRW_Surprised",
	"Fcl_EYE_Natural", "Fcl_EYE_Angry", "Fcl_EYE_Close", "Fcl_EYE_Close_R", "Fcl_EYE_Close_L", "Fcl_EYE_Fun",
	"Fcl_EYE_Joy", "Fcl_EYE_Joy_R", "Fcl_EYE_Joy_L", "Fcl_EYE_Sorrow", "Fcl_EYE_Surprised", "Fcl_EYE_Spread",
	"Fcl_EYE_Iris_Hide", "Fcl_EYE_Highlight_Hide",
	"Fcl_MTH_Close", "Fcl_MTH_Up", "Fcl_MTH_Down", "Fcl_MTH_Angry", "Fcl_MTH_Small", "Fcl_MTH_Large",
	"Fcl_MTH_Neutral", "Fcl_MTH_Fun", "Fcl_MTH_Joy", "Fcl_MTH_Sorrow", "Fcl_MTH_Surprised", "Fcl_MTH_SkinFung",
	"Fcl_MTH_SkinFung_R", "Fcl_MTH_SkinFung_L", "Fcl_MTH_A", "Fcl_MTH_I", "Fcl_MTH_U", "Fcl_MTH_E", "Fcl_MTH_O",
	"Fcl_HA_Hide", "Fcl_HA_Fung1", "Fcl_HA_Fung1_Low", "Fcl_HA_Fung1_Up", "Fcl_HA_Fung2", "Fcl_HA_Fung2_Low",
	"Fcl_HA_Fung2_Up", "Fcl_HA_Fung3", "Fcl_HA_Fung3_Up", "Fcl_HA_Fung3_Low", "Fcl_HA_Short", "Fcl_HA_Short_Up",
	"Fcl_HA_Short_Low",
]

## Fcl shape -> {this face's blend shape: weight}. {} drops the shape.
var shapes: Dictionary[String, Dictionary] = {}


## The map fits `mesh`: every Fcl shape is decided, nothing else is mapped, and
## every blend shape it writes is on the mesh. Pushes an error for each problem.
func check(mesh: MeshInstance3D) -> bool:
	var ok := true
	var source := (get_script() as Script).resource_path
	for fcl in FCL:
		if not shapes.has(fcl):
			push_error("FaceShapeMap %s: '%s' isn't mapped (map it to {} if the face has nothing like it)" % [source, fcl])
			ok = false
	for fcl: String in shapes:
		if fcl not in FCL:
			push_error("FaceShapeMap %s: '%s' isn't a VRoid face shape" % [source, fcl])
			ok = false
			continue
		for target: Variant in shapes[fcl]:
			if not target is String or mesh.find_blend_shape_by_name(target) < 0:
				push_error("FaceShapeMap %s: %s maps to '%s', which %s has no blend shape for" % [source, fcl, target,
					mesh.name])
				ok = false
			elif not (shapes[fcl][target] is float or shapes[fcl][target] is int):
				push_error("FaceShapeMap %s: %s -> %s needs a number for its weight" % [source, fcl, target])
				ok = false
	return ok
