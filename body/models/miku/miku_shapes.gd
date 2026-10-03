extends FaceShapeMap
## Miku's face in the VRoid Fcl shapes. She isn't a VRoid model: her face is 16
## MMD morphs on her one mesh (Body):
##   あ い う え お   the mouth vowels
##   まばたき         both eyes shut (the same as ウィンク２ + ｳｨﾝｸ２右)
##   ウィンク２       her left eye shut (her VRM's Blink_L)
##   ｳｨﾝｸ２右         her right eye shut (Blink_R)
##   笑い             closed smiling eyes (upper lids down in an arc, lower lids up)
##   はぅ             >< eyes, squeezed shut
##   怒り             angry brows: the inner ends drop most
##   困る             troubled brows: the inner ends rise, the outer ends drop
##   下               both brows straight down (3 cm at full weight)
##   ワ               a wide-open happy mouth
##   ∧                a ∧-shaped frown (the corners drop, the middle rises)
##   涙               tears
## Where her VRM has an expression, the weights follow it (Fun = 笑い + 下 0.3,
## Sorrow = ∧ 0.5 + 困る 0.7 + 涙).
## Dropped (no counterpart, mapped to {} below): raised brows (BRW_Joy,
## BRW_Surprised), wide-open eyes (EYE_Surprised, EYE_Spread), EYE_Natural, the
## iris and highlight hiders (EYE_Iris_Hide, EYE_Highlight_Hide), the closed,
## pursed, wide and neutral mouths (MTH_Close, MTH_Up, MTH_Down, MTH_Small,
## MTH_Large, MTH_Neutral), fangs and teeth (MTH_SkinFung*, HA_*) and
## ALL_Neutral / ALL_Surprised (her VRM has none). Her tears and >< eyes only
## come with ALL_Sorrow and ALL_Joy, which the brain doesn't send.


func _init() -> void:
	shapes = {
		# Her VRM's own presets (the brain doesn't use the ALL_ shapes).
		"Fcl_ALL_Neutral": {},
		"Fcl_ALL_Angry": {"∧": 1.0, "怒り": 1.0},
		"Fcl_ALL_Fun": {"笑い": 1.0, "下": 0.3},
		"Fcl_ALL_Joy": {"ワ": 1.0, "はぅ": 1.0},
		"Fcl_ALL_Sorrow": {"∧": 0.5, "困る": 0.7, "涙": 1.0},
		"Fcl_ALL_Surprised": {},

		# Brows. 下 at full weight drops them onto her lids; her VRM's Fun uses 0.3.
		"Fcl_BRW_Angry": {"怒り": 1.0},
		"Fcl_BRW_Fun": {"下": 0.3},
		"Fcl_BRW_Joy": {},
		"Fcl_BRW_Sorrow": {"困る": 1.0},
		"Fcl_BRW_Surprised": {},

		# Eyes. Blinks write Close_L / Close_R. She has no glaring or drooping lids,
		# so EYE_Angry and EYE_Sorrow lower them a little (face.gd fades both out
		# during a blink, as it does on a VRoid face).
		"Fcl_EYE_Natural": {},
		"Fcl_EYE_Angry": {"まばたき": 0.3},
		"Fcl_EYE_Close": {"まばたき": 1.0},
		"Fcl_EYE_Close_R": {"ｳｨﾝｸ２右": 1.0},
		"Fcl_EYE_Close_L": {"ウィンク２": 1.0},
		"Fcl_EYE_Fun": {"笑い": 0.4},
		"Fcl_EYE_Joy": {"笑い": 1.0},
		"Fcl_EYE_Joy_R": {"ｳｨﾝｸ２右": 1.0},  # no one-sided smiling eye: the eye shuts
		"Fcl_EYE_Joy_L": {"ウィンク２": 1.0},
		"Fcl_EYE_Sorrow": {"まばたき": 0.25},
		"Fcl_EYE_Surprised": {},
		"Fcl_EYE_Spread": {},
		"Fcl_EYE_Iris_Hide": {},
		"Fcl_EYE_Highlight_Hide": {},

		# Mouth. Her resting mouth is closed and soft; a smile parts her lips a
		# little (ワ 0.3), an open smile or a laugh opens them (ワ).
		"Fcl_MTH_Close": {},
		"Fcl_MTH_Up": {},
		"Fcl_MTH_Down": {},
		"Fcl_MTH_Angry": {"∧": 1.0},
		"Fcl_MTH_Small": {},
		"Fcl_MTH_Large": {},
		"Fcl_MTH_Neutral": {},
		"Fcl_MTH_Fun": {"ワ": 0.3},
		"Fcl_MTH_Joy": {"ワ": 1.0},
		"Fcl_MTH_Sorrow": {"∧": 0.5},
		"Fcl_MTH_Surprised": {"お": 1.0},
		"Fcl_MTH_SkinFung": {},
		"Fcl_MTH_SkinFung_R": {},
		"Fcl_MTH_SkinFung_L": {},

		# The vowels (lip sync), as her VRM's A I U E O.
		"Fcl_MTH_A": {"あ": 1.0},
		"Fcl_MTH_I": {"い": 1.0},
		"Fcl_MTH_U": {"う": 1.0},
		"Fcl_MTH_E": {"え": 1.0},
		"Fcl_MTH_O": {"お": 1.0},

		# Teeth and fangs.
		"Fcl_HA_Hide": {},
		"Fcl_HA_Fung1": {},
		"Fcl_HA_Fung1_Low": {},
		"Fcl_HA_Fung1_Up": {},
		"Fcl_HA_Fung2": {},
		"Fcl_HA_Fung2_Low": {},
		"Fcl_HA_Fung2_Up": {},
		"Fcl_HA_Fung3": {},
		"Fcl_HA_Fung3_Up": {},
		"Fcl_HA_Fung3_Low": {},
		"Fcl_HA_Short": {},
		"Fcl_HA_Short_Up": {},
		"Fcl_HA_Short_Low": {},
	}
