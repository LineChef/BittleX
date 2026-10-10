"""V6: a chain of short skill stages, then a 20M consolidation, run unattended (plan: docs/plan-detail/v6-staged-training-plan.md; user approved 2026-10-09).

    python phase_v6.py run        # preflight -> S0 -> S1 -> S2 -> S3 -> S3 benchmark and go/no-go -> S4 (20M) -> pick (average of the last 5) -> export -> report
    python phase_v6.py status | plan | smoke

Recipe (all stages): the V5 recipe plus the four adopted screens (crossing bonus, hazard-aware speed and posture, heading-blind) and the 30 mm ledge tops. Each stage adds its own mix of
episodes (g2_profile levers v6_s0_flat ... v6_s4_all). S0 is a fresh run; every later stage starts from the previous stage's final weights with a fresh-run learning-rate schedule that
decays inside the stage (train.py --chain-from). The go/no-go for the 20M is Claude's (user, 2026-10-09); nothing is promoted or deployed here. Reuses phase_v5.py's helpers with
its module settings pointed at the V6 files. Log trained/phase_v6.log, state trained/v6_state.json, halt trained/v6_halt (tools/v6_watchdog.sh keeps it alive)."""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, ".")
import g2_profile
import phase_v5 as V5
import run_pipeline as RP

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_v6.log", "trained/v6_halt", "trained/v6_state.json", "trained/v6_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR


def log(msg):
    line = f"[v6 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.log = log
halt, load_state, save_state, clock_in, cm = V5.halt, V5.load_state, V5.save_state, V5.clock_in, V5.cm

ADOPTED = ["cross_bonus", "haz_speed", "haz_posture", "heading_blind"]
BASE6 = V5.BASE + ADOPTED + ["ledge30"]
STAGES = [   # (name, lever, steps, minutes estimate)
    ("s0", "v6_s0_flat", "2e6", 14),
    ("s1", "v6_s1_terrain", "3e6", 21),
    ("s2", "v6_s2_ledges", "3e6", 21),
    ("s3", "v6_s3_slopes", "1e6", 8),
]
FINAL = ("s4", "v6_s4_all", "20e6", 145)
TAG = lambda n: f"v6_{n}"                                          # noqa: E731
STAGE_EPISODES, STAGE_LADDER_EPISODES = 40, 20
TRACK_EPISODES, TRACK_LADDER_EPISODES = 40, 20
PICK_WINDOW = 5                                                    # user, 2026-10-09: the average of the last 5 checkpoints
V5_JSON, V4_JSON, SCRIPTED_JSON = "trained/v5_report/v5.json", "trained/v5_cmp_v4.json", V5.SCRIPTED_JSON


def stage_env(name, lever, last=False):
    env = g2_profile.env_for_job({"kind": "final", "tag": TAG(name), "fresh": True, "levers": list(BASE6) + [lever]})
    env["G2E_SEED"] = "42"
    if not last:
        env.pop("G2E_PLATEAU_STOP", None)                          # only the 20M may plateau-stop
    return {k: v for k, v in env.items() if v != ""}


def clean_environ():
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP                  # the ladders everywhere use the 30 mm tops


def run_stage(name, lever, steps, minutes, prev):
    tag = TAG(name)
    zip_ = f"trained/{tag}_ppo.zip"
    if os.path.exists(zip_):
        return
    if not RP.training(tag):
        if os.path.exists(f"trained/{tag}_console.log"):
            halt(f"HALT: {tag} stopped without finishing (trained/{tag}_console.log): fix, move its files aside, rm {HALT}, restart")
        clean_environ()
        log(f"{tag} START: {lever}, {steps} steps{' from ' + prev if prev else ' (fresh)'}, about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, stage_env(name, lever), steps=steps, base=False, chain_from=((prev if prev.startswith("trained/") else f"trained/{prev}_ppo") if prev else None))
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: {tag} did not finish: {why}")
    out = f"trained/v6_score_{name}.json"
    if not os.path.exists(out):
        t0 = time.time()
        res = V5.score(f"trained/{tag}_ppo", BASE6, STAGE_EPISODES, STAGE_LADDER_EPISODES)
        json.dump(res, open(out, "w"), indent=1)
        log(f"{tag} DONE, scored in {(time.time() - t0) / 60:.0f} min | {V5.summary(res)}")


def mean_cell_falls(res, ids=None):
    c = cm(res)
    ids = ids or [i for i in c if not i.startswith(("Z.", "N")) and i != "Z0"]
    return sum(c[i]["fell_fraction"] for i in ids) / len(ids), ids


def go_no_go(st):
    """Claude's call (user, 2026-10-09): the S3 checkpoint against V5's final and V4 on the same cells. GO if it is safe on flat ground, walks straight and even, and is at least
    near V5's overall fall rate (it has had 9M steps against V5's 20M); anything else halts for a review, never silently runs 2.4 hours."""
    if st.get("go"):
        return
    s3 = json.load(open("trained/v6_score_s3.json"))
    v5, v4 = json.load(open(V5_JSON)), json.load(open(V4_JSON))
    c = cm(s3)
    ids = [i for i in c if i in cm(v5) and i in cm(v4) and not i.startswith(("Z.", "N")) and i != "Z0"]
    m3, m5, m4 = (mean_cell_falls(r, ids)[0] for r in (s3, v5, v4))
    flat = all(c[i]["fell_fraction"] == 0 for i in ("T1.1", "N1"))
    head, asym = c["N1"]["heading_abs_mean_deg"], c["N1"]["lr_asym_max_deg"]
    lu = s3["size_ladder"]["summary"]["ledge_up"]["success"][0]
    reasons = []
    if not flat:
        reasons.append("it falls on flat ground")
    if head > 30:
        reasons.append(f"calm-walk heading {head:.0f} deg > 30")
    if asym > 4:
        reasons.append(f"left/right difference {asym:.1f} > 4")
    if lu < 0.4:
        reasons.append(f"7.5 mm step-up success {lu:.2f} < 0.4: it avoids the edge instead of crossing it")
    if m3 > m5 + 0.03:
        reasons.append(f"mean falls {m3:.3f} above V5's {m5:.3f} + 0.03")
    log(f"S3 BENCHMARK | mean falls over {len(ids)} cells: S3 {m3:.3f}, V5 final {m5:.3f}, V4 {m4:.3f} | flat falls none = {flat} | calm walk heading {head:.0f} asym {asym:.1f} | "
        f"7.5 mm step-up success {lu:.2f} (V5 0.95, V4 0.62, scripted 0.47)")
    if reasons:
        halt(f"DECISION (mine, per the user's delegation): S3 is below the bar for the 20M: {'; '.join(reasons)}. Review before spending 2.4 h: look at trained/v6_score_s3.json")
    st["go"] = True
    save_state(st)
    log("S3 GO: the 20M consolidation starts now (my call, delegated by the user)")


def track6(step, levers):
    """The 1M tracker, with 40 episodes (V5's 12-20 were too noisy to steer by) on 3 workers while training runs."""
    tag = TAG(FINAL[0])
    ck = f"trained/checkpoints/{tag}_{step}_steps"
    out = f"trained/.v6_track_{step}.json"
    cmd = [sys.executable, "-c",
           "import sys, json; sys.path.insert(0, '.'); import benchmark_v4 as V, benchmark_v5 as B; "
           f"r = V.run({ck!r}, 'T1.1,N1,SL8,SR8,LU15,LD15', {TRACK_EPISODES}, 1000, 3, None, {tuple(V5.obs_levers(levers))!r}, None, mirror_gap=True, quiet=True); "
           f"r['size_ladder'] = B.run_ladder({ck!r}, {tuple(V5.obs_levers(levers))!r}, {TRACK_LADDER_EPISODES}, jobs=3, hazards=['ledge_up', 'ledge_down', 'rubble', 'sidehill_l', 'sidehill_r'], quiet=True); "
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
               **{f"{h}_falls": s[h]["mean_falls"] for h in s}, **{f"{h}_success": s[h]["success"] for h in s})
    with open(f"trained/{tag}_curve.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    su, sd = s["ledge_up"], s["ledge_down"]
    log(f"{tag} TRACK {step // 10**6}M | N1 heading {row['heading']:.0f} asym {row['asym']:.1f} roll {row['roll']:.1f} speed {row['speed']:.3f} | step-up falls {su['mean_falls']:.2f} "
        f"success {[round(x, 2) for x in su['success']]} | step-down falls {sd['mean_falls']:.2f} success {[round(x, 2) for x in sd['success']]} | rubble {s['rubble']['mean_falls']:.2f} | "
        f"side-hill L/R {s['sidehill_l']['mean_falls']:.2f}/{s['sidehill_r']['mean_falls']:.2f} | mirror {res.get('mirror_gap') or float('nan'):.3f}")
    return row


def final6(st):
    name, lever, steps, minutes = FINAL
    tag = TAG(name)
    if st.get("final") == "done":
        return
    clean_environ()
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        log(f"{tag} START: the 20M consolidation from {TAG('s3')} (plateau stop on), about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, stage_env(name, lever, last=True), steps=steps, base=False, chain_from=f"trained/{TAG('s3')}_ppo")
    done, step = set(st.get("tracked", [])), 1_000_000
    while True:
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
        row = track6(step, BASE6)
        if step in V5.FINAL_CHECKS and row is not None and max(row["t11"], row["n1"]) > 0.25:
            RP.stop(tag)
            halt(f"DECISION (mine): the 20M falls on flat ground at {step // 10**6}M (T1.1 {row['t11']:.2f}, N1 {row['n1']:.2f}); stopped for review")
        done.add(step)
        st["tracked"] = sorted(done)
        save_state(st)
        step += 1_000_000
        if step > 20_000_000:
            break
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        halt(f"HALT: the 20M did not finish: {why}")
    st["final"] = "done"
    save_state(st)
    log(f"{tag} FINISHED")


def pick6(st):
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
            log(f"PICK: scoring {key} in full (about 8 min, done about {clock_in(8)})")
            json.dump(V5.score(path, BASE6, V5.FINAL_EPISODES, V5.FINAL_LADDER_EPISODES), open(f, "w"), indent=1)
        scored[key] = json.load(open(f))
        log(f"PICK: {key} | {V5.summary(scored[key])}")
    flat_ok = {k: all(cm(r)[c]["fell_fraction"] == 0 for c in ("T1.1", "N1")) for k, r in scored.items()}
    best = min(scored, key=lambda k: (not flat_ok[k], mean_cell_falls(scored[k])[0]))
    path = dict(cands)[best]
    log(f"PICK: {best} chosen (flat-ground falls none = {flat_ok[best]}, mean cell falls {mean_cell_falls(scored[best])[0]:.3f})")
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", "trained/V6cand_ppo.onnx", "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind"],
                       capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log("EXPORTED trained/V6cand_ppo.onnx (+ .onnx.json); not promoted, not deployed (the user decides)")
    shutil.copy(f"{REPORT_DIR}/{best}.json", f"{REPORT_DIR}/v6.json")
    st["picked"] = best
    save_state(st)


def report6(st):
    if st.get("report") == "done":
        return
    import report_v5
    P, S = json.load(open(f"{REPORT_DIR}/v6.json")), json.load(open(SCRIPTED_JSON))
    fr = json.load(open(f"trained/{TAG(FINAL[0])}_frontier.json")) if os.path.exists(f"trained/{TAG(FINAL[0])}_frontier.json") else None
    open(f"{REPORT_DIR}/report.html", "w").write(report_v5.build(P, S, fr, title="V6 Gait Report", console=f"trained/{TAG(FINAL[0])}_console.log", policy_name="V6"))
    v5, v4 = json.load(open(V5_JSON)), json.load(open(V4_JSON))
    ids = [i for i in cm(P) if i in cm(v5) and i in cm(v4) and not i.startswith(("Z.", "N")) and i != "Z0"]
    rows = [f"mean falls over {len(ids)} cells: V6 {mean_cell_falls(P, ids)[0]:.3f} | V5 {mean_cell_falls(v5, ids)[0]:.3f} | V4 {mean_cell_falls(v4, ids)[0]:.3f} | scripted {mean_cell_falls(json.load(open(SCRIPTED_JSON)), ids)[0]:.3f}"]
    for h in ("ledge_up", "ledge_down"):
        for nm, r in (("V6", P), ("V5", v5), ("V4", v4), ("scripted", S)):
            x = r["size_ladder"]["summary"][h]
            rows.append(f"  {h:10s} {nm:9s} falls {[round(v, 2) for v in x['falls']]} success {[round(v, 2) for v in x['success']]}")
    open(f"{REPORT_DIR}/compare.txt", "w").write("\n".join(rows) + "\n")
    st["report"] = "done"
    save_state(st)
    for r_ in rows:
        log("COMPARE " + r_)
    log(f"REPORT ready: rl_training/opencat-gym/{REPORT_DIR}/report.html (publish it as an Artifact page)")


def preflight6(st):
    if st.get("preflight") == "pass":
        return
    levers = BASE6 + ["v6_s2_ledges"]                                   # the stage with the new rewards
    log(f"PREFLIGHT on the V6 recipe with the ledge-stage rewards (about 15 min, done about {clock_in(15)})")
    r = subprocess.run([sys.executable, "preflight.py", "--levers", ",".join(levers)], capture_output=True, text=True)
    open("trained/v6_preflight.log", "w").write(r.stdout + r.stderr)
    if "ALL PASS" not in r.stdout:
        halt(f"HALT: preflight FAILED (trained/v6_preflight.log): {[l for l in r.stdout.splitlines() if 'FAIL' in l][:6]}")
    st["preflight"] = "pass"
    save_state(st)
    log("PREFLIGHT ALL PASS")

# ---------------------------------------------------------------------------------------------------- layer 2, Plan B, the summary (hands-off: user, 2026-10-09 "if decisions need to be made, you make the call and document them")
DECISIONS = f"{REPORT_DIR}/decisions.md"
L2_STAGES = (("a", "v6_l2_ledges", "5e6", 31), ("b", "v6_l2_mixed", "9e6", 52))
L2_MAX_EXTRA_FALLS = 0.03      # layer 2 may not fall more over the 31 cells than layer 1 by more than this
L2_STEPUP15_SUCCESS, L2_STEPUP15_FALLS = 0.3, 0.4


def decision(msg):
    os.makedirs(REPORT_DIR, exist_ok=True)
    log("DECISION " + msg)
    with open(DECISIONS, "a") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %I:%M %p')}: {msg}\n")


def shared_ids(*results):
    cs = [cm(r) for r in results]
    return [i for i in cs[0] if all(i in c for c in cs) and not i.startswith(("Z.", "N")) and i != "Z0"]


def l2_metrics(res, ids):
    c, su = cm(res), res["size_ladder"]["summary"]["ledge_up"]
    return dict(mean=mean_cell_falls(res, ids)[0], flat=all(c[i]["fell_fraction"] == 0 for i in ("T1.1", "N1")), lu15_success=su["success"][1], lu15_falls=su["falls"][1],
                lu75_success=su["success"][0], heading=c["N1"]["heading_abs_mean_deg"], asym=c["N1"]["lr_asym_max_deg"])


def l2_passes(res, base, ids):
    m, b = l2_metrics(res, ids), l2_metrics(base, ids)
    return bool(m["flat"] and m["lu15_success"] >= L2_STEPUP15_SUCCESS and m["lu15_falls"] <= L2_STEPUP15_FALLS and m["mean"] <= b["mean"] + L2_MAX_EXTRA_FALLS)


def candidate_score(m):
    """Lower is better: mean falls, a bonus for crossing the 15 mm step-up, and a heavy penalty for flat-ground falls."""
    return m["mean"] - 0.15 * m["lu15_success"] + (10.0 if not m["flat"] else 0.0)


def l1_path(st):
    return f"trained/{TAG(FINAL[0])}_ppo" if st.get("picked") == "final" else f"trained/{TAG(FINAL[0])}_avg{PICK_WINDOW}_ppo"


def l2_attempt(st, key, start):
    """Stage a (ledges, action noise reset) then stage b (mixed) chained from `start`; scores the final and the average of the last 5 checkpoints of b in full and keeps the better."""
    import glob
    import re
    prev = start
    for suffix, lever, steps, minutes in L2_STAGES:
        name = f"{key}{suffix}"
        run_stage(name, lever, steps, minutes, prev)
        prev = f"trained/{TAG(name)}_ppo"
    tag = TAG(f"{key}b")
    cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
    cands = [("final", f"trained/{tag}_ppo")]
    if len(cks) >= PICK_WINDOW:
        ok, out = V5.average_checkpoints([c[:-4] for c in cks[-PICK_WINDOW:]], f"trained/{tag}_avg{PICK_WINDOW}_ppo")
        if ok:
            cands.append((f"avg{PICK_WINDOW}", f"trained/{tag}_avg{PICK_WINDOW}_ppo"))
    scored = {}
    for k, path in cands:
        f = f"{REPORT_DIR}/{key}_{k}.json"
        if not os.path.exists(f):
            log(f"{key}: scoring {k} in full (about 8 min, done about {clock_in(8)})")
            json.dump(V5.score(path, BASE6, V5.FINAL_EPISODES, V5.FINAL_LADDER_EPISODES), open(f, "w"), indent=1)
        scored[k] = json.load(open(f))
    base = json.load(open(f"{REPORT_DIR}/v6.json"))
    ids = shared_ids(base, *scored.values())
    best = min(scored, key=lambda k: candidate_score(l2_metrics(scored[k], ids)))
    shutil.copy(f"{REPORT_DIR}/{key}_{best}.json", f"{REPORT_DIR}/{key}.json")
    st.setdefault("l2", {})[key] = dict(path=dict(cands)[best], which=best, passes=l2_passes(scored[best], base, ids))
    save_state(st)
    m = l2_metrics(scored[best], ids)
    log(f"{key} RESULT ({best}) | mean falls {m['mean']:.3f} (layer 1 {l2_metrics(base, ids)['mean']:.3f}) | flat falls none = {m['flat']} | 7.5 mm step-up success {m['lu75_success']:.2f} | "
        f"15 mm step-up success {m['lu15_success']:.2f} falls {m['lu15_falls']:.2f} | heading {m['heading']:.0f} asym {m['asym']:.1f} | passes the success criteria = {st['l2'][key]['passes']}")
    return best


def layer2(st):
    if st.get("l2_done"):
        return
    base = json.load(open(f"{REPORT_DIR}/v6.json"))
    start = l1_path(st)
    decision(f"Layer 2 starts from layer 1's {st.get('picked')} policy ({start}): a 5M ledge stage with the action noise reset, then a 9M mixed stage (the plan's structural changes 1-3).")
    l2_attempt(st, "l2", start)
    a = st["l2"]["l2"]
    if a["passes"]:
        decision("Layer 2 met the success criteria (15 mm step-up success at least 0.3 with falls at most 0.4, mean falls within 0.03 of layer 1, no flat falls): no Plan B needed.")
    else:
        ck = "trained/checkpoints/v6_s4_10000000_steps"
        if os.path.exists(ck + ".zip"):
            decision(f"Layer 2 did NOT meet the success criteria; running Plan B (the user's definition): the same recipe from layer 1's 10M checkpoint ({ck}), no hi-step base.")
            l2_attempt(st, "l2b", ck)
        else:
            decision("Layer 2 did not meet the criteria and layer 1's 10M checkpoint is missing, so Plan B was not run.")
    st["l2_done"] = True
    save_state(st)


def choose_and_export(st):
    if st.get("chosen"):
        return
    base = json.load(open(f"{REPORT_DIR}/v6.json"))
    cands = {"layer 1": (base, l1_path(st))}
    for key, label in (("l2", "layer 2"), ("l2b", "Plan B")):
        if key in st.get("l2", {}):
            cands[label] = (json.load(open(f"{REPORT_DIR}/{key}.json")), st["l2"][key]["path"])
    ids = shared_ids(*(r for r, _ in cands.values()))
    ranked = sorted(cands, key=lambda k: candidate_score(l2_metrics(cands[k][0], ids)))
    for k in ranked:
        m = l2_metrics(cands[k][0], ids)
        decision(f"candidate {k}: mean falls {m['mean']:.3f}, 15 mm step-up success {m['lu15_success']:.2f} / falls {m['lu15_falls']:.2f}, 7.5 mm success {m['lu75_success']:.2f}, flat falls none = {m['flat']}, "
                 f"heading {m['heading']:.0f}, asym {m['asym']:.1f}, score {candidate_score(m):.3f}")
    win = ranked[0]
    path = cands[win][1]
    decision(f"CHOSEN as the V6 candidate: {win} ({path}). Rule: lowest mean falls over the shared cells, minus 0.15 x the 15 mm step-up success, with flat-ground falls ruled out. Promotion and deployment are left to the user.")
    if win != "layer 1":
        r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", "trained/V6L2cand_ppo.onnx", "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind"],
                           capture_output=True, text=True)
        if r.returncode != 0 or "MISMATCH" in r.stdout:
            decision(f"export of {win} failed ({(r.stdout + r.stderr)[-200:]}); falling back to layer 1's exported V6cand_ppo.onnx")
            win, path = "layer 1", l1_path(st)
        else:
            log("EXPORTED trained/V6L2cand_ppo.onnx (+ .onnx.json); not promoted, not deployed (the user decides)")
    open("trained/v6_candidate.txt", "w").write(f"{win}\n{path}\n{'trained/V6cand_ppo.onnx' if win == 'layer 1' else 'trained/V6L2cand_ppo.onnx'}\n")
    st["chosen"] = dict(name=win, path=path)
    save_state(st)


def summary6(st):
    if st.get("summary") == "done":
        return
    import html as H
    base = json.load(open(f"{REPORT_DIR}/v6.json"))
    rows = [("V6 layer 1", base), ("V5", json.load(open(V5_JSON))), ("V4", json.load(open(V4_JSON))), ("Scripted walk", json.load(open(SCRIPTED_JSON)))]
    for key, label in (("l2", "V6 layer 2"), ("l2b", "V6 Plan B")):
        if os.path.exists(f"{REPORT_DIR}/{key}.json"):
            rows.insert(1, (label, json.load(open(f"{REPORT_DIR}/{key}.json"))))
    ids = shared_ids(*(r for _, r in rows))
    body = ""
    for label, r in rows:
        c, L = cm(r), r["size_ladder"]["summary"]
        m = l2_metrics(r, ids)
        body += (f"<tr><td>{H.escape(label)}</td><td>{m['mean']:.3f}</td><td>{'none' if m['flat'] else 'yes'}</td><td>{m['heading']:.0f}</td><td>{m['asym']:.1f}</td>"
                 f"<td>{' / '.join(f'{v:.2f}' for v in L['ledge_up']['success'])}</td><td>{' / '.join(f'{v:.2f}' for v in L['ledge_up']['falls'])}</td>"
                 f"<td>{' / '.join(f'{v:.2f}' for v in L['ledge_down']['success'])}</td></tr>")
    dec = "".join(f"<li>{H.escape(l[2:])}</li>" for l in open(DECISIONS).read().splitlines() if l.startswith("- ")) if os.path.exists(DECISIONS) else ""
    chosen = st.get("chosen", {})
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>V6 Summary</title>
<style>:root{{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b64;--line:#dcdcd2;--card:#fff}}@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161614;--fg:#ecece6;--mut:#a3a39a;--line:#34342f;--card:#1f1f1c}}}}
:root[data-theme="dark"]{{--bg:#161614;--fg:#ecece6;--mut:#a3a39a;--line:#34342f;--card:#1f1f1c}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:980px;margin-inline:auto}}h1{{font-size:1.5rem}}h2{{font-size:1.1rem;margin-top:1.6rem}}
.t{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.88rem;background:var(--card)}}th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left}}th{{color:var(--mut);font-weight:600}}
li{{margin:.35rem 0}}.mut{{color:var(--mut)}}</style></head><body><h1>V6 Summary</h1>
<p>Chosen candidate: <b>{H.escape(str(chosen.get('name', 'none yet')))}</b> ({H.escape(str(chosen.get('path', '')))}). Not promoted, not deployed: that is your call. Numbers are 100 paired episodes per cell on the same {len(ids)} cells; ledge columns are the four sizes 7.5 / 15 / 22.5 / 30 mm.</p>
<h2>Candidates</h2><div class="t"><table><tr><th>Policy</th><th>Mean falls</th><th>Flat falls</th><th>Heading (deg)</th><th>Asymmetry</th><th>Step-up success</th><th>Step-up falls</th><th>Step-down success</th></tr>{body}</table></div>
<h2>Decisions made while you were away</h2><ul>{dec}</ul>
<p class="mut">Full per-hazard report for layer 1: report.html in the same folder; the plan, stage results and Layer 2 / Plan B design: docs/plan-detail/v6-staged-training-plan.md.</p></body></html>"""
    open(f"{REPORT_DIR}/summary.html", "w").write(page)
    st["summary"] = "done"
    save_state(st)
    log(f"SUMMARY ready: rl_training/opencat-gym/{REPORT_DIR}/summary.html (publish it as an Artifact page)")



def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    st = load_state()
    st.setdefault("screens", {})
    st["adopted"] = list(ADOPTED)
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    preflight6(st)
    prev = None
    for name, lever, steps, minutes in STAGES:
        run_stage(name, lever, steps, minutes, prev)
        prev = TAG(name)
    go_no_go(st)
    final6(st)
    pick6(st)
    report6(st)
    layer2(st)
    choose_and_export(st)
    summary6(st)
    log("V6 COMPLETE")


def status():
    st = load_state()
    print("preflight:", st.get("preflight", "-"))
    for name, lever, steps, _ in STAGES:
        print(f"  {name} {lever:14s} {steps}:", "done" if os.path.exists(f"trained/{TAG(name)}_ppo.zip") else ("training" if RP.training(TAG(name)) else "-"))
    print("go:", st.get("go", "-"), "| s4 (20M):", st.get("final", "-"), "tracked", st.get("tracked", []), "| picked:", st.get("picked", "-"), "| report:", st.get("report", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


def plan():
    for name, lever, steps, minutes in STAGES + [FINAL]:
        e = stage_env(name, lever, last=(name == FINAL[0]))
        print(f"{name}: {steps} steps, about {minutes} min, {'fresh' if name == 's0' else 'chained'}; " + ", ".join(f"{k.replace('G2E_', '')}={e[k]}" for k in
              ("G2E_FR_ANCHOR", "G2E_FR_SHARE_SET", "G2E_LR_SCALE", "G2E_LR_FLOOR", "G2E_FRONTIER_FLOOR", "G2E_FR_PASS_H", "G2E_FAC_EDGE_STALL", "G2E_FAC_EDGE_LIFT", "G2E_HAZ_POSTURE_RELAX", "G2E_PLATEAU_STOP") if k in e))


def smoke():
    """Two tiny chained stages (60k steps each) with the real stage environments, to prove the chain, the new rewards and the stage mixes run end to end; deletes what it made."""
    prev = None
    for name, lever in (("smoke0", "v6_s0_flat"), ("smoke1", "v6_l2_ledges"), ("smoke2", "v6_l2_mixed")):
        tag = TAG(name)
        clean_environ()
        RP.launch(tag, stage_env(name, lever), steps="60000", base=False, chain_from=(f"trained/{prev}_ppo" if prev else None))
        ok, why = RP.wait_for_finish(tag)
        print(name, "finished" if ok else f"FAILED: {why}", flush=True)
        c = open(f"trained/{tag}_console.log").read() if os.path.exists(f"trained/{tag}_console.log") else ""
        print("  action noise reset line:", "action noise reset" in c, "| chaining line:", "chaining from" in c, flush=True)
        if not ok:
            break
        prev = tag
    for n in ("smoke0", "smoke1", "smoke2"):
        for f in [f for f in os.listdir("trained") if f.startswith(f"v6_{n}")]:
            p = os.path.join("trained", f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        for f in [f for f in os.listdir("trained/checkpoints") if f.startswith(f"v6_{n}")]:
            os.remove(os.path.join("trained/checkpoints", f))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "status": status, "plan": plan, "smoke": smoke}[cmd]()
