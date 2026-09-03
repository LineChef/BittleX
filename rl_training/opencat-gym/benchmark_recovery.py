"""Stance-recovery probe -- the Phase 4 target metric, measured where the payload
does NOT mask it: payload OFF, DR on, walk command, escalating hard shoves.

For each (checkpoint), N seeds x M shove levels:
  - falls           : episodes that terminated (tipped past 1.3 rad)
  - big_spikes       : body-tilt spikes above 0.6 rad
  - recovered        : spikes that came back below 0.35 rad (didn't fall)
  - recover_rate     : recovered / big_spikes   <- the headline number
  - resettle_steps   : mean steps from spike to settled (lower = snappier catch)
  - net_x_mean       : mean end-of-episode forward x (kept walking through the hits?)

    python recovery_probe.py trained/run20m_ppo trained/p4c_ppo
"""
import sys, os, numpy as np, json
sys.path.insert(0, "/Users/markjohnson/Desktop/OneFolder/projects/bittleX/rl_training/opencat-gym")
os.chdir("/Users/markjohnson/Desktop/OneFolder/projects/bittleX/rl_training/opencat-gym")
import opencat_gym_env as E

E.GUI_MODE = False
E.DR_EVAL_FULL = True
E.PAYLOAD_PROB = 0.0          # bare robot -- the payload masks every wobble
E.ROUGH_TERRAIN = 0.30
E.RANDOM_TERRAIN = 0.020
E.TORQUE_CUTBACK = 0.0
E.LEDGE_PROB = 0.0

from opencat_gym_env import OpenCatGymEnv
import pybullet as p
from stable_baselines3 import PPO


def _recovery_times(tilt, spike=0.6, settled=0.35):
    out, i, n = [], 0, len(tilt)
    while i < n:
        if tilt[i] > spike:
            j = i
            while j < n and tilt[j] >= settled:
                j += 1
            if j < n:
                out.append(j - i)
            i = j
        else:
            i += 1
    return out


SHOVES = [0.20, 0.28, 0.36, 0.44]     # IMPULSE_PUSH magnitude -- calibrated so the
                                      # bare robot enters the 0.6 rad catch band
                                      # often but doesn't just fall every time
SEEDS = 16
STEPS = 300


def probe(ckpt):
    m = PPO.load(ckpt)
    env = OpenCatGymEnv()
    falls = big = rec = 0
    rt_all, netx = [], []
    for sh in SHOVES:
        E.IMPULSE_PUSH = sh
        E.IMPULSE_PUSH_PROB = 0.020
        for s in range(SEEDS):
            np.random.seed(4000 + s)
            obs, _ = env.reset()
            env.set_command(fwd=0.10, yaw=0.0)
            tilt = []
            fell = False
            for _ in range(STEPS):
                a, _ = m.predict(obs, deterministic=True)
                obs, r, term, trunc, info = env.step(a)
                q = p.getBasePositionAndOrientation(env.robot_id)[1]
                rp = p.getEulerFromQuaternion(q)
                tilt.append(max(abs(rp[0]), abs(rp[1])))
                if term:
                    fell = True
                    break
            x_end = p.getBasePositionAndOrientation(env.robot_id)[0][0]
            netx.append(x_end)
            falls += fell
            tilt = np.asarray(tilt)
            spikes = int(np.sum((tilt[:-1] <= 0.6) & (tilt[1:] > 0.6))) if tilt.size > 1 else 0
            rts = _recovery_times(tilt)
            big += spikes
            rec += len(rts)
            rt_all += rts
    env.close()
    n = len(SHOVES) * SEEDS
    return {
        "ckpt": ckpt,
        "episodes": n,
        "falls": falls,
        "fall_rate": falls / n,
        "big_spikes": big,
        "recovered": rec,
        "recover_rate": (rec / big) if big else None,
        "resettle_steps_mean": float(np.mean(rt_all)) if rt_all else None,
        "net_x_mean": float(np.mean(netx)),
        "net_x_min": float(np.min(netx)),
    }


if __name__ == "__main__":
    out = [probe(c) for c in sys.argv[1:]]
    print(f"\n{'ckpt':<26}{'falls':>7}{'fall%':>7}{'spikes':>8}{'recov':>7}"
          f"{'rec%':>7}{'resettle':>10}{'net_x':>8}{'net_x_min':>10}")
    for o in out:
        rr = f"{o['recover_rate']:.0%}" if o['recover_rate'] is not None else "--"
        rs = f"{o['resettle_steps_mean']:.1f}" if o['resettle_steps_mean'] is not None else "--"
        print(f"{o['ckpt']:<26}{o['falls']:>7}{o['fall_rate']:>7.0%}{o['big_spikes']:>8}"
              f"{o['recovered']:>7}{rr:>7}{rs:>10}{o['net_x_mean']:>8.3f}{o['net_x_min']:>10.3f}")
    json.dump(out, open(sys.argv[-1].replace("trained/", "").replace("/", "_") + "__recovery_probe.json", "w")
              if False else open("/private/tmp/claude-502/-Users-markjohnson-Desktop-OneFolder-projects-bittleX/"
                                 "d7c45dae-58d7-4bee-ac85-5462b49fdbd6/scratchpad/recovery_probe.json", "w"), indent=1)
