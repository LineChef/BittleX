"""Phase 1 of the sim training (2026-11-02): fit the simulator's physics to what G2 actually did, from the goal journal's attempt traces (and the pace book).
    python tools/sim_train/calibrate.py [JOURNAL] [OUT.json]
Each quantity is fitted as a value plus a spread (the training randomizes inside it), with the sample count, so thin data shows as wide spread. Nothing here touches hardware."""
import json, os, statistics as st, sys
J = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/Desktop/G2Memory/goals/goal_journal.jsonl")
OUT = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/g2_sim_train/calibration.json")

def stats(xs, lo=None, hi=None):
    xs = [x for x in xs if (lo is None or x >= lo) and (hi is None or x <= hi)]
    if len(xs) < 2: return {"n": len(xs), "mean": xs[0] if xs else None, "sd": None}
    q = sorted(xs)
    return {"n": len(xs), "mean": round(st.mean(xs), 3), "sd": round(st.pstdev(xs), 3), "p10": q[len(q) // 10], "p50": q[len(q) // 2], "p90": q[(len(q) * 9) // 10]}

rows = [json.loads(l) for l in open(J) if l.strip()]
atts = [r for r in rows if r.get("kind") == "attempt" and r.get("trace") and r.get("counted", True) is not None]
walk_obs, turn_obs, cycle_look_to_act, act_to_look, drops, first_seen, starts, punts, falls = [], [], [], [], [], [], [], [], 0
n_looks = n_none = n_nopic = n_dim = 0
for a in atts:
    tr = [e for e in a["trace"] if "t" in e]
    if any(e.get("kind") == "still" for e in tr) is False and a.get("time", "") > "2026-11-02 09:00" : pass
    prev_look = None; pend = None
    for i, e in enumerate(tr):
        k = e.get("kind")
        if k == "no_picture": n_nopic += 1
        if k == "dim_confirm": n_dim += 1
        if k == "look":
            n_looks += 1
            if e.get("ball") is None: n_none += 1
            if pend is not None and e.get("ball") and pend["ball"]:
                b0, b1 = pend["ball"], e["ball"]
                if pend["act"] in ("walk",) and abs(b0["bearing_deg"]) < 15 and pend["state"] == "ok" and not b1.get("edge") and not b0.get("edge"):
                    walk_obs.append((pend["seconds"], b0["distance_in"] - b1["distance_in"], b1["bearing_deg"] - b0["bearing_deg"]))
                if pend["act"] in ("turn", "align", "wall_turn", "search_turn") and pend["state"] == "ok":
                    turn_obs.append((pend["seconds"], pend["degrees"], b0["bearing_deg"] - b1["bearing_deg"], pend["act"]))
            if pend is not None: act_to_look.append(e["t"] - pend["t"])
            pend = None; prev_look = e
            if e.get("ball") and not first_seen: first_seen = [e["t"]]
        elif k == "act" and e.get("act") in ("walk", "turn", "align", "search_turn", "search_walk", "wall_turn", "back", "search_back", "three_point"):
            if prev_look is not None: cycle_look_to_act.append((e["t"] - prev_look["t"] - (e.get("seconds") or 0.0), e["act"]))
            pend = {"t": e["t"], "act": e["act"], "seconds": e.get("seconds") or 0.0, "degrees": e.get("degrees") or 0.0, "state": e.get("state"), "ball": prev_look.get("ball") if prev_look else None}
    ex = a.get("extra") or {}
    for p in ex.get("punt_log") or []:
        punts.append({"dist_in": p[0], "bearing": p[1], "outcome": (a.get("outcome") or {}).get("code")})
    if (a.get("outcome") or {}).get("code") == "fell": falls += 1
    tr0 = next((e for e in tr if e.get("kind") == "look" and e.get("ball")), None)
    if tr0: starts.append((tr0["ball"]["distance_in"], tr0["ball"]["bearing_deg"]))

# walk: distance = v * (s - dead)  (least squares through the origin shifted by a dead time)
import numpy as np
w = [(s, d) for s, d, _ in walk_obs if s >= 0.5 and -2 < d < 25]
v = dead = None
if len(w) >= 4:
    S = np.array([x[0] for x in w]); D = np.array([x[1] for x in w])
    A = np.vstack([S, np.ones_like(S)]).T; (v, c), *_ = np.linalg.lstsq(A, D, rcond=None); dead = float(-c / v) if v > 0 else 0.0
    resid = D - (v * S + c)
turn_pulse = [(t[2] / t[1]) for t in turn_obs if abs(t[1]) > 3 and t[3] in ("align",) and abs(t[2]) < 120]
turn_long = [(t[2] / t[1]) for t in turn_obs if abs(t[1]) > 15 and t[3] != "align" and abs(t[2]) < 150]
turn_rate = [(abs(t[2]) / max(t[0], .1)) for t in turn_obs if abs(t[1]) > 15 and t[3] != "align" and abs(t[2]) < 150]
cal = {
  "source": f"{len(atts)} attempts in {J}", "walk": {"in_per_s": round(float(v), 3) if v else None, "dead_s": round(dead, 2) if dead is not None else None, "resid_sd_in": round(float(np.std(resid)), 2) if v else None, "n": len(w),
         "heading_drift_deg_sd": stats([x[2] for x in walk_obs if x[0] > 1.0])},
  "turn": {"pulse_gain_actual_over_commanded": stats(turn_pulse), "long_gain": stats(turn_long), "deg_per_s_long": stats(turn_rate), "n_obs": len(turn_obs)},
  "timing": {"settle_camera_s_after_move": stats([x for x in act_to_look if 0.5 < x < 15]), "decide_overhead_s_before_move": stats([c for c, _ in cycle_look_to_act if -1 < c < 20])},
  "camera": {"looks": n_looks, "no_ball_frac": round(n_none / max(1, n_looks), 3), "no_picture_events": n_nopic, "dim_confirm_events": n_dim},
  "punt": {"n": len(punts), "samples": punts[:40]},
  "falls_per_attempt": round(falls / max(1, len(atts)), 3),
  "start_distance_in": stats([s[0] for s in starts]), "start_bearing_abs_deg": stats([abs(s[1]) for s in starts]),
}
os.makedirs(os.path.dirname(OUT), exist_ok=True); json.dump(cal, open(OUT, "w"), indent=1)
print(json.dumps(cal, indent=1)[:3800])
