"""Side-by-side replay GIFs of G2 under different joint-command paths.

Same seed, same course, fixed camera, four panels: learned gait with instant
commands (training), with `m`, with `i` (both through the firmware timing
model in resilience_joint_cmd.py, stock 5 Hz IMU), and the pure scripted walk.

    python replay_control_path.py --cell T1.1 --out trained/replay_T1.1.gif
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw

import resilience_joint_cmd as J
from resilience_joint_cmd import E, p, ResidualGaitPolicy, R

PANELS = [("ideal", "Learned — instant (training)"), ("m", "Learned — m (current before today)"),
          ("i", "Learned — i (switched today)"), ("scripted", "Scripted walk (pure wkF)")]
W, H = 400, 250


def capture(env, x0):
    _, _, rgb, _, _ = p.getCameraImage(
        W, H,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[x0 + 0.20, 0.0, 0.03], distance=0.62,
            yaw=0, pitch=-22, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(55, W / H, 0.05, 5),
        renderer=p.ER_TINY_RENDERER)
    return np.reshape(rgb, (H, W, 4))[:, :, :3].astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="T1.1")
    ap.add_argument("--seed", type=int, default=9000)
    ap.add_argument("--steps", type=int, default=320)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import benchmark_decathlon as B
    from opencat_gym_env import OpenCatGymEnv
    cell = {c[0]: c for c in B.LADDER}[args.cell]
    B._apply({k: v for k, v in cell[4].items() if not k.startswith("_")})
    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = args.steps
    pol = ResidualGaitPolicy(onnx_path=R.os.path.join(R.HERE, "trained", "run20m_ppo.onnx"),
                             wkf_path=R.os.path.join(R.HERE, "reference_gait", "wkf_ref.npy"))
    env = OpenCatGymEnv()

    tracks, results = [], []
    for variant, _ in PANELS:
        frames = []
        x0 = [None]

        def on_step(t, env_, frames=frames, x0=x0):
            if x0[0] is None:
                x0[0] = p.getBasePositionAndOrientation(env_.robot_id)[0][0]
            if t % args.stride == 0:
                frames.append(capture(env_, x0[0]))
        r = J.run_episode(env, pol, variant, args.seed, args.steps, 0.10, on_step=on_step)
        tracks.append(frames)
        results.append(r)
    env.close()

    n = max(len(f) for f in tracks)
    out = []
    for k in range(n):
        canvas = Image.new("RGB", (2 * W, 2 * H), (20, 24, 23))
        for i, ((variant, label), frames, r) in enumerate(zip(PANELS, tracks, results)):
            img = Image.fromarray(frames[min(k, len(frames) - 1)])
            d = ImageDraw.Draw(img)
            d.rectangle([0, 0, W, 22], fill=(20, 24, 23))
            d.text((8, 5), label, fill=(235, 240, 238))
            status = "FELL" if (r["fell"] and k >= len(frames) - 1) else f"{r['dist']:+.2f} m total"
            d.text((W - 110, 5), status, fill=(240, 150, 130) if r["fell"] else (150, 220, 180))
            canvas.paste(img, ((i % 2) * W, (i // 2) * H))
        out.append(canvas)
    out[0].save(args.out, save_all=True, append_images=out[1:],
                duration=int(1000 * args.stride / 80), loop=0, optimize=True)
    print(args.out, len(out), "frames", [(v, round(r["dist"], 3), r["fell"]) for (v, _), r in zip(PANELS, results)])


if __name__ == "__main__":
    main()
