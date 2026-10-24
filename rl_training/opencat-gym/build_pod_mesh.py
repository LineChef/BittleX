"""The pod's real look for the viewers (2026-10-24, user: "something that looks like it when we run the sim vs just blocks"): the Bittle X Pi add-on's installed STLs, as drawn by
the platform project's 3D viewer, moved into the frame of the sim's pod body and written to models/local/ (gitignored: the project's files are not copied into this repository).

    python build_pod_mesh.py            # reads G2_POD_STL_DIR (default: the platform project's site/viewer/models next to this repo)

Looks only: the physics keeps its box (opencat_gym_env PAYLOAD_BOX_HALF / PAYLOAD_POS), and the viewers draw these meshes on the box when the files exist, the box otherwise.

The viewer's frame is G2's: millimetres, the origin between the four shoulder / hip joints, front = -Z, left = -X, up = +Y. The sim's base frame is front = +x, left = +y, up = +z. The
pod's centre front to back and side to side lands on the sim box's centre already (-9.2 mm); its height does not: the CAD puts the pod bottom 26 mm above the joint line and the sim's box
puts it on the URDF torso's top, 10 mm up. The meshes are drawn on the box (what the sim simulates), so they sit 15.7 mm lower than the CAD."""
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "models", "local")
SRC = os.path.expanduser(os.environ.get("G2_POD_STL_DIR", os.path.join(HERE, "..", "..", "..", "beatlebug", "bittlex", "site", "viewer", "models")))
# (file, colour from the project's viewer manifest, in the arm build too): the camera moves to the claw with the arm (user, 2026-10-24), so its mount is left out there too
PARTS = [("installed_pod_body.stl", "#f2f2ef", True), ("installed_pod_panel.stl", "#e8641b", True), ("installed_pod_button.stl", "#f2f2ef", True),
         ("installed_pod_logo_white.stl", "#f2f2ef", True), ("installed_pod_logo_red.stl", "#d83a34", True), ("installed_pod_camera_mount.stl", "#e8641b", False),
         ("parts_camera__case.stl", "#2b2d33", False)]
BOX_CENTRE = (-0.0092, 0.0, 0.02895)          # opencat_gym_env PAYLOAD_POS (pod and arm profiles)
R = np.array([[0, 0, -1], [-1, 0, 0], [0, 1, 0]], dtype=float)      # viewer (x, y, z) -> sim (x, y, z)


def load_stl(path):
    d = open(path, "rb").read()
    if d[:5] == b"solid" and b"facet" in d[:300]:
        return np.array([list(map(float, l.split()[1:4])) for l in d.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")]).reshape(-1, 3, 3)
    n = struct.unpack("<I", d[80:84])[0]
    a = np.frombuffer(d[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    return a["v"].reshape(-1, 3, 3).astype(float)


def save_stl(path, tris):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    rec["n"], rec["v"] = n, tris.reshape(-1, 9)
    with open(path, "wb") as f:
        f.write(b"g2 pod mesh, sim pod-body frame, metres".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(rec.tobytes())


def main():
    body = [load_stl(os.path.join(SRC, f)) for f in ("installed_pod_body.stl", "installed_pod_panel.stl")]
    allv = np.concatenate([b.reshape(-1, 3) for b in body]) @ R.T / 1000.0
    centre = (allv.min(0) + allv.max(0)) / 2                       # the pod's own centre in the sim frame (CAD height)
    shift = np.array(BOX_CENTRE) - centre
    os.makedirs(OUT, exist_ok=True)
    index = []
    for f, colour, in_arm in PARTS:
        tris = load_stl(os.path.join(SRC, f)) @ R.T / 1000.0 + shift - np.array(BOX_CENTRE)     # relative to the pod body's origin
        name = "pod_" + f.replace("installed_pod_", "").replace("parts_", "")
        save_stl(os.path.join(OUT, name), tris)
        index.append({"file": name, "rgba": [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1.0], "in_arm": in_arm})
    import json
    json.dump({"parts": index, "cad_height_offset_m": round(float(-shift[2]), 4)}, open(os.path.join(OUT, "pod_mesh.json"), "w"), indent=1)
    print(f"wrote {len(index)} pod meshes to {OUT} (centre shift {np.round(shift * 1000, 1)} mm: drawn on the sim's box)")


if __name__ == "__main__":
    main()
