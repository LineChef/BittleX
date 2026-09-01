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

# One env.step() runs 3 p.stepSimulation() calls at PyBullet's default 1/240 s
# timestep -> 1/80 s of sim per control step -> 80 Hz control. (evaluate_policy.py
# historically assumed 50 Hz; Run 7 fixes it to 80. Multiply any pre-Run-7
# reported m/s by 1.6 to compare.)
CONTROL_HZ = 80.0

# Factors to weight rewards and penalties.
PENALTY_STEPS = 5e5       # Increase of penalty by step_counter/PENALTY_STEPS -- was 2e6 (exactly equal to total training length in every run so far, v1-v4), meaning the penalty was still shifting the reward landscape for the entire run. Lowered so it reaches full, stable strength at 25% through a 2M-step run, leaving most of training to converge under a non-shifting reward.
FAC_MOVEMENT = 300        # Reward forward progress (capped at TARGET_SPEED). surv_r5: back to surv_r2's 300 (r3's 550 flattened the trot, r4's 350 no better). The tilt-gated MIN_SPEED floor now holds the flat-speed gate without fighting a stumble.
FAC_OVERSPEED = 35.0      # surv_r1: penalty = FAC_OVERSPEED * max(0, vx_est - TARGET_SPEED), unramped -- mirror of the MIN_SPEED floor on the fast side. surv_r2: 60 -> 35, surv_r1 pulled flat speed to 0.081 (just under the 0.085 gate); the MIN_SPEED floor (120) still stops a stall.

# --- Residual action space (residual-on-wkF, "resid" line) -------------------
# RESIDUAL_MODE True: the policy output modulates Bittle's scripted wkF keyframe
# pose instead of accumulating per-step deltas --
#   joint_target = wkF(phase) + action * deg2rad(RESIDUAL_SCALE_DEG)
# action = 0 reproduces the open-loop scripted walk exactly, so the policy can
# only add a learned correction on top of a gait that's already robust -- a
# learned version of the firmware's gyro-balance layer. Motivation: the
# learned-vs-scripted benchmark (docs/rl-runs/gait-benchmark.md) showed the scripted
# keyframes are hard to beat on obstacles; this starts from them and climbs.
RESIDUAL_MODE = True
RESIDUAL_SCALE_DEG = 11   # +/- correction the policy may apply. r1 used 18 (warped wkF to a crawl); resid_r2 used 11. rtune_r3 tried 8 -- fixed heading at 20/35mm but couldn't catch 50mm trips (falls 14->29%). Reverted to 11.
FAC_RESIDUAL_COST = 1.5   # -mean(action^2) * this -- deviate from the scripted pose only when it helps
FAC_RESID_SMOOTH = 6.0    # rtune_r4: -mean(|action - prev_action|) * this (ramped). Penalise frame-to-frame jerk in the correction, not its magnitude -- a smoother residual should cut roll oscillation / heading drift without capping the authority needed for a 50mm trip.

# --- Stay-down / stay-level shaping (also from the scripted-gait benchmark) ---
FAC_DUTY = 0.0            # r1: 4.0 was the main 'freeze with feet planted' attractor -> the gait stalled. wkF already has a good duty factor by construction; don't reward it.
FAC_UPRIGHT = 3.0         # ramped penalty on tilt^2 (always on). r1: 8.0 stacked with FAC_DUTY + the speed cap into a stand-still attractor. Keep a tilt penalty, don't let it dominate.

# --- Target walk speed (Run 7) ------------------------------------------------
# "Walk" line: establish a deliberate baseline speed and hold it, rather than
# letting whatever speed falls out of the other terms stand. Speed stays BELOW
# gait-match in priority (FAC_SPEED << FAC_IMITATION). Faster gaits come later.
# Tracking-bonus form (user pick): a [0,1] bonus peaking exactly at the target,
# falling off if too slow OR too fast -- same shape as the imitation reward.
TARGET_SPEED = 0.10        # m/s. resid line: match the scripted wkF's own open-loop pace (~0.10).
FAC_SPEED = 5.0            # weight on the speed-tracking bonus. r1: 2.0 was too weak -- the policy stalled the gait to 0.03 m/s (a third of wkF). Back up + a floor penalty below MIN_SPEED so the walk cannot be smothered.
SPEED_SHARPNESS = 1.8      # wider capture band so the bonus still has a meaningful gradient when the policy is slow. Error is relative to TARGET_SPEED, so this is scale-free.
SPEED_WINDOW = 12          # steps to average base-x velocity over for the reward (per-step Δx is too noisy)
MIN_SPEED = 0.085          # m/s. Hard floor, suspended while wobbling (tilt < BALANCE_TILT_ON). surv_r12 config. gait-polish G1 tried 0.090 to clear the flat-speed gate (0.080->0.085) -- but survival crashed 21%->11% and trot -0.55->-0.43. Not worth 0.005 m/s. The 0.080 flat speed stands as a minor accepted shortfall.
FAC_MIN_SPEED = 120.0      # weight on the below-MIN_SPEED shortfall
MOVEMENT_CAP_AT_TARGET = True   # surv_r1: back to True. resid_r1's stall was FAC_SPEED=2 + no floor; now FAC_SPEED=5 + MIN_SPEED floor + FAC_OVERSPEED make speed a set-point, so the progress reward should stop paying above TARGET_SPEED.
FAC_STABILITY = 0.1       # Punish body roll and pitch velocities. rtune_r2 tried 0.4 -- over-damped the correction layer: falls 14->21% at 50mm, yaw 8->13deg. Reverted.
FAC_YAW = 0.1             # Punish body yaw (turning) velocity -- discourages curving off a straight line. rtune_r2 tried 0.3 with FAC_STABILITY 0.4 -- regressed, reverted.
FAC_HEADING = 5.0         # Punish absolute heading error (accumulated yaw away from straight-ahead). FAC_YAW penalizes turn *rate*; nothing pulled accumulated heading back to 0, so v6's gait drifted ~12 deg off straight by episode end. auto_iter1 tried 0.5 -- far too weak (~1% of the forward reward), no effect. auto_iter2: 5.0 (~7% of forward reward at a 13 deg drift). Yaw is recoverable from the base quaternion already in the observation, so no observation-space change.
FAC_Z_VELOCITY = 0.0      # Punish z movement of body
FAC_SLIP = 0.01           # Punish slipping of paws -- was 0.0; enabled to discourage dragging/jittering feet instead of real steps
FAC_ARM_CONTACT = 0.01    # Punish crawling on arms and elbows
FAC_SMOOTH_1 = 0.3        # Punish jitter and vibrational movement, 1st order -- was 1.0; halved because it directly penalizes joint-angle-change magnitude, which was fighting against bigger, more deliberate leg swings (v5 produced fast but very small-stepped movement on all four legs). FAC_JITTER still targets direction-reversal specifically, so genuine oscillation should stay in check.
FAC_SMOOTH_2 = 0.3        # Punish jitter and vibrational movement, 2nd order -- was 1.0; see FAC_SMOOTH_1 note above
FAC_CLEARANCE = 0.1       # Factor to enfore foot clearance to PAW_Z_TARGET -- was 0.0; enabled to reward lifting feet during swing phase
PAW_Z_TARGET = 0.020      # Target height (m) of paw during swing phase. v6: 15mm (was 5mm before that). auto_iter3: 25mm -- after FAC_HEADING=5.0 the policy went front-heavy and let the back feet drag at ~10mm; FAC_CLEARANCE penalizes squared deviation from this target both ways, so raising it pushes the dragging back feet up hard while easing the over-high front feet. Matches what v6 actually achieved (~23mm).
FAC_JITTER = 0.1          # Punish joints reversing direction frame-to-frame (adapted from bmabsout/opencat-gym's change_direction idea) -- discourages jittering/shuffling in place instead of real steps
FAC_STRIDE = 0.0         # Reward per-foot forward distance between consecutive ground contacts (touchdown->touchdown = real stride length). Cannot be gamed by fast air-flicks like Run 4's swing-velocity version. Added in Run 5 iter3 to counter domain randomization's pull toward a timid tiny-step shuffle. First guess -- tune.
FAC_GAIT_SYMMETRY = 3.5   # Reward a diagonal trot pattern: front-right+back-left swinging together, opposite to front-left+back-right, like a real quadruped. Applied unramped (not scaled by PENALTY_STEPS) so this shapes gait structure from step 1, rather than risking the policy settling into a different pattern early and getting disrupted later (the mechanism behind full_run_v1's late-training collapse). v6 and earlier: 2.0. auto_iter4: raised to 3.5 after auto_iter3 (PAW_Z_TARGET bump) loosened the trot to -0.45 correlation; a crisper diagonal trot is also left/right symmetric, so this should tighten heading drift too.
FAC_IMITATION = 10.0     # Reward matching Bittle's built-in `wkF` walk gait (reference_gait/wkf_ref.npy, 100 phase-frames aligned to TIME_PHASE_PERIOD). DeepMimic-style: exp(-IMITATION_SHARPNESS * sum sq per-joint error), in [0,1]. Dense 8-joint target -- a much stronger, less-gameable gait signal than FAC_GAIT_SYMMETRY / FAC_STRIDE. Default 0; enable HEAVY (~20-40) for imitation runs so the policy mimics wkF while adapting only as much as staying upright forces. Verified: open-loop playback walks the URDF +0.48m without falling, direct joint mapping, no sign flips.
IMITATION_SHARPNESS = 2.0 # higher = stricter match required for the same reward
IMITATION_TILT_FADE = 0.6  # rad; above this tilt (prev step) the imitation reward is scaled down so it doesn't fight a recovery
IMITATION_FADE_FACTOR = 1.0 # imitation reward multiplier while stumbling

# --- Fall recovery / self-righting -------------------------------------------
# Normally is_fallen() (roll or pitch > 1.3 rad) ends the episode instantly with
# reward 0, so the policy never sees a single timestep past tipping over and has
# no signal for how to get back up. With FAC_RECOVERY > 0, a fall instead opens a
# recovery window: keep stepping, replace the walking reward with a shaped reward
# for driving roll/pitch back toward level and lifting the body off the ground.
# Get both |roll| and |pitch| back under RECOVERY_UPRIGHT_RAD for
# RECOVERY_HOLD_STEPS steps in a row -> "recovered": collect a bonus and resume
# normal walking rewards. Window runs out still down, or tilt passes
# RECOVERY_ABORT_RAD (hopeless) -> terminate with reward 0 (the old outcome, just
# delayed). FAC_RECOVERY = 0 restores the legacy instant-terminate behavior.
FAC_RECOVERY = 0.0          # post-fall recovery window. R2 & R3 both proved a force-limited flat quadruped CANNOT self-right from >1.3 rad (0% recovered at FAC_RECOVERY 8 and 22, denser reward, eased criteria, pushes off, boosted torque). Disabled from R4 on -> legacy instant-terminate at 1.3. Replaced by FAC_BALANCE (always-on stumble-catch). Window code kept but dormant.
FAC_BALANCE = 4.0           # dense "fight back toward level" reward while STUMBLING (tilt > BALANCE_TILT_ON but not yet fallen). surv_r1: 2.0 -> 4.0 -- at 2.0 (through rtune_r4) it never produced an active big-stumble save (big_stumble_recovery_rate stuck at 0). The survive-what-scripted-can't loop needs the save to pay.
FAC_SURVIVE_BONUS = 12.0    # one-shot reward at episode end IF not fallen, scaled by how rough the episode was -- factor = clip((peak_tilt - BALANCE_TILT_ON) / (1.3 - BALANCE_TILT_ON), 0, 1). surv_r2: 40 -> 12 -- this terminal lump gave no gradient for a mid-episode save (paid 0 if the episode ended in a fall); demoted to a small "finished upright after a rough one" cherry. The dense per-step term below carries the load now.
FAC_SURVIVE_STEP = 6.0     # surv_r2: DENSE per-step reward for a step held upright while near tipping -- continuous "stay up one more step" gradient, the real "reward the save". surv_r3 tried RAMPING it (gutted the magnitude, 25%->11%); surv_r4 tried cutoff 0.7 (no gain). surv_r5: back to surv_r2 exactly -- flat 6.0, cutoff 0.8.
SURVIVE_BAND_LO = 0.8      # rad; below this = normal wobble (no credit), above = near tipping, every held step pays FAC_SURVIVE_STEP flat up to the 1.3 fall line.
BALANCE_TILT_ON = 0.5       # rad; balance-catch reward active above this tilt
# Run 7 balance shaping: reward reducing the tilt ANGLE, reducing the tilt RATE
# (damping the wobble, not just the lean), and planting more feet while tilted.
BALANCE_W_ANGLE = 1.0      # weight on frame-to-frame tilt-angle reduction
BALANCE_W_RATE = 0.6       # weight on tilt-rate reduction (damping). R3: 0.6 -> 1.0 -- emphasise killing the wobble's velocity, not just leaning back.
BALANCE_W_FEET = 0.15     # weight on (paws in contact / 4) while tilted -- "get feet down"

# Phase clock (Run 7): the wkF phase index normally advances one step per control
# step. While the body is tilted past PHASE_SLOW_TILT it advances at PHASE_SLOW_RATE
# instead, so a stumbling policy isn't told "you must be at stride phase X now" and
# isn't hit by the imitation penalty for being off-beat -- it can take a corrective
# off-phase step and re-sync once level. Both time_obs and the imitation reference
# read this same counter.
PHASE_SLOW_TILT = 0.6      # rad
PHASE_SLOW_RATE = 1.0      # R2: pause DISABLED (1.0 = phase always advances normally). R1's pause also froze the imitation reference during a wobble, making the imitation reward fight the catch; revisit with a fixed clock + reduced imitation weight instead.

# Impulse "recovery drills" (Run 7): in addition to the small continuous nudges
# (RANDOM_PUSH), deliver an occasional LARGE base-velocity kick at a random gait
# phase and direction -- concentrated practice in the big-wobble regime R5 fails.
IMPULSE_PUSH = 0.55      # m/s kick magnitude. surv_r1: 0.4 -> 0.55 -- the survive-what-scripted-can't loop needs the policy to actually practise big saves; 0.55 = recoverable big wobbles without the 0.7 fall-storm (prior-loop finding).
IMPULSE_PUSH_PROB = 0.006  # per-step probability (~1.5x per 250-step episode). surv_r1: 0.003 -> 0.006.

# --- Adaptive push curriculum (surv_r12, from PA-LOCO) ---------------------
# Per-env: track the last ADAPT_WINDOW episode outcomes; scale the impulse
# magnitude up when the policy is surviving most of them, down when it isn't.
# The policy masters the catchable range before the pushes escalate, instead of
# facing full-strength kicks from the moment the fixed DR ramp completes.
ADAPTIVE_PUSH = True
ADAPT_WINDOW = 12          # episodes averaged
ADAPT_UP_RATE = 0.75      # survive-rate above this -> harder
ADAPT_DOWN_RATE = 0.40    # below this -> easier
ADAPT_STEP = 0.12         # curriculum multiplier change per adjustment
ADAPT_MIN, ADAPT_MAX = 0.35, 1.70   # bounds on the multiplier

# --- Scripted mid-walk push reflex (surv_r13, from the firmware's --------
# IMU_EXCEPTION_PUSHED, which the real firmware only runs while standing).
# On a roll spike, blend a brace-and-lean bias into the joint targets for a
# short window -- crouch/widen all four, prop the falling side, tuck the rising
# side. Layered UNDER the residual policy: joint = wkF(phase) + reflex + action.
MIDWALK_PUSH_REFLEX = False  # surv_r13 REJECT: trained-in it was a wash (21%=surv_r12) and dropped trot below the gate. Off again.
REFLEX_TRIGGER_ROLL = 0.35   # rad -- engage above this |roll|
REFLEX_TRIGGER_RATE = 2.5    # rad/s -- or this |roll rate|
REFLEX_WINDOW = 16           # control steps the bias is applied (linear decay)
REFLEX_BRACE_DEG = 9.0       # crouch/widen on all four legs
REFLEX_LEAN_DEG = 7.0        # asymmetric prop toward the fall
RECOVERY_WINDOW_STEPS = 120 # steps allowed to right itself before giving up
RECOVERY_UPRIGHT_RAD = 0.7  # both |roll| and |pitch| under this = upright again. R3: 0.5->0.7 so partial recoveries count and build a learning gradient.
RECOVERY_HOLD_STEPS = 3     # consecutive upright steps to count as recovered. R3: 5->3 -- being pushed made holding 5 too hard.
RECOVERY_ABORT_RAD = 2.4    # tilt past this = hopeless, terminate now
RECOVERY_RESUME_STEPS = 60  # walking steps guaranteed AFTER righting itself, so the
                            # policy is rewarded for getting back into the wkF gait,
                            # not just for standing up. A fall extends the episode's
                            # step budget by (window + resume) rather than eating the
                            # walking budget; total episode capped at 2x EPISODE_LENGTH.

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
RANDOM_FRICTION = 0.30   # +/- fraction on ground lateral friction, per episode. surv_r1: 0.22 -> 0.30.
RANDOM_MASS = 0.18       # +/- fraction on every robot link mass, per episode. surv_r1: 0.10 -> 0.18 -- the policy needs to see real inertia variation to learn to compensate for it (~= the Pi+PiSugar payload swing).
RANDOM_PUSH = 0.2       # random horizontal shove: max instantaneous base-velocity kick (m/s) -- the small continuous nudge. The big concentrated hits come from IMPULSE_PUSH (Run 7).
RANDOM_PUSH_PROB = 0.02  # per-step probability of a shove
RANDOM_TERRAIN = 0.045   # obstacle max height (m). R2: 0.045 -> 0.03 (back to R5) -- the 45mm plateau + 0.7 impulse gave R1 a 25% FLAT fall rate. Re-raise once the base gait is solid again.
DR_EVAL_FULL = False     # eval sets this True -> dr = 1 regardless of step count

# --- Environment-coverage scenarios (gait-polish "coverage" loop) ----------
# Each a DR knob, default 0/off. The loop turns them on one at a time and they
# accumulate. Scaled by self._dr like the rest. Benchmark cells in
# benchmark_gaits.py exercise each with the knob forced on.
SLOPE_MAX_DEG = 10.0      # coverage R1: per-episode ground tilt, random roll & pitch in +/- this (deg), scaled by _dr
SLOPE_FIXED_RP = None     # benchmark-only: (roll_rad, pitch_rad) forces a deterministic ground tilt (overrides the random draw)
START_POSE_JITTER = 0.0   # deg of gaussian noise on the reset joint angles + a small base tilt
STUCK_FOOT_PROB = 0.0     # per-step prob of jamming one leg joint (holds its angle) for STUCK_FOOT_STEPS
STUCK_FOOT_STEPS = 12
SUSTAINED_FORCE = 0.0     # N: a held horizontal push, random direction, applied for SUSTAINED_FORCE_STEPS
SUSTAINED_FORCE_PROB = 0.004
SUSTAINED_FORCE_STEPS = 25
DEFORM_GROUND = 0.3     # coverage R2: 0..1 randomize ground contact stiffness/damping/restitution (indoor floor: hardwood/tile/thin carpet)
SLIP_PATCH = 0.35       # coverage R2: 0..1 fraction of episodes with a random low-friction patch on the floor

LENGTH_RECENT_ANGLES = 3  # Buffer to read recent joint angles
LENGTH_JOINT_HISTORY = 30 # Number of steps to store joint angles.
LENGTH_TILT_HISTORY = 12  # Run 7: steps of (roll, pitch) history in the observation -- lets the policy see a stumble as a developing trajectory, not a snapshot. IMU-only, transfers to hardware.

# Size of observation space:
# [ 30*8 joint history | quaternion(4) gyro(2) time_phase(1)
#   | 12*2 tilt history | roll/pitch angular-accel(2) ]      (Run 7 adds the last two)
SIZE_OBSERVATION = LENGTH_JOINT_HISTORY * 8 + 6 + 3 + 1 + LENGTH_TILT_HISTORY * 2 + 2  # +3 = proj_gravity (surv_r12)


class OpenCatGymEnv(gym.Env):
    """ Gymnasium environment (stable baselines 3) for OpenCat robots.
    """

    metadata = {'render.modes': ['human']}

    def __init__(self):
        self.step_counter = 0
        self.step_counter_session = 0
        self._dr = 0.0            # domain-randomization ramp for the current episode
        self._push_curr = 0.55   # adaptive push-magnitude multiplier (surv_r12)
        self._ep_outcomes = []   # last few episodes: 1 survived to length, 0 fell
        self._reflex_timer = 0   # scripted mid-walk push reflex (surv_r13)
        self._stuck_joint = -1   # coverage loop: index of a currently-jammed leg joint (-1 = none)
        self._stuck_timer = 0
        self._stuck_angle = 0.0
        self._sforce_timer = 0   # sustained-force perturbation
        self._sforce_vec = (0.0, 0.0)
        self._slope_rp = (0.0, 0.0)
        self._reflex_dir = 0.0
        self._reflex_on = MIDWALK_PUSH_REFLEX   # per-instance override -- benchmark_gaits.py
                                                 # sets this so the reflex applies only to the
                                                 # controller under test, never to the scripted
                                                 # baseline it's compared against.
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

    def _record_outcome(self, survived: int) -> None:
        """Adaptive push curriculum (surv_r12): once ADAPT_WINDOW episodes are in,
        nudge the per-env push multiplier up if the policy is mostly surviving,
        down if it's mostly falling. Persists across resets within this env."""
        if not ADAPTIVE_PUSH:
            return
        self._ep_outcomes.append(survived)
        if len(self._ep_outcomes) < ADAPT_WINDOW:
            return
        rate = sum(self._ep_outcomes) / len(self._ep_outcomes)
        if rate >= ADAPT_UP_RATE:
            self._push_curr = min(ADAPT_MAX, self._push_curr + ADAPT_STEP)
        elif rate <= ADAPT_DOWN_RATE:
            self._push_curr = max(ADAPT_MIN, self._push_curr - ADAPT_STEP)
        self._ep_outcomes = self._ep_outcomes[ADAPT_WINDOW // 2:]  # slide the window

    def step(self, action):
        p.configureDebugVisualizer(p.COV_ENABLE_SINGLE_STEP_RENDERING)
        # Random horizontal shove (perturbation robustness / balance recovery).
        if (RANDOM_PUSH > 0 and self._dr > 0 and not self._in_recovery
                and np.random.rand() < RANDOM_PUSH_PROB):
            lin, ang = p.getBaseVelocity(self.robot_id)
            dv = np.random.uniform(-RANDOM_PUSH, RANDOM_PUSH, 2) * self._dr
            p.resetBaseVelocity(self.robot_id,
                                [lin[0] + dv[0], lin[1] + dv[1], lin[2]], ang)
        # Impulse "recovery drill" (Run 7): occasional large kick, random
        # direction, at whatever gait phase it lands on -- concentrated practice
        # in the big-wobble regime.
        if (IMPULSE_PUSH > 0 and self._dr > 0 and not self._in_recovery
                and np.random.rand() < IMPULSE_PUSH_PROB):
            lin, ang = p.getBaseVelocity(self.robot_id)
            theta = np.random.uniform(0, 2 * np.pi)
            mag = IMPULSE_PUSH * self._dr * (self._push_curr if ADAPTIVE_PUSH else 1.0)
            p.resetBaseVelocity(self.robot_id,
                                [lin[0] + mag * np.cos(theta),
                                 lin[1] + mag * np.sin(theta), lin[2]], ang)
        # Sustained directional force (coverage loop): a held push over a window.
        if SUSTAINED_FORCE > 0 and self._dr > 0 and not self._in_recovery:
            if self._sforce_timer == 0 and np.random.rand() < SUSTAINED_FORCE_PROB:
                a = np.random.uniform(0, 2 * np.pi)
                self._sforce_vec = (np.cos(a), np.sin(a))
                self._sforce_timer = SUSTAINED_FORCE_STEPS
            if self._sforce_timer > 0:
                f = SUSTAINED_FORCE * self._dr
                p.applyExternalForce(self.robot_id, -1,
                                     [self._sforce_vec[0] * f, self._sforce_vec[1] * f, 0.0],
                                     [0, 0, 0], p.LINK_FRAME)
                self._sforce_timer -= 1
        # Stuck foot (coverage loop): jam one leg joint at its current angle.
        if STUCK_FOOT_PROB > 0 and self._dr > 0 and not self._in_recovery:
            if self._stuck_timer == 0 and np.random.rand() < STUCK_FOOT_PROB:
                self._stuck_joint = int(np.random.randint(0, 8))
                self._stuck_angle = float(p.getJointState(
                    self.robot_id, self.joint_id[self._stuck_joint])[0])
                self._stuck_timer = STUCK_FOOT_STEPS
        last_position = p.getBasePositionAndOrientation(self.robot_id)[0][0]
        joint_angs = np.asarray(p.getJointStates(self.robot_id, self.joint_id),
                                                   dtype=object)[:,0].astype(float)
        if RESIDUAL_MODE and WKF_REF is not None:
            # policy modulates the scripted wkF pose; action=0 -> open-loop wkF
            ref = WKF_REF[int(self._phase) % len(WKF_REF)]
            joint_angs = ref + action * np.deg2rad(RESIDUAL_SCALE_DEG)
        else:
            ds = np.deg2rad(STEP_ANGLE) # Maximum change of angle per step
            joint_angs += action * ds # Change per step including agent action

        # Scripted mid-walk push reflex (surv_r13): trigger on a roll spike, then
        # blend a brace-and-lean bias under the policy for REFLEX_WINDOW steps.
        if self._reflex_on and not self._in_recovery:
            _q = p.getBasePositionAndOrientation(self.robot_id)[1]
            _roll = p.getEulerFromQuaternion(_q)[0]
            _rr = p.getBaseVelocity(self.robot_id)[1][0]
            if self._reflex_timer == 0 and (abs(_roll) > REFLEX_TRIGGER_ROLL
                                            or abs(_rr) > REFLEX_TRIGGER_RATE):
                self._reflex_timer = REFLEX_WINDOW
                self._reflex_dir = float(np.sign(_roll if abs(_roll) > 0.1 else _rr))
            if self._reflex_timer > 0:
                d = self._reflex_timer / REFLEX_WINDOW          # linear decay
                brace = np.deg2rad(REFLEX_BRACE_DEG) * d
                lean = np.deg2rad(REFLEX_LEAN_DEG) * d * self._reflex_dir
                # URDF idx 0 FLsh,1 FLel,2 FRsh,3 FRel,4 BRhip,5 BRkn,6 BLhip,7 BLkn
                joint_angs = joint_angs + np.array([
                    brace - lean, brace, brace + lean, brace,    # front L / R
                    brace + lean, brace, brace - lean, brace])   # back  R / L
                self._reflex_timer -= 1

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

        # Stuck foot (coverage loop): hold the jammed joint at its captured angle.
        if self._stuck_timer > 0 and 0 <= self._stuck_joint < 8:
            joint_angs[self._stuck_joint] = self._stuck_angle
            self._stuck_timer -= 1

        # Set new joint angles
        p.setJointMotorControlArray(self.robot_id,
                                    self.joint_id,
                                    p.POSITION_CONTROL,
                                    joint_angs,
                                    forces=np.ones(8)*(0.5 if self._in_recovery else 0.2))
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
        # roll/pitch angular acceleration (Run 7 observation) -- ANG_FACTOR-scaled
        # like the rates, clipped to [-1, 1].
        ang_acc = np.clip((state_vel_raw[0:2] - self._prev_ang_vel) * ANG_FACTOR, -1.0, 1.0)
        self._prev_ang_vel = state_vel_raw[0:2].copy()
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
        # Cyclical time/phase signal. The phase index advances one step per
        # control step, but slows to PHASE_SLOW_RATE while the body WAS tilted
        # last step (self._prev_tilt), so a stumbling policy isn't forced onto
        # the stride beat and isn't hit by the imitation penalty for stepping
        # off-phase to catch itself -- it re-syncs once level. time_obs and the
        # wkF imitation reference both read self._phase.
        self._phase += PHASE_SLOW_RATE if self._prev_tilt > PHASE_SLOW_TILT else 1.0
        time_obs = np.fmod(self._phase / TIME_PHASE_PERIOD, 1.0)
        # IMU noise: noise only what the policy SEES, not the reward. The real
        # BiBoard IMU is noisy/biased; a policy trained on perfect orientation
        # can oscillate on real data.
        obs_ang, obs_vel_clip = state_ang, state_vel_clip
        gyro_n = RANDOM_GYRO * self._dr if (RANDOM_GYRO > 0 and self._dr > 0) else 0.0
        if gyro_n:
            obs_ang = np.array(state_ang) + np.random.normal(0.0, gyro_n, 4)
            obs_vel_clip = np.clip(state_vel_clip + np.random.normal(0.0, gyro_n, 2), -1, 1)
            ang_acc = np.clip(ang_acc + np.random.normal(0.0, gyro_n, 2), -1, 1)
        # Tilt history (Run 7): last LENGTH_TILT_HISTORY steps of (roll, pitch),
        # normalised so the fall threshold (1.3 rad) is +/-1. Same IMU noise.
        tnorm = np.clip(state_ang_euler / 1.3, -1.0, 1.0)
        if gyro_n:
            tnorm = np.clip(tnorm + np.random.normal(0.0, gyro_n, 2), -1.0, 1.0)
        self.tilt_history = np.append(self.tilt_history, tnorm)
        self.tilt_history = np.delete(self.tilt_history, np.s_[0:2])
        _rot = np.asarray(p.getMatrixFromQuaternion(obs_ang)).reshape(3, 3)
        proj_grav = np.clip(_rot.T @ np.array([0.0, 0.0, -1.0]), -1.0, 1.0)  # gravity in body frame
        self.state_robot = np.concatenate((obs_ang, obs_vel_clip, proj_grav, [time_obs],
                                           self.tilt_history, ang_acc))
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
            ref = WKF_REF[int(self._phase) % len(WKF_REF)] / self.bound_ang
            imit_err = np.sum((joint_angs - ref) ** 2)
            imitation_reward = np.exp(-IMITATION_SHARPNESS * imit_err)
            # R3: fade the imitation reward while stumbling (prev-step tilt over
            # IMITATION_TILT_FADE) so matching wkF stops fighting a recovery --
            # FAC_BALANCE takes over. The R1 phase-pause tried to do this by
            # freezing the reference and destabilised the gait; this is the
            # gentler version (clock keeps running, weight drops).
            if self._prev_tilt > IMITATION_TILT_FADE:
                imitation_reward *= IMITATION_FADE_FACTOR

        # Balance-catch reward (Run 7 shaping): while the body is stumbling
        # (BALANCE_TILT_ON < tilt < fall threshold), pay for (a) reducing the
        # tilt ANGLE frame-to-frame, (b) reducing the tilt RATE -- damping the
        # wobble, not just leaning back -- and (c) having feet planted. Dense,
        # always on: trains catching a wobble before it becomes a fall (R2/R3
        # showed a force-limited flat quadruped can't recover past 1.3 rad).
        tilt = float(np.max(np.abs(state_ang_euler)))
        self._peak_tilt = max(self._peak_tilt, tilt)
        tilt_rate = abs(tilt - self._prev_tilt)
        # surv_r2/r4: dense survival credit -- flat FAC_SURVIVE_STEP for every step
        # held upright in the near-tipping band (SURVIVE_BAND_LO..1.3 rad).
        survive_step_reward = FAC_SURVIVE_STEP if SURVIVE_BAND_LO < tilt < 1.3 else 0.0
        balance_reward = 0.0
        if FAC_BALANCE > 0 and BALANCE_TILT_ON < tilt < 1.3:
            balance_reward = FAC_BALANCE * (
                BALANCE_W_ANGLE * max(0.0, self._prev_tilt - tilt)
                + BALANCE_W_RATE * max(0.0, self._prev_tilt_rate - tilt_rate)
                + BALANCE_W_FEET * (sum(paw_contact) / 4.0))
        self._prev_tilt_rate = tilt_rate
        self._prev_tilt = tilt

        # Target-speed tracking bonus (Run 7): [0,1] * FAC_SPEED, peaking at
        # TARGET_SPEED, from a base-x velocity averaged over SPEED_WINDOW steps
        # (per-step Δx is too noisy). Relative error -> scale-free sharpness.
        self._x_window.append(current_position)
        if len(self._x_window) > SPEED_WINDOW + 1:
            self._x_window.pop(0)
        if len(self._x_window) >= 3:
            vx_est = ((self._x_window[-1] - self._x_window[0])
                      / ((len(self._x_window) - 1) / CONTROL_HZ))
        else:
            vx_est = 0.0
        # Hard floor: below MIN_SPEED, a steep linear penalty so the residual
        # policy cannot learn to stall the wkF walk (r1 failure mode).
        # surv_r5/r12: suspend the speed floor while wobbling -- slowing to catch a
        # stumble must not be punished. Active only when the body is ~upright.
        min_speed_penalty = (FAC_MIN_SPEED * max(0.0, MIN_SPEED - vx_est)
                             if tilt < BALANCE_TILT_ON else 0.0)
        overspeed_penalty = FAC_OVERSPEED * max(0.0, vx_est - TARGET_SPEED)
        speed_reward = FAC_SPEED * np.exp(
            -SPEED_SHARPNESS * ((vx_est - TARGET_SPEED) / TARGET_SPEED) ** 2)

        movement_forward = current_position - last_position
        # Forward-progress reward capped at the walk set-point: rewards progress
        # up to TARGET_SPEED's per-step displacement, nothing above, so it no
        # longer competes with the speed tracker. Backward motion still stings.
        capped_forward = (min(movement_forward, TARGET_SPEED / CONTROL_HZ)
                         if MOVEMENT_CAP_AT_TARGET else movement_forward)
        penalty_scale = self.step_counter_session / PENALTY_STEPS
        # Scripted-gait lessons (docs/rl-runs/gait-benchmark.md): keep feet on the ground
        # (duty factor), stay level (tilt^2), and -- in residual mode -- deviate
        # from the scripted pose only when it helps.
        duty_reward = FAC_DUTY * (sum(paw_contact) / 4.0)
        upright_penalty = FAC_UPRIGHT * tilt ** 2
        residual_cost = FAC_RESIDUAL_COST * float(np.mean(np.asarray(action) ** 2)) if RESIDUAL_MODE else 0.0
        if RESIDUAL_MODE:
            resid_smooth_cost = FAC_RESID_SMOOTH * float(
                np.mean(np.abs(np.asarray(action) - self._prev_action)))
        else:
            resid_smooth_cost = 0.0
        self._prev_action = np.asarray(action, dtype=float)
        reward = (FAC_MOVEMENT * capped_forward
                 + FAC_GAIT_SYMMETRY * gait_symmetry
                 + FAC_STRIDE * stride_reward
                 + FAC_IMITATION * imitation_reward
                 + speed_reward
                 + balance_reward
                 + survive_step_reward
                 + duty_reward
                 - residual_cost
                 - min_speed_penalty
                 - overspeed_penalty
                 - penalty_scale * (
                    smooth_movement + body_stability
                    + heading_penalty
                    + resid_smooth_cost
                    + upright_penalty
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
            "r_movement": FAC_MOVEMENT * capped_forward,
            "r_gait_symmetry": FAC_GAIT_SYMMETRY * gait_symmetry,
            "r_stride": FAC_STRIDE * stride_reward,
            "r_imitation": FAC_IMITATION * imitation_reward,
            "r_speed": speed_reward,
            "speed_mps": vx_est,
            "r_balance": balance_reward,
            "r_duty": duty_reward,
            "r_upright": -penalty_scale * upright_penalty,
            "r_residual_cost": -residual_cost,
            "r_resid_smooth": -penalty_scale * resid_smooth_cost,
            "r_min_speed": -min_speed_penalty,
            "r_overspeed": -overspeed_penalty,
            "r_survive_step": survive_step_reward,
            "r_survive_bonus": 0.0,
            "r_smooth_movement": -penalty_scale * smooth_movement,
            "r_body_stability": -penalty_scale * body_stability,
            "r_heading": -penalty_scale * heading_penalty,
            "r_paw_clearance": -penalty_scale * FAC_CLEARANCE * paw_clearance,
            "r_paw_slip": -penalty_scale * FAC_SLIP * paw_slipping**2,
            "r_arm_contact": -penalty_scale * FAC_ARM_CONTACT * self.arm_contact,
            "r_jitter": -penalty_scale * FAC_JITTER * jitter_penalty,
        }

        # Stop criteria of current learning episode:
        # step budget, or the robot fell (-> recovery window if FAC_RECOVERY > 0).
        self.step_counter += 1
        recovery_reward = 0.0
        if self.step_counter > self._step_budget:
            self.step_counter_session += self.step_counter
            terminated = False
            truncated = True
            self._record_outcome(1)                  # survived to episode length
            # surv_r1: survived to the end -> asymmetric bonus scaled by how rough
            # it got. Calm episode (peak_tilt <= BALANCE_TILT_ON) -> ~0; a near-tip
            # that was held -> full FAC_SURVIVE_BONUS.
            survive_factor = float(np.clip(
                (self._peak_tilt - BALANCE_TILT_ON) / (1.3 - BALANCE_TILT_ON), 0.0, 1.0))
            reward += FAC_SURVIVE_BONUS * survive_factor
            info["r_survive_bonus"] = FAC_SURVIVE_BONUS * survive_factor

        elif FAC_RECOVERY <= 0:
            if self.is_fallen():                     # legacy: fall = instant end
                self.step_counter_session += self.step_counter
                reward = 0
                terminated = True
                truncated = False
                self._record_outcome(0)              # fell

        else:
            # Recovery-window behavior. roll/pitch from the clean (un-noised)
            # base orientation already read this step (state_ang).
            rp = np.abs(p.getEulerFromQuaternion(state_ang)[:2])
            upright = 1.0 - np.clip((rp[0] + rp[1]) / (2 * 1.3), 0.0, 1.0)

            if not self._in_recovery and self.is_fallen():
                self._in_recovery = True            # just tipped over
                self._recovery_steps = 0
                self._recovery_hold = 0
                self._prev_upright = upright
                # give the episode room for the recovery detour + a resume, so a
                # fall doesn't cost normal walking practice (capped at 2x length)
                self._step_budget = min(
                    2 * EPISODE_LENGTH,
                    max(self._step_budget,
                        self.step_counter + RECOVERY_WINDOW_STEPS + RECOVERY_RESUME_STEPS))

            if self._in_recovery:
                self._recovery_steps += 1
                d_upright = upright - self._prev_upright   # progress toward level
                self._prev_upright = upright
                clearance_term = np.clip(base_clearance / 0.06, 0.0, 1.0)
                recovery_reward = FAC_RECOVERY * (
                    6.0 * d_upright + 0.30 * upright + 0.15 * clearance_term)
                reward = recovery_reward            # override walking reward while down

                if rp[0] < RECOVERY_UPRIGHT_RAD and rp[1] < RECOVERY_UPRIGHT_RAD:
                    self._recovery_hold += 1
                else:
                    self._recovery_hold = 0

                if self._recovery_hold >= RECOVERY_HOLD_STEPS:
                    reward += FAC_RECOVERY * 10.0    # righted itself -> bonus
                    recovery_reward = reward
                    self._recovered_count += 1
                    self._in_recovery = False
                    self._recovery_steps = 0
                    self._recovery_hold = 0
                    # guarantee walking steps after standing up so resuming the
                    # wkF gait (not just standing) gets rewarded
                    self._step_budget = min(
                        2 * EPISODE_LENGTH,
                        max(self._step_budget, self.step_counter + RECOVERY_RESUME_STEPS))
                elif (self._recovery_steps >= RECOVERY_WINDOW_STEPS
                      or float(np.max(rp)) > RECOVERY_ABORT_RAD):
                    self.step_counter_session += self.step_counter
                    reward = 0                       # out of time / hopeless
                    terminated = True
                    truncated = False

        info["r_recovery"] = recovery_reward
        info["recovering"] = 1.0 if self._in_recovery else 0.0
        if self._in_recovery:
            # walking-reward terms don't apply while it's righting itself
            for _k in ("r_movement", "r_gait_symmetry", "r_stride", "r_imitation"):
                info[_k] = 0.0

        self.observation = np.hstack((self.state_robot, self.angle_history))

        return (np.array(self.observation).astype(np.float32), 
                        reward, terminated, truncated, info)


    def reset(self, seed=None, options=None):
        self.step_counter = 0
        self.arm_contact = 0
        self._foot_prev_contact = [False, False, False, False]
        self._foot_td_x = [0.0, 0.0, 0.0, 0.0]
        # Fall-recovery window state (see FAC_RECOVERY).
        self._in_recovery = False
        self._recovery_steps = 0
        self._recovery_hold = 0
        self._prev_upright = 1.0
        self._prev_tilt = 0.0
        self._prev_tilt_rate = 0.0
        self._peak_tilt = 0.0            # surv_r1: roughest moment survived, for FAC_SURVIVE_BONUS
        self._recovered_count = 0
        # Run 7 state: gait-phase counter (slows under tilt), speed window,
        # tilt history, previous angular velocity for the accel observation.
        self._phase = 0.0
        self._prev_action = np.zeros(8)  # rtune_r4: for the residual-smoothness penalty
        self._reflex_timer = 0           # a fresh episode starts with no reflex active
        self._reflex_dir = 0.0
        self._x_window = []
        self._prev_ang_vel = np.zeros(2)
        self.tilt_history = np.zeros(LENGTH_TILT_HISTORY * 2)
        # Per-episode step budget; a fall extends it (see RECOVERY_RESUME_STEPS).
        self._step_budget = EPISODE_LENGTH
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
        # Slope: tilt the ground plane a few degrees, random roll & pitch (coverage loop).
        self._slope_rp = (0.0, 0.0)
        if SLOPE_FIXED_RP is not None:
            self._slope_rp = (float(SLOPE_FIXED_RP[0]), float(SLOPE_FIXED_RP[1]))
        elif SLOPE_MAX_DEG > 0 and self._dr > 0:
            m = np.deg2rad(SLOPE_MAX_DEG) * self._dr
            self._slope_rp = (np.random.uniform(-m, m), np.random.uniform(-m, m))
        plane_id = p.loadURDF("plane.urdf", [0, 0, 0],
                              p.getQuaternionFromEuler([self._slope_rp[0], self._slope_rp[1], 0]))
        if RANDOM_FRICTION > 0:
            p.changeDynamics(plane_id, -1, lateralFriction=max(0.1,
                1.0 + np.random.uniform(-RANDOM_FRICTION, RANDOM_FRICTION) * self._dr))
        if DEFORM_GROUND > 0 and self._dr > 0:
            k = DEFORM_GROUND * self._dr
            p.changeDynamics(plane_id, -1,
                             contactStiffness=float(np.random.uniform(3e4, 1e5) * (1 - 0.7 * k) + 1e5 * (1 - k)),
                             contactDamping=float(np.random.uniform(500, 3000) * (1 + k)),
                             restitution=float(np.random.uniform(0.0, 0.15 * k)))
        if SLIP_PATCH > 0 and self._dr > 0 and np.random.rand() < SLIP_PATCH:
            sx, sy = np.random.uniform(0.10, 0.45), np.random.uniform(-0.15, 0.15)
            patch = p.createMultiBody(
                0, p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.06, 0.09, 0.005]),
                basePosition=[sx, sy, 0.005])
            p.changeDynamics(patch, -1, lateralFriction=float(np.random.uniform(0.03, 0.18)))
        if RANDOM_TERRAIN > 0 and self._dr > 0:
            self._scatter_obstacles(RANDOM_TERRAIN * self._dr)

        _pose_tilt = 0.0
        if START_POSE_JITTER > 0 and self._dr > 0:
            _pose_tilt = np.deg2rad(0.3 * START_POSE_JITTER) * self._dr
        start_pos = [0, 0, 0.08]
        start_orient = p.getQuaternionFromEuler([
            self._slope_rp[0] + np.random.uniform(-_pose_tilt, _pose_tilt),
            self._slope_rp[1] + np.random.uniform(-_pose_tilt, _pose_tilt), 0])

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
        if START_POSE_JITTER > 0 and self._dr > 0:
            joint_angs = joint_angs + np.random.normal(
                0.0, np.deg2rad(START_POSE_JITTER) * self._dr, 8)
        self._stuck_timer = 0
        self._stuck_joint = -1
        self._sforce_timer = 0

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
        # self._phase is 0 here, so time_obs starts each episode at phase 0.
        time_obs = np.fmod(self._phase / TIME_PHASE_PERIOD, 1.0)
        _rot = np.asarray(p.getMatrixFromQuaternion(state_ang)).reshape(3, 3)
        proj_grav = np.clip(_rot.T @ np.array([0.0, 0.0, -1.0]), -1.0, 1.0)
        self.state_robot = np.concatenate((state_ang,
                                           np.clip(state_vel, -1, 1),
                                           proj_grav,
                                           [time_obs],
                                           self.tilt_history,      # all zeros at reset (level)
                                           np.zeros(2)))           # ang accel


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
        """Small static boxes/steps scattered in the robot's forward path --
        'obstacles to trip it up a bit', not walls. Amplitude (max_h) is scaled
        by the caller (dr ramp); the recovery loop raises it slowly per round.
        Deliberately kept passable: scattered (never spanning the lane), short
        along-path, so a decent gait clears most and only clips some -- the
        stumbles that give the FAC_RECOVERY reward its signal."""
        # Ground plane may be tilted (SLOPE_MAX_DEG). Place each box ON the sloped
        # surface -- height offset from the plane equation, orientation matched --
        # so nothing floats or half-buries. slope_rp = (0, 0) -> flat, as before.
        roll, pitch = getattr(self, "_slope_rp", (0.0, 0.0))
        n = np.array([np.sin(pitch) * np.cos(roll), -np.sin(roll),
                      np.cos(pitch) * np.cos(roll)])
        box_orn = p.getQuaternionFromEuler([roll, pitch, 0])
        for _ in range(np.random.randint(4, 10)):
            h = np.random.uniform(0.002, max(0.003, max_h))
            x = np.random.uniform(0.12, 1.3)
            y = np.random.uniform(-0.06, 0.06)
            z_ground = -(n[0] * x + n[1] * y) / n[2]   # plane through the origin
            cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[
                np.random.uniform(0.015, 0.045),  # along-path half-length
                np.random.uniform(0.04, 0.10),    # across-path half-width
                h / 2])
            p.createMultiBody(0, cs, basePosition=[x, y, z_ground + h / 2],
                              baseOrientation=box_orn)


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
