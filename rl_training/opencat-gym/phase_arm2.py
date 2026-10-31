"""ARM2: the arm build's walking policy for the 0.2 in wide shoulders and CLpaw (user, 2026-10-31, plan approved; docs/plan-detail/arm2-policy-plan.md).

The world: ARM1X's (Petoi's arm walk at its own pace, the armsmall recipe, the claw as measured, PPO batch 512 x 5 and the entropy bonus that ARM1X adopted) on the new
legs: G2_BUILD=arm_wide_clpaw (build_limits.json: the leg servos 0.2 in further out, a hinged CLpaw on every foot with a free pivot, about 553 g, round snag cords capped
at 7 mm, step-ups at 15 mm). The paw grip and the servo strength are NOT varied (user).

    python phase_arm2.py run      # ARM1X + Petoi's walk in this world -> 2 screens -> rule -> S0..S3 -> two 20Ms (seeds 42 and 7) -> pick -> export ARM2cand -> verdict
    python phase_arm2.py status

Screens (3M each, fresh): arm2_ctrl (the recipe), arm2_ev15 (a slope bin counts after 15 outcomes, was 30). Rule (set before the results): adopt(). Both 20Ms start from
arm2_s3 (user, 2026-10-31: a second 20M with a fresh seed). Nothing is promoted or deployed: ARM2 waits until the user says the parts are on G2.
Log trained/phase_arm2.log, state trained/arm2_state.json, halt trained/arm2_halt, reports trained/arm2_report/."""
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
os.environ["G2_BUILD"] = "arm_wide_clpaw"                           # the new legs, for every training and scoring environment of this process (and its children)
import g2_profile
import phase_v4 as P4
import phase_v5 as V5
import run_pipeline as RP

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_arm2.log", "trained/arm2_halt", "trained/arm2_state.json", "trained/arm2_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR


def log(msg):
    line = f"[arm2 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.log = log
halt, load_state, save_state, clock_in, cm = V5.halt, V5.load_state, V5.save_state, V5.clock_in, V5.cm

ADOPTED = ["cross_bonus", "haz_speed", "haz_posture", "heading_blind"]
BASE6 = V5.BASE + ADOPTED + ["ledge30"]                            # the V7 recipe
ARM_REF = "wkArm"
RESID = "15"
PHYSICS = {"G2E_PHASE_RATE_NOM_CMD": "0.064", "G2E_RESIDUAL_SCALE_DEG": RESID}      # what a scorer needs to run these policies (mass, legs and tops come from the build)
RECIPE = {**PHYSICS, "G2E_SKILL_REF": ARM_REF, "G2E_IMITATION_SHARPNESS": "8", "G2E_FAC_ROLL": "100", "G2E_FAC_ROLL_RATE": "5",
          "G2E_EVAL_FR": "1", "G2E_PLATEAU_SMOOTH": "1", "G2E_FR_TRAINED_SHARE": "0.05", "G2E_HEALTH_WARN_ONLY": "1",
          "G2E_PPO_BATCH": "512", "G2E_PPO_EPOCHS": "5", "G2E_PPO_ENT_COEF": "0.005"}            # ARM1X's recipe with what its screens adopted
SCREENS = [   # (tag, extra settings, what)
    ("arm2_ctrl", {}, "the ARM1X recipe on the new legs (control)"),
    ("arm2_ev15", {"G2E_FR_MIN_N_H": "slopes:15"}, "a slope bin counts after 15 outcomes (was 30)"),
]
SLOW = 1.34                                                         # the hinged paws: measured 7.59 against 5.67 min per million steps (2026-10-31)
SCREEN_MIN, SCORE_MIN, SCORE_EPISODES, SCORE_LADDER_EPISODES = 43, 12, 100, 40
STAGES = [   # (name, lever, steps, minutes estimate): ARM1X's real stage times x SLOW
    ("s0", "v6_s0_flat", "2e6", 17),
    ("s1", "v6_s1_terrain", "3e6", 23),
    ("s2", "v6_s2_ledges", "3e6", 23),
    ("s3", "v6_s3_slopes", "1e6", 7),
]
FINALS = [("s4", "42"), ("s4b", "7")]                               # (name, seed): two 20Ms from arm2_s3
FINAL_LEVER, FINAL_STEPS, FINAL_MIN = "v6_s4_all", "20e6", 158      # ARM1X's 20M took 118 min; x SLOW
TAG = lambda n: f"arm2_{n}"                                         # noqa: E731
TRACK_EVERY, TRACK_EPISODES, TRACK_LADDER_EPISODES = 2_000_000, 40, 20
PICK_WINDOW = 5
CAND_ONNX = "trained/ARM2cand_ppo.onnx"
ARM1X = "trained/armx_s4_avg5_ppo"
GRIP = {"pin18": "0.0018", "pin36": "0.0036"}                       # robustness check only (user: the grip is not varied in training): CLpaw trains free


def clean_environ(extra=None, resid=RESID, score_extra=None):
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    phys = {**PHYSICS, "G2E_RESIDUAL_SCALE_DEG": resid, **(score_extra or {})}
    os.environ.update({**RECIPE, **phys, **(extra or {})})
    os.environ["G2E_SCORE_OVERRIDES"] = ",".join(f"{k}={v}" for k, v in phys.items())   # the scorers' profile (ladder workers included) takes the policy's physics


def score(policy, episodes=SCORE_EPISODES, ladder_episodes=SCORE_LADDER_EPISODES, resid=RESID, score_extra=None):
    clean_environ(resid=resid, score_extra=score_extra)
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
    b = " | beyond the build: " + ", ".join(f"{h} {v['size'] * 1000:.0f} falls {v['falls']:.2f} success {v['success']:.2f}" for h, v in beyond.items()) if beyond else ""
    return (f"{name} | flat falls {flat_falls(res):.2f} | N1 speed {r['speed']:.3f} roll {r['roll']:.1f} heading {r['heading']:.0f} front {r['front']:.0f} back {r['back']:.0f} | "
            f"ladder falls {l['falls']:.3f} success {l['success']:.2f} step-up success {l['stepup']:.2f}{b}")


# ------------------------------------------------------------------------------------------------ ARM1X and Petoi's walk on the new legs, the screens and the rule
def baselines(st):
    os.makedirs(REPORT_DIR, exist_ok=True)
    for key, path, what in (("arm1x_newlegs", ARM1X, "ARM1X (stock-leg policy) on the new legs"), ("scripted_newlegs", "scripted", "Petoi's scripted arm walk on the new legs")):
        f = f"{REPORT_DIR}/{key}.json"
        if os.path.exists(f):
            continue
        log(f"BASELINE: {what}, about {SCORE_MIN} min, done about {clock_in(SCORE_MIN)}")
        if path == "scripted":
            clean_environ()
            res = V5.score("scripted", [], SCORE_EPISODES, SCORE_LADDER_EPISODES)
        else:
            res = score(path)
        json.dump(res, open(f, "w"), indent=1)
        log("BASELINE " + line(key, res))


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
    """The rule (set before the results, plan 2026-10-31): arm2_ev15 is adopted if its flat-ground falls are 0, its mean ladder falls are no more than the control's + 0.005,
    its ladder success is no less than the control's - 0.02 and its calm-walk roll is no more than the control's + 0.5 deg."""
    c = res["arm2_ctrl"]
    lc, rc = ladder(c), reach(c)
    out, notes = {}, []
    for tag, extra, _ in SCREENS[1:]:
        r = res[tag]
        l, rr = ladder(r), reach(r)
        ok = flat_falls(r) == 0 and l["falls"] <= lc["falls"] + 0.005 and l["success"] >= lc["success"] - 0.02 and rr["roll"] <= rc["roll"] + 0.5
        notes.append(f"{tag} {'ADOPTED' if ok else 'not adopted'} (flat falls {flat_falls(r):.2f}, ladder falls {l['falls']:.3f} vs {lc['falls']:.3f}, "
                     f"success {l['success']:.2f} vs {lc['success']:.2f}, roll {rr['roll']:.1f} vs {rc['roll']:.1f}, clip {r['clip_fraction']:.2f} vs {c['clip_fraction']:.2f})")
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
def stage_env(name, lever, st, seed="42"):
    env = g2_profile.env_for_job({"kind": "final", "tag": TAG(name), "fresh": True, "levers": list(BASE6) + [lever], "extra": {**RECIPE, **st["chain_extra"]}})
    env["G2E_SEED"] = seed
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


def track(tag, step):
    ck = f"trained/checkpoints/{tag}_{step}_steps"
    out = f"trained/.arm2_track_{step}.json"
    ol = tuple(V5.obs_levers(BASE6))
    clean_environ()
    cmd = [sys.executable, "-c",
           "import sys, json; sys.path.insert(0, '.'); import benchmark_v4 as V, benchmark_v5 as B; "
           f"r = V.run({ck!r}, 'T1.1,N1', {TRACK_EPISODES}, 1000, 3, None, {ol!r}, None, mirror_gap=False, quiet=True); "
           f"r['size_ladder'] = B.run_ladder({ck!r}, {ol!r}, {TRACK_LADDER_EPISODES}, jobs=3, hazards=['ledge_up', 'ledge_down', 'rubble', 'snag', 'sidehill_l', 'sidehill_r'], quiet=True); "
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


def final(name, seed, st):
    tag = TAG(name)
    if st.get(f"final_{name}") == "done":
        return
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        if os.path.exists(f"trained/{tag}_console.log"):
            halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
        clean_environ(st["chain_extra"])
        log(f"{tag} START: a full 20M from {TAG('s3')}, seed {seed} (no plateau stop; the smoothed rule logs only), about {FINAL_MIN} min, done about {clock_in(FINAL_MIN)}")
        RP.launch(tag, stage_env(name, FINAL_LEVER, st, seed=seed), steps=FINAL_STEPS, base=False, chain_from=f"trained/{TAG('s3')}_ppo")
    key = f"tracked_{name}"
    done, step = set(st.get(key, [])), TRACK_EVERY
    while step <= 20_000_000:
        if os.path.exists(f"trained/{tag}_ppo.zip") and not os.path.exists(RP.ckpt(tag, step)):
            break
        if step not in done:
            ok, why = RP.wait_for_ckpt(tag, step)
            if not ok:
                if os.path.exists(f"trained/{tag}_ppo.zip"):
                    break
                halt(f"HALT: {tag} stopped before {step // 10**6}M: {why}")
            track(tag, step)
            done.add(step)
            st[key] = sorted(done)
            save_state(st)
        step += TRACK_EVERY
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: {tag} did not finish: {why}")
    st[f"final_{name}"] = "done"
    save_state(st)
    log(f"{tag} FINISHED")


def pick(st):
    """final and avg5 of each 20M, scored in full; the pick: no flat-ground falls first, then the lowest mean ladder falls."""
    if st.get("picked"):
        return
    cands = []
    for name, _seed in FINALS:
        tag = TAG(name)
        cands.append((f"{name}_final", f"trained/{tag}_ppo"))
        cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
        if len(cks) >= PICK_WINDOW:
            ok, out = V5.average_checkpoints([c[:-4] for c in cks[-PICK_WINDOW:]], f"trained/{tag}_avg{PICK_WINDOW}_ppo")
            if ok:
                cands.append((f"{name}_avg{PICK_WINDOW}", f"trained/{tag}_avg{PICK_WINDOW}_ppo"))
    scored = {}
    for key, path in cands:
        f = f"{REPORT_DIR}/{key}.json"
        if not os.path.exists(f):
            log(f"PICK: scoring {key} in full, about {SCORE_MIN} min, done about {clock_in(SCORE_MIN)}")
            json.dump(score(path), open(f, "w"), indent=1)
        scored[key] = json.load(open(f))
        log("PICK: " + line(key, scored[key]))
    best = min(scored, key=lambda k: (flat_falls(scored[k]) > 0, ladder(scored[k])["falls"]))
    path = dict(cands)[best]
    log(f"PICK: {best} chosen (flat-ground falls {flat_falls(scored[best]):.2f}, ladder falls {ladder(scored[best])['falls']:.3f})")
    side = {"levers": [l for l in V5.obs_levers(BASE6) if l != "privileged_critic"], "payload_profile": "arm", "base_ref": ARM_REF,
            "legs": {"build": "arm_wide_clpaw", "shoulder_widen_mm": 5.08, "paw": "clpaw"},
            "gait": "ARM2: Petoi's arm walk held close and level, claw world as measured, 0.2 in wide shoulders and CLpaw (about 553 g)",
            "phase_rate_nom_cmd": float(PHYSICS["G2E_PHASE_RATE_NOM_CMD"])}
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", CAND_ONNX, "--residual-scale-deg", RESID, "--cmd-send-every-n", "3", "--heading-blind",
                        "--sidecar-extra", json.dumps(side)], capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log(f"EXPORTED {CAND_ONNX} (+ .onnx.json, residual {RESID} deg, base_ref {ARM_REF}, legs arm_wide_clpaw); not promoted, not deployed")
    shutil.copy(f"{REPORT_DIR}/{best}.json", f"{REPORT_DIR}/arm2.json")
    st["picked"], st["picked_path"] = best, path
    save_state(st)


def verdict(st):
    """The promotion rule (plan, set before the results), against ARM1X on the new legs: no flat-ground falls; mean ladder falls no higher; calm-walk roll no more than
    + 0.5 deg; heading no more than + 5 deg and under 20; calm-walk speed at least 90%. Reported only: promotion waits for the user (parts installed). Then the grip check."""
    if st.get("verdict"):
        return
    a, b = json.load(open(f"{REPORT_DIR}/arm2.json")), json.load(open(f"{REPORT_DIR}/arm1x_newlegs.json"))
    la, lb, ra, rb = ladder(a), ladder(b), reach(a), reach(b)
    checks = [("no flat-ground falls", flat_falls(a) == 0, f"{flat_falls(a):.2f}"),
              ("ladder falls no higher", la["falls"] <= lb["falls"], f"{la['falls']:.3f} vs {lb['falls']:.3f}"),
              ("roll within 0.5 deg", ra["roll"] <= rb["roll"] + 0.5, f"{ra['roll']:.1f} vs {rb['roll']:.1f}"),
              ("heading within 5 deg and under 20", ra["heading"] <= rb["heading"] + 5 and ra["heading"] < 20, f"{ra['heading']:.0f} vs {rb['heading']:.0f}"),
              ("speed at least 90%", ra["speed"] >= 0.9 * rb["speed"], f"{ra['speed']:.3f} vs {rb['speed']:.3f}")]
    for n, ok, v in checks:
        log(f"VERDICT: {'PASS' if ok else 'FAIL'} {n} ({v})")
    st["verdict"] = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
    log(f"VERDICT: {st['verdict']} against ARM1X on the new legs (reported only; promotion waits for the user)")
    for name, pin in GRIP.items():
        f = f"{REPORT_DIR}/arm2_{name}.json"
        if not os.path.exists(f):
            log(f"GRIP: ARM2 with the paw pivot at {float(pin) * 1000:.1f} mN.m (trained free), about {SCORE_MIN} min, done about {clock_in(SCORE_MIN)}")
            json.dump(score(st["picked_path"], score_extra={"G2E_PAW_PIN_FRICTION": pin}), open(f, "w"), indent=1)
        log("GRIP " + line(f"ARM2 pivot {float(pin) * 1000:.1f} mN.m", json.load(open(f))))
    for name, path in (("ARM2", "arm2.json"), ("ARM1X on the new legs", "arm1x_newlegs.json"), ("scripted on the new legs", "scripted_newlegs.json")):
        log("COMPARE " + line(name, json.load(open(f"{REPORT_DIR}/{path}"))))
    save_state(st)


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    st = load_state()
    baselines(st)
    screens(st)
    prev = None
    for name, lever, steps, minutes in STAGES:
        run_stage(name, lever, steps, minutes, prev, st)
        prev = TAG(name)
    for name, seed in FINALS:
        final(name, seed, st)
    pick(st)
    verdict(st)
    log("ARM2 COMPLETE")


def status():
    st = load_state()
    for tag, _, what in SCREENS:
        print(f"  {tag:10s}", "scored" if os.path.exists(f"{REPORT_DIR}/{tag}.json") else ("training" if RP.training(tag) else "-"), "|", what)
    print("  adopted:", st.get("chain_extra", "-"))
    for name, lever, steps, _ in STAGES + [(n, FINAL_LEVER, FINAL_STEPS, 0) for n, _ in FINALS]:
        print(f"  {name} {lever:14s} {steps}:", "done" if os.path.exists(f"trained/{TAG(name)}_ppo.zip") else ("training" if RP.training(TAG(name)) else "-"))
    print("  tracked", {n: [t // 10**6 for t in st.get(f"tracked_{n}", [])] for n, _ in FINALS}, "| picked:", st.get("picked", "-"), "| verdict:", st.get("verdict", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "status": status}[cmd]()
