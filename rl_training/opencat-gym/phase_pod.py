"""POD: the V6 recipe, unchanged, retrained from scratch on the new payload (the 185 g pod + the 42 g AI head, sim profile "pod"; user, 2026-10-18). A copy of phase_v6.py with its own tags (pod_*),
state, log, report and candidate names so the V6 files are never touched; it never promotes or deploys anything, and it does not compare against V4/V5 (their numbers are on the old payload).

(The V6 docstring follows.) V6: a chain of short skill stages, then a 20M consolidation, run unattended (plan: docs/plan-detail/v6-staged-training-plan.md; user approved 2026-10-09).

    python phase_pod.py run       # preflight -> S0 -> S1 -> S2 -> S3 -> S3 flat-ground check -> S4 (20M) -> pick (average of the last 5) -> export
    python phase_pod.py status | plan

Recipe (all stages): the V5 recipe plus the four adopted screens (crossing bonus, hazard-aware speed and posture, heading-blind) and the 30 mm ledge tops. Each stage adds its own mix of
episodes (g2_profile levers v6_s0_flat ... v6_s4_all). S0 is a fresh run; every later stage starts from the previous stage's final weights with a fresh-run learning-rate schedule that
decays inside the stage (train.py --chain-from). The go/no-go for the 20M is Claude's (user, 2026-10-09); nothing is promoted or deployed here. Reuses phase_v5.py's helpers with
its module settings pointed at the V6 files. Log trained/phase_pod.log, state trained/pod_state.json, halt trained/pod_halt (tools/pod_watchdog.sh keeps it alive)."""
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

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_pod.log", "trained/pod_halt", "trained/pod_state.json", "trained/pod_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR


def log(msg):
    line = f"[pod {time.strftime('%I:%M %p')}] {msg}"
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
TAG = lambda n: f"pod_{n}"                                          # noqa: E731
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
    out = f"trained/pod_score_{name}.json"
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
    """The user asked for the 20M (2026-10-18), so it starts unless S3 falls on flat ground (T1.1, N1) or walks badly; the V4/V5 comparison of the V6 plan is not used (those are on the old payload)."""
    if st.get("go"):
        return
    s3 = json.load(open("trained/pod_score_s3.json"))
    c = cm(s3)
    flat = all(c[i]["fell_fraction"] == 0 for i in ("T1.1", "N1"))
    head, asym = c["N1"]["heading_abs_mean_deg"], c["N1"]["lr_asym_max_deg"]
    log(f"S3 CHECK | flat falls none = {flat} | calm walk heading {head:.0f} asym {asym:.1f}")
    if not flat or head > 30:
        halt(f"DECISION NEEDED: S3 falls on flat ground or its heading is over 30 deg (flat none = {flat}, heading {head:.0f}); review trained/pod_score_s3.json before the 20M")
    st["go"] = True
    save_state(st)
    log("S3 GO: the 20M consolidation starts now (the user asked for it)")


def track6(step, levers):
    """The 1M tracker, with 40 episodes (V5's 12-20 were too noisy to steer by) on 3 workers while training runs."""
    tag = TAG(FINAL[0])
    ck = f"trained/checkpoints/{tag}_{step}_steps"
    out = f"trained/.pod_track_{step}.json"
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
    row["t"] = time.time()
    with open(f"trained/{tag}_curve.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    su, sd = s["ledge_up"], s["ledge_down"]
    log(f"{tag} TRACK {step // 10**6}M | N1 heading {row['heading']:.0f} asym {row['asym']:.1f} roll {row['roll']:.1f} speed {row['speed']:.3f} | step-up falls {su['mean_falls']:.2f} "
        f"success {[round(x, 2) for x in su['success']]} | step-down falls {sd['mean_falls']:.2f} success {[round(x, 2) for x in sd['success']]} | rubble {s['rubble']['mean_falls']:.2f} | "
        f"side-hill L/R {s['sidehill_l']['mean_falls']:.2f}/{s['sidehill_r']['mean_falls']:.2f} | mirror {res.get('mirror_gap') or float('nan'):.3f}{projected_finish(tag, row)}")
    return row


def projected_finish(tag, row):
    """' | training done about HH:MM PM' from the pace of the last three checkpoints (the pace drifts: the trackers share the CPU and the courses get heavier, so a start-of-run estimate is too short).
    Training only: the scoring steps after it (final, averaged candidate, report, export) take about 25 min more and are announced when they start."""
    try:
        target = {TAG(n): float(st) for n, _l, st, _m in STAGES}
        target[TAG(FINAL[0])] = float(FINAL[2])
        rows = [json.loads(l) for l in open(f"trained/{tag}_curve.jsonl")][-4:]
        rows = [r for r in rows if "t" in r]
        if len(rows) < 3 or tag not in target or row["step"] >= target[tag]:
            return ""
        pace = (rows[-1]["t"] - rows[0]["t"]) / max(rows[-1]["step"] - rows[0]["step"], 1)     # seconds per step over the last checkpoints
        return f" | training done about {time.strftime('%I:%M %p', time.localtime(time.time() + pace * (target[tag] - row['step'])))}"
    except (OSError, ValueError, KeyError):
        return ""


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
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", "trained/PODcand_ppo.onnx", "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind"],
                       capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log("EXPORTED trained/PODcand_ppo.onnx (+ .onnx.json); not promoted, not deployed (the user decides)")
    shutil.copy(f"{REPORT_DIR}/{best}.json", f"{REPORT_DIR}/pod.json")
    st["picked"] = best
    save_state(st)


def preflight6(st):
    if st.get("preflight") == "pass":
        return
    levers = BASE6 + ["v6_s2_ledges"]                                   # the stage with the new rewards (the lever names stay v6_*: they are the recipe)
    log(f"PREFLIGHT on the V6 recipe (new payload) with the ledge-stage rewards (about 15 min, done about {clock_in(15)})")
    r = subprocess.run([sys.executable, "preflight.py", "--levers", ",".join(levers)], capture_output=True, text=True)
    open("trained/pod_preflight.log", "w").write(r.stdout + r.stderr)
    if "ALL PASS" not in r.stdout:
        halt(f"HALT: preflight FAILED (trained/pod_preflight.log): {[l for l in r.stdout.splitlines() if 'FAIL' in l][:6]}")
    st["preflight"] = "pass"
    save_state(st)
    log("PREFLIGHT ALL PASS")



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
    log("POD COMPLETE")


def status():
    st = load_state()
    print("preflight:", st.get("preflight", "-"))
    for name, lever, steps, _ in STAGES:
        print(f"  {name} {lever:14s} {steps}:", "done" if os.path.exists(f"trained/{TAG(name)}_ppo.zip") else ("training" if RP.training(TAG(name)) else "-"))
    print("go:", st.get("go", "-"), "| s4 (20M):", st.get("final", "-"), "tracked", st.get("tracked", []), "| picked:", st.get("picked", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


def plan():
    for name, lever, steps, minutes in STAGES + [FINAL]:
        e = stage_env(name, lever, last=(name == FINAL[0]))
        print(f"{name}: {steps} steps, about {minutes} min, {'fresh' if name == 's0' else 'chained'}; payload {e.get('G2E_PAYLOAD_PROFILE')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "status": status, "plan": plan}[cmd]()
