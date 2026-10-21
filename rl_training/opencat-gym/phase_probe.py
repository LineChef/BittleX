"""Short carpet probes (user, 2026-10-20: "short probes to test what helps before longer probes"). Each variant is a 0.5M-step run (about 3 min) chained from a start policy on ONE fixed
carpet that the start policy mostly fails, then scored on that carpet and on the fitted carpet (24 episodes, about 1.5 min).

    python phase_probe.py run NAME [NAME ...]      # variants below
    python phase_probe.py show                      # every result so far, best first
A variant is only a lead: what helps here is then tried at 2-3M steps with the adaptive carpet ground. Results: trained/probe_results.json; run logs trained/probe_<name>_console.log."""
import json
import os
import sys
import time

sys.path.insert(0, ".")
import carpet_fit as CF
import g2_profile
import phase_pod as PP
import run_pipeline as RP

START = os.environ.get("PROBE_START", "trained/carpet_g3_s43_ppo")
FIXED = {"G2E_CARPET_ADAPT": "0", "G2E_CARPET_PAD_K": "350", "G2E_CARPET_PAD_K_MAX": "0", "G2E_CARPET_PAD_C": "4", "G2E_CARPET_PAD_C_MAX": "0", "G2E_CARPET_PAD_DEPTH": "0.0088",
         "G2E_CARPET_PAD_DEPTH_MAX": "0", "G2E_CARPET_PAD_MU": "1.5", "G2E_CARPET_PAD_MU_MAX": "0", "G2E_CARPET_PAD_PROB": "1.0"}
PROBE_CARPET = dict(grid=(350.0,), damp=(4.0,), depth=0.0088, mu=1.5)
VARIANTS = {
    "base": {},
    "slip": {"G2E_FAC_SLIP": "0.5"},
    "clear": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3"},
    "loose": {"G2E_FAC_IMITATION": "6", "G2E_FAC_FOOT_PHASE": "0.5", "G2E_FAC_GAIT_SYMMETRY": "1.5"},
    "explore": {"G2E_RESET_LOG_STD": "-1.2"},
    "clear40": {"G2E_PAW_Z_TARGET": "0.040", "G2E_FAC_CLEARANCE": "0.5"},
    "clear_loose": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_FAC_IMITATION": "6", "G2E_FAC_FOOT_PHASE": "0.5", "G2E_FAC_GAIT_SYMMETRY": "1.5"},
    "clear_mu12": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.2"},
    "clear_mu12_long": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.2"},
    "soft": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_FAC_TOUCHDOWN": "25"},
    "soft_z": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_FAC_TOUCHDOWN": "25", "G2E_FAC_Z_VELOCITY": "20"},
    "soft_only": {"G2E_FAC_TOUCHDOWN": "25"},
    "stair15_long": {"_start": "trained/probe_clear_mu12_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.5"},
    "stair18_long": {"_start": "trained/probe_stair15_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.8", "G2E_CARPET_PAD_K": "250", "G2E_CARPET_PAD_DEPTH": "0.010"},
    "stair22_long": {"_start": "trained/probe_stair18_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "2.2", "G2E_CARPET_PAD_K": "120", "G2E_CARPET_PAD_C": "2", "G2E_CARPET_PAD_DEPTH": "0.012"},
    "stair18s43_long": {"_start": "trained/probe_stair15_long_ppo", "_seed": "43", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.8", "G2E_CARPET_PAD_K": "250", "G2E_CARPET_PAD_DEPTH": "0.010"},
    "mix_long": {"_start": "trained/probe_stair18_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.5", "G2E_CARPET_PAD_MU_MAX": "2.2",
                 "G2E_CARPET_PAD_K": "120", "G2E_CARPET_PAD_K_MAX": "350", "G2E_CARPET_PAD_C": "2", "G2E_CARPET_PAD_C_MAX": "4", "G2E_CARPET_PAD_DEPTH": "0.0088", "G2E_CARPET_PAD_DEPTH_MAX": "0.012"},
    "stair18more_long": {"_start": "trained/probe_stair18_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.8", "G2E_CARPET_PAD_K": "250", "G2E_CARPET_PAD_DEPTH": "0.010"},
    "fine20_long": {"_start": "trained/probe_mix_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "1.8", "G2E_CARPET_PAD_MU_MAX": "2.1",
                    "G2E_CARPET_PAD_K": "150", "G2E_CARPET_PAD_K_MAX": "250", "G2E_CARPET_PAD_C": "2", "G2E_CARPET_PAD_C_MAX": "3", "G2E_CARPET_PAD_DEPTH": "0.010", "G2E_CARPET_PAD_DEPTH_MAX": "0.012"},
    "fine22_long": {"_start": "trained/probe_fine20_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "2.0", "G2E_CARPET_PAD_MU_MAX": "2.4",
                    "G2E_CARPET_PAD_K": "100", "G2E_CARPET_PAD_K_MAX": "160", "G2E_CARPET_PAD_C": "1.8", "G2E_CARPET_PAD_C_MAX": "2.5", "G2E_CARPET_PAD_DEPTH": "0.011", "G2E_CARPET_PAD_DEPTH_MAX": "0.013"},
    "speed22_long": {"_start": "trained/probe_mix_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_SPEED_DROP": "0.5", "G2E_CARPET_TRACK_SCALE": "0.5",
                     "G2E_CARPET_PAD_MU": "2.0", "G2E_CARPET_PAD_MU_MAX": "2.4", "G2E_CARPET_PAD_K": "100", "G2E_CARPET_PAD_K_MAX": "160", "G2E_CARPET_PAD_C": "1.8", "G2E_CARPET_PAD_C_MAX": "2.5",
                     "G2E_CARPET_PAD_DEPTH": "0.011", "G2E_CARPET_PAD_DEPTH_MAX": "0.013"},
    "lowA_long": {"_start": "trained/probe_fine22_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "2.0", "G2E_CARPET_PAD_MU_MAX": "2.4", "G2E_CARPET_PAD_K": "100", "G2E_CARPET_PAD_K_MAX": "160", "G2E_CARPET_PAD_C": "1.8", "G2E_CARPET_PAD_C_MAX": "2.5", "G2E_CARPET_PAD_DEPTH": "0.011", "G2E_CARPET_PAD_DEPTH_MAX": "0.013", "G2E_HEIGHT_TARGET": "0.064"},
    "lowB_long": {"_start": "trained/probe_fine22_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "2.0", "G2E_CARPET_PAD_MU_MAX": "2.4", "G2E_CARPET_PAD_K": "100", "G2E_CARPET_PAD_K_MAX": "160", "G2E_CARPET_PAD_C": "1.8", "G2E_CARPET_PAD_C_MAX": "2.5", "G2E_CARPET_PAD_DEPTH": "0.011", "G2E_CARPET_PAD_DEPTH_MAX": "0.013", "G2E_HEIGHT_TARGET": "0.058"},
    "fine22b_long": {"_start": "trained/probe_fine22_long_ppo", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_MU": "2.0", "G2E_CARPET_PAD_MU_MAX": "2.4", "G2E_CARPET_PAD_K": "100", "G2E_CARPET_PAD_K_MAX": "160", "G2E_CARPET_PAD_C": "1.8", "G2E_CARPET_PAD_C_MAX": "2.5", "G2E_CARPET_PAD_DEPTH": "0.011", "G2E_CARPET_PAD_DEPTH_MAX": "0.013"},
    "adapt3m": {"_start": "trained/probe_fine22b_long_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5"},
    "adapt3mb": {"_start": "trained/probe_adapt3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5"},
    "adapt3mc": {"_start": "trained/probe_adapt3mb_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.55"},
    "adapt3m_s43": {"_start": "trained/probe_fine22b_long_ppo", "_seed": "43", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5"},
    "weak3m": {"_start": "trained/probe_adapt3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5",
               "G2E_MOTOR_FORCE_LO": "0.05", "G2E_MOTOR_FORCE": "0.12", "G2E_POD_RIGHT_MAX": "0.016"},
    "weak3mb": {"_start": "trained/probe_weak3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5",
                "G2E_MOTOR_FORCE_LO": "0.05", "G2E_MOTOR_FORCE": "0.12", "G2E_POD_RIGHT_MAX": "0.016"},
    "deep3m": {"_start": "trained/probe_adapt3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5", "G2E_CARPET_PAD_K": "30", "G2E_CARPET_PAD_DEPTH_MAX": "0.025", "G2E_MOTOR_FORCE_LO": "0.08", "G2E_MOTOR_FORCE": "0.12", "G2E_POD_RIGHT_MAX": "0.012"},
    "deep3mb": {"_start": "trained/probe_deep3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5", "G2E_CARPET_PAD_K": "30", "G2E_CARPET_PAD_DEPTH_MAX": "0.025", "G2E_MOTOR_FORCE_LO": "0.08", "G2E_MOTOR_FORCE": "0.12", "G2E_POD_RIGHT_MAX": "0.012"},
    "match3m": {"_start": "trained/probe_adapt3m_ppo", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3",
                "G2E_CARPET_PAD_K": "120", "G2E_CARPET_PAD_K_MAX": "0", "G2E_CARPET_PAD_C": "2", "G2E_CARPET_PAD_C_MAX": "0", "G2E_CARPET_PAD_DEPTH": "0.012", "G2E_CARPET_PAD_DEPTH_MAX": "0",
                "G2E_CARPET_PAD_MU": "2.2", "G2E_CARPET_PAD_MU_MAX": "0", "G2E_MOTOR_FORCE_LO": "0.06", "G2E_MOTOR_FORCE": "0.06", "G2E_POD_RIGHT_MAX": "0.016", "G2E_RESET_LOG_STD": "-1.2"},
    "recover3m": {"_start": "trained/probe_adapt3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.5",
                  "G2E_CARPET_BALANCE_SCALE": "2.0", "G2E_FAC_UPRIGHT": "6.0"},
    "stall4_3m": {"_start": "trained/probe_adapt3m_ppo", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_K": "120", "G2E_CARPET_PAD_K_MAX": "0", "G2E_CARPET_PAD_C": "2", "G2E_CARPET_PAD_C_MAX": "0", "G2E_CARPET_PAD_DEPTH": "0.012", "G2E_CARPET_PAD_DEPTH_MAX": "0", "G2E_CARPET_PAD_MU": "2.2", "G2E_CARPET_PAD_MU_MAX": "0", "G2E_MOTOR_FORCE_LO": "0.12", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_STALL": "0.4"},
    "stall7_3m": {"_start": "trained/probe_stall4_3m_ppo", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_PAD_K": "120", "G2E_CARPET_PAD_K_MAX": "0", "G2E_CARPET_PAD_C": "2", "G2E_CARPET_PAD_C_MAX": "0", "G2E_CARPET_PAD_DEPTH": "0.012", "G2E_CARPET_PAD_DEPTH_MAX": "0", "G2E_CARPET_PAD_MU": "2.2", "G2E_CARPET_PAD_MU_MAX": "0", "G2E_MOTOR_FORCE_LO": "0.12", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_STALL": "0.7"},
    "astall3m": {"_start": "trained/probe_adapt3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.3", "G2E_MOTOR_FORCE_LO": "0.12", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_STALL": "0.8"},
    "astall3mb": {"_start": "trained/probe_astall3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_MOTOR_FORCE_LO": "0.12", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_STALL": "0.8", "G2E_CARPET_LEVEL0": "0.5"},
    "astall5_3m": {"_start": "trained/probe_astall3mb_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_CARPET_LEVEL0": "0.3", "G2E_MOTOR_FORCE_LO": "0.12", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_STALL": "0.5"},
    "astall5_3mb": {"_start": "trained/probe_astall5_3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_MOTOR_FORCE_LO": "0.12", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_STALL": "0.5", "G2E_CARPET_LEVEL0": "0.5"},
    "ref3m": {"_start": "", "_adapt": "1", "_steps": "3e6", "G2E_SKILL_REF": "carpet", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_MOTOR_FORCE_LO": "0.10", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_FAC_Z_VELOCITY": "20", "G2E_FAC_TOUCHDOWN": "25", "G2E_FAC_UPRIGHT": "5.0", "G2E_CARPET_LEVEL0": "0.3"},
    "ref3mb": {"_start": "trained/probe_ref3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_SKILL_REF": "carpet", "G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3", "G2E_MOTOR_FORCE_LO": "0.10", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_FAC_Z_VELOCITY": "20", "G2E_FAC_TOUCHDOWN": "25", "G2E_FAC_UPRIGHT": "5.0", "G2E_CARPET_LEVEL0": "0.5"},
    "creep3m": {"_start": "", "_adapt": "1", "_steps": "3e6", "G2E_SKILL_REF": "creepfr", "G2E_PHASE_RATE_NOM_CMD": "0.035", "G2E_CMD_BANDS": "creep", "G2E_FAC_FOOT_PHASE": "0", "G2E_FAC_GAIT_SYMMETRY": "0", "G2E_CARPET_LEVEL0": "0.3", "G2E_MOTOR_FORCE_LO": "0.10", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008"},
    "creep3mb": {"_start": "trained/probe_creep3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_SKILL_REF": "creepfr", "G2E_PHASE_RATE_NOM_CMD": "0.035", "G2E_CMD_BANDS": "creep", "G2E_FAC_FOOT_PHASE": "0", "G2E_FAC_GAIT_SYMMETRY": "0", "G2E_MOTOR_FORCE_LO": "0.10", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_CARPET_LEVEL0": "0.5"},
    "creep_calm": {"_start": "trained/probe_creep3m_ppo", "_adapt": "1", "_steps": "3e6", "G2E_SKILL_REF": "creepfr", "G2E_PHASE_RATE_NOM_CMD": "0.035", "G2E_CMD_BANDS": "creep", "G2E_FAC_FOOT_PHASE": "0", "G2E_FAC_GAIT_SYMMETRY": "0", "G2E_CARPET_LEVEL0": "0.4", "G2E_MOTOR_FORCE_LO": "0.10", "G2E_MOTOR_FORCE": "0.15", "G2E_POD_RIGHT_MAX": "0.008", "G2E_FAC_Z_VELOCITY": "20", "G2E_FAC_TOUCHDOWN": "25", "G2E_FAC_UPRIGHT": "6.0"},
    "clear_long": {"G2E_PAW_Z_TARGET": "0.030", "G2E_FAC_CLEARANCE": "0.3"},
}
RES = "trained/probe_results.json"


def log(m):
    print(f"[probe {time.strftime('%I:%M %p')}] {m}", flush=True)


def run(name, steps="5e5"):
    if name.endswith("_long"):
        steps = "1.5e6"
    steps = VARIANTS[name].get("_steps", steps)
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    if name in res:
        return res[name]
    tag = f"probe_{name}"
    env = g2_profile.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(PP.BASE6) + ["carpet_body", "carpet_ground"]})
    env.pop("G2E_PLATEAU_STOP", None)
    if not VARIANTS[name].get("_adapt"):
        env.update(FIXED)                                  # the adaptive carpet ground (carpet_ground) keeps its own per-env difficulty
    env.update({k: v for k, v in VARIANTS[name].items() if not k.startswith("_")})
    start = VARIANTS[name].get("_start", START)
    env["G2E_SEED"] = env["G2E_CHAIN_SEED"] = VARIANTS[name].get("_seed", "42")
    env = {k: v for k, v in env.items() if v != ""}
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    log(f"{name}: {VARIANTS[name]} from {start}, {steps} steps")
    RP.launch(tag, env, steps=steps, base=False, chain_from=(start or None))
    ok, why = RP.wait_for_finish(tag)
    if not ok:
        log(f"{name} did not finish: {why}")
        return None
    out = {}
    fit_c = dict(grid=(120.0,), damp=(2.0,), depth=0.012, mu=2.2)
    for label, c, mf, dy in (("probe", PROBE_CARPET, 0.10, -0.008), ("fitted", fit_c, 0.10, -0.008), ("hard", dict(grid=(0.0,), damp=(0.0,)), 0.10, -0.008),
                             ("match", fit_c, 0.06, -0.016), ("deep", dict(grid=(30.0,), damp=(1.5,), depth=0.025, mu=2.4), 0.10, -0.008),
                             ("stall7", fit_c, 0.15, -0.008)):      # stall7: the stall model that reproduced the real falls (stall 0.7: 67% falls at 1.9 s)      # match: the body that reproduced the real carpet-policy falls (2026-10-20: 96% falls at 1.5 s)
        r = CF.run(f"trained/{tag}_ppo", ["privileged_critic", "heading_blind"], episodes=24, extra={"MOTOR_FORCE": mf}, payload_dy=dy, quiet=True, env_extra=({"G2E_CARPET_STALL": "0.7"} if label == "stall7" else None), **c)["rows"][0]
        out[label] = dict(falls=r["falls"], dist=r["dist_in_med"], t_fall=r["t_fall_med"], sink=r["sink_med_mm"])
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    res[name] = out
    json.dump(res, open(RES, "w"), indent=1)
    log(f"{name}: probe carpet falls {out['probe']['falls']:.2f} walks {out['probe']['dist']:.0f} in | fitted falls {out['fitted']['falls']:.2f} walks {out['fitted']['dist']:.0f} in | hard falls {out['hard']['falls']:.2f} | match-body falls {out['match']['falls']:.2f} walks {out['match']['dist']:.0f} in t_fall {out['match']['t_fall'] or 0:.1f} | deep-pad falls {out['deep']['falls']:.2f} walks {out['deep']['dist']:.0f} in | stall7 falls {out['stall7']['falls']:.2f} walks {out['stall7']['dist']:.0f} in t_fall {out['stall7']['t_fall'] or 0:.1f}")
    return out


def show():
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    for n, o in sorted(res.items(), key=lambda kv: (kv[1]["probe"]["falls"], -kv[1]["probe"]["dist"])):
        print(f"{n:10s} probe falls {o['probe']['falls']:.2f} walks {o['probe']['dist']:5.1f} in | fitted falls {o['fitted']['falls']:.2f} walks {o['fitted']['dist']:5.1f} in | hard falls {o['hard']['falls']:.2f}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        for n in sys.argv[2:]:
            run(n)
    else:
        show()
