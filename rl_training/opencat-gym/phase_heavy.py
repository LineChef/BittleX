"""HEAVY: a policy that stays stable carrying up to 1 lb, trained and judged with no stops (user, 2026-10-19; plan docs/planned/heavy-load-training-plan.md).

    python phase_heavy.py run      # screens (round 1, 2, 3) -> recipe -> chain S0..S3 -> 20M -> pick -> export -> benchmark against V7 -> report
    python phase_heavy.py status

The user's instructions: keep the whole run automatic, with rules (written here before any result) that accept or reject each round; iterate between rounds; train the
20M on the final recipe; benchmark it against V7. The real limit was not measured on G2, so 1 lb (454 g payload in all, 227 g more than today) is the top. Nothing is
promoted or deployed. Every decision goes to trained/heavy_report/decisions.md and the log trained/phase_heavy.log; tools/heavy_watchdog.sh keeps the runner alive.

Rules (fixed 2026-10-19, before any result):
  score         benchmark_load.py's heavy_score: mean falls over 13 cells at +150 g and +227 g, plus 0.02 x the calm-walk roll + pitch sway there (lower is better)
  gates         flat ground: no more than 5% falls on T1.1 / N1 at any load; it still walks: calm-walk speed at 1 lb at least half the (load-scaled) command;
                today's payload: mean falls no more than 0.03 above the reference (the control screen in the screens, V7 for the final)
  round 1       four fresh 3M screens on the V7 recipe: ctrl (no load change), A (+ the load range and slower commands), B (A + the load input), C (B + the load-scaled
                stability, heat and slip costs). The best of A / B / C that passes the gates wins (if none passes, the best score wins and that is logged).
  round 2       two variants of the winner, each fresh 3M: more episodes near 1 lb (heavy_skew35), twice the stability weight (heavy_stab3). A variant is adopted
                if it passes the gates and scores at least 0.015 better than the winner.
                TIP rule (added 2026-10-19 before round 1 finished): if the winner falls at 1 lb at least 1.5x as often as at today's payload, or more than 10% at 1 lb,
                two more variants join round 2: keep the capture point over the middle of the paws (heavy_margin), ride lower with the scripted pose held more
                loosely (heavy_low).
  round 3       only if two or more variants were adopted: all of them together; kept if at least 0.015 better than the best variant alone.
  chain         the V6 chain (S0 2M, S1 3M, S2 3M, S3 1M) on the final recipe, then the 20M from the last stage that does not fall on flat ground (fresh if none).
  pick          the 20M's final weights or the average of its last 5 checkpoints: the better heavy_score among those that pass the gates (else the better score).
  verdict       better at carrying than V7 if, at 100 paired episodes per cell, its heavy_score is at least 0.02 lower, it falls less at 1 lb and never falls more than
                5% on flat ground; no regression at today's payload if its mean falls over the shared V5 benchmark cells are within 0.03 of V7's."""
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

V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR = "trained/phase_heavy.log", "trained/heavy_halt", "trained/heavy_state.json", "trained/heavy_report"
LOG, HALT, STATE, REPORT_DIR = V5.LOG, V5.HALT, V5.STATE, V5.REPORT_DIR
DECISIONS = f"{REPORT_DIR}/decisions.md"


def log(msg):
    line = f"[heavy {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


V5.log = log
halt, load_state, save_state, clock_in, cm = V5.halt, V5.load_state, V5.save_state, V5.clock_in, V5.cm

ADOPTED = ["cross_bonus", "haz_speed", "haz_posture", "heading_blind"]
BASE6 = V5.BASE + ADOPTED + ["ledge30"]                            # the V7 recipe (the V6 recipe on the pod payload)
ROUND1 = {"ctrl": [], "a": ["heavy_world"], "b": ["heavy_world", "load_obs"], "c": ["heavy_world", "load_obs", "heavy_reward"]}
VARIANTS = ("heavy_skew35", "heavy_stab3")
TIP_VARIANTS = ("heavy_margin", "heavy_low")       # added 2026-10-19 (user: "make a judgement call"): only when the round-1 winner still tips under the load (TIP rule)
TIP_RATIO, TIP_FALLS = 1.5, 0.10
SCREEN_STEPS, SCREEN_MIN = "3e6", 25
SCREEN_EPISODES, FINAL_EPISODES = 40, 100
MARGIN, VERDICT_MARGIN, LIGHT_SLACK, FLAT_MAX, SPEED_MIN = 0.015, 0.02, 0.03, 0.05, 0.5
STAGES = [("s0", "v6_s0_flat", "2e6", 16), ("s1", "v6_s1_terrain", "3e6", 24), ("s2", "v6_s2_ledges", "3e6", 24), ("s3", "v6_s3_slopes", "1e6", 9)]
FINAL = ("s4", "v6_s4_all", "20e6", 150)
TAG = lambda n: f"heavy_{n}"                                       # noqa: E731
V7_POLICY, V7_LEVERS, V7_V5_JSON = "trained/pod_s4_ppo", ["privileged_critic", "heading_blind"], "trained/pod_report/pod.json"
PICK_WINDOW = 5
TRACK_EVERY = 2_000_000
CAND_ONNX = "trained/HEAVYcand_ppo.onnx"


def decision(msg):
    os.makedirs(REPORT_DIR, exist_ok=True)
    log("DECISION " + msg)
    with open(DECISIONS, "a") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %I:%M %p')}: {msg}\n")


def clean_environ():
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP


def job_env(tag, levers, last=False):
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
    env["G2E_SEED"] = "42"
    if not last:
        env.pop("G2E_PLATEAU_STOP", None)
    return {k: v for k, v in env.items() if v != ""}


def train(tag, levers, steps, minutes, chain_from=None, last=False):
    """Train one run to its own end. A crash is retried once from scratch (files moved aside); a second crash returns False and the caller decides."""
    zip_ = f"trained/{tag}_ppo.zip"
    for attempt in (1, 2):
        if os.path.exists(zip_):
            return True
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_console.log"):
                aside = f"trained/failed_{tag}_{int(time.time())}"
                os.makedirs(aside, exist_ok=True)
                for f in [f for f in os.listdir("trained") if f.startswith(f"{tag}_")]:
                    shutil.move(os.path.join("trained", f), aside)
                decision(f"{tag} had stopped without finishing; its files are in {aside}; starting it again (attempt {attempt})")
            clean_environ()
            log(f"{tag} START: {steps} steps{' from ' + chain_from if chain_from else ' (fresh)'}, about {minutes} min, done about {clock_in(minutes)} | levers +{[l for l in levers if l not in BASE6]}")
            RP.launch(tag, job_env(tag, levers, last), steps=steps, base=False, chain_from=chain_from)
        ok, why = RP.wait_for_finish(tag)
        if ok:
            return True
        log(f"{tag} did not finish: {why}")
    return False


def load_score(policy, levers, episodes, out):
    """benchmark_load in a fresh process (the scoring environment is set before the env module is imported). Cached in `out`."""
    if os.path.exists(out):
        return json.load(open(out))
    t0 = time.time()
    r = subprocess.run([sys.executable, "benchmark_load.py", "--policy", policy, "--levers", ",".join(V5.obs_levers(levers)), "--episodes", str(episodes),
                        "--jobs", "8", "--json-out", out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        log(f"load scoring of {policy} failed: {(r.stdout + r.stderr)[-500:]}")
        return None
    res = json.load(open(out))
    log(f"LOAD {policy} ({episodes} eps, {(time.time() - t0) / 60:.0f} min) | {line(res['summary'])}")
    return res


def line(s):
    return (f"heavy score {s['heavy_score']:.3f} (falls {s['heavy_falls']:.3f}, sway {s['heavy_sway']:.1f} deg) | today's payload falls {s['light_falls']:.3f} | "
            f"flat falls {s['flat_falls']:.2f} | 1 lb speed ratio {s['speed_ratio']:.2f} | falls by load " + " / ".join(f"{v['falls']:.3f}" for v in s["per_load"].values()))


def gates(s, ref_light):
    why = []
    if s["flat_falls"] > FLAT_MAX:
        why.append(f"flat-ground falls {s['flat_falls']:.2f} > {FLAT_MAX}")
    if s["speed_ratio"] < SPEED_MIN:
        why.append(f"1 lb speed ratio {s['speed_ratio']:.2f} < {SPEED_MIN} (stands still)")
    if ref_light is not None and s["light_falls"] > ref_light + LIGHT_SLACK:
        why.append(f"today's-payload falls {s['light_falls']:.3f} > reference {ref_light:.3f} + {LIGHT_SLACK}")
    return why


def screen(st, key, extra):
    """One fresh 3M screen: the V7 recipe plus `extra` levers; returns its load summary (or None if it could not be trained or scored)."""
    sc = st.setdefault("screens", {})
    if key in sc and sc[key].get("summary"):
        return sc[key]["summary"]
    tag = TAG(f"sc_{key}")
    levers = BASE6 + list(extra)
    if not train(tag, levers, SCREEN_STEPS, SCREEN_MIN):
        decision(f"screen {key} could not be trained twice: dropped from the round")
        sc[key] = {"extra": list(extra), "summary": None}
        save_state(st)
        return None
    res = load_score(f"trained/{tag}_ppo", levers, SCREEN_EPISODES, f"trained/heavy_load_sc_{key}.json")
    sc[key] = {"extra": list(extra), "summary": res["summary"] if res else None}
    save_state(st)
    return sc[key]["summary"]


def pick_best(cands, ref_light, label):
    """cands {key: summary}: the lowest heavy score among those that pass the gates; if none passes, the lowest score (logged)."""
    cands = {k: s for k, s in cands.items() if s}
    if not cands:
        return None
    ok = {k: s for k, s in cands.items() if not gates(s, ref_light)}
    pool = ok or cands
    best = min(pool, key=lambda k: pool[k]["heavy_score"])
    for k, s in sorted(cands.items(), key=lambda kv: kv[1]["heavy_score"]):
        decision(f"{label} {k}: {line(s)} | gates {'pass' if k in ok else 'FAIL: ' + '; '.join(gates(s, ref_light))}")
    if not ok:
        decision(f"{label}: no candidate passed the gates; {best} chosen on score alone")
    return best


def screens(st):
    if st.get("recipe"):
        return st["recipe"]
    r1 = {k: screen(st, k, ex) for k, ex in ROUND1.items()}
    ctrl = r1.pop("ctrl")
    ref = ctrl["light_falls"] if ctrl else None
    if ctrl:
        decision(f"round 1 reference ctrl (the V7 recipe at 3M): {line(ctrl)}")
    win = pick_best(r1, ref, "round 1")
    if win is None:                                                    # never stop (user, 2026-10-19): fall back to the plan's full recipe
        extra = list(ROUND1["c"])
        decision(f"no round-1 screen could be trained or scored; the plan's full recipe (+{extra}) goes on to the chain unscreened")
        st["recipe"] = extra
        save_state(st)
        return extra
    base_extra, base_s = list(ROUND1[win]), r1[win]
    decision(f"round 1 WINNER {win} (+{base_extra}), heavy score {base_s['heavy_score']:.3f}" + (f" against ctrl {ctrl['heavy_score']:.3f}" if ctrl else ""))
    pl = base_s["per_load"]
    f_top, f_light = pl[max(pl, key=float)]["falls"], pl[min(pl, key=float)]["falls"]
    tips = f_top >= TIP_RATIO * max(f_light, 1e-6) or f_top > TIP_FALLS
    variants = list(VARIANTS) + (list(TIP_VARIANTS) if tips else [])
    decision(f"TIP rule: the winner falls {f_top:.3f} at 1 lb against {f_light:.3f} at today's payload -> "
             + ("it still tips under the load: round 2 also tests " + ", ".join(TIP_VARIANTS) if tips else "it does not tip much more under the load: the two tip variants are not run"))
    good = {}
    for v in variants:
        s = screen(st, f"{win}_{v}", base_extra + [v])
        if s is None:
            continue
        fails = gates(s, ref)
        better = s["heavy_score"] <= base_s["heavy_score"] - MARGIN
        gain = base_s["heavy_score"] - s["heavy_score"]
        why = ("gates: " + "; ".join(fails)) if fails else f"{gain:+.3f} better than the winner, needs {MARGIN}"
        decision(f"round 2 {win}+{v}: {line(s)} | {'ADOPTED' if better and not fails else 'not adopted'} ({why})")
        if better and not fails:
            good[v] = s
    extra = base_extra
    if len(good) >= 2:
        combo = [v for v in variants if v in good]
        s = screen(st, f"{win}_combo", base_extra + combo)
        best1 = min(good, key=lambda k: good[k]["heavy_score"])
        if s and not gates(s, ref) and s["heavy_score"] <= good[best1]["heavy_score"] - MARGIN:
            extra = base_extra + combo
            decision(f"round 3 {combo} together: {line(s)} | ADOPTED (better than {best1} alone by {good[best1]['heavy_score'] - s['heavy_score']:.3f})")
        else:
            extra = base_extra + [best1]
            decision(f"round 3 {combo} together: {line(s) if s else 'not scored'} | not adopted; {best1} alone is kept")
    elif len(good) == 1:
        extra = base_extra + list(good)
    st["recipe"] = extra
    save_state(st)
    decision(f"FINAL RECIPE: the V7 recipe + {extra}")
    return extra


def chain(st, extra):
    levers = BASE6 + extra
    prev = None
    for name, lever, steps, minutes in STAGES:
        tag = TAG(name)
        if not train(tag, levers + [lever], steps, minutes, chain_from=(f"trained/{prev}_ppo" if prev else None)):
            decision(f"{tag} could not be trained twice: the chain stops at {prev or 'nothing'}")
            break
        res = load_score(f"trained/{tag}_ppo", levers, SCREEN_EPISODES, f"trained/heavy_load_{name}.json")
        st.setdefault("stages", {})[name] = res["summary"] if res else None
        save_state(st)
        prev = tag
    if st.get("start_from") is not None:
        return st["start_from"] or None
    start = None
    for name, *_ in reversed(STAGES):
        s = st.get("stages", {}).get(name)
        if s and s["flat_falls"] <= FLAT_MAX:
            start = f"trained/{TAG(name)}_ppo"
            break
    decision(f"the 20M starts from {start or 'scratch (no stage passed the flat-ground gate)'}")
    st["start_from"] = start or ""
    save_state(st)
    return start


def track(step, levers):
    ck = RP.ckpt(TAG(FINAL[0]), step)[:-4]
    out = f"trained/.heavy_track_{step}.json"
    code = ("import sys, json; sys.path.insert(0, '.'); import benchmark_load as L; "
            f"r = L.run({ck!r}, {tuple(V5.obs_levers(levers))!r}, 20, 3, loads=(0.0, 0.150, 0.227), cells=('T1.1', 'N1', 'T1.2', 'T3.1', 'T8.1', 'N4')); json.dump(r, open({out!r}, 'w'))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        log(f"tracker {step // 10**6}M failed (the run continues): {(r.stdout + r.stderr)[-300:]}")
        return
    s = json.load(open(out))["summary"]
    os.remove(out)
    with open(f"trained/{TAG(FINAL[0])}_curve.jsonl", "a") as f:
        f.write(json.dumps({"step": step, "t": time.time(), **{k: v for k, v in s.items() if k != "per_load"}, "per_load": s["per_load"]}) + "\n")
    log(f"{TAG(FINAL[0])} TRACK {step // 10**6}M | {line(s)}")


def final20m(st, extra, start):
    tag = TAG(FINAL[0])
    if st.get("final") == "done":
        return
    levers = BASE6 + extra
    name, lever, steps, minutes = FINAL
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        clean_environ()
        log(f"{tag} START: the 20M on the final recipe from {start or 'scratch'} (plateau stop on), about {minutes} min, done about {clock_in(minutes)}")
        RP.launch(tag, job_env(tag, levers + [lever], last=True), steps=steps, base=False, chain_from=start)
    done = set(st.get("tracked", []))
    step = TRACK_EVERY
    while step <= 20_000_000:
        if step in done:
            step += TRACK_EVERY
            continue
        ok, _why = RP.wait_for_ckpt(tag, step)
        if not ok:
            break                                                          # finished early (plateau stop) or stopped: the wait below says which
        track(step, levers)
        done.add(step)
        st["tracked"] = sorted(done)
        save_state(st)
        step += TRACK_EVERY
    ok, why = RP.wait_for_finish(tag)
    import glob
    import re
    tries = st.get("final_retries", 0)
    while not ok and tries < 3:                                        # never stop (user, 2026-10-19): resume from the last checkpoint, or start again, up to 3 times
        tries += 1
        st["final_retries"] = tries
        save_state(st)
        cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
        if cks:
            left = 20_000_000 - int(re.search(r"_(\d+)_steps", cks[-1]).group(1))
            decision(f"the 20M stopped before the end ({why}); restart {tries} of 3 resumes from {cks[-1]} for the {left // 10**6}M steps left")
            src, steps_ = cks[-1][:-4], str(left)
        else:
            decision(f"the 20M died before its first checkpoint ({why}); restart {tries} of 3 starts it again from {start or 'scratch'}")
            src, steps_ = start, steps
        aside = f"trained/failed_{tag}_{int(time.time())}"
        os.makedirs(aside, exist_ok=True)
        for f in [f for f in os.listdir("trained") if f.startswith(f"{tag}_") and f.endswith(("console.log", "caps.json", "frontier.json"))]:
            shutil.move(os.path.join("trained", f), aside)
        clean_environ()
        RP.launch(tag, job_env(tag, levers + [lever], last=True), steps=steps_, base=False, chain_from=src)
        ok, why = RP.wait_for_finish(tag)
    if not ok:
        decision(f"the 20M could not be finished after 3 restarts ({why}); the pick uses its last checkpoint or, failing that, the last chain stage")
    st["final"] = "done"
    save_state(st)
    log(f"{tag} FINISHED")


def pick(st, extra):
    import glob
    import re
    if st.get("picked"):
        return st["picked"]
    levers = BASE6 + extra
    tag = TAG(FINAL[0])
    v7 = load_score(V7_POLICY, V7_LEVERS, FINAL_EPISODES, f"{REPORT_DIR}/v7_load.json")
    cands = {"final": f"trained/{tag}_ppo"} if os.path.exists(f"trained/{tag}_ppo.zip") else {}
    cks = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
    if len(cks) >= PICK_WINDOW:
        ok, out = V5.average_checkpoints([c[:-4] for c in cks[-PICK_WINDOW:]], f"trained/{tag}_avg{PICK_WINDOW}_ppo")
        if ok:
            cands[f"avg{PICK_WINDOW}"] = f"trained/{tag}_avg{PICK_WINDOW}_ppo"
        else:
            log(f"checkpoint averaging failed: {out}")
    if not cands and cks:
        cands["last_ckpt"] = cks[-1][:-4]
    if not cands:
        for name, *_ in reversed(STAGES):
            if os.path.exists(f"trained/{TAG(name)}_ppo.zip"):
                cands[name] = f"trained/{TAG(name)}_ppo"
                break
    scored = {}
    for k, path in cands.items():
        res = load_score(path, levers, FINAL_EPISODES, f"{REPORT_DIR}/{k}_load.json")
        if res:
            scored[k] = res["summary"]
    best = pick_best(scored, v7["summary"]["light_falls"] if v7 else None, "pick")
    if best is None:
        best = next(iter(cands), None)
        decision(f"no candidate could be scored on the load benchmark; {best} is exported unscored")
        if best is None:
            decision("no trained policy exists to pick: the run ends without a candidate")
            st["picked"], st["picked_path"] = "none", None
            save_state(st)
            return "none"
    path = cands[best]
    if os.path.exists(f"{REPORT_DIR}/{best}_load.json"):
        shutil.copy(f"{REPORT_DIR}/{best}_load.json", f"{REPORT_DIR}/heavy_load.json")
    side = {"levers": [l for l in V5.obs_levers(levers) if l != "privileged_critic"], "load_input": "load_obs" in extra, "load_ref_kg": 0.227, "payload_profile": "pod",
            "note": "heavy-load candidate: input 279 (after the joint history) = extra payload kg / 0.227, i.e. 0 today, 1 at 1 lb"}
    r = subprocess.run([sys.executable, "export_onnx.py", "--model", path, "--out", CAND_ONNX, "--residual-scale-deg", "30", "--cmd-send-every-n", "3", "--heading-blind",
                        "--sidecar-extra", json.dumps(side)], capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        decision(f"export of {path} failed ({(r.stdout + r.stderr)[-300:]}); the benchmark goes on with the zip")
    else:
        decision(f"PICKED {best} ({path}); exported {CAND_ONNX} (+ .onnx.json). Not promoted, not deployed (the user decides)")
    st["picked"], st["picked_path"] = best, path
    save_state(st)
    return best


def compare(st, extra):
    """The benchmark against V7: the load ladder (100 paired episodes per cell, both policies) and the full V5 benchmark at today's payload."""
    if st.get("compared"):
        return
    if not st.get("picked_path") or not all(os.path.exists(f"{REPORT_DIR}/{f}") for f in ("heavy_load.json", "v7_load.json")):
        decision("the comparison with V7 could not run (no scored candidate or no V7 load score)")
        st["compared"] = {"skipped": True}
        save_state(st)
        return
    levers = BASE6 + extra
    out = f"{REPORT_DIR}/heavy_v5.json"
    for attempt in (1, 2):
        if os.path.exists(out):
            break
        log(f"V5 benchmark of the candidate at today's payload (about 10 min, done about {clock_in(10)})")
        r = subprocess.run([sys.executable, "benchmark_v5.py", "--policy", st["picked_path"], "--levers", ",".join(V5.obs_levers(levers)), "--json-out", out,
                            "--episodes", str(V5.FINAL_EPISODES), "--ladder-episodes", str(V5.FINAL_LADDER_EPISODES), "--jobs", "8"], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"V5 benchmark attempt {attempt} failed: {(r.stdout + r.stderr)[-400:]}")
    if not os.path.exists(out):
        decision("the V5 benchmark at today's payload failed twice; the report compares the load ladder only")
    H, V = json.load(open(f"{REPORT_DIR}/heavy_load.json")), json.load(open(f"{REPORT_DIR}/v7_load.json"))
    h5 = json.load(open(out)) if os.path.exists(out) else None
    v5 = json.load(open(V7_V5_JSON))
    hs, vs = H["summary"], V["summary"]
    top = max(hs["per_load"], key=float)
    carry = (hs["heavy_score"] <= vs["heavy_score"] - VERDICT_MARGIN and hs["per_load"][top]["falls"] < vs["per_load"][top]["falls"] and hs["flat_falls"] <= FLAT_MAX)
    ids = [i for i in cm(h5) if i in cm(v5) and not i.startswith(("Z.", "N")) and i != "Z0"] if h5 else []
    mv = sum(cm(v5)[i]["fell_fraction"] for i in ids) / len(ids) if ids else float("nan")
    mh = sum(cm(h5)[i]["fell_fraction"] for i in ids) / len(ids) if ids else float("nan")
    light = (mh <= mv + LIGHT_SLACK) if ids else None
    decision(f"VERDICT carrying: {'BETTER than V7' if carry else 'NOT better than V7'} by the rule set beforehand | heavy score {hs['heavy_score']:.3f} against V7 {vs['heavy_score']:.3f}; "
             f"falls at 1 lb {hs['per_load'][top]['falls']:.3f} against {vs['per_load'][top]['falls']:.3f}; flat falls {hs['flat_falls']:.2f}")
    decision(f"VERDICT today's payload: {'not measured' if light is None else 'no regression' if light else 'REGRESSION'} | mean falls over {len(ids)} V5 cells {mh:.3f} against V7 {mv:.3f} (allowed +{LIGHT_SLACK})")
    st["compared"] = dict(carry=carry, light=light, mean_v5=mh, mean_v5_v7=mv, cells=len(ids))
    save_state(st)
    report(st, H, V, h5, v5, ids)


def report(st, H, V, h5, v5, ids):
    import html as E
    hs, vs = H["summary"], V["summary"]
    rows = "".join(f"<tr><td>+{float(k) * 1000:.0f} g ({227 + float(k) * 1000:.0f} g payload)</td><td>{vs['per_load'][k]['falls']:.3f}</td><td>{hs['per_load'][k]['falls']:.3f}</td>"
                   f"<td>{vs['per_load'][k]['sway']:.1f}</td><td>{hs['per_load'][k]['sway']:.1f}</td><td>{vs['per_load'][k]['n1_speed']:.3f}</td><td>{hs['per_load'][k]['n1_speed']:.3f}</td></tr>"
                   for k in sorted(hs["per_load"], key=float))
    top = max(H["loads"], key=float)
    cells = "".join(f"<tr><td>{c}</td><td>{V['loads'][top][c]['fell_fraction']:.2f}</td><td>{H['loads'][top][c]['fell_fraction']:.2f}</td>"
                    f"<td>{(V['loads'][top][c]['roll_std_deg'] or 0):.1f}</td><td>{(H['loads'][top][c]['roll_std_deg'] or 0):.1f}</td></tr>" for c in H["loads"][top])
    v5rows = "".join(f"<tr><td>{i}</td><td>{cm(v5)[i]['fell_fraction']:.2f}</td><td>{cm(h5)[i]['fell_fraction']:.2f}</td></tr>" for i in ids) if h5 else "<tr><td colspan=3>not measured</td></tr>"
    dec = "".join(f"<li>{E.escape(l[2:])}</li>" for l in open(DECISIONS).read().splitlines() if l.startswith("- ")) if os.path.exists(DECISIONS) else ""
    c = st["compared"]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Heavy-Load Policy</title>
<style>:root{{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b64;--line:#dcdcd2;--card:#fff;--good:#1f7a3a;--bad:#a3322a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161614;--fg:#ecece6;--mut:#a3a39a;--line:#34342f;--card:#1f1f1c;--good:#6fcf8a;--bad:#f08a80}}}}
:root[data-theme="dark"]{{--bg:#161614;--fg:#ecece6;--mut:#a3a39a;--line:#34342f;--card:#1f1f1c;--good:#6fcf8a;--bad:#f08a80}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0 auto;padding:24px 16px;max-width:980px}}h1{{font-size:1.5rem}}h2{{font-size:1.1rem;margin-top:1.6rem}}
.t{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.88rem;background:var(--card)}}th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left}}th{{color:var(--mut);font-weight:600}}
.good{{color:var(--good);font-weight:600}}.bad{{color:var(--bad);font-weight:600}}.mut{{color:var(--mut)}}li{{margin:.3rem 0}}</style></head><body>
<h1>Heavy-Load Policy vs V7</h1>
<p>Carrying: <span class="{'good' if c['carry'] else 'bad'}">{'better than V7' if c['carry'] else 'not better than V7'}</span>. Today's payload: <span class="{'mut' if c['light'] is None else 'good' if c['light'] else 'bad'}">{'not measured' if c['light'] is None else 'no regression' if c['light'] else 'regression'}</span>.
Recipe: the V7 recipe + {E.escape(', '.join(st.get('recipe', [])))}. Picked: {E.escape(str(st.get('picked')))}. Not promoted, not deployed.</p>
<p class="mut">Simulator only. 1 lb is an estimate of G2's limit (not measured on G2). Every policy walks the same load-scaled commands (60% at 1 lb) on the same paired courses, {H['episodes']} episodes per cell.</p>
<h2>By load</h2><div class="t"><table><tr><th>Extra load</th><th>Falls V7</th><th>Falls new</th><th>Sway V7 (deg)</th><th>Sway new</th><th>Calm speed V7 (m/s)</th><th>Calm speed new</th></tr>{rows}</table></div>
<p>Heavy score (lower is better): V7 {vs['heavy_score']:.3f}, new {hs['heavy_score']:.3f}.</p>
<h2>Each cell at 1 lb</h2><div class="t"><table><tr><th>Cell</th><th>Falls V7</th><th>Falls new</th><th>Roll sd V7</th><th>Roll sd new</th></tr>{cells}</table></div>
<h2>Today's payload, V5 benchmark</h2><p>Mean falls over {c['cells']} cells: V7 {c['mean_v5_v7']:.3f}, new {c['mean_v5']:.3f}.</p>
<div class="t"><table><tr><th>Cell</th><th>Falls V7</th><th>Falls new</th></tr>{v5rows}</table></div>
<h2>Decisions made during the run</h2><ul>{dec}</ul></body></html>"""
    open(f"{REPORT_DIR}/report.html", "w").write(page)
    log(f"REPORT ready: rl_training/opencat-gym/{REPORT_DIR}/report.html")


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    os.makedirs(REPORT_DIR, exist_ok=True)
    st = load_state()
    clean_environ()
    extra = screens(st)
    start = chain(st, extra)
    final20m(st, extra, start)
    pick(st, extra)
    compare(st, extra)
    log("HEAVY COMPLETE")


def status():
    st = load_state()
    for k, v in st.get("screens", {}).items():
        print(f"screen {k:22s}", line(v["summary"]) if v.get("summary") else "-")
    print("recipe:", st.get("recipe", "-"))
    for name, *_ in STAGES:
        s = st.get("stages", {}).get(name)
        print(f"  {name}:", "done" if os.path.exists(f"trained/{TAG(name)}_ppo.zip") else ("training" if RP.training(TAG(name)) else "-"), line(s) if s else "")
    print("20M:", st.get("final", "training" if RP.training(TAG(FINAL[0])) else "-"), "tracked", [t // 10**6 for t in st.get("tracked", [])], "| picked:", st.get("picked", "-"),
          "| verdict:", st.get("compared", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


if __name__ == "__main__":
    {"run": run, "status": status}[sys.argv[1] if len(sys.argv) > 1 else "status"]()
