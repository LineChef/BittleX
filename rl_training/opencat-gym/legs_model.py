"""Leg builds for the simulator (user, 2026-10-31): the wide shoulder parts and the hinged paws, as settings that are OFF by default so a stock-legs
policy can always be trained again.

    G2E_SHOULDER_WIDEN_MM   mm each of the four leg servos sits further out (0 = stock; the printed wide_shoulder_ends part: 5.08 = 0.2 in)
    G2E_PAW                 none (stock feet) | clpaw | seated: a hinged paw on every foot, built from the owner's paw STL
    G2E_PAW_STL             a different paw STL (optional; same frame as the presets)

With both at their defaults nothing changes: opencat_gym_env loads the stock URDF as before. Otherwise the model is built once into
models/local/legs/<key>/ (gitignored, rebuilt when missing; the key covers the base URDF, the settings and the STL's bytes).

The paw STLs are the owner's design files and stay outside the repository (read only): the folder holding the paw folders comes from G2_PROTOTYPES_DIR or the
one-line file ~/.local/share/g2/prototypes_dir. Paw frame (the owner's wide_foot_part.scad / paw_checks.py): x outward, y toward the toe, z up, sole at z = 0,
the pivot along x at y = 0, PIN_Z above the sole. Collision is the paw's convex hull (the sole's window, the seats and the hollow toe are filled in).
The paw's pivot friction comes from the preset (opencat_gym_env reads pin_friction_default / rim_mur_default); G2E_PAW_PIN_FRICTION / G2E_PAW_RIM_MUR override.

    python legs_model.py [--widen 5.08] [--paw clpaw]      # build and print the model's path, mass and pivot; stock with no options
"""
import hashlib
import json
import os
import re
import shutil

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "models", "local", "legs")
VERSION = 1                     # bump when the build changes, so cached models are rebuilt
PAD_R = 0.006                   # the sim's stock foot: a 6 mm radius cylinder
PETG_G_CM3 = 1.27               # printed at 100% infill (the blueprint's assumption)
# preset: (folder/file under the prototypes dir, pivot above the sole mm, stock foot showing below the sole mm, stops toe up / toe down deg, pin friction N m, rim friction N m per N)
PAWS = {
    "clpaw": ("CLpaw/CLpaw.stl", 4.5, 1.0, 30.0, 13.0, 0.0, 0.0),            # a pin through the foot: modelled free (the 2026-10-23 sole sweep's setting)
    "seated": ("seated/seated.stl", 4.5, 1.0, 30.0, 13.0, 0.0018, 0.0022),   # clip flaps with cone pegs: the blueprint's nominal grip
}
LEG_JOINTS = ("shoulder_left", "shoulder_right", "hip_right", "hip_left")     # the four servo mounts on the torso
LOWER = {"FL": "left_lower_arm", "FR": "right_lower_arm", "BR": "right_lower_leg", "BL": "left_lower_leg"}
FOOT = {"FL": "left_front_paw", "FR": "right_front_paw", "BR": "right_back_paw", "BL": "left_back_paw"}


def widen_mm():
    return float(os.environ.get("G2E_SHOULDER_WIDEN_MM", "0") or 0.0)


def paw_name():
    v = (os.environ.get("G2E_PAW", "none") or "none").strip().lower()
    if v not in ("none", *PAWS):
        raise ValueError(f"G2E_PAW={v!r}: use none, {', '.join(PAWS)}")
    return v


def active():
    return widen_mm() != 0.0 or paw_name() != "none"


def pin_friction_default():
    return PAWS[paw_name()][5] if paw_name() != "none" else 0.0


def rim_mur_default():
    return PAWS[paw_name()][6] if paw_name() != "none" else 0.0


def prototypes_dir():
    d = os.environ.get("G2_PROTOTYPES_DIR")
    if not d:
        f = os.path.expanduser("~/.local/share/g2/prototypes_dir")
        d = open(f).read().strip() if os.path.exists(f) else ""
    if not d:
        raise FileNotFoundError("the paw STL folder is not set: G2_PROTOTYPES_DIR or ~/.local/share/g2/prototypes_dir")
    return os.path.expanduser(d)


def paw_stl(name):
    return os.environ.get("G2E_PAW_STL") or os.path.join(prototypes_dir(), PAWS[name][0])


def load_stl(path):
    data = open(path, "rb").read()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        v = [[float(x) for x in xyz] for xyz in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)]
        return np.array(v).reshape(-1, 3, 3)
    n = int(np.frombuffer(data[80:84], "<u4")[0])                     # binary STL
    rec = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return rec["v"].astype(float)


def volume_com(tri):
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    v6 = np.einsum("ij,ij->i", a, np.cross(b, c))
    return v6.sum() / 6.0, (((a + b + c) / 4.0) * v6[:, None]).sum(0) / v6.sum()


def widen_urdf(text, mm):
    """The four leg mounts move mm outward in y (the sign of each mount's own y)."""
    if not mm:
        return text
    for j in LEG_JOINTS:
        m = re.search(r'(<joint name="%s"[^>]*>.*?<origin xyz=")([-0-9.e]+) ([-0-9.e]+) ([-0-9.e]+)(")' % j, text, re.S)
        if not m:
            raise ValueError(f"joint {j} not found in the base URDF")
        y = float(m.group(3))
        text = text[:m.start(3)] + f"{y + np.sign(y) * mm / 1000.0:.6f}" + text[m.end(3):]
    return text


def _frames(urdf_path, stand_pose):
    """World frames of the lower legs and stock feet with the body level at the origin and the joints at the stand pose (a private physics client)."""
    import pybullet as pb
    from pybullet_utils import bullet_client
    c = bullet_client.BulletClient(connection_mode=pb.DIRECT)
    try:
        rid = c.loadURDF(urdf_path, [0, 0, 0], [0, 0, 0, 1])
        names = {c.getJointInfo(rid, j)[12].decode(): j for j in range(c.getNumJoints(rid))}
        rev = [j for j in range(c.getNumJoints(rid)) if c.getJointInfo(rid, j)[2] == pb.JOINT_REVOLUTE]
        for j, q in zip(rev, stand_pose if stand_pose is not None else np.zeros(len(rev))):
            c.resetJointState(rid, j, float(q))
        out = {}
        for leg in LOWER:
            lo, ft = c.getLinkState(rid, names[LOWER[leg]], computeForwardKinematics=1), c.getLinkState(rid, names[FOOT[leg]], computeForwardKinematics=1)
            out[leg] = dict(low_pos=np.array(lo[4]), low_R=np.array(c.getMatrixFromQuaternion(lo[5])).reshape(3, 3), foot=np.array(ft[4]))
        return out
    finally:
        c.disconnect()


def _paw_xml(leg, g, tri, mass_g, com, pin_z, prot, up, down, workdir, outdir):
    from scipy.spatial import ConvexHull
    R, lp, foot = g["low_R"], g["low_pos"], g["foot"]
    fwd, upv = np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
    outward = np.array([0.0, 1.0 if foot[1] > 0 else -1.0, 0.0])
    pin_w = foot + upv * (-PAD_R + prot / 1000.0 + pin_z / 1000.0)          # the stock foot's lowest point is PAD_R below its frame; sole = that + prot; pivot = sole + pin_z
    origin_l = R.T @ (pin_w - lp)
    M = np.stack([outward, fwd, upv], axis=1)                             # paw frame (x, y, z) -> world, about the pivot

    def to_link(pts):
        return (R.T @ (M @ ((pts - np.array([0.0, 0.0, pin_z])) / 1000.0).T)).T

    vl = to_link(tri.reshape(-1, 3))
    hull = ConvexHull(vl)
    idx = np.unique(hull.simplices)
    remap = {int(i): k + 1 for k, i in enumerate(idx)}
    obj = os.path.join(outdir, f"paw_{leg}.obj")                         # the URDF names the final folder; the file is written in the work folder
    cen = vl[idx].mean(0)
    with open(os.path.join(workdir, f"paw_{leg}.obj"), "w") as f:
        for i in idx:
            f.write("v %.6f %.6f %.6f\n" % tuple(vl[i]))
        for s in hull.simplices:
            a, b, c = vl[s[0]], vl[s[1]], vl[s[2]]
            if np.dot(np.cross(b - a, c - a), a - cen) < 0:                 # outward-facing triangles
                s = (s[0], s[2], s[1])
            f.write("f %d %d %d\n" % tuple(remap[int(i)] for i in s))
    com_l = to_link(com[None, :])[0]
    dims = vl.max(0) - vl.min(0)
    m = mass_g / 1000.0
    ixx, iyy, izz = m / 12 * (dims[1] ** 2 + dims[2] ** 2), m / 12 * (dims[0] ** 2 + dims[2] ** 2), m / 12 * (dims[0] ** 2 + dims[1] ** 2)
    up_l, fwd_l = R.T @ upv, R.T @ fwd
    ax = R.T @ np.cross(fwd, upv)
    ax /= np.linalg.norm(ax)
    if np.dot(np.cross(ax, fwd_l), up_l) < 0:                             # a positive angle lifts the toe
        ax = -ax
    nm = FOOT[leg].replace("_paw", "")
    link = f"""    <link name="{nm}_pawplate">
        <visual><origin xyz="0 0 0" rpy="0 0 0"/><geometry><mesh filename="{obj}"/></geometry><material name="plate_{leg}"><color rgba="0.91 0.39 0.11 1"/></material></visual>
        <collision><origin xyz="0 0 0" rpy="0 0 0"/><geometry><mesh filename="{obj}"/></geometry></collision>
        <contact><friction_anchor/><spinning_friction value=".3"/><lateral_friction value="0.5"/></contact>
        <inertial><origin xyz="{com_l[0]:.6f} {com_l[1]:.6f} {com_l[2]:.6f}" rpy="0 0 0"/><mass value="{m:.6f}"/><inertia ixx="{ixx:.3e}" ixy="0" ixz="0" iyy="{iyy:.3e}" iyz="0" izz="{izz:.3e}"/></inertial>
    </link>
"""
    joint = f"""    <joint name="pawplate_{leg}" type="revolute">
        <origin xyz="{origin_l[0]:.6f} {origin_l[1]:.6f} {origin_l[2]:.6f}" rpy="0 0 0"/>
        <parent link="{LOWER[leg]}"/><child link="{nm}_pawplate"/>
        <axis xyz="{ax[0]:.6f} {ax[1]:.6f} {ax[2]:.6f}"/>
        <limit effort="0" lower="{-np.radians(down):.6f}" upper="{np.radians(up):.6f}" velocity="0"/>
    </joint>
"""
    return link, joint


def build(base_urdf, stand_pose=None, widen=None, paw=None):
    """The URDF path for these legs (built when missing). widen / paw default to the environment settings; stock legs return base_urdf unchanged."""
    widen = widen_mm() if widen is None else widen
    paw = paw_name() if paw is None else paw
    if not widen and paw == "none":
        return base_urdf
    base = open(base_urdf).read()
    stl = paw_stl(paw) if paw != "none" else None
    h = hashlib.sha256(json.dumps([VERSION, base, widen, paw, None if stand_pose is None else np.round(stand_pose, 6).tolist()]).encode())
    if stl:
        h.update(open(stl, "rb").read())
    outdir = os.path.join(OUT_ROOT, f"{os.path.basename(base_urdf).split('.')[0]}_w{widen:g}_{paw}_{h.hexdigest()[:10]}")
    path = os.path.join(outdir, "bittle_legs.urdf")
    if os.path.exists(path):
        return path
    # The training's parallel environments all build at once: each writes a private work folder and renames it into place in one step; a loser throws its copy away.
    work = f"{outdir}.work{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    text = widen_urdf(base, widen)
    info = {"base": base_urdf, "widen_mm": widen, "paw": paw}
    if stl:
        tmp = os.path.join(work, "wide.urdf")
        with open(tmp, "w") as f:
            f.write(text)
        geo = _frames(tmp, stand_pose)
        os.remove(tmp)
        _f, pin_z, prot, up, down, _pf, _rm = PAWS[paw]
        tri = load_stl(stl)
        vol, com = volume_com(tri)
        mass_g = abs(vol) * PETG_G_CM3 / 1000.0
        parts = [_paw_xml(leg, geo[leg], tri, mass_g, com, pin_z, prot, up, down, work, outdir) for leg in LOWER]
        text = text.replace("</robot>", "".join(p[0] for p in parts) + "".join(p[1] for p in parts) + "</robot>")
        info.update(stl=stl, stl_sha256=hashlib.sha256(open(stl, "rb").read()).hexdigest(), paw_mass_g=round(mass_g, 2),
                    com_mm=[round(float(x), 2) for x in com], pin_z_mm=pin_z, foot_showing_mm=prot, stops_deg=[up, down])
    with open(os.path.join(work, "bittle_legs.urdf"), "w") as f:
        f.write(text)
    with open(os.path.join(work, "build.json"), "w") as f:
        json.dump(info, f, indent=1)
    os.makedirs(OUT_ROOT, exist_ok=True)
    try:
        os.rename(work, outdir)
    except OSError:                                                       # another environment finished first: its model is the same
        shutil.rmtree(work, ignore_errors=True)
    return path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build a leg model (stock with no options).")
    ap.add_argument("--base", default=os.path.join(HERE, "models", "bittle_esp32_cad.urdf"))
    ap.add_argument("--widen", type=float, default=None)
    ap.add_argument("--paw", default=None, choices=["none", *PAWS])
    a = ap.parse_args()
    p = build(a.base, widen=a.widen, paw=a.paw)
    print(p)
    j = os.path.join(os.path.dirname(p), "build.json")
    if os.path.exists(j):
        print(open(j).read())
