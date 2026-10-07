"""Unattended runner for the V3 gait retrain (docs/rl/v3-retrain-plan.md section 4, phases 3, 4 and 6).

    python phase_v3.py init            # write trained/v3_queue.json with the control + the ten screening rounds (edit it freely)
    python phase_v3.py run             # work through the queue; safe to restart (a job already training or finished is resumed, not redone)
    python phase_v3.py status          # the results so far, one line per job

Every state change is one log line starting "[v3 HH:MM AM]" in trained/phase_v3.log, so a watcher can notify on it. Jobs (queue entries):
    {"kind": "ref"}                                              score the frozen Release_CandidateV2.1 on the v4 ladder (the context every round is read against)
    {"kind": "screen", "tag", "levers": [...], "desc"}           a FRESH 3M run of the recipe + these levers, judged against the control "v3_c0"
    {"kind": "combo", "tag": "v3_k3"}                            a fresh 3M run with EVERY lever that passed its screen; judged on each lever's own target
    {"kind": "stage", "tag", "stage", "from": tag, "levers"}     a 3M continuation (default LR 3e-5, full ramp) adding that stage's course; re-scores every earlier stage
    {"kind": "final", "tag", "from": tag, "levers", "extra"}     the 20M run (hard levels x1.10); gait checks at 3M / 5M / 10M stop it on a regression
    {"kind": "pause", "name"}                                    wait for the user: `touch trained/v3_go_<name>` (hardware check-in before the final run)
A screening round "passes" when the calm walk does not regress against the control (falls <= min(0.15, control + 0.05), speed >= 90% of the control)
AND its own target metric (TARGETS below) beats the control. The control itself must clear T1.1 falls <= 0.15. Scoring is the v4 ladder in parallel
(benchmark_v4.py, SCORE_JOBS workers; 2 while a training is running, so it does not starve it).
"""
import glob
import json
import os
import sys
import time

import g2_profile
import run_pipeline as RP

LOG = "trained/phase_v3.log"
QUEUE = "trained/v3_queue.json"
RESULTS = "trained/v3_results.json"
REF = "trained/v3_ref_v21.json"
V21 = "trained/Release_CandidateV2.1_ppo"
CONTROL = "v3_w3_c0"          # the control in the current world (case2 payload and the measured IMU, 2026-10-07); earlier controls: "v3_c0" (C0), "v3_w2_c0" (case2 payload, old IMU)
K3 = "v3_k3"
SCORE_JOBS = 8
SCORE_JOBS_BUSY = 2
EPISODES = 40
SCREEN_STEPS = "3e6"
STEP_MIN = 58            # minutes per 3M steps at ~860 steps/s (train.py now uses 4 torch threads)
SCORE_MIN = 4
SPEC = "all"                         # the benchmark cells a round is scored on
CALM_FELL_MAX, CALM_FELL_MARGIN, CALM_SPEED_RATIO = 0.15, 0.05, 0.90
NO_REGRESSION_FELL = 0.15            # a decision cell may not fall more than the control + this (24-40 episode counts carry ~+-15 points of noise)
FINAL_CHECK_STEPS = (3000000, 5000000, 10000000)

# the screening rounds, in order: tag, levers, description
SCREENS = [
    ("v3_s1_mirror", ["mirror"], "R1 left/right mirror-symmetry loss"),
    ("v3_s2_heading_obs", ["heading_obs"], "Y2 explicit heading-error input + yaw-free tilt"),
    ("v3_s3_heading_shape", ["heading_shape"], "R2 bounded, steeper heading penalty"),
    ("v3_s4_long_eps", ["long_episodes"], "Y3 25% of episodes 12.5 s long"),
    ("v3_s5_turn", ["turn"], "Y4 turn-command curriculum (only if Phase 1's turning gate passed: touch trained/v3_turning_gate_pass)"),
    ("v3_s6_faults", ["faults"], "Y5 persistent faults (stuck servo, weak joint, offset, yaw push, battery sag)"),
    ("v3_s11_length_level", ["length_level"], "S11 the length difficulty level (episodes grow from 3 s to 40 s as the gait earns it), balanced yaw push on long episodes, left and right must both pass"),
    ("v3_s7_servo_feas", ["servo_feas"], "R3 penalty on joint speeds above the servo ceiling"),
    ("v3_s8_balance_pbrs", ["balance_pbrs"], "R4 potential-based balance reward"),
    ("v3_s9_smooth", ["smooth"], "R5 activate the inert joint-smoothness terms"),
    ("v3_s10_touchdown", ["touchdown"], "R6 softer footfalls (only if Phase 1 reproduced G2's roll swing)"),
]

# per lever: (cell, metric, how, factor) -- the round's own target. "lower": value <= factor * control's. "abs_lower" compares |value|.
TARGETS = {
    "mirror": [("N1", "lr_asym_max_deg", "lower", 0.5), ("N1", "heading_abs_mean_deg", "lower", 1.0)],
    "heading_obs": [("N5", "heading_abs_mean_deg", "lower", 0.7), ("N1", "heading_abs_mean_deg", "lower", 1.0)],
    "heading_shape": [("N5", "heading_abs_mean_deg", "lower", 0.7), ("N1", "heading_abs_mean_deg", "lower", 1.0)],
    "long_episodes": [("N2", "speed_decay", "lower", 0.7), ("N2", "fell_fraction", "lower", 1.0)],
    "turn": [("N6a", "turn_ratio", "higher_abs", 0.5), ("N6b", "turn_ratio", "higher_abs", 0.5), ("N1", "heading_abs_mean_deg", "lower", 1.3)],
    "faults": [("N3", "heading_abs_mean_deg", "lower", 0.7), ("N5", "heading_abs_mean_deg", "lower", 0.7)],
    "length_level": [("L1", "heading_abs_mean_deg", "lower", 0.7), ("L1", "heading_sign_gap_deg", "lower_abs_gap", 10.0), ("L1", "fell_fraction", "lower", 1.0)],
    "servo_feas": [("N1", "servo_over_frac", "lower", 0.5), ("N1", "roll_std_deg", "lower", 1.1)],
    "balance_pbrs": [("T8.1", "fell_fraction", "lower", 1.0), ("T11.1", "fell_fraction", "lower", 1.0)],
    "smooth": [("N1", "yaw_rate_rms", "lower", 0.9)],
    "touchdown": [("N1", "roll_std_deg", "lower", 0.9)],
}
YAW_LEVERS = ("mirror", "heading_obs", "heading_shape", "long_episodes", "turn", "faults", "length_level")      # K1: the levers aimed at straightness
SMOOTH_LEVERS = ("servo_feas", "balance_pbrs", "smooth", "touchdown")                          # K2: the levers aimed at smoothness / resilience
DECISION_CELLS = ["T1.1", "N1", "N3", "N5", "T2.2", "T3.2", "T5.2", "T7.2", "T8.1", "T9.1", "T10.2", "T11.1"]


def log(msg):
    line = f"[v3 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def clock_in(minutes):
    return time.strftime("%I:%M %p", time.localtime(time.time() + 60 * minutes))


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, obj):
    json.dump(obj, open(path, "w"), indent=1)


# ----------------------------------------------------------------------------------------------- scoring
def policy_levers(levers):
    """Only the observation-changing levers matter to how a policy is scored."""
    return tuple(l for l in levers if l == "heading_obs")


def score(policy_path, levers, spec=None, busy=False, ladder=False, ladder_levers=(), extra_env=None):
    import benchmark_v4
    saved = dict(os.environ)                      # benchmark_v4.run puts the scoring profile in os.environ: keep it out of later training launches
    try:
        return benchmark_v4.run(policy_path, spec or SPEC, EPISODES, 1000, SCORE_JOBS_BUSY if busy else SCORE_JOBS, None,
                                policy_levers(levers), None, mirror_gap=True, quiet=True, extra_env=extra_env, ladder=ladder, ladder_levers=tuple(ladder_levers))
    finally:
        os.environ.clear()
        os.environ.update(saved)


def with_extra_cells(ctrl, tag=None):
    """The control's result plus any cells scored for it later (`trained/<control>_L1.json`, run with benchmark_v4 --cells L1): a screen added after the control ran (S11, the length level) is judged on its own cell."""
    tag = tag or CONTROL
    path = f"trained/{tag}_L1.json"
    if ctrl is not None and os.path.exists(path):
        try:
            extra = json.load(open(path))["cells"]
            have = {c["id"] for c in ctrl["cells"]}
            ctrl = dict(ctrl, cells=ctrl["cells"] + [c for c in extra if c["id"] not in have])
        except (OSError, ValueError, KeyError):
            pass
    return ctrl


def cellmap(res):
    out = {}
    for c in res["cells"]:
        d = dict(c)
        if "turn" in c:
            d["turn_ratio"] = c["turn"]["yaw_rate_ratio"]
        out[c["id"]] = d
    return out


def calm_ok(res, ctrl):
    a, b = cellmap(res), cellmap(ctrl)
    why = []
    for cid in ("T1.1", "N1"):
        lim = min(CALM_FELL_MAX, b[cid]["fell_fraction"] + CALM_FELL_MARGIN)
        if a[cid]["fell_fraction"] > lim:
            why.append(f"{cid} falls {a[cid]['fell_fraction']:.2f} > {lim:.2f}")
        if a[cid]["speed_mps"] < CALM_SPEED_RATIO * b[cid]["speed_mps"]:
            why.append(f"{cid} speed {a[cid]['speed_mps']:.3f} < {CALM_SPEED_RATIO:.0%} of control's {b[cid]['speed_mps']:.3f}")
    return why


def targets_ok(res, ctrl, levers):
    a, b = cellmap(res), cellmap(ctrl)
    why = []
    for lv in levers:
        for cid, key, how, f in TARGETS.get(lv, []):
            if cid not in a or key not in a[cid]:
                why.append(f"{lv}: {cid}.{key} missing")
                continue
            x, y = a[cid][key], b[cid][key]
            if how == "lower" and not (abs(x) if key.startswith("heading") else x) <= f * (abs(y) if key.startswith("heading") else y) + 1e-9:
                why.append(f"{lv}: {cid}.{key} {x:.3g} not <= {f} x control's {y:.3g}")
            if how == "higher_abs" and not abs(x) >= f:
                why.append(f"{lv}: {cid}.{key} {x:.2f} below {f}")
            if how == "lower_abs_gap" and not x <= f:                       # an absolute limit (degrees), not relative to the control: the left and right pushes must end within this of each other
                why.append(f"{lv}: {cid}.{key} {x:.1f} deg is above {f:g} deg: one side is corrected worse than the other")
    return why


def regressions(res, ctrl):
    a, b = cellmap(res), cellmap(ctrl)
    return [f"{c} falls {a[c]['fell_fraction']:.2f} vs {b[c]['fell_fraction']:.2f}" for c in DECISION_CELLS
            if c in a and c in b and a[c]["fell_fraction"] > b[c]["fell_fraction"] + NO_REGRESSION_FELL]


def summary(res):
    c = cellmap(res)
    parts = []
    if "T1.1" in c:
        parts.append(f"T1.1 falls {c['T1.1']['fell_fraction']:.2f}")
    if "N1" in c:
        n1 = c["N1"]
        parts.append(f"N1 speed {n1['speed_mps']:.3f} heading {n1['heading_mean_deg']:+.1f} roll {n1['roll_std_deg']:.1f} "
                     f"asym {n1['lr_asym_max_deg']:.1f} over {n1['servo_over_frac']:.2f}")
    if "N2" in c:
        parts.append(f"N2 falls {c['N2']['fell_fraction']:.2f} decay {c['N2']['speed_decay']:.2f}")
    if "N5" in c:
        parts.append(f"N5 heading {c['N5']['heading_abs_mean_deg']:.1f}")
    parts.append(f"mirror gap {res.get('mirror_gap')}")
    return " | ".join(parts)


# ----------------------------------------------------------------------------------------------- jobs
def train(job, results):
    tag = job["tag"]
    levers = job.get("levers", [])
    kind = job["kind"]
    for k in [k for k in os.environ if k.startswith("G2E_")]:      # a clean slate: the profile alone decides the training env
        del os.environ[k]
    if kind == "stage":
        env = g2_profile.env_for(*levers, stage=job["stage"], extra=job.get("extra"))
        steps, from_ckpt = job.get("steps", SCREEN_STEPS), f"trained/{job['from']}_ppo"
    elif kind == "final":
        env = g2_profile.env_for(*levers, stage=job["stage"], extra=job.get("extra"))
        steps, from_ckpt = "20e6", f"trained/{job['from']}_ppo"
    else:
        env = g2_profile.env_for(*levers, extra=job.get("extra"))
        steps, from_ckpt = SCREEN_STEPS, None
    if RP.training(tag) or os.path.exists(f"trained/{tag}_ppo.zip"):
        log(f"{tag} RESUME: already running or finished, not relaunching")
        return True
    minutes = STEP_MIN * float(steps) / 3e6
    log(f"{tag} START ({kind}): {job.get('desc', '')} levers={levers} steps={steps} -> done about {clock_in(minutes)}, scored about {clock_in(minutes + SCORE_MIN)}")
    RP.launch(tag, env, steps=steps, from_ckpt=from_ckpt)
    return True


def finish(job, results, ctrl_res):
    tag, kind = job["tag"], job["kind"]
    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"{tag} HALT: {reason}")
        return False
    levers = job.get("levers", [])
    res = score(f"trained/{tag}_ppo", levers, extra_env={k: v for k, v in (job.get("extra") or {}).items() if k != "G2E_SEED"})   # a job pinned to an older world is scored in it
    reached = ""
    try:                                              # the difficulty levels the curriculum had reached when the run ended (last probe line)
        probes = [l for l in open(f"trained/{tag}_console.log") if l.startswith("[probe]")]
        if probes:
            reached = probes[-1].strip().split("(new level):", 1)[-1].strip()
    except OSError:
        pass
    rec = dict(kind=kind, levers=levers, summary=summary(res) + (f" | levels reached: {reached}" if reached else ""), result_file=f"trained/v3_score_{tag}.json")
    save(rec["result_file"], res)
    if tag == CONTROL:
        why = [f"T1.1 falls {cellmap(res)['T1.1']['fell_fraction']:.2f} > {CALM_FELL_MAX}"] if cellmap(res)["T1.1"]["fell_fraction"] > CALM_FELL_MAX else []
        rec.update(passed=not why, why=why)
        log(f"{tag} DONE control {'PASS' if not why else 'FAIL'} {why or ''} | {rec['summary']}")
    elif kind in ("screen", "combo"):
        if ctrl_res is None:
            log(f"{tag} DONE but there is no control result to judge it against | {rec['summary']}")
            rec.update(passed=None, why=["no control"])
        else:
            why = calm_ok(res, ctrl_res) + targets_ok(res, ctrl_res, levers) + regressions(res, ctrl_res)
            rec.update(passed=not why, why=why)
            log(f"{tag} DONE {kind} {'PASS' if not why else 'FAIL'} {why or ''} | {rec['summary']}")
    else:
        rec.update(passed=None, why=[])
        log(f"{tag} DONE {kind} | {rec['summary']}")
    results[tag] = rec
    save(RESULTS, results)
    return True


def stage_gate(job, results):
    """After a stage: every earlier stage's cells must still hold (falls <= the previous stage's + NO_REGRESSION_FELL) and the calm walk too."""
    prev = results.get(job["from"], {}).get("result_file")
    cur = results[job["tag"]]["result_file"]
    if not prev:
        return []
    a, b = cellmap(json.load(open(cur))), cellmap(json.load(open(prev)))
    why = [f"{c} falls {a[c]['fell_fraction']:.2f} vs previous stage {b[c]['fell_fraction']:.2f}" for c in DECISION_CELLS
           if c in a and c in b and a[c]["fell_fraction"] > b[c]["fell_fraction"] + NO_REGRESSION_FELL]
    if a["N1"]["speed_mps"] < CALM_SPEED_RATIO * b["N1"]["speed_mps"]:
        why.append(f"N1 speed {a['N1']['speed_mps']:.3f} < {CALM_SPEED_RATIO:.0%} of previous {b['N1']['speed_mps']:.3f}")
    return why



REPORT_DIR = "trained/v3_report"


def do_report(job, results, last_stage, outdir=None, episodes=None, spec=None, ladder_episodes=None):
    """The pre-20M benchmark: score the deployed V2.1, the V3 control, K3 and the last finished stage on benchmark v5 (every cell + the difficulty-level ladder, all in the
    world the final stage trains in), then write the HTML report (v3_report.py). Resumable: a policy already scored in the report folder is not scored again."""
    import v3_report
    outdir = outdir or REPORT_DIR
    os.makedirs(outdir, exist_ok=True)
    kept = results[K3]["levers"] if K3 in results else []
    policies = [("v21", V21, []), ("control", "trained/v3_c0b_ppo", []), ("k3", f"trained/{K3}_ppo", kept), ("final", f"trained/{last_stage}_ppo", kept)]
    log(f"REPORT scoring {len(policies)} policies on benchmark v5 with the difficulty ladder (world levers {kept}); about 10 min each -> done about {clock_in(10 * len(policies))}")
    out = {}
    for key, path, levers in policies:
        f = f"{outdir}/{key}.json"
        if os.path.exists(f):
            out[key] = json.load(open(f))
            continue
        if not os.path.exists(path + ".zip"):
            log(f"REPORT skipping {key}: {path}.zip does not exist")
            continue
        import benchmark_v4
        saved = dict(os.environ)
        try:
            res = benchmark_v4.run(path, spec or SPEC, episodes or EPISODES, 1000, SCORE_JOBS, None, policy_levers(levers), None, mirror_gap=True, quiet=True,
                                   ladder=True, ladder_levers=tuple(kept), ladder_episodes=ladder_episodes or benchmark_v4.LADDER_EPISODES)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        save(f, res)
        out[key] = res
        log(f"REPORT scored {key} in {res['wall_seconds'] / 60:.0f} min | {summary(res)}")
    training = load(RESULTS, {})
    html_path = f"{outdir}/pre20m_report.html"
    open(html_path, "w").write(v3_report.build(out, training))
    log(f"REPORT ready: {html_path} (final stage = {last_stage}). Tell Claude to publish it; the 20M starts only on your go")
    return html_path


def run_final(job, results):
    """20M with gait checks: each checkpoint is scored against the stage it continues from; a regression stops the run."""
    tag = job["tag"]
    base = json.load(open(results[job["from"]]["result_file"]))
    for step in FINAL_CHECK_STEPS:
        ok, reason = RP.wait_for_ckpt(tag, step)
        if not ok:
            log(f"{tag} HALT before {step // 10**6}M: {reason}")
            return False
        t0 = time.time()
        res = score(f"trained/checkpoints/{tag}_{step}_steps", job.get("levers", []), busy=True)
        save(f"trained/v3_score_{tag}_{step // 10**6}M.json", res)
        why = calm_ok(res, base) + regressions(res, base)
        log(f"{tag} GAIT CHECK {step // 10**6}M {'PASS' if not why else 'REGRESSION'} {why or ''} | {summary(res)} (scored in {(time.time() - t0) / 60:.0f} min)")
        if why:
            RP.stop(tag)
            log(f"{tag} STOPPED at {step // 10**6}M on a regression; checkpoint {step} and the last good stage ({job['from']}) are the fallbacks")
            return False
    return True


def run_queue():
    queue = load(QUEUE, None)
    if queue is None:
        raise SystemExit(f"no {QUEUE}: run `python phase_v3.py init` first")
    results = load(RESULTS, {})
    ctrl = with_extra_cells(json.load(open(results[CONTROL]["result_file"]))) if CONTROL in results else None
    last_stage = K3                         # the stage chain continues from the last stage that actually ran (a skipped optional stage is not one)
    for job in queue:
        kind, tag = job["kind"], job.get("tag")
        if kind in ("stage", "final"):
            job = dict(job, **{"from": last_stage})
        if kind == "ref":
            if not os.path.exists(REF):
                log("REF scoring the frozen Release_CandidateV2.1 on the v4 ladder (context for every round)")
                res = score(V21, [])
                save(REF, res)
                log(f"REF done | {summary(res)}")
            continue
        if kind == "report":
            if not os.path.exists(f"{REPORT_DIR}/pre20m_report.html"):
                do_report(job, results, last_stage)
            continue
        if kind == "pause":
            while not os.path.exists(f"trained/v3_go_{job['name']}"):
                if not job.get("announced"):
                    log(f"PAUSE {job['name']}: waiting for the user (touch trained/v3_go_{job['name']} to continue). {job.get('note', '')}")
                    job["announced"] = True
                time.sleep(60)
            continue
        if tag in results:
            if kind == "stage":
                last_stage = tag
            continue                                         # finished in an earlier run of this runner
        if tag == "v3_s5_turn" and not os.path.exists("trained/v3_turning_gate_pass"):
            log("v3_s5_turn SKIPPED: Phase 1's turning gate has not passed (touch trained/v3_turning_gate_pass if it did)")
            continue
        if tag == "v3_s10_touchdown" and not os.path.exists("trained/v3_roll_matched"):
            log("v3_s10_touchdown SKIPPED: Phase 1 has not confirmed the sim reproduces G2's roll swing (touch trained/v3_roll_matched if it does)")
            continue
        if kind == "combo":
            levers = [lv for r in results.values() if r.get("kind") == "screen" and r.get("passed") for lv in r["levers"]]
            if not levers:
                log("v3_k3 SKIPPED: no screening round passed")
                return
            job = dict(job, levers=levers)
            log(f"COMBO levers that passed their screens: {levers}")
        elif job.get("levers") == "K3":
            job = dict(job, levers=results[K3]["levers"])
        if job.get("needs") and job["needs"] not in job.get("levers", []):
            log(f"{tag} SKIPPED: the {job['needs']} lever was not kept")
            continue
        train(job, results)
        if kind == "final":
            if not run_final(job, results):
                return
            continue
        if not finish(job, results, ctrl):
            return
        if tag == CONTROL:
            ctrl = with_extra_cells(json.load(open(results[CONTROL]["result_file"])))
            if not results[CONTROL]["passed"]:
                log("CONTROL did not clear the flat-ground bar: stopping so the calibrated sim / recipe can be reviewed before any lever is judged against it")
                return
        if kind == "stage":
            why = stage_gate(job, results)
            results[tag]["passed"], results[tag]["why"] = not why, why
            save(RESULTS, results)
            if why:
                log(f"{tag} STAGE GATE FAILED {why}: stopping for a decision (retry with a higher LR, or drop the stage)")
                return
            last_stage = tag
        if kind == "combo" and not results[tag]["passed"]:
            log(f"K3 FAILED {results[tag]['why']}: running the two halves to find the group (K1 = passing yaw levers, K2 = passing smoothness levers)")
            for tg, grp in (("v3_k1", YAW_LEVERS), ("v3_k2", SMOOTH_LEVERS)):
                sub = [lv for lv in job["levers"] if lv in grp]
                if not sub or sub == job["levers"] or tg in results:
                    continue
                half = dict(kind="combo", tag=tg, levers=sub, desc=f"{tg}: half of K3")
                train(half, results)
                if not finish(half, results, ctrl):
                    return
            log("DECISION NEEDED: compare v3_k1 / v3_k2 with v3_k3 (python phase_v3.py status), drop the lever whose removal recovers it "
                "(one 3M run per suspect), then edit trained/v3_queue.json / the lever list and restart the runner")
            return
    log("QUEUE COMPLETE")


def default_queue():
    q = [{"kind": "ref"}, {"kind": "screen", "tag": CONTROL, "levers": [], "desc": "C0 control: calibrated profile, sign-correct, ramp fix, base recipe"}]
    q += [{"kind": "screen", "tag": t, "levers": lv, "desc": d} for t, lv, d in SCREENS]
    q += [{"kind": "combo", "tag": "v3_k3", "desc": "K3: every lever that passed its screen, together (also stage s0, the flat base)"}]
    chain = [(name, None) for name, _ in g2_profile.STAGES[1:]] + [("s5_turn_wide", "turn"), ("s6_full_strength", None)]
    for name, needs in chain:                      # "from" is filled in at run time (the last stage that ran)
        q.append(dict(kind="stage", tag=f"v3_{name}", stage=name, levers="K3", desc=f"stage {name}", **({"needs": needs} if needs else {})))
    q.append({"kind": "report", "name": "pre20m_report"})
    q.append({"kind": "pause", "name": "hardware_checkin", "note": "Export the last stage, put it on the Pi without making it default, walk it six times."})
    q.append({"kind": "final", "tag": "v3_20m", "stage": "s6_full_strength", "levers": "K3",
              "desc": "20M consolidation, hard levels x1.10, gait checks at 3M/5M/10M"})
    return q


def status():
    res = load(RESULTS, {})
    if not res:
        print("no results yet")
    for tag, r in res.items():
        p = {True: "PASS", False: "FAIL", None: "done"}[r.get("passed")]
        print(f"{tag:24s} {p:5s} {r.get('why') or ''}\n    {r['summary']}")


def test_mode():
    """`python phase_v3.py run --test`: a rehearsal on tiny jobs (40k steps, two cells, 2 episodes) in zz_ files, to shake out the machinery."""
    global LOG, QUEUE, RESULTS, REF, SCREEN_STEPS, EPISODES, SPEC, CONTROL, STEP_MIN, SCORE_JOBS, FINAL_CHECK_STEPS
    LOG, QUEUE, RESULTS, REF = "trained/zz_v3.log", "trained/zz_v3_queue.json", "trained/zz_v3_results.json", "trained/zz_v3_ref.json"
    SCREEN_STEPS, EPISODES, SPEC, CONTROL, STEP_MIN, SCORE_JOBS = "40000", 2, "T1.1,N1", "zz_c0", 1, 2
    global K3
    K3 = "zz_k3"
    if "--keep" in sys.argv:                       # continue an earlier rehearsal (after editing its results file by hand)
        return
    for f in (QUEUE, RESULTS, REF, LOG):
        if os.path.exists(f):
            os.remove(f)
    save(QUEUE, [{"kind": "screen", "tag": "zz_c0", "levers": [], "desc": "rehearsal control"},
                 {"kind": "screen", "tag": "zz_s1_mirror", "levers": ["mirror"], "desc": "rehearsal mirror"},
                 {"kind": "combo", "tag": "zz_k3", "desc": "rehearsal combo"},
                 {"kind": "stage", "tag": "zz_s1_transition", "stage": "s1_transition", "levers": "K3", "desc": "rehearsal stage"}])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if "--test" in sys.argv:
        test_mode()
    if cmd == "init":
        if os.path.exists(QUEUE):
            raise SystemExit(f"{QUEUE} exists; edit it, or delete it to start over")
        save(QUEUE, default_queue())
        print(f"wrote {QUEUE} ({len(default_queue())} jobs)")
    elif cmd == "status":
        status()
    else:
        run_queue()
