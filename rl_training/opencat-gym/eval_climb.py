"""Evaluate a trained CLIMB policy: run N deterministic episodes, print
success / flip / height / pitch stats, and write a labelled side-view GIF of a
few episodes.

    python eval_climb.py trained/climb_smoke --episodes 20 --gif /tmp/climb.gif
"""
import argparse
import sys

import numpy as np
import pybullet as p

from climb_env import ClimbEnv, LEDGE_FRONT_X, STAND_Z

_SKY = np.array([120, 131, 148], np.uint8)


def _grab(env, w=440, h=300):
    (bx, _by, _bz), orn = p.getBasePositionAndOrientation(env._robot)
    ry = p.getEulerFromQuaternion(orn)[2]
    c, s = np.cos(ry), np.sin(ry)
    off = np.array([c * 0 - s * 0.62, s * 0 + c * 0.62, 0.13 + env._ledge_h])
    eye = np.array([bx, 0.0, 0.0]) + off
    tgt = [bx, 0.0, 0.05 + env._ledge_h]
    _, _, rgb, _, _ = p.getCameraImage(
        w, h,
        viewMatrix=p.computeViewMatrix(eye.tolist(), tgt, [0, 0, 1]),
        projectionMatrix=p.computeProjectionMatrixFOV(46, w / h, 0.1, 6),
        renderer=p.ER_TINY_RENDERER)
    im = np.reshape(rgb, (h, w, 4))[:, :, :3].astype(np.uint8)
    im[(im > 243).all(axis=2)] = _SKY
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--ledge-lo", type=float, default=0.04)
    ap.add_argument("--ledge-hi", type=float, default=0.04)
    ap.add_argument("--gif", default=None)
    ap.add_argument("--gif-episodes", type=int, default=3)
    a = ap.parse_args()

    from stable_baselines3 import PPO
    model = PPO.load(a.model, device="cpu")
    env = ClimbEnv(ledge_lo=a.ledge_lo, ledge_hi=a.ledge_hi)

    succ = flip = 0
    end_pitch, end_dz, end_top, ret = [], [], [], []
    frames, labels = [], []
    for e in range(a.episodes):
        obs, _ = env.reset()
        tot = 0.0
        grab_this = a.gif and e < a.gif_episodes
        while True:
            act, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(act)
            tot += r
            if grab_this and env._t % 2 == 0:
                frames.append(_grab(env))
                labels.append((e, info["pitch"], info["on_top"], info["success"]))
            if term or trunc:
                break
        tgt_z = env._ledge_h + STAND_Z
        end_pitch.append(np.degrees(info["pitch"]))
        end_dz.append(info["bz"] - tgt_z)
        end_top.append(info["on_top"])
        ret.append(tot)
        if info["success"]:
            succ += 1
        if abs(info["pitch"]) > 1.2:
            flip += 1
        print(f"  ep {e:2d}: return {tot:7.1f}  end pitch {np.degrees(info['pitch']):+4.0f}  "
              f"bz {info['bz']:.3f} (dz {info['bz']-tgt_z:+.3f})  on_top {info['on_top']}/4  "
              f"{'SUCCESS' if info['success'] else ('FLIP' if abs(info['pitch'])>1.2 else '')}")
    env.close()

    n = a.episodes
    print(f"\n=== {a.model}  ({n} eps, ledge {a.ledge_lo*100:.0f}"
          + (f"-{a.ledge_hi*100:.0f}" if a.ledge_hi != a.ledge_lo else "") + " cm) ===")
    print(f"success (on-top+stable 12 steps) : {succ}/{n}  ({succ/n:.0%})")
    print(f"flipped (|pitch|>69 deg)         : {flip}/{n}  ({flip/n:.0%})")
    print(f"end pitch  mean {np.mean(end_pitch):+.0f} deg   (|.| mean {np.mean(np.abs(end_pitch)):.0f})")
    print(f"end height dz vs target: mean {np.mean(end_dz):+.3f} m  (0 = on top at stand height)")
    print(f"feet on ledge at end   : mean {np.mean(end_top):.1f}/4")
    print(f"return mean {np.mean(ret):.1f}")

    if a.gif and frames:
        from PIL import Image, ImageDraw
        imgs = []
        for fr, (e, pit, top, sc) in zip(frames, labels):
            im = Image.fromarray(fr)
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, im.width, 16], fill=(20, 20, 24))
            d.text((5, 3), f"ep{e}  pitch {np.degrees(pit):+.0f}  feet {top}/4"
                           + ("  SUCCESS" if sc else ""), fill=(235, 235, 235))
            imgs.append(im)
        imgs[0].save(a.gif, save_all=True, append_images=imgs[1:], duration=60, loop=0, disposal=2)
        print(f"wrote {a.gif}  ({len(imgs)} frames)")


if __name__ == "__main__":
    sys.exit(main())
