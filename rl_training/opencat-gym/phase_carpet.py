"""CARPET (user, 2026-10-20): a carpet-only gait for G2, unattended end to end. The fit and the real walks behind it: carpet_fit.py and the "Carpet Fall Check" page (V7 on the
fitted carpet: 95% falls, all to the right, as on G2's carpet). The user approved the plan, pre-approved the 20M, asked that training not stop, that judgment calls be made and
logged, and that it keep iterating until a policy walks on carpet.

    python phase_carpet.py run       # G1 -> G2 -> G3 -> G4 (20M) -> G5 (pick, export) [-> up to two more 20M passes]; resumable; a run still training is waited for, never restarted
    python phase_carpet.py status
    bash ../../tools/carpet_watchdog.sh   # keeps `run` alive (relaunches it if it dies; stops on trained/carpet_halt or "CARPET ALL COMPLETE")

History: round 1 (11:04 AM - 11:45 AM, state trained/carpet_state.json) trained the V7 course with carpet on half the flat-floor episodes, and it failed: the carpet under ledges,
boxes and slopes wrecked the ledge skill and taught no carpet walking (fitted-carpet falls: control 0.60, candidate 0.88). The user then set the course: carpet only.

What it trains: a carpet-only policy (its own policy file; on G2, "G2, carpet mode" loads it and "switch to default gait" goes back to V7). It branches the V7 chain at its
slopes stage (trained/pod_s3_ppo, before V7's 20M consolidation; the finished V7 is never trained on), with V7's recipe (BASE6), the fitted body (carpet_body: servo strength
0.10-0.15, the pod's weight 0-8 mm to G2's right) and the carpet ground (carpet_ground: every episode hazard-free, 12.5 s, on carpet; the carpet's difficulty adapts per env,
from near-hard up past the fitted carpet, raised only when the policy succeeds at its current level).

Rules (fixed 2026-10-20 before any result; the user's only criterion: "did it improve performance when walking on carpet" -- no V7 comparison decides anything):
  carpet tests  the fitted carpet (stiffness 120, damping 2, 12 mm, grip 2.2), the harsh carpet (80, 1.5, 14 mm, 2.6) and, for information, a hard floor; all with the fitted
                body (servo strength 0.10, pod 8 mm right), paired episodes (40; 100 for the 20M picks). "Walks" = at least half the commanded distance on the fitted carpet.
  G1   the carpet ground, 3M from pod_s3, seed 42. Improves if fitted-carpet falls are at least 0.10 below round 1's best (its control, 0.60) and it walks. G2 builds on it either way.
  G2   one carpet change at a time on top of the best recipe so far, each 3M from pod_s3:
         carpet_speed    commands 50-100% of the drawn speed, speed tracking half-weight (the policy is scored at 75% of 0.10 m/s on carpet)
         carpet_loose    imitation and diagonal-footfall weights halved
         carpet_recover  the stumble "fight back toward level" reward doubled
       Adopted (and kept for the next ones) if fitted-carpet falls drop by at least 0.10 against the best so far and it walks; else rejected. A run that stops itself (health
       check) or crashes twice is rejected.
  G3   the final recipe as a 5M carpet stage from pod_s3, seeds 42 and 43; the pick: fewer fitted-carpet falls, then fewer harsh-carpet falls.
  G4   the 20M consolidation on the carpet ground, chained from the G3 pick: the recipe + carpet_consol (V7's 20M learning rate, 0.4, decaying to zero) and V7's plateau stop.
  G5   the final weights and the average of the last 5 checkpoints on the carpet tests (100 episodes); the pick: fewer fitted-carpet falls, then fewer harsh-carpet falls.
       Improves if its fitted-carpet falls are below the G3 pick's. Exported as trained/CARPETcand_ppo.onnx (+ sidecar) either way.
  walks on carpet (the goal): fitted-carpet falls at most 0.20 and it walks. If G5 misses it and the 20M cut fitted-carpet falls by at least 0.05, another 20M pass runs from the
       G5 pick (G4/G5 again, at most two extra passes); otherwise the plan ends and says what it reached. V7's carpet numbers are reported for information only.
Nothing is promoted or deployed (the user decides). Every decision is one "DECISION" line in trained/phase_carpet.log; results in trained/carpet_report/."""
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, ".")
import carpet_fit as CF
import g2_profile
import phase_pod as PP
import phase_v5 as V5
import run_pipeline as RP

LOG, STATE, OLD_STATE, REPORT_DIR, HALT = "trained/phase_carpet.log", "trained/carpet_ground_state.json", "trained/carpet_state.json", "trained/carpet_report", "trained/carpet_halt"
FROM = "trained/pod_s3_ppo"
V7_POLICY, LEVERS = "trained/pod_s4_ppo", ["privileged_critic", "heading_blind"]       # the carpet policy has V7's inputs (no carpet-mode input)
RECIPE0 = ["carpet_body", "carpet_ground"]
G2_LEVERS = [("carpet_speed", "commands 50-100% of the drawn speed, speed tracking half-weight"),
             ("carpet_loose", "imitation and diagonal-footfall weights halved"),
             ("carpet_recover", "the stumble fight-back reward doubled")]
SETTINGS = {"fitted": dict(grid=(CF.FITTED_CARPET["k"],), damp=(CF.FITTED_CARPET["c"],), depth=CF.FITTED_CARPET["depth"], mu=CF.FITTED_CARPET["mu"]),
            "harsh": dict(grid=(CF.HARSH_CARPET["k"],), damp=(CF.HARSH_CARPET["c"],), depth=CF.HARSH_CARPET["depth"], mu=CF.HARSH_CARPET["mu"]),
            "hard": dict(grid=(0.0,), damp=(0.0,))}
EPISODES, FINAL_EPISODES = 40, 100
GAIN, GOAL_FALLS, PASS_GAIN, MAX_EXTRA = 0.10, 0.20, 0.05, 2
SCREEN_STEPS, STAGE_STEPS, CONSOL_STEPS = "3e6", "5e6", "20e6"
CAND_ONNX = "trained/CARPETcand_ppo.onnx"


def log(msg):
    line = f"[carpet {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = LOG, HALT, STATE, REPORT_DIR     # phase_pod pointed them at the pod files on import
V5.log = log


def decision(msg):
    log("DECISION " + msg)


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {"trained": {}, "scores": {}}


def save_state(st):
    json.dump(st, open(STATE, "w"), indent=1)


def carpet_cmd(recipe):
    return 0.10 * (0.75 if "carpet_speed" in recipe else 1.0)


def job_env(tag, levers, seed=42, last=False):
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(PP.BASE6) + levers})
    env["G2E_SEED"] = env["G2E_CHAIN_SEED"] = str(seed)
    if not last:
        env.pop("G2E_PLATEAU_STOP", None)                          # only the 20M may plateau-stop (as in V7's chain)
    return {k: v for k, v in env.items() if v != ""}


def carpet_levels(tag):
    """The carpet levels the run's envs reached: (median, highest) of the last changes, from the console's "[carpet level] a -> b" lines."""
    try:
        vals = [float(m) for m in re.findall(r"\[carpet level\] [\d.]+ -> ([\d.]+)", open(f"trained/{tag}_console.log").read())]
    except OSError:
        return None
    if not vals:
        return None
    tail = vals[-12:]
    return round(sorted(tail)[len(tail) // 2], 3), round(max(vals), 3)


def train_run(st, tag, levers, steps, chain_from, seed=42, last=False, minutes=20):
    """Train one run to the end (resumable). Returns the policy path, or None if it stopped itself or crashed twice."""
    if tag in st["trained"]:
        return st["trained"][tag]
    if not os.path.exists(f"trained/{tag}_ppo.zip"):
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_console.log"):         # an earlier attempt died
                if os.path.exists(f"trained/{tag}_crash1_console.log"):
                    decision(f"{tag} crashed twice: rejected, carrying on without it")
                    st["trained"][tag] = None
                    save_state(st)
                    return None
                for f in [f for f in os.listdir("trained") if f.startswith(tag + "_")]:
                    os.replace(os.path.join("trained", f), os.path.join("trained", f.replace(tag + "_", tag + "_crash1_", 1)))
                for f in [f for f in os.listdir("trained/checkpoints") if f.startswith(tag + "_")]:
                    os.remove(os.path.join("trained/checkpoints", f))
                decision(f"{tag} crashed: its files kept as {tag}_crash1_*, retrying once")
            for k in [k for k in os.environ if k.startswith("G2E_")]:
                del os.environ[k]
            log(f"{tag} START: levers {levers}, {steps} steps from {chain_from}, seed {seed}; about {minutes} min, done about {V5.clock_in(minutes)}")
            RP.launch(tag, job_env(tag, levers, seed, last), steps=steps, base=False, chain_from=chain_from)
        ok, why = RP.wait_for_finish(tag)
        if not ok:
            if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
                decision(f"{tag} stopped itself (its health check: it was not learning): rejected")
                st["trained"][tag] = None
                save_state(st)
                return None
            log(f"{tag} did not finish: {why}")
            return train_run(st, tag, levers, steps, chain_from, seed, last, minutes)
    st["trained"][tag] = f"trained/{tag}_ppo"
    save_state(st)
    log(f"{tag} FINISHED | carpet level (median, highest) {carpet_levels(tag)}")
    return f"trained/{tag}_ppo"


def line(c):
    return " | ".join(f"{n}: falls {c[n]['falls']:.2f} ({c[n]['right']}R/{c[n]['left']}L), {c[n]['dist_in_med']:.0f} in" for n in SETTINGS) + f" (carpet cmd {c.get('cmd', 0.10):.3f})"


def score(st, name, policy, cmd=0.10, episodes=EPISODES, tag=None):
    if name in st["scores"]:
        return st["scores"][name]
    os.makedirs(REPORT_DIR, exist_ok=True)
    log(f"scoring {name}: carpet tests, {episodes} episodes each (about {2 if episodes <= 40 else 5} min)")
    rec = {"carpet": {}, "path": policy, "levels": carpet_levels(tag) if tag else None}
    for n, s in SETTINGS.items():
        r = CF.run(policy, LEVERS, episodes=episodes, cmd=cmd, extra=CF.FITTED_BODY["set"], payload_dy=CF.FITTED_BODY["payload_dy"], quiet=True, **s)
        rec["carpet"][n] = r["rows"][0]
    rec["carpet"]["cmd"] = cmd
    st["scores"][name] = rec
    save_state(st)
    json.dump(rec, open(f"{REPORT_DIR}/{name}.json", "w"), indent=1)
    log(f"SCORED {name} | {line(rec['carpet'])}" + (f" | carpet level (median, highest) {rec['levels']}" if rec["levels"] else ""))
    return rec


def falls(r):
    return r["carpet"]["fitted"]["falls"]


def walks(r):
    need = 0.5 * r["carpet"].get("cmd", 0.10) * 12.5 / 0.0254
    return [] if r["carpet"]["fitted"]["dist_in_med"] >= need else [f"walks {r['carpet']['fitted']['dist_in_med']:.0f} in on the fitted carpet, needs {need:.0f}"]


def key(r):
    return (falls(r), r["carpet"]["harsh"]["falls"])


def goal(r):
    return falls(r) <= GOAL_FALLS and not walks(r)


# ---------------------------------------------------------------------------------------------------- G1, G2
def g1(st):
    if "g1" in st:
        return
    old = json.load(open(OLD_STATE))["scores"] if os.path.exists(OLD_STATE) else {}
    base = old.get("carpet_ctrl", {}).get("carpet", {}).get("fitted", {}).get("falls", 1.0)
    path = train_run(st, "carpet_g1", RECIPE0, SCREEN_STEPS, FROM)
    if not path:
        open(HALT, "w").write("HALT: the carpet ground's first run did not finish\n")
        log("HALT: the carpet ground's first run did not finish (trained/carpet_g1_console.log)")
        raise SystemExit(1)
    r = score(st, "carpet_g1", path, tag="carpet_g1")
    why = ([] if falls(r) <= base - GAIN else [f"fitted-carpet falls {falls(r):.2f}, needs {base - GAIN:.2f} or less (round 1's best {base:.2f})"]) + walks(r)
    decision(f"G1 the carpet ground {'IMPROVES' if not why else 'does not improve enough: ' + '; '.join(why)}; G2 builds on it")
    st["g1"] = dict(improves=not why)
    st["g2"] = {"recipe": list(RECIPE0), "best": "carpet_g1", "done": []}
    save_state(st)


def g2(st):
    r2 = st["g2"]
    for lever, desc in G2_LEVERS:
        if lever in r2["done"]:
            continue
        tag = f"carpet_g2_{lever.split('_')[1]}"
        recipe = r2["recipe"] + [lever]
        log(f"G2 {lever}: {desc} (recipe {recipe})")
        path = train_run(st, tag, recipe, SCREEN_STEPS, FROM)
        if path:
            r, best = score(st, tag, path, cmd=carpet_cmd(recipe), tag=tag), st["scores"][r2["best"]]
            why = ([] if falls(best) - falls(r) >= GAIN else [f"fitted-carpet falls {falls(r):.2f} against the best so far ({r2['best']}) {falls(best):.2f}: needs a drop of {GAIN}"]) + walks(r)
            if not why:
                r2["recipe"], r2["best"] = recipe, tag
                decision(f"G2 {lever} ADOPTED: fitted-carpet falls {falls(r):.2f} (was {falls(best):.2f}); recipe now {recipe}")
            else:
                decision(f"G2 {lever} REJECTED: {'; '.join(why)}")
        else:
            decision(f"G2 {lever} REJECTED: the run did not finish")
        r2["done"].append(lever)
        save_state(st)
    if not r2.get("complete"):
        r2["complete"] = True
        save_state(st)
        log(f"G2 COMPLETE: recipe {r2['recipe']} (best screen {r2['best']})")


# ---------------------------------------------------------------------------------------------------- G3, G4, G5
def g3(st):
    r3 = st.setdefault("g3", {})
    if r3.get("pick"):
        return
    recipe, rows = st["g2"]["recipe"], {}
    for seed in (42, 43):
        tag = f"carpet_g3_s{seed}"
        path = train_run(st, tag, recipe, STAGE_STEPS, FROM, seed=seed, minutes=30)
        if path:
            rows[tag] = score(st, tag, path, cmd=carpet_cmd(recipe), tag=tag)
    if not rows:
        decision("G3: neither seed finished; the G2 best screen goes on to the 20M instead")
        r3["pick"] = st["g2"]["best"]
    else:
        r3["pick"] = min(rows, key=lambda t: key(rows[t]))
        decision(f"G3 picked {r3['pick']} to start the 20M (" + "; ".join(f"{t}: {line(r['carpet'])}" for t, r in rows.items()) + ")")
    save_state(st)


def consolidate(st, n):
    """Pass n (0 = G4/G5, then 1, 2): a 20M on the carpet ground from the previous pick, then the pick of its final / averaged weights. Returns the pick's score."""
    rec = st.setdefault("passes", {}).setdefault(str(n), {})
    if rec.get("picked"):
        return st["scores"][rec["picked"]]
    recipe = st["g2"]["recipe"]
    start_name = st["g3"]["pick"] if n == 0 else st["passes"][str(n - 1)]["picked"]
    start_path = st["scores"][start_name]["path"]
    tag = "carpet_g20m" + ("" if n == 0 else f"_p{n + 1}")
    if not rec.get("trained"):
        path = train_run(st, tag, recipe + ["carpet_consol"], CONSOL_STEPS, start_path, last=True, minutes=150)
        if not path:
            decision(f"{tag}: the 20M did not finish cleanly; its last checkpoints are scored instead")
        rec["trained"] = True
        save_state(st)
    cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
    cands = [("final", f"trained/{tag}_ppo")] if os.path.exists(f"trained/{tag}_ppo.zip") else ([("last", cks[-1][:-4])] if cks else [])
    if len(cks) >= 5:
        ok, out = V5.average_checkpoints([c[:-4] for c in cks[-5:]], f"trained/{tag}_avg5_ppo")
        if ok:
            cands.append(("avg5", f"trained/{tag}_avg5_ppo"))
        else:
            decision(f"{tag}: checkpoint averaging failed ({out}); only the final weights are scored")
    if not cands:
        open(HALT, "w").write(f"HALT: {tag} left nothing to score\n")
        log(f"HALT: {tag} left nothing to score")
        raise SystemExit(1)
    start = score(st, f"{tag}_start", start_path, cmd=carpet_cmd(recipe), episodes=FINAL_EPISODES)
    rows = {k: score(st, f"{tag}_{k}", p, cmd=carpet_cmd(recipe), episodes=FINAL_EPISODES, tag=tag) for k, p in cands}
    pick = min(rows, key=lambda k: key(rows[k]))
    r = rows[pick]
    v7 = score(st, "V7_final", V7_POLICY, episodes=FINAL_EPISODES)                                   # for information only
    decision(f"{tag} picked {pick}: {line(r['carpet'])}; {'improves on' if falls(r) < falls(start) else 'does NOT improve on'} its start ({start_name}: fitted-carpet falls "
             f"{falls(start):.2f}); the goal (fitted-carpet falls <= {GOAL_FALLS} and it walks) is {'MET' if goal(r) else 'not met yet'} "
             f"(for information: V7 fitted-carpet falls {falls(v7):.2f})")
    side = {"gait": "carpet", "levers": ["heading_blind"], "payload_profile": "pod", "cmd_fwd_on_carpet": carpet_cmd(recipe),
            "note": f"carpet-only gait (V7 chain from pod_s3, carpet ground, recipe {recipe}, {tag} {pick}); on G2 'G2, carpet mode' loads it"}
    e = subprocess.run([sys.executable, "export_onnx.py", "--model", r["path"], "--out", CAND_ONNX, "--residual-scale-deg", "30", "--cmd-send-every-n", "3",
                        "--heading-blind", "--sidecar-extra", json.dumps(side)], capture_output=True, text=True)
    decision(f"{tag}: " + (f"exported {CAND_ONNX} (+ .onnx.json)" if e.returncode == 0 and "MISMATCH" not in e.stdout else f"export failed ({(e.stdout + e.stderr)[-200:]})")
             + ". Not promoted, not deployed (the user decides)")
    rec.update(picked=f"{tag}_{pick}", start=start_name, gain=round(falls(start) - falls(r), 3), goal=goal(r))
    save_state(st)
    return r


def run():
    st = load_state()
    g1(st)
    g2(st)
    g3(st)
    for n in range(MAX_EXTRA + 1):
        r = consolidate(st, n)
        rec = st["passes"][str(n)]
        if rec["goal"]:
            log(f"GOAL MET after pass {n + 1}: the carpet gait walks the fitted carpet (falls {falls(r):.2f})")
            break
        if n == MAX_EXTRA or rec["gain"] < PASS_GAIN:
            decision(f"stopping after pass {n + 1}: the goal is not met and " + ("this was the last pass allowed" if n == MAX_EXTRA else
                     f"the pass cut fitted-carpet falls by only {rec['gain']:.2f} (needs {PASS_GAIN}): more of the same will not get there; a new idea is needed"))
            break
        decision(f"pass {n + 1} cut fitted-carpet falls by {rec['gain']:.2f} but the goal is not met: another 20M pass from its pick")
    log("CARPET ALL COMPLETE")


def status():
    st = load_state()
    print("trained:", {k: bool(v) for k, v in st.get("trained", {}).items()})
    for name, rec in st.get("scores", {}).items():
        print("scored", name, line(rec["carpet"]), rec.get("levels") or "")
    print("G1:", st.get("g1"), "| G2:", st.get("g2"), "| G3:", st.get("g3"), "| passes:", st.get("passes"))


if __name__ == "__main__":
    {"run": run, "status": status}[sys.argv[1]]()
