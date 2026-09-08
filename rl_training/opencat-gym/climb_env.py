"""ClimbEnv -- standalone Gym env for the Phase F learned CLIMB / traverse skill.

Narrow task: from a walk-like pose ~4 cm in front of a ledge, get the body UP
ONTO the ledge and stand there, upright. Standalone PyBullet (not a subclass of
OpenCatGymEnv -- that class is welded to the walk task). Reuses the URDF, the
neutral stance, and the ledge + scoring idea from `climb_test.py`.

  obs (33): quat(4) + gyro*0.1(3) + proj-gravity(3) + joint/bound(8)
            + last-action(8) + fwd height-profile(6, GROUND TRUTH) + progress(1)
  action (8): residual on the neutral stance, +/- RES_DEG, position-controlled
  reward/step: forward progress + height gained + be-at-target-height, minus a
            heavy nose-over penalty + roll + action jerk; big terminal bonus for
            on-top-and-stable, big penalty for flipping.

Smoke test = fixed ~4 cm ledge, ~300-500 k PPO steps, one question: does it learn
to get up at all without faceplanting.  `--ledge-lo/-hi` widen the randomisation
once it does.
"""
from __future__ import annotations

import os
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_URDF = os.path.join(_HERE, "models", "bittle_esp32.urdf")   # absolute -> cwd-independent

try:
    import gymnasium as gym
    from gymnasium import spaces
except Exception:                                    # SB3 may still be on classic gym
    import gym
    from gym import spaces

import pybullet as p
import pybullet_data

WKF_REF = np.load(os.path.join(_HERE, "reference_gait", "wkf_ref.npy"))
STANCE = WKF_REF.mean(axis=0)                         # (8,) rad, neutral four-foot pose
REV = [1, 2, 4, 5, 7, 8, 10, 11]                     # revolute joints, URDF keyframe order
PAW = [3, 6, 9, 12]                                  # FL FR BR BL paw links
FRONT_PAW = [3, 6]
REAR_PAW = [9, 12]
BOUND = np.deg2rad(110.0)
RES_DEG = 24.0                                        # RESIDUAL scale on top of the scripted base
                                                     # (small -- the base does most of it, policy nudges)

# --- scripted base: the working part of climb_test.py -- front feet tuck up ->
# reach forward -> plant on the ledge, body pulls forward staying LEVEL. The
# policy learns a residual on top; its job is the hard part the script can't do
# (bring the rear legs up without tipping -- needs IMU feedback). Deltas in DEG
# from STANCE, URDF order [FLsh FLkn FRsh FRkn  BRhip BRkn BLhip BLkn].
_BASE_POSES = np.array([
    [0,   0,   0,   0,   0,   0,   0,   0],   # stance
    [38, -32,  38, -32,   0,   0,   0,   0],  # front tuck UP
    [-12, 34, -12,  34,   0,   0,   0,   0],  # front reach fwd + plant on the top
    [16,  28,  16,  28,   4,   6,   4,   6],  # body pull, front planted
    [16,  28,  16,  28,  24, -18,  24, -18],  # REAR tuck up (front holds on the ledge)
    [10,  20,  10,  20,  -8,  22,  -8,  22],  # REAR reach fwd + plant on the ledge, settle
], dtype=float)
_BASE_SEGS = [14, 20, 24, 18, 24]                     # env-steps per leg of the base motion


def _build_base():
    out = []
    for a, b, n in zip(_BASE_POSES[:-1], _BASE_POSES[1:], _BASE_SEGS):
        for t in range(n):
            w = 0.5 - 0.5 * np.cos(np.pi * (t + 1) / n)
            out.append(a * (1 - w) + b * w)
    return np.deg2rad(np.rad2deg(STANCE) + np.array(out))   # (58, 8) rad


_BASE = _build_base()


def _base_pose(t):
    return _BASE[min(int(t), len(_BASE) - 1)]


CTRL_HZ = 60.0
FRAME_SKIP = 4                                        # 240 Hz sim / 4 = 60 Hz control
MAX_STEPS = 200                                       # ~3.3 s
STAND_Z = 0.065                                       # body height above its support

LEDGE_FRONT_X = 0.085                                 # ledge near face, just ahead of the front paws
LEDGE_LEN = 0.40
PROFILE_X = np.linspace(0.03, 0.18, 6)                # fwd sample offsets for the height profile

# reward weights (module-level so runs can tune them). Run 2: pull the policy out
# of the "stand still, stay level" local optimum found in run 1.
GOAL_DX = 0.10                      # goal point: this far past the ledge face, at stand height
SHAPE_SCALE = 42.0                 # potential-based shaping toward that goal (the main driver)
PHI_W_X, PHI_W_Z = 2.5, 6.0        # potential: horizontal vs vertical distance-to-goal weights
W_PROG = 6.0                       # small raw forward-progress term on top of the shaping
W_ROLL = 10.0                      # roll is never wanted
PEN_PITCH_HARD = 30.0             # penalty ONLY for pitch past PITCH_FREE (approaching a flip)
PITCH_FREE = 0.80                  # rad (~46 deg): lean up to here is free -- a climb needs it
W_JERK, W_ALIVE = 0.3, 0.1
W_FRONT_ON = 4.0                   # per front paw on the ledge -- but worth only 0.4x while the
                                  # rear is still down (stops "park with the front up" being cosy)
W_REAR_ON = 11.0                  # per REAR paw on the ledge -- the actual completion, paid big
W_REAR_SHAPE = 34.0              # POTENTIAL-based on rear-paw height toward the ledge (telescopes
                                # over the episode -> per-step up/down bouncing cancels, can't farm)
STALL_PEN, STALL_WIN, STALL_EPS = 2.0, 25, 0.008   # no >8mm gain over 25 steps past step 25 -> stalled
STALL_KILL = 50                    # stalled this many steps -> end the episode (-20)
BONUS_TOP, PEN_FLIP = 250.0, 100.0
FLIP_RAD = 1.2


class ClimbEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(self, render_mode=None, ledge_lo=0.04, ledge_hi=0.04, seed=None):
        super().__init__()
        self.render_mode = render_mode
        self.ledge_lo, self.ledge_hi = float(ledge_lo), float(ledge_hi)
        self._rng = np.random.default_rng(seed)
        self._cid = p.connect(p.GUI if render_mode == "human" else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        p.setTimeStep(1.0 / 240.0)
        if render_mode == "human":                    # clean, close-in replay window
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_RGB_BUFFER_PREVIEW, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_DEPTH_BUFFER_PREVIEW, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_SEGMENTATION_MARK_PREVIEW, 0)
            p.configureDebugVisualizer(p.COV_ENABLE_SHADOWS, 1)
            p.resetDebugVisualizerCamera(0.55, 55, -22, [0.10, 0.0, 0.05])
        self.action_space = spaces.Box(-1.0, 1.0, (8,), np.float32)
        self.observation_space = spaces.Box(-np.inf, np.inf, (34,), np.float32)
        self._robot = None

    def set_ledge(self, lo, hi):                     # curriculum callback hook
        self.ledge_lo, self.ledge_hi = float(lo), float(hi)

    # -- helpers --------------------------------------------------------
    def _proj_gravity(self, quat):
        x, y, z, w = quat
        return np.array([-2.0 * (x * z - w * y),
                         -2.0 * (y * z + w * x),
                         -(1.0 - 2.0 * (x * x + y * y))])

    def _height_profile(self, body_x):
        """ground-truth surface height at PROFILE_X offsets ahead of the body."""
        out = []
        for dx in PROFILE_X:
            hit = p.rayTest([body_x + dx, 0.0, 0.30], [body_x + dx, 0.0, -0.20])[0]
            z = hit[3][2] if hit[0] >= 0 else 0.0
            out.append(np.clip(z / 0.08, 0.0, 1.5))     # scale ~ ledge / 8 cm
        return np.array(out)

    def _obs(self, action):
        (bx, by, bz), quat = p.getBasePositionAndOrientation(self._robot)
        _, ang = p.getBaseVelocity(self._robot)
        js = [p.getJointState(self._robot, j)[0] for j in REV]
        prog = np.clip((bx - LEDGE_FRONT_X) / 0.20, -1.0, 1.5)
        base_phase = min(1.0, self._t / len(_BASE))       # where we are in the scripted base motion
        return np.concatenate([
            quat,
            np.clip(np.array(ang) * 0.1, -1, 1),
            np.clip(self._proj_gravity(quat), -1, 1),
            np.array(js) / BOUND,
            action,
            self._height_profile(bx),
            [prog, base_phase],
        ]).astype(np.float32)

    def _state(self):
        (bx, by, bz), quat = p.getBasePositionAndOrientation(self._robot)
        roll, pitch, _ = p.getEulerFromQuaternion(quat)
        paws = [p.getLinkState(self._robot, j)[0] for j in PAW]
        on_top = sum(1 for (px, _py, pz) in paws
                     if pz > self._ledge_h - 0.02 and LEDGE_FRONT_X - 0.02 < px < LEDGE_FRONT_X + LEDGE_LEN)
        return bx, bz, roll, pitch, on_top

    # -- gym API ------------------------------------------------------
    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        p.resetSimulation()
        p.setGravity(0, 0, -9.81)
        p.setTimeStep(1.0 / 240.0)
        p.loadURDF("plane.urdf", [0, 0, 0])
        self._ledge_h = float(self._rng.uniform(self.ledge_lo, self.ledge_hi))
        cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[LEDGE_LEN / 2, 0.25, self._ledge_h / 2])
        vs = p.createVisualShape(p.GEOM_BOX, halfExtents=[LEDGE_LEN / 2, 0.25, self._ledge_h / 2],
                                 rgbaColor=[0.55, 0.45, 0.35, 1])
        p.createMultiBody(0, cs, vs, [LEDGE_FRONT_X + LEDGE_LEN / 2, 0.0, self._ledge_h / 2])

        self._robot = p.loadURDF(_URDF, [0, 0, 0.08],
                                 p.getQuaternionFromEuler([0, 0, 0]),
                                 flags=p.URDF_USE_SELF_COLLISION)
        for j, a in zip(REV, STANCE):
            p.resetJointState(self._robot, j, a)
        for _ in range(30):                             # settle at stance
            p.setJointMotorControlArray(self._robot, REV, p.POSITION_CONTROL,
                                        targetPositions=STANCE.tolist(), forces=[2.4] * 8)
            p.stepSimulation()
        self._t = 0
        self._last_action = np.zeros(8, np.float32)
        self._prev_x, self._prev_z = self._state()[0], self._state()[1]
        self._top_streak = 0
        self._xhist = [self._prev_x]
        self._stall_streak = 0
        self._goal = (LEDGE_FRONT_X + GOAL_DX, self._ledge_h + STAND_Z)
        self._prev_phi = self._phi(self._prev_x, self._prev_z)
        rz = np.mean([p.getLinkState(self._robot, j)[0][2] for j in REAR_PAW])
        self._prev_rear_phi = -max(0.0, self._ledge_h - rz)    # 0 when rear paws are at ledge height
        return self._obs(self._last_action), {}

    def _phi(self, bx, bz):
        gx, gz = self._goal
        return -(PHI_W_X * max(0.0, gx - bx) + PHI_W_Z * abs(gz - bz))

    def step(self, action):
        action = np.clip(np.asarray(action, np.float32), -1.0, 1.0)
        tgt = np.clip(_base_pose(self._t) + action * np.deg2rad(RES_DEG), -BOUND, BOUND)
        for _ in range(FRAME_SKIP):
            p.setJointMotorControlArray(self._robot, REV, p.POSITION_CONTROL,
                                        targetPositions=tgt.tolist(), forces=[2.6] * 8)
            p.stepSimulation()
        self._t += 1

        bx, bz, roll, pitch, on_top = self._state()
        if self.render_mode == "human":               # chase the robot, real-time
            p.resetDebugVisualizerCamera(0.55, 55, -22, [bx, 0.0, bz])
            time.sleep(1.0 / CTRL_HZ)
        d_x = bx - self._prev_x
        self._prev_x, self._prev_z = bx, bz
        tgt_z = self._ledge_h + STAND_Z

        # potential-based shaping toward the on-top goal (the main driver)
        phi = self._phi(bx, bz)
        r_shape = SHAPE_SCALE * (phi - self._prev_phi)
        self._prev_phi = phi

        # stall detection -- kills the "stand still" optimum
        self._xhist.append(bx)
        stalled = (self._t > STALL_WIN
                   and bx - self._xhist[-STALL_WIN - 1] < STALL_EPS)
        self._stall_streak = self._stall_streak + 1 if stalled else 0

        def _on(links):
            return sum(1 for (px, _py, pz) in (p.getLinkState(self._robot, j)[0] for j in links)
                       if pz > self._ledge_h - 0.015
                       and LEDGE_FRONT_X - 0.02 < px < LEDGE_FRONT_X + LEDGE_LEN)
        front_on, rear_on = _on(FRONT_PAW), _on(REAR_PAW)
        rear_z = np.mean([p.getLinkState(self._robot, j)[0][2] for j in REAR_PAW])
        rear_phi = -max(0.0, self._ledge_h - rear_z)                     # 0 at ledge height
        r_rear = W_REAR_SHAPE * (rear_phi - self._prev_rear_phi)         # telescopes -> unfarmnable
        self._prev_rear_phi = rear_phi

        pitch_over = max(0.0, abs(pitch) - PITCH_FREE)
        r = (r_shape
             + W_PROG * np.clip(d_x / 0.01, -1.0, 1.5)
             + W_FRONT_ON * front_on * (0.4 if rear_on == 0 else 1.0)   # front-only parking worth less
             + W_REAR_ON * rear_on                                       # the actual completion
             + r_rear                                                    # potential-based rear-height
             - W_ROLL * min(1.0, abs(roll) / 1.0)
             - PEN_PITCH_HARD * pitch_over
             - W_JERK * float(np.mean((action - self._last_action) ** 2))
             + W_ALIVE
             - (STALL_PEN if stalled else 0.0))
        self._last_action = action

        flipped = abs(pitch) > FLIP_RAD or abs(roll) > FLIP_RAD
        on_top_stable = (abs(bz - tgt_z) < 0.03 and bx > LEDGE_FRONT_X + 0.03
                         and on_top >= 3 and abs(pitch) < 0.4 and abs(roll) < 0.4)
        self._top_streak = self._top_streak + 1 if on_top_stable else 0

        terminated = False
        if flipped:
            r -= PEN_FLIP
            terminated = True
        elif self._top_streak >= 12:
            r += BONUS_TOP
            terminated = True
        elif self._stall_streak >= STALL_KILL:
            r -= 20.0
            terminated = True
        truncated = self._t >= MAX_STEPS
        return self._obs(action), float(r), terminated, truncated, {
            "on_top": on_top, "bz": bz, "pitch": pitch, "success": self._top_streak >= 12}

    def close(self):
        try:
            p.disconnect(self._cid)
        except Exception:
            pass
