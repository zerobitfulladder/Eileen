#!/usr/bin/env python3
"""Turn a recorded demo take (Godot's MJPEG .avi) into a web-ready MP4.

The director's <take>.markers.json says where the silence is: that stretch is
sped up (video and audio together), the rest plays as recorded. The audio is
normalized to -16 LUFS (web loudness).

    demo/encode.py takes/take1.avi takes/take1.mp4
"""

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    markers = json.loads(src.with_suffix(".markers.json").read_text())
    fast = [m for m in markers if "fast_from" in m]
    if len(fast) > 1:
        sys.exit("encode.py: more than one sped-up stretch in the markers")
    if fast:
        a, b, speed = fast[0]["fast_from"], fast[0]["fast_to"], fast[0]["speed"]
        tempo = f"atempo={speed}"  # ffmpeg 4.3+: up to 100x in one filter
        graph = (
            f"[0:v]trim=0:{a},setpts=PTS-STARTPTS[v0];"
            f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed}[v1];"
            f"[0:v]trim=start={b},setpts=PTS-STARTPTS[v2];"
            f"[0:a]atrim=0:{a},asetpts=PTS-STARTPTS[a0];"
            f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,{tempo}[a1];"
            f"[0:a]atrim=start={b},asetpts=PTS-STARTPTS[a2];"
            "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][araw];"
            "[araw]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        )
    else:
        graph = "[0:v]null[v];[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    subprocess.run([
        "ffmpeg", "-v", "error", "-stats", "-y", "-i", str(src), "-filter_complex", graph,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(dst),
    ], check=True)


if __name__ == "__main__":
    main()
