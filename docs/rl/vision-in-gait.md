# Vision-in-the-gait — closed campaign

> **The whole vision-navigation stack is flag-gated OFF on hardware.** The camera
> runs a household-recognition model, not an obstacle/edge detector — nothing on
> G2 perceives things in its path. Phase E's scripted skill-switching
> (`SkillSwitch` / `GaitSelector` / `CliffGuard` / `INSPECT`) showed sim-only
> gains but has no sensor to run on, and the auto-scan-on-obstacle idea tested
> **negative**. All of it is held behind **`features.vision`** (default `False`):
> `run_gait --skills` refuses without it; `BehaviorDriver(vision_available=False)`
> drops EXPLORE / recognition / cliff reflex / enrollment. Re-enable with
> `G2_FEATURES="+vision"` once a real forward sensor ships. See
> [`../vision/detection-layer.md`](../vision/detection-layer.md).

> **Campaign closed 2026-09-08.** Six phases (A–F). Turning is a sim-physics
> limit → firmware. Learned vision-in-the-policy was **ruled out** (Phase D A/B,
> plus a 3M retry). Scripted skill-switching on the frozen walk works in sim but
> needs a sensor. Climb is a sim-fidelity wall. `run20m_ppo` was untouched
> throughout; no 20M ever ran.

---

## Per-phase results

**Phases A / A-retune / C — goal-directed turning: NOT ACHIEVABLE in this sim.**
Three campaigns, zero turning each. Root cause (open-loop test): the scripted
OpenCat turn gaits (`wkL` / `wkR`) produce ~0° of yaw in this PyBullet URDF even
with no policy on top — real Bittle turning leans on foot-slip + a firmware gyro
turn-assist the sim contact model doesn't reproduce. A bounded residual on `wkF`
cannot express a sustained asymmetric gait. **→ turning goes to firmware**
(scripted `kbk` / `wkL` turn the real robot fine); the behaviour layer steers.

**Phase D — vision-in-the-loop A/B: RULED OUT.** The clean test — two fresh 20M
runs, identical cluttered course / R-NOSTALL reward / loosened `wkF` anchor, the
**only** difference a 4-float forward terrain feature in the obs (`abD_vision`
282-d vs `abD_blind` 278-d). Both trained cleanly, converged, 0 training falls.
`eval_obstacle_response` (40 ep, matched seeds): **falls tie at zero on every
cell; the seeing policy slows *less* on tall obstacles** (decel 0.83 vs 1.89) —
it ignored the feature and walked through at commanded speed. Per-term reward
near an obstacle: `r_obs_*` all 0.0, `r_nostall` −0.2 (the dense speed-track
penalty rewards *holding* commanded speed; the breakthrough bonus fired too
rarely to shape anything). Regression check: the feature cost nothing on
obstacle-free cells — it just bought nothing. **→ ship the `Avoider` speed reflex
on the frozen `run20m_ppo`.** `abD_vision` / `abD_blind` kept as checkpoints, not
adopted.

**`smoke_vfix3` — a 3M vision-conditioned retry: also fails.** With the Phase-D
scan fix + `r_obs_clear` on + `FAC_SPEED_TRACK` 60→25, the policy learned to
**creep at 0.025 m/s**, not step over (`ep_rew_mean` 524→193). Two data points
now — plow (Phase D) or stall (this). **Reward-shaping "see it → step over it"
into a bounded-residual policy is off the table.**

**Phase E — vision picks a SCRIPTED skill on the frozen walk (0 training).**
`run20m_ppo` stays frozen; a vision reading selects a `GaitMode` (cruise /
careful / step-over / back-out / brace / inspect / halt) and `SkillSwitch` plays
a scripted OpenCat keyframe with a phase-gated via-stance blend. Sim results:
**+48% farther through low obstacles** (5-seed sweep, step-over attributed ~6×),
**0% vs 34% edge-falls** with `CliffGuard` on drop-offs. Mixed course: safety
airtight, forward −29% because sim `HALT` = frozen (no turn layer). The catch:
**there is no sensor to drive it** — the camera is a recognition model, not an
obstacle/edge detector. Held behind `features.vision`. The auto-scan-on-obstacle
variant (INSPECT bow to get a better near read) tested **negative**.

**Phase F — learned CLIMB skill: sim-fidelity wall.** Full harness built
(`climb_env.py` / `train_climb.py` / `eval_climb.py` / `climbwatch`). Nothing
climbs a ≥ 2.5 cm ledge in PyBullet — not 6 scripted-base designs, not
from-scratch RL, not Petoi's own `cmh` keyframe, across standoff / torque /
friction sweeps. Front paw can't reach forward *and* up; body can't rear
> ~13°; `cmh` needs real foot-grip + a human in the loop. **Not a design gap —
a sim gap.** On-hardware path: port `cmh`, tune approach + keyframe on a real
step, then a residual policy on real IMU. The reusable output is the method
([`skill-learning-method.md`](skill-learning-method.md)), not a climb.

## What's built and left dormant

All on `development`, off by default — kept so a future run with real hardware
doesn't start from zero:

| Piece | What |
|---|---|
| `G2E_TERRAIN_FEATURE` | the 4-float forward scan in the sim obs (`opencat_gym_env._scan_terrain`), off by default |
| `G2E_GOAL_MODE` / `G2E_TRAIN_YAW` / `CLIFF` / `TURN_BLEND` | goal-bearing command, yaw curriculum, cliff feature, `wkF`→`wkL/wkR` blend — all dormant |
| `run20m_graft282/285/289` | grafted obs-width checkpoints (not adopted) |
| `benchmark_goal.py` / `eval_obstacle_response.py` / `gate_check.py` | the campaign's eval harness |
| `pi_pipeline/gait/skill_layer.py` | `SkillLayer` = `GaitSelector` + `SkillSwitch` + `CliffGuard`; `run_gait.py --skills` (serial Grove Vision feed or mock) |
| scripted skill refs | `STEP_OVER` (trot) / `BACK_OUT` (bk) / `HALT` / `CAREFUL` / `INSPECT` (buttUp bow) / `BRACE`, `reference_gait/*_ref.npy`, the `G2E_SKILL_REF` hook |
| `climb_env.py` + `train_climb.py` + `eval_climb.py` | the Phase F climb harness |

## What would reopen this

- **A real forward sensor** (depth / ToF / a mounted obstacle+edge detector) —
  the current camera can't drive any of it.
- The **adapter skill probe** ([`adapter-skill-probe-spec.md`](adapter-skill-probe-spec.md))
  is the reserved route for *one* genuinely-learned skill (frozen base + a small
  trained module) if a scripted one proves too fragile on hardware.
- A consolidation 20M with **skill-code-in-obs** (not a terrain feature), only
  post-hardware and only if H1 says the learned walk is worth extending.
