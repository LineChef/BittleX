"""The arm as the viewers draw it (2026-11-01, user: "more closely match what the claw looks like"): the claw's round orange base with two black printed pointed jaws, a spring across their
hollow, the camera case with its lens and its coiled cable to the pod, the neck servo's slotted orange housing and the black linkage. Sizes are read off the user's photos of G2's arm in its rest pose (top, side, front,
underside and close-ups; no CAD and no calipers: scaled against the pod and the 29 x 47 mm camera case, good to about 10%). Looks only: the physics keeps the boxes
(opencat_gym_env ARM_PARTS), so nothing here changes training or any score.

    watch_live.build calls make_body(p, part, pos, orn, dims) for the parts drawn here; it returns the body id, or None to draw the part as its box.

Frames: each mesh is expressed relative to its part's box centre (the sim's body origin: x forward, y left, z up; metres). The jaw box centre is 0.110 m ahead of the base centre,
0.009 m to its side, and its bottom edge 0.005 m below it (the claw's ground clearance stays what the sim has). Photo sizes (mm): base 47 across and 7 thick, rear half a disc, its front cut
8 mm ahead of its centre; jaws 16 tall, 47 across at the shoulder, tapering to a point 36 mm ahead of that, 7.5 mm thick at the sides and about 6 mm solid at the tip; a 19 mm spring across the hollow."""
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "models", "local")
VERSION = "v4"
BOX_X, BOX_Y, BOX_Z_BOTTOM = 0.110, 0.009, -0.005        # the jaw box's centre in the claw's frame, and its bottom edge below that centre
PLATE_X, PLATE_R, PLATE_T, PLATE_CUT = 0.116, 0.024, 0.007, 0.008     # the base's centre (its rear edge meets the claw servo's front face), radius, thickness, front cut ahead of the centre
JAW_X, JAW_W, JAW_L, JAW_H = PLATE_X + PLATE_CUT, 0.0235, 0.036, 0.016  # where the jaws start, their half-width there, their length to the tip, their height
JAW_T, TIP_FRAC = 0.0075, 0.85                            # wall thickness at the sides; the hollow ends at this fraction of the jaws' length
SPRING_LEN, SPRING_R = 0.019, 0.0016
# The camera's coiled USB cable (photos, 2026-11-01): from a port on the pod's top (about a third of the way back from its front edge, near the middle), an 18 mm metal plug, up about
# 2.3 in above the pod in an arc, a coil of about 10 turns 8 mm across, then down into a 15 mm plug on top of the camera case. Points in the base frame (m); the camera's centre there
# (opencat_gym_env ARM_PARTS with the default ARM_LOWER_DZ) turns them into the camera body's frame. The per-episode arm shift (up to 0.4 in) moves the pod end with the camera.
CAMERA_C = np.array([0.0835, 0.0, -0.0056])
POD_TOP = 0.0652                                          # the pod's top in the base frame (PAYLOAD_POS z + PAYLOAD_BOX_HALF z)
CABLE_R, COIL_WIRE_R, COIL_R, COIL_TURNS = 0.0016, 0.0012, 0.004, 10
CABLE_PTS = [(0.008, 0.003, POD_TOP + 0.018), (0.009, 0.003, 0.095), (0.016, 0.002, 0.115), (0.030, 0.0, 0.124), (0.045, 0.0, 0.122)]   # the pod plug's top to the coil
COIL_END = (0.070, 0.0, 0.100)
CABLE_PTS2 = [(0.078, 0.0, 0.088), (0.0835, 0.0, 0.065), (0.0835, 0.0, 0.0178 + 0.015)]                                               # the coil to the camera plug's top
N = 14
BLACK, ORANGE, SILVER, CAMERA_GREEN = [0.12, 0.12, 0.13, 1], [0.95, 0.62, 0.1, 1], [0.72, 0.73, 0.75, 1], [0.86, 0.93, 0.74, 1]


def _prism(loop, caps, a0, a1):
    """Extrude a 2D outline (list of (u, v)) between a0 and a1 along the third axis into triangles (n, 3, 3) as (u, v, w); `caps` are index triples into the outline for the flat faces."""
    pts = np.array(loop, dtype=float)
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    if area < 0:
        pts = pts[::-1]
        caps = [tuple(len(pts) - 1 - i for i in c) for c in caps]
    tris = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        tris.append([(*a, a0), (*b, a0), (*b, a1)])
        tris.append([(*a, a0), (*b, a1), (*a, a1)])
    for c in caps:
        q = pts[list(c)]
        if 0.5 * ((q[1, 0] - q[0, 0]) * (q[2, 1] - q[0, 1]) - (q[2, 0] - q[0, 0]) * (q[1, 1] - q[0, 1])) < 0:
            q = q[::-1]
        tris.append([(*q[0], a1), (*q[1], a1), (*q[2], a1)])
        tris.append([(*q[0], a0), (*q[2], a0), (*q[1], a0)])
    return np.array(tris, dtype=float)


def _jaw_left():
    """The pointed jaw's left half: a hollow shield, closed at the tip."""
    t = np.linspace(0.0, 1.0, 2 * N + 1)
    m = int(np.searchsorted(t, TIP_FRAC - 1e-9))
    tm = t[m]
    outer = [(JAW_X + JAW_L * s, JAW_W * (1 - s ** 1.7) ** 0.9) for s in t]
    inner = [(JAW_X + JAW_L * s, (JAW_W - JAW_T) * (1 - (s / tm) ** 1.7) ** 0.9) for s in t[:m + 1]]
    n_out = len(outer)
    loop = outer + inner[::-1]
    iidx = lambda j: n_out + (m - j)
    caps = []
    for i in range(m):
        caps.append((i, i + 1, iidx(i + 1)))
        caps.append((i, iidx(i + 1), iidx(i)))
    caps += [(iidx(m), k, k + 1) for k in range(m, n_out - 1)]
    return _prism(loop, caps, BOX_Z_BOTTOM, BOX_Z_BOTTOM + JAW_H)


def _plate_left():
    """The orange base's left half: a disc cut straight across 8 mm ahead of its centre."""
    xc = PLATE_X + PLATE_CUT
    yc = np.sqrt(PLATE_R ** 2 - PLATE_CUT ** 2)
    a0 = np.arctan2(yc, PLATE_CUT)
    th = np.linspace(a0, np.pi, 2 * N)
    loop = [(xc, 0.0)] + [(PLATE_X + PLATE_R * np.cos(a), PLATE_R * np.sin(a)) for a in th]
    caps = [(0, i, i + 1) for i in range(1, len(loop) - 1)]
    return _prism(loop, caps, BOX_Z_BOTTOM, BOX_Z_BOTTOM + PLATE_T)


def _camera(dims):
    """The camera case: a box with its two top corners cut off (the USB-C end), as in the front photo."""
    d, w, h = (x / 2 for x in dims)
    c = 0.0055
    loop = [(-w, -h), (w, -h), (w, h - c), (w - c, h), (-w + c, h), (-w, h - c)]
    caps = [(0, i, i + 1) for i in range(1, 5)]
    t = _prism(loop, caps, -d, d)                    # (y, z, x)
    return t[..., [2, 0, 1]]                         # to (x, y, z)


def _catmull(pts, n=8):
    """A smooth curve through the points (Catmull-Rom, the ends held)."""
    P = np.array(pts, dtype=float)
    P = np.vstack([P[0], P, P[-1]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2])
    return np.array(out)


def _tube(path, r, sides=8):
    """A round tube along a path (both faces, so it shows from either side)."""
    path = np.asarray(path, dtype=float)
    tris = []
    rings = []
    for i in range(len(path)):
        t = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        t /= max(np.linalg.norm(t), 1e-9)
        ref = np.array([0, 0, 1.0]) if abs(t[2]) < 0.9 else np.array([1.0, 0, 0])
        u = np.cross(t, ref); u /= np.linalg.norm(u)
        v = np.cross(t, u)
        rings.append([path[i] + r * (np.cos(a) * u + np.sin(a) * v) for a in np.linspace(0, 2 * np.pi, sides, endpoint=False)])
    for i in range(len(rings) - 1):
        for k in range(sides):
            a, b, c, d = rings[i][k], rings[i][(k + 1) % sides], rings[i + 1][(k + 1) % sides], rings[i + 1][k]
            tris += [[a, b, c], [a, c, d], [a, c, b], [a, d, c]]
    return np.array(tris, dtype=float)


def _cable():
    """The coiled cable from the pod's plug to the camera's plug, in the camera body's frame."""
    a = _catmull(CABLE_PTS)
    c0, c1 = np.array(CABLE_PTS[-1]), np.array(COIL_END)
    axis = c1 - c0
    L = np.linalg.norm(axis); ax = axis / L
    u = np.cross(ax, [0, 1.0, 0]); u /= np.linalg.norm(u); v = np.cross(ax, u)
    th = np.linspace(0, 2 * np.pi * COIL_TURNS, COIL_TURNS * 16)
    coil = np.array([c0 + ax * L * (k / th[-1]) + COIL_R * (np.cos(k) * u + np.sin(k) * v) for k in th])
    b = _catmull([tuple(c1)] + CABLE_PTS2)
    t = np.concatenate([_tube(a, CABLE_R), _tube(coil, COIL_WIRE_R, 6), _tube(b, CABLE_R)])
    return t - CAMERA_C


def _shift(tris, side):
    t = tris.copy()
    t[..., 0] -= BOX_X
    t[..., 1] -= BOX_Y
    if side == "right":
        t[..., 1] = -tris[..., 1] + BOX_Y            # mirror about the claw's centre line, relative to the right box's centre
        t = t[:, ::-1]                               # keep the faces pointing out
    return t


def _write_obj(path, tris):
    v = tris.reshape(-1, 3)
    with open(path + f".tmp{os.getpid()}", "w") as f:
        for x, y, z in v:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for i in range(0, len(v), 3):
            f.write(f"f {i + 1} {i + 2} {i + 3}\n")
    os.replace(path + f".tmp{os.getpid()}", path)


def _mesh(name, make):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"arm_{name}_{VERSION}.obj")
    if not os.path.exists(path):
        _write_obj(path, make())
    return path


def jaw_meshes(side):
    """(black jaw OBJ path, orange plate OBJ path) for 'left' or 'right', written if missing."""
    return (_mesh(f"jaw_{side}", lambda: _shift(_jaw_left(), side)), _mesh(f"plate_{side}", lambda: _shift(_plate_left(), side)))


def jaw_hull(side):
    """The claw half's collision points for the sim's real-size claw (opencat_gym_env G2E_CLAW_REAL): the drawn jaw and base, relative to the jaw body; pybullet wraps them in a convex hull."""
    v = np.concatenate([_shift(_jaw_left(), side).reshape(-1, 3), _shift(_plate_left(), side).reshape(-1, 3)])
    return np.unique(np.round(v, 6), axis=0).tolist()


def _body(p, base, links, pos, orn):
    """A welded body with a base visual and fixed-link visuals: base = a visual shape index, links = [(visual shape index, (x, y, z))]."""
    n = len(links)
    ident = [[0, 0, 0, 1]] * n
    return p.createMultiBody(0, baseVisualShapeIndex=base, basePosition=pos, baseOrientation=orn, linkMasses=[0] * n, linkCollisionShapeIndices=[-1] * n,
                             linkVisualShapeIndices=[v for v, _ in links], linkPositions=[list(q) for _, q in links], linkOrientations=ident, linkInertialFramePositions=[[0, 0, 0]] * n,
                             linkInertialFrameOrientations=ident, linkParentIndices=[0] * n, linkJointTypes=[p.JOINT_FIXED] * n, linkJointAxis=[[0, 0, 1]] * n)


def make_body(p, part, pos, orn, dims):
    """The viewer's body for one arm part, or None to draw the part as its box. `dims` are the part's box edge lengths (the scene's)."""
    if part in ("jaw_left", "jaw_right"):
        side = part.split("_")[1]
        jaw_f, plate_f = jaw_meshes(side)
        sgn = 1.0 if side == "left" else -1.0
        base = p.createVisualShape(p.GEOM_MESH, fileName=jaw_f, rgbaColor=BLACK)
        plate = p.createVisualShape(p.GEOM_MESH, fileName=plate_f, rgbaColor=ORANGE)
        spring = p.createVisualShape(p.GEOM_CYLINDER, radius=SPRING_R, length=SPRING_LEN / 2, rgbaColor=SILVER, visualFrameOrientation=[0.7071068, 0, 0, 0.7071068])
        spring_pos = (JAW_X + 0.004 - BOX_X, sgn * (SPRING_LEN / 4) - sgn * BOX_Y, BOX_Z_BOTTOM + PLATE_T + 0.004)
        return _body(p, base, [(plate, (0, 0, 0)), (spring, spring_pos)], pos, orn)
    if part == "camera":
        path = _mesh(f"camera_{round(dims[0] * 1e4)}_{round(dims[1] * 1e4)}_{round(dims[2] * 1e4)}", lambda: _camera(dims))      # the size is in the name: a changed camera box never reuses an old file
        base = p.createVisualShape(p.GEOM_MESH, fileName=path, rgbaColor=CAMERA_GREEN)
        lens = p.createVisualShape(p.GEOM_CYLINDER, radius=0.0027, length=0.0012, rgbaColor=[0.05, 0.05, 0.06, 1], visualFrameOrientation=[0, 0.7071068, 0, 0.7071068])
        cable = p.createVisualShape(p.GEOM_MESH, fileName=_mesh("cable", _cable), rgbaColor=BLACK)
        plug = p.createVisualShape(p.GEOM_CYLINDER, radius=0.0035, length=0.016, rgbaColor=SILVER)
        pod_plug = np.array([CABLE_PTS[0][0], CABLE_PTS[0][1], POD_TOP + 0.009]) - CAMERA_C
        cam_plug = np.array([CAMERA_C[0], 0.0, 0.0178 + 0.0075]) - CAMERA_C
        return _body(p, base, [(lens, (dims[0] / 2 + 0.0004, 0.0, -0.0028)), (cable, (0, 0, 0)), (plug, tuple(pod_plug)), (plug, tuple(cam_plug))], pos, orn)
    if part == "lift_servo":
        base = p.createVisualShape(p.GEOM_BOX, halfExtents=[d / 2 for d in dims], rgbaColor=ORANGE)
        slot = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.0007, 0.0002, 0.0075], rgbaColor=BLACK)
        links = [(slot, (x, s * (dims[1] / 2 + 0.0001), 0.0)) for s in (1, -1) for x in (-0.0042, -0.0014, 0.0014, 0.0042)]
        return _body(p, base, links, pos, orn)
    return None


if __name__ == "__main__":
    for s in ("left", "right"):
        print(jaw_meshes(s))
