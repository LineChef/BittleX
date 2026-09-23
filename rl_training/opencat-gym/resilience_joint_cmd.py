"""Joint-command path probe: `m` (sequential) vs `i` (simultaneous) on stock firmware.

run_gait.py sends one 8-joint target per 12.5 ms tick. Training applied each
target instantly. On the BiBoard (OpenCatEsp32, traced from source
2026-09-22) a command is *executed* over time, and the loop can't read the
next one until it finishes:

  m  (T_INDEXED_SEQUENTIAL_ASC, reaction.h): per joint, in the order sent,
     transform(target, 1, speed 1) -> one 1-degree step per 8 ms
     (delay((DOF-offset)/2), DOF 16), then delay(10); then a final
     transform at transformSpeed 2 (already there: one 8 ms iteration).
     Joints move one at a time.
  i  (T_INDEXED_SIMULTANEOUS_ASC): one transform(target, 1, transformSpeed=2)
     -> round(maxDiff/2)+1 iterations of 8 ms, all joints cosine-eased together.

Backlog (moduleManager.h read_serial()): when the firmware gets back to the
serial port it slurps every byte waiting, and the '\\n' strip truncates the
string at the first command -- the OLDEST waiting command runs, the rest are
dropped. So a slow command format shows up as latency + skipped targets.

Also modeled: 115200-baud transfer of the ASCII command, 1 ms read delay.
Not modeled: servo PWM dynamics beyond PyBullet's position control, other
firmware loop work (IMU reads, prints), the 5 Hz IMU print's own cost.

The policy is the deployed ONNX via pi_pipeline's ResidualGaitPolicy, fed
IMU the way stock firmware delivers it (5 Hz held orientation, no rate --
see resilience_imu_rate.py) in every variant, so the only difference
between variants is the joint-command path.

Variants: ideal (training), m, i (both sent every 80 Hz tick), and i@40 /
i@27 (policy still steps at 80 Hz, but only every 2nd / 3rd target is sent,
so the firmware isn't handed a backlog), and ifast = `i` with
transformSpeed 0 (jump straight to the target, one 8 ms iteration). Stock
firmware has no serial command for that -- transformSpeed is only changed by
camera.h / randomMind.h -- so ifast is what a one-line firmware change buys.
scripted = the policy's own wkF reference with a zero residual, applied
instantly: the firmware plays `kwkF` from its own memory, so the serial
command path doesn't apply to it (firmware gyro-balance not modeled).

    python resilience_joint_cmd.py
    python resilience_joint_cmd.py --cells T1.1,T5.1b --episodes 20 --json-out trained/joint_cmd.json
"""
import argparse
import json

import numpy as np

import resilience_imu_rate as R      # sets up sys.path / env flags; reuses ImuView
from resilience_imu_rate import E, p, ResidualGaitPolicy

DT = 1.0 / R.E_HZ
from firmware_model import FirmwareCmdPath, ITER_S, SEQ_JOINT_DELAY_S, READ_DELAY_S, BAUD_BYTES_PER_S, CMD_BYTES  # noqa: F401

VARIANTS = ("ideal", "m", "i", "i@40", "i@27", "ifast", "scripted")   # "<cmd>@<Hz>": send every 80/Hz-th tick only


def run_episode(env, pol, variant, seed, steps, cmd, on_step=None):
    np.random.seed(seed)
    E.JOINT_TARGET_HOOK = None
    env.reset()
    env.set_command(fwd=cmd, yaw=0.0)
    pol.set_command(fwd=cmd, yaw=0.0)
    d0 = env._deploy_dbg
    j0 = np.asarray(p.getJointStates(env.robot_id, env.joint_id), dtype=object)[:, 0].astype(float)
    view = R.ImuView("hold_zero", phase=int(np.random.randint(R.HOLD_STEPS)))
    q, w = view.read(0, d0["quat"], d0["angvel_raw"])
    pol.reset(j0, q, w)

    fw = None
    clock = {"t": 0.0, "k": 0}
    track = []
    if variant not in ("ideal", "scripted"):
        mode, _, hz = variant.partition("@")
        every = int(round(R.E_HZ / float(hz))) if hz else 1
        fw = FirmwareCmdPath(mode, np.rad2deg(j0))

        def hook(_env, joint_angs):
            t = clock["t"]
            want = np.rad2deg(joint_angs)
            if clock["k"] % every == 0:
                fw.send(t, want)
            clock["k"] += 1
            got = fw.output(t + DT / 2)                  # mid-step sample of the servo drive
            track.append(np.abs(got - want).mean())
            return np.deg2rad(got)
        E.JOINT_TARGET_HOOK = hook

    lo, hi = env.action_space.low, env.action_space.high
    x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
    tilt_max, fell, n = 0.0, False, 0
    for t in range(1, steps + 1):
        clock["t"] = (t - 1) * DT
        a = pol._sess.run(None, {pol._in_name: pol.obs[None, :]})[0][0]
        if variant == "scripted":
            a = np.zeros_like(a)                         # reference walk, no correction
        _, _, term, trunc, _ = env.step(np.clip(a, lo, hi))
        dbg = env._deploy_dbg
        q, w = view.read(t, dbg["quat"], dbg["angvel_raw"])
        pol.step(q, w)
        rp = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])
        tilt_max = max(tilt_max, abs(rp[0]), abs(rp[1]))
        n = t
        if on_step is not None:
            on_step(t, env)
        if term:
            fell = True
            break
        if trunc:
            break
    E.JOINT_TARGET_HOOK = None
    dx = p.getBasePositionAndOrientation(env.robot_id)[0][0] - x0
    out = dict(fell=fell, steps=n, dist=dx, speed=dx / (n * DT), tilt_max_deg=np.rad2deg(tilt_max))
    if fw is not None:
        out.update(executed_frac=len(fw.executed) / max(fw.sent, 1),
                   latency_ms=1e3 * float(np.mean(fw.executed)) if fw.executed else None,
                   track_err_deg=float(np.mean(track)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=R.os.path.join(R.HERE, "trained", "run20m_ppo.onnx"))
    ap.add_argument("--wkf", default=R.os.path.join(R.HERE, "reference_gait", "wkf_ref.npy"))
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--steps", type=int, default=E.EPISODE_LENGTH)
    ap.add_argument("--cmd", type=float, default=0.10)
    ap.add_argument("--cells", default="T1.1,T3.1,T3.2,T5.1b,T6.3b,T7.5,T8.2,T9.1")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    import benchmark_decathlon as B
    from opencat_gym_env import OpenCatGymEnv
    cells = {c[0]: c for c in B.LADDER}
    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = args.steps
    pol = ResidualGaitPolicy(onnx_path=args.onnx, wkf_path=args.wkf)

    results = {}
    print(f"{'cell':>6} {'cmd':>6} {'falls':>6} {'speed':>7} {'exec%':>6} {'lat ms':>7} {'err°':>6}")
    for cid in args.cells.split(","):
        B._apply({k: v for k, v in cells[cid][4].items() if not k.startswith("_")})
        env = OpenCatGymEnv()
        for variant in args.variants.split(","):
            eps = [run_episode(env, pol, variant, 9000 + s, args.steps, args.cmd)
                   for s in range(args.episodes)]
            r = dict(falls=sum(e["fell"] for e in eps), episodes=len(eps),
                     speed=float(np.mean([e["speed"] for e in eps])), episodes_detail=eps)
            if variant not in ("ideal", "scripted"):
                r.update(executed_frac=float(np.mean([e["executed_frac"] for e in eps])),
                         latency_ms=float(np.mean([e["latency_ms"] for e in eps])),
                         track_err_deg=float(np.mean([e["track_err_deg"] for e in eps])))
            results[f"{cid}/{variant}"] = r
            ex = f"{100 * r['executed_frac']:>5.0f}% {r['latency_ms']:>7.0f} {r['track_err_deg']:>6.1f}" \
                if variant not in ("ideal", "scripted") else f"{'-':>6} {'-':>7} {'-':>6}"
            print(f"{cid:>6} {variant:>6} {r['falls']:>3}/{len(eps):<2} {r['speed']:>7.3f} {ex}", flush=True)
        env.close()

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(results, f, indent=1, default=float)


if __name__ == "__main__":
    main()
