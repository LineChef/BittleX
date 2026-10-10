# Session handoff, 2026-10-09 night (read this first in a new session)

Times Eastern. Earlier: [`handoff-2026-10-09-evening.md`](handoff-2026-10-09-evening.md) (the V6 run while it trained), [`handoff-2026-10-09.md`](handoff-2026-10-09.md) (V4 evaluation, V5), [`handoff-2026-10-08.md`](handoff-2026-10-08.md).
Current truth about the robot: [`../STATUS.md`](../STATUS.md). **The next step is the hardware session: [`hardware-session-plan-2026-10-09.md`](hardware-session-plan-2026-10-09.md).**

## 1. Where things stand
- **Training is finished; nothing is running.** The V6 chain's 20M ended 10:50 PM, scored 11:02 PM (average of the last 5 checkpoints; log `trained/phase_v6.log`, "V6 COMPLETE"). Result: mean falls 0.215 (V4 0.189, scripted 0.216, V5 0.230); better on small step-ups (7.5-15 mm), about equal elsewhere, worse on slopes/tilts (secondary), the 25-35 mm step-up falls (V4 does not attempt them; neither crosses) and shoves. Rule fixed beforehand said NOT promoted; calm-walk asymmetry no longer gates (user: the calm walk is good enough).
- **The user then promoted V6 anyway (11:20 PM) and it is deployed to the Pi (11:23 PM)**, to be calibrated on hardware ("we will calibrate it on hardware now"). `DEFAULT_POLICY` = `Release_CandidateV6_ppo.onnx` (heading-blind, send every 3rd tick, scale 30). V6 has no trim yet; V4 (trim -0.2) and V3/V2.1 stay as fallbacks. Rollback: set `DEFAULT_POLICY` to the V4 file, `tools/g2_deploy_when_online.sh --once`.
- Pi: online, `g2-voice` active, deployed commit matches the repo. G2 rests on the user's desk.
- Reports: short V6 report https://claude.ai/artifact/P2CTwR8Z1KgCw8ccVtrRiK (private; the full statistics version is `trained/v6_report/report_full.html`, share only when asked), decisions page https://claude.ai/artifact/Xn8EbD6rQ6uki3XsLHmMEr.

## 2. Built this evening after the run (all committed and pushed)
- `tools/eta.py` (`plan`, `now`, `check`): read-only timing estimates from the trainer's console logs; use it for every training/benchmark estimate and quote "training done" and "verdict" clocks with its range; the runners' progress lines also project a finish time. Estimates were short because scoring/report time was left out and pace halves over a 20M run.
- `report_summary.py`: the short benchmark report (topic scorecard against a reference, one-line sentences, bars); `phase_v6.py` writes it as `report.html` and keeps the old one as `report_full.html`. Tests: `test_eta.py`, `test_v6.py`.
- `watch_live.py` (`g2watchrun`): real-speed playback, camera keeps the user's angle, readable overlay, exits with a plain message when no run is training (`--replay` for the last episode, `--fast` for the old mode).
- `promote_release.py` force-adds the ignored sidecar; the Pi yaw test is pinned to V4 and a new test checks a heading-blind policy is fed yaw 0.
- Plans written: the hardware session ([`hardware-session-plan-2026-10-09.md`](hardware-session-plan-2026-10-09.md)) and the periodic wall look ([`../vision/wall-check-plan.md`](../vision/wall-check-plan.md): one look per leg at the stand, next leg shortened to what was seen, built on the existing dry run).

## 3. User rules added tonight
- Hardware: no gait comparisons on G2 (sim only); no "in the air first": all testing on his feet, hands near.
- Promotion of V6 was the user's call against the sim rule; calm-walk asymmetry is reported, not gated.
- Still standing: no training on a consolidated 20M; ask before any download (security protocol); API calls sparingly; always rest G2 before stopping anything that controls him; clean up temp files; commit explicit paths.

## 4. Open items
- Hardware session (blocks 1-6 in the plan), V6 trim into `DEFAULT_TRIMS` afterwards.
- Back-left shoulder servo stiffer/louder (parked; no servo-feedback test possible without removing the Pi; sound sweep or video are the cheap checks).
- Wall: calibration, dry-run review, then (on the user's word) the per-leg look wired to the leg planner.
- Object recognition: first 5 labelled pictures per object, DINOv2-small threshold retune and Pi timing.
- Backlog ideas from tonight: no step-up above 7.5 mm is ever crossed by any policy (a fresh chain with the layer-2 rewards is available as levers only if the user asks); mode-trained hi step; why V4's tape path stays straighter than its body turn suggests; the API-cost jump (the Pi made almost no billed calls).
- The deploy watcher already ran (nothing armed now).
