"""ResidualGaitPolicy -- run the trained residual-on-wkF walking policy
(`run20m_ppo.onnx`) on real IMU data, producing joint targets for the BiBoard.

Pure numpy + onnxruntime. No pybullet, no serial. Exact deployment mirror of
`opencat_gym_env.OpenCatGymEnv`'s observation build + residual->joint mapping;
constants copied from that file, kept in sync by
`rl_training/opencat-gym/validate_deploy.py` (drives this class from the sim and
asserts obs + joint targets match `model.predict` bit-for-bit).

Control-flow mirrors the env exactly:
  reset(joints, quat, gyro)  builds obs_0  (phase 0, tilt history zero)
  step(quat, gyro):
     action = onnx(pending obs)          # pending = obs_0, then obs_1, ...
     joints = clip(wkF(phase) + action*22deg)        # uses the CURRENT phase
     advance phase
     build the NEXT pending obs from the freshly-read IMU + NEW phase
     return joints  (8 ints, degrees, URDF order)

Usage:
    pol = ResidualGaitPolicy()                         # gait/run20m_ppo.onnx + gait/wkf_ref.npy
    pol.set_command(fwd=0.10, yaw=0.0)
    quat, gyro = read_imu()
    pol.reset(joint_pos_rad_urdf, quat, gyro)
    while running:
        joint_deg_urdf = pol.step(*read_imu())
        send_to_servos(joint_deg_urdf)                 # via deploy_map -> OpenCat 'm'
        hold_rate(pol.CONTROL_HZ)

Observation layout (278):
    [ 0: 4] quaternion (x,y,z,w)
    [ 4: 6] roll/pitch angular velocity * 0.1, clipped
    [ 6: 9] projected gravity in body frame, clipped
    [ 9:10] cyclical phase = fmod(phase / 100, 1)
    [10:34] tilt history: last 12 x (roll,pitch)/1.3, clipped, oldest first
    [34:36] roll/pitch angular ACCEL (finite diff * 0.1), clipped
    [36:38] [cmd_fwd / 0.15, cmd_yaw / 0.45], clipped
    [38:278] joint-angle history: 30 x 8 commanded targets / deg2rad(110),
             newest last, appended every 2nd tick
"""
from __future__ import annotations

import os

import numpy as np

# ---- constants copied verbatim from opencat_gym_env.py -----------------------
CONTROL_HZ = 80.0
TIME_PHASE_PERIOD = 100
PHASE_RATE_NOM_CMD = 0.10
PHASE_RATE_MIN = 0.35
PHASE_RATE_MAX = 1.60
CMD_FWD_MAX = 0.15
CMD_FWD_MIN = -0.10
CMD_YAW_MAX = 0.45
BOUND_ANG_RAD = np.deg2rad(110)
RESIDUAL_SCALE_DEG = 22
STAND_FWD_THRESH = 0.025
ANG_FACTOR = 0.10
LEN_JOINT_HISTORY = 30
LEN_TILT_HISTORY = 12
FALL_TILT_RAD = 1.3

_HERE = os.path.dirname(os.path.abspath(__file__))


def quat_to_euler(q):
    """[x,y,z,w] -> (roll, pitch, yaw), Tait-Bryan ZYX. Matches pybullet."""
    x, y, z, w = q
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2.0 * (w * y - z * x), -1.0, 1.0))
    yaw = np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return roll, pitch, yaw


def proj_gravity_body(q):
    """[0,0,-1] rotated into the body frame = -R[2,:] with R = getMatrixFromQuaternion(q)."""
    x, y, z, w = q
    return np.array([
        -(2.0 * (x * z - w * y)),
        -(2.0 * (y * z + w * x)),
        -(1.0 - 2.0 * (x * x + y * y)),
    ])


class ResidualGaitPolicy:
    def __init__(self, onnx_path=None, wkf_path=None, intra_op_threads=2):
        import onnxruntime as ort
        self.CONTROL_HZ = CONTROL_HZ
        _train = os.path.normpath(os.path.join(
            _HERE, "..", "..", "rl_training", "opencat-gym", "trained", "run20m_ppo.onnx"))
        onnx_path = onnx_path or next(
            (p for p in (os.path.join(_HERE, "run20m_ppo.onnx"), _train) if os.path.exists(p)),
            os.path.join(_HERE, "run20m_ppo.onnx"))
        wkf_path = wkf_path or os.path.join(_HERE, "wkf_ref.npy")
        if not os.path.exists(onnx_path):
            raise FileNotFoundError(
                f"run20m_ppo.onnx not found (looked in pi_pipeline/gait/ and "
                f"rl_training/opencat-gym/trained/). Run export_onnx.py, or pass onnx_path=")
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(intra_op_threads)
        self._sess = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
        self._in_name = self._sess.get_inputs()[0].name

        self.WKF_REF = np.load(wkf_path).astype(np.float64)          # (100,8) rad, URDF order
        assert self.WKF_REF.shape == (TIME_PHASE_PERIOD, 8), self.WKF_REF.shape
        self.STAND_POSE = self.WKF_REF.mean(axis=0)

        self._cmd_fwd = 0.0
        self._cmd_yaw = 0.0
        self._obs = None
        self.last_action = None

    # -- setup ------------------------------------------------------------
    def set_command(self, fwd=None, yaw=None):
        if fwd is not None:
            self._cmd_fwd = float(np.clip(fwd, CMD_FWD_MIN, CMD_FWD_MAX))
        if yaw is not None:
            self._cmd_yaw = float(np.clip(yaw, -CMD_YAW_MAX, CMD_YAW_MAX))

    def _cmd_obs(self):
        return np.array([np.clip(self._cmd_fwd / CMD_FWD_MAX, -1.0, 1.0),
                         np.clip(self._cmd_yaw / CMD_YAW_MAX, -1.0, 1.0)])

    def reset(self, joint_pos_rad_urdf, quat_xyzw, gyro_xyz_radps):
        """Build obs_0 exactly as env.reset(): phase 0, tilt history all-zero,
        ang-accel zero."""
        j = np.asarray(joint_pos_rad_urdf, dtype=np.float64).reshape(8) / BOUND_ANG_RAD
        self.angle_history = np.tile(j, LEN_JOINT_HISTORY)              # 240
        self.tilt_history = np.zeros(LEN_TILT_HISTORY * 2)             # 24
        self._phase = 0.0
        self._tick = 0
        q = np.asarray(quat_xyzw, dtype=np.float64).reshape(4)
        g = np.asarray(gyro_xyz_radps, dtype=np.float64).reshape(3)[:2]
        self._prev_ang_vel = g.copy()
        vel_clip = np.clip(g * ANG_FACTOR, -1.0, 1.0)
        pg = np.clip(proj_gravity_body(q), -1.0, 1.0)
        state_robot = np.concatenate((q, vel_clip, pg, [0.0],
                                      self.tilt_history, np.zeros(2), self._cmd_obs()))
        self._obs = np.concatenate((state_robot, self.angle_history)).astype(np.float32)
        return self._obs

    # -- one control tick ----------------------------------------------
    def step(self, quat_xyzw, gyro_xyz_radps):
        """quat_xyzw: [x,y,z,w] body orientation, freshly read.
           gyro_xyz_radps: body-frame angular rate [wx,wy,wz], freshly read.
           returns: 8 integer joint targets, degrees, URDF order."""
        if self._obs is None:
            raise RuntimeError("call reset(joints, quat, gyro) first")

        # --- action + joints for THIS tick, from the pending obs and CURRENT phase ---
        action = self._sess.run(None, {self._in_name: self._obs[None, :]})[0][0]
        self.last_action = action
        is_stand = abs(self._cmd_fwd) < STAND_FWD_THRESH
        ref = self.STAND_POSE if is_stand else self.WKF_REF[int(self._phase) % TIME_PHASE_PERIOD]
        joint_rad = np.clip(ref + action * np.deg2rad(RESIDUAL_SCALE_DEG),
                            -BOUND_ANG_RAD, BOUND_ANG_RAD)
        joint_deg = np.rint(np.rad2deg(joint_rad)).astype(int)
        joint_rad_rounded = np.deg2rad(joint_deg.astype(np.float64))

        # --- update joint history (every 2nd tick, like the env) ---
        if self._tick % 2 == 0:
            self.angle_history = np.append(self.angle_history,
                                           joint_rad_rounded / BOUND_ANG_RAD)[8:]

        # --- advance phase (tilt-slow disabled: PHASE_SLOW_RATE = 1.0) ---
        if not is_stand:
            pd = 1.0 if self._cmd_fwd >= 0 else -1.0
            prate = float(np.clip(abs(self._cmd_fwd) / PHASE_RATE_NOM_CMD,
                                  PHASE_RATE_MIN, PHASE_RATE_MAX))
            self._phase += pd * prate
        self._tick += 1

        # --- build the NEXT pending obs from the freshly-read IMU + NEW phase ---
        q = np.asarray(quat_xyzw, dtype=np.float64).reshape(4)
        w_rp = np.asarray(gyro_xyz_radps, dtype=np.float64).reshape(3)[:2]
        roll, pitch, _ = quat_to_euler(q)
        tnorm = np.clip(np.array([roll, pitch]) / FALL_TILT_RAD, -1.0, 1.0)
        self.tilt_history = np.append(self.tilt_history, tnorm)[2:]
        vel_clip = np.clip(w_rp * ANG_FACTOR, -1.0, 1.0)
        ang_acc = np.clip((w_rp - self._prev_ang_vel) * ANG_FACTOR, -1.0, 1.0)
        self._prev_ang_vel = w_rp.copy()
        pg = np.clip(proj_gravity_body(q), -1.0, 1.0)
        time_obs = np.fmod(self._phase / TIME_PHASE_PERIOD, 1.0)
        state_robot = np.concatenate((q, vel_clip, pg, [time_obs],
                                      self.tilt_history, ang_acc, self._cmd_obs()))
        self._obs = np.concatenate((state_robot, self.angle_history)).astype(np.float32)

        return joint_deg

    @property
    def obs(self):
        return self._obs
