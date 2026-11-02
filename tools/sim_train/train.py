"""Phases 2-4 of the sim training (2026-11-02), fully automatic and resumable:  python tools/sim_train/train.py RUN_DIR [--quick]
  validate  the simulator with G2's CURRENT real settings against the real journal (outcome mix, success rate): the gap is reported, never hidden
  search    for each of the 18 (search_order x when_vanished) combos, an evolution strategy over the 8 numeric settings, scored on a hard mix of situations (objective J = 0.6 x mean
            + 0.4 x the WORST situation family's mean, so no situation is traded away), common random numbers inside a generation, domain randomization inside every attempt
  final     the best candidates, the current real settings and the defaults re-scored on thousands of FRESH attempts, including three situation families training never saw
  report    recommended_punt_settings.json + report.html (+ results.json). Nothing is sent to G2: loading the values is a decision for the owner.
State is checkpointed after every generation (state.json); rerunning with the same RUN_DIR resumes. A DONE file marks the end."""
import json, math, os, random, sys, time, zlib, collections, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import world
from pi_pipeline.behavior import punt_settings as ps
from pi_pipeline.behavior import ball_chase as bc

RUN = os.path.expanduser(sys.argv[1]); QUICK = "--quick" in sys.argv
SEARCH = "--search" in sys.argv                               # the search-focused run (owner, 2026-11-02: the punch is dialed in; what is missing is the best way to FIND and RE-ACQUIRE the ball)
BASE_RUN = os.path.expanduser(sys.argv[sys.argv.index("--base") + 1]) if "--base" in sys.argv else None
os.makedirs(RUN, exist_ok=True)
NUM = {  # name: (lo, hi, int?)
    "walk_aim_in": (2.5, 7.0, False), "nudge_max_in": (4.5, 10.0, False), "nudges_before_punt": (0, 5, True), "nudge_step_s": (0.4, 1.6, False),
    "lost_looks": (1, 5, True), "scan_turn_deg": (20.0, 80.0, False), "search_step_deg": (10.0, 45.0, False), "punt_max_in": (3.0, 4.5, False)}
if SEARCH:        # only the settings that govern searching are tuned; the rest stay at the first run's recommendation (or the current real values)
    NUM = {k: NUM[k] for k in ("lost_looks", "scan_turn_deg", "search_step_deg")}
NAMES = list(NUM)
ORDERS, VANISH = ps.SPEC["search_order"][2], ps.SPEC["when_vanished"][2]
MIX = {"ahead": .15, "angled": .20, "side": .15, "behind": .20, "far": .10, "wall_ball": .20}      # a deliberately hard mix: more "behind" and "by a wall" than real life
REAL_LIKE = {"ahead": .45, "angled": .35, "far": .10, "side": .10}
if SEARCH:
    MIX = {"behind": .25, "side": .20, "lost": .20, "wall_ball": .10, "far": .15, "angled": .10}      # search-heavy: the ball is NOT where he is looking
    HOLDOUT = {"corner": .25, "decoy": .25, "dim": .25, "behind": .125, "lost": .125}                  # (dim, corner and decoy are never trained on here)
else:
    HOLDOUT = {"corner": .34, "dim": .33, "decoy": .33}
CURRENT = {"punt_max_in": 4.0, "nudge_max_in": 7.0, "nudges_before_punt": 3, "nudge_step_s": 0.9, "walk_aim_in": 4.0, "lost_looks": 3, "when_vanished": "punt", "search_order": "back_turn", "scan_turn_deg": 60.0, "search_step_deg": 20.0}
if SEARCH: VANISH = (CURRENT["when_vanished"],)                # the search run does not tune when_vanished (it belongs to the punch)
REAL_CURRENT = dict(CURRENT)                                  # what G2 runs now: the baseline everything is compared with, in both runs
S = dict(gens=3, pop=8, eps=40, final=300, workers=2) if QUICK else (dict(gens=40, pop=24, eps=600, final=8000, workers=7) if SEARCH else dict(gens=60, pop=48, eps=500, final=10000, workers=7))
if SEARCH and BASE_RUN and os.path.exists(os.path.join(BASE_RUN, "recommended_punt_settings.json")):
    CURRENT = {**CURRENT, **json.load(open(os.path.join(BASE_RUN, "recommended_punt_settings.json")))["recommended_settings"]}          # the approach settings the first run found stay
CAL = world.load_cal()


def decode(x, combo):
    s = dict(CURRENT) if SEARCH else {}
    s.update({"search_order": combo[0], "when_vanished": combo[1]})
    for v, n in zip(x, NAMES):
        lo, hi, isint = NUM[n]; val = lo + min(1.0, max(0.0, v)) * (hi - lo); s[n] = int(round(val)) if isint else round(val, 2)
    s["nudge_max_in"] = max(s["nudge_max_in"], round(s["punt_max_in"] + 0.5, 2))
    return s


def settings_full(s):
    base = ps.defaults(bc); base.update(s); return base


def pick_family(rng, mix):
    r, acc = rng.random(), 0.0
    for f, w in mix.items():
        acc += w
        if r <= acc: return f
    return list(mix)[-1]


def evaluate(args):
    """(settings, mix, n, seed0) -> per-family score lists. Runs in a worker process."""
    s, mix, n, seed0 = args
    full = settings_full(s); fam = collections.defaultdict(list); codes = collections.Counter(); secs = []; seen = []
    for i in range(n):
        f = pick_family(random.Random(seed0 * 7919 + i), mix)
        sc, code, t, _, stats = world.run_episode(full, f, seed0 * 100003 + i, CAL)
        fs = stats.get("first_seen")
        seen.append(fs)
        if SEARCH:                                           # 70% how fast the ball was first found (0 = never, 1 = at once), 30% the whole attempt: finding it is the point, using it still counts
            sc = 0.7 * (0.0 if fs is None else max(0.0, 1.0 - fs / 75.0)) + 0.3 * sc
        fam[f].append(sc); codes[code] += 1; secs.append(t)
    return dict(fam), dict(codes), secs, seen


def J(fam):
    allv = [x for v in fam.values() for x in v]
    means = [st.mean(v) for f, v in fam.items() if f in MIX and v]
    return 0.6 * st.mean(allv) + 0.4 * min(means), st.mean(allv), {f: round(st.mean(v), 3) for f, v in fam.items()}


def load_state():
    p = os.path.join(RUN, "state.json")
    return json.load(open(p)) if os.path.exists(p) else {"stage": "validate", "combos": {}, "log": []}


def save_state(state):
    tmp = os.path.join(RUN, "state.json.tmp"); json.dump(state, open(tmp, "w")); os.replace(tmp, os.path.join(RUN, "state.json"))


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True); open(os.path.join(RUN, "progress.log"), "a").write(line + "\n")


def real_summary():
    rows = [json.loads(l) for l in open(os.path.expanduser("~/Desktop/G2Memory/goals/goal_journal.jsonl")) if l.strip()]
    atts = [r for r in rows if r.get("kind") == "attempt" and r.get("outcome")]
    codes = collections.Counter(r["outcome"]["code"] for r in atts)
    hits = sum(1 for r in atts if r["outcome"]["code"] in ("hit", "hit_unseen")); n = len(atts)
    sc = [r["outcome"]["score"] for r in atts if r["outcome"].get("score") is not None]
    return {"n": n, "hit_rate": round(hits / max(1, n), 3), "mean_score": round(st.mean(sc), 3), "codes": dict(codes)}


def main():
    from multiprocessing import Pool
    state = load_state(); pool = Pool(S["workers"])
    log(f"run {RUN} stage={state['stage']} settings={S} quick={QUICK}")
    # ------------------------------------------------------------------ validate
    if state["stage"] == "validate":
        n = 300 if QUICK else 4000
        parts = pool.map(evaluate, [(REAL_CURRENT, REAL_LIKE, n // S["workers"], 5000 + k) for k in range(S["workers"])])
        codes = collections.Counter(); allv = []
        for f, c, s_, _sn in parts:
            codes.update(c); allv += [x for v in f.values() for x in v]
        tot = sum(codes.values()); simhit = (codes["hit"] + codes["hit_unseen"]) / tot
        real = real_summary()
        state["validation"] = {"sim_hit_rate": round(simhit, 3), "sim_mean_score": round(st.mean(allv), 3), "sim_codes": {k: round(v / tot, 3) for k, v in codes.most_common()}, "real": real,
                               "hit_rate_gap_pp": round(100 * (simhit - real["hit_rate"]), 1), "score_gap": round(st.mean(allv) - real["mean_score"], 3)}
        log("VALIDATION " + json.dumps(state["validation"])); state["stage"] = "search"; save_state(state)
    # ------------------------------------------------------------------ search
    if state["stage"] == "search":
        combos = [(o, v) for o in ORDERS for v in VANISH]
        for ci, combo in enumerate(combos):
            key = "|".join(combo); c = state["combos"].setdefault(key, {"gen": 0, "mean": [0.5] * len(NAMES), "sigma": [0.3] * len(NAMES), "best": None})
            while c["gen"] < S["gens"]:
                g = c["gen"]; rng = np.random.default_rng(zlib.crc32(f"{key}|{g}".encode()))                  # (not hash(): that differs per process, so a resume would not repeat)
                mean, sig = np.array(c["mean"]), np.array(c["sigma"])
                xs = [np.clip(mean + sig * rng.standard_normal(len(NAMES)), 0, 1) for _ in range(S["pop"])]
                if g == 0: xs[0] = np.array([(CURRENT.get(n, (NUM[n][0] + NUM[n][1]) / 2) - NUM[n][0]) / (NUM[n][1] - NUM[n][0]) for n in NAMES]).clip(0, 1)      # the current real values are a candidate
                seed0 = 10_000 + ci * 1000 + g                                       # the same attempts for every candidate of this generation
                res = pool.map(evaluate, [(decode(x, combo), MIX, S["eps"], seed0) for x in xs])
                scored = sorted(((J(r[0])[0], J(r[0])[1], x, r) for x, r in zip(xs, res)), key=lambda t: -t[0])
                mu = max(2, S["pop"] // 4); elite = np.array([t[2] for t in scored[:mu]])
                c["mean"] = elite.mean(axis=0).tolist(); c["sigma"] = np.maximum(0.04, 0.5 * sig + 0.5 * elite.std(axis=0)).tolist()
                if c["best"] is None or scored[0][0] > c["best"]["J"]: c["best"] = {"J": scored[0][0], "mean_score": scored[0][1], "x": scored[0][2].tolist(), "gen": g}
                c["gen"] += 1; save_state(state)
                log(f"combo {ci + 1}/{len(combos)} {key} gen {c['gen']}/{S['gens']} bestJ {c['best']['J']:.3f} (gen top {scored[0][0]:.3f}, mean-score {scored[0][1]:.3f})")
        state["stage"] = "final"; save_state(state)
    # ------------------------------------------------------------------ final
    if state["stage"] == "final":
        ranked = sorted(((k, c["best"]) for k, c in state["combos"].items()), key=lambda kv: -kv[1]["J"])
        cands = {f"sim#{i + 1} {k} (search average)": decode(np.array(state["combos"][k]["mean"]), tuple(k.split("|"))) for i, (k, b) in enumerate(ranked[:6])}      # the converged mean: less luck in it
        cands.update({f"sim-best#{i + 1} {k} (best sample)": decode(np.array(b["x"]), tuple(k.split("|"))) for i, (k, b) in enumerate(ranked[:3])})      # the single best-scoring sample (partly luck)
        cands["CURRENT (real hardware)"] = dict(REAL_CURRENT)
        if SEARCH: cands["FIRST RUN's approach values only (current search values)"] = {**CURRENT, **{k: REAL_CURRENT[k] for k in NUM}}
        cands["DEFAULTS (source)"] = {k: v for k, v in ps.defaults(bc).items() if k in list(NUM) + ["search_order", "when_vanished"] + (list(CURRENT) if SEARCH else [])}
        out = {}
        for name, s in cands.items():
            row = {"settings": s}
            for label, mix, seed0 in (("train_mix", MIX, 900_000), ("holdout", HOLDOUT, 910_000), ("real_like", REAL_LIKE, 920_000)):
                parts = pool.map(evaluate, [(s, mix, S["final"] // S["workers"], seed0 + k) for k in range(S["workers"])])
                fam = collections.defaultdict(list); codes = collections.Counter(); secs = []; seen = []
                for f, c, s_, sn in parts:
                    for k, v in f.items(): fam[k] += v
                    codes.update(c); secs += s_; seen += sn
                allv = [x for v in fam.values() for x in v]; q = sorted(allv)
                row[label] = {"mean": round(st.mean(allv), 3), "worst_quartile": round(st.mean(q[: max(1, len(q) // 4)]), 3), "families": {f: round(st.mean(v), 3) for f, v in fam.items()},
                              "hit_rate": round((codes["hit"] + codes["hit_unseen"]) / sum(codes.values()), 3), "median_s": round(st.median(secs), 1), "codes": dict(codes.most_common(6)),
                              "found_rate": round(sum(1 for x in seen if x is not None) / len(seen), 3), "found_within_30s": round(sum(1 for x in seen if x is not None and x <= 30) / len(seen), 3),
                              "median_find_s": round(st.median([x for x in seen if x is not None] or [0]), 1)}
            out[name] = row; log(f"final {name}: train {row['train_mix']['mean']} holdout {row['holdout']['mean']} real-like {row['real_like']['mean']}")
        state["final"] = out; state["stage"] = "report"; save_state(state)
    # ------------------------------------------------------------------ report
    if state["stage"] == "report":
        fin = state["final"]; base = fin["CURRENT (real hardware)"]
        def robust(r): return 0.4 * r["train_mix"]["mean"] + 0.2 * r["train_mix"]["worst_quartile"] + 0.25 * r["holdout"]["mean"] + 0.15 * r["real_like"]["mean"]
        sims = {k: v for k, v in fin.items() if k.startswith("sim")}
        win = max(sims, key=lambda k: robust(sims[k])); w = sims[win]
        better = robust(w) > robust(base) + 0.01          # a simulated winner that does not clearly beat what G2 runs now is NOT recommended: the real settings stay
        rec = dict(w["settings"]) if better else dict(REAL_CURRENT); rec_all = {**{k: v for k, v in settings_full(rec).items() if k in ps.SPEC}, **world.PINNED}
        json.dump({"recommended_settings": rec, "pinned_unchanged": world.PINNED, "winner": win if better else "none: the current real settings stay (no clear gain in simulation)", "best_sim_candidate": win, "robust_score": round(robust(w), 4), "current_robust_score": round(robust(base), 4)}, open(os.path.join(RUN, "recommended_punt_settings.json"), "w"), indent=1)
        json.dump(state, open(os.path.join(RUN, "results.json"), "w"), indent=1)
        rows = "".join(f"<tr><td>{k}</td><td>{v['train_mix']['mean']}</td><td>{v['train_mix']['worst_quartile']}</td><td>{v['holdout']['mean']}</td><td>{v['real_like']['mean']}</td><td>{v['real_like']['hit_rate']}</td><td>{v['real_like']['median_s']}</td><td><code>{json.dumps(v['settings'])}</code></td></tr>" for k, v in fin.items())
        fams = "".join(f"<tr><td>{f}</td><td>{base['train_mix']['families'].get(f, '')}</td><td>{w['train_mix']['families'].get(f, '')}</td></tr>" for f in list(MIX))
        fams += "".join(f"<tr><td>{f} (held out)</td><td>{base['holdout']['families'].get(f, '')}</td><td>{w['holdout']['families'].get(f, '')}</td></tr>" for f in ("corner", "dim", "decoy"))
        html = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Sim training report</title><style>body{{font:15px system-ui;margin:16px;max-width:1000px}}table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}td,th{{border:1px solid #8884;padding:4px 6px;text-align:left}}code{{font-size:11px}}</style>
<h1>Sim training report</h1><p>Best simulated candidate: <b>{win}</b> (robust score {robust(w):.3f} vs current real settings {robust(base):.3f}); {"RECOMMENDED: it clearly beats the current settings." if better else "NOT recommended: no clear gain over the current real settings."} Scores are the goal's own scorer (0 to 1).</p>
<h2>Recommended starting values</h2><pre>{json.dumps(rec, indent=1)}</pre><p>Pinned (unchanged): {json.dumps(world.PINNED)}</p>
<h2>Simulator vs the real journal (current settings)</h2><pre>{json.dumps(state['validation'], indent=1)}</pre>
<h2>Candidates (fresh attempts)</h2><table><tr><th>candidate</th><th>train mean</th><th>worst quartile</th><th>held-out mean</th><th>real-like mean</th><th>real-like hit rate</th><th>median s</th><th>settings</th></tr>{rows}</table>
<h2>By situation: current vs winner</h2><table><tr><th>family</th><th>current</th><th>winner</th></tr>{fams}</table>
<p>Limits: walls are bumps, the punch is a fitted 40% hit chance from 13 real punts, turn data is thin. These are starting values for hardware to adjust, not final ones.</p>"""
        open(os.path.join(RUN, "report.html"), "w").write(html)
        log(f"REPORT written: winner {win} robust {robust(w):.3f} vs current {robust(base):.3f}"); state["stage"] = "done"; save_state(state)
    open(os.path.join(RUN, "DONE"), "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))
    pool.close()


if __name__ == "__main__":
    main()
