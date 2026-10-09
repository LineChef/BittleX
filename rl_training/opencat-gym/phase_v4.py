"""Unattended screening of the 2026-10-08 training upgrade (docs/plan-detail/handoff-2026-10-08.md section 12), then the 20M on the user's go.

    python phase_v4.py run       # work through SCREENS (resumable: a finished run is not redone, a run still training is waited for)
    python phase_v4.py status    # one line per screen
    python phase_v4.py final     # the 20M with the adopted recipe (ONLY on the user's go): gait checks at 3M / 5M / 10M against the adopted 3M pair, plateau stop

Each screen trains TWO seeds (42, 43) of a fresh 3M run in the next 20M's own world (g2_profile.env_for_job of a fresh final: the full course, world 2, hard x1.10),
with the base recipe plus one lever, scores both on benchmark v5 (every cell, 40 episodes, plus the difficulty ladder; episodes are seeded, so the base and the lever
meet the same courses) and averages the two seeds. Adoption is sequential: a lever that passes joins the base, and its own pair becomes the next control.
Gate (every lever): the calm walk does not regress (T1.1 / N1 falls <= min(0.15, base + 0.05), speed >= 90% of the base) and no decision cell falls more than
PAIR_MARGIN above the base; plus the lever's own target (TARGETS). `cmd_forward` is the user's decision (drop backward) and is adopted whatever the screen says
(the result is still recorded). `opt_bundle` that fails is repaired by leaving one part out at a time (the first passing variant is adopted).
Every state change is one line "[v4 HH:MM AM] ..." in trained/phase_v4.log. Nothing here waits for a person except `final`, which only runs when the user says go.
"""
import json
import os
import sys
import time

import g2_profile
import phase_v3 as V3
import run_pipeline as RP

LOG = "trained/phase_v4.log"
HALT = "trained/v4_halt"                     # written on a failure that needs a fix: the watchdog stops relaunching the runner
RESULTS = "trained/v4_results.json"
BASE_LEVERS = ["mirror"]                     # K3, the recipe the parked 20M was going to use
SEEDS = (42, 43)
STEPS = "3e6"
EPISODES = 40
PAIR_MARGIN = 0.10                           # two-seed averages: a decision cell may not fall more than this above the base
HAZARD_CELLS = ["T2.2", "T3.2", "T5.2", "T7.2", "T8.1", "T9.1", "T10.2", "T11.1"]
# (name, levers added, description)
SCREENS = [
    ("control", [], "control: the current recipe on the fixed code and the native stack"),
    ("big_batch", ["big_batch"], "PPO batch 4096 x 5 epochs (20 gradient steps per rollout instead of 2,560)"),
    ("frontier", ["frontier"], "per-hazard frontier curriculum replaces the probe levels and the static caps"),
    ("cmd_forward", ["cmd_forward"], "no backward commands, no unreachable fast band (user decision)"),
    ("opt_bundle", ["opt_bundle"], "reward normalization, starting noise std 0.37, learning-rate floor 3e-5"),
    ("hazard_contact", ["hazard_contact"], "hazard-focus episodes 4.7 s with obstacles spread to match"),
    ("imitation_actual", ["imitation_actual"], "imitation reward on the measured joints"),
    ("privileged_critic", ["privileged_critic"], "critic sees the true state and the hazards (the policy's inputs unchanged)"),
]
USER_DECIDED = {"cmd_forward"}
OPT_PARTS = {"norm_reward": {"G2E_NORM_REWARD": "0"}, "std_init": {"G2E_LOG_STD_INIT": ""}, "lr_floor": {"G2E_LR_FLOOR": "0"}}   # what leaving each part out sets


def log(msg):
    line = f"[v4 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, obj):
    json.dump(obj, open(path, "w"), indent=1)


def job_env(tag, levers, seed, extra=None):
    """The 20M's own world at 3M: a fresh final (full course, world 2, hard x1.10) with these levers and this seed. Every key not in the profile is unset."""
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
    env.update({"G2E_SEED": str(seed)})
    env.pop("G2E_PLATEAU_STOP", None)           # never in a 3M screen
    env.update(extra or {})
    return {k: v for k, v in env.items() if v != ""}


def obs_levers(levers):
    return [l for l in levers if l in g2_profile.OBS_LEVERS]


class HealthStop(Exception):
    """The run's own health check stopped it (it was not learning): a verdict on the lever, not a crash."""


def run_one(tag, levers, seed, extra=None):
    """Train (or resume / skip) one 3M run and score it; returns the score dict (cached in trained/v4_score_<tag>.json)."""
    out = f"trained/v4_score_{tag}.json"
    if os.path.exists(out):
        return json.load(open(out))
    for attempt in (1, 2):
        if os.path.exists(f"trained/{tag}_ppo.zip"):
            break
        if not RP.training(tag):
            if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
                raise HealthStop(tag)
            if os.path.exists(f"trained/{tag}_console.log"):          # a run that died: keep its files aside and try once more (no person in the loop)
                if attempt == 2 or os.path.exists(f"trained/{tag}_crash1_console.log"):
                    open(HALT, "w").write(f"{tag} crashed twice\n")
                    raise SystemExit(log(f"{tag} HALT: crashed twice (trained/{tag}_crash1_console.log, trained/{tag}_console.log); the watchdog stops, fix needed") or 1)
                for f in [f for f in os.listdir("trained") if f.startswith(tag + "_")]:
                    os.replace(os.path.join("trained", f), os.path.join("trained", f.replace(tag + "_", tag + "_crash1_", 1)))
                for f in [f for f in os.listdir("trained/checkpoints") if f.startswith(tag + "_")]:
                    os.remove(os.path.join("trained/checkpoints", f))
                log(f"{tag} crashed: files kept as {tag}_crash1_*, retrying once")
            for k in [k for k in os.environ if k.startswith("G2E_")]:
                del os.environ[k]
            log(f"{tag} START: levers {levers} seed {seed}{' extra ' + str(extra) if extra else ''}")
            RP.launch(tag, job_env(tag, levers, seed, extra), steps=STEPS, base=False)
        ok, why = RP.wait_for_finish(tag)
        if ok:
            break
        log(f"{tag} did not finish: {why}")
        if os.path.exists(f"trained/{tag}_health_stop_ppo.zip"):
            raise HealthStop(tag)
    t0 = time.time()
    res = V3.score(f"trained/{tag}_ppo", obs_levers(levers), ladder=True, ladder_levers=tuple(levers))
    res["explained_variance_last"] = _last_ev(tag)
    save(out, res)
    log(f"{tag} SCORED in {(time.time() - t0) / 60:.0f} min | {V3.summary(res)}")
    return res


def _last_ev(tag):
    try:
        vals = [float(l.split("|")[2]) for l in open(f"trained/{tag}_console.log", errors="replace") if "explained_variance" in l]
        return float(sum(vals[-20:]) / len(vals[-20:])) if vals else None
    except (OSError, ValueError, IndexError):
        return None


def combine(results):
    """Average a pair of scores: every numeric cell metric, the ladder's per-category relative scores, explained variance."""
    out = dict(results[0])
    cells = []
    for c in results[0]["cells"]:
        same = [next(x for x in r["cells"] if x["id"] == c["id"]) for r in results]
        d = dict(c)
        for k, v in c.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                d[k] = float(sum(s[k] for s in same) / len(same))
        cells.append(d)
    out["cells"] = cells
    evs = [r.get("explained_variance_last") for r in results if r.get("explained_variance_last") is not None]
    out["explained_variance_last"] = sum(evs) / len(evs) if evs else None
    lads = [r.get("ladder", {}).get("summary") for r in results if r.get("ladder")]
    if lads:
        out["ladder_score"] = float(sum(ladder_score(s) for s in lads) / len(lads))
    return out


def ladder_score(summary):
    """Mean relative score over every category and level of the ladder (1 = no worse than the clean floor everywhere)."""
    vals = [v for cat in summary["categories"].values() for v in cat["rel"].values()]
    return float(sum(vals) / len(vals)) if vals else 0.0


def hazard_falls(res):
    m = V3.cellmap(res)
    return sum(m[c]["fell_fraction"] for c in HAZARD_CELLS if c in m) / max(1, sum(c in m for c in HAZARD_CELLS))


TARGETS = {    # the lever's own target, on top of "no regression"
    "frontier": lambda a, b: [] if (hazard_falls(a) <= hazard_falls(b) + 0.02 and a.get("ladder_score", 0) >= b.get("ladder_score", 0) - 0.03)
    else [f"hazards: falls {hazard_falls(a):.2f} vs {hazard_falls(b):.2f}, ladder {a.get('ladder_score', 0):.2f} vs {b.get('ladder_score', 0):.2f}"],
    "hazard_contact": lambda a, b: [] if hazard_falls(a) <= hazard_falls(b) else [f"hazard falls {hazard_falls(a):.2f} > {hazard_falls(b):.2f}"],
    "imitation_actual": lambda a, b: [] if hazard_falls(a) <= hazard_falls(b) + 0.02 else [f"hazard falls {hazard_falls(a):.2f} vs {hazard_falls(b):.2f}"],
    "privileged_critic": lambda a, b: [] if (a.get("explained_variance_last") or 0) >= (b.get("explained_variance_last") or 0) - 0.02
    else [f"explained variance {a.get('explained_variance_last')} vs {b.get('explained_variance_last')}"],
}


def gate(name, a, b):
    why = V3.calm_ok(a, b)
    ma, mb = V3.cellmap(a), V3.cellmap(b)
    why += [f"{c} falls {ma[c]['fell_fraction']:.2f} vs {mb[c]['fell_fraction']:.2f}" for c in V3.DECISION_CELLS
            if c in ma and c in mb and ma[c]["fell_fraction"] > mb[c]["fell_fraction"] + PAIR_MARGIN]
    if name in TARGETS:
        why += TARGETS[name](a, b)
    return why


def screen_pair(name, levers, extra=None, label=None):
    label = label or name
    res = [run_one(f"v4_{label}_s{seed}", levers, seed, extra) for seed in SEEDS]
    return combine(res)


def run():
    results = load(RESULTS, {"base": list(BASE_LEVERS), "screens": {}})
    base_res = None
    for name, add, desc in SCREENS:
        levers = list(results["base"]) + [l for l in add if l not in results["base"]]
        rec = results["screens"].get(name)
        if rec and rec.get("decided"):
            if rec.get("adopted"):
                base_res = json.load(open(rec["combined_file"]))
            elif base_res is None and name == "control":
                base_res = json.load(open(rec["combined_file"]))
            continue
        log(f"SCREEN {name}: {desc} (levers {levers}{', ' + str(results.get('base_extra')) if results.get('base_extra') else ''}, seeds {list(SEEDS)})")
        try:
            combined = screen_pair(name, levers, extra=results.get("base_extra") or None)
        except HealthStop as e:
            if name == "control":
                raise
            why = [f"{e} did not learn: stopped by its own health check (explained variance below 0.2 twice); see trained/{e}_console.log"]
            results["screens"][name] = dict(levers=levers, combined_file=None, decided=True, adopted=False, why=why, extra={})
            log(f"{name} REJECTED {why}")
            save(RESULTS, results)
            continue
        cf = f"trained/v4_combined_{name}.json"
        save(cf, combined)
        if name == "control":
            results["screens"][name] = dict(levers=levers, combined_file=cf, decided=True, adopted=True, why=[])
            base_res = combined
            log(f"control DONE | {V3.summary(combined)} | ladder {combined.get('ladder_score', 0):.2f} | ev {combined.get('explained_variance_last')}")
            save(RESULTS, results)
            continue
        why = gate(name, combined, base_res)
        adopted = not why or name in USER_DECIDED
        part_extra = {}
        if why and name == "opt_bundle":
            adopted, levers, cf, why, part_extra = repair_opt(levers, base_res, why, results.get("base_extra") or {})
        results["screens"][name] = dict(levers=levers, combined_file=cf, decided=True, adopted=adopted, why=why, extra=part_extra)
        if adopted:
            results["base"] = levers
            results["base_extra"] = dict(results.get("base_extra") or {}, **part_extra)
            base_res = json.load(open(cf))
        log(f"{name} {'ADOPTED' if adopted else 'REJECTED'}{' (user decision; gate said ' + str(why) + ')' if (why and name in USER_DECIDED) else (' ' + str(why) if why else '')} | "
            f"{V3.summary(json.load(open(cf)))} | ladder {json.load(open(cf)).get('ladder_score', 0):.2f}")
        save(RESULTS, results)
    ablate_cmd_capped(results, base_res)
    log(f"SCREENS COMPLETE: adopted recipe {results['base']} {results.get('base_extra') or ''}. Next: preflight, the final bug sweep, then the 20M on the user's go")


def cmd_capped_verdict(a, b):
    """The cap-only variant (backward kept) replaces the full `cmd_forward` only if it clearly wins: calm-walk speed up at least 5% on T1.1 and N1, falls on T3.2 and
    T11.1 no higher, hazard falls overall no higher (+0.02), and the usual calm-walk gate. Otherwise `cmd_forward` stays. Returns the reasons it does not win."""
    ma, mb = V3.cellmap(a), V3.cellmap(b)
    why = list(V3.calm_ok(a, b))
    for c in ("T1.1", "N1"):
        if c in ma and c in mb and ma[c]["speed_mps"] < 1.05 * mb[c]["speed_mps"]:
            why.append(f"{c} speed {ma[c]['speed_mps']:.3f} is not 5% above {mb[c]['speed_mps']:.3f}")
    for c in ("T3.2", "T11.1"):
        if c in ma and c in mb and ma[c]["fell_fraction"] > mb[c]["fell_fraction"]:
            why.append(f"{c} falls {ma[c]['fell_fraction']:.2f} vs {mb[c]['fell_fraction']:.2f}")
    if hazard_falls(a) > hazard_falls(b) + 0.02:
        why.append(f"hazard falls {hazard_falls(a):.2f} vs {hazard_falls(b):.2f}")
    return why


def ablate_cmd_capped(results, base_res):
    """After the screens (user approved 2026-10-08): the adopted recipe with `cmd_forward` swapped for `cmd_capped` (only the unreachable fast band removed, backward kept),
    two seeds, compared with the adopted recipe's own combined score. Tells whether dropping backward walking is what `cmd_forward` cost. Resumable; recorded under
    results["ablations"] (not "screens", so the screen count that `final` checks is unchanged)."""
    rec = results.get("ablations", {}).get("cmd_capped")
    if (rec and rec.get("decided")) or "cmd_forward" not in results["base"]:
        return
    levers = ["cmd_capped" if l == "cmd_forward" else l for l in results["base"]]
    log(f"ABLATION cmd_capped: the adopted recipe with only the fast band removed and backward kept (levers {levers}, seeds {list(SEEDS)})")
    try:
        combined = screen_pair("cmd_capped", levers, extra=results.get("base_extra") or None)
    except HealthStop as e:
        why = [f"{e} did not learn: stopped by its own health check"]
        results.setdefault("ablations", {})["cmd_capped"] = dict(decided=True, swapped=False, why=why)
        log(f"cmd_capped KEPT cmd_forward {why}")
        save(RESULTS, results)
        return
    cf = "trained/v4_combined_cmd_capped.json"
    save(cf, combined)
    why = cmd_capped_verdict(combined, base_res)
    swapped = not why
    results.setdefault("ablations", {})["cmd_capped"] = dict(decided=True, swapped=swapped, combined_file=cf, why=why)
    if swapped:
        results["base"] = levers
    log(f"cmd_capped {'SWAPPED IN for cmd_forward' if swapped else 'KEPT cmd_forward'}{'' if swapped else ' ' + str(why)} | {V3.summary(combined)} | ladder {combined.get('ladder_score', 0):.2f}")
    save(RESULTS, results)


def repair_opt(levers, base_res, why0, base_extra):
    """opt_bundle failed: leave one part out at a time; adopt the first variant that passes (returned as the setting that removes the part), else drop the bundle."""
    log(f"opt_bundle FAILED {why0}: trying it without one part at a time")
    for part, unset in OPT_PARTS.items():
        try:
            combined = screen_pair("opt_bundle", levers, extra=dict(base_extra, **unset), label=f"opt_bundle_wo_{part}")
        except HealthStop as e:
            log(f"opt_bundle without {part}: FAIL {e} did not learn (health stop)")
            continue
        cf = f"trained/v4_combined_opt_bundle_wo_{part}.json"
        save(cf, combined)
        why = gate("opt_bundle", combined, base_res)
        log(f"opt_bundle without {part}: {'PASS' if not why else 'FAIL ' + str(why)}")
        if not why:
            return True, levers, cf, [], dict(unset)
    return False, [l for l in levers if l != "opt_bundle"], "trained/v4_combined_opt_bundle.json", why0, {}


def status():
    r = load(RESULTS, {})
    print("base:", r.get("base"), r.get("base_extra", ""))
    for name, rec in r.get("screens", {}).items():
        print(f"{name:18s} {'ADOPTED' if rec.get('adopted') else 'rejected'} {rec.get('why') or ''}")
    for name, rec in r.get("ablations", {}).items():
        print(f"ablation {name:10s} {'SWAPPED IN' if rec.get('swapped') else 'kept cmd_forward'} {rec.get('why') or ''}")


FINAL_CHECKS = (3_000_000, 5_000_000, 10_000_000)


def final(tag="v4_20m"):
    """The 20M (user's go only): the adopted recipe in the 20M world with the plateau stop; gait checks against the adopted pair's 3M scores."""
    r = load(RESULTS, {})
    if not r.get("screens") or not all(rec.get("decided") for rec in r["screens"].values()) or len(r["screens"]) < len(SCREENS):
        raise SystemExit("the screens have not all finished: run `phase_v4.py run` first")
    levers, extra = r["base"], r.get("base_extra", {})
    adopted = [rec for rec in r["screens"].values() if rec.get("adopted")]
    base = json.load(open(adopted[-1]["combined_file"]))
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
    env.update(extra)
    env = {k: v for k, v in env.items() if v != ""}
    if not RP.training(tag) and not os.path.exists(f"trained/{tag}_ppo.zip"):
        log(f"{tag} START: the 20M with {levers} {extra or ''} (plateau stop on)")
        RP.launch(tag, env, steps="20e6", base=False)
    for step in FINAL_CHECKS:
        ok, why = RP.wait_for_ckpt(tag, step)
        if not ok:
            if os.path.exists(f"trained/{tag}_ppo.zip"):
                break                                  # the plateau stop ended the run before this check
            raise SystemExit(log(f"{tag} HALT before {step // 10**6}M: {why}") or 1)
        res = V3.score(f"trained/checkpoints/{tag}_{step}_steps", obs_levers(levers), spec=",".join(V3.DECISION_CELLS), busy=True)
        save(f"trained/v4_score_{tag}_{step // 10**6}M.json", res)
        bad = V3.calm_ok(res, base) + V3.regressions(res, base)
        log(f"{tag} GAIT CHECK {step // 10**6}M {'PASS' if not bad else 'REGRESSION ' + str(bad)} | {V3.summary(res)}")
        if bad:
            RP.stop(tag)
            raise SystemExit(log(f"{tag} STOPPED at {step // 10**6}M on a regression") or 1)
    ok, why = RP.wait_for_finish(tag)
    log(f"{tag} {'FINISHED' if ok else 'HALT: ' + why}")
    if ok:
        compare_v3_v4(tag, levers)


V3_POLICY = "trained/v3_20m_ppo"            # Release_CandidateV3, the deployed policy
DELAY_CELLS = "T1.1,N1,T3.2,T5.2,T6.1,T8.1,N5"     # the reality-gap check: calm walks, a side-hill, a ledge, rubble, shoves, the yaw push


def difficulty_reached(tag, levers, extra=None):
    """The hardest size of each challenge a run was training at when it ended (user, 2026-10-08: show it in the benchmark report). Frontier runs: each hazard's frontier bin
    and any blocked ceiling (trained/<tag>_frontier.json). Level runs: the last [probe] levels mapped through the run's own course (ranges x level, x1.10 hard scaling where it
    applies, the live caps at the end, hazards the course did not have marked as such)."""
    import opencat_gym_env as E
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
    env.update(extra or {})
    fr = f"trained/{tag}_frontier.json"
    if env.get("G2E_FRONTIER") == "1" and os.path.exists(fr):
        st = json.load(open(fr))
        K, rows = st["n_bins"], {}
        names = {"sidehill": ("Side-hill", "deg", 1), "climb": ("Climb", "deg", 1), "descent": ("Descent", "deg", 1), "ledge_up": ("Step up", "cm", 100),
                 "ledge_down": ("Step down", "cm", 100), "rubble": ("Rubble", "x level-1 size", 1), "boxes": ("Box obstacles", "x level-1 size", 1),
                 "rough": ("Rough floor", "x level-1 size", 1), "snag": ("Snag obstacles", "x level-1 size", 1), "cutback": ("Overheat cutback", "x level-1 size", 1)}
        for h, F in st["F"].items():
            nm, unit, k = names[h]
            b = st["bound"][h]
            txt = f"{(F + 1) / K * b * k:.3g} {unit} (frontier bin {F + 1} of {K})"
            if st["blocked"].get(h) is not None:
                txt += f"; ceiling found at {st['blocked'][h] / K * b * k:.3g} {unit} (unpassable so far)"
            rows[nm] = txt
        return {"note": f"per-hazard frontier curriculum, {st['steps']:,} steps; a bin counts once the policy passes it at least half as often as a hazard-free walk", "rows": rows}
    probes = [l for l in open(f"trained/{tag}_console.log", errors="replace") if l.startswith("[probe]")] if os.path.exists(f"trained/{tag}_console.log") else []
    if not probes:
        return {"note": "no curriculum record in the run's log", "rows": {}}
    import re
    lv = {c: float(v) for c, v in re.findall(r"(terrain|ledge|slope|fault) [0-9.]+ \([0-9.]+\) -> ([0-9.]+)", probes[-1])}
    steps = int(re.search(r"steps (\d+)", probes[-1]).group(1))
    caps = json.load(open(f"trained/{tag}_caps.json")) if os.path.exists(f"trained/{tag}_caps.json") else {}
    hard = float(env.get("G2E_HARD_SCALE", "1") or 1)
    def capped(v, key):
        c = float(caps.get(key, 0) or 0)
        return min(v, c) if c > 0 else v
    on = lambda k: float(env.get(k, "0") or 0) > 0
    rows = {}
    L = lv.get("slope", 0.0)
    rows["Side-hill"] = f"{capped(15.0 * L, 'sidehill_deg'):.3g} deg (slope level {L:.2f})"
    rows["Climb"] = f"{capped(24.0 * L, 'uphill_deg'):.3g} deg (slope level {L:.2f})"
    rows["Descent"] = f"{capped(float(env.get('G2E_SLOPE_MAX_DEG', '14')) * hard * L, 'downhill_deg'):.3g} deg (slope level {L:.2f})"
    L = lv.get("ledge", 0.0)
    led = capped(float(env.get("G2E_LEDGE_HEIGHT", "0") or 0) * L, "ledge_m") * 100
    rows["Step up / down"] = f"{led:.3g} cm (ledge level {L:.2f})" if on("G2E_LEDGE_PROB") else "not in its course"
    L = lv.get("terrain", 0.0)
    for nm, key in (("Rubble", "G2E_RUBBLE_PROB"), ("Box obstacles", "G2E_RANDOM_TERRAIN_PROB"), ("Rough floor", "G2E_ROUGH_TERRAIN_PROB"), ("Snag obstacles", "G2E_SNAG_OBSTACLE_PROB")):
        present = on(key) if key in env else nm in ("Rubble", "Box obstacles", "Rough floor")        # module defaults: rubble, boxes and rough floor on, snags off
        rows[nm] = f"{L:.2f} x level-1 size (terrain level {L:.2f})" if present else "not in its course"
    L = lv.get("fault", 0.0)
    rows["Overheat cutback"] = f"{L:.2f} x level-1 size (fault level {L:.2f})"
    return {"note": f"category levels at {steps:,} steps (the last curriculum probe), sizes through the run's own course and caps", "rows": rows}


def train_info(tag, levers, extra=None):
    """How a run trained, from its own log (user, 2026-10-08): mean episode reward over the run, the 1M-step eval, why it stopped, and (frontier runs) success by size."""
    import re
    log_path = f"trained/{tag}_console.log"
    lines = open(log_path, errors="replace").read().splitlines() if os.path.exists(log_path) else []
    reward, ts, rew = [], None, None
    for l in lines:
        m = re.search(r"\|\s+ep_rew_mean\s+\|\s+([-0-9.e+]+)", l)
        if m:
            rew = float(m.group(1))
        m = re.search(r"\|\s+total_timesteps\s+\|\s+([0-9]+)", l)
        if m:
            ts = int(m.group(1))
            if rew is not None:
                reward.append((ts / 1e6, rew))
    reward = reward[::max(1, len(reward) // 300)]
    ev = [(int(m.group(1)) / 1e6, float(m.group(2))) for l in lines for m in [re.search(r"^\[health\] steps (\d+)\s+eval ([0-9.]+)", l)] if m]
    stop = next((l for l in lines if l.startswith("[plateau]")), None)
    hstop = next((l for l in lines if "run STOPPED" in l), None)
    last = reward[-1][0] if reward else 0
    note = f"trained {last:.1f}M steps; " + ("stopped by the plateau rule: " + stop.split(":", 1)[1].strip() if stop else
                                            ("stopped by a health check: " + hstop if hstop else "ran its full length"))
    out = {"reward": reward, "eval": ev, "note": note}
    fr = f"trained/{tag}_frontier.json"
    if os.path.exists(fr):
        st = json.load(open(fr))
        a = st["anchor"] if st["anchor"] == st["anchor"] else 0.9
        units = {"sidehill": ("deg", 1), "climb": ("deg", 1), "descent": ("deg", 1), "ledge_up": ("cm", 100), "ledge_down": ("cm", 100)}
        out["frontier_bins"] = {h: ([(min(1.0, (v or 0) / max(a, 0.3)), n) for v, n in st["bins"][h]],
                                    st["bound"][h] * units.get(h, ("", 1))[1], units.get(h, ("x level-1 size", 1))[0]) for h in st["bins"]}
    return out


GIF_CELLS = [("T1.1", "Calm flat walk"), ("T5.2", "25 mm ledge (up or down)"), ("T3.2", "10 deg side-hill"), ("T6.1", "Rubble")]


def _render_worker(job):
    """One policy, one cell, one seed, in a fresh process with the policy's own scoring environment: frames every 4 control steps (20 fps = real time) and the outcome."""
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ.update(job["env"])
    import numpy as np
    import pybullet as p
    import opencat_gym_env as E
    import benchmark_decathlon as B
    import benchmark_v4 as V
    from benchmark_gaits import _load_learned
    E.GUI_MODE = False
    E.ADAPTIVE_PUSH = False
    row = {r[0]: r for r in V.cell_table(None)}[job["cell"]]
    env = E.OpenCatGymEnv()
    B._apply(dict(row[2]))
    E.EPISODE_LENGTH = row[4] or 250
    env.set_command(fwd=0.10, yaw=0.0)
    model = _load_learned(job["policy"])
    np.random.seed(job["seed"])
    obs, _ = env.reset()
    frames, x0, steps, fell = [], p.getBasePositionAndOrientation(env.robot_id)[0][0], 0, False
    while True:
        a, _ = model.predict(obs, deterministic=True)
        obs, _r, te, tr, _i = env.step(a)
        steps += 1
        pos, orn = p.getBasePositionAndOrientation(env.robot_id)
        if steps % 4 == 0:
            w, h, rgb, _, _ = p.getCameraImage(
                280, 200, viewMatrix=p.computeViewMatrixFromYawPitchRoll(cameraTargetPosition=[pos[0], pos[1], 0.03], distance=0.36, yaw=55, pitch=-28, roll=0, upAxisIndex=2),
                projectionMatrix=p.computeProjectionMatrixFOV(60, 280 / 200, 0.05, 5), renderer=p.ER_TINY_RENDERER)
            frames.append(np.reshape(np.asarray(rgb, dtype=np.uint8), (h, w, 4))[:, :, :3])
        if te or tr:
            rr, pp, _ = p.getEulerFromQuaternion(orn)
            fell = max(abs(rr), abs(pp)) > 1.3
            break
    return {"frames": frames, "fell": fell, "t": steps / 80.0, "dist": pos[0] - x0}


def render_pairs(policies, seed=4242):
    """Side-by-side GIFs (left = policies[0], right = policies[1]) for GIF_CELLS; returns [(label, data URI, outcome text)]."""
    import base64
    import io
    import multiprocessing as mp
    import numpy as np
    from PIL import Image
    jobs = []
    for cid, _ in GIF_CELLS:
        for path, lv in policies:
            env = {**g2_profile.scoring_env(*obs_levers(lv))}
            jobs.append(dict(cell=cid, policy=path, env={k: str(v) for k, v in env.items()}, seed=seed))
    with mp.get_context("spawn").Pool(min(8, len(jobs))) as pool:
        res = pool.map(_render_worker, jobs)
    out = []
    for i, (cid, label) in enumerate(GIF_CELLS):
        a, b = res[2 * i], res[2 * i + 1]
        n = max(len(a["frames"]), len(b["frames"]))
        pad = lambda fr: fr + [fr[-1]] * (n - len(fr))
        imgs = [Image.fromarray(np.concatenate([fa, np.full((fa.shape[0], 4, 3), 255, np.uint8), fb], axis=1)) for fa, fb in zip(pad(a["frames"]), pad(b["frames"]))]
        buf = io.BytesIO()
        imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:], duration=50, loop=0, optimize=True)
        uri = "data:image/gif;base64," + base64.b64encode(buf.getvalue()).decode()
        say = lambda r: (f"fell at {r['t']:.1f} s" if r["fell"] else f"walked {r['dist']:.2f} m in {r['t']:.1f} s")
        out.append((f"{cid} {label}", uri, f"V3 {say(a)}; V4 {say(b)}"))
    return out


def compare_v3_v4(tag="v4_20m", levers=None):
    """User, 2026-10-08: when the 20M is done, benchmark V3 against it (V4 once promoted) with every update the training runs got: the same scoring profile (native
    stack, per-frame IMU noise, honoured seeds, paired courses), the full cell list at 40 episodes, the difficulty ladder (version 2: forced hazards, forward walks), and
    each policy scored with the observation levers it was trained with. Both policies are scored now, in the same code, so nothing old is mixed in."""
    import benchmark_v4
    import v3_report
    if levers is None:
        levers = load(RESULTS, {}).get("base", [])
    outdir = f"trained/v4_report_{tag}"
    os.makedirs(outdir, exist_ok=True)
    out = {}
    for key, path, lv in (("v21", V3_POLICY, []), ("final", f"trained/{tag}_ppo", list(levers))):
        f = f"{outdir}/{key}.json"
        if not os.path.exists(f):
            saved = dict(os.environ)
            try:
                res = benchmark_v4.run(path, "all", EPISODES, 1000, V3.SCORE_JOBS, None, tuple(obs_levers(lv)), None, mirror_gap=True, quiet=True,
                                       ladder=True, ladder_levers=tuple(lv), ladder_episodes=benchmark_v4.LADDER_EPISODES)
            finally:
                os.environ.clear()
                os.environ.update(saved)
            save(f, res)
            log(f"V3 vs V4: scored {key} ({path}) | {V3.summary(res)}")
        out[key] = json.load(open(f))
    html = f"{outdir}/v3_vs_v4_report.html"
    # Reality-gap check (user, 2026-10-08): both policies scored again with the command-path delay G2's walks show (12.5 ms, the measured loop jitter; the sim
    # trains with 4 ms). Evaluation only: training never uses it. benchmark_v4.run's extra_env sets it; the benchmark code itself is unchanged.
    delay = {}
    for key, path, lv in (("v21", V3_POLICY, []), ("final", f"trained/{tag}_ppo", list(levers))):
        f = f"{outdir}/{key}_delay12p5ms.json"
        if not os.path.exists(f):
            # a FRESH process: benchmark_v4.run applies extra_env through the environment, which an env module already imported in this process would ignore
            import subprocess
            code = ("import sys, json; sys.path.insert(0, '.'); import benchmark_v4 as B; "
                    f"r = B.run({path!r}, {DELAY_CELLS!r}, {EPISODES}, 1000, {V3.SCORE_JOBS}, None, {tuple(obs_levers(lv))!r}, None, mirror_gap=False, quiet=True, "
                    "extra_env={'G2E_CMD_PATH_EXTRA_MS_MAX': '12.5'}); "
                    f"json.dump(r, open({f!r}, 'w'), indent=1)")
            subprocess.run([sys.executable, "-c", code], check=True)
            res = json.load(open(f))
            log(f"V3 vs V4: scored {key} with the 12.5 ms command delay | {V3.summary(res)}")
        delay[key] = json.load(open(f))
    r = load(RESULTS, {})
    reached = {"v21": difficulty_reached("v3_20m", ["mirror"]), "final": difficulty_reached(tag, levers, r.get("base_extra"))}
    train = {"v21": train_info("v3_20m", ["mirror"]), "final": train_info(tag, levers, r.get("base_extra"))}
    try:
        gifs = render_pairs([(V3_POLICY, []), (f"trained/{tag}_ppo", list(levers))])
    except Exception as ex:  # noqa: BLE001 -- the report without replays is still the report
        log(f"V3 vs V4: replays failed ({type(ex).__name__}: {ex}); the report has none")
        gifs = []
    open(html, "w").write(v3_report.build(out, {}, title="G2 Gait V3 vs V4", labels={"v21": "V3 (deployed)", "final": "V4 (the new 20M)"},
                                          reached=reached, train=train, gifs=gifs, delay=delay))
    log(f"V3 vs V4 REPORT ready: {html} (publish it as an Artifact page)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    {"run": run, "status": status, "final": final, "compare": compare_v3_v4}[cmd]()
