# Hardware session plan, 2026-10-09 (user-run, Claude walks through it)

Why now: V4 (the deployed policy) has never walked on G2, the system-identification capture ([`sysid-capture-plan.md`](sysid-capture-plan.md)) was skipped twice, and V5's ledge cap (30 mm up and down)
needs real step-up and step-down data. G2 is charged. Training runs on the Mac meanwhile (the `real2sim.py --fit` waits for an idle Mac, after the 20M's report).

Rules: the user is the hands-on agent (G2 is held upright in the air for the first walk; never on its back). Ask the floor first and label it (`g2floor <label>`). Capture walks use `--foot-hold off`
(the heading hold changes the legs' motion); the everyday-behavior check uses the hold on. Real data sets sim numbers and scores; it never feeds drift.

| Part | What | Runs | About |
|---|---|---|---|
| 0 Setup | floor label; pack voltage at rest (write it down); deploy check; tape the lane (start spot + a 1.5 m line); know the halt (`python -m pi_pipeline.app --halt`) | - | 10 min |
| 1 First V4 walk | held upright in the air: `run_gait.py --cmd 0.10 --seconds 6` | 1 | 3 min |
| 2 V4 on the lane, hold on | the real behavior check (STATUS 0c): `--cmd 0.10 --seconds 12.5 --log ~/g2_runs/v4_a.csv` ; expect about 0.09 m/s and heading within about 10 deg | 3 | 10 min |
| 3 Capture A | hold off: 6 V4 walks and 6 scripted `wkF` walks alternating (`g2_baseline.sh start 12 sysidA --scripted-mix abab`); tape forward distance and sideways offset (cm, + = right) after every run | 12 | 30 min |
| 4 Ledges | a book at about 12 mm and one at about 25 mm, taped down, height by ruler. Step UP: 3 V4 runs into each; step DOWN: G2 starts on the book and walks off, 3 V4 runs each; 3 scripted runs at 12 mm each way for comparison. Note success, or where it caught | about 21 | 30 min |
| 5 Low pack (same day if time, else another day) | the 6 V4 walks again when the resting pack reads about 7.9 V | 6 | 15 min |
| 6 Bench servo tests (optional) | lid off, Mac USB: `tools/servo_static_test.py`, the H13 step test | - | 20 min |

Stop and tell Claude on: any fall (note the time), a servo that sounds or smells wrong, odd heating, the pack dropping fast. Not today: slopes (secondary), exploration pictures (a separate visit).

After: `bash tools/g2_baseline.sh fetch`, `g2data` (sync and ingest), Claude summarizes each part against the scripted walk (`tools/walk_log_summary.py`). Fits and V5 comparison wait for the idle Mac.
