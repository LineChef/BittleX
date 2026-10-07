# Real-hardware data pipeline: capture every run, feed the sim only what helps (plan approved by the user 2026-10-07)

Goal (user): every run G2 makes is captured automatically, and every retrain inherits what has accumulated since the last one, so the sim gains data it would otherwise never have.
Rule that overrides the goal: **only data that can help gait training reaches the sim; anything noisy or harmful is filtered, quarantined or left out, and the data is audited periodically.**
Related: [`sysid-capture-plan.md`](sysid-capture-plan.md) (the planned dedicated sessions), [`hardware-logging.md`](hardware-logging.md) (what a log carries), [`v3-decisions-log.md`](v3-decisions-log.md).

## Decisions (user, 2026-10-07)

1. Approval is **semi-automatic**: collection, sync, filtering and fitting are automatic; a calibration snapshot is used by a retrain only once approved, and a change that stays within the noise and passes every check is approved automatically (see Approval).
2. The data store is **outside the repo** (`~/g2_data/` on the Mac); only non-personal summaries are committed.
3. **Every** policy walk is logged, including voice-triggered and exploration walking, not only direct runs.
4. Everything is kept, **compressed losslessly** (gzip). The user tells Claude when hardware changes (a new hardware epoch).

## Flow

Pi: every movement path logs (raw CSV + JSON sidecar, `~/g2_runs/auto/<date>/`; commands: `g2floor [label]`, `g2floor status`, `g2floor epochs`) -> sync watcher pulls to the Mac when the Pi is online (the Pi copy is deleted only after the Mac copy is verified) ->
Mac store `~/g2_data/` (gzip) -> **ingest gates** (per-run filters, quarantine) -> **calibration builder** (fits, reproducibility check, harm check) -> **snapshot** (immutable, numbered) ->
approval (auto or user) -> `g2_profile` loads the approved snapshot at retrain launch and the run records its id.

## What gets captured (movement-path inventory, 2026-10-07)

| Path | Where it goes through | Capture |
|---|---|---|
| Policy walking from the voice service and the exploration runtime | `PolicyWalker` -> `run_gait.run()` with no log path | one choke point: auto-log when no `--log` is given (`G2_AUTOLOG=off` disables) |
| Policy walks started from the command line / baseline runner | `run_gait.run()` | already logged with `--log`; the auto-log fills in when none is given |
| Scripted `wkF` open-loop walks | `run_gait.openloop()` | only run from the command line / baseline runner, which already pass `--log`; not hooked |
| Firmware gaits and skills sent as tokens (turns, `kwk*`, tricks, rest, stand) | `WalkerSink` / `SerialActuatorSink` | IMU-only recorder (later phase); commands are already traceable through `link/trace.py` |
| Idle / rest IMU | the IMU stream the app already reads | low-rate recorder (later phase): IMU bias and noise at rest are free, plentiful data |
| Events: falls, guard stops, thermal cooldowns, battery alerts, pick-ups | diag events | event log, used for real fault and fall rates |

Every run gets a sidecar with: kind, policy name, commands, git commit, hardware epoch, surface label, battery at start and end, features on, why the run ended.

## Hardware epochs and surfaces

- **Epoch** (`pi_pipeline/telemetry/hardware_epochs.json`): dated hardware changes (case mounted, servo replaced, ...). The user says when hardware changes; Claude adds the entry. Fits use the current epoch only; older epochs are kept and never fed unless a person says so.
- **Surface** (hardwood, tile, carpet, ...): a label set with one command and stored on the Pi; every run records it. Fits are per surface, because friction differs (kitchen tile is a good floor for real **snag** data: feet catching on grout lines. The sim's snag category is thin 10 mm cord-scale obstacles, two per episode; grout lines are probably lower, so this tests the low end).
  Grout depth is unmeasured; the logs will show how often feet catch. Snags are not detected on the robot today, so they appear in the log only as IMU and command signatures; a hand label would make them usable for hazard rates (offered to the user, not built).

## Ingest gates: what is kept out of the fits (nothing is deleted; excluded runs are quarantined with a reason)

A run is usable for fitting only if all hold: file complete and time strictly increasing; control loop on time (dropped ticks under a limit); IMU frames arriving (no long stale stretch);
no NaN or out-of-range values; the run's hardware epoch is current; surface label known; policy known; length above a minimum; no operator pick-up (accel / tilt spike) inside the window used;
no fall or guard trip inside the window used (those runs still count for event rates); battery above the low-battery line, or tagged by voltage band and never mixed with full-pack data;
the first seconds after the stand excluded; thermal cooldown stretches excluded.
Statistical screen: a run whose metrics sit outside the epoch's median by more than k x MAD is quarantined for review, not dropped.
Per-parameter rules in the builder: a minimum number of supporting runs; fit on one half of the runs and check it on the other (a value that moves more than its own noise is not used); physical bounds;
left-right symmetry for fitted *parameters* (approved 2026-10-07; see below); **no drift parameter exists in the builder** (drift direction and size never feed the sim; a test enforces it).

## Keeping drift out of the sim (guards, agreed 2026-10-07)

Hardware drift is not a stable property of G2 (it moved from about +142 to about +40 deg per 12.7 s with one servo swap and grew from +44 to +178 deg as the pack sagged); a sim trained against it learns a one-sided correction (the V2.1 problem). The guards:
1. **Whitelist:** the builder's output has a fixed list of allowed parameters; any other key is rejected. There is no yaw, heading, lateral or drift entry (a test enforces it).
2. **No yaw or heading input to any fit:** only yaw-free statistics (roll and pitch spread, timing, IMU noise at rest).
3. **Mean lean excluded:** a steady roll or pitch offset is a mounting or calibration offset and correlates with one-sided leg differences; only the spread is used, never the mean. The IMU zero is estimated at rest and fed as a range.
4. **Drift canary:** after a candidate snapshot, the reference policy runs in the new sim; if the sim's measured heading drift or the mirror gap changes beyond noise, the snapshot is leaking asymmetry and is blocked.
5. **Proxy screen:** each parameter's per-run estimate is compared with that run's heading change; a parameter that tracks drift is dropped as a drift proxy.
6. **Battery confound:** voltage bands are kept apart, because drift grew as the pack sagged.
7. **Monitor-only drift channel:** per-run drift is stored for audits and is not visible to the builder.

## Snag detection from the logs (hypothesis to test on the kitchen runs)

Snags will be frequent on kitchen tile (feet catching on grout lines) and the user will not label them (no voice notes, no per-event labels). The sensor is the limit: the IMU gives a fresh frame only every 200 ms, so a brief catch may show in one frame or only through the policy's
reaction; the logged joint angles are commands, not measurements. The approach, in order:
1. **Look at distributions first**, before building any detector, and keep turns, pick-ups and ordinary gait impacts from being mistaken for snags.
2. **Periodicity:** grout lines recur at the tile size, so at about 0.1 m/s disturbances should recur every (tile size / speed) seconds; a regular beat in roll and pitch spikes locked to that period is strong evidence. Needs the tile size (asked, not yet known).
3. **Floor comparison:** the same policy on hardwood is the baseline; extra spikes, stalls and policy-correction jumps on tile are the snag effect, with no labels needed. A same-day, same-battery hardwood control walk makes this clean (asked).
4. **Policy reaction:** a catch should make the policy's correction jump (logged at 80 Hz).
Individual snags may not be identifiable; a **rate of snag-like events per metre walked, per floor** is what the sim's hazard setting needs, and the statistical view is enough for that. The sim's snag category is thin 10 mm cord-scale obstacles, two per episode; grout lines are probably lower.
Nothing from the kitchen reaches the sim until it passes the ingest gates and the audit.

## Calibration builder and the harm check

Runs when enough new usable data has arrived (default: 10 new usable runs in the current epoch and surface). Fits only the confident tier: IMU bias and noise at rest; command cadence, latency and loop jitter;
servo rate and force (needs the bench data); roll and pitch swing statistics; pack voltage against behaviour; real fall and fault rates. Writes a snapshot: each value, its range, the number of runs, epoch, surface, and the checks passed.
**Harm check before any approval:** score the reference policies (V2.1 and the current V3 candidate) on the benchmark in the snapshot's world; flat-ground falls must not rise, the mirror gap must not worsen, and no benchmark cell
may drop beyond its noise. A change that fails is blocked.

## Approval: who and when

| Case | Who approves | When |
|---|---|---|
| Every changed value within its noise band, every check and the harm check pass, no epoch change, and the total change since the last **human**-approved snapshot is under the cumulative cap | **Automatic** (the rules); recorded as auto-approved and shown in the next report; one command reverts to the previous snapshot | when the snapshot is built |
| A change beyond noise, a new parameter, an epoch change, or the cumulative cap exceeded | **The user** (Claude never approves these): says "approve" in chat or runs `g2cal approve <id>` after reading the one-page diff and checks | at the next session after the proposal exists; always reviewed before a 20M go |
| Harm check fails | **Blocked**, not approvable until the cause is understood | |

**Training launches (user, 2026-10-07).** The **20M run never starts automatically**, and approving a snapshot starts nothing by itself. Two rules for the 3M screening run (the smoke test, in the same world as the snapshot, scored against the control):
1. **Automatic when idle:** a 3M screen may start on its own for a new snapshot that passed the harm check and the drift canary, only when nothing else is running on the Mac (no training, benchmark or other test in progress, so nothing gets a random slowdown), at most one per snapshot, and its result is reported. The harm check (benchmark scoring, no training) follows the same idle-only rule.
2. **Always before a 20M:** when the user gives a go for a 20M run, a 3M smoke test on the snapshot it would use runs first, on an otherwise idle Mac (reused if one already finished for that snapshot), and its result is reported before the 20M starts.
When the user launches a run, it uses the latest approved snapshot instead of waiting on a pending proposal, logs any pending proposal it did not use, and Claude reports it before the go. The cumulative cap stops many small auto-approvals from creeping.

## Symmetry rule (approved 2026-10-07)

Fitted **parameters** (servo strength, latency, IMU noise, ...) are symmetric by default. A real left-right difference in the hardware (a weak servo) goes to the user as a maintenance flag and never into the sim as a fixed one-sided bias, which is how a policy learns a one-sided correction.
**Events** keep their side in the log (a snag on one foot is a real event) and feed the sim's hazard rates, where the side is randomized: a right-foot snag teaches "snags happen at some rate on any foot".

## Event labels

No voice notes and no per-event labels (user, 2026-10-07). Falls are recorded by the log (`end_reason: fall`, the fall guard) and by the user telling Claude when one happened (Claude notes the time against the session). Snags will be frequent on kitchen tile, so they are counted
statistically from their IMU and command signatures per metre walked and per floor, never labelled one by one.
Snapshots are immutable and numbered; "current" is a pointer, so reverting is safe.

## Periodic audit ("is the data tidy and doing its job")

A data-health report on a schedule: every 25 new usable runs or monthly (whichever first), after every epoch change, and before every retrain. It shows: runs per epoch, surface and policy; quarantine rate and reasons;
each fitted value over time (flip-flopping or trending values are flagged); the sim-versus-real gap on the monitored statistics before and after each snapshot (it must shrink or hold); a forward check (fit on older runs, predict newer);
and anything excluded that probably should not have been. Findings go in [`v3-decisions-log.md`](v3-decisions-log.md) and are summarised to the user.

## Storage

Raw CSV on the Pi, gzip on the Mac at ingest (Pillow-free, `pandas` and `numpy` read `.csv.gz` directly). Lossless only: never round values below the log's own precision. Downsides, and how they are covered: a gzip file cannot be appended
to once closed (compress after the run ends, and sweep half-written files at start-up); one damaged file loses its tail (keep a checksum and keep the Pi copy until the Mac copy is verified); a slightly slower read (negligible).
Size estimate: about 40 MB of raw log per walking hour, roughly 10 MB gzipped (an estimate, to be measured).

## Speed measurement: not part of the automatic pipeline

Speed has no ground truth on the robot (the IMU estimator is weak), so automatic runs do not feed speed to the sim. Where it would help: the known sim-versus-real speed gap (about 25%), comparing V3 with V2.1 on hardware, distance-based behaviour,
and the carpet detector. For those, a tape-measured average speed per dedicated run (distance over time) is enough, and it is already in the capture plan.

## Phases and status

| Phase | What | Status |
|---|---|---|
| 0 | Inventory, schema, epochs file, capture module with tests | **done 2026-10-07** (`pi_pipeline/telemetry/`, the hook in `run_gait.run()`, `g2floor`; tests in `test_autolog.py`; not yet on the Pi) |
| 1 | Capture in every path (firmware-gait and rest IMU recorders, events), rotation, orphan cleanup at service start, overhead check on the Pi | not started; the policy-walk capture waits for the next deploy and one short hardware run to confirm the loop timing is unchanged |
| 2 | Sync watcher, ingest gates, store, `g2data status` | not started |
| 3 | Calibration builder, harm check, snapshots, approval, `g2_profile` loading | not started |
| 4 | Backfill of the 2026-10-01 to 10-07 logs by epoch | not started |
| 5 | Retrain runner reads the snapshot; report in the pre-20M report | not started |
