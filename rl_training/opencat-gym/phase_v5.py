"""The V5 training plan, unattended end to end (user-approved 2026-10-09; the plan and every decision rule: docs/plan-detail/v5-training-plan.md).

    python phase_v5.py run                    # the whole plan, resumable: scripted baseline -> screens -> preflight -> the 20M -> pick + export -> report
    python phase_v5.py status                 # where it is: one line per step
    python phase_v5.py decide SCREEN adopt|reject     # answer a DECISION NEEDED (then: rm trained/v5_halt and restart the watchdog)
    bash ../../tools/v5_watchdog.sh           # keeps `run` alive (relaunches it if it dies, stops on trained/v5_halt or when the plan is complete)

Steps (each one is recorded in trained/v5_state.json, so a relaunch carries on where it stopped; a run still training is waited for, never restarted):
  1. baseline   the scripted wkF walk scored once on benchmark V5 (benchmark_v5.run_all), the bar for the final report
  2. screens    control (BASE) and one lever at a time on top of it, two seeds x 3M each, scored on benchmark V5; each lever judged against the control by RULES below:
                adopt (target met, no regression), reject (target missed), or DECISION NEEDED (target met but a regression elsewhere: the runner halts for a judgement call)
  3. preflight  preflight.py on the adopted recipe (must print ALL PASS; a failure halts)
  4. final      the fresh 20M (BASE + adopted levers, plateau stop on); every 1M a tracker line (calm walk, side-hills both ways, rubble, step-up); gait checks at
                3M / 5M / 10M stop it only if G2 falls on flat ground (T1.1 or N1 above 25%)
  5. pick       the final policy and the average of its last three checkpoints, both scored in full; the better one (no flat-ground falls, then fewer hazard falls) is
                exported as trained/V5cand_ppo.onnx (+ sidecar). Not promoted, not deployed (the user decides).
  6. report     trained/v5_report/report.html: V5 against the scripted walk (report_v5.py). Publish it as an Artifact page.
Every state change is one line "[v5 HH:MM AM] ..." in trained/phase_v5.log; the lines a person must act on contain "DECISION NEEDED" or "HALT".
"""
import json
import os
import shutil
import subprocess
import sys
import time

import g2_profile
import phase_v4 as P4
import run_pipeline as RP

LOG = "trained/phase_v5.log"
HALT = "trained/v5_halt"
STATE = "trained/v5_state.json"
# The fixed V5 recipe: the V4 recipe (mirror x2, frontier curriculum, forward commands, optimizer bundle, privileged critic, half learning rate, 7.5 s hazard episodes) plus the
# V5 course (caps fixed, slopes 10% and even, no background tilt, at most two hazards, 7.5 s hazard-free baseline, pass at 0.7, gentler shoves) and the KL limit.
BASE = ["mirror_strong", "frontier", "cmd_forward", "opt_bundle", "privileged_critic", "lr_half", "hazard_long", "v5_course", "kl_limit"]
SEEDS = (42, 43)
SCREEN_STEPS = "3e6"
FINAL_TAG = "v5_20m"
SCREENS = [   # (name, lever added to BASE, what it is)
    ("control", None, "the V5 course alone"),
    ("cross_bonus", "cross_bonus", "one-time bonus for getting past the obstacle field / a ledge edge"),
    ("haz_speed", "haz_speed", "no speed-tracking penalty while on a hazard"),
    ("haz_posture", "haz_posture", "holding a non-scripted posture costs half while on a hazard"),
    ("heading_blind", "heading_blind", "the policy never sees yaw (no steering in the policy; the Pi steers); heading penalty x2"),
]
SCREEN_EPISODES, SCREEN_LADDER_EPISODES = 30, 20
FINAL_EPISODES, FINAL_LADDER_EPISODES = 100, 40
FINAL_CHECKS = (3_000_000, 5_000_000, 10_000_000)
SCRIPTED_JSON = "trained/v5_scripted.json"
REPORT_DIR = "trained/v5_report"


def log(msg):
    line = f"[v5 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {"screens": {}, "adopted": []}


def save_state(st):
    json.dump(st, open(STATE, "w"), indent=1)


def halt(msg):
    open(HALT, "w").write(msg + "\n")
    log(msg)
    raise SystemExit(1)


def clock_in(minutes):
    return time.strftime("%I:%M %p", time.localtime(time.time() + 60 * minutes))


def obs_levers(levers):
    return [l for l in levers if l in g2_profile.OBS_LEVERS]


def score(policy, levers, episodes, ladder_episodes, jobs=8):
    """benchmark_v5.run_all in a fresh process (the scoring environment must be set before the env module is imported)."""
    out = f"trained/.v5_score_tmp_{os.getpid()}.json"
    cmd = [sys.executable, "benchmark_v5.py", "--policy", policy, "--levers", ",".join(obs_levers(levers)), "--json-out", out,
           "--episodes", str(episodes), "--ladder-episodes", str(ladder_episodes), "--jobs", str(jobs)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        halt(f"HALT: scoring {policy} failed: {(r.stdout + r.stderr)[-600:]}")
    res = json.load(open(out))
    os.remove(out)
    return res


def cm(res):
    return {c["id"]: c for c in res["cells"]}


# ------------------------------------------------------------------------------------------------ measures used by the rules
def ladder_falls(res):
    s = res["size_ladder"]["summary"]
    return sum(v["mean_falls"] for v in s.values()) / max(1, len(s))


def crossing(res):
    """Mean share of 7.5 s ladder episodes that got past the whole obstacle field (rubble, boxes, snags) or over the ledge edge."""
    vals = []
    for c in res["size_ladder"]["cells"]:
        for k in ("past_all", "past_ledge"):
            if c.get(k) is not None:
                vals.append(c[k])
    return sum(vals) / max(1, len(vals))


def summary(res):
    c = cm(res)
    n1 = c.get("N1", {})
    side = res["size_ladder"]["summary"]
    return (f"T1.1 falls {c.get('T1.1', {}).get('fell_fraction', float('nan')):.2f} | N1 speed {n1.get('path_speed_mps', float('nan')):.3f} roll {n1.get('roll_std_deg', float('nan')):.1f} "
            f"heading {n1.get('heading_abs_mean_deg', float('nan')):.0f} asym {n1.get('lr_asym_max_deg', float('nan')):.1f} | ladder falls {ladder_falls(res):.2f} crossing {crossing(res):.2f} | "
            f"side-hill L/R falls {side.get('sidehill_l', {}).get('mean_falls', float('nan')):.2f}/{side.get('sidehill_r', {}).get('mean_falls', float('nan')):.2f}"
            + (f" | mirror {res['mirror_gap']:.3f}" if res.get("mirror_gap") is not None else ""))


def combine(results):
    """Two seeds -> one score: every numeric cell and ladder-cell value averaged, the ladder summary recomputed."""
    import benchmark_v5 as B
    out = P4.combine([{k: v for k, v in r.items() if k != "size_ladder"} for r in results])
    lad = []
    for c in results[0]["size_ladder"]["cells"]:
        same = [next(x for x in r["size_ladder"]["cells"] if x["id"] == c["id"]) for r in results]
        d = dict(c)
        for k, v in c.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                d[k] = float(sum(s[k] for s in same) / len(same))
            elif v is None and k in ("past_all", "past_first", "past_ledge"):
                d[k] = None
        for k in ("past_all", "past_first", "past_ledge"):
            vals = [s.get(k) for s in same if s.get(k) is not None]
            if vals:
                d[k] = float(sum(vals) / len(vals))
        lad.append(d)
    gaps = [r.get("mirror_gap") for r in results if r.get("mirror_gap") is not None]
    out["mirror_gap"] = sum(gaps) / len(gaps) if gaps else None
    out["size_ladder"] = {"cells": lad, "summary": B.ladder_summary(lad)}
    return out


# ------------------------------------------------------------------------------------------------ the decision rules (docs/plan-detail/v5-training-plan.md section 5)
SLOPE_CELLS = ("T2.2", "T3.2", "SL10", "SL8", "SR8")          # slope / tilt tests
SLOPE_HAZARDS = ("sidehill_l", "sidehill_r", "climb", "descent")
SLOPE_LARGE = 0.30       # user, 2026-10-09: slopes and tilts are not a primary trait (only some exposure); stop for them only on a LARGE regression


def regressions(a, ctrl):
    """What a lever may not do, whatever its target: fall on flat ground, slow the calm walk, or make a hazard clearly worse (slopes and tilts only if LARGELY worse)."""
    ca, cc = cm(a), cm(ctrl)
    why = []
    for c in ("T1.1", "N1"):
        lim = max(0.05, cc[c]["fell_fraction"] + 0.05)
        if ca[c]["fell_fraction"] > lim:
            why.append(f"{c} falls {ca[c]['fell_fraction']:.2f} > {lim:.2f}")
    if ca["N1"]["path_speed_mps"] < 0.95 * cc["N1"]["path_speed_mps"]:
        why.append(f"N1 speed {ca['N1']['path_speed_mps']:.3f} < 95% of the control's {cc['N1']['path_speed_mps']:.3f}")
    sa, sc = a["size_ladder"]["summary"], ctrl["size_ladder"]["summary"]
    for h in sa:
        if h in sc and sa[h]["mean_falls"] > sc[h]["mean_falls"] + (SLOPE_LARGE if h in SLOPE_HAZARDS else 0.10):
            why.append(f"{h} ladder falls {sa[h]['mean_falls']:.2f} vs {sc[h]['mean_falls']:.2f}")
    for c in SLOPE_CELLS + ("T6.1", "T7.1", "T7.2", "T8.1", "T9.1", "T11.1", "LU15", "LD15", "LU25", "LD25"):
        if c in ca and c in cc and ca[c]["fell_fraction"] > cc[c]["fell_fraction"] + (SLOPE_LARGE if c in SLOPE_CELLS else 0.15):
            why.append(f"{c} falls {ca[c]['fell_fraction']:.2f} vs {cc[c]['fell_fraction']:.2f}")
    return why


def target(name, a, ctrl):
    """The lever's own reason to exist; returns (met, text)."""
    lf, lc, xa, xc = ladder_falls(a), ladder_falls(ctrl), crossing(a), crossing(ctrl)
    if name == "cross_bonus":
        return (xa >= xc + 0.03 and lf <= lc + 0.02), f"crossing {xa:.2f} vs {xc:.2f} (needs +0.03), ladder falls {lf:.2f} vs {lc:.2f}"
    if name in ("haz_speed", "haz_posture"):
        return (lf <= lc - 0.02 or (xa >= xc + 0.03 and lf <= lc + 0.01)), f"ladder falls {lf:.2f} vs {lc:.2f} (needs -0.02), crossing {xa:.2f} vs {xc:.2f}"
    if name == "heading_blind":     # its value is on G2 (no sim steering to go wrong), so it is adopted unless it costs something in the sim (user expects to keep it)
        ha, hc = cm(a)["N1"]["heading_abs_mean_deg"], cm(ctrl)["N1"]["heading_abs_mean_deg"]
        return (lf <= lc + 0.03 and ha <= hc + 3.0), f"ladder falls {lf:.2f} vs {lc:.2f} (allowed +0.03), N1 heading {ha:.0f} vs {hc:.0f} deg (allowed +3)"
    return True, ""


# ------------------------------------------------------------------------------------------------ steps
def baseline():
    if os.path.exists(SCRIPTED_JSON):
        return json.load(open(SCRIPTED_JSON))
    log(f"BASELINE: scoring the scripted walk on benchmark V5 ({FINAL_EPISODES} episodes per cell, {FINAL_LADDER_EPISODES} per ladder size; ~15 min, done about {clock_in(15)})")
    res = score("scripted", [], FINAL_EPISODES, FINAL_LADDER_EPISODES)
    json.dump(res, open(SCRIPTED_JSON, "w"), indent=1)
    log(f"BASELINE done | {summary(res)}")
    return res


def train_and_score(tag, levers, seed):
    """One 3M screen run (resumable) and its V5 score (cached in trained/v5_score_<tag>.json)."""
    out = f"trained/v5_score_{tag}.json"
    if os.path.exists(out):
        return json.load(open(out))
    if not os.path.exists(f"trained/{tag}_ppo.zip"):
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
                raise P4.HealthStop(tag)
            if os.path.exists(f"trained/{tag}_console.log"):
                if os.path.exists(f"trained/{tag}_crash1_console.log"):
                    halt(f"HALT: {tag} crashed twice (trained/{tag}_crash1_console.log, trained/{tag}_console.log); a fix is needed")
                for f in [f for f in os.listdir("trained") if f.startswith(tag + "_")]:
                    os.replace(os.path.join("trained", f), os.path.join("trained", f.replace(tag + "_", tag + "_crash1_", 1)))
                for f in [f for f in os.listdir("trained/checkpoints") if f.startswith(tag + "_")]:
                    os.remove(os.path.join("trained/checkpoints", f))
                log(f"{tag} crashed: files kept as {tag}_crash1_*, retrying once")
            for k in [k for k in os.environ if k.startswith("G2E_")]:
                del os.environ[k]
            log(f"{tag} START: levers {levers} seed {seed} (3M, about 30 min, done about {clock_in(30)})")
            RP.launch(tag, P4.job_env(tag, levers, seed), steps=SCREEN_STEPS, base=False)
        ok, why = RP.wait_for_finish(tag)
        if not ok:
            if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
                raise P4.HealthStop(tag)
            log(f"{tag} did not finish: {why}")
            return train_and_score(tag, levers, seed)          # the crash branch above retries once, then halts
    t0 = time.time()
    res = score(f"trained/{tag}_ppo", levers, SCREEN_EPISODES, SCREEN_LADDER_EPISODES)
    json.dump(res, open(out, "w"), indent=1)
    log(f"{tag} SCORED in {(time.time() - t0) / 60:.0f} min | {summary(res)}")
    return res


def screens(st):
    ctrl = None
    for name, lever, desc in SCREENS:
        rec = st["screens"].get(name, {})
        if rec.get("decided"):
            if name == "control":
                ctrl = json.load(open(rec["combined_file"]))
            continue
        levers = list(BASE) + ([lever] if lever else [])
        log(f"SCREEN {name}: {desc} (levers {levers}, seeds {list(SEEDS)}; about 70 min, done about {clock_in(70)})")
        try:
            pair = [train_and_score(f"v5_{name}_s{seed}", levers, seed) for seed in SEEDS]
        except P4.HealthStop as e:
            if name == "control":
                halt(f"HALT: the control did not learn ({e} stopped by its own health check); the V5 course needs a look before anything else runs")
            st["screens"][name] = dict(decided=True, adopted=False, why=[f"{e} did not learn (health stop)"])
            save_state(st)
            log(f"{name} REJECTED: {e} did not learn (health stop)")
            continue
        combined = combine(pair)
        cf = f"trained/v5_combined_{name}.json"
        json.dump(combined, open(cf, "w"), indent=1)
        if name == "control":
            flat = [c for c in ("T1.1", "N1") if cm(combined)[c]["fell_fraction"] > 0.10]
            st["screens"][name] = dict(decided=True, adopted=True, combined_file=cf, why=[])
            save_state(st)
            log(f"control DONE | {summary(combined)}")
            if flat:
                halt(f"DECISION NEEDED: the control falls on flat ground ({', '.join(flat)} above 10%); continue the screens anyway "
                     f"(rm {HALT} and restart the watchdog) or fix the course first")
            ctrl = combined
            continue
        reg = regressions(combined, ctrl)
        met, ttxt = target(name, combined, ctrl)
        rec = dict(decided=True, combined_file=cf, target=ttxt, regressions=reg)
        if met and not reg:
            rec["adopted"] = True
            st["adopted"].append(lever)
            log(f"{name} ADOPTED | target: {ttxt} | {summary(combined)}")
        elif not met:
            rec["adopted"] = False
            log(f"{name} REJECTED (target not met: {ttxt}){' and regressions ' + str(reg) if reg else ''} | {summary(combined)}")
        else:
            rec["decided"] = False
            rec["pending"] = True
            st["screens"][name] = rec
            save_state(st)
            halt(f"DECISION NEEDED: {name} met its target ({ttxt}) but regressed elsewhere: {reg}. Decide with `phase_v5.py decide {name} adopt|reject`, "
                 f"then rm {HALT} and restart the watchdog")
        st["screens"][name] = rec
        save_state(st)
    log(f"SCREENS COMPLETE: adopted {st['adopted'] or 'none'}; recipe {BASE + st['adopted']}")
    return ctrl


LEDGE_TOP = "0.03"      # user, 2026-10-09: step-up and step-down tops 30 mm (the screens ran with 35 / 40 mm)


def use_ledge30():
    """From the preflight on, everything (20M recipe, tracker, scoring, report) uses the 30 mm ledge tops; the scripted walk's ledge ladders are re-scored once at the same sizes."""
    os.environ["G2E_V5_LEDGE_TOP"] = LEDGE_TOP


def rescore_scripted_ledges(st):
    if st.get("scripted_ledge30"):
        return
    log("BASELINE (ledges): re-scoring the scripted walk's step-up and step-down ladders at the 30 mm tops (about 3 min)")
    code = ("import json, sys; sys.path.insert(0, '.'); import benchmark_v5 as B; P = 'trained/v5_scripted.json'; d = json.load(open(P)); "
            "json.dump(d, open('trained/v5_scripted_ledge40.json', 'w')); "
            f"r = B.run_ladder('scripted', (), {FINAL_LADDER_EPISODES}, jobs=4, hazards=['ledge_up', 'ledge_down'], quiet=True); "
            "cells = [c for c in d['size_ladder']['cells'] if c['hazard'] not in ('ledge_up', 'ledge_down')] + r['cells']; "
            "d['size_ladder']['cells'] = cells; d['size_ladder']['summary'] = B.ladder_summary(cells); json.dump(d, open(P, 'w'), indent=1); print('MERGED')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "G2E_V5_LEDGE_TOP": LEDGE_TOP})
    if "MERGED" not in r.stdout:
        halt(f"HALT: re-scoring the scripted ledge ladders failed: {(r.stdout + r.stderr)[-500:]}")
    st["scripted_ledge30"] = True
    save_state(st)


def preflight(st):
    use_ledge30()
    rescore_scripted_ledges(st)
    if st.get("preflight") == "pass":
        return
    levers = BASE + st["adopted"] + ["ledge30"]
    log(f"PREFLIGHT on {levers} (about 15 min, done about {clock_in(15)})")
    r = subprocess.run([sys.executable, "preflight.py", "--levers", ",".join(levers)], capture_output=True, text=True)
    open("trained/v5_preflight.log", "w").write(r.stdout + r.stderr)
    if "ALL PASS" not in r.stdout:
        halt(f"HALT: preflight FAILED on the adopted recipe (trained/v5_preflight.log): {[l for l in r.stdout.splitlines() if 'FAIL' in l][:6]}")
    st["preflight"] = "pass"
    save_state(st)
    log("PREFLIGHT ALL PASS")


def track(step, levers):
    """The 1M tracker: calm walk, side-hills both ways, rubble and a step up on a checkpoint, with 3 workers (the training is running)."""
    ck = f"trained/checkpoints/{FINAL_TAG}_{step}_steps"
    out = f"trained/.v5_track_{step}.json"
    cmd = [sys.executable, "-c",
           "import sys, json; sys.path.insert(0, '.'); import benchmark_v4 as V, benchmark_v5 as B; "
           f"r = V.run({ck!r}, 'T1.1,N1,SL8,SR8', 20, 1000, 3, None, {tuple(obs_levers(levers))!r}, None, mirror_gap=True, quiet=True); "
           f"r['size_ladder'] = B.run_ladder({ck!r}, {tuple(obs_levers(levers))!r}, 12, jobs=3, hazards=['sidehill_l', 'sidehill_r', 'rubble', 'ledge_up'], quiet=True); "
           f"json.dump(r, open({out!r}, 'w'))"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        log(f"{FINAL_TAG} tracker {step // 10**6}M failed (the run continues): {(r.stdout + r.stderr)[-300:]}")
        return None
    res = json.load(open(out))
    os.remove(out)
    c, s = cm(res), res["size_ladder"]["summary"]
    row = dict(step=step, n1_heading=c["N1"]["heading_abs_mean_deg"], n1_asym=c["N1"]["lr_asym_max_deg"], n1_roll=c["N1"]["roll_std_deg"], n1_speed=c["N1"]["path_speed_mps"],
               t11_falls=c["T1.1"]["fell_fraction"], n1_falls=c["N1"]["fell_fraction"], sl8=c["SL8"]["fell_fraction"], sr8=c["SR8"]["fell_fraction"], mirror=res.get("mirror_gap"),
               **{f"{h}_falls": s[h]["mean_falls"] for h in s}, **{f"{h}_passed": s[h]["largest_passed"] for h in s})
    with open(f"trained/{FINAL_TAG}_curve.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    log(f"{FINAL_TAG} TRACK {step // 10**6}M | N1 heading {row['n1_heading']:.0f} asym {row['n1_asym']:.1f} roll {row['n1_roll']:.1f} speed {row['n1_speed']:.3f} | "
        f"side-hill 8 deg L/R falls {row['sl8']:.2f}/{row['sr8']:.2f} | ladder falls L {s['sidehill_l']['mean_falls']:.2f} R {s['sidehill_r']['mean_falls']:.2f} "
        f"rubble {s['rubble']['mean_falls']:.2f} step-up {s['ledge_up']['mean_falls']:.2f} | mirror {res.get('mirror_gap') or float('nan'):.3f}")
    return row


def final(st):
    use_ledge30()
    if st.get("final") == "done":
        return
    levers = BASE + st["adopted"] + ["ledge30"]
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    env = g2_profile.env_for_job({"kind": "final", "tag": FINAL_TAG, "fresh": True, "levers": list(levers)})
    env = {k: v for k, v in env.items() if v != ""}
    if not RP.training(FINAL_TAG) and not os.path.exists(f"trained/{FINAL_TAG}_ppo.zip"):
        log(f"{FINAL_TAG} START: the fresh 20M with {levers} (plateau stop on; about 3.5 h, done about {clock_in(210)})")
        RP.launch(FINAL_TAG, env, steps="20e6", base=False)
    done = set(st.get("tracked", []))
    step = 1_000_000
    while True:
        if os.path.exists(f"trained/{FINAL_TAG}_ppo.zip") and not os.path.exists(RP.ckpt(FINAL_TAG, step)):
            break                                                  # finished (or plateau-stopped) before this checkpoint
        if step in done:
            step += 1_000_000
            continue
        ok, why = RP.wait_for_ckpt(FINAL_TAG, step)
        if not ok:
            if os.path.exists(f"trained/{FINAL_TAG}_ppo.zip"):
                break
            if os.path.exists(f"trained/{FINAL_TAG}_health_stop_ppo.zip"):
                halt(f"DECISION NEEDED: the 20M was stopped by its own health check before {step // 10**6}M (trained/{FINAL_TAG}_console.log): relaunch, change the recipe, or stop")
            halt(f"HALT: the 20M stopped before {step // 10**6}M: {why}")
        row = track(step, levers)
        if step in FINAL_CHECKS and row is not None and max(row["t11_falls"], row["n1_falls"]) > 0.25:
            RP.stop(FINAL_TAG)
            halt(f"DECISION NEEDED: the 20M falls on flat ground at {step // 10**6}M (T1.1 {row['t11_falls']:.2f}, N1 {row['n1_falls']:.2f}); stopped. Relaunch or change the recipe")
        done.add(step)
        st["tracked"] = sorted(done)
        save_state(st)
        step += 1_000_000
        if step > 20_000_000:
            break
    ok, why = RP.wait_for_finish(FINAL_TAG)
    if not ok:
        halt(f"HALT: the 20M did not finish: {why}")
    st["final"] = "done"
    save_state(st)
    log(f"{FINAL_TAG} FINISHED")


def average_checkpoints(paths, out):
    """Mean of the policies' weights (same architecture, late in a low-learning-rate run): often steadier than any single checkpoint."""
    code = ("import sys, torch; sys.path.insert(0, '.'); from stable_baselines3 import PPO; "
            f"ps = {paths!r}; ms = [PPO.load(p, device='cpu') for p in ps]; sd = [m.policy.state_dict() for m in ms]; "
            "avg = {k: (sum(s[k].float() for s in sd) / len(sd)).to(sd[0][k].dtype) for k in sd[0]}; "
            f"ms[-1].policy.load_state_dict(avg); ms[-1].save({out!r}); print('AVERAGED')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return "AVERAGED" in r.stdout, (r.stdout + r.stderr)[-400:]


def pick(st):
    use_ledge30()
    if st.get("picked"):
        return st["picked"]
    import glob
    import re
    levers = BASE + st["adopted"] + ["ledge30"]
    cks = sorted(glob.glob(f"trained/checkpoints/{FINAL_TAG}_*_steps.zip"), key=lambda p: int(re.search(r"_(\d+)_steps", p).group(1)))
    cands = [("final", f"trained/{FINAL_TAG}_ppo")]
    if len(cks) >= 3:
        ok, out = average_checkpoints([c[:-4] for c in cks[-3:]], f"trained/{FINAL_TAG}_avg3_ppo")
        if ok:
            cands.append(("avg3", f"trained/{FINAL_TAG}_avg3_ppo"))
        else:
            log(f"checkpoint averaging failed (only the final policy is scored): {out}")
    os.makedirs(REPORT_DIR, exist_ok=True)
    scored = {}
    for key, path in cands:
        f = f"{REPORT_DIR}/{key}.json"
        if not os.path.exists(f):
            log(f"PICK: scoring {key} ({path}) in full (about 15 min, done about {clock_in(15)})")
            json.dump(score(path, levers, FINAL_EPISODES, FINAL_LADDER_EPISODES), open(f, "w"), indent=1)
        scored[key] = json.load(open(f))
        log(f"PICK: {key} | {summary(scored[key])}")
    flat_ok = {k: all(cm(r)[c]["fell_fraction"] == 0 for c in ("T1.1", "N1")) for k, r in scored.items()}
    def hazard_falls(r):
        cells = [c for cid, c in cm(r).items() if cid.startswith(("T", "S", "L")) and cid not in ("T1.1", "T1.2", "L1")]
        return (ladder_falls(r) + sum(c["fell_fraction"] for c in cells) / max(1, len(cells))) / 2.0
    best = min(scored, key=lambda k: (not flat_ok[k], hazard_falls(scored[k])))
    path = dict(cands)[best]
    log(f"PICK: {best} ({path}) chosen: flat-ground falls none = {flat_ok[best]}, ladder falls {ladder_falls(scored[best]):.2f}")
    cmd = [sys.executable, "export_onnx.py", "--model", path, "--out", "trained/V5cand_ppo.onnx", "--residual-scale-deg", "30", "--cmd-send-every-n", "3"]
    if "heading_blind" in st["adopted"]:
        cmd.append("--heading-blind")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or "MISMATCH" in r.stdout:
        halt(f"HALT: export of {path} failed: {(r.stdout + r.stderr)[-400:]}")
    log("EXPORTED trained/V5cand_ppo.onnx (+ .onnx.json); not promoted, not deployed (the user decides)")
    shutil.copy(f"{REPORT_DIR}/{best}.json", f"{REPORT_DIR}/v5.json")
    st["picked"] = best
    save_state(st)
    return best


def report(st):
    use_ledge30()
    if st.get("report") == "done":
        return
    import report_v5
    P = json.load(open(f"{REPORT_DIR}/v5.json"))
    S = json.load(open(SCRIPTED_JSON))
    fr = json.load(open(f"trained/{FINAL_TAG}_frontier.json")) if os.path.exists(f"trained/{FINAL_TAG}_frontier.json") else None
    out = f"{REPORT_DIR}/report.html"
    open(out, "w").write(report_v5.build(P, S, fr, title="G2 Gait V5 vs Scripted", console=f"trained/{FINAL_TAG}_console.log", policy_name="V5"))
    st["report"] = "done"
    save_state(st)
    log(f"REPORT ready: rl_training/opencat-gym/{out} (publish it as an Artifact page)")


def run():
    if os.path.exists(HALT):
        raise SystemExit(f"{HALT} exists: {open(HALT).read().strip()}  (resolve it, then rm {HALT})")
    st = load_state()
    baseline()
    screens(st)
    preflight(st)
    final(st)
    pick(st)
    report(st)
    log("V5 COMPLETE")


def status():
    st = load_state()
    print("scripted baseline:", "scored" if os.path.exists(SCRIPTED_JSON) else "not yet")
    for name, lever, _ in SCREENS:
        rec = st["screens"].get(name)
        print(f"  {name:14s}", "not started" if not rec else ("PENDING DECISION " + str(rec.get("regressions")) if rec.get("pending") else
                                                             ("ADOPTED" if rec.get("adopted") else "rejected") + " " + (rec.get("target") or str(rec.get("why") or ""))))
    print("adopted:", st.get("adopted"), "| preflight:", st.get("preflight", "-"), "| 20M:", st.get("final", "-"), "tracked", st.get("tracked", []),
          "| picked:", st.get("picked", "-"), "| report:", st.get("report", "-"))
    if os.path.exists(HALT):
        print("HALTED:", open(HALT).read().strip())


def decide(name, verdict):
    st = load_state()
    rec = st["screens"].get(name)
    if rec is None:
        raise SystemExit(f"no screen {name}")
    rec["decided"], rec["pending"] = True, False
    rec["adopted"] = verdict == "adopt"
    rec["decided_by"] = "person"
    lever = dict((n, l) for n, l, _ in SCREENS).get(name)
    if rec["adopted"] and lever and lever not in st["adopted"]:
        st["adopted"].append(lever)
    if not rec["adopted"] and lever in st["adopted"]:
        st["adopted"].remove(lever)
    save_state(st)
    log(f"{name} {'ADOPTED' if rec['adopted'] else 'REJECTED'} by decision (phase_v5.py decide)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "decide":
        decide(sys.argv[2], sys.argv[3])
    else:
        {"run": run, "status": status}[cmd]()
