"""ARM1: Petoi's arm walk (wkArmF) as the base gait, the V7 recipe unchanged, trained on the claw payload (sim profile "arm": the pod with the Petoi robot arm in place of the
AI head; stock shoulders and feet). Plan, rules and results: docs/plan-detail/arm-policy-plan.md (user approved 2026-10-24, the 20M included). A copy of phase_pod.py with its own
tags (arm_*), state, log, report and candidate names; it never promotes or deploys anything.

    python phase_arm.py run       # preflight -> screens armwk / armctl (3M) -> S0 -> S1 -> S2 -> S3 -> flat check -> S4 (20M) -> pick -> export -> score V7 in the claw world -> verdict
    python phase_arm.py status | plan

Every training and scoring environment of this process carries the claw (G2_PAYLOAD_PROFILE=arm, read by g2_profile.payload_world). The arm walk base reaches the trainer and every
scorer through G2E_SKILL_REF=wkArm (reference_gait/wkArm_ref.npy); V7 and the control screen keep wkF. Log trained/phase_arm.log, state trained/arm_state.json, halt trained/arm_halt."""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, ".")
os.environ["G2_PAYLOAD_PROFILE"] = "arm"                            # before g2_profile builds any environment
import g2_profile
import phase_v4 as P4
import phase_v5 as V5
import run_pipeline as RP

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_arm.log", "trained/arm_halt", "trained/arm_state.json", "trained/arm_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR


def log(msg):
    line = f"[arm {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.log = log
halt, load_state, save_state, clock_in, cm = V5.halt, V5.load_state, V5.save_state, V5.clock_in, V5.cm

ADOPTED = ["cross_bonus", "haz_speed", "haz_posture", "heading_blind"]
BASE6 = V5.BASE + ADOPTED + ["ledge30"]                            # the V7 recipe
ARM_REF = "wkArm"
SCREENS = [   # (tag, base walk or None for wkF, what it is)
    ("armwk", ARM_REF, "the arm walk base (the candidate recipe)"),
    ("armctl", None, "today's wkF base (the control)"),
]
SCREEN_MIN = 30
STAGES = [   # (name, lever, steps, minutes estimate)
    ("s0", "v6_s0_flat", "2e6", 14),
    ("s1", "v6_s1_terrain", "3e6", 21),
    ("s2", "v6_s2_ledges", "3e6", 21),
    ("s3", "v6_s3_slopes", "1e6", 8),
]
FINAL = ("s4", "v6_s4_all", "20e6", 145)
TAG = lambda n: f"arm_{n}"                                          # noqa: E731
STAGE_EPISODES, STAGE_LADDER_EPISODES = 40, 20
TRACK_EPISODES, TRACK_LADDER_EPISODES = 40, 20
PICK_WINDOW = 5
V7_ZIP = "trained/pod_s4_ppo"                                       # V7 (Release_CandidateV7_ppo.onnx was exported from it)
CAND_ONNX = "trained/ARM1cand_ppo.onnx"
# Promotion rule (set before the result, user approved 2026-10-24), against V7 in the claw world
RULE_FALLS_MARGIN, RULE_HEADING_MARGIN, RULE_HEADING_MAX, RULE_SPEED_RATIO = 0.03, 5.0, 20.0, 0.70


def base_of(st):
    """The base walk the chain trains on (the screens' verdict); None = wkF."""
    return st.get("base", ARM_REF)


def set_base(ref):
    """Put the base walk in this process's environment (the trainer, the trackers and the scorers all read G2E_SKILL_REF from it)."""
    os.environ.pop("G2E_SKILL_REF", None)
    if ref:
        os.environ["G2E_SKILL_REF"] = ref


def clean_environ(ref):
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    set_base(ref)


def score(policy, ref, episodes, ladder_episodes):
    set_base(ref)
    return V5.score(policy, BASE6, episodes, ladder_episodes)


def stage_env(name, lever, ref, last=False):
    env = g2_profile.env_for_job({"kind": "final", "tag": TAG(name), "fresh": True, "levers": list(BASE6) + [lever]})
    env["G2E_SEED"] = "42"
    if ref:
        env["G2E_SKILL_REF"] = ref
    if not last:
        env.pop("G2E_PLATEAU_STOP", None)                          # only the 20M may plateau-stop
    return {k: v for k, v in env.items() if v != ""}


def flat_falls(res):
    c = cm(res)
    return max(c[i]["fell_fraction"] for i in ("T1.1", "N1"))


def mean_cell_falls(res, ids=None):
    c = cm(res)
    ids = ids or [i for i in c if not i.startswith(("Z.", "N")) and i != "Z0"]
    return sum(c[i]["fell_fraction"] for i in ids) / len(ids), ids


# ------------------------------------------------------------------------------------------------ preflight and screens
def preflight(st):
    if st.get("preflight") == "pass":
        return
    clean_environ(ARM_REF)
    levers = BASE6 + ["v6_s2_ledges"]
    log(f"PREFLIGHT on the V7 recipe, claw payload, arm walk base, ledge-stage rewards (about 15 min, done about {clock_in(15)})")
    r = subprocess.run([sys.executable, "preflight.py", "--levers", ",".join(levers), "--env", f"G2E_SKILL_REF={ARM_REF}"], capture_output=True, text=True)
    open("trained/arm_preflight.log", "w").write(r.stdout + r.stderr)
    if "ALL PASS" not in r.stdout:
        halt(f"HALT: preflight FAILED (trained/arm_preflight.log): {[l for l in r.stdout.splitlines() if 'FAIL' in l][:6]}")
    st["preflight"] = "pass"
    save_state(st)
    log("PREFLIGHT ALL PASS")


def screen(tag, ref, what):
    out = f"trained/arm_score_{tag}.json"
    if os.path.exists(out):
        return json.load(open(out))
    if not os.path.exists(f"trained/{tag}_ppo.zip"):
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
                return {"health_stop": True}
            if os.path.exists(f"trained/{tag}_console.log"):
                halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
            clean_environ(ref)
            log(f"{tag} START: {what}, 3M, about {SCREEN_MIN} min, done about {clock_in(SCREEN_MIN)}")
            RP.launch(tag, P4.job_env(tag, BASE6, 42, extra={"G2E_SKILL_REF": ref} if ref else None), steps=V5.SCREEN_STEPS, base=False)
        ok, why = RP.wait_for_finish(tag)
        if not ok:
            if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
                log(f"{tag} HEALTH STOP: it did not learn")
                return {"health_stop": True}
            halt(f"HALT: {tag} did not finish: {why}")
    t0 = time.time()
    res = score(f"trained/{tag}_ppo", ref, V5.SCREEN_EPISODES, V5.SCREEN_LADDER_EPISODES)
    json.dump(res, open(out, "w"), indent=1)
    log(f"{tag} SCORED in {(time.time() - t0) / 60:.0f} min | {V5.summary(res)}")
    return res


def learned(res):
    """Learnable: no health stop, and the calm walk moves (at least a third of the 0.10 m/s command)."""
    return not res.get("health_stop") and cm(res)["N1"]["path_speed_mps"] >= 0.033


def screens(st):
    if "base" in st:
        return
    res = {tag: screen(tag, ref, what) for tag, ref, what in SCREENS}
    wk, ctl = res["armwk"], res["armctl"]
    wk_ok = learned(wk) and (not learned(ctl) or flat_falls(wk) <= flat_falls(ctl))
    if wk_ok:
        st["base"] = ARM_REF
        why = "it learns and falls no more on flat ground than the control"
    elif learned(ctl):
        st["base"] = None
        why = "the arm walk screen failed the gate (learns / flat falls no more than the control); the chain trains on wkF, the control recipe"
    else:
        halt("DECISION NEEDED: neither screen learned on the claw payload; see trained/arm_score_armwk.json and trained/arm_score_armctl.json")
    for tag in res:
        if not res[tag].get("health_stop"):
            log(f"SCREEN {tag}: learned {learned(res[tag])} | flat falls {flat_falls(res[tag]):.2f} | mean cell falls {mean_cell_falls(res[tag])[0]:.3f}")
    log(f"SCREENS: the chain trains on {st['base'] or 'wkF'} ({why})")
    save_state(st)


# ------------------------------------------------------------------------------------------------ the chain (as phase_pod)
def run_stage(name, lever, steps, minutes, prev, ref):
    tag = TAG(name)
    if os.path.exists(f"trained/{tag}_ppo.zip"):
        return
    if not RP.training(tag):
        if os.path.exists(f"trained/{tag}_console.log"):
            halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
        clean_environ(ref)
        log(f"{tag} START: {lever}, {steps} steps{' from ' + prev if prev else ' (fresh)'}, about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, stage_env(name, lever, ref), steps=steps, base=False, chain_from=(f"trained/{prev}_ppo" if prev else None))
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: {tag} did not finish: {why}")


def score_stage(name, ref):
    out = f"trained/arm_score_{name}.json"
    if not os.path.exists(out):
        t0 = time.time()
        res = score(f"trained/{TAG(name)}_ppo", ref, STAGE_EPISODES, STAGE_LADDER_EPISODES)
        json.dump(res, open(out, "w"), indent=1)
        log(f"{TAG(name)} DONE, scored in {(time.time() - t0) / 60:.0f} min | {V5.summary(res)}")


def go_no_go(st):
    """The user approved the 20M (2026-10-24); it starts unless S3 falls on flat ground or its calm-walk heading is over 30 deg."""
    if st.get("go"):
        return
    c = cm(json.load(open("trained/arm_score_s3.json")))
    flat = all(c[i]["fell_fraction"] == 0 for i in ("T1.1", "N1"))
    head, asym = c["N1"]["heading_abs_mean_deg"], c["N1"]["lr_asym_max_deg"]
    log(f"S3 CHECK | flat falls none = {flat} | calm walk heading {head:.0f} asym {asym:.1f}")
    if not flat or head > 30:
        halt(f"DECISION NEEDED: S3 falls on flat ground or its heading is over 30 deg (flat none = {flat}, heading {head:.0f}); review trained/arm_score_s3.json before the 20M")
    st["go"] = True
    save_state(st)
    log("S3 GO: the 20M consolidation starts now (approved by the user)")


def track(step):
    """The 1M tracker (40 episodes, 3 workers) while the 20M trains."""
    tag = TAG(FINAL[0])
    ck = f"trained/checkpoints/{tag}_{step}_steps"
    out = f"trained/.arm_track_{step}.json"
    ol = tuple(V5.obs_levers(BASE6))
    cmd = [sys.executable, "-c",
           "import sys, json; sys.path.insert(0, '.'); import benchmark_v4 as V, benchmark_v5 as B; "
           f"r = V.run({ck!r}, 'T1.1,N1,SL8,SR8,LU15,LD15', {TRACK_EPISODES}, 1000, 3, None, {ol!r}, None, mirror_gap=True, quiet=True); "
           f"r['size_ladder'] = B.run_ladder({ck!r}, {ol!r}, {TRACK_LADDER_EPISODES}, jobs=3, hazards=['ledge_up', 'ledge_down', 'rubble', 'sidehill_l', 'sidehill_r'], quiet=True); "
           f"json.dump(r, open({out!r}, 'w'))"]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "G2E_V5_LEDGE_TOP": V5.LEDGE_TOP})
    if r.returncode != 0 or not os.path.exists(out):
        log(f"{tag} tracker {step // 10**6}M failed (the run continues): {(r.stdout + r.stderr)[-300:]}")
        return None
    res = json.load(open(out))
    os.remove(out)
    c, s = cm(res), res["size_ladder"]["summary"]
    row = dict(step=step, heading=c["N1"]["heading_abs_mean_deg"], asym=c["N1"]["lr_asym_max_deg"], roll=c["N1"]["roll_std_deg"], speed=c["N1"]["path_speed_mps"],
               t11=c["T1.1"]["fell_fraction"], n1=c["N1"]["fell_fraction"], mirror=res.get("mirror_gap"),
               **{f"{h}_falls": s[h]["mean_falls"] for h in s}, **{f"{h}_success": s[h]["success"] for h in s}, t=time.time())
    with open(f"trained/{tag}_curve.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    su, sd = s["ledge_up"], s["ledge_down"]
    log(f"{tag} TRACK {step // 10**6}M | N1 heading {row['heading']:.0f} asym {row['asym']:.1f} roll {row['roll']:.1f} speed {row['speed']:.3f} | step-up falls {su['mean_falls']:.2f} "
        f"success {[round(x, 2) for x in su['success']]} | step-down falls {sd['mean_falls']:.2f} success {[round(x, 2) for x in sd['success']]} | rubble {s['rubble']['mean_falls']:.2f} | "
        f"side-hill L/R {s['sidehill_l']['mean_falls']:.2f}/{s['sidehill_r']['mean_falls']:.2f} | mirror {res.get('mirror_gap') or float('nan'):.3f}{projected_finish(tag)}")
    return row


def projected_finish(tag):
    try:
        rows = [r for r in (json.loads(l) for l in open(f"trained/{tag}_curve.jsonl")) if "t" in r][-4:]
        if len(rows) < 3 or rows[-1]["step"] >= float(FINAL[2]):
            return ""
        pace = (rows[-1]["t"] - rows[0]["t"]) / max(rows[-1]["step"] - rows[0]["step"], 1)
        return f" | training done about {time.strftime('%I:%M %p', time.localtime(time.time() + pace * (float(FINAL[2]) - rows[-1]['step'])))}"
    except (OSError, ValueError, KeyError):
        return ""


def final(st, ref):
    name, lever, steps, minutes = FINAL
    tag = TAG(name)
    if st.get("final") == "done":
        return
    clean_environ(ref)
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        log(f"{tag} START: the 20M consolidation from {TAG('s3')} (plateau stop on), about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, stage_env(name, lever, ref, last=True), steps=steps, base=False, chain_from=f"trained/{TAG('s3')}_ppo")
    done, step = set(st.get("tracked", [])), 1_000_000
    while step <= 20_000_000:
        if os.path.exists(f"trained/{tag}_ppo.zip") and not os.path.exists(RP.ckpt(tag, step)):
            break
        if step in done:
            step += 1_000_000
            continue
        ok, why = RP.wait_for_ckpt(tag, step)
        if not ok:
            if os.path.exists(f"trained/{tag}_ppo.zip"):
                break
            halt(f"HALT: the 20M stopped before {step // 10**6}M: {why}")
        row = track(step)
        if step in V5.FINAL_CHECKS and row is not None and max(row["t11"], row["n1"]) > 0.25:
            RP.stop(tag)
            halt(f"DECISION (mine): the 20M falls on flat ground at {step // 10**6}M (T1.1 {row['t11']:.2f}, N1 {row['n1']:.2f}); stopped for review")
        done.add(step)
        st["tracked"] = sorted(done)
        save_state(st)
        step += 1_000_000
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: the 20M did not finish: {why}")
    st["final"] = "done"
    save_state(st)
    log(f"{tag} FINISHED")


def pick(st, ref):
    import glob
    import re
    if st.get("picked"):
        return
    tag = TAG(FINAL[0])
    cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
    cands = [("final", f"trained/{tag}_ppo")]
    if len(cks) >= PICK_WINDOW:
        ok, out = V5.average_checkpoints([c[:-4] for c in cks[-PICK_WINDOW:]], f"trained/{tag}_avg{PICK_WINDOW}_ppo")
        if ok:
            cands.append((f"avg{PICK_WINDOW}", f"trained/{tag}_avg{PICK_WINDOW}_ppo"))
        else:
            log(f"checkpoint averaging failed (only the final policy is scored): {out}")
    os.makedirs(REPORT_DIR, exist_ok=True)
    scored = {}
    for key, path in cands:
        f = f"{REPORT_DIR}/{key}.json"
        if not os.path.exists(f):
            log(f"PICK: scoring {key} in full ({V5.FINAL_EPISODES} episodes per cell, about 10 min, done about {clock_in(10)})")
            json.dump(score(path, ref, V5.FINAL_EPISODES, V5.FINAL_LADDER_EPISODES), open(f, "w"), indent=1)
        scored[key] = json.load(open(f))
        log(f"PICK: {key} | {V5.summary(scored[key])}")
    flat_ok = {k: flat_falls(r) == 0 for k, r in scored.items()}
    best = min(scored, key=lambda k: (not flat_ok[k], mean_cell_falls(scored[k])[0]))
    path = dict(cands)[best]
    log(f"PICK: {best} chosen (flat-ground falls none = {flat_ok[best]}, mean cell falls {mean_cell_falls(scored[best])[0]:.3f})")
    side = {"levers": [l for l in V5.obs_levers(BASE6) if l != "privileged_critic"], "payload_profile": "arm", "gait": "ARM1: Petoi's arm walk base, claw payload, stock legs"}
    if ref:
        side["base_ref"] = ref
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", CAND_ONNX, "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind",
                        "--sidecar-extra", json.dumps(side)], capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log(f"EXPORTED {CAND_ONNX} (+ .onnx.json, base_ref {ref or 'wkf'}, payload_profile arm); not promoted, not deployed")
    shutil.copy(f"{REPORT_DIR}/{best}.json", f"{REPORT_DIR}/arm1.json")
    st["picked"], st["picked_path"] = best, path
    save_state(st)


# ------------------------------------------------------------------------------------------------ V7 in the claw world, the load ladder, the verdict
def load_ladder(key, path, ref):
    f = f"{REPORT_DIR}/{key}_load.json"
    if os.path.exists(f):
        return json.load(open(f))
    set_base(ref)
    log(f"LOAD LADDER: {key} (about 8 min, done about {clock_in(8)})")
    r = subprocess.run([sys.executable, "benchmark_load.py", "--policy", path, "--levers", ",".join(V5.obs_levers(BASE6)), "--json-out", f], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(f):
        log(f"load ladder for {key} failed (reported, not gated): {(r.stdout + r.stderr)[-300:]}")
        return None
    return json.load(open(f))


def compare(st, ref):
    if st.get("verdict"):
        return
    f = f"{REPORT_DIR}/v7_claw.json"
    if not os.path.exists(f):
        log(f"V7 IN THE CLAW WORLD: scoring {V7_ZIP} on wkF with the claw ({V5.FINAL_EPISODES} episodes per cell, about 10 min, done about {clock_in(10)})")
        json.dump(score(V7_ZIP, None, V5.FINAL_EPISODES, V5.FINAL_LADDER_EPISODES), open(f, "w"), indent=1)
    v7, a1 = json.load(open(f)), json.load(open(f"{REPORT_DIR}/arm1.json"))
    log(f"V7 (claw) | {V5.summary(v7)}")
    log(f"ARM1      | {V5.summary(a1)}")
    load_ladder("arm1", st["picked_path"], ref)
    load_ladder("v7", V7_ZIP, None)
    cv, ca = cm(v7), cm(a1)
    ids = [i for i in cv if i in ca and not i.startswith(("Z.", "N")) and i != "Z0"]
    fa, fv = mean_cell_falls(a1, ids)[0], mean_cell_falls(v7, ids)[0]
    ha, hv = ca["N1"]["heading_abs_mean_deg"], cv["N1"]["heading_abs_mean_deg"]
    sa, sv = ca["N1"]["path_speed_mps"], cv["N1"]["path_speed_mps"]
    checks = {
        "no flat falls": flat_falls(a1) == 0,
        f"mean falls {fa:.3f} <= V7 {fv:.3f} + {RULE_FALLS_MARGIN}": fa <= fv + RULE_FALLS_MARGIN,
        f"heading {ha:.1f} <= V7 {hv:.1f} + {RULE_HEADING_MARGIN:.0f} and < {RULE_HEADING_MAX:.0f}": ha <= hv + RULE_HEADING_MARGIN and ha < RULE_HEADING_MAX,
        f"speed {sa:.3f} >= {RULE_SPEED_RATIO:.0%} of V7 {sv:.3f}": sa >= RULE_SPEED_RATIO * sv,
    }
    for k, v in checks.items():
        log(f"RULE {'PASS' if v else 'FAIL'}: {k}")
    su = lambda r: r["size_ladder"]["summary"]["ledge_up"]["success"]           # noqa: E731
    log(f"REPORTED (not gated): step-up success ARM1 {[round(x, 2) for x in su(a1)]} vs V7 {[round(x, 2) for x in su(v7)]}")
    st["verdict"] = "pass" if all(checks.values()) else "fail"
    st["checks"] = {k: bool(v) for k, v in checks.items()}
    save_state(st)
    log(f"VERDICT: ARM1 {'PASSES' if st['verdict'] == 'pass' else 'FAILS'} the promotion rule (nothing promoted or deployed here)")


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    st = load_state()
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    preflight(st)
    screens(st)
    ref = base_of(st)
    prev = None
    for name, lever, steps, minutes in STAGES:
        run_stage(name, lever, steps, minutes, prev, ref)
        score_stage(name, ref)
        prev = TAG(name)
    go_no_go(st)
    final(st, ref)
    pick(st, ref)
    compare(st, ref)
    log("ARM1 COMPLETE")


def status():
    st = load_state()
    print("preflight:", st.get("preflight", "-"), "| base:", st.get("base", "-") if "base" in st else "- (screens)")
    for tag, _ref, what in SCREENS:
        print(f"  screen {tag}:", "scored" if os.path.exists(f"trained/arm_score_{tag}.json") else ("training" if RP.training(tag) else "-"), f"({what})")
    for name, lever, steps, _ in STAGES:
        print(f"  {name} {lever:14s} {steps}:", "done" if os.path.exists(f"trained/{TAG(name)}_ppo.zip") else ("training" if RP.training(TAG(name)) else "-"))
    print("go:", st.get("go", "-"), "| s4 (20M):", st.get("final", "-"), "tracked", [t // 10**6 for t in st.get("tracked", [])], "| picked:", st.get("picked", "-"),
          "| verdict:", st.get("verdict", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


def plan():
    for tag, ref, what in SCREENS:
        e = P4.job_env(tag, BASE6, 42, extra={"G2E_SKILL_REF": ref} if ref else None)
        print(f"screen {tag}: 3M, {what}; payload {e.get('G2E_PAYLOAD_PROFILE')}, base {e.get('G2E_SKILL_REF', 'wkF')}")
    for name, lever, steps, minutes in STAGES + [FINAL]:
        e = stage_env(name, lever, ARM_REF, last=(name == FINAL[0]))
        print(f"{name}: {steps} steps, about {minutes} min, {'fresh' if name == 's0' else 'chained'}; payload {e.get('G2E_PAYLOAD_PROFILE')}, base {e.get('G2E_SKILL_REF', 'wkF')} (if the screens pick it)")
    print("scoring payload:", g2_profile.scoring_env().get("G2E_PAYLOAD_PROFILE"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "status": status, "plan": plan}[cmd]()
