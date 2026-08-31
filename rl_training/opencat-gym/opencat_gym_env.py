import os
import gymnasium as gym
import numpy as np
import pybullet as p
import pybullet_data

# Bittle's built-in `wkF` walk gait as a per-phase joint reference (radians, URDF
# joint order), for the FAC_IMITATION reward. Built by
# reference_gait/build_wkf_reference.py from OpenCatEsp32's InstinctBittleESP.h.
_WKF_PATH = os.path.join(os.path.dirname(__file__), "reference_gait", "wkf_ref.npy")
WKF_REF = np.load(_WKF_PATH) if os.path.exists(_WKF_PATH) else None


# Constants to define training and visualisation.
GUI_MODE = False          # Set "True" to display pybullet in a window
EPISODE_LENGTH = 250      # Number of steps for one training episode
MAXIMUM_LENGTH = 1.8e6    # Number of total steps for entire training

# Factors to weight rewards and penalties.
PENALTY_STEPS = 5e5       # Increase of penalty by step_counter/PENALTY_STEPS -- was 2e6 (exactly equal to total training length in every run so far, v1-v4), meaning the penalty was still shifting the reward landscape for the entire run. Lowered so it reaches full, stable strength at 25% through a 2M-step run, leaving most of training to converge under a non-shifting reward.
FAC_MOVEMENT = 1000       # Reward movement in x-direction
FAC_STABILITY = 0.1       # Punish body roll and pitch velocities
FAC_YAW = 0.1             # Punish body yaw (turning) velocity -- discourages curving off a straight line
FAC_HEADING = 5.0         # Punish absolute heading error (accumulated yaw away from straight-ahead). FAC_YAW penalizes turn *rate*; nothing pulled accumulated heading back to 0, so v6's gait drifted ~12 deg off straight by episode end. auto_iter1 tried 0.5 -- far too weak (~1% of the forward reward), no effect. auto_iter2: 5.0 (~7% of forward reward at a 13 deg drift). Yaw is recoverable from the base quaternion already in the observation, so no observation-space change.
FAC_Z_VELOCITY = 0.0      # Punish z movement of body
FAC_SLIP = 0.01           # Punish slipping of paws -- was 0.0; enabled to discourage dragging/jittering feet instead of real steps
FAC_ARM_CONTACT = 0.01    # Punish crawling on arms and elbows
FAC_SMOOTH_1 = 0.5        # Punish jitter and vibrational movement, 1st order -- was 1.0; halved because it directly penalizes joint-angle-change magnitude, which was fighting against bigger, more deliberate leg swings (v5 produced fast but very small-stepped movement on all four legs). FAC_JITTER still targets direction-reversal specifically, so genuine oscillation should stay in check.
FAC_SMOOTH_2 = 0.5        # Punish jitter and vibrational movement, 2nd order -- was 1.0; see FAC_SMOOTH_1 note above
FAC_CLEARANCE = 0.1       # Factor to enfore foot clearance to PAW_Z_TARGET -- was 0.0; enabled to reward lifting feet during swing phase
PAW_Z_TARGET = 0.020      # Target height (m) of paw during swing phase. v6: 15mm (was 5mm before that). auto_iter3: 25mm -- after FAC_HEADING=5.0 the policy went front-heavy and let the back feet drag at ~10mm; FAC_CLEARANCE penalizes squared deviation from this target both ways, so raising it pushes the dragging back feet up hard while easing the over-high front feet. Matches what v6 actually achieved (~23mm).
FAC_JITTER = 0.2          # Punish joints reversing direction frame-to-frame (adapted from bmabsout/opencat-gym's change_direction idea) -- discourages jittering/shuffling in place instead of real steps
FAC_STRIDE = 0.0         # Reward per-foot forward distance between consecutive ground contacts (touchdown->touchdown = real stride length). Cannot be gamed by fast air-flicks like Run 4's swing-velocity version. Added in Run 5 iter3 to counter domain randomization's pull toward a timid tiny-step shuffle. First guess -- tune.
FAC_GAIT_SYMMETRY = 3.5   # Reward a diagonal trot pattern: front-right+back-left swinging together, opposite to front-left+back-right, like a real quadruped. Applied unramped (not scaled by PENALTY_STEPS) so this shapes gait structure from step 1, rather than risking the policy settling into a different pattern early and getting disrupted later (the mechanism behind full_run_v1's late-training collapse). v6 and earlier: 2.0. auto_iter4: raised to 3.5 after auto_iter3 (PAW_Z_TARGET bump) loosened the trot to -0.45 correlation; a crisper diagonal trot is also left/right symmetric, so this should tighten heading drift too.
FAC_IMITATION = 12.0     # Reward matching Bittle's built-in `wkF` walk gait (reference_gait/wkf_ref.npy, 100 phase-frames aligned to TIME_PHASE_PERIOD). DeepMimic-style: exp(-IMITATION_SHARPNESS * sum sq per-joint error), in [0,1]. Dense 8-joint target -- a much stronger, less-gameable gait signal than FAC_GAIT_SYMMETRY / FAC_STRIDE. Default 0; enable HEAVY (~20-40) for imitation runs so the policy mimics wkF while adapting only as much as staying upright forces. Verified: open-loop playback walks the URDF +0.48m without falling, direct joint mapping, no sign flips.
IMITATION_SHARPNESS = 2.0 # higher = stricter match required for the same reward

TIME_PHASE_PERIOD = 100   # Steps per cycle of the time/phase observation input (adapted from bmabsout/opencat-gym) -- gives the policy a rhythmic clock signal to help it learn periodic gaits

BOUND_ANG = 110         # Joint maximum angle (deg)
STEP_ANGLE = 11           # Maximum angle (deg) delta per step
ANG_FACTOR = 0.1          # Improve angular velocity resolution before clip.

# --- Domain randomization (sim-to-real) -----------------------------------------
# Each per-episode randomization ramps in over training:
#   dr = min(1, env.step_counter_session / DR_RAMP_STEPS)
# so early training keeps the clean flat-ground gait and difficulty grows. All
# default 0 (= no randomization); the automated loop enables them one at a time.
# evaluate_policy.py --dr-* flags override these and force dr = 1 for testing.
DR_RAMP_STEPS = 5e5

RANDOM_JOINT_ANGS = 5     # % noise on the joint-angle *history* buffer (already wired, unchanged)
RANDOM_GYRO = 0.02       # IMU noise: gaussian std added to the orientation quat + roll/pitch-rate in the OBSERVATION only (reward stays clean). e.g. 0.03
RANDOM_FRICTION = 0.3    # +/- fraction on ground lateral friction, per episode. e.g. 0.5
RANDOM_MASS = 0.15        # +/- fraction on every robot link mass, per episode. e.g. 0.15
RANDOM_PUSH = 0.0        # random horizontal shove: max instantaneous base-velocity kick (m/s). e.g. 0.35
RANDOM_PUSH_PROB = 0.02  # per-step probability of a shove
RANDOM_TERRAIN = 0.012    # scatter small boxes/steps in the forward path, max height (m). e.g. 0.012
DR_EVAL_FULL = False     # eval sets this True -> dr = 1 regardless of step count

LENGTH_RECENT_ANGLES = 3  # Buffer to read recent joint angles
LENGTH_JOINT_HISTORY = 30 # Number of steps to store joint angles.

# Size of oberservation space is set up of:
# [LENGTH_JOINT_HISTORY, quaternion, gyro, time_phase]
SIZE_OBSERVATION = LENGTH_JOINT_HISTORY * 8 + 6 + 1


class OpenCatGymEnv(gym.Env):
    """ Gymnasium environment (stable baselines 3) for OpenCat robots.
    """

    metadata = {'render.modes': ['human']}

    def __init__(self):
        self.step_counter = 0
        self.step_counter_session = 0
        self._dr = 0.0            # domain-randomization ramp for the current episode
        self.state_history = np.array([])
        self.angle_history = np.array([])
        self.bound_ang = np.deg2rad(BOUND_ANG)

        if GUI_MODE:
            p.connect(p.GUI)
            # Uncommend to create a video.
            #video_options = ("--width=960 --height=540 
            #                + "--mp4=\"training.mp4\" --mp4fps=60")
            #p.connect(p.GUI, options=video_options) 
        else:
            # Use for training without visualisation (significantly faster).
            p.connect(p.DIRECT)

        p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
        p.resetDebugVisualizerCamera(cameraDistance=0.5, 
                                     cameraYaw=-170, 
                                     cameraPitch=-40, 
                                     cameraTargetPosition=[0.4,0,0])

        # The action space are the 8 joint angles.
        self.action_space = gym.spaces.Box(np.array([-1]*8), np.array([1]*8))

        # The observation space are the torso roll, pitch and the 
        # angular velocities and a history of the last 30 joint angles.
        self.observation_space = gym.spaces.Box(np.array([-1]*SIZE_OBSERVATION), 
                                                np.array([1]*SIZE_OBSERVATION))


    def step(self, action):
        p.configureDebugVisualizer(p.COV_ENABLE_SINGLE_STEP_RENDERING)
        # Random horizontal shove (perturbation robustness / balance recovery).
        if RANDOM_PUSH > 0 and self._dr > 0 and np.random.rand() < RANDOM_PUSH_PROB:
            lin, ang = p.getBaseVelocity(self.robot_id)
            dv = np.random.uniform(-RANDOM_PUSH, RANDOM_PUSH, 2) * self._dr
            p.resetBaseVelocity(self.robot_id,
                                [lin[0] + dv[0], lin[1] + dv[1], lin[2]], ang)
        last_position = p.getBasePositionAndOrientation(self.robot_id)[0][0]
        joint_angs = np.asarray(p.getJointStates(self.robot_id, self.joint_id),
                                                   dtype=object)[:,0]
        ds = np.deg2rad(STEP_ANGLE) # Maximum change of angle per step
        joint_angs += action * ds # Change per step including agent action

        # Apply joint boundaries individually.
        min_ang = -self.bound_ang
        max_ang = self.bound_ang
        joint_angs[0] = np.clip(joint_angs[0], min_ang, max_ang) # shoulder_left
        joint_angs[1] = np.clip(joint_angs[1], min_ang, max_ang) # elbow_left
        joint_angs[2] = np.clip(joint_angs[2], min_ang, max_ang) # shoulder_right
        joint_angs[3] = np.clip(joint_angs[3], min_ang, max_ang) # elbow_right
        joint_angs[4] = np.clip(joint_angs[4], min_ang, max_ang) # hip_right
        joint_angs[5] = np.clip(joint_angs[5], min_ang, max_ang) # knee_right
        joint_angs[6] = np.clip(joint_angs[6], min_ang, max_ang) # hip_left
        joint_angs[7] = np.clip(joint_angs[7], min_ang, max_ang) # knee_left

        # Transform angle to degree and perform rounding, because 
        # OpenCat robot have only integer values.
        joint_angsDeg = np.rad2deg(joint_angs.astype(np.float64))
        joint_angsDegRounded = joint_angsDeg.round()
        joint_angs = np.deg2rad(joint_angsDegRounded)

        # Simulate delay for data transfer. Delay has to be modeled to close 
        # "reality gap").
        p.stepSimulation()

        # Check for friction of paws, to prevent slipping while training.
        paw_contact = []
        paw_idx = [3, 6, 9, 12]
        for idx in paw_idx:
            paw_contact.append(True if p.getContactPoints(bodyA=self.robot_id, 
                                                          linkIndexA=idx) 
                                    else False)

        paw_slipping = 0
        for in_contact in np.nonzero(paw_contact)[0]:
            paw_slipping += np.linalg.norm((
                            p.getLinkState(self.robot_id,
                                           linkIndex=paw_idx[in_contact], 
                                           computeLinkVelocity=1)[0][0:1]))

        # Read clearance of paw from ground
        paw_clearance = 0
        for idx in paw_idx:
            paw_z_pos = p.getLinkState(self.robot_id, linkIndex=idx)[0][2]
            paw_clearance += (paw_z_pos-PAW_Z_TARGET)**2 * np.linalg.norm(
                (p.getLinkState(self.robot_id, linkIndex=idx, 
                                computeLinkVelocity=1)[0][0:1]))**0.5

        # Stride-length reward: on each foot touchdown (contact False->True),
        # reward the forward x-distance that foot covered since its previous
        # touchdown. That is a real stride and can't be gamed by fast air-flicks.
        stride_reward = 0.0
        for i, idx in enumerate(paw_idx):
            fx = p.getLinkState(self.robot_id, idx)[0][0]
            if paw_contact[i] and not self._foot_prev_contact[i]:
                stride_reward += max(0.0, fx - self._foot_td_x[i])
                self._foot_td_x[i] = fx
            self._foot_prev_contact[i] = paw_contact[i]

        # Check if elbows or lower arm are in contact with ground
        arm_idx = [1, 2, 4, 5]
        for idx in arm_idx:
            if p.getContactPoints(bodyA=self.robot_id, linkIndexA=idx):
                self.arm_contact += 1

        # Read clearance of torso from ground
        base_clearance = p.getBasePositionAndOrientation(self.robot_id)[0][2]

        # Set new joint angles
        p.setJointMotorControlArray(self.robot_id, 
                                    self.joint_id, 
                                    p.POSITION_CONTROL, 
                                    joint_angs, 
                                    forces=np.ones(8)*0.2)
        p.stepSimulation() # Delay of data transfer

        # Normalize joint_angs
        joint_angs[0] /= self.bound_ang
        joint_angs[1] /= self.bound_ang
        joint_angs[2] /= self.bound_ang
        joint_angs[3] /= self.bound_ang
        joint_angs[4] /= self.bound_ang
        joint_angs[5] /= self.bound_ang
        joint_angs[6] /= self.bound_ang
        joint_angs[7] /= self.bound_ang

        # Adding every 2nd angle to the joint angle history.
        if(self.step_counter % 2 == 0):
            self.angle_history = np.append(self.angle_history, 
                                           self.randomize(joint_angs, 
                                                          RANDOM_JOINT_ANGS))
            self.angle_history = np.delete(self.angle_history, np.s_[0:8])

        self.recent_angles = np.append(self.recent_angles, joint_angs)
        self.recent_angles = np.delete(self.recent_angles, np.s_[0:8])

        joint_angs_prev = self.recent_angles[8:16]
        joint_angs_prev_prev = self.recent_angles[0:8]

        # Read robot state (pitch, roll and their derivatives of the torso).
        state_pos, state_ang = p.getBasePositionAndOrientation(self.robot_id)
        p.stepSimulation() # Emulated delay of data transfer via serial port
        state_ang_euler = np.asarray(p.getEulerFromQuaternion(state_ang)[0:2])
        state_vel_raw = np.asarray(p.getBaseVelocity(self.robot_id)[1])
        # Yaw (turning) rate -- penalized below to discourage curving off a
        # straight line, but not added to the observation (self.state_robot)
        # to keep the observation space unchanged for this iteration.
        yaw_rate_clip = np.clip(state_vel_raw[2]*ANG_FACTOR, -1, 1)
        # Absolute heading error: yaw relative to the reset heading (0 = straight
        # ahead). Penalized below so accumulated drift is corrected, not just
        # turn rate. Stays small for a roughly-straight walker, so no wraparound
        # handling is needed; clip anyway for safety.
        heading_error_clip = np.clip(p.getEulerFromQuaternion(state_ang)[2], -np.pi, np.pi)
        state_vel = state_vel_raw[0:2]*ANG_FACTOR
        state_vel_clip = np.clip(state_vel, -1, 1)
        # Cyclical time/phase signal (adapted from bmabsout/opencat-gym) -- a
        # rhythmic clock input to help the policy learn periodic gaits instead
        # of an arbitrary, potentially jittery movement pattern.
        time_obs = np.fmod(self.step_counter / TIME_PHASE_PERIOD, 1.0)
        # IMU noise: noise only what the policy SEES, not the reward. The real
        # BiBoard IMU is noisy/biased; a policy trained on perfect orientation
        # can oscillate on real data.
        obs_ang, obs_vel_clip = state_ang, state_vel_clip
        if RANDOM_GYRO > 0 and self._dr > 0:
            n = RANDOM_GYRO * self._dr
            obs_ang = np.array(state_ang) + np.random.normal(0.0, n, 4)
            obs_vel_clip = np.clip(state_vel_clip + np.random.normal(0.0, n, 2), -1, 1)
        self.state_robot = np.concatenate((obs_ang, obs_vel_clip, [time_obs]))
        current_position = p.getBasePositionAndOrientation(self.robot_id)[0][0]

        # Penalty and reward
        smooth_movement = np.sum(
            FAC_SMOOTH_1*np.abs(joint_angs-joint_angs_prev)**2
            + FAC_SMOOTH_2*np.abs(joint_angs
            - 2*joint_angs_prev
            + joint_angs_prev_prev)**2)

        # Anti-jitter penalty (adapted from bmabsout/opencat-gym's
        # change_direction idea): count joints whose movement direction
        # reversed from the previous frame to this one -- directly targets
        # jittering/shuffling back and forth in place, rather than just
        # penalizing the magnitude of movement like FAC_SMOOTH_1/2 do.
        direction_reversed = np.sign(joint_angs - joint_angs_prev) != np.sign(joint_angs_prev - joint_angs_prev_prev)
        jitter_penalty = np.sum(direction_reversed)

        # Diagonal trot gait-symmetry reward: front-right (shoulder_right,
        # idx 2) + back-left (hip_left, idx 6) should swing together, in
        # opposition to front-left (shoulder_left, idx 0) + back-right
        # (hip_right, idx 4) -- like a real quadruped trot. Verified
        # empirically (see docs/project-plan.md) that all 8 joints in this
        # URDF share the same sign convention, so "same sign of angle change"
        # genuinely means "in phase" here, no mirroring to account for.
        joint_delta = joint_angs - joint_angs_prev
        diagonal_a = joint_delta[2] + joint_delta[6]  # front-right + back-left
        diagonal_b = joint_delta[0] + joint_delta[4]  # front-left + back-right
        gait_symmetry = -diagonal_a * diagonal_b  # positive when diagonals move opposite each other

        z_velocity = p.getBaseVelocity(self.robot_id)[0][2]

        body_stability = (FAC_STABILITY * (state_vel_clip[0]**2
                                          + state_vel_clip[1]**2)
                                          + FAC_Z_VELOCITY * z_velocity**2
                                          + FAC_YAW * yaw_rate_clip**2)

        # Accumulated-heading penalty -- its own term (not folded into
        # body_stability) so its contribution shows up separately in info.
        heading_penalty = FAC_HEADING * heading_error_clip**2

        # Imitation reward: match Bittle's built-in wkF walk at the current gait
        # phase. DeepMimic-style exp(-sharpness * sum sq per-joint error), in
        # [0,1]. joint_angs here is already normalised (/ bound_ang); normalise
        # the reference the same way.
        imitation_reward = 0.0
        if FAC_IMITATION > 0 and WKF_REF is not None:
            ref = WKF_REF[self.step_counter % len(WKF_REF)] / self.bound_ang
            imit_err = np.sum((joint_angs - ref) ** 2)
            imitation_reward = np.exp(-IMITATION_SHARPNESS * imit_err)

        movement_forward = current_position - last_position
        penalty_scale = self.step_counter_session / PENALTY_STEPS
        reward = (FAC_MOVEMENT * movement_forward
                 + FAC_GAIT_SYMMETRY * gait_symmetry
                 + FAC_STRIDE * stride_reward
                 + FAC_IMITATION * imitation_reward
                 - penalty_scale * (
                    smooth_movement + body_stability
                    + heading_penalty
                    + FAC_CLEARANCE * paw_clearance
                    + FAC_SLIP * paw_slipping**2
                    + FAC_ARM_CONTACT * self.arm_contact
                    + FAC_JITTER * jitter_penalty))

        # Set state of the current state.
        terminated = False
        truncated = False
        # Per-term reward breakdown (weighted contributions, same units as the
        # final reward) -- lets us see which term shifts when behavior changes,
        # instead of only seeing the total reward.
        info = {
            "r_movement": FAC_MOVEMENT * movement_forward,
            "r_gait_symmetry": FAC_GAIT_SYMMETRY * gait_symmetry,
            "r_stride": FAC_STRIDE * stride_reward,
            "r_imitation": FAC_IMITATION * imitation_reward,
            "r_smooth_movement": -penalty_scale * smooth_movement,
            "r_body_stability": -penalty_scale * body_stability,
            "r_heading": -penalty_scale * heading_penalty,
            "r_paw_clearance": -penalty_scale * FAC_CLEARANCE * paw_clearance,
            "r_paw_slip": -penalty_scale * FAC_SLIP * paw_slipping**2,
            "r_arm_contact": -penalty_scale * FAC_ARM_CONTACT * self.arm_contact,
            "r_jitter": -penalty_scale * FAC_JITTER * jitter_penalty,
        }

        # Stop criteria of current learning episode: 
        # Number of steps or robot fell.
        self.step_counter += 1
        if self.step_counter > EPISODE_LENGTH:
            self.step_counter_session += self.step_counter
            terminated = False
            truncated = True

        elif self.is_fallen(): # Robot fell
            self.step_counter_session += self.step_counter
            reward = 0
            terminated = True
            truncated = False

        self.observation = np.hstack((self.state_robot, self.angle_history))

        return (np.array(self.observation).astype(np.float32), 
                        reward, terminated, truncated, info)


    def reset(self, seed=None, options=None):
        self.step_counter = 0
        self.arm_contact = 0
        self._foot_prev_contact = [False, False, False, False]
        self._foot_td_x = [0.0, 0.0, 0.0, 0.0]
        # Domain-randomization ramp for this episode.
        if DR_EVAL_FULL or DR_RAMP_STEPS <= 0:
            self._dr = 1.0
        else:
            self._dr = min(1.0, self.step_counter_session / DR_RAMP_STEPS)
        p.resetSimulation()
        # Disable rendering during loading.
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING,0)
        p.setGravity(0,0,-9.81)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        plane_id = p.loadURDF("plane.urdf")
        if RANDOM_FRICTION > 0:
            p.changeDynamics(plane_id, -1, lateralFriction=max(0.1,
                1.0 + np.random.uniform(-RANDOM_FRICTION, RANDOM_FRICTION) * self._dr))
        if RANDOM_TERRAIN > 0 and self._dr > 0:
            self._scatter_obstacles(RANDOM_TERRAIN * self._dr)

        start_pos = [0,0,0.08]
        start_orient = p.getQuaternionFromEuler([0,0,0])

        urdf_path = "models/"#"/content/drive/My Drive/opencat-gym-esp32/models/"
        self.robot_id = p.loadURDF(urdf_path + "bittle_esp32.urdf", 
                                   start_pos, start_orient, 
                                   flags=p.URDF_USE_SELF_COLLISION) 
        
        # Initialize urdf links and joints.
        self.joint_id = []
        #paramIds = []
        for j in range(p.getNumJoints(self.robot_id)):
            info = p.getJointInfo(self.robot_id, j)
            joint_name = info[1]
            joint_type = info[2]

            if (joint_type == p.JOINT_PRISMATIC 
                or joint_type == p.JOINT_REVOLUTE):
                self.joint_id.append(j)
                #paramIds.append(p.addUserDebugParameter(joint_name.decode("utf-8")))
                # Limiting motor dynamics. Although bittle's dynamics seem to
                # be be quite high like up to 7 rad/s.
                p.changeDynamics(self.robot_id, j, maxJointVelocity = np.pi*10)

        # Per-episode link-mass randomization (URDF masses are estimates; the
        # real robot's battery/wiring shift the distribution).
        if RANDOM_MASS > 0:
            for link in range(-1, p.getNumJoints(self.robot_id)):
                m0 = p.getDynamicsInfo(self.robot_id, link)[0]
                if m0 > 0:
                    p.changeDynamics(self.robot_id, link, mass=m0 * (
                        1.0 + np.random.uniform(-RANDOM_MASS, RANDOM_MASS) * self._dr))

        # Setting start position. This influences training.
        joint_angs = np.deg2rad(np.array([1, 0, 1, 0, 1, 0, 1, 0])*50)

        i = 0
        for j in self.joint_id:
            p.resetJointState(self.robot_id,j, joint_angs[i])
            i = i+1

        # Normalize joint angles.
        joint_angs[0] /= self.bound_ang
        joint_angs[1] /= self.bound_ang
        joint_angs[2] /= self.bound_ang
        joint_angs[3] /= self.bound_ang
        joint_angs[4] /= self.bound_ang
        joint_angs[5] /= self.bound_ang
        joint_angs[6] /= self.bound_ang
        joint_angs[7] /= self.bound_ang

        # Read robot state (pitch, roll and their derivatives of the torso)
        state_ang = p.getBasePositionAndOrientation(self.robot_id)[1]
        state_vel = np.asarray(p.getBaseVelocity(self.robot_id)[1])
        state_vel = state_vel[0:2]*ANG_FACTOR
        # step_counter is 0 here, so time_obs starts each episode at phase 0.
        time_obs = np.fmod(self.step_counter / TIME_PHASE_PERIOD, 1.0)
        self.state_robot = np.concatenate((state_ang,
                                           np.clip(state_vel, -1, 1),
                                           [time_obs]))

        # Initialize robot state history with reset position
        state_joints = np.asarray(
            p.getJointStates(self.robot_id, self.joint_id), dtype=object)[:,0]
        state_joints /= self.bound_ang 
        
        self.angle_history = np.tile(state_joints, LENGTH_JOINT_HISTORY)
        self.recent_angles = np.tile(state_joints, LENGTH_RECENT_ANGLES)
        self.observation = np.concatenate((self.state_robot, 
                                           self.angle_history))
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING,1)
        info = {}
        return np.array(self.observation).astype(np.float32), info


    def _scatter_obstacles(self, max_h):
        """Small static boxes/steps in the robot's forward path -- 'small
        obstacles to walk over'. Amplitude is scaled by the caller (dr ramp)."""
        for _ in range(np.random.randint(3, 9)):
            h = np.random.uniform(0.002, max(0.003, max_h))
            cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[
                np.random.uniform(0.015, 0.04),   # along-path half-length
                np.random.uniform(0.04, 0.10),    # across-path half-width
                h / 2])
            p.createMultiBody(0, cs, basePosition=[
                np.random.uniform(0.12, 1.3),
                np.random.uniform(-0.06, 0.06),
                h / 2])


    def render(self, mode='human'):
        pass


    def close(self):
        p.disconnect()


    def is_fallen(self):
        """ Check if robot is fallen. It becomes "True", 
            when pitch or roll is more than 1.3 rad.
        """
        pos, orient = p.getBasePositionAndOrientation(self.robot_id)
        orient = p.getEulerFromQuaternion(orient)
        is_fallen = (np.fabs(orient[0]) > 1.3 
                    or np.fabs(orient[1]) > 1.3)

        return is_fallen


    def randomize(self, value, percentage):
        """ Randomize value within percentage boundaries.
        """
        percentage /= 100
        value_randomized = value * (1 + percentage*(2*np.random.rand()-1))

        return value_randomized
