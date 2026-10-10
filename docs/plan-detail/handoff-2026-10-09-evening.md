# Session handoff, 2026-10-09 evening (read this first in a new session)

Times Eastern. Earlier handoffs: [`handoff-2026-10-09.md`](handoff-2026-10-09.md) (V4 evaluation and the V5 run, complete), [`handoff-2026-10-08.md`](handoff-2026-10-08.md). Plan: [`v6-staged-training-plan.md`](v6-staged-training-plan.md)
(stage results, the S2 loophole, Layer 2 and Plan B, the alternate-gait design). Current truth about the robot: [`../STATUS.md`](../STATUS.md).

## 1. Right now
- **The V6 20M ("layer 1", tag `v6_s4`) is training** on the Mac (started 8:31 PM from the S3 weights, plateau stop on). It was at 10M at 9:26 PM and is due to finish about **10:25 PM**; then the runner picks the average of the last
  5 checkpoints, scores it on the full benchmark, exports `trained/V6cand_ppo.onnx` (not promoted, not deployed), and builds `trained/v6_report/report.html` and `compare.txt` (V6 / V5 / V4 / scripted), about 10:45 PM.
  Check: `cd rl_training/opencat-gym && ../../.venv/bin/python phase_v6.py status` and `tail -20 trained/phase_v6.log`. The watchdog (`tools/v6_watchdog.sh`) relaunches the runner; it stops on `trained/v6_halt` or "V6 COMPLETE".
  Publish the report as an Artifact when "REPORT ready" appears; tell the user the verdict in a few lines.
- **The user's decisions about it:** let it finish (do not stop early); promotion and deployment of any result are the USER's call; the 20M go/no-go was delegated to Claude and is used.
- **G2 and the Pi are off** (G2 charging). A **deploy watcher is armed** (`tools/g2_deploy_when_online.sh`, up to 24 h, deploys once when the Pi answers; `--cancel` disarms): it will ship everything committed (the exchange sounds, exploration changes, gait switching and the
  scripted hi step, the V4 trim). The V4 policy is the deployed default; V5 was not promoted.

## 2. What was done today (in order)
1. V4 evaluated, V5 planned and run (single fresh 20M): about equal to the scripted walk, worse than V4 on the same 31-cell benchmark (mean falls 0.230 against 0.189; scripted 0.216). Report published as an Artifact; V4 stays the default.
2. **First V4 hardware session on G2 (hardwood, 1/4 inch ramped threshold, data in `docs/rl/real-walk-data/2026-10-09/README.md`):** V4 walks at the commanded speed with no falls and less sway than the scripted walk; with the heading hold OFF it turns
   right about 60 deg in 12.5 s (the user judged by eye; the log reads about 100); the closed-loop front-foot hold overshot to 60 deg LEFT even at -0.9 authority; a constant front-left trim of -0.2 with the hold off ended within about 30 deg
   (12:15 / 11:55 / 11:00 by eye) and is now the V4 everyday default (`gait/heading_hold.py` DEFAULT_TRIMS, `G2_FOOT_TRIM`, hold off unless `G2_FOOT_HOLD=fl`); both walks cleared the 6.4 mm ramp 6 of 6. The scripted walk drifts about 8 in right with almost no yaw.
   Sim-versus-real replay: the sim sways about 30% less; first fit (servo speed, motor force, friction) is flat and NOT applied.
3. **Exploration and sound changes (committed, to be deployed):** rising "ba nun na NAAA" fanfare at the start (buzzer arpeggio, brass on the speaker); 7 s legs ending in the standing pose; rest only at the end of a session (stop, balance, then rest; `tools/g2_safe_stop.sh`);
   voice announces before the hand-over; picture stops at most every 60 s, only for something worth it (unknown or unfinished objects, never a person; slow 5 min fallback), camera prep only for the first picture and half way; no head gestures
   (`G2_HEAD=1` brings them back) and no recognition hop (`G2_EXCITED_HOP=1`), a short play bow at a find; wall-distance estimator logs only (dry run).
4. **Spoken exchange sounds:** beep at the wake word, boop when your words are captured, two falling notes when the follow-up window closes, short double beep when the gait switches. Speaker sounds play only on the Pi (`G2_SPEAKER_SOUNDS`), never in tests.
5. **Object recognition build** (plan `../vision/exploration-object-learning-plan.md`): foreground localizer, interest scoring, gallery feeder, held-out lock rule (15 pictures, every 5th held back, 90% recognized); MobileNetV2 fetched from the official ONNX Model Zoo under the download protocol
   (hash recorded) and first compared with the histogram baseline: no winner yet; needs more labelled pictures.
6. **Gait probes** (`rl_training/opencat-gym/gait_probe.py`, open loop): the high-step gaits gain clearance but lose stability; the stable one (hsF) reaches 17.8 mm and walks at under half speed; a symmetrized wkF changes nothing.
7. **Gait switching built** (`gait/gait_mode.py`): "hi step" / "walk normally" / "walk mode" from the voice loop and an exploration session; today hi step = the scripted hsF gait, experimental.
8. **V6 chain** (the live run; stage results in the plan doc). First S2 found a loophole (hovering with a paw raised) and was redone; S3 missed the mean-falls bar by 0.03 and I overrode it (forgetting on uphill, snags and rubble); the 20M started.

## 3. Standing decisions and rules from today (also in memory and the local CLAUDE.md)
- Scripted wkF stays the base and the comparison gait. Hi-step is not the default comparison gait; no hi-step base in Plan B.
- Falls first, success second; ledge target 25 mm, stretch 30 mm; slopes and tilts are secondary (scored, stop only on a large regression, 0.30); the calm-walk heading is judged against the scripted walk plus 3 deg (the user reverted the 0-deg idea).
- Always rest or stand G2 before stopping anything that controls him (`tools/g2_safe_stop.sh`, never a plain service stop mid-stride); never put G2 on his back.
- API calls sparingly, prefer local on the Pi; every download follows the security protocol and needs the user's yes first (official source, pinned, ONNX/safetensors only, own folder, hash, Mac first).
- Do not read replies aloud (the read-aloud idea was dropped).

## 4. What is left
1. **When the 20M finishes:** read the report and `compare.txt`; judge Layer 2 against the success criteria in the plan doc; build the `--chain-from` action-noise reset option and the stronger ledge stage; run Layer 2 (3-6M ledge stage, then 8-10M mixed); Plan B = an earlier layer-1 checkpoint. Promotion/deploy only on the user's word.
2. **Hardware (the user wants to discuss next):** deploy (watcher armed); hi step first held in the air, then on the floor; measure V6/V5's own turn with the hold off and set a trim; tile trim for V4; the taller threshold; low-pack repeat; bench servo tests; wall calibration (a box at 20/30/40/60/100 cm: `python -m pi_pipeline.vision.wall_distance calibrate`) then dry-run logs; first 5 labelled pictures per object; BiBoard low-battery alarm reading (the user will say when it sounds; the Pi's own "low battery" is only a runtime estimate).
3. **Open questions:** the object-recognition model choice (DINO-class needs another download and a yes); why V4's path stays near straight on tape while its body turns about 60 deg; the API cost jump (the Pi made almost no billed calls, so the cause is probably outside G2).

## 5. Pitfalls
- Never type a run's process text or tag in a shell command (`pgrep` matches your own shell). Stop things through the runner's helpers (`run_pipeline.stop`) or a python snippet.
- Tests must not make sound or call the API (conftest sets `G2_SPEAKER_SOUNDS=0`); scripts that call the benchmark need an `if __name__ == "__main__"` guard; `git add` explicit files, never a folder.
- Each progress line is 40 episodes and swings a lot (heading 12-34 deg, asymmetry 0.8-5.3 within a few lines): read trends over several lines, not one.
