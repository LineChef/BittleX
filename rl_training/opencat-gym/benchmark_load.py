"""Load ladder benchmark (heavy-load plan, user 2026-10-19: docs/planned/heavy-load-training-plan.md): the benchmark_v4 cells that matter for carrying, scored at
several payloads, the extra mass in the block on G2's back (opencat_gym_env LOAD_FIXED_KG; today's payload is 227 g, 1 lb is 454 g, so the extra goes 0 to 227 g).

    python benchmark_load.py --policy trained/pod_s4_ppo --levers privileged_critic,heading_blind --json-out out.json [--episodes 40] [--jobs 8]

Every policy, the deployed one included, walks with the same load-scaled commands (LOAD_SPEED_DROP 0.4: 60% of the command at 1 lb; slower is fine under a heavy
load, user), and episode e uses seed seed0 + e, so all policies meet the same courses (paired). The summary is what the heavy-load runner decides on:
  heavy_falls    mean fall rate over the cells at the two heaviest loads
  heavy_sway     mean roll + pitch std (deg) of the calm walks (N1, T1.2) at the two heaviest loads
  heavy_score    heavy_falls + 0.02 x heavy_sway (lower is better)
  light_falls    mean fall rate over the cells at today's payload (the no-regression check)
  flat_falls     the worst fall rate on flat ground (T1.1, N1) at any load
  speed_ratio    calm-walk speed at 1 lb / the commanded (load-scaled) speed: it must still walk, not stand still"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

LOADS_KG = (0.0, 0.075, 0.150, 0.227)          # payload 227 / 302 / 377 / 454 g
CELLS = ("T1.1", "N1", "T1.2", "T2.1", "T2.2", "T3.1", "T3.2", "T5.1", "T6.1", "T7.1", "T8.1", "T10.2", "N4")
CALM = ("N1", "T1.2")
SPEED_DROP = os.environ.get("BENCH_SPEED_DROP", "0.4")            # the command at 1 lb is (1 - this) of the calm command; BENCH_SPEED_DROP lets a probe slow it further (stance probe, user 2026-10-21)
CMD_N1 = 0.10                                  # the calm walk's command (benchmark_v4 N cells walk at 0.10 m/s)


def run(policy, levers=(), episodes=40, jobs=8, loads=LOADS_KG, cells=CELLS, quiet=True):
    import benchmark_v4 as V
    out = {"policy": policy, "levers": list(levers), "episodes": episodes, "loads": {}}
    for kg in loads:
        res = V.run(policy, ",".join(cells), episodes, 1000, jobs, None, tuple(levers), None, mirror_gap=False, quiet=quiet,
                    extra_env={"G2E_LOAD_FIXED_KG": str(kg), "G2E_LOAD_SPEED_DROP": SPEED_DROP})
        out["loads"][f"{kg:.3f}"] = {c["id"]: {k: c.get(k) for k in ("fell_fraction", "roll_std_deg", "pitch_std_deg", "path_speed_mps", "speed_mps", "heading_abs_mean_deg",
                                                                         "servo_over_frac", "lr_asym_max_deg", "foot_clear_p90_mm")} for c in res["cells"]}
    out["summary"] = summarize(out)
    return out


def summarize(res):
    keys = sorted(res["loads"], key=float)
    heavy, light = keys[-2:], keys[0]
    L = res["loads"]
    mean = lambda xs: sum(xs) / max(1, len(xs))                                      # noqa: E731
    hf = mean([L[k][c]["fell_fraction"] for k in heavy for c in L[k]])
    sway = mean([(L[k][c]["roll_std_deg"] or 0) + (L[k][c]["pitch_std_deg"] or 0) for k in heavy for c in CALM if c in L[k]])
    top = keys[-1]
    drop = float(SPEED_DROP) * min(1.0, float(top) / 0.227)
    n1 = L[top].get("N1", {})
    return dict(heavy_falls=hf, heavy_sway=sway, heavy_score=hf + 0.02 * sway, light_falls=mean([L[light][c]["fell_fraction"] for c in L[light]]),
                flat_falls=max(L[k][c]["fell_fraction"] for k in keys for c in ("T1.1", "N1") if c in L[k]),
                speed_ratio=(n1.get("path_speed_mps") or 0.0) / (CMD_N1 * (1.0 - drop)),
                per_load={k: dict(falls=mean([L[k][c]["fell_fraction"] for c in L[k]]),
                                  sway=mean([(L[k][c]["roll_std_deg"] or 0) + (L[k][c]["pitch_std_deg"] or 0) for c in CALM if c in L[k]]),
                                  n1_speed=L[k].get("N1", {}).get("path_speed_mps"),
                                  paw_mm=mean([L[k][c].get("foot_clear_p90_mm") or 0 for c in ("T1.1", "N1") if c in L[k]])) for k in keys})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--levers", default="")
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--json-out", required=True)
    a = ap.parse_args()
    res = run(a.policy, [x for x in a.levers.split(",") if x], a.episodes, a.jobs)
    json.dump(res, open(a.json_out, "w"), indent=1)
    s = res["summary"]
    print(f"heavy score {s['heavy_score']:.3f} | heavy falls {s['heavy_falls']:.3f} sway {s['heavy_sway']:.1f} deg | light falls {s['light_falls']:.3f} | flat falls {s['flat_falls']:.2f} "
          f"| 1 lb speed ratio {s['speed_ratio']:.2f}")
    for k, v in s["per_load"].items():
        print(f"  +{float(k) * 1000:3.0f} g: falls {v['falls']:.3f} sway {v['sway']:.1f} N1 speed {v['n1_speed']:.3f} paw lift {v['paw_mm']:.1f} mm")


if __name__ == "__main__":
    main()
