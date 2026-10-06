"""Automated rounds for the v2.2 policy: fix the real G2's drift to one side, on the new 422 g payload (2026-10-06).

    python phase_v22.py            # reads/writes trained/v22_queue.json, logs to trained/phase_v22.log

Each round is a fresh 3M-step run (never a fine-tune). After it finishes it is scored against the frozen Release_CandidateV2.1 in the SAME sim
(case payload): a calm flat walk and the same walk under the reference yaw disturbance (drift_probe.py), plus a few decathlon cells. The round passes if the
calm walk does not regress and the drift under the disturbance is at least halved. The runner then waits up to WAIT_NEXT_S for a new round to appear in the
queue file (that is where the next iteration is decided); if none appears it launches the final 20M run with the best passing round's settings plus the +10% hard
levels, gated at 3M and 5M. At most MAX_ROUNDS rounds. Every state change is one log line starting with "[v22 ...]" so a watcher can notify on it.
"""
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("G2E_PAYLOAD_PROFILE", "case")        # the scoring env must model the same robot as the training env
import run_pipeline as RP  # noqa: E402

LOG = "trained/phase_v22.log"
QUEUE = "trained/v22_queue.json"
BASELINE = "trained/v22_baseline.json"
RESULTS = "trained/v22_results.json"
V21 = "trained/Release_CandidateV2.1_ppo"
MAX_ROUNDS = 5
WAIT_NEXT_S = 12 * 60
REF_TORQUE = "0.5"            # the reference yaw disturbance both policies are scored under
CELLS = ["T2.2", "T3.2", "T5.2", "T7.2", "T8.1", "T10.1", "T10.2"]
FLAT_FELL_MAX = 0.15
FLAT_FELL_MARGIN = 0.05       # a round may not fall more than V2.1 + this on the calm walk
SPEED_MIN_RATIO = 0.90
DRIFT_MIN_IMPROVEMENT = 0.50  # heading error under the disturbance must be at least this much lower than V2.1's
GATE_SPEED_RATIO = 0.80       # final-run gates at 3M / 5M
FINAL_TAG = "v22_20m"


def log(msg):
    line = f"[v22 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def probe(zip_path, kind):
    env = dict(os.environ, G2E_PAYLOAD_PROFILE="case")
    if kind == "ref":
        env.update(G2E_DRIFT_TORQUE=REF_TORQUE, G2E_DRIFT_PROB="1.0")
    r = subprocess.run([RP.PY, "drift_probe.py", zip_path, "--episodes", "24", "--seed", "777"], capture_output=True, text=True, env=env)
    return json.loads(r.stdout.strip().splitlines()[-1])


def evaluate(zip_path, cells=CELLS):
    calm, ref = probe(zip_path, "calm"), probe(zip_path, "ref")
    out = dict(calm_falls=calm["falls"] / calm["episodes"], calm_speed=calm["speed_mps"], calm_roll=calm["roll_std_deg"], calm_yawrms=calm["yaw_rate_rms"],
               ref_heading_abs=ref["heading_abs_mean_deg"], ref_heading_mean=ref["heading_mean_deg"], ref_falls=ref["falls"] / ref["episodes"],
               ref_yawrms=ref["yaw_rate_rms"])
    if cells:
        out["cells"] = score_cells(zip_path, cells)
    return out


def score_cells(zip_path, cells):
    code = (
        "import json,sys\nimport run_pipeline as RP\nimport opencat_gym_env as E\nE.GUI_MODE=False\nimport benchmark_decathlon as B\n"
        "from benchmark_gaits import _load_learned, _bench\nfrom opencat_gym_env import OpenCatGymEnv\n"
        f"m=_load_learned({zip_path.replace('.zip','')!r})\nenv=OpenCatGymEnv(); env.set_command(fwd=0.10,yaw=0.0)\nres={{}}\nall_c={{c[0]:c for c in B.LADDER}}\n"
        f"for cid in {cells!r}:\n    kn={{k:v for k,v in all_c[cid][4].items() if not k.startswith('_')}}\n    B._apply(kn)\n"
        "    E.IMU_HOLD_STEPS,E.IMU_RATE_ZERO,E.CMD_PATH=16,True,'i'\n    E.CMD_SEND_EVERY_N=3\n    E.EPISODE_LENGTH=250\n"
        "    s,_=_bench(env,m,20,1000)\n    res[cid]=round(float(s['fell_fraction']),3)\nprint('CELLS '+json.dumps(res))\n")
    r = subprocess.run([RP.PY, "-c", code], capture_output=True, text=True, env=dict(os.environ, G2E_PAYLOAD_PROFILE="case", **RP.BASE))
    for line in r.stdout.splitlines()[::-1]:
        if line.startswith("CELLS "):
            return json.loads(line[6:])
    return {"error": (r.stderr or r.stdout)[-300:]}


def baseline():
    if os.path.exists(BASELINE):
        return json.load(open(BASELINE))
    log("scoring the frozen Release_CandidateV2.1 in the new case-payload sim (the reference every round is judged against)")
    b = evaluate(V21 + ".zip")
    json.dump(b, open(BASELINE, "w"), indent=1)
    log(f"V2.1 baseline: {json.dumps(b)}")
    return b


def verdict(res, base):
    why = []
    if res["calm_falls"] > min(FLAT_FELL_MAX, base["calm_falls"] + FLAT_FELL_MARGIN):
        why.append(f"calm falls {res['calm_falls']:.2f} > {min(FLAT_FELL_MAX, base['calm_falls'] + FLAT_FELL_MARGIN):.2f}")
    if res["calm_speed"] < SPEED_MIN_RATIO * base["calm_speed"]:
        why.append(f"calm speed {res['calm_speed']:.3f} < {SPEED_MIN_RATIO:.0%} of V2.1's {base['calm_speed']:.3f}")
    if res["ref_heading_abs"] > (1 - DRIFT_MIN_IMPROVEMENT) * base["ref_heading_abs"]:
        why.append(f"drift {res['ref_heading_abs']:.1f} deg is not {DRIFT_MIN_IMPROVEMENT:.0%} below V2.1's {base['ref_heading_abs']:.1f}")
    return (not why), why


def read_queue():
    return json.load(open(QUEUE))


def run_round(i, rnd, base, results):
    tag = rnd["tag"]
    if RP.training(tag) or os.path.exists(f"trained/{tag}_ppo.zip"):
        log(f"ROUND {i} RESUME {tag}: already running or finished, not relaunching")
    else:
        log(f"ROUND {i} START {tag}: {rnd['desc']}  extra={rnd['extra']}")
        RP.launch(tag, {"G2E_PAYLOAD_PROFILE": "case", **rnd["extra"]}, steps="3e6")
    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"ROUND {i} HALT {tag}: {reason}")
        return None
    res = evaluate(f"trained/{tag}_ppo.zip")
    passed, why = verdict(res, base)
    results[tag] = dict(round=i, desc=rnd["desc"], extra=rnd["extra"], result=res, passed=passed, why=why)
    json.dump(results, open(RESULTS, "w"), indent=1)
    log(f"ROUND {i} DONE {tag} {'PASS' if passed else 'FAIL'} {why or ''} | drift {res['ref_heading_abs']:.1f} deg (V2.1 {base['ref_heading_abs']:.1f}), "
        f"calm falls {res['calm_falls']:.2f} (V2.1 {base['calm_falls']:.2f}), speed {res['calm_speed']:.3f} (V2.1 {base['calm_speed']:.3f}), "
        f"yawrms {res['calm_yawrms']:.3f} (V2.1 {base['calm_yawrms']:.3f}), cells {res.get('cells')}")
    return results[tag]


def final_run(best_extra, base):
    extra = {"G2E_PAYLOAD_PROFILE": "case", "G2E_HARD_SCALE": "1.10", **best_extra}
    log(f"FINAL START {FINAL_TAG}: 20M, gates at 3M and 5M, extra={extra}")
    RP.launch(FINAL_TAG, extra, steps="20e6")
    for step in (3000000, 5000000):
        ok, reason = RP.wait_for_ckpt(FINAL_TAG, step)
        if not ok:
            log(f"FINAL HALT: {reason}")
            return False
        z = RP.ckpt(FINAL_TAG, step) 
        res = evaluate(z, cells=CELLS)
        bad = []
        if res["calm_falls"] > FLAT_FELL_MAX:
            bad.append(f"calm falls {res['calm_falls']:.2f} > {FLAT_FELL_MAX}")
        if res["calm_speed"] < GATE_SPEED_RATIO * base["calm_speed"]:
            bad.append(f"calm speed {res['calm_speed']:.3f} < {GATE_SPEED_RATIO:.0%} of V2.1's")
        if res["ref_heading_abs"] > base["ref_heading_abs"]:
            bad.append(f"drift {res['ref_heading_abs']:.1f} worse than V2.1's {base['ref_heading_abs']:.1f}")
        log(f"FINAL GATE {step // 1000000}M {'STOP' if bad else 'OK'} {bad or ''} | {json.dumps(res)}")
        if bad:
            RP.stop(FINAL_TAG)
            return False
    ok, reason = RP.wait_for_finish(FINAL_TAG)
    log(f"FINAL {'DONE' if ok else 'HALT'}: {reason}")
    return ok


def main():
    os.makedirs("trained", exist_ok=True)
    base = baseline()
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {}
    i = len(results)
    while True:
        q = read_queue()
        rounds = q["rounds"]
        if i < len(rounds) and i < MAX_ROUNDS:
            if rounds[i]["tag"] not in results:
                if run_round(i + 1, rounds[i], base, results) is None:
                    return
            i += 1
            continue
        if q.get("final") or i >= MAX_ROUNDS:
            break
        log(f"waiting up to {WAIT_NEXT_S // 60} min for the next round to be added to {QUEUE} (else the final run starts)")
        t0 = time.time()
        while time.time() - t0 < WAIT_NEXT_S and len(read_queue()["rounds"]) <= i and not read_queue().get("final"):
            time.sleep(20)
        if len(read_queue()["rounds"]) <= i:
            break
    passing = [(r["result"]["ref_heading_abs"], t) for t, r in results.items() if r["passed"]]
    if not passing:
        log("NO ROUND PASSED the gates -- the final 20M run is NOT started. Needs a decision.")
        return
    best_tag = min(passing)[1]
    log(f"best passing round: {best_tag} (drift {results[best_tag]['result']['ref_heading_abs']:.1f} deg)")
    # HARDWARE CHECK-IN (user request, 2026-10-06): testing pauses here, before the 20M run, so the best 3M policy can be walked on G2.
    # Resume by creating trained/v22_final_go (optionally containing a different round tag to use for the final run).
    go = "trained/v22_final_go"
    log(f"HW CHECKIN: best 3M round is {best_tag}. PAUSED before the final 20M run until {go} exists (the user tests the policy on G2 first)")
    while not os.path.exists(go):
        time.sleep(20)
    chosen = open(go).read().strip()
    if chosen in results:
        best_tag = chosen
    log(f"HW CHECKIN done: starting the final run from round {best_tag}")
    final_run(results[best_tag]["extra"], base)


if __name__ == "__main__":
    main()
