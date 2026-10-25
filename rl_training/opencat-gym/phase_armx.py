"""ARM1X: the claw policy on the corrected claw world, with a training system that keeps learning (user, 2026-10-25, plan approved).

The world: the armsmall recipe (Petoi's arm walk at its own pace, imitation sharpness 8, roll terms, residual 15 deg) on G2's measured body: 532 g and the claw 1.25 in off
the floor (build_limits.json, opencat_gym_env.ARM_LOWER_DZ), step-ups capped at the build's top (15 mm). The training system: the eval on the build's own course
(G2E_EVAL_FR), a hazard trained to its top drops to 5% of its share (G2E_FR_TRAINED_SHARE), and the smoothed plateau rule (G2E_PLATEAU_SMOOTH), log only in the 20M.

    python phase_armx.py run      # ARM1R in this world -> 4 screens -> rule -> S0..S3 -> the full 20M (no plateau stop) -> pick -> export ARM1Xcand -> compare
    python phase_armx.py status

Screens (3M each, fresh): armx_ctrl (the recipe), armx_b512 (PPO batch 512 x 5 epochs), armx_ent (entropy bonus 0.005), armx_rear (back-paw swing clearance 20 mm).
Rule (set before the results): see adopt(). Log trained/phase_armx.log, state trained/armx_state.json, halt trained/armx_halt, reports trained/armx_report/."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, ".")
os.environ["G2_PAYLOAD_PROFILE"] = "arm"                            # before g2_profile builds any environment
import g2_profile
import phase_v4 as P4
import phase_v5 as V5
import run_pipeline as RP

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_armx.log", "trained/armx_halt", "trained/armx_state.json", "trained/armx_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR


def log(msg):
    line = f"[armx {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.log = log
halt, load_state, save_state, clock_in, cm = V5.halt, V5.load_state, V5.save_state, V5.clock_in, V5.cm

ADOPTED = ["cross_bonus", "haz_speed", "haz_posture", "heading_blind"]
BASE6 = V5.BASE + ADOPTED + ["ledge30"]                            # the V7 recipe
ARM_REF = "wkArm"
RESID = "15"
PHYSICS = {"G2E_PHASE_RATE_NOM_CMD": "0.064", "G2E_RESIDUAL_SCALE_DEG": RESID}      # what a scorer needs to run these policies (the mass comes from build_limits.json)
RECIPE = {**PHYSICS, "G2E_SKILL_REF": ARM_REF, "G2E_IMITATION_SHARPNESS": "8", "G2E_FAC_ROLL": "100", "G2E_FAC_ROLL_RATE": "5",
          "G2E_EVAL_FR": "1", "G2E_PLATEAU_SMOOTH": "1", "G2E_FR_TRAINED_SHARE": "0.05", "G2E_HEALTH_WARN_ONLY": "1"}
SCREENS = [   # (tag, extra settings, what)
    ("armx_ctrl", {}, "the recipe on the corrected world (control)"),
    ("armx_b512", {"G2E_PPO_BATCH": "512", "G2E_PPO_EPOCHS": "5"}, "PPO batch 512 x 5 epochs (160 gradient steps per update, was 2,560)"),
    ("armx_ent", {"G2E_PPO_ENT_COEF": "0.005"}, "entropy bonus 0.005"),
    ("armx_rear", {"G2E_FAC_SWING_CLEAR": "30000", "G2E_PAW_Z_REAR": "0.020"}, "back paws at 20 mm in mid-swing (swing clearance 30000)"),
]
SCREEN_MIN, SCORE_EPISODES, SCORE_LADDER_EPISODES = 32, 100, 40
STAGES = [   # (name, lever, steps, minutes estimate)
    ("s0", "v6_s0_flat", "2e6", 15),
    ("s1", "v6_s1_terrain", "3e6", 23),
    ("s2", "v6_s2_ledges", "3e6", 23),
    ("s3", "v6_s3_slopes", "1e6", 9),
]
FINAL = ("s4", "v6_s4_all", "20e6", 160)
TAG = lambda n: f"armx_{n}"                                          # noqa: E731
TRACK_EVERY, TRACK_EPISODES, TRACK_LADDER_EPISODES = 2_000_000, 40, 20
PICK_WINDOW = 5
CAND_ONNX = "trained/ARM1Xcand_ppo.onnx"


def clean_environ(extra=None, resid=RESID):
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    phys = {**PHYSICS, "G2E_RESIDUAL_SCALE_DEG": resid}
    os.environ.update({**RECIPE, **phys, **(extra or {})})
    os.environ["G2E_SCORE_OVERRIDES"] = ",".join(f"{k}={v}" for k, v in phys.items())   # the scorers' profile (ladder workers included) takes the policy's physics


def score(policy, episodes=SCORE_EPISODES, ladder_episodes=SCORE_LADDER_EPISODES, resid=RESID):
    clean_environ(resid=resid)
    return V5.score(policy, BASE6, episodes, ladder_episodes)


def flat_falls(res):
    c = cm(res)
    return max(c[i]["fell_fraction"] for i in ("T1.1", "N1"))


def ladder(res):
    s = res["size_ladder"]["summary"]
    return dict(falls=float(np.mean([v["mean_falls"] for v in s.values()])), success=float(np.mean([np.mean(v["success"]) for v in s.values()])),
                stepup=float(np.mean(s["ledge_up"]["success"])) if "ledge_up" in s else 0.0)


def reach(res):
    c = cm(res)["N1"]
    return dict(front=max(c["joint_hi_deg"][0], c["joint_hi_deg"][2]), back=max(c["joint_hi_deg"][4], c["joint_hi_deg"][6]), roll=c["roll_std_deg"],
                speed=c["path_speed_mps"], heading=c["heading_abs_mean_deg"])


def clip_fraction(tag):
    """Mean PPO clip fraction over the run's last 20 updates (its console log)."""
    vals = [float(m.group(1)) for m in re.finditer(r"clip_fraction\s*\|\s*([0-9.]+)", open(f"trained/{tag}_console.log").read())]
    return float(np.mean(vals[-20:])) if vals else float("nan")


def line(name, res):
    r, l = reach(res), ladder(res)
    beyond = res["size_ladder"].get("beyond", {})
    b = " | beyond the build: " + ", ".join(f"{h} {v['size'] * 1000:.0f} mm falls {v['falls']:.2f} success {v['success']:.2f}" for h, v in beyond.items()) if beyond else ""
    return (f"{name} | flat falls {flat_falls(res):.2f} | N1 speed {r['speed']:.3f} roll {r['roll']:.1f} heading {r['heading']:.0f} front {r['front']:.0f} back {r['back']:.0f} | "
            f"ladder falls {l['falls']:.3f} success {l['success']:.2f} step-up success {l['stepup']:.2f}{b}")


# ------------------------------------------------------------------------------------------------ the old policy in this world, the screens and the rule
def baseline(st):
    f = f"{REPORT_DIR}/arm1r_532g.json"
    if not os.path.exists(f):
        os.makedirs(REPORT_DIR, exist_ok=True)
        log(f"BASELINE: ARM1R (trained/armr_s4_ppo, residual 30) in the corrected world, about 9 min, done about {clock_in(9)}")
        json.dump(score("trained/armr_s4_ppo", resid="30"), open(f, "w"), indent=1)
        log(line("ARM1R (532 g, claw 1.25 in)", json.load(open(f))))


def screen(tag, extra, what):
    out = f"{REPORT_DIR}/{tag}.json"
    if os.path.exists(out):
        return json.load(open(out))
    if not os.path.exists(f"trained/{tag}_ppo.zip"):
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_console.log"):
                halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
            clean_environ(extra)
            log(f"{tag} START: {what}, 3M, about {SCREEN_MIN} min with scoring, done about {clock_in(SCREEN_MIN)}")
            RP.launch(tag, P4.job_env(tag, BASE6, 42, extra={**RECIPE, **extra}), steps=V5.SCREEN_STEPS, base=False)
        ok, why = RP.wait_for_finish(tag)
        if not ok:
            halt(f"HALT: {tag} did not finish: {why}")
    t0 = time.time()
    res = score(f"trained/{tag}_ppo")
    res["clip_fraction"] = clip_fraction(tag)
    json.dump(res, open(out, "w"), indent=1)
    log(f"{tag} SCORED in {(time.time() - t0) / 60:.0f} min, clip fraction {res['clip_fraction']:.2f} | " + line(tag, res))
    return res


def adopt(res):
    """The rule (set before the results, 2026-10-25). Every candidate keeps flat-ground falls at 0 and its mean ladder falls within 0.02 of the control's, and then:
      b512: ladder success at least the control's + 0.02, or the same (within 0.02) with the clip fraction at least 0.05 lower
      ent:  ladder success at least the control's + 0.02
      rear: step-up success at least the control's + 0.10, roll no more than the control's + 0.5 deg, front shoulders no more than 55 deg
    The adopted settings go into the chain together."""
    c = res["armx_ctrl"]
    lc, rc = ladder(c), reach(c)
    out, notes = {}, []
    for tag, extra, _ in SCREENS[1:]:
        r = res[tag]
        l, rr = ladder(r), reach(r)
        base = flat_falls(r) == 0 and l["falls"] <= lc["falls"] + 0.02
        if tag == "armx_b512":
            ok = base and (l["success"] >= lc["success"] + 0.02 or (abs(l["success"] - lc["success"]) <= 0.02 and r["clip_fraction"] <= c["clip_fraction"] - 0.05))
        elif tag == "armx_ent":
            ok = base and l["success"] >= lc["success"] + 0.02
        else:
            ok = base and l["stepup"] >= lc["stepup"] + 0.10 and rr["roll"] <= rc["roll"] + 0.5 and rr["front"] <= 55
        notes.append(f"{tag} {'ADOPTED' if ok else 'not adopted'} (ladder falls {l['falls']:.3f} vs {lc['falls']:.3f}, success {l['success']:.2f} vs {lc['success']:.2f}, "
                     f"step-up {l['stepup']:.2f} vs {lc['stepup']:.2f}, roll {rr['roll']:.1f} vs {rc['roll']:.1f}, clip {r['clip_fraction']:.2f} vs {c['clip_fraction']:.2f})")
        if ok:
            out.update(extra)
    return out, notes


def screens(st):
    if "chain_extra" in st:
        return
    res = {tag: screen(tag, extra, what) for tag, extra, what in SCREENS}
    st["chain_extra"], notes = adopt(res)
    for n in notes:
        log(f"RULE: {n}")
    log(f"RULE: the chain trains with {st['chain_extra'] or 'the recipe alone'}")
    save_state(st)


# ------------------------------------------------------------------------------------------------ the chain
def stage_env(name, lever, st, last=False):
    env = g2_profile.env_for_job({"kind": "final", "tag": TAG(name), "fresh": True, "levers": list(BASE6) + [lever], "extra": {**RECIPE, **st["chain_extra"]}})
    env["G2E_SEED"] = "42"
    env.pop("G2E_PLATEAU_STOP", None)                              # no stage stops on a plateau (user, 2026-10-25: learn across the whole 20M); the smoothed rule only logs
    return {k: v for k, v in env.items() if v != ""}


def run_stage(name, lever, steps, minutes, prev, st):
    tag = TAG(name)
    if os.path.exists(f"trained/{tag}_ppo.zip"):
        return
    if not RP.training(tag):
        if os.path.exists(f"trained/{tag}_console.log"):
            halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
        clean_environ(st["chain_extra"])
        log(f"{tag} START: {lever}, {steps} steps{' from ' + prev if prev else ' (fresh)'}, about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, stage_env(name, lever, st), steps=steps, base=False, chain_from=(f"trained/{prev}_ppo" if prev else None))
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: {tag} did not finish: {why}")
    log(f"{tag} DONE")


def track(step):
    tag = TAG(FINAL[0])
    ck = f"trained/checkpoints/{tag}_{step}_steps"
    out = f"trained/.armx_track_{step}.json"
    ol = tuple(V5.obs_levers(BASE6))
    clean_environ()
    cmd = [sys.executable, "-c",
           "import sys, json; sys.path.insert(0, '.'); import benchmark_v4 as V, benchmark_v5 as B; "
           f"r = V.run({ck!r}, 'T1.1,N1', {TRACK_EPISODES}, 1000, 3, None, {ol!r}, None, mirror_gap=False, quiet=True); "
           f"r['size_ladder'] = B.run_ladder({ck!r}, {ol!r}, {TRACK_LADDER_EPISODES}, jobs=3, hazards=['ledge_up', 'ledge_down', 'rubble', 'sidehill_l', 'sidehill_r'], quiet=True); "
           f"json.dump(r, open({out!r}, 'w'))"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ))
    if r.returncode != 0 or not os.path.exists(out):
        log(f"{tag} tracker {step // 10**6}M failed (the run continues): {(r.stdout + r.stderr)[-300:]}")
        return
    res = json.load(open(out))
    os.remove(out)
    c, s = cm(res)["N1"], res["size_ladder"]["summary"]
    row = dict(step=step, roll=c["roll_std_deg"], heading=c["heading_abs_mean_deg"], speed=c["path_speed_mps"], front=max(c["joint_hi_deg"][0], c["joint_hi_deg"][2]),
               **{f"{h}_falls": v["mean_falls"] for h, v in s.items()}, **{f"{h}_success": float(np.mean(v["success"])) for h, v in s.items()}, t=time.time())
    with open(f"trained/{tag}_curve.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    fr = {}
    try:
        fr = json.load(open(f"trained/{tag}_frontier.json"))
    except (OSError, ValueError):
        pass
    states = ", ".join(f"{h} {'trained' if fr.get('trained', {}).get(h) else 'stuck' if fr.get('stuck', {}).get(h) else 'F' + str(fr.get('F', {}).get(h))}" for h in fr.get("F", {}))
    log(f"{tag} TRACK {step // 10**6}M | N1 roll {row['roll']:.1f} heading {row['heading']:.0f} speed {row['speed']:.3f} front {row['front']:.0f} | "
        + " | ".join(f"{h} falls {v['mean_falls']:.2f} success {np.mean(v['success']):.2f}" for h, v in s.items()) + (f" | frontier: {states}" if states else ""))


def final(st):
    name, lever, steps, minutes = FINAL
    tag = TAG(name)
    if st.get("final") == "done":
        return
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        if os.path.exists(f"trained/{tag}_console.log"):
            halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
        clean_environ(st["chain_extra"])
        log(f"{tag} START: the full 20M from {TAG('s3')} (no plateau stop; the smoothed rule logs only), about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, stage_env(name, lever, st, last=True), steps=steps, base=False, chain_from=f"trained/{TAG('s3')}_ppo")
    done, step = set(st.get("tracked", [])), TRACK_EVERY
    while step <= 20_000_000:
        if os.path.exists(f"trained/{tag}_ppo.zip") and not os.path.exists(RP.ckpt(tag, step)):
            break
        if step not in done:
            ok, why = RP.wait_for_ckpt(tag, step)
            if not ok:
                if os.path.exists(f"trained/{tag}_ppo.zip"):
                    break
                halt(f"HALT: the 20M stopped before {step // 10**6}M: {why}")
            track(step)
            done.add(step)
            st["tracked"] = sorted(done)
            save_state(st)
        step += TRACK_EVERY
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: the 20M did not finish: {why}")
    st["final"] = "done"
    save_state(st)
    log(f"{tag} FINISHED")


def pick(st):
    if st.get("picked"):
        return
    tag = TAG(FINAL[0])
    cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
    cands = [("final", f"trained/{tag}_ppo")]
    if len(cks) >= PICK_WINDOW:
        ok, out = V5.average_checkpoints([c[:-4] for c in cks[-PICK_WINDOW:]], f"trained/{tag}_avg{PICK_WINDOW}_ppo")
        if ok:
            cands.append((f"avg{PICK_WINDOW}", f"trained/{tag}_avg{PICK_WINDOW}_ppo"))
    scored = {}
    for key, path in cands:
        f = f"{REPORT_DIR}/{key}.json"
        if not os.path.exists(f):
            log(f"PICK: scoring {key} in full, about 9 min, done about {clock_in(9)}")
            json.dump(score(path), open(f, "w"), indent=1)
        scored[key] = json.load(open(f))
        log("PICK: " + line(key, scored[key]))
    best = min(scored, key=lambda k: (flat_falls(scored[k]) > 0, ladder(scored[k])["falls"]))
    path = dict(cands)[best]
    log(f"PICK: {best} chosen (flat-ground falls {flat_falls(scored[best]):.2f}, ladder falls {ladder(scored[best])['falls']:.3f})")
    side = {"levers": [l for l in V5.obs_levers(BASE6) if l != "privileged_critic"], "payload_profile": "arm", "base_ref": ARM_REF,
            "gait": "ARM1X: Petoi's arm walk held close and level, claw world as measured (532 g, claw 1.25 in), stock legs", "phase_rate_nom_cmd": float(PHYSICS["G2E_PHASE_RATE_NOM_CMD"])}
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", CAND_ONNX, "--residual-scale-deg", RESID, "--cmd-send-every-n", "3", "--heading-blind",
                        "--sidecar-extra", json.dumps(side)], capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log(f"EXPORTED {CAND_ONNX} (+ .onnx.json, residual {RESID} deg, base_ref {ARM_REF}, phase_rate_nom_cmd {PHYSICS['G2E_PHASE_RATE_NOM_CMD']}); not promoted, not deployed")
    shutil.copy(f"{REPORT_DIR}/{best}.json", f"{REPORT_DIR}/arm1x.json")
    st["picked"], st["picked_path"] = best, path
    save_state(st)


def compare(st):
    """No gate: ARM1X next to ARM1R and Petoi's scripted arm walk, all three in the corrected world."""
    if st.get("verdict"):
        return
    f = f"{REPORT_DIR}/scripted_wkarm.json"
    if not os.path.exists(f):
        log(f"COMPARE: scoring Petoi's scripted arm walk in the corrected world, about 9 min, done about {clock_in(9)}")
        clean_environ()
        json.dump(V5.score("scripted", [], SCORE_EPISODES, SCORE_LADDER_EPISODES), open(f, "w"), indent=1)
    for name, path in (("ARM1X", "arm1x.json"), ("ARM1R", "arm1r_532g.json"), ("scripted", "scripted_wkarm.json")):
        log("COMPARE " + line(name, json.load(open(f"{REPORT_DIR}/{path}"))))
    st["verdict"] = "reported"
    save_state(st)


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    st = load_state()
    baseline(st)
    screens(st)
    prev = None
    for name, lever, steps, minutes in STAGES:
        run_stage(name, lever, steps, minutes, prev, st)
        prev = TAG(name)
    final(st)
    pick(st)
    compare(st)
    log("ARM1X COMPLETE")


def status():
    st = load_state()
    for tag, _, what in SCREENS:
        print(f"  {tag:10s}", "scored" if os.path.exists(f"{REPORT_DIR}/{tag}.json") else ("training" if RP.training(tag) else "-"), "|", what)
    print("  adopted:", st.get("chain_extra", "-"))
    for name, lever, steps, _ in STAGES + [FINAL]:
        print(f"  {name} {lever:14s} {steps}:", "done" if os.path.exists(f"trained/{TAG(name)}_ppo.zip") else ("training" if RP.training(TAG(name)) else "-"))
    print("  tracked", [t // 10**6 for t in st.get("tracked", [])], "| picked:", st.get("picked", "-"), "| verdict:", st.get("verdict", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "status": status}[cmd]()
