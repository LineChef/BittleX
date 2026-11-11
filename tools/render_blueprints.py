#!/usr/bin/env python3
"""Render our own printed designs (wide shoulders, clip-on paws) to PNG for the build record, with OpenSCAD. Local tool: it needs `openscad` and the STL files, which live in the case project
(G2_CASE_PROJECT, default ~/Desktop/OneFolder/projects/beatlebug/bittlex), not in this repository. Only the PNGs are committed (blueprints/images/, at most 300 KB each).

    python tools/render_blueprints.py              # render every view in VIEWS
    python tools/render_blueprints.py paw-iso      # render one by output name (without .png)

Cameras are OpenSCAD's `--camera=tx,ty,tz,rx,ry,rz,dist` with `--autocenter --viewall`, orthographic.
"""
import os
import subprocess
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "blueprints", "images")
SRC = os.path.expanduser(os.environ.get("G2_CASE_PROJECT", "~/Desktop/OneFolder/projects/beatlebug/bittlex"))
MAX_BYTES = 300 * 1024
ISO, TOP, FRONT, SIDE = "55,0,35,0", "0,0,0,0", "90,0,0,0", "90,0,90,0"

# output name: (STL path inside the case project, camera rotation "rx,ry,rz,0")
VIEWS = {
    "wide-shoulders-iso": ("prototypes/wide_shoulder_ends/wide_shoulder_ends.stl", ISO),
    "wide-shoulders-top": ("prototypes/wide_shoulder_ends/wide_shoulder_ends.stl", TOP),
    "paw-iso": ("prototypes/CLpaw/CLpaw.stl", ISO),
    "paw-side": ("prototypes/CLpaw/CLpaw.stl", SIDE),
    "paw-foot-in-frame": ("prototypes/CLpaw/foot_in_paw_frame.stl", ISO),
}


def tidy(im):
    """Crop to the part with a margin, make the background white and scale to at most 1200 px wide."""
    bg = im.getpixel((0, 0))
    diff = Image.new("L", im.size, 0)
    px, dp = im.load(), diff.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = px[x, y]
            d = abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2])
            dp[x, y] = 255 if d > 24 else 0
    box = diff.getbbox()
    if box:
        m = 24
        box = (max(0, box[0] - m), max(0, box[1] - m), min(im.width, box[2] + m), min(im.height, box[3] + m))
        im, diff = im.crop(box), diff.crop(box)
    white = Image.new("RGB", im.size, "white")
    im = Image.composite(im, white, diff.point(lambda v: 255 if v else 0))
    if im.width > 1200:
        im = im.resize((1200, int(im.height * 1200 / im.width)), Image.LANCZOS)
    return im


def render(name, stl, cam):
    src = os.path.join(SRC, stl)
    if not os.path.exists(src):
        print("missing", src)
        return False
    with tempfile.TemporaryDirectory() as d:
        scad = os.path.join(d, "v.scad")
        open(scad, "w").write(f'import("{src}");\n')
        raw = os.path.join(d, "v.png")
        rx, ry, rz, _ = cam.split(",")
        subprocess.run(["openscad", "-o", raw, "--imgsize=2400,1800", "--projection=o", f"--camera=0,0,0,{rx},{ry},{rz},0", "--autocenter", "--viewall", "--colorscheme=Metallic", scad],
                       check=True, capture_output=True)
        im = tidy(Image.open(raw).convert("RGB"))
        dst = os.path.join(OUT, name + ".png")
        im.save(dst, optimize=True)
        if os.path.getsize(dst) > MAX_BYTES:
            im.quantize(colors=128).save(dst, optimize=True)
    print(name, os.path.getsize(dst) // 1024, "KB")
    return True


def main(argv):
    os.makedirs(OUT, exist_ok=True)
    todo = {k: v for k, v in VIEWS.items() if not argv or k in argv}
    return 0 if all(render(k, *v) for k, v in todo.items()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
