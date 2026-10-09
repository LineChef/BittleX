"""Watch REAL training episodes (not a recreation): the episodes `episode_recorder.RecordingWrapper` saved while a run trained.

    python watch_training.py <tag>                 # newest recorded episode of trained/<tag>_episodes, then the next ones as they arrive (Ctrl-C to stop)
    python watch_training.py <tag> --all           # every recorded episode, oldest first
    python watch_training.py <tag> --episode PATH  # one file
    python watch_training.py <tag> --headless      # no window: just check that the replay reproduces the recording (a matching final reward and length)

Each episode is rebuilt from what was saved at its start (the env settings, the ramp step count, the difficulty levels, the random generator state), so the terrain, obstacles,
slope, shoves and commands are the ones training met, and the policy's own recorded actions are fed to the robot. The last line of each episode says whether the replay matched
the recording; a mismatch means something outside the recording influenced the original (it is reported, never hidden). Runs started before the recorder existed have no episodes.
"""
import argparse
import glob
import os
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--all", action="store_true")
ap.add_argument("--episode", default=None)
ap.add_argument("--headless", action="store_true")
ap.add_argument("--speed", type=float, default=1.0, help="1.0 = real time (the sim's own pacing)")
args = ap.parse_args()

directory = args.tag if os.path.isdir(args.tag) else os.path.join("trained", f"{args.tag}_episodes")
files = [args.episode] if args.episode else sorted(glob.glob(os.path.join(directory, "ep_*.npz")), key=os.path.getmtime)
if not files:
    sys.exit(f"no recorded episodes in {directory} (the run must have started with G2E_RECORD_EVERY set; see g2_profile RECIPE)")

from episode_recorder import load_episode  # noqa: E402

first = load_episode(files[0])
os.environ.update(first["meta"]["env"])                  # the training run's settings, before the env module reads them
import numpy as np  # noqa: E402

import opencat_gym_env as E  # noqa: E402

E.GUI_MODE = not args.headless


def replay(path: str) -> bool:
    ep = load_episode(path)
    m = ep["meta"]
    env = E.OpenCatGymEnv()
    u = env
    if m.get("ramp_steps") is not None:
        u.set_ramp_steps(m["ramp_steps"])
    if m.get("levels"):
        u.set_category_levels(m["levels"])
    u._len_ep = int(m.get("len_ep", 0))
    u._forced_cmd = m.get("forced_cmd")
    if m.get("push_curr") is not None:                   # recordings made after 2026-10-08: the env's shove multiplier and the caps in force at the time
        u._push_curr = float(m["push_curr"])
    if m.get("caps"):
        E.apply_caps(m["caps"])
    if m.get("slope_deck") is not None:                 # V5 runs: the slope cards left in this env's deck when the episode started
        u._slope_deck = list(m["slope_deck"])
    fr = m.get("frontier")
    if fr and fr.get("w"):                               # FRONTIER runs: the bin weights in force when the episode started
        u.set_frontier(fr)
    np.random.set_state(ep["rng"])
    env.reset()
    focus = m.get("focus")
    print(f"\n{os.path.basename(path)}  recorded {m['recorded_at']}  focus: {focus or 'combo/easy'}  levels {m['levels']}  difficulty this episode {m['d']}"
          f"  slope {[round(float(np.degrees(x)), 1) for x in m['slope_rp']]} deg{' (targeted)' if m['slope_targeted'] else ''}", flush=True)
    total, steps, out = 0.0, 0, None
    ramp_events = {int(i): v for i, v in m.get("ramp_events", [])}      # mid-episode ramp updates (recordings made after 2026-10-08)
    for i, a in enumerate(ep["actions"]):
        if i in ramp_events:
            u.set_ramp_steps(ramp_events[i])
        out = env.step(a)
        total += float(out[1])
        steps += 1
        if out[2] or out[3]:
            break
        if not args.headless and args.speed > 0:
            time.sleep(max(0.0, 1.0 / 25.0 / args.speed - 0.001))
    ok = (steps == m["steps"]) and (bool(out[2]) == m["terminated"]) and abs(float(out[1]) - m["final_reward"]) < 1e-4 * max(1.0, abs(m["final_reward"]))
    print(f"  {steps} steps, ended {'by falling/stopping' if out[2] else 'by the step budget' if out[3] else 'early'}; "
          f"{'REPLAY MATCHES the recording' if ok else 'replay DIFFERS from the recording (recorded %d steps, final reward %.4f; replayed %d steps, %.4f)' % (m['steps'], m['final_reward'], steps, float(out[1]))}", flush=True)
    env.close()
    return ok


seen = set()
try:
    while True:
        todo = [f for f in (files if args.all or args.episode or args.headless else files[-1:]) if f not in seen]
        for f in todo:
            seen.add(f)
            replay(f)
        if args.all or args.episode or args.headless:
            break
        time.sleep(5)
        files = sorted(glob.glob(os.path.join(directory, "ep_*.npz")), key=os.path.getmtime)
except KeyboardInterrupt:
    pass
