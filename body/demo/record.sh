#!/usr/bin/env bash
# Records one take of the demo video and encodes it to MP4.
# Start the brain first, in her Eileen body with the built-in voice:
#     cd ../brain && uv run server.py --model eileen
# Then:
#     demo/record.sh OUT_DIR [NAME]      -> OUT_DIR/NAME.avi (raw), NAME.markers.json, NAME.mp4
# A Godot window opens while it records (in real time, about 3 minutes); the
# video is captured from the engine at 1920x1080, not from the screen, so the
# window's size doesn't matter. Every take differs (her mind and lines are live):
# record a few and keep the best.
set -euo pipefail
project="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:?usage: demo/record.sh OUT_DIR [NAME]}"
name="${2:-take}"
mkdir -p "$out"
godot --path "$project" res://demo/demo.tscn --write-movie "$out/$name.avi" --fixed-fps 30 --resolution 1920x1080
python3 "$project/demo/encode.py" "$out/$name.avi" "$out/$name.mp4"
echo "done: $out/$name.mp4"
