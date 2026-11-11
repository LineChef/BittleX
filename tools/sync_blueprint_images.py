#!/usr/bin/env python3
"""Copy the build renders and wiring figures from the Bittle X case project into blueprints/images/ and record where each came from.

    python tools/sync_blueprint_images.py            # copy, recompress to at most 300 KB, write blueprints/images/SOURCES.json
    G2_CASE_PROJECT=/path/to/bittlex python tools/sync_blueprint_images.py

The case project (LineChef/G2bittlex, from Jeremy Collins's Bittle X Platform and Pi add-on) is a separate repository. Its designs and documents are CC BY 4.0, so every figure caption credits the
author; its Petoi and PiSugar models keep their own terms. SOURCES.json lists each file's source path, the source commit and the licence. Needs Pillow (the `pi_pipeline/.venv` has it).
"""
import json
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "blueprints", "images")
SRC = os.path.expanduser(os.environ.get("G2_CASE_PROJECT", "~/Desktop/OneFolder/projects/beatlebug/bittlex"))
MAX_BYTES = 300 * 1024
LICENSE = "CC BY 4.0 (Jeremy Collins). The Petoi and PiSugar models shown keep their own terms."

# new file name: source path in the case project
FILES = {
    "addon-on-robot.png": "bittle_pi_addon/doc/02_addon.png",
    "addon-rear.png": "bittle_pi_addon/doc/03_rear.png",
    "addon-top-openings.png": "bittle_pi_addon/doc/04_top.png",
    "addon-front-notch.png": "bittle_pi_addon/doc/05_front_notch.png",
    "addon-open-right.png": "bittle_pi_addon/doc/06_open.png",
    "addon-open-left.png": "bittle_pi_addon/doc/07_open_left.png",
    "addon-section.png": "bittle_pi_addon/doc/08_section.png",
    "addon-wires-3d.png": "bittle_pi_addon/doc/09_wires.png",
    "addon-exploded.png": "bittle_pi_addon/doc/10_exploded.png",
    "addon-wires-top.png": "bittle_pi_addon/doc/11_wires_top.png",
    "addon-wires-closeup.png": "bittle_pi_addon/doc/12_wires_left.png",
    "wire-routing-top.png": "bittle_pi_addon/doc/13_routing_top.png",
    "wire-routing-side.png": "bittle_pi_addon/doc/14_routing_side.png",
    "wiring-module-biboard-serial.png": "bittle_pi_addon/doc/15_wiring_0.png",
    "wiring-module-amp.png": "bittle_pi_addon/doc/15_wiring_1.png",
    "wiring-module-mic.png": "bittle_pi_addon/doc/15_wiring_2.png",
    "wiring-module-speaker.png": "bittle_pi_addon/doc/15_wiring_3.png",
    "addon-on-robot-model.png": "bittle_pi_addon/doc/cover.png",
    "platform-keyhole-and-peg.png": "bittle_platform/doc/keyhole.png",
    "platform-touch-areas.png": "bittle_platform/doc/petoi_touch_areas.png",
    "platform-plan-view.png": "bittle_platform/doc/plan.png",
    "platform-starter-plate.png": "bittle_platform/doc/r2_starter.png",
}


def shrink(src, dst):
    im = Image.open(src)
    im.save(dst, optimize=True)
    if os.path.getsize(dst) <= MAX_BYTES:
        return
    rgb = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    q = rgb.quantize(colors=256, method=Image.Quantize.FASTOCTREE) if rgb.mode == "RGB" else rgb.convert("RGB").quantize(colors=256)
    q.save(dst, optimize=True)
    while os.path.getsize(dst) > MAX_BYTES:
        w, h = q.size
        q = q.resize((int(w * 0.9), int(h * 0.9)), Image.LANCZOS)
        q.save(dst, optimize=True)


def main():
    commit = subprocess.run(["git", "-C", SRC, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for name, rel in FILES.items():
        src = os.path.join(SRC, rel)
        if not os.path.exists(src):
            print("missing:", src)
            return 1
        dst = os.path.join(OUT, name)
        shrink(src, dst)
        w, h = Image.open(dst).size
        rows.append({"file": name, "width": w, "height": h, "bytes": os.path.getsize(dst), "source_project": "LineChef/G2bittlex (Bittle X Platform and Pi add-on, Jeremy Collins)", "source_path": rel,
                     "source_commit": commit, "license": LICENSE})
    json.dump(rows, open(os.path.join(OUT, "SOURCES.json"), "w"), indent=1)
    print(len(rows), "images,", sum(r["bytes"] for r in rows) // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
