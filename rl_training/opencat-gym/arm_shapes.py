"""The arm's claw as the viewers draw it (2026-11-01, user: "more closely match what the claw looks like"): a round orange base plate with two black printed jaws in a rounded wedge,
sized from three photos of G2's arm in its rest pose (top, side and front, 2026-11-01; no CAD and no calipers, so the sizes are read off the photos against the pod and the
29 mm camera case and are good to about 10%). Looks only: the physics keeps the two thin jaw boxes (opencat_gym_env ARM_PARTS), so nothing here changes training.

    watch_live.build asks for jaw_meshes(side): (the black jaw half, the orange plate half) as OBJ files written to models/local/ (gitignored, regenerated if missing).

Frames: each half is expressed relative to its jaw box's centre (the sim's jaw_left / jaw_right body origin: x forward, y left, z up; metres), the box centre being 0.110 m ahead
of the base centre, 0.009 m to its side, and its bottom 0.005 m below it (the claw's ground clearance stays what the sim has). Sizes read off the photos (mm):
plate 44 across and 7 thick, jaws 16 tall and 44 across overall, the black jaw tips 40 ahead of the plate's centre, the plate's front 22 ahead of the claw servo's front face."""
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "models", "local")
BOX_X, BOX_Y, BOX_Z_BOTTOM = 0.110, 0.009, -0.005        # the jaw box's centre in the claw's frame, and its bottom edge below that centre
PLATE_X = 0.116                                           # the plate's centre, 0.094 (the claw servo's front face) + its 22 mm radius
PLATE_R, PLATE_T = 0.022, 0.007
JAW_H = 0.016
JAW_OUT = (0.040, 0.022)                                  # outer edge of the jaws: half-ellipse, 40 mm ahead of the plate's centre, 22 mm to each side
JAW_IN = (0.030, 0.0165, -0.004)                          # inner edge: the jaws are 10 mm thick at the tip, 5.5 mm at the sides; centre 4 mm behind the plate's centre
N = 14


def _prism(loop, caps, z0, z1):
    """Extrude a 2D outline (list of (x, y)) between z0 and z1 into triangles (n, 3, 3). `caps` are index triples into the outline for the flat faces."""
    pts = np.array(loop, dtype=float)
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    if area < 0:
        pts = pts[::-1]
        caps = [tuple(len(pts) - 1 - i for i in c) for c in caps]
    tris = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        tris.append([(*a, z0), (*b, z0), (*b, z1)])
        tris.append([(*a, z0), (*b, z1), (*a, z1)])
    for c in caps:
        q = pts[list(c)]
        if 0.5 * ((q[1, 0] - q[0, 0]) * (q[2, 1] - q[0, 1]) - (q[2, 0] - q[0, 0]) * (q[1, 1] - q[0, 1])) < 0:
            q = q[::-1]
        tris.append([(*q[0], z1), (*q[1], z1), (*q[2], z1)])
        tris.append([(*q[0], z0), (*q[2], z0), (*q[1], z0)])
    return np.array(tris, dtype=float)


def _jaw_left():
    th = np.linspace(0.0, np.pi / 2, N)
    outer = [(PLATE_X + JAW_OUT[0] * np.cos(t), JAW_OUT[1] * np.sin(t)) for t in th]
    inner = [(PLATE_X + JAW_IN[2] + JAW_IN[0] * np.cos(t), JAW_IN[1] * np.sin(t)) for t in th]
    loop = outer + inner[::-1]
    caps = [(i, i + 1, 2 * N - 1 - i) for i in range(N - 1)] + [(i + 1, 2 * N - 2 - i, 2 * N - 1 - i) for i in range(N - 1)]
    return _prism(loop, caps, BOX_Z_BOTTOM, BOX_Z_BOTTOM + JAW_H)


def _plate_left():
    th = np.linspace(0.0, np.pi, 2 * N)
    loop = [(PLATE_X, 0.0)] + [(PLATE_X + PLATE_R * np.cos(t), PLATE_R * np.sin(t)) for t in th]
    caps = [(0, i, i + 1) for i in range(1, len(loop) - 1)]
    return _prism(loop, caps, BOX_Z_BOTTOM, BOX_Z_BOTTOM + PLATE_T)


def _shift(tris, side):
    t = tris.copy()
    t[..., 0] -= BOX_X
    t[..., 1] -= BOX_Y
    if side == "right":
        t[..., 1] = -tris[..., 1] + BOX_Y               # mirror about the claw's centre line, relative to the right box's centre
        t = t[:, ::-1]                                  # keep the faces pointing out
    return t


def _write_obj(path, tris):
    v = tris.reshape(-1, 3)
    with open(path + ".tmp", "w") as f:
        for x, y, z in v:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for i in range(0, len(v), 3):
            f.write(f"f {i + 1} {i + 2} {i + 3}\n")
    os.replace(path + ".tmp", path)


def jaw_meshes(side):
    """(black jaw OBJ path, orange plate OBJ path) for 'left' or 'right', written if missing."""
    os.makedirs(OUT, exist_ok=True)
    out = []
    for name, tris in (("jaw", _jaw_left()), ("plate", _plate_left())):
        path = os.path.join(OUT, f"claw_{name}_{side}_v1.obj")
        if not os.path.exists(path):
            _write_obj(path, _shift(tris, side))
        out.append(path)
    return tuple(out)


if __name__ == "__main__":
    for s in ("left", "right"):
        print(jaw_meshes(s))
