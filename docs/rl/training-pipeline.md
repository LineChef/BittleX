# The training pipeline, end to end

How a walking policy goes from an idea to a file on G2, and the rules that govern each step. Code index: [`../../rl_training/README.md`](../../rl_training/README.md). Deploying: [`../guides/gait-deployment.md`](../guides/gait-deployment.md).

1\. Define what the sim models
-----------------------------

`g2_profile.py` is the single definition of "G2 as the sim should model it": the real control path (5 Hz IMU, firmware command timing), the measured payload and balance, IMU calibration, the course and its hazard shares, and the **levers** (named switches for each change to try). Training, every scorer and every viewer take their environment from it (`env_for_job`), so what you watch is what trains. Real-robot data refines it only through numbered calibration snapshots with approval gates ([`real-data-pipeline.md`](real-data-pipeline.md), `G2_CAL_ID`).

Every new mechanic in `opencat_gym_env.py` defaults off, so older checkpoints and scripts replay unchanged.

2\. Plan a chain
---------------

A chain is a plan plus a runner that carries it out unattended and stops only for a judgement call:

- V3: Runner: `phase_v3.py` (also the scoring code the others reuse); State: done
- V4 (screens, then a 20M): Runner: `phase_v4.py`; State: done, deployed
- V5: Runner: `phase_v5.py`; State: done, not promoted
- V6 (staged skills, then a 20M): Runner: `phase_v6.py`; State: done, deployed
- High-step creep: Runner: `phase_hs.py`; State: stopped, goal not met

The rules every plan follows: a fresh candidate each time; screens of at most 3M steps with two seeds per lever, judged on learnability and no flat-ground regression; a 20M only after `preflight.py` prints ALL PASS and only on explicit approval; difficulty capped by what a capable policy can pass (`passability_audit.py`); nothing trains on a consolidated 20M.

3\. Train
--------

`train.py` runs PPO over 6 environments with the per-hazard frontier curriculum, mirror-symmetry loss, a privileged critic (training only), health checks every 1M steps with automatic stops, a best-checkpoint eval, and a plateau stop with a learning-rate cool-down. Estimate the time before launching and quote a completion clock: `python tools/eta.py plan --steps 3e6 --tail stage`. Watch the run live with `watch_live.py` (`g2watchrun`), or replay its recorded episodes with `watch_training.py`.

4\. Score
--------

`benchmark_decathlon.py` and its V4 and V5 successors score a policy on a fixed ladder of cells (flat, slopes, ledges, rubble, boxes, snags, shoves, carpet, faults). Results use paired seeds so two policies are compared on the same episodes, with exact tests on falls (`paired_compare.py`, `final_exam.py`) and a calm-walk check over 12.5 s, which catches one-sided drift the 3 s cells cannot. Policies are scored through G2's real control path (`--hw i`). Reports: `report_summary.py` (short), `report_v5.py` (against the scripted walk).

5\. Export and validate
----------------------

`export_onnx.py` writes the ONNX file and its `.onnx.json` sidecar (residual scale, command cadence, heading-blind, modes). `verify_onnx.py` checks ONNX against the torch policy; `validate_deploy.py` drives the Pi-side `residual_policy.py` in lockstep with the sim and requires the observation, action and joint targets to match.

6\. Promote and deploy
---------------------

Promotion needs explicit approval (`promote_release.py`, or `tools/g2_promote_policy.sh TAG NAME`): the release is named `Release_Candidate<name>`, `DEFAULT_POLICY` is pointed at it, the tests run, and the deploy waits for the Pi. The previous release stays on the Pi as a fallback. Then test on G2 on his feet, hands near, with the trim for that policy ([`../guides/gait-deployment.md`](../guides/gait-deployment.md)).

7\. Feed real data back
----------------------

Every real walk is logged automatically on the Pi, gated into a store on the Mac, and turned into calibration snapshots; `real2sim.py` replays logged joint commands through the training environment to compare roll, pitch and sway frequency. Real data never feeds heading drift into a fit.

Housekeeping
------------

Intermediate checkpoints are not kept. A finished run keeps its final policy (`trained/<tag>_ppo.zip`), its console log and any small result files that back a decision (force-added to git). `python tools/g2_cleanup.py` lists scratch files; delete by exact path, never a wildcard over `trained/`, because the code reads switches from it.
