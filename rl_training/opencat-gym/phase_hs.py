"""The high-step creep training plan, unattended end to end (user-approved 2026-10-12; plan, rules and resume steps: docs/plan-detail/high-step-creep-training-plan.md).

    python phase_hs.py run        # V6 baseline -> base sweep -> base check -> preflight -> S0 -> S1 -> S2 -> go/no-go -> S4 20M (trackers) -> pick -> export -> report
    python phase_hs.py status | plan
    nohup bash ../../tools/hs_watchdog.sh > /dev/null 2>&1 &      # keeps `run` alive; stops on trained/hs_halt or "HS COMPLETE"

A separate policy (not V6, not trained on top of anything): a fresh chain from S0 on the creep base (reference_gait/creep_ref.npy, picked by creep_sweep.py), step-ups only,
no step-downs, no slopes. Every stage after S0 starts from the previous stage's final weights with a fresh-run learning-rate schedule (train.py --chain-from), as V6's chain did.
Scoring is hs_probe.py (calm flat walk + a step-up ladder judged foot by foot). Every judgement call is Claude's (user, 2026-10-12: "make decisions when needed and document
them"), written to trained/hs_report/decisions.md; deployment is the user's. Log trained/phase_hs.log, state trained/hs_state.json, halt trained/hs_halt.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, ".")
import g2_profile           # noqa: E402
import phase_v5 as V5       # noqa: E402
import run_pipeline as RP   # noqa: E402

LOG, HALT, STATE, REPORT_DIR = "trained/phase_hs.log", "trained/hs_halt", "trained/hs_state.json", "trained/hs_report"
DECISIONS = f"{REPORT_DIR}/decisions.md"
HS_BASE = V5.BASE + ["cross_bonus", "haz_speed", "haz_posture", "heading_blind", "ledge30", "hs_creep"]
SCORE_LEVERS = "hs_creep,privileged_critic,heading_blind"
STAGES = [   # (name, lever, steps, minutes estimate incl. scoring)
    ("s0", "hs_s0_flat", "2e6", 20),
    ("s1", "hs_s1_low", "3e6", 30),
    ("s2", "hs_s2_tall", "3e6", 30),
]
FINAL = ("s4", "hs_s4_all", "20e6", 141)
TAG = lambda n: f"hs_{n}"                                          # noqa: E731
V6_POLICY = "trained/v6_s4_avg5_ppo"
LADDER = "0.0075,0.010,0.0125,0.015,0.0175,0.020,0.025"
TRACK_LADDER = "0.010,0.0125,0.015,0.020"
CMD, NOM = 0.035, 0.035
PICK_WINDOW = 5
CAND_ONNX = "trained/HS1cand_ppo.onnx"
SIDECAR_EXTRA = {"modes": ["hi_step"], "base_ref": "creep", "phase_rate_nom_cmd": NOM, "cmd_fwd_range": [0.028, 0.045], "gait": "high-step creep (three feet down)"}
# gates (plan section 5)
FLAT_FALLS_MAX = 0.05
MIN_SPEED = 0.025
BODY_SLACK_MM = 1.0           # body height at least V6's minus this
REAR_KNEE_SLACK = 5.0         # mean rear knee at least V6's minus this
TRACK_EVERY = 2_000_000
SAFETY_CHECKS = (4_000_000, 6_000_000, 10_000_000)
SAFETY_FLAT_FALLS = 0.25
# success criteria (plan section 6, set before any result): 80% success at 12.5 mm (minimum), 15 mm (target), 60% at 20 mm (stretch)
CRIT_MIN_MM, CRIT_TARGET_MM, CRIT_STRETCH_MM, CRIT_STRETCH_SUCCESS = 12.5, 15.0, 20.0, 0.6


def log(msg):
    line = f"[hs {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def decision(msg):
    os.makedirs(REPORT_DIR, exist_ok=True)
    log("DECISION " + msg)
    with open(DECISIONS, "a") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %I:%M %p')}: {msg}\n")


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def save_state(st):
    json.dump(st, open(STATE, "w"), indent=1)


def halt(msg):
    open(HALT, "w").write(msg + "\n")
    log(msg)
    raise SystemExit(1)


def clock_in(minutes):
    return time.strftime("%I:%M %p", time.localtime(time.time() + 60 * minutes))


def clean_environ():
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]


def probe(policy, out, levers=SCORE_LEVERS, cmd=CMD, flat=20, ladder=LADDER, ledge_eps=20, jobs=8, ref="", nom=None):
    """hs_probe.py in a fresh process; returns its JSON (cached in `out`)."""
    if os.path.exists(out):
        return json.load(open(out))
    cmd_ = [sys.executable, "hs_probe.py", "--policy", policy, "--levers", levers, "--cmd", str(cmd), "--flat-episodes", str(flat), "--ledges", ladder,
            "--ledge-episodes", str(ledge_eps), "--jobs", str(jobs), "--json-out", out]
    if ref:
        cmd_ += ["--ref", ref]
    if nom:
        cmd_ += ["--nom-cmd", str(nom)]
    clean_environ()
    r = subprocess.run(cmd_, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        halt(f"HALT: scoring {policy} failed: {(r.stdout + r.stderr)[-600:]}")
    return json.load(open(out))


def line(res):
    import hs_probe
    return hs_probe.line(res)


def ledge_at(res, mm):
    return next((L for L in res["ledges"] if abs(L["size_mm"] - mm) < 1e-6), None)


def v6(st):
    return json.load(open(f"{REPORT_DIR}/v6_baseline.json"))


# ------------------------------------------------------------------------------------------------ steps
def v6_baseline(st):
    out = f"{REPORT_DIR}/v6_baseline.json"
    if os.path.exists(out):
        return
    os.makedirs(REPORT_DIR, exist_ok=True)
    log(f"V6 BASELINE: V6 (the deployed walk) on the same flat walk and step-up ladder at its own speed (0.10 m/s), about 4 min, done about {clock_in(4)}")
    res = probe(V6_POLICY, out, levers="privileged_critic,heading_blind", cmd=0.10, flat=20, ledge_eps=40)
    log(f"V6 BASELINE | {line(res)}")


def sweep(st):
    if st.get("sweep") == "done" and os.path.exists("reference_gait/creep_ref.npy"):
        return
    log(f"BASE SWEEP: 36 creep candidates open loop on flat ground, then the best 4 on step-ups (creep_sweep.py), about 10 min, done about {clock_in(10)}")
    clean_environ()
    r = subprocess.run([sys.executable, "creep_sweep.py", "--v6-flat", f"{REPORT_DIR}/v6_baseline.json", "--out", f"{REPORT_DIR}/sweep.json"], capture_output=True, text=True)
    open(f"{REPORT_DIR}/sweep.log", "w").write(r.stdout + r.stderr)
    if r.returncode == 2:
        halt("DECISION NEEDED / HALT: no creep candidate passed the flat-ground gates (no falls, rear lift 3x V6, body and rear knee at V6's): see trained/hs_report/sweep.log. "
             "The gates are not loosened without a review.")
    if r.returncode != 0:
        halt(f"HALT: creep_sweep.py failed: {(r.stdout + r.stderr)[-600:]}")
    w = json.load(open(f"{REPORT_DIR}/sweep.json"))["winner"]
    decision(f"Base gait chosen by the sweep: {w['params']} (step-up score {w['ledge_score']:.3f}, rear paw lift {w['flat']['rear_lift_mm']:.1f} mm, body {w['flat']['body_mm']:.1f} mm, "
             f"open-loop flat falls {w['flat']['falls']:.2f}). Rule set before the sweep: pass the flat gates, then the best step-up score among the 4 highest rear lifts.")
    shutil.copy("reference_gait/creep_ref.npy", "../../pi_pipeline/gait/creep_ref.npy")        # the Pi's base (not deployed: rsync is the user's call)
    st["sweep"] = "done"
    save_state(st)


def base_check(st):
    out = f"{REPORT_DIR}/base.json"
    if os.path.exists(out):
        return
    log(f"BASE CHECK: the chosen creep base, open loop, on the full flat walk and ladder (about 3 min, done about {clock_in(3)})")
    res = probe("scripted", out, levers="hs_creep")
    log(f"BASE CHECK | {line(res)}")


def preflight(st):
    if st.get("preflight") == "pass":
        return
    levers = HS_BASE + ["hs_s2_tall"]
    log(f"PREFLIGHT on the creep recipe with the step-up stage (about 15 min, done about {clock_in(15)})")
    clean_environ()
    r = subprocess.run([sys.executable, "preflight.py", "--levers", ",".join(levers)], capture_output=True, text=True)
    open("trained/hs_preflight.log", "w").write(r.stdout + r.stderr)
    if "ALL PASS" not in r.stdout:
        halt(f"HALT: preflight FAILED (trained/hs_preflight.log): {[l for l in r.stdout.splitlines() if 'FAIL' in l][:6]}")
    st["preflight"] = "pass"
    save_state(st)
    log("PREFLIGHT ALL PASS")


def stage_env(tag, lever, seed=42, last=False):
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(HS_BASE) + [lever]})
    env["G2E_SEED"] = str(seed)
    if not last:
        env.pop("G2E_PLATEAU_STOP", None)
    return {k: v for k, v in env.items() if v != ""}


def flat_ok(res, base):
    """(ok, reasons): no more than FLAT_FALLS_MAX falls on the calm walk, at least MIN_SPEED, and no crouch (body and rear knee near V6's)."""
    f, b = res["flat"], base["flat"]
    why = []
    if f["falls"] > FLAT_FALLS_MAX:
        why.append(f"flat falls {f['falls']:.2f} > {FLAT_FALLS_MAX}")
    if f["speed"] < MIN_SPEED:
        why.append(f"speed {f['speed']:.3f} < {MIN_SPEED}")
    if f["body_mm"] is not None and f["body_mm"] < b["body_mm"] - BODY_SLACK_MM:
        why.append(f"body {f['body_mm']:.1f} mm < V6's {b['body_mm']:.1f} - {BODY_SLACK_MM}")
    if f["rear_knee_deg"] is not None and f["rear_knee_deg"] < b["rear_knee_deg"] - REAR_KNEE_SLACK:
        why.append(f"rear knee {f['rear_knee_deg']:+.1f} < V6's {b['rear_knee_deg']:+.1f} - {REAR_KNEE_SLACK}")
    return (not why), why


def run_stage(st, name, lever, steps, minutes, prev):
    """Train (resumable) and score one stage; a stage that fails the flat-ground gate is retried ONCE with another seed (my rule, plan section 5); a second failure halts."""
    rec = st.setdefault("stages", {}).setdefault(name, {})
    if rec.get("passed"):
        return rec["path"]
    attempt = rec.get("attempt", 1)
    tag = TAG(name) if attempt == 1 else f"{TAG(name)}r{attempt}"
    seed = 42 if attempt == 1 else 43
    zip_ = f"trained/{tag}_ppo.zip"
    if not os.path.exists(zip_):
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_console.log"):
                halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart the watchdog")
            clean_environ()
            log(f"{tag} START: {lever}, {steps} steps{' from ' + prev if prev else ' (fresh)'}, seed {seed}, about {minutes} min with scoring, done about {clock_in(minutes)}")
            rec["started"] = time.time()
            save_state(st)
            RP.launch(tag, stage_env(tag, lever, seed), steps=steps, base=False, chain_from=prev)
        ok, why = RP.wait_for_finish(tag)
        if not ok:
            halt(f"HALT: {tag} did not finish: {why}")
    rec["finished"] = rec.get("finished") or time.time()
    res = probe(f"trained/{tag}_ppo", f"{REPORT_DIR}/{tag}.json")
    log(f"{tag} SCORED | {line(res)}")
    ok, why = flat_ok(res, v6(st))
    if not ok:
        if attempt == 1:
            decision(f"{tag} failed the flat-ground gate ({'; '.join(why)}): retrying the stage once with seed 43 (rule set before the run).")
            rec["attempt"] = 2
            save_state(st)
            return run_stage(st, name, lever, steps, minutes, prev)
        halt(f"DECISION (mine): {tag} failed the flat-ground gate twice ({'; '.join(why)}); the chain stops before spending the 20M. See {REPORT_DIR}/{tag}.json")
    rec.update(passed=True, path=f"trained/{tag}_ppo", tag=tag)
    save_state(st)
    stage_targets(name, tag, res)
    return rec["path"]


def stage_targets(name, tag, res):
    """The stage's own step-up target, reported (not gating: the 20M keeps training step-ups; only flat-ground safety stops the chain)."""
    want = {"s0": None, "s1": (10.0, 0.6), "s2": (12.5, 0.5)}[name]
    if not want:
        b6 = json.load(open(f"{REPORT_DIR}/v6_baseline.json"))["flat"]
        f = res["flat"]
        decision(f"{tag}: flat walk passes. Rear paw lift {f['rear_lift_mm']:.1f} mm ({f['rear_lift_mm'] / b6['rear_lift_mm']:.1f}x V6), front {f['front_lift_mm']:.1f} mm "
                 f"({f['front_lift_mm'] / b6['front_lift_mm']:.1f}x V6), body {f['body_mm']:.1f} mm, speed {f['speed']:.3f} m/s. Continuing to S1.")
        return
    mm, bar = want
    L = ledge_at(res, mm)
    got = L["success"] if L else 0.0
    decision(f"{tag}: {mm:g} mm step-up success {got:.2f} (stage target {bar}); {'met' if got >= bar else 'NOT met, continuing anyway: the 20M keeps 45% step-ups and only flat-ground safety stops the chain'}.")


def go_no_go(st):
    if st.get("go"):
        return
    s2 = json.load(open(f"{REPORT_DIR}/{st['stages']['s2']['tag']}.json"))
    base = json.load(open(f"{REPORT_DIR}/base.json"))
    ok, why = flat_ok(s2, v6(st))
    if not ok:                     # run_stage already halts on this; kept as the explicit rule
        halt(f"DECISION (mine): NO-GO for the 20M: S2 is not safe on flat ground ({'; '.join(why)})")
    up = lambda r, mm: (ledge_at(r, mm) or {}).get("all_up", 0.0)      # noqa: E731
    decision(f"GO for the 20M (the user approved the 20M; my check is flat-ground safety and posture, both pass). S2 vs the open-loop base: all four paws up at 12.5 mm "
             f"{up(s2, 12.5):.2f} vs {up(base, 12.5):.2f}, at 15 mm {up(s2, 15.0):.2f} vs {up(base, 15.0):.2f}.")
    st["go"] = True
    save_state(st)


def track(tag, step):
    ck = f"trained/checkpoints/{tag}_{step}_steps"
    out = f"trained/.hs_track_{step}.json"
    if os.path.exists(out):
        os.remove(out)
    clean_environ()
    r = subprocess.run([sys.executable, "hs_probe.py", "--policy", ck, "--levers", SCORE_LEVERS, "--cmd", str(CMD), "--flat-episodes", "10", "--ledges", TRACK_LADDER,
                        "--ledge-episodes", "10", "--jobs", "3", "--json-out", out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        log(f"{tag} tracker {step // 10**6}M failed (the run continues): {(r.stdout + r.stderr)[-300:]}")
        return None
    res = json.load(open(out))
    os.remove(out)
    row = dict(step=step, t=time.time(), flat=res["flat"], ledges=res["ledges"])
    with open(f"trained/{tag}_curve.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    log(f"{tag} TRACK {step // 10**6}M | {line(res)}{projected_finish(tag)}")
    return row


def projected_finish(tag):
    try:
        rows = [json.loads(l) for l in open(f"trained/{tag}_curve.jsonl")][-3:]
        if len(rows) < 2:
            return ""
        pace = (rows[-1]["t"] - rows[0]["t"]) / max(rows[-1]["step"] - rows[0]["step"], 1)
        left = float(FINAL[2]) - rows[-1]["step"]
        return f" | training done about {time.strftime('%I:%M %p', time.localtime(time.time() + pace * left))}" if left > 0 else ""
    except (OSError, ValueError, KeyError):
        return ""


def final(st):
    name, lever, steps, minutes = FINAL
    tag = TAG(name)
    if st.get("final") == "done":
        return
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        clean_environ()
        prev = st["stages"]["s2"]["path"]
        log(f"{tag} START: the 20M consolidation from {prev} (plateau stop on), about {minutes} min of training, done about {clock_in(minutes)}; "
            f"pick, scoring and report about 30 min after")
        st["final_started"] = time.time()
        save_state(st)
        RP.launch(tag, stage_env(tag, lever, last=True), steps=steps, base=False, chain_from=prev)
    done, step = set(st.get("tracked", [])), TRACK_EVERY
    while step <= int(float(steps)):
        if os.path.exists(f"trained/{tag}_ppo.zip") and not os.path.exists(RP.ckpt(tag, step)):
            break
        if step in done:
            step += TRACK_EVERY
            continue
        ok, why = RP.wait_for_ckpt(tag, step)
        if not ok:
            if os.path.exists(f"trained/{tag}_ppo.zip"):
                break
            halt(f"HALT: the 20M stopped before {step // 10**6}M: {why}")
        row = track(tag, step)
        if row is not None and step in SAFETY_CHECKS and row["flat"]["falls"] > SAFETY_FLAT_FALLS:
            RP.stop(tag)
            halt(f"DECISION (mine): the 20M falls on flat ground at {step // 10**6}M ({row['flat']['falls']:.2f} of calm walks); stopped for review")
        done.add(step)
        st["tracked"] = sorted(done)
        save_state(st)
        step += TRACK_EVERY
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: the 20M did not finish: {why}")
    st["final"] = "done"
    st["final_finished"] = time.time()
    save_state(st)
    log(f"{tag} FINISHED")


def pick_key(res):
    """Higher is better: safe on flat ground first, then the 80% step-up ceiling, then the mean success over the ladder, then fewer flat falls."""
    ok, _ = flat_ok(res, json.load(open(f"{REPORT_DIR}/v6_baseline.json")))
    mean = sum(L["success"] for L in res["ledges"]) / max(1, len(res["ledges"]))
    return (ok, res.get("ceiling80_mm", 0.0), mean, -res["flat"]["falls"])


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
        else:
            decision(f"checkpoint averaging failed, only the final policy is scored: {out}")
    scored = {}
    for key, path in cands:
        log(f"PICK: scoring {key} in full (30 flat walks, 40 episodes per step-up size; about 6 min, done about {clock_in(6)})")
        scored[key] = probe(path, f"{REPORT_DIR}/pick_{key}.json", flat=30, ledge_eps=40)
        log(f"PICK: {key} | {line(scored[key])}")
    best = max(scored, key=lambda k: pick_key(scored[k]))
    path = dict(cands)[best]
    decision(f"PICK: {best} ({path}) chosen. Rule set before the result: safe on flat ground first, then the highest 80% step-up ceiling, then the mean ladder success, then fewer flat falls. "
             + " | ".join(f"{k}: ceiling {scored[k].get('ceiling80_mm', 0):g} mm, flat falls {scored[k]['flat']['falls']:.2f}" for k in scored))
    clean_environ()
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", CAND_ONNX, "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind",
                        "--sidecar-extra", json.dumps(SIDECAR_EXTRA)], capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log(f"EXPORTED {CAND_ONNX} (+ .onnx.json with modes [hi_step], base_ref creep); not promoted, not deployed (the user decides)")
    shutil.copy(f"{REPORT_DIR}/pick_{best}.json", f"{REPORT_DIR}/final.json")
    st["picked"] = best
    st["picked_path"] = path
    save_state(st)


def verdict(res, v6res):
    """The success criteria set before the run (plan section 6)."""
    f, b = res["flat"], v6res["flat"]
    s = {L["size_mm"]: L["success"] for L in res["ledges"]}
    ok_flat, why_flat = flat_ok(res, v6res)
    crit = [
        ("Minimum: 80% success at 12.5 mm (0.49 in)", s.get(CRIT_MIN_MM, 0) >= 0.8, f"{s.get(CRIT_MIN_MM, 0):.2f}"),
        ("Target: 80% success at 15 mm (0.59 in)", s.get(CRIT_TARGET_MM, 0) >= 0.8, f"{s.get(CRIT_TARGET_MM, 0):.2f}"),
        ("Stretch: 60% success at 20 mm (0.79 in)", s.get(CRIT_STRETCH_MM, 0) >= CRIT_STRETCH_SUCCESS, f"{s.get(CRIT_STRETCH_MM, 0):.2f}"),
        ("Flat ground: at most 5% falls, at least 0.025 m/s, no crouch", ok_flat, f"falls {f['falls']:.2f}, speed {f['speed']:.3f}" + (f" ({'; '.join(why_flat)})" if why_flat else "")),
        ("Clearance: rear paw lift at least 3x V6's", (f["rear_lift_mm"] or 0) >= 3 * b["rear_lift_mm"], f"{(f['rear_lift_mm'] or 0) / b['rear_lift_mm']:.1f}x"),
        ("Clearance: front paw lift above V6's", (f["front_lift_mm"] or 0) > b["front_lift_mm"], f"{(f['front_lift_mm'] or 0) / b['front_lift_mm']:.2f}x"),
        ("Higher than V6: 80% ceiling above V6's", res.get("ceiling80_mm", 0) > v6res.get("ceiling80_mm", 0), f"{res.get('ceiling80_mm', 0):g} mm vs V6 {v6res.get('ceiling80_mm', 0):g} mm"),
    ]
    return crit


def report(st):
    if st.get("report") == "done":
        return
    import hs_report
    page = hs_report.build(st)
    open(f"{REPORT_DIR}/report.html", "w").write(page)
    st["report"] = "done"
    save_state(st)
    log(f"REPORT ready: rl_training/opencat-gym/{REPORT_DIR}/report.html (publish it as an Artifact page)")


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    st = load_state()
    st.setdefault("started", time.time())
    save_state(st)
    v6_baseline(st)
    sweep(st)
    base_check(st)
    preflight(st)
    prev = None
    for name, lever, steps, minutes in STAGES:
        prev = run_stage(st, name, lever, steps, minutes, prev)
    go_no_go(st)
    final(st)
    pick(st)
    report(st)
    st["complete"] = time.time()
    save_state(st)
    log("HS COMPLETE")


def status():
    st = load_state()
    print("v6 baseline:", os.path.exists(f"{REPORT_DIR}/v6_baseline.json"), "| sweep:", st.get("sweep", "-"), "| base check:", os.path.exists(f"{REPORT_DIR}/base.json"),
          "| preflight:", st.get("preflight", "-"))
    for name, lever, steps, _ in STAGES:
        rec = st.get("stages", {}).get(name, {})
        print(f"  {name} {lever:11s} {steps}:", "passed" if rec.get("passed") else ("training" if RP.training(TAG(name)) else "-"), f"attempt {rec.get('attempt', 1)}")
    print("go:", st.get("go", "-"), "| s4 (20M):", st.get("final", "-"), "tracked", [t // 10**6 for t in st.get("tracked", [])], "| picked:", st.get("picked", "-"),
          "| report:", st.get("report", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


def plan():
    for name, lever, steps, minutes in STAGES + [FINAL]:
        e = stage_env(TAG(name), lever, last=(name == FINAL[0]))
        print(f"{name}: {steps} steps, about {minutes} min, {'fresh' if name == 's0' else 'chained'}; " + ", ".join(f"{k.replace('G2E_', '')}={e[k]}" for k in
              ("G2E_SKILL_REF", "G2E_PHASE_RATE_NOM_CMD", "G2E_CMD_BANDS", "G2E_FR_ANCHOR", "G2E_FR_SHARE_SET", "G2E_FR_BOUNDS", "G2E_FRONTIER_FLOOR", "G2E_LR_SCALE",
               "G2E_HAZARD_EP_LEN", "G2E_FR_LEDGE_UP_ONLY", "G2E_PLATEAU_STOP") if k in e))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "status": status, "plan": plan}[cmd]()
