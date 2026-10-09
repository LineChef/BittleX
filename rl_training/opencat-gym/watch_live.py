"""Watch the training run that is going on RIGHT NOW (user, 2026-10-09: "I want to see the actual run, in progress, not an approximation"). No simulation here: one of
the run's training environments (env 0) streams the episode it is actually simulating (its scene at each reset, then G2's pose and joints every 2 steps), and this
window draws exactly that, joining wherever the run is.

    python watch_live.py              # follow the live episode as it is simulated (training runs about 4-5x faster than real time)
    python watch_live.py --realtime   # play each episode at real speed, then jump to the newest one

`g2watchrun` runs this. The stream is on only while a viewer is open (this script touches trained/live/request every few seconds; the env checks it at each episode
start), so a run nobody watches pays nothing. A run started before 2026-10-09's change has no stream: the window says so and keeps waiting."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
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


def describe(scene):
    hz = ", ".join(f"{k} {v:g}" for k, v in scene["hazards"].items()) or "no hazard"
    return (f"{scene['tag']}  |  episode {scene['ep']}  ({scene['role'] or '-'}: {hz})  |  slope roll/pitch {scene['slope_deg'][0]:+.1f}/{scene['slope_deg'][1]:+.1f} deg"
            + (f"  |  ledge {scene['ledge_mm']:+.0f} mm" if scene.get("ledge_mm") else "") + f"  |  command {scene['cmd_fwd']:.2f} m/s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--realtime", action="store_true", help="play each episode at real speed, then jump to the newest one")
    a = ap.parse_args()
    import pybullet as p
    p.connect(p.GUI)
    p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
    touch()
    last_touch, ep, f, rid, ids, text, jids = time.time(), None, None, None, {}, None, []
    waited, scene, scene_t, scene_m, done_playing, last_draw = time.time(), None, 0.0, None, False, 0.0
    print("watching trained/live (close the window or Ctrl-C to stop)", flush=True)
    try:
        while p.isConnected():
            now = time.time()
            if now - last_touch > 5:
                touch()
                last_touch = now
            if now - scene_t > 0.5:                                # the scene file is read twice a second, only when it changed (it used to be parsed on every loop)
                scene_t = now
                scene_path = os.path.join(LIVE, "scene.json")
                try:
                    m = os.stat(scene_path).st_mtime
                    if m != scene_m:
                        scene, scene_m = json.load(open(scene_path)), m
                except (OSError, ValueError):
                    pass
            # a new episode: switch to it now (live) or once the current one has played out (--realtime)
            if scene is not None and scene["ep"] != ep and (not a.realtime or f is None or done_playing):
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
                    scene_m = None                                 # re-read the scene file
                    scene = None
                    time.sleep(0.3)
                    continue
                ep, jids, rid, ids, f = scene["ep"], scene["joint_ids"], nrid, nids, nf
                if not a.realtime:                                 # live: join near the end of the stream instead of replaying a backlog
                    f.seek(max(0, os.fstat(f.fileno()).st_size - 60000))
                    f.readline()
                text = p.addUserDebugText(describe(scene), [0, 0, 0.25], textSize=1.1, textColorRGB=[0.1, 0.1, 0.1])
                print(describe(scene), flush=True)
                done_playing = False
            if f is None:
                time.sleep(0.2)
                continue
            # read what is there: live mode takes everything new and draws only the newest frame (a viewer that falls behind skips ahead, it never queues up work);
            # --realtime draws every frame at 80 Hz pace
            fr, end = None, None
            for _ in range(1 if a.realtime else 5000):
                line = f.readline()
                if not line or not line.endswith("\n"):
                    if line:
                        f.seek(f.tell() - len(line))
                    break
                try:
                    fr = json.loads(line)
                except ValueError:
                    continue
                end = fr.get("end") or end
            if fr is None:
                if a.realtime and ep is not None and scene is not None and scene["ep"] != ep:
                    done_playing = True                            # the episode ended and a newer one exists
                time.sleep(0.02)
                continue
            if not a.realtime and time.time() - last_draw < 0.05:      # at most 20 drawings a second
                time.sleep(0.02)
                continue
            last_draw = time.time()
            b = fr["b"]
            p.resetBasePositionAndOrientation(rid, b[:3], b[3:7])
            for j, v in zip(jids, fr["j"]):
                p.resetJointState(rid, j, v)
            for k, v in fr.get("m", {}).items():
                if int(k) in ids:
                    p.resetBasePositionAndOrientation(ids[int(k)], v[:3], v[3:7])
            p.resetDebugVisualizerCamera(cameraDistance=0.45, cameraYaw=50, cameraPitch=-25, cameraTargetPosition=[b[0], b[1], 0.04])
            if end:
                p.addUserDebugText("FELL" if end == "fell" else "episode over", [b[0], b[1], 0.15], textSize=1.6,
                                   textColorRGB=[0.8, 0.1, 0.1] if end == "fell" else [0.1, 0.5, 0.1], lifeTime=1.5)
                done_playing = True
            if a.realtime:
                time.sleep(2 / 80.0)                        # 2 control steps per frame, 80 Hz
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
