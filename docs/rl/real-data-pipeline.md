---
audience: contributor
kind: concept
---

# Real-hardware data pipeline: capture every run, feed the sim only what helps

This page specifies how G2's own runs become simulation calibration: every walk is captured automatically, filtered, fitted and, if the checks pass, used by the next training run. The governing rule is that only data that can help gait training reaches the simulator. Anything noisy or harmful is filtered, quarantined or left out, and the data is audited periodically. What a log carries is described in [Hardware walk logging](hardware-logging.md).

Design rules
------------

- Approval is automatic when every gate holds. Collection, sync, filtering and fitting are automatic, and a calibration snapshot is used by a retrain only once approved (see "Approval").
- The data store is outside the repository (`~/g2_data/` on the Mac). Only non-personal summaries are committed.
- Every policy walk is logged, including voice-triggered and exploration walking, not only direct runs.
- Everything is kept and compressed losslessly (gzip). A new hardware epoch is recorded whenever the hardware changes.

Flow
----

1. On the Pi, every movement path writes a raw CSV and a JSON sidecar to `~/g2_runs/auto/<date>/`. Commands: `g2floor [label]`, `g2floor status`, `g2floor epochs`.
2. A sync watcher pulls the runs to the Mac when the Pi is online. The Pi copy is deleted only after the Mac copy is verified.
3. The Mac store `~/g2_data/` holds the gzipped runs.
4. The ingest gates filter each run and quarantine the rest.
5. The calibration builder fits parameters, checks them for reproducibility and runs the harm check.
6. A snapshot is written (immutable, numbered), and approval is automatic or manual.
7. `g2_profile` loads the approved snapshot at retrain launch, and the run records its id.

What is captured
----------------

- Policy walking from the voice service and the exploration runtime: One choke point (`PolicyWalker` into `run_gait.run()` with no log path) auto-logs when no `--log` is given. `G2_AUTOLOG=off` disables it.
- Policy walks started from the command line or the baseline runner: Already logged with `--log`; the auto-log fills in when none is given.
- Scripted firmware gaits (`kwkF`, `kwkL`, `kwkR`, `kbkF`): Each run gets a `scripted_walk` sidecar with no CSV, so the ingest quarantines it and no fit ever reads it. The learned walks are tagged `policy_walk`.
- Scripted `wkF` open-loop walks: Run only from the command line, which already passes `--log`.
- Idle and rest IMU: A low-rate recorder is a later phase. IMU bias and noise at rest are plentiful data.
- Events (falls, guard stops, thermal cooldowns, battery alerts, pick-ups): Written to the event log and used for real fault and fall rates.

Every run gets a sidecar with its kind, policy name, commands, git commit, hardware epoch, surface label, battery at start and end, features on, and why the run ended.

Hardware epochs and surfaces
----------------------------

- Epoch: `pi_pipeline/telemetry/hardware_epochs.json` lists hardware changes (case mounted, servo replaced, and so on). Fits use the current epoch only. Older epochs are kept and never fed unless a person says so.
- Surface: A label (hardwood, tile, carpet, ...) set with one command and stored on the Pi with the time it was set. Every run records both. The label is changed whenever G2 moves to another floor (`g2floor hardwood`). Tile data is its own category and is never pooled with hardwood, and fits are per surface because friction differs.

Ingest gates
------------

Nothing is deleted. A run that fails a gate is quarantined with a reason code (`reason_codes` in `manifest.json`). A run is usable for fitting only if all of these hold:

- Not excluded: A person marks a run that must never be used (a collision, a pick-up) with `python -m pi_pipeline.telemetry exclude RUN WHY` on the Pi. The log is kept, and the sidecar records who, when and why.
- Complete and clean: The file is complete, time strictly increases, and the control loop is on time (dropped ticks under a limit).
- Sensors: IMU frames arrive with no long stale stretch, and there are no NaN or out-of-range values.
- Known context: The hardware epoch is current, the surface label is known and was set within the last 72 hours, the policy is known, and the length is above a minimum.
- Undisturbed window: There is no operator pick-up (accel or tilt spike) and no fall or guard trip inside the window used. Those runs still count for event rates.
- Battery: The pack is above the low-battery line, or the run is tagged by voltage band and never mixed with full-pack data.
- Steady state: The first seconds after the stand and thermal cooldown stretches are excluded.
- Statistical screen: A run whose metrics sit outside the epoch's median by more than k times the MAD is quarantined for review, not dropped.

Per-parameter rules in the builder require a minimum number of supporting runs, a fit on one half of the runs that holds on the other half (a value that moves more than its own noise is not used), physical bounds, and left-right symmetry for fitted parameters.

Gates apply per fit. Each run in `manifest.json` lists the kinds of fit it may feed in `uses`:
- `timing`: The loop-timing fits. These need a 1 s steady window, and the late-tick check does not apply to them, because it would remove exactly the runs whose jitter the jitter fit measures.
- `body`: Roll and pitch spread and event rates. These need a 2 s steady window and a floor label under the 72 h limit, and the late-tick check and the outlier screen apply.

`status` is `usable` when `uses` is not empty, `excluded` when a person said so, and `quarantined` otherwise. A run that did not end cleanly (a fall, a crash, a stale IMU, any stop but `stopped` or `complete`) is used up to its last second (`END_CUT_S` removes the final second), and its end reason stays in the manifest so falls still count for event rates. A walk with the everyday foot trim (the policy's `DEFAULT_TRIMS` entry, an attachment's saved trim, or `foot_trim_source: "everyday"`) is normal gait, not a steering test.

A person can state the floor for any time range (`~/g2_data/floor_overrides.json`, a list of `{from, to, surface}`). It replaces the recorded label, and `unknown` takes those runs out of every fit.

Keeping drift out of the sim
----------------------------

Hardware drift is not a stable property of G2: it changes with one servo swap and grows as the pack sags. A simulator trained against it learns a one-sided correction. The guards:

1. Whitelist: The builder's output has a fixed list of allowed parameters, and any other key is rejected. There is no yaw, heading, lateral or drift entry (a test enforces it).
2. No yaw or heading input to any fit: Only yaw-free statistics are used (roll and pitch spread, timing, IMU noise at rest).
3. Mean lean excluded: A steady roll or pitch offset is a mounting or calibration offset, so only the spread is used. The IMU zero is estimated at rest and fed as a range.
4. Drift canary: After a candidate snapshot, the reference policy runs in the new sim. If the sim's heading drift or the mirror gap changes beyond noise, the snapshot is blocked.
5. Proxy screen: Each parameter's per-run estimate is compared with that run's heading change, and a parameter that tracks drift is dropped.
6. Battery confound: Voltage bands are kept apart.
7. Monitor-only drift channel: Per-run drift is stored for audits and is not visible to the builder.

Snag detection
--------------

Snags (feet catching on grout lines or edges) are counted statistically from their IMU and command signatures, per metre walked and per floor, and are never labelled one by one. The IMU gives a fresh frame every 200 ms, so a brief catch may show in one frame or only through the policy's reaction. The approach, in order:

1. Distributions first, before any detector, keeping turns, pick-ups and ordinary gait impacts from being mistaken for snags.
2. Periodicity: Grout lines recur at the tile size, so disturbances should recur every (tile size / speed) seconds.
3. Floor comparison: The same policy on hardwood is the baseline, and extra spikes, stalls and correction jumps on tile are the snag effect.
4. Policy reaction: A catch should make the policy's correction jump (logged at 80 Hz).

A rate of snag-like events per metre per floor is what the simulator's hazard setting needs. Nothing from a surface reaches the sim until it passes the ingest gates and the audit.

Calibration builder and harm check
----------------------------------

The builder runs when enough new usable data has arrived (default: 10 new usable runs in the current epoch and surface). It fits only the confident tier: IMU bias and noise at rest, command cadence, latency and loop jitter, servo rate and force (which needs bench data), roll and pitch swing statistics, pack voltage against behaviour, and real fall and fault rates. It writes a snapshot with each value, its range, the number of runs, the epoch, the surface and the checks passed.

The harm check runs before any approval. It scores the reference policies on the benchmark in the snapshot's world. Flat-ground falls must not rise, the mirror gap must not worsen, and no benchmark cell may drop beyond its noise. A snapshot that fails is blocked.

Approval
--------

A snapshot is approved automatically when all of these hold:

1. Every parameter passed its fit checks: enough runs and seconds, reproducible across odd and even runs, within physical bounds, and not a drift proxy.
2. The harm check passed. A failed harm check blocks the snapshot and it cannot be approved.
3. The hardware epoch is unchanged.
4. Every value stays within its own noise of the value it replaces, or moves for real with strong evidence (20 runs, 120 s) and a modest size (at most 25% of the value it replaces, measured against the profile's value or the last manually approved snapshot).

A snapshot that fails any other gate waits for a person (`g2cal approve ID`). Every automatic approval is written to `~/g2_data/calibration/approvals.jsonl`, and `g2cal revert` undoes it. A cumulative cap stops many small automatic approvals from creeping. A fitted parameter that is measured but must not be applied is refused with `g2cal reject NAME` (recorded in `~/g2_data/calibration/rejected.json`) until `g2cal unreject`.

Snapshots are immutable and numbered, and "current" is a pointer, so reverting is safe.

Training launches
-----------------

A 20-million-step run never starts automatically, and approving a snapshot starts nothing by itself. Two rules apply to the 3-million-step screening run (the smoke test, in the same world as the snapshot, scored against the control):

1. Automatic when idle: A 3M screen may start on its own for a new snapshot that passed the harm check and the drift canary, only when nothing else is running on the Mac, at most once per snapshot, and its result is reported. The harm check follows the same idle-only rule.
2. Before a 20M: A 3M smoke test on the snapshot the run would use runs first, on an otherwise idle Mac (reused if one already finished for that snapshot), and its result is reported before the 20M starts.

A launched run uses the latest approved snapshot instead of waiting on a pending proposal, and it logs any pending proposal it did not use.

Symmetry rule
-------------

Fitted parameters (servo strength, latency, IMU noise, ...) are symmetric by default. A real left-right difference in the hardware (a weak servo) is raised as a maintenance flag and never enters the sim as a fixed one-sided bias, which is how a policy learns a one-sided correction. Events keep their side in the log and feed the sim's hazard rates, where the side is randomized.

Event labels
------------

There are no voice notes and no per-event labels. Falls are recorded by the log (`end_reason: fall`, the fall guard) and by the operator reporting when one happened, and snags are counted statistically.

Periodic audit
--------------

A data-health report runs every 25 new usable runs or monthly (whichever comes first), after every epoch change and before every retrain. It shows runs per epoch, surface and policy, the quarantine rate and reasons, each fitted value over time (flip-flopping or trending values are flagged), the sim-versus-real gap before and after each snapshot (it must shrink or hold), a forward check (fit on older runs, predict newer), and anything excluded that probably should not have been.

Storage
-------

Raw CSV stays on the Pi and is gzipped on the Mac at ingest (`pandas` and `numpy` read `.csv.gz` directly). Compression is lossless, and values are never rounded below the log's own precision. A closed gzip file cannot be appended to, so compression happens after the run ends and half-written files are swept at start-up. A checksum is kept, and the Pi copy is kept until the Mac copy is verified. A walking hour is about 40 MB raw and roughly 10 MB gzipped.

Speed measurement
-----------------

Speed has no ground truth on the robot (the IMU estimator is weak), so automatic runs do not feed speed to the sim. Where speed matters (the sim-versus-real speed gap, comparing policies on hardware, distance-based behaviour, the carpet detector), a tape-measured average speed per dedicated run is enough.

Phases and status
-----------------

- Phase 0, capture module: Done. `pi_pipeline/telemetry/`, the hook in `run_gait.run()`, `g2floor`, and `test_autolog.py`.
- Phase 1, capture in every path: Policy-walk capture is done and verified on G2 (loop timing unchanged). The firmware-gait and rest-IMU recorders, the event log, rotation and orphan cleanup are not built. Scripted gaits get a `scripted_walk` sidecar.
- Phase 2, sync, ingest gates and store: Built. `tools/g2_ingest.py`, `g2data sync|ingest|status`.
- Phase 3, calibration builder: Built. `tools/g2_calibrate.py` and `g2cal`, with the background loop `tools/g2_bg_jobs.sh` (`g2bg`) calling `tools/g2_cal_auto.sh`. It fits the confident tier the walk logs support (the IMU frames per tick and the loop jitter). IMU bias and noise, servo rate and force, and fall and snag rates need more data (the rest-IMU recorder, bench data, many more metres). `g2_profile` loads only an approved snapshot and records `G2E_CAL_ID`.
- Phase 4, backfill of older logs by epoch: Not started.
- Phase 5, retrain runner reads the snapshot and reports it before a 20M: Not started.

Results so far
--------------

- Exploration produces many short stop-and-go walks, so its usable steady-state seconds are few. Long dedicated walks (12.5 s each, with tape distance and a hardwood control) are worth far more per minute of testing.
- Roll and pitch spread on tile is about 5.4 and 2.6 deg, in line with the hardwood baselines (roll about 5, pitch about 2.5), so tile does not yet look different on those two measures.
- The fitted loop-jitter value (`G2E_CMD_PATH_EXTRA_MS_MAX`, 12.5 ms against the profile's 4) is not approved: it is an approximation of command-path delay, so it stays out of every snapshot while still being measured and reported.
