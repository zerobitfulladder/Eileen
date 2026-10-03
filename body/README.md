# Eileen (Godot body)

The avatar's body. Her brain, voice and mind run in [`../brain`](../brain) (start
`uv run server.py` there first); this project connects to it, plays her
speech, and runs all per-frame motion. Python decides every face and gesture
(which, how strong, when); Godot only mixes and moves.

## Scenes

- `main.tscn`: the stage and everything that moves her, whichever body she's
  in. Camera operator (`stage/camera_rig.gd`, portrait 720×1080, 30° lens),
  frontal key light, a low rose "sun" behind her that is both her rim light
  and the glow in the sky, a purple procedural sky (`WorldEnvironment` → Sky →
  colors), and the debug UI (see below):

```
Main
├─ Model               her body: loads the model the brain picks and binds the parts below to it
│  └─ (the model scene, once loaded)
├─ Targets
│  └─ Chat             where her chat is; add Marker3Ds here for more look targets
├─ Avatar
│  ├─ Link             connection to the Python brain: runs its commands, reports events
│  ├─ Gaze             saccades, head follows eyes later and slower; eyes-only looks, glides
│  ├─ Gestures         nods, tilts, laughs, sighs, exhales... (additive)
│  ├─ Clips            plays body clips (dances, sitting) on the model's ClipPlayer, fades them in and out
│  ├─ Blink            irregular blinks; suppress, burst, slow, flutter, failed winks
│  ├─ Speech           plays clips, lip sync, fires timed commands on the audio clock
│  └─ Face             the only thing that writes blend shapes
├─ Camera3D            follows the loaded model's eyes
└─ DebugUI
```

- `models/<name>/<name>.tscn`: one body each (`lucy`, `eileen`, `miku`), an
  inherited scene of its VRM (`models/<name>/<name>.vrm`), so its spring bones
  (hair physics) and materials stay the model's own:

```
Lucy (VRM)
├─ GeneralSkeleton     (Armature/GeneralSkeleton in Miku)
│  └─ AvatarRig        writes her bones every frame, over a body clip's pose (hair physics runs after it);
│                      its inspector holds this model's standing pose and eye values
├─ ClipPlayer          AnimationPlayer with the body clips (animations/clips.res)
└─ Parts               ModelParts: which nodes are the rig, the face mesh and the clip player,
                       and the face's shape map if it isn't a VRoid face
```

Scripts are in `avatar/` (one job each) and `ui/`; the body clips and the
script that builds them are in `animations/`.

## Models

The brain picks her body: `uv run server.py --model lucy` (the default is
`lucy`; the list is `models.toml` in the Python project (`../brain`)). On every connect,
right after Godot's hello, it sends `{"cmd": "model", "name": "lucy"}` before
anything else, and `Model` (`avatar/model.gd`) loads
`res://models/lucy/lucy.tscn` and binds Gaze, Face, Clips, Speech, the camera
and the debug UI to it. If that model is already loaded (the brain restarted
with the same one), it stays; another name replaces it. An unknown name is
refused with an error listing the models there are. Until the first `model`
command the stage is empty and she waits: body commands are refused.

| Model | VRM | Face | Eyes (lookAt) |
|---|---|---|---|
| `lucy` | Lucyna by TsukiLuna (the "Lucyna blendshapes" export, the one with eyelashes), VRoid, VRM 0.x; her VRM's license: no commercial use, no redistribution | VRoid's `Fcl_*` shapes | offset (0, 0.06, 0), out 12° in 8° up 10° down 10° |
| `eileen` | VRoid, VRM 1.0 | VRoid's `Fcl_*` shapes | offset (0, 0.06, 0.05), out 12° in 8° up 10° down 10° |
| `miku` | 止丸式初音ミクNT (止丸), VRM 0.x, not VRoid | 16 MMD morphs, through `models/miku/miku_shapes.gd` | offset (0, 0.065, 0.065), 15° every way |

All three face the camera the same way (the importer turns VRM 0.x models,
which face backwards, around), their skeletons are `GeneralSkeleton` with the
humanoid bone names and a `motion_scale`, and the body clips play on all of
them.

**The face across models.** Everything speaks VRoid's face shapes (`Fcl_*`):
the recipes in `mimics.py`, `face.gd`, blinks and lip sync. A VRoid face has
them. Any other face needs a shape map (`avatar/shape_map.gd`): a script in
its model's folder that maps every `Fcl_*` shape to the model's own blend
shapes, with weights, or to nothing (`{}`: dropped). `face.gd` mixes in `Fcl_*`
shapes as always and writes them through the map at its one write point.
Miku's map lists what each of her morphs does and which shapes she lacks at
its top.

Model differences to know about:

- Heights differ (eyes at about 1.48 m for Eileen, 1.43 m for Miku, 1.35 m for
  Lucy). The camera frames from her eyes with the same shot sizes in meters,
  so a smaller model shows a little more of her body in each shot.
- Miku has no `UpperChest` bone: the clips' upper-chest motion and the
  upper-chest share of her breathing and head turns don't happen (Clips warns
  once when she loads). Her face has no raised brows, wide eyes, closed smile
  or pursed lips; a smile parts her lips a little instead. Her hair has only
  two spring bone groups, so it moves stiffer than the VRoid models'. Her
  license: personal, non-commercial use only, no redistribution (Piapro
  Character License plus the author's terms; `models/miku/` must not be shared).
- Lucy's and Miku's standing pose uses Eileen's values for now; tune each in
  its `AvatarRig`.

**Adding a model:**

1. Put the VRM in `models/<name>/<name>.vrm` (`<name>` in snake_case: it's what
   `--model` takes) and let the editor import it.
2. Right-click it > New Inherited Scene, name the root, and save it as
   `models/<name>/<name>.tscn`. Add (`models/lucy/lucy.tscn` is the example):
   - under `GeneralSkeleton`: a `SkeletonModifier3D` named `AvatarRig` with
     `avatar/rig.gd`. Set its `eye_offset` and eye ranges from the VRM's
     lookAt (VRM 1.0: `offsetFromHeadBone` and the range maps' `outputScale`;
     VRM 0.x: `firstPersonBoneOffset` and each range's `yRange`; the importer
     also puts the offset on `GeneralSkeleton/Head/LookOffset`);
   - at the root: an `AnimationPlayer` named `ClipPlayer` with
     `animations/clips.res` as its library;
   - at the root: a `Node` named `Parts` with `avatar/model_parts.gd`, and
     assign its rig, face mesh (the mesh with the face's blend shapes) and
     clip player.
3. If the face isn't VRoid's: copy `models/miku/miku_shapes.gd` to
   `models/<name>/<name>_shapes.gd` and map every shape to the model's own; on
   `Parts`, set `shape_map` to New FaceShapeMap and drag your script onto its
   Script property.
4. Add a `[<name>]` entry to `models.toml` in the Python project, then
   `uv run server.py --model <name>`. A model scene missing a part is refused
   with an error saying what's missing.

## The face

`avatar/face.gd` mixes four layers, bottom to top, then lip sync and blinks:

| Layer | What | Sent as |
|---|---|---|
| tonic | her resting face, from her mood and lingering feelings (smoothed) | `face_tonic` |
| felt | short displays of what she feels, eased in and out | `face_layer` layer `felt` |
| display | faces she puts on (the actor's tags), social smiles | `face_layer` layer `display` |
| leak | short pulses of a hidden feeling through one region | `face_layer` layer `leak` |

Each entry has its own envelope: `deliberate` (a face made on purpose: snaps
on, holds flat, drops quickly) or `felt` (eases in, drifts at its peak, eases
out). A face held while she talks lasts until the next face or `face_end`.
While her lips move, mouth shapes that would fight them are turned down
(`TALK_KEEP`). The recipes themselves live in `mimics.py` in the Python project.

Other body commands: `freeze` (a moment of stillness with held breath, ending
in a blink and an exhale), `hold_breath`, `blink_mode`, `body` and `body_ramp`
(a timed change of sway, blinks, breathing... that undoes itself), `posture`,
`look` (with an eyes-only mode), `head_pose`, `gesture`, `body_clip` and
`body_clip_end` (see below), camera moves. The full list, with every field, is
at the top of `avatar/link.gd`; malformed commands are refused with an error.

## Body clips

Mixamo animations (dances, a sitting idle) retargeted onto her skeleton.
`{"cmd": "body_clip", "name": "hip_hop_1"}` plays one, looping, until
`{"cmd": "body_clip_end"}`; both take an optional `fade` (seconds, default 0.4).
An unknown name is refused with an error. While a clip plays:

- `ClipPlayer` poses her bones first; `AvatarRig` (a skeleton modifier, so it
  runs after) fades that pose in over her rest pose while her standing pose,
  weight shift, sway, breathing and gestures fade out by the same eased
  weight. Ending the clip runs the same fade backwards, then stops the player.
  A clip started during another crossfades from it.
- Her face, lip sync, blinks and eyes keep going. Her head look stays at
  `clip_head_look` (0.35) on top of the dance: enough to turn a little toward
  chat or the camera, not enough to fight the dance's own head motion. Her
  eyes track in full and keep eye contact while the head moves.
- Hair physics runs after everything, as before.

The clips: `hip_hop_1` … `hip_hop_5`, `snake_hip_hop`, `arms_hip_hop`,
`running_man`, `belly_dance_1`, `belly_dance_2`, and `sitting_idle` (there's no
chair, so her hips drop to sitting height in the air).

How they're built (`animations/build_clips.gd`, an EditorScript): each FBX in
`animations/mixamo/` is imported with Godot's retargeting (the Mixamo bone map
`animations/mixamo/bone_map.tres` onto SkeletonProfileHumanoid, Overwrite Axis,
Fix Silhouette with the feet left out, position tracks normalized to hip
height). The script then keeps only bone transform tracks, takes the hips'
slow travel across the floor out (sway, steps and vertical motion stay), loops
each clip, and saves them all, plus a RESET pose, into `animations/clips.res`.
The import settings live in the script; it writes them into the `.import`
files, so don't change them in the import dialog.

**Adding a clip:** download it from Mixamo as FBX, *Without Skin*. Save it as
`animations/mixamo/<name>.fbx` in snake_case (the file name is the clip's name,
what the brain sends), let the editor import it, then open
`animations/build_clips.gd` in the script editor and run it (File > Run,
Ctrl+Shift+X). The output panel lists every clip and how much hip travel was
taken out, and warns if a clip's last frame doesn't meet its first (it would
jump at every loop). Rebuild the same way after removing a clip.

Known limits: the camera frames her from the eyes down to about mid-thigh even
in the `wide` shot, so footwork is out of frame, and it follows her eyes, so it
moves with a dance. Taking the hips' travel out makes the feet slide a little
where the dancer walked (most in `belly_dance_1`, which walks almost a meter).

## Debug UI

| Key / input | What it does |
|---|---|
| F1 | show or hide all debug UI (hide it before going live) |
| F2 | show or hide the inner-state panel |
| chat box: `hi eileen` | a chat message from you, as a regular viewer (your name: `eileen/chat/username`, see below) |
| chat box: `jo: hi` | a chat message from someone else |
| chat box: `/set jo liking 0.7 familiarity 0.8` | debug: how she feels about someone |
| chat box: `/say text` | she says exactly that |
| chat box: `/stop`, `/reset` | cut her off; start her mind and the chat fresh |
| top bar: Expression…, Camera…, Animation… | play the pick; ▶ plays it again |
| top bar: ■ | end the body clip, back to her own body |

Your chat name is the project setting `eileen/chat/username`. `project.godot`
holds a neutral default. To chat under your own name without committing it,
put it in `override.cfg` next to `project.godot`. Godot reads that file on
start, and git ignores it:

```ini
[eileen]

chat/username="YourName"
```

The inner-state panel (`ui/mind_panel.gd`, with `mind_bar.gd`, `mind_meter.gd`
and `mind_lane.gd`) shows her mind live from the brain's `{"type": "mind"}`
snapshots: emotions as two-tone bars (the bright fast part and the darker slow
tail) with a thin line for what her face actually shows, a faint ghost where a
value dropped from, a short glow when it rises, each feeling's source and
display rule; mood centered on zero with its baseline and where it's heading;
the wound (threat, composure with its thresholds, doubt, how much she's
hiding), drives, people, prospects, the exact text the actor is told, the
calculation for the last event, a 30 s event lane, thoughts, jokes, and the
face and body values the avatar is writing right now. Hover a bar for what it
means; click a section title to fold it.

The dropdown bar at the top plays any expression, camera move or body clip on
its own; the expression and camera lists come from the brain when it connects,
the body clips from `animations/clips.res`.

## Tuning

- Pose, breathing, sway, eye limits: inspector on `AvatarRig` in each model
  scene (`models/<name>/<name>.tscn`; the pose shows in the editor too).
- Faces: `mimics.py` in the Python project (recipes); mixing and caps in
  `avatar/face.gd`.
- Gestures: `avatar/gestures.gd`.
- Body clips: `clip_head_look` in the inspector on `AvatarRig`; the default fade
  is `FADE` in `avatar/clips.gd`; retargeting, how much hip travel is taken out
  (`IN_PLACE`) and the loop check are at the top of `animations/build_clips.gd`
  (run it again after changing them). To preview a clip in the editor, play
  it on a model scene's `ClipPlayer` with `AvatarRig`'s `pose_weight` at 0 (in the editor her
  standing pose is drawn over whatever the skeleton holds), and set it back to
  1 afterwards. Saving the scene applies RESET first, so a previewed pose is
  never saved.
- Camera: inspector on `Camera3D` (base shot/angle, handheld, follow speed,
  shake decay); shot sizes are `SHOTS` in `stage/camera_rig.gd`. When it moves
  is `camera.py` in the Python project. The camera's editor transform is
  ignored at runtime.
- Behavior and her inner life: `brain.py` and `mind/` in the Python project.

## Capture

Capture the game window. Under qtile, add `Match(wm_class="Eileen")` to your
float rules so it opens at 720×1080. Press F1 to hide the debug UI before
going live.

## Demo video

`demo/demo.tscn` is her real stage (`main.tscn`) with a presentation layer
on top, for a video that shows how she works:
- a pipeline strip (Chat › Appraiser › Mind › Actor › Voice › Body), lit by
  the brain's real `stage` events and her body's commands
- her mind panel (state) on the left
- on the right: what she feels against what her face shows, the mind's
  calculation trace, and the chat (viewers only)
- captions, and a glow around whatever a caption is about

Only the chat lines in `demo/steps.gd` are scripted. They're typed into the
chat box; her mind, lines, voice and body are live, so every take differs.

```sh
cd ../brain && uv run server.py --model eileen   # the brain, Eileen's body, built-in voice
demo/record.sh ~/Videos/eileen take1                      # in this project: one take -> take1.mp4
```

How a take is made:
- Godot's movie writer records the engine's own 1920×1080 frames and audio,
  not the screen.
- Each frame is held to the wall clock so the brain's timing stays real.
- `demo/encode.py` speeds up the marked silence 4× (from
  `<take>.markers.json`), normalizes loudness to −16 LUFS, and writes an
  H.264 MP4.
- `-- --stop-after=40` on the Godot command line ends a take early, to check
  the layout.

Files, one job each:
- `director.gd` runs the script and lays out the stage
- `pipeline.gd`, `feelings.gd`, `trace.gd`, `chat_feed.gd`, `caption.gd`,
  `outline.gd` and `card.gd` are the overlay parts
- `style.gd` holds the shared look
