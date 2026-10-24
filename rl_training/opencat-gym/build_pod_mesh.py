"""The pod's part list and the mesh helpers for build_body_mesh.py (2026-10-24, user: "something that looks like it when we run the sim vs just blocks"): the Bittle X Pi add-on's
installed STLs as drawn by the platform project's 3D viewer. build_body_mesh.py puts them on the dressed robot model's torso at their CAD place (models/local/, gitignored:
the project's files are not copied into this repository). Looks only: the physics keeps its box (opencat_gym_env PAYLOAD_BOX_HALF / PAYLOAD_POS).

    python build_pod_mesh.py            # the same as python build_body_mesh.py

The viewer's frame is G2's: millimetres, the origin between the four shoulder / hip joints, front = -Z, left = -X, up = +Y. The sim's base frame is front = +x, left = +y, up = +z."""
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
    import build_body_mesh
    build_body_mesh.main()


if __name__ == "__main__":
    main()
