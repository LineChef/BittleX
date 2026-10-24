"""G2's real look for the viewers (2026-10-24, user: "see the real robot body, and any other parts we have the models for"): a dressed copy of the sim's robot model,
models/local/bittle_dressed.urdf (gitignored, like the meshes it uses), with the same links and joints as models/bittle_esp32.urdf and the platform project's part meshes as
its visuals. Training keeps loading the plain model; only the viewers load this one, so nothing here changes the physics or the training speed.

    python build_body_mesh.py          # reads G2_POD_STL_DIR (default: the platform project's site/viewer/models next to this repo); then run build_pod_mesh.py

The project's meshes are one assembly in G2's frame (millimetres, front = -Z, left = -X, up = +Y), with the legs posed. Each leg's two joint angles in that pose, and the
assembly's height against the sim's joint line, are found by fitting the sim's leg segments (shoulder -> knee -> paw) to the thigh and shank meshes; each mesh is then
moved into its own link's frame, so it follows the joints in the viewer. Torso-mounted parts, the pod included (at its CAD place), go on the torso. Writes models/local/body_mesh.json (the fit) as well."""
import json
import os
import xml.etree.ElementTree as ET

import numpy as np

from build_pod_mesh import PARTS as POD_PARTS, R, SRC, load_stl, save_stl

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "models", "local")
URDF = os.path.join(HERE, "models", "bittle_esp32.urdf")
# torso-mounted parts: (file, colour from the project's viewer manifest, mirror x, left out with the arm)
TORSO = [("robot_hip_servos.stl", "#26272b", False, False), ("robot_battery.stl", "#4a4c52", False, False), ("reference_Bittle_FrontPlate.stl", "#26272b", False, False),
         ("robot_rear_plate.stl", "#26272b", False, False), ("reference_Bittle_SideShoulder.stl", "#f2a71c", False, False),
         ("reference_Bittle_SideShoulder.stl", "#f2a71c", True, False), ("robot_neck_mount.stl", "#26272b", False, False), ("robot_tail.stl", "#3a3b40", False, False),
         ("installed_cover_pegs.stl", "#34363b", False, False), ("robot_head.stl", "#3a3b40", False, True)]
# legs: CAD name -> (sim upper link, sim lower link, shoulder joint, knee joint)
LEGS = {"lf": ("left_upper_arm", "left_lower_arm", "shoulder_left", "elbow_left"), "rf": ("right_upper_arm", "right_lower_arm", "shoulder_right", "elbow_right"),
        "lr": ("left_upper_leg", "left_lower_leg", "hip_left", "knee_left"), "rr": ("right_upper_leg", "right_lower_leg", "hip_right", "knee_right")}
THIGH_RGB, SHANK_RGB = "#f2a71c", "#2c2d31"


def rgba(h):
    return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1.0]


def to_sim(tris, mirror=False):
    v = tris.copy()
    if mirror:
        v[..., 0] *= -1
        v = v[:, ::-1]                                              # keep the faces pointing out
    return v @ R.T / 1000.0


def seg_dist2(pts, a, b):
    ab = b - a
    t = np.clip(((pts - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    d = pts - (a + t[:, None] * ab)
    return (d * d).sum(1)


def main():
    import pybullet as p
    p.connect(p.DIRECT)
    rid = p.loadURDF(URDF, [0, 0, 0], [0, 0, 0, 1], useFixedBase=True)
    jn = {p.getJointInfo(rid, j)[1].decode(): j for j in range(p.getNumJoints(rid))}
    ln = {p.getJointInfo(rid, j)[12].decode(): j for j in range(p.getNumJoints(rid))}
    paw_of = {"left_lower_arm": "left_front_paw", "right_lower_arm": "right_front_paw", "left_lower_leg": "left_back_paw", "right_lower_leg": "right_back_paw"}

    def fk(link):
        s = p.getLinkState(rid, ln[link], computeForwardKinematics=True)
        return np.array(s[4]), np.array(p.getMatrixFromQuaternion(s[5])).reshape(3, 3)

    legs = {k: (to_sim(load_stl(os.path.join(SRC, f"robot_thigh_{k}.stl"))).reshape(-1, 3), to_sim(load_stl(os.path.join(SRC, f"robot_shank_{k}.stl"))).reshape(-1, 3)) for k in LEGS}
    grid = np.radians(np.arange(-180, 180, 1.0))

    def fit_leg(k, dz):
        up, lo, js, jk = LEGS[k]
        th, sh = legs[k][0][::7] + [0, 0, dz], legs[k][1][::7] + [0, 0, dz]
        p.resetJointState(rid, jk, 0)
        best = None
        for q in grid:
            p.resetJointState(rid, js, q)
            a, b = fk(up)[0], fk(lo)[0]
            e = seg_dist2(th, a, b).mean()
            if best is None or e < best[0]:
                best = (e, q)
        p.resetJointState(rid, js, best[1])
        bk = None
        for q in grid:
            p.resetJointState(rid, jk, q)
            a, b = fk(lo)[0], fk(paw_of[lo])[0]
            e = seg_dist2(sh, a, b).mean()
            if bk is None or e < bk[0]:
                bk = (e, q)
        p.resetJointState(rid, jk, bk[1])
        return best[0] + bk[0], best[1], bk[1]

    for k in LEGS:
        LEGS[k] = (LEGS[k][0], LEGS[k][1], jn[LEGS[k][2]], jn[LEGS[k][3]])
    fits = []
    for dz_mm in range(-30, 31, 2):
        err = sum(fit_leg(k, dz_mm / 1000.0)[0] for k in LEGS)
        fits.append((err, dz_mm))
    dz = min(fits)[1] / 1000.0
    pose, rms = {}, {}
    for k in LEGS:
        e, qs, qk = fit_leg(k, dz)
        pose[k] = (qs, qk)
        rms[k] = float(np.sqrt(e / 2) * 1000)
    for k, (qs, qk) in pose.items():
        p.resetJointState(rid, LEGS[k][2], qs)
        p.resetJointState(rid, LEGS[k][3], qk)

    os.makedirs(OUT, exist_ok=True)
    visuals = {}                                                   # link -> [(file, rgba, arm_ok)]
    for f, colour, mirror, not_arm in TORSO:
        name = "body_" + f.replace(".stl", "").replace("robot_", "").replace("reference_", "").replace("installed_", "") + ("_l" if mirror else "")
        tris = to_sim(load_stl(os.path.join(SRC, f)), mirror) + [0, 0, dz]
        save_stl(os.path.join(OUT, name + ".stl"), tris)
        visuals.setdefault("torso", []).append((name + ".stl", rgba(colour), not not_arm))
    for f, colour, in_arm in POD_PARTS:                            # the pod at its CAD place on the cover (the camera and its mount only without the arm: it rides on the claw)
        name = "pod_" + f.replace(".stl", "").replace("installed_pod_", "").replace("parts_", "")
        save_stl(os.path.join(OUT, name + ".stl"), to_sim(load_stl(os.path.join(SRC, f))) + [0, 0, dz])
        visuals.setdefault("torso", []).append((name + ".stl", rgba(colour), in_arm))
    for k, (up, lo, _js, _jk) in LEGS.items():
        for link, part, colour in ((up, "thigh", THIGH_RGB), (lo, "shank", SHANK_RGB)):
            pos, rot = fk(link)
            tris = to_sim(load_stl(os.path.join(SRC, f"robot_{part}_{k}.stl"))) + [0, 0, dz]
            local = (tris - pos) @ rot                              # world -> link frame (row vectors: v_local = R^T (v - p))
            name = f"leg_{part}_{k}"
            save_stl(os.path.join(OUT, name + ".stl"), local)
            visuals.setdefault(link, []).append((name + ".stl", rgba(colour), True))

    for arm in (False, True):
        tree = ET.parse(URDF)
        for link in tree.getroot().iter("link"):
            name = link.get("name")
            for v in link.findall("visual"):
                link.remove(v)
            if name not in visuals:                                 # a link with no visual is drawn as its collision shape (white): the paws as dark rubber feet of the same shape, others hidden
                col = link.find("collision")
                if col is not None:
                    v = ET.SubElement(link, "visual")
                    for el in (col.find("origin"), col.find("geometry")):
                        if el is not None:
                            v.append(el)
                    m = ET.SubElement(v, "material", name=f"m_{name}")
                    ET.SubElement(m, "color", rgba="0.10 0.10 0.11 1" if name.endswith("_paw") else "0 0 0 0")
            for f, c, arm_ok in visuals.get(name, []):
                if arm and not arm_ok:
                    continue
                v = ET.SubElement(link, "visual")
                ET.SubElement(v, "origin", xyz="0 0 0", rpy="0 0 0")
                g = ET.SubElement(v, "geometry")
                ET.SubElement(g, "mesh", filename=f, scale="1 1 1")
                m = ET.SubElement(v, "material", name=f"m_{f[:-4]}")
                ET.SubElement(m, "color", rgba=" ".join(f"{x:.3f}" for x in c))
        tree.write(os.path.join(OUT, "bittle_dressed_arm.urdf" if arm else "bittle_dressed.urdf"))
    info = {"cad_dz_m": dz, "pose_deg": {k: [round(float(np.degrees(a)), 1) for a in v] for k, v in pose.items()}, "leg_fit_rms_mm": {k: round(v, 1) for k, v in rms.items()}}
    json.dump(info, open(os.path.join(OUT, "body_mesh.json"), "w"), indent=1)
    print(f"dressed model written to {OUT}: CAD height vs the sim's joint line {dz * 1000:+.0f} mm; leg pose (shoulder, knee deg) {info['pose_deg']}; fit rms mm {info['leg_fit_rms_mm']}")


if __name__ == "__main__":
    main()
