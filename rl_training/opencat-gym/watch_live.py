"""Watch the training run that is going on RIGHT NOW (user, 2026-10-09: "I want to see the actual run, in progress, not an approximation"). No simulation here: one of
the run's training environments (env 0) streams the episode it is actually simulating (its scene at each reset, then G2's pose and joints every 2 steps), and this
window draws exactly that, joining wherever the run is.

    python watch_live.py              # play each episode at real speed (80 Hz), then jump to the newest one
    python watch_live.py --fast       # draw the newest frame as the run produces it (about 4-5x real time)

`g2watchrun` runs this. The stream is on only while a viewer is open (this script touches trained/live/request every few seconds; the env checks it at each episode
start), so a run nobody watches pays nothing. A run started before 2026-10-09's change has no stream: the window says so and keeps waiting."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOLD_S = 1.2                                                # how long an episode's last frame stays up before the next episode is shown
LIVE = os.path.join(HERE, "trained", "live")
REQ = os.path.join(LIVE, "request")


def touch():
    os.makedirs(LIVE, exist_ok=True)
    with open(REQ, "a"):
        os.utime(REQ, None)


def build(p, scene):
    """Rebuild the episode's scene as it was at its reset; returns (robot id, {streamed body id: our body id})."""
    p.resetSimulation()
    p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 0)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    ids = {}
    for b in scene["bodies"]:
        for sh in b["shapes"]:
            if sh["type"] == "heightfield":
                import numpy as np
                n = sh["n"]
                cs = p.createCollisionShape(p.GEOM_HEIGHTFIELD, meshScale=sh["scale"], heightfieldData=sh["data"], numHeightfieldRows=n, numHeightfieldColumns=n)
                bid = p.createMultiBody(0, cs, basePosition=b["pos"], baseOrientation=b["orn"])
            elif sh["type"] == p.GEOM_PLANE:
                bid = p.loadURDF("plane.urdf", b["pos"], b["orn"])
            elif sh["type"] == p.GEOM_BOX:
                he = [d / 2 for d in sh["dims"]]
                vs = p.createVisualShape(p.GEOM_BOX, halfExtents=he, visualFramePosition=sh["lpos"], visualFrameOrientation=sh["lorn"])
                bid = p.createMultiBody(0, baseVisualShapeIndex=vs, basePosition=b["pos"], baseOrientation=b["orn"])
            elif sh["type"] == p.GEOM_SPHERE:
                vs = p.createVisualShape(p.GEOM_SPHERE, radius=sh["dims"][0], visualFramePosition=sh["lpos"])
                bid = p.createMultiBody(0, baseVisualShapeIndex=vs, basePosition=b["pos"], baseOrientation=b["orn"])
            elif sh["type"] in (p.GEOM_CYLINDER, p.GEOM_CAPSULE):
                vs = p.createVisualShape(sh["type"], radius=sh["dims"][1], length=sh["dims"][0], visualFramePosition=sh["lpos"], visualFrameOrientation=sh["lorn"])
                bid = p.createMultiBody(0, baseVisualShapeIndex=vs, basePosition=b["pos"], baseOrientation=b["orn"])
            else:
                continue
            color = [0.55, 0.55, 0.58, 1] if b.get("ground") else ([0.25, 0.45, 0.75, 1] if b["mass"] > 0 else [0.70, 0.55, 0.40, 1])
            try:
                p.changeVisualShape(bid, -1, rgbaColor=color)
            except Exception:  # noqa: BLE001
                pass
            ids[b["id"]] = bid
            break
    rid = p.loadURDF(os.path.join(HERE, "models", "bittle_esp32.urdf"), [0, 0, 0.1], useFixedBase=False)
    p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 1)
    return rid, ids


NAMES = {"ledge_up": "step up", "ledge_down": "step down", "rubble": "rubble", "boxes": "boxes", "snags": "snags", "slope": "slope", "sidehill": "side-hill",
         "threshold": "threshold", "shove": "shoves", "snag": "snag", "cutback": "switchback turn", "sidehill_r": "side-hill (right side down)",
         "sidehill_l": "side-hill (left side down)"}
ROLES = {"anchor": "flat-ground check", "combo": "mixed hazards", "focus": "hazard practice"}


def _amount(k, v):
    """A hazard's size in words: ledges in millimetres, the rest as a plain 0-100% strength."""
    return f"{abs(v) * 1000:.0f} mm" if k.startswith("ledge") and abs(v) < 0.2 else f"{min(abs(v), 1.0) * 100:.0f}%"


def describe(scene):
    """The overlay as short lines: what this episode is, what is in the way, how steep the ground is, how fast G2 was told to go."""
    hz = scene["hazards"]
    lines = [f"Episode {str(scene['ep']).split('_')[-1]}   ({ROLES.get(scene['role'], scene['role'] or 'episode')})"]
    lines.append("In the way: " + (", ".join(f"{NAMES.get(k, k.replace('_', ' '))} {_amount(k, v)}" for k, v in hz.items()) if hz else "nothing, flat ground"))
    roll, pitch = scene["slope_deg"]
    if abs(roll) >= 0.5 or abs(pitch) >= 0.5:
        lines.append(f"Ground tilt: {abs(pitch):.0f} deg {'uphill' if pitch > 0 else 'downhill'}, {abs(roll):.0f} deg sideways")
    if scene.get("ledge_mm"):
        lines.append(f"Ledge: {abs(scene['ledge_mm']):.0f} mm {'up' if scene['ledge_mm'] > 0 else 'down'}")
    lines.append(f"Speed asked for: {scene['cmd_fwd'] * 100:.0f} cm/s")
    return lines


def read_frames(f, out):
    """Append every complete new line of the frames file to `out` (a partial last line is left for the next read)."""
    while True:
        line = f.readline()
        if not line:
            return
        if not line.endswith("\n"):
            f.seek(f.tell() - len(line))
            return
        try:
            out.append(json.loads(line))
        except ValueError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="draw the newest frame as fast as the run produces it (about 4-5x real time) instead of playing each episode at real speed")
    ap.add_argument("--realtime", action="store_true", help="(default, kept for old habits)")
    a = ap.parse_args()
    import collections
    import pybullet as p
    p.connect(p.GUI)
    p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
    p.configureDebugVisualizer(p.COV_ENABLE_SHADOWS, 0)         # shadow maps flicker and cost frames on a laptop GPU
    touch()
    labels = []
    last_touch, ep, f, rid, ids, jids = time.time(), None, None, None, {}, []
    waited, scene, scene_t, scene_m = time.time(), None, 0.0, None
    q, t0, k0, last_k, end_t, cam, new_cam = collections.deque(), 0.0, 0, 0, 0.0, None, True
    print("watching trained/live (close the window or Ctrl-C to stop)", flush=True)
    try:
        while p.isConnected():
            now = time.time()
            if now - last_touch > 5:
                touch()
                last_touch = now
            if now - scene_t > 0.5:                                # the scene file is read twice a second, only when it changed
                scene_t = now
                scene_path = os.path.join(LIVE, "scene.json")
                try:
                    m = os.stat(scene_path).st_mtime
                    if m != scene_m:
                        scene, scene_m = json.load(open(scene_path)), m
                except (OSError, ValueError):
                    pass
            # an episode is played to its end at real speed, its last frame is held a moment, then the newest episode is shown (no mid-episode jumps, no flashing)
            playing = f is not None and not (end_t and now - end_t >= HOLD_S)
            idle = f is not None and not q and now - last_k > 1.5 and scene is not None and scene["ep"] != ep      # the stream stopped and a newer episode exists
            if scene is not None and scene["ep"] != ep and (f is None or idle or not playing):
                if now - scene["t"] > 60:
                    if now - waited > 10:
                        print("no live episode in the last minute: is a run training (started after the live-view change)?", flush=True)
                        waited = now
                    time.sleep(1)
                    continue
                try:
                    nf = open(os.path.join(LIVE, scene["frames"]))     # the run deletes an episode's frames when the next one starts: it can be gone already
                    nrid, nids = build(p, scene)
                except (OSError, KeyError, ValueError, p.error) as e:
                    print(f"skipping an episode that is already over ({type(e).__name__}); waiting for the next one", flush=True)
                    scene_m = None
                    scene = None
                    time.sleep(0.3)
                    continue
                if f is not None:
                    f.close()
                ep, jids, rid, ids, f = scene["ep"], scene["joint_ids"], nrid, nids, nf
                q.clear()
                t0, end_t, last_k = 0.0, 0.0, time.time()
                labels = []
                print(" | ".join(describe(scene)), flush=True)
                continue
            if f is None:
                time.sleep(0.2)
                continue
            read_frames(f, q)
            if not q:
                time.sleep(0.01)
                continue
            if a.fast:
                while len(q) > 1:
                    q.popleft()
                fr = q.popleft()
            else:
                # pace by the run's own step counter: frame k is due at k / 80 s after the first frame was shown
                if not t0:
                    t0, k0 = now, q[0]["k"]
                fr = None
                while q and now >= t0 + (q[0]["k"] - k0) / 80.0:
                    fr = q.popleft()                              # several can be due after a slow draw: show the latest, skip the rest
                    if fr.get("end"):
                        break
                if fr is None:
                    time.sleep(0.004)
                    continue
            last_k = time.time()
            b = fr["b"]
            p.resetBasePositionAndOrientation(rid, b[:3], b[3:7])
            for j, v in zip(jids, fr["j"]):
                p.resetJointState(rid, j, v)
            for k, v in fr.get("m", {}).items():
                if int(k) in ids:
                    p.resetBasePositionAndOrientation(ids[int(k)], v[:3], v[3:7])
            # follow G2 smoothly but keep whatever angle and distance the user has dragged the camera to
            if new_cam:
                dist, yaw, pitch, tgt, new_cam = 0.45, 50.0, -25.0, [b[0], b[1], 0.04], False
            else:
                c = p.getDebugVisualizerCamera()
                yaw, pitch, dist = c[8], c[9], c[10]
                tgt = [cam[0] + 0.25 * (b[0] - cam[0]), cam[1] + 0.25 * (b[1] - cam[1]), 0.04]
            cam = tgt
            lines = describe(scene)                         # the overlay rides above G2 so it is never left behind
            for n, line in enumerate(lines):
                pos = [b[0], b[1], 0.20 - 0.02 * n]
                kw = dict(textSize=1.0 if n else 1.3, textColorRGB=[0.05, 0.05, 0.05])
                labels.append(p.addUserDebugText(line, pos, **kw)) if len(labels) <= n else p.addUserDebugText(line, pos, replaceItemUniqueId=labels[n], **kw)
            p.resetDebugVisualizerCamera(cameraDistance=dist, cameraYaw=yaw, cameraPitch=pitch, cameraTargetPosition=tgt)
            if fr.get("end"):
                p.addUserDebugText("FELL" if fr["end"] == "fell" else "episode over", [b[0], b[1], 0.15], textSize=1.6,
                                   textColorRGB=[0.8, 0.1, 0.1] if fr["end"] == "fell" else [0.1, 0.5, 0.1], lifeTime=1.5)
                end_t = time.time()
                q.clear()
    except KeyboardInterrupt:
        pass
    except p.error:                                         # the window was closed while a frame was being drawn
        print("window closed", flush=True)
    finally:
        try:
            os.remove(REQ)                                  # stop the stream
        except OSError:
            pass


if __name__ == "__main__":
    main()
