"""One clip per hazard: ARM2 (new legs) crossing the hardest size of that hazard it still passes some of the time (user, 2026-11-01), drawn with the real robot body: the env streams the
episode (the live viewer's scene and frames) and watch_live.build draws it, so the clip looks like the viewer. GIFs are never committed (leave them in an untracked folder).
usage (from rl_training/opencat-gym): render_arm2_hazards.py <policy> <out_dir> [--tries 24]
Sizes come from trained/arm2_report/arm2.json (the ladder, 40 episodes a rung): the largest rung with success >= 10%, else the largest with any success. The episode shown is the
first of the tries (same seeds as the ladder's, then further ones) that crosses; the search is reported with each clip so the clip is not mistaken for the typical outcome."""
import json
import multiprocessing as mp
import os
import sys

import numpy as np

HERE = os.getcwd()
sys.path.insert(0, HERE)
LADDER_JSON = "trained/arm2_report/arm2.json"
STRIDE, W, H = 6, 320, 240


def pick_sizes():
    s = json.load(open(LADDER_JSON))["size_ladder"]["summary"]
    out = {}
    for h, v in s.items():
        succ = list(v["success"])
        idx = [i for i, x in enumerate(succ) if x >= 0.10]
        i = max(idx) if idx else (max(i for i, x in enumerate(succ) if x > 0) if any(x > 0 for x in succ) else None)
        if i is not None:
            out[h] = (float(v["sizes"][i]), float(succ[i]), v["label"], v["unit"], v["factor"])
    return out


def worker(job):
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ.update(job["env"])
    sys.path.insert(0, HERE)
    import evaluate_policy
    evaluate_policy.EPISODE_CAP = 10 ** 9
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    import benchmark_v5 as BV
    import pybullet as p
    from benchmark_gaits import _load_learned
    from PIL import Image, ImageDraw, ImageFont
    keep = {k: getattr(E, k) for k in ("RANDOM_TERRAIN", "RUBBLE", "TORQUE_CUTBACK", "ROUGH_TERRAIN", "RANDOM_TERRAIN_MAX_H", "RUBBLE_MAX_H", "RUBBLE_N", "SNAG_OBSTACLE_N") if hasattr(E, k)}
    E.ADAPTIVE_PUSH = False
    env = E.OpenCatGymEnv()
    model = _load_learned(job["policy"])
    h = job["hazard"]
    size = job["size"]
    need = 0.5 * 0.10 * BV.LADDER_STEPS / 80.0

    def setup(seed):
        B._apply({})
        for k, v in keep.items():
            setattr(E, k, v)
        E.EPISODE_LENGTH = BV.LADDER_STEPS
        env.set_command(fwd=0.10, yaw=0.0)
        env.set_forced_hazards({h: size})
        env._reflex_on = False
        np.random.seed(seed)
        if hasattr(model, "reset"):
            model.reset()
        obs, _ = env.reset()
        return obs

    def judge(fell, dist):
        objs = sorted(getattr(env, "_obj_far", []) or [])
        ledge = getattr(env, "_ledge_edge", None)
        ok = (not fell) and dist >= need
        if h in BV.OBJECT_HAZARDS and objs:
            ok = ok and dist - 0.10 > objs[-1]
        if h in BV.LEDGE_HAZARDS and ledge is not None:
            ok = ok and dist - 0.10 > ledge + 0.05
        return ok

    def run(seed, frames=None):
        obs = setup(seed)
        fell, n = False, 0
        while True:
            a, _ = model.predict(obs, deterministic=True)
            obs, r, te, tr, info = env.step(a)
            n += 1
            if frames is not None and n % STRIDE == 1:
                frames.append(snap(n))
            if te or tr:
                fell = bool(te)
                break
        dist = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        return judge(fell, dist), fell, dist, n

    view_yaw = {"sidehill_l": -20, "sidehill_r": -20, "climb": -60, "descent": -60}.get(h, -55)

    def snap(n):
        pos = p.getBasePositionAndOrientation(env.robot_id)[0]
        vm = p.computeViewMatrixFromYawPitchRoll([pos[0] + 0.03, pos[1], pos[2]], 0.42, view_yaw, -22, 0, 2)
        pm = p.computeProjectionMatrixFOV(50, W / H, 0.02, 4.0)
        img = p.getCameraImage(W, H, vm, pm, renderer=p.ER_TINY_RENDERER)[2]
        im = Image.fromarray(np.reshape(np.array(img, dtype=np.uint8), (H, W, 4))[:, :, :3])
        return im

    tries = job["tries"]
    for cand in job["cands"]:                       # hardest candidate first; the first one the policy crosses at all in the tries is the one shown
        size, job["size_text"], job["ladder_success"] = cand
        wins, first = 0, None
        for k in range(tries):
            seed = 5000 + k
            ok, fell, dist, n = run(seed)
            wins += int(ok)
            if ok and first is None:
                first = seed
        if first is not None:
            break
    if first is None:
        return dict(hazard=h, size=size, tries=tries, wins=0, seed=None)
    import shutil
    live = os.path.join(job["out"], h + "_live")
    shutil.rmtree(live, ignore_errors=True)
    os.makedirs(live)
    open(os.path.join(live, "request"), "w").close()
    env.set_live_slot("clip")
    env._live_dir = live                              # the env streams this episode's scene and frames here (the viewer's own data); render_live() draws them with the viewer's code
    ok, fell, dist, n = run(first)
    return dict(hazard=h, size=size, size_text=job["size_text"], ladder_success=job["ladder_success"], tries=tries, wins=wins, seed=first, live=live, seconds=round(n / 80.0, 1))


def render_live(live, out_gif, title, foot, yaw=-55, stride=3):
    """Draw a streamed episode the way the viewer does (watch_live.build: the dressed model with the paws and wide shoulders, the claw and the course), one frame in `stride` of the stream."""
    import pybullet as p
    from PIL import Image, ImageDraw, ImageFont
    import watch_live as WL
    scene = json.load(open(os.path.join(live, "scene.json")))
    frames = [json.loads(l) for l in open(os.path.join(live, scene["frames"]))]
    p.connect(p.DIRECT)
    rid, ids = WL.build(p, scene, None, None)
    jids, pj = WL.joint_ids(p, rid, scene)
    font = ImageFont.load_default(size=13)
    out = []
    for i, fr in enumerate(frames[::stride]):
        b = fr["b"]
        p.resetBasePositionAndOrientation(rid, b[:3], b[3:7])
        for j, v in zip(jids, fr["j"]):
            p.resetJointState(rid, j, v)
        for j, v in zip(pj, fr.get("pj") or ()):
            p.resetJointState(rid, j, v)
        for k, v in fr.get("m", {}).items():
            if int(k) in ids:
                p.resetBasePositionAndOrientation(ids[int(k)], v[:3], v[3:7])
        vm = p.computeViewMatrixFromYawPitchRoll([b[0] + 0.03, b[1], b[2]], 0.42, yaw, -22, 0, 2)
        pm = p.computeProjectionMatrixFOV(50, W / H, 0.02, 4.0)
        img = p.getCameraImage(W, H, vm, pm, renderer=p.ER_TINY_RENDERER)[2]
        im = Image.fromarray(np.reshape(np.array(img, dtype=np.uint8), (H, W, 4))[:, :, :3])
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 21], fill=(20, 26, 23))
        d.text((6, 3), title, fill=(230, 238, 233), font=font)
        d.rectangle([0, H - 20, W, H], fill=(20, 26, 23))
        d.text((6, H - 18), f"ARM2  t = {fr['k'] / 80.0:3.1f} s   {foot}", fill=(150, 214, 178), font=font)
        out.append(im.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    out[0].save(out_gif, save_all=True, append_images=out[1:], duration=int(1000 * 2 * stride / 80), loop=0, optimize=True, disposal=1)
    return len(out), os.path.getsize(out_gif)


def main():
    pol, out = sys.argv[1], sys.argv[2]
    tries = int(sys.argv[sys.argv.index("--tries") + 1]) if "--tries" in sys.argv else 24
    os.environ["G2_PAYLOAD_PROFILE"] = "arm"
    os.environ["G2_BUILD"] = "arm_wide_clpaw"
    import phase_arm2 as A
    import g2_profile
    A.clean_environ()
    env = {k: str(v) for k, v in g2_profile.scoring_env(*A.V5.obs_levers(A.BASE6)).items()}
    env["G2E_FR_SPLIT_SIDE"] = "1"
    env["G2E_SCALE_ALL_HAZARDS"] = "1"
    for k in ("G2E_SKILL_REF", "G2E_PHASE_RATE_NOM_CMD", "G2E_V5_LEDGE_TOP", "G2E_V5_BUILD_TOPS"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    os.makedirs(out, exist_ok=True)
    jobs = []
    S = json.load(open(LADDER_JSON))["size_ladder"]["summary"]
    for h, (size, succ, label, unit, factor) in pick_sizes().items():
        def text(sz):
            if unit in ("mm", "deg"):
                return f"{sz * factor:g} mm" if unit == "mm" else f"{sz * factor:g} deg"
            if h == "snag":
                return f"{10 * (0.4 + 0.6 * sz):.1f} mm high ({10 * (0.4 + 0.6 * sz) / 25.4:.2f} in)"
            return f"{sz:g}x the course's standard size"
        v = S[h]
        order = sorted([(float(sz), float(sc)) for sz, sc in zip(v["sizes"], v["success"]) if sc > 0 and sz <= size + 1e-9], reverse=True)
        cands = [(sz, text(sz), sc) for sz, sc in order]
        jobs.append(dict(policy=pol, env=env, hazard=h, size=size, label=label, size_text=text(size), tries=tries, out=out, ladder_success=succ, cands=cands))
    with mp.get_context("spawn").Pool(min(8, len(jobs))) as pool:
        res = pool.map(worker, jobs)
    for j, r in zip(jobs, res):
        r["label"] = j["label"]
        r.setdefault("size_text", j["size_text"])
        r.setdefault("ladder_success", j["ladder_success"])
    short = {"Snag obstacles (cable-like)": "Snag cord", "Side-hill, left side down": "Side-hill, left down", "Side-hill, right side down": "Side-hill, right down"}
    yaw = {"sidehill_l": -20, "sidehill_r": -20}
    import subprocess
    procs = []
    for r in res:
        if r.get("seed") is None:
            continue
        gif = os.path.join(out, r["hazard"] + ".gif")
        title = f"{short.get(r['label'], r['label'])}: {r['size_text']}"
        foot = f"crossed {r['wins']} of {r['tries']} tries"
        procs.append((r, gif, subprocess.Popen([sys.executable, __file__, "render", r["live"], gif, title, foot, str(yaw.get(r["hazard"], -55))], cwd=HERE)))
    for r, gif, pr in procs:
        pr.wait()
        r["path"], r["bytes"] = gif, (os.path.getsize(gif) if os.path.exists(gif) else None)
    json.dump(res, open(os.path.join(out, "index.json"), "w"), indent=1)
    for r in res:
        print(r["hazard"], r["size_text"], "ladder", r["ladder_success"], "| tries", r["wins"], "/", r["tries"], "| seed", r["seed"], "|", r.get("bytes"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render_live(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], yaw=float(sys.argv[6]))
    else:
        main()
