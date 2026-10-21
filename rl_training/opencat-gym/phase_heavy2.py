"""HEAVY2: V7 made steadier with the pod, by a fine-tune of V7 itself (user, 2026-10-19: "lets train on top of v7 this time"; the standing rule against training on a
finished 20M is set aside for this run by the user). Plan and rules: docs/planned/heavy-load-training-plan.md section "Attempt 2".

    python phase_heavy2.py run      # fine-tune (up to 20M, tracked every 2M, cut off when the curve flattens) -> finalists -> benchmarks against V7 -> pick -> export -> report
    python phase_heavy2.py status

Rules (fixed 2026-10-19, before any result):
  training      V7 (trained/pod_s4_ppo) fine-tuned with the V7 recipe + its 20M stage + heavy_ft: half the episodes carry today's payload, the rest up to +227 g (1 lb in all)
                with the cap growing from 0 over the first 6M; slower commands only with extra weight (60% at 1 lb); a crouch of 1.5 mm at today's payload growing to 4 mm (0.16 in)
                at 1 lb; 12.5 s obstacle episodes; action noise reset to std 0.15; the trainer's fine-tune learning rate (3e-5, constant). No plateau stop.
  tracking      every 2M: benchmark_load at today's payload and at 1 lb, 9 cells, 100 paired episodes per cell. today_score = mean falls at today's payload + 0.02 x the calm sway there.
  cutoff        the weight range is complete at 6M; from then on, if 3 checks in a row (6M) do not beat the best today_score before them by 0.005, the run is ended
                (so not before 12M)
                there (the checkpoints are kept); otherwise it runs to 20M.
  finalists     the 3 tracked checkpoints with the best today_score, plus the final weights; each scored on the full load ladder (13 cells x 4 loads, 100 episodes) and the
                31-cell V5 benchmark at today's payload. V7 is scored the same way.
  pass          (1) today's payload: V5 mean falls at least 0.02 below V7's; (2) the ladder: falls no more than V7's + 0.01 at every load; (3) flat ground: no more than 2% falls
                on T1.1 / N1 at any load; (4) still walks: calm speed at 1 lb at least half the command; (5) paw lift on flat ground no lower than V7's at that load minus the crouch
                there minus 1 mm (0.04 in). The pick is the passing finalist with the lowest V5 mean falls; if none passes, the lowest V5 mean falls is exported and the report says
                it failed. Nothing is promoted or deployed.
  control       (added 2026-10-19 before the fine-tune's results, user: "is V7 better just from more exposure?") after the fine-tune is scored: the SAME fine-tune of V7
                without the weight changes (no extra load, no crouch, no slower commands; the 12.5 s obstacle episodes, the noise reset and the learning rate kept), trained
                to the step the fine-tune ended at (its cutoff, else 20M), tracked the same way, no cutoff. Its finalists are scored and judged by the same rules (crouch 0
                in the paw rule) and exported as trained/HEAVY2ctrl_cand_ppo.onnx. Comparison of the two picks: if the control's V5 mean falls are within 0.01 of the
                fine-tune's (or lower), the gain is put down to more training, not the weight changes."""
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, ".")
import g2_profile
import phase_v5 as V5
import run_pipeline as RP

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_heavy2.log", "trained/heavy2_halt", "trained/heavy2_state.json", "trained/heavy2_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR
DECISIONS = f"{REPORT_DIR}/decisions.md"


def log(msg):
    line = f"[heavy2 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.log = log
load_state, save_state, clock_in, cm = V5.load_state, V5.save_state, V5.clock_in, V5.cm

ADOPTED = ["cross_bonus", "haz_speed", "haz_posture", "heading_blind"]
BASE6 = V5.BASE + ADOPTED + ["ledge30"]                            # the V7 recipe
LEVERS = BASE6 + ["v6_s4_all", "heavy_ft"]                         # + V7's 20M stage, + the fine-tune's load / crouch / episode changes (heavy_ft last: it overrides hazard_long)
TAG = "heavy2_ft"
CTRL_TAG, CTRL_LEVERS = "heavy2_ctrl", BASE6 + ["v6_s4_all", "ft_ctrl"]
CTRL_ONNX = "trained/HEAVY2ctrl_cand_ppo.onnx"
V7_POLICY, V7_LEVERS, V7_V5_JSON = "trained/pod_s4_ppo", ["privileged_critic", "heading_blind"], "trained/pod_report/pod.json"
STEPS, MINUTES = 20_000_000, 150
TRACK_EVERY, CUT_MIN, CUT_CHECKS, CUT_EPS = 2_000_000, 12_000_000, 3, 0.005
TRACK_CELLS = ("T1.1", "N1", "T1.2", "T2.1", "T3.1", "T5.1", "T7.1", "T8.1", "N4")
TRACK_LOADS = (0.0, 0.227)
EPISODES, N_FINALISTS = 100, 3
V5_MARGIN, LADDER_SLACK, FLAT_MAX, SPEED_MIN, PAW_SLACK_MM = 0.02, 0.01, 0.02, 0.5, 1.0
CROUCH0_MM, CROUCH_MM = 1.5, 4.0
CAND_ONNX = "trained/HEAVY2cand_ppo.onnx"


def decision(msg):
    os.makedirs(REPORT_DIR, exist_ok=True)
    log("DECISION " + msg)
    with open(DECISIONS, "a") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %I:%M %p')}: {msg}\n")


def clean_environ():
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP


def job_env(tag=TAG, levers=LEVERS):
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
    env.pop("G2E_PLATEAU_STOP", None)                                 # the user: the curve decides, through the cutoff rule above
    return {k: v for k, v in env.items() if v != ""}


def ladder(policy, out, loads=None, cells=None, episodes=EPISODES, jobs=8):
    """benchmark_load in a fresh process; cached in `out`."""
    if os.path.exists(out):
        return json.load(open(out))
    t0 = time.time()
    args = [sys.executable, "-c", "import sys, json; sys.path.insert(0, '.'); import benchmark_load as L; "
            f"r = L.run({policy!r}, {tuple(V7_LEVERS)!r}, {episodes}, {jobs}" + (f", loads={loads!r}" if loads else "") + (f", cells={cells!r}" if cells else "")
            + f"); json.dump(r, open({out!r}, 'w'), indent=1)"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        log(f"load scoring of {policy} failed: {(r.stdout + r.stderr)[-400:]}")
        return None
    res = json.load(open(out))
    log(f"LADDER {policy} ({episodes} eps, {(time.time() - t0) / 60:.0f} min) | {line(res['summary'])}")
    return res


def today_score(s):
    k = min(s["per_load"], key=float)
    return s["light_falls"] + 0.02 * s["per_load"][k]["sway"]


def line(s):
    return (f"today score {today_score(s):.3f} (falls {s['light_falls']:.3f}) | flat falls {s['flat_falls']:.2f} | 1 lb speed ratio {s['speed_ratio']:.2f} | "
            "falls / paw mm by load " + " | ".join(f"{float(k) * 1000:.0f} g {v['falls']:.3f} / {v.get('paw_mm') or 0:.1f}" for k, v in s["per_load"].items()))


def finetune(root, s=None, tag=TAG, levers=LEVERS, steps=STEPS, use_cutoff=True, what="fine-tune of V7"):
    """Train one fine-tune of V7 and track it every 2M. `s` is its part of the state (the weight fine-tune keeps its keys at the top level, the control under "ctrl")."""
    s = root if s is None else s
    if s.get("trained") == "done":
        return
    started = glob.glob(f"trained/checkpoints/{tag}_*_steps.zip")
    if not RP.training(tag) and started and not os.path.exists(f"trained/{tag}_ppo.zip") and not s.get("cut_at"):
        decision(f"{tag} is not running but has {len(started)} checkpoints (it stopped, or the runner was restarted): not started again (that would wipe them); "
                 "the finalists come from the checkpoints it saved")
        s["cut_at"] = max(int(re.search(r"_(\d+)_steps", p).group(1)) for p in started)
        save_state(root)
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip") and not s.get("cut_at"):
        clean_environ()
        mins = round(MINUTES * steps / STEPS)
        log(f"{tag} START: {what} ({V7_POLICY}), {'up to ' if use_cutoff else ''}{steps // 10**6}M, about {mins} min, done about {clock_in(mins)}")
        RP.launch(tag, job_env(tag, levers), steps=str(steps), base=False, from_ckpt=V7_POLICY)
    curve = s.setdefault("curve", {})
    step = TRACK_EVERY
    while step <= steps and not s.get("cut_at"):
        if str(step) in curve:
            step += TRACK_EVERY
            continue
        ok, _why = RP.wait_for_ckpt(tag, step)
        if not ok:
            break
        res = ladder(RP.ckpt(tag, step)[:-4], f"trained/.{tag}_track_{step}.json", loads=TRACK_LOADS, cells=TRACK_CELLS, jobs=4)
        if res:
            curve[str(step)] = res["summary"]
            if os.path.exists(f"trained/.{tag}_track_{step}.json"):
                os.remove(f"trained/.{tag}_track_{step}.json")
            log(f"{tag} TRACK {step // 10**6}M | {line(res['summary'])}")
            save_state(root)
            if use_cutoff and cutoff(root, s, step):
                break
        step += TRACK_EVERY
    if s.get("cut_at"):
        if RP.training(tag):
            RP.stop(tag)
    else:
        ok, why = RP.wait_for_finish(tag)
        if not ok:
            decision(f"{tag} stopped before {steps // 10**6}M ({why}); the finalists come from the checkpoints it saved")
    s["trained"] = "done"
    save_state(root)
    log(f"{tag} FINISHED")


def cutoff(root, st, step):
    if step < CUT_MIN:
        return False
    pts = sorted((int(k), today_score(v)) for k, v in st["curve"].items())
    best_t, best = min(pts, key=lambda p: p[1])
    recent = [p for p in pts if p[0] > step - CUT_CHECKS * TRACK_EVERY]
    before = [s for t, s in pts if t <= step - CUT_CHECKS * TRACK_EVERY]
    if len(recent) < CUT_CHECKS or not before:
        return False
    if min(s for _, s in recent) > min(before) - CUT_EPS:
        decision(f"CUTOFF at {step // 10**6}M: the today's-payload score has not improved by {CUT_EPS} in the last {CUT_CHECKS} checks "
                 f"(best {best:.3f} at {best_t // 10**6}M); the run ends here and the finalists are picked from the checkpoints")
        st["cut_at"] = step
        save_state(root)
        return True
    return False


def passes(H, V, h5, v5, crouch0=CROUCH0_MM, crouch1=CROUCH_MM):
    """The five pass rules above; returns the list of failures (empty = passes) and the V5 mean falls of both."""
    hs, vs = H["summary"], V["summary"]
    why = []
    ids = [i for i in cm(h5) if i in cm(v5) and not i.startswith(("Z.", "N")) and i != "Z0"] if h5 else []
    mh = sum(cm(h5)[i]["fell_fraction"] for i in ids) / len(ids) if ids else float("nan")
    mv = sum(cm(v5)[i]["fell_fraction"] for i in ids) / len(ids) if ids else float("nan")
    if not ids or not mh <= mv - V5_MARGIN:
        why.append(f"today's payload: V5 mean falls {mh:.3f}, needs {mv - V5_MARGIN:.3f} or less (V7 {mv:.3f})")
    for k in hs["per_load"]:
        if hs["per_load"][k]["falls"] > vs["per_load"][k]["falls"] + LADDER_SLACK:
            why.append(f"+{float(k) * 1000:.0f} g: falls {hs['per_load'][k]['falls']:.3f} > V7 {vs['per_load'][k]['falls']:.3f} + {LADDER_SLACK}")
        crouch = crouch0 + (crouch1 - crouch0) * min(1.0, float(k) / 0.227)
        need = (vs["per_load"][k].get("paw_mm") or 0) - crouch - PAW_SLACK_MM
        if (hs["per_load"][k].get("paw_mm") or 0) < need:
            why.append(f"+{float(k) * 1000:.0f} g: paw lift {hs['per_load'][k].get('paw_mm') or 0:.1f} mm < {need:.1f}")
    if hs["flat_falls"] > FLAT_MAX:
        why.append(f"flat-ground falls {hs['flat_falls']:.2f} > {FLAT_MAX}")
    if hs["speed_ratio"] < SPEED_MIN:
        why.append(f"1 lb speed ratio {hs['speed_ratio']:.2f} < {SPEED_MIN}")
    return why, mh, mv, ids


def v5_bench(policy, out):
    for attempt in (1, 2):
        if os.path.exists(out):
            return json.load(open(out))
        log(f"V5 benchmark of {policy} (about 10 min, done about {clock_in(10)})")
        r = subprocess.run([sys.executable, "benchmark_v5.py", "--policy", policy, "--levers", ",".join(V7_LEVERS), "--json-out", out,
                            "--episodes", str(V5.FINAL_EPISODES), "--ladder-episodes", str(V5.FINAL_LADDER_EPISODES), "--jobs", "8"], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"V5 benchmark attempt {attempt} of {policy} failed: {(r.stdout + r.stderr)[-400:]}")
    return None


def finals(root, st=None, tag=TAG, prefix="", onnx=CAND_ONNX, crouch=(CROUCH0_MM, CROUCH_MM), label="fine-tune",
           note="heavy2: V7 fine-tuned for the pod (half the episodes at today's payload, the rest up to 1 lb), slight crouch; same inputs as V7"):
    """Score one run's finalists against V7, pick, export. The weight fine-tune keeps its keys at the top level of the state, the control under "ctrl"."""
    st = root if st is None else st
    if st.get("picked"):
        return
    V = ladder(V7_POLICY, f"{REPORT_DIR}/v7_load.json")
    v5 = json.load(open(V7_V5_JSON))
    curve = st.get("curve", {})
    best = sorted(curve, key=lambda k: today_score(curve[k]))[:N_FINALISTS]
    cands = {f"{int(k) // 10**6}M": RP.ckpt(tag, int(k))[:-4] for k in best if os.path.exists(RP.ckpt(tag, int(k)))}
    if os.path.exists(f"trained/{tag}_ppo.zip"):
        cands["final"] = f"trained/{tag}_ppo"
    if not cands:
        cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
        if cks:
            cands["last"] = cks[-1][:-4]
    decision(f"{label} finalists: {', '.join(cands) or 'none'} (the {N_FINALISTS} best tracked checkpoints by today's-payload score, plus the final weights)")
    rows = {}
    for name, path in cands.items():
        H = ladder(path, f"{REPORT_DIR}/{prefix}{name}_load.json")
        h5 = v5_bench(path, f"{REPORT_DIR}/{prefix}{name}_v5.json")
        if not H or not V:
            continue
        why, mh, mv, ids = passes(H, V, h5, v5, *crouch)
        rows[name] = dict(path=path, why=why, v5=mh, v5_v7=mv, cells=len(ids))
        decision(f"{label} finalist {name}: V5 mean falls {mh:.3f} (V7 {mv:.3f}) | {line(H['summary'])} | {'PASSES' if not why else 'fails: ' + '; '.join(why)}")
    ok = {k: r for k, r in rows.items() if not r["why"]}
    pool = ok or rows
    if not pool:
        decision(f"{label}: no finalist could be scored: no candidate")
        st["picked"] = "none"
        save_state(root)
        return
    pick = min(pool, key=lambda k: pool[k]["v5"] if pool[k]["v5"] == pool[k]["v5"] else 9.9)
    r = rows[pick]
    side = {"levers": [x for x in V7_LEVERS if x != "privileged_critic"], "payload_profile": "pod", "note": note}
    e = subprocess.run([sys.executable, "export_onnx.py", "--model", r["path"], "--out", onnx, "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind",
                        "--sidecar-extra", json.dumps(side)], capture_output=True, text=True)
    exported = e.returncode == 0 and "MISMATCH" not in e.stdout
    decision(f"{label} PICKED {pick} ({r['path']}): {'PASSES every rule' if not r['why'] else 'FAILS: ' + '; '.join(r['why'])}"
             + (f"; exported {onnx} (+ .onnx.json)" if exported else f"; export failed ({(e.stdout + e.stderr)[-200:]})") + ". Not promoted, not deployed (the user decides)")
    st["picked"], st["picked_path"], st["verdict"], st["picked_v5"] = pick, r["path"], ("pass" if not r["why"] else "fail"), r["v5"]
    save_state(root)


def control(root):
    """The control (docstring): the same fine-tune of V7 without the weight changes, to the step the fine-tune ended at; then its finalists and the comparison."""
    c = root.setdefault("ctrl", {})
    steps = int(root.get("cut_at") or STEPS)
    if "steps" not in c:
        c["steps"] = steps
        save_state(root)
        decision(f"CONTROL starts: V7 fine-tuned the same way without the weight changes, for {steps // 10**6}M steps (the fine-tune ended at {steps // 10**6}M)")
    finetune(root, c, CTRL_TAG, CTRL_LEVERS, c["steps"], use_cutoff=False, what="control fine-tune of V7, no weight changes")
    finals(root, c, CTRL_TAG, "ctrl_", CTRL_ONNX, (0.0, 0.0), "control",
           "heavy2 control: V7 fine-tuned with the same settings minus the weight changes (more training, 12.5 s obstacle runs); same inputs as V7")
    if c.get("compared") or c.get("picked") in (None, "none") or root.get("picked") in (None, "none"):
        return
    w, k = root.get("picked_v5"), c.get("picked_v5")
    if w is None:                                                       # the fine-tune's pick was scored by the runner before the control existed: read its V5 file
        h5 = json.load(open(f"{REPORT_DIR}/{root['picked']}_v5.json")) if os.path.exists(f"{REPORT_DIR}/{root['picked']}_v5.json") else None
        v5 = json.load(open(V7_V5_JSON))
        ids = [i for i in cm(h5) if i in cm(v5) and not i.startswith(("Z.", "N")) and i != "Z0"] if h5 else []
        w = sum(cm(h5)[i]["fell_fraction"] for i in ids) / len(ids) if ids else None
    if w is None or k is None:
        decision("COMPARISON fine-tune vs control: not measured (a V5 score is missing)")
    else:
        more = k <= w + 0.01
        decision(f"COMPARISON at today's payload: weight fine-tune V5 mean falls {w:.3f} ({root.get('verdict')}), control {k:.3f} ({c.get('verdict')}) -> "
                 + ("the control is as good or better: the gain is put down to more training, not the weight changes" if more
                    else "the weight fine-tune is better by more than 0.01: the weight changes helped beyond more training"))
    c["compared"] = True
    save_state(root)


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}")
    os.makedirs(REPORT_DIR, exist_ok=True)
    st = load_state()
    clean_environ()
    finetune(st)
    finals(st)
    log("HEAVY2 COMPLETE")                                             # the weight fine-tune is done (the old watchdog stopped here)
    control(st)
    log("HEAVY2 ALL COMPLETE")


def status():
    st = load_state()
    print("training:", st.get("trained", "training" if RP.training(TAG) else "-"), "| cut at:", st.get("cut_at", "-"))
    for k in sorted(st.get("curve", {}), key=int):
        print(f"  {int(k) // 10**6:2d}M", line(st["curve"][k]))
    print("picked:", st.get("picked", "-"), "| verdict:", st.get("verdict", "-"))
    c = st.get("ctrl", {})
    print("control:", c.get("trained", "training" if RP.training(CTRL_TAG) else "-"), "| steps:", c.get("steps", "-"), "| picked:", c.get("picked", "-"), "| verdict:", c.get("verdict", "-"))
    for k in sorted(c.get("curve", {}), key=int):
        print(f"  {int(k) // 10**6:2d}M", line(c["curve"][k]))


if __name__ == "__main__":
    {"run": run, "status": status}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
