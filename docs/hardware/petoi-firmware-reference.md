# Petoi / OpenCat firmware reference

Confirmed from `PetoiCamp/OpenCatEsp32` source (2026-09-07, IMU serial
protocol + line format re-verified against `main` again 2026-09-20), the
BiBoard/ESP32 firmware that runs on G2 (Bittle X). Captured so the
knowledge isn't lost between sessions. Verify against the repo if firmware
has moved on.

## Repositories

| repo | what |
|---|---|
| `PetoiCamp/OpenCatEsp32` (aka `OpenCatEsp32-Quadruped-Robot`) | **BiBoard/ESP32 firmware — this is G2's.** |
| `PetoiCamp/OpenCat` | NyBoard/AVR firmware (older boards) |
| `PetoiCamp/OpenCat-Old` | legacy |

`OpenCatEsp32/src/`: `src.ino` (serial parser / main loop), `imu.h` + `mpu6050/`
(IMU fusion + exception detection), `reaction.h` (`dealWithExceptions()` — auto
recovery), `skill.h` (skill runtime — a copy is vendored at
`rl_training/opencat-gym/reference_gait/skill.h`), `InstinctBittleESP.h` (keyframe
data — vendored), `OpenCat.h` (token macros + config constants).

**No official Petoi RL/sim repo.** Petoi points to community work: `ger01d/opencat-gym`
(the lineage of `rl_training/opencat-gym`) and `ger01d/opencat-gym-sim2real`, plus
forum MuJoCo/Isaac efforts. Our fork is already the canonical community base.

## Serial command tokens (`OpenCat.h` `T_*` macros)

Newline-terminated ASCII over UART. Confirmed set:

**Confirmed against the real BiBoard 2026-09-28: commands produce more than
one reply line.** `check_serial.py`'s `allmoves` sends each move with
`read_reply=False` (fire-and-forget), then queries `P` afterward and reads
one line back. Real-hardware logs showed the "voltage" field cycling
through move-name fragments instead of `Voltage: X.XX V` on a steady 1-in-4
pattern — the unread reply/echo from each move command was sitting in the
buffer, so the next single-line read (the `P` query) picked up that stale
backlog instead of its own reply, and the real voltage line surfaced later,
misattributed to a subsequent move. Not a hardware fault — fixed by
draining (`SerialLink.drain()`) immediately before every voltage read in
`_allmoves()`. Practical implication for any new code that fires a command
with `read_reply=False` and later expects a clean single-line read: drain
first, don't assume the buffer is empty.

**Second layer confirmed the same day: a real, previously-undocumented
debug line, `imuException: <code>`.** After the drain fix above, most reads
came back clean, but `wave`/`push_ups`/`check_around`/`come_here`/
`high_five` still intermittently returned `imuException: \t0` instead of
voltage — `0` per `getImuException()`'s documented codes above means no
exception, so nothing bad happened during those moves, but the line's
timing is variable enough (one case took ~1s, near the read timeout) that
a single `drain()` pass doesn't reliably clear it either. `check_serial.py`
now retries the voltage query itself (`_read_voltage()`: drain, query,
check for a `Voltage:` prefix, retry up to 4 attempts) rather than trusting
one line no matter what. Not yet known which skills trigger this print or
why the delay varies — flag if it recurs somewhere that matters.

## Onboard voice-recognition module (`X<letter>` commands)

BiBoard V1 carries a built-in offline voice-recognition module + speaker
(`project-plan.md`'s parts notes), separate from the `T_*` command parser
above and not decoded from our own firmware source — confirmed instead
from [Petoi's official docs](https://docs.petoi.com/extensible-modules/voice-command-module)
and against the real board 2026-09-28:

| command | action |
|---|---|
| `XAa` | set English as default language |
| `XAb` | set Chinese as default language |
| `XAc` | enable the voice module |
| `XAd` | disable the voice module |
| `XAe` | enter learning mode |

Not blocked by `opencat.is_safe()` (only `c`/`cd` are). There's also a
physical dial switch on the bottom of the BiBoard extension hat (Bittle X
only) that must be set to "Voice Command" — unchecked here since the
module was otherwise responsive. Voice commands: "play sound" tests
liveness (replies with a "Do-Re-Mi" tone, works regardless of language --
tests only that it's not muted); "be quiet" mutes it; "bing bing" is the
spoken equivalent of `XAa` (switch to English).

**Switching it on and off (confirmed 2026-10-03):** speak to G2. **"Be quiet"** makes the module ignore basic commands such as "rest";
**"play sound"** turns them back on (Do-Re-Mi tone). Per Petoi's docs the module listens continuously with **no wake word**, has 40 fixed
commands (two languages) plus up to 10 you record yourself in learning mode; **"rest" is one of the fixed commands, "stop" is not.**
While it is on, a phrase meant for the Pi can also trigger it.

**Do NOT send `Xa` (lowercase) — or `XAd` — to "disable" it over serial.** The board only ever replies `X` to these, so there is no
confirmation, and the module's on/off state is saved in the board's settings across reboots. After `Xa` was sent on 2026-10-03 the module
kept listening and said "ok" to "stand up", but G2 did nothing, even after a reboot: voice commands had silently stopped working.
**`XA` (uppercase) fixed it** (voice commands worked again right after). Rule of thumb from `moduleManager.h`: `X` + uppercase letter
enables a module, `X` + lowercase disables it, and neither prints anything useful. Use the spoken switch above instead. Symptom to
remember: module answers "ok" but the body does not move → send `XA`, and check the dial on the hat is on "Voice Command".

**2026-09-28 incident: module found stuck defaulting to Chinese, with
voice commands unresponsive, for no identified trigger (nothing bumped/
dropped, unrelated to our serial link work, broken before this session
started).** Matches a closed PetoiCamp/OpenCatEsp32-Quadruped-Robot PR
(#51) where an identical symptom on BiBoard V1.0 was root-caused to the
module getting stuck in a bad persistent armed state that survives
reboots/reflashes -- not a firmware bug, and the author's own code-level
fix attempt was a red herring. Recovered here by sending `XAc` (enable),
waiting ~1.2s, `XAb` (confirmed via its own reply: `Default language:
Chinese` -- so this *was* the stuck state), waiting ~1.2s, then `XAa`
(confirmed via reply: `Default language: English`). Verified working
after (both "play sound" and an actual English command). If this recurs,
this sequence is the first thing to try again before assuming a deeper
fault.

**Recurred 2026-09-29, as expected — the full erase/reflash wipes this
too.** Same symptom, same fix, applied right after the reflash + servo
recalibration: `XAc` → `XAb` (confirmed stuck: `Default language:
Chinese`) → `XAa` (confirmed: `Default language: English`), then verified
live by voice again ("play sound" + an actual command). Not a new
incident — this module's state lives in the same EEPROM/NVS wiped by
`esptool erase_flash`, so re-applying this sequence is now an expected
step after any future full reflash, not a fault to re-diagnose.

| token | name | meaning |
|---|---|---|
| `k<skill>` | `T_SKILL` | run a named skill — `kwkF`, `ksit`, `kbalance`, `kcrF`, `ktrF` |
| `m<idx> <deg> …` | `T_INDEXED_SIMULTANEOUS_ASC` | move joint(s), chainable — `m0 30 8 -35` |
| `b<note> <dur> …` | `T_BEEP` | buzzer melody: pairs of (note, duration). Note = semitone number, C3 = 14, C4 = 26, **1-35 is the usable range (loudest at the low end)**, 0 or -1 = rest. Duration = a divisor of one second (`b14 4` = note 14 for 1/4 s, **not milliseconds**), so a longer note is a smaller number. Chain as many pairs as fit; keep a token short (~60 chars). `b<1-10>` on its own sets the volume per Petoi's serial-protocol page (unconfirmed on this board, see the research note); a bare `b` toggles mute -- never send it |
| `d` | `T_REST` | rest posture, servos off (ends a looping gait) |
| `P` | `T_POWER` | **print battery voltage** — confirmed against the real BiBoard 2026-09-28 (`check_serial send P` → `Voltage: 8.02 V`, healthy for the 7.4 V 2S pack) |
| `j` / `j <idx>` | `T_JOINTS` | **return all joint angles / one joint** |
| `f` | `T_SERVO_FEEDBACK` | servo position feedback (if the servo chip supports it) |
| `g` | `T_GYRO` | gyro function toggle (bare `g`) |
| `gU` / `gu` | `C_GYRO_UPDATE` / `_OFF` | continuous gyro data update on/off (already **on by default from boot** — `updateGyroQ = true` is set during IMU init, so `gU` is rarely needed just to get data flowing) |
| `gB` / `gb` | `C_GYRO_BALANCE` / `_OFF` | turn gyro balancing on/off |
| `gc` | `C_GYRO_CALIBRATE` | calibrate the IMU |
| `gP` | `C_PRINT` (in the `g`-context) | **start CONTINUOUS 6-axis print** — sets `printGyroQ = true`, which is what actually makes `readEnvironment()` call `print6Axis()` every loop |
| `gp` | `C_PRINT_OFF` | stop it — **NOT symmetric with `gP`**, this is "print once then stop", not a toggle; sending `gP` twice does not turn it off |
| `p` | `T_PAUSE` | pause |
| `t` | `T_TILT` | tilt command |
| `c` / `cd` | calibration / factory | **never send from the pipeline** |

**CONFIRMED 2026-09-20, corrects the previous entry here:** `v`/`V` are still
not a real token at all (grepped current `main` source directly — no match
anywhere in the command parser), and `pi_pipeline/gait/run_gait.py` /
`sysid_collect.py` were both sending it until this date, which would have
been silently ignored by the board and produced *zero* streamed IMU data —
`--probe-imu` would have hit a dead loop-timeout at first real bring-up.
Fixed in both files to send `gP`/`gp` instead, matching the actual
`T_GYRO`+`C_PRINT` mechanism traced above. `python -m pi_pipeline.gait.run_gait
--probe-imu` still needs to run against the real board to confirm this against
actual hardware (nothing above has touched a real BiBoard) — that's step 13a
of the bring-up sequence.

## IMU

- BiBoard V1 compiles support for **both MPU6050 and ICM42670** and picks
  whichever chip is physically present at runtime (`OpenCat.h` defines both
  `IMU_MPU6050` and `IMU_ICM42670` for `BiBoard_V1_0`) — don't assume MPU6050
  without checking which prefix (`MCU:` vs `ICM:`) the real board actually
  sends (see the confirmed line format below).
- DMP quaternion fusion (no hand-tuned complementary filter).
- `IMU_PERIOD 5` ms → **200 Hz** sample loop. `IMU_SKIP 1`, `IMU_SKIP_MORE 23`
  for frame-skip during motion.
- Orientation as YPR (yaw/pitch/roll ≈ body z/y/x).
- Balance hooks: `RollPitchDeviation[2]`, `balanceSlope[2] = {1, 1}`, `gyroBalanceQ`.
  Exact balance `KP/KI/KD` gains not yet pulled — TODO if the deployment balance
  loop needs matching.

### Confirmed serial line format (`imu.h` `print6Axis()`, 2026-09-20)

The function actually wired into the main loop (via `readEnvironment()`) —
**not** the similarly-named but dead `print6AxisMacro()`, which is unused
and would have been the wrong thing to match against:

```
MCU:<ax><ay><az><yaw><pitch><roll>      # MPU6050
ICM:<ax><ay><az><yaw><pitch><roll>      # ICM42670
```

`snprintf(..., "MCU:%6.2f%6.2f%6.2f%7.1f%7.1f%7.1f", ax, ay, az, -yaw, pitch, roll)`
— fixed-width, no explicit delimiter (padding makes it whitespace-safe in
practice), accel in g, angles in degrees, **yaw printed negated**.
`PRINT_ACCELERATION` is unconditionally defined in current firmware, so the
accel triplet is always present — there is no gyro-only variant.

**No angular rate, 5 Hz ceiling — how the Pi side handles it (2026-09-22).**
The line carries acceleration, not angular velocity; the raw-gyro print path
is dead code (commented out in `print6AxisMacro()`, which isn't even
called). And `print6Axis()` returns early unless 200 ms have passed since its
last print (`PRINT6AXIS_MIN_INTERVAL`), so the stream is at most 5 Hz. Every
call site (main loop, `transform()`'s per-step print, skills) goes through
that one throttle — there is no faster read path in stock firmware.
`gait/imu_parse.py`'s `ImuFeed` holds the latest frame between prints and
derives roll/pitch rate by finite-differencing consecutive frames;
`run_gait.py` and `app/sensors.py` both use it, reading through
`SerialLink.poll_imu()` (non-blocking; IMU lines are split out of command
replies). What that costs the gait policy in sim:
`rl_training/opencat-gym/resilience_imu_rate.py`.

**RESOLVED, 2026-09-28/29 — was a stale-firmware artifact, fixed by a
reflash. Full story, in order:**

1. **2026-09-28, `run_gait.py --probe-imu` against the real BiBoard
   measured 249.2 Hz** raw line rate (1246 lines / 5 s), not "at most
   5 Hz." Checked it wasn't the same stale line reprinted fast: of those
   1246 lines, 500 carried a genuinely distinct 6-axis value (~100 Hz
   distinct-sample rate). Chip prefix confirmed `ICM:` (ICM42670, not
   MPU6050). Also noted `az` read ~9.9 at rest, consistent with **m/s²**,
   not "g" as this doc used to say.
2. **Cross-validated under real load same day**: `--probe-imu-load`
   (sends the neutral stand pose at 80 Hz on the same UART while
   counting IMU lines, the actual shared-bus condition the control loop
   runs under) measured **93.0 Hz** — same ballpark, still nowhere near
   5 Hz, ruling out a fluke/burst reading.
3. **2026-09-29, read BiBoard's full two-line `?` banner properly**
   (a naive single-read grabs only line 1, leaving line 2 as backlog for
   whatever reads next — same class of bug as the `allmoves` desync
   documented below): line 1 `Bittle X`, line 2 a version string,
   **`B10_251121`** — read as a 2025-11-21 build, ~10 months older than
   our `main`-branch source review (2026-09-07/09-20). Strong
   circumstantial evidence the stale build had different IMU timing.
4. **Separately that same night**, found and fixed a real firmware bug
   (below) requiring a full flash erase + reflash to Petoi's *current*
   official firmware via the Desktop App.
5. **After the reflash, re-ran `--probe-imu`: exactly 5.0 Hz** (25 lines /
   5 s) — matching the documented `PRINT6AXIS_MIN_INTERVAL` cap exactly,
   on the nose. Confirms step 3's theory directly rather than just
   circumstantially: the stale ~10-month-old build genuinely had
   different (much faster) IMU print timing than current firmware.

**Practical upshot:** `hw1_20m`/`Release_CandidateV2`/`V2.1` were all
trained under the *correct* assumption (`IMU_HOLD_STEPS=16`, 5 Hz) for
G2's real, current firmware. A same-night retrain campaign built around
the stale 93-249 Hz reading (`docs/rl/hw1-log.md` Round 5) was abandoned
once this closed out — not a wasted detour exactly, since it's what led
to catching the reflash-worthy bug, but its premise no longer holds.

## Onboard voice module + camera: EEPROM-persisted module state (`moduleManager.h`)

Separate from the serial tokens above — a status/enable table for
BiBoard's extension modules, confirmed from `src/moduleManager.h`:

| letter | module | | letter | module |
|---|---|---|---|---|
| `S` | Serial (Grove_Serial, i.e. Pi/UART2) | | `B` | Backtouch |
| `A` | Voice | | `U` | Ultrasonic |
| `T` | Touch | | `G` | Gesture |
| `L` | Light | | `C` | Camera |
| `D` | infrared Distance | | `Q` | Quick_demo |

Printed as `?`'s status dump: a header row of these letters, then a `0`/`1`
row (also reachable via `X`+letter, e.g. `XC`'s enable prints it). **`G`
here is Gesture, not Gyro/IMU** — easy to misread and chase the wrong flag
(done once, 2026-09-28, before finding the real mechanism below).

**Confirmed from `reconfigureTheActiveModule()`'s literal source**: `X` +
uppercase letter enables that module; `X` + lowercase letter disables only
that one (bare, not `X`-prefixed, single lowercase/uppercase letters seem
intended for a different -- untested -- calling convention; **do not test
bare lowercase `c` to find out, see below**). Enabled/disabled state is
persisted — `i2c_eeprom_write_byte()` if an external I2C EEPROM is present,
else the ESP32's own `config.putBytes("moduleState", ...)` (NVS/Preferences)
as fallback. **This means enabling a module isn't just a runtime toggle —
it survives power cycles**, and `initModuleManager()` re-runs `initModule()`
for every module still marked enabled on *every boot*.

**The bug this caused, 2026-09-28: enabling Camera (`XC`) permanently
kills the IMU streaming task, with zero restore path anywhere in the
firmware, and re-triggers on every boot because the enabled state
persists.** Confirmed from `camera.h`'s `groveVisionSetup()`, called by
`moduleManager.h`'s `EXTENSION_CAMERA` case: it unconditionally sets
`updateGyroQ = false` and `vTaskDelete()`s the IMU task, with no code
anywhere that recreates it. Because `moduleActivatedQ[Camera]` persists
to EEPROM/NVS, `initModuleManager()`'s boot loop calls this every single
boot from then on — explaining why the IMU stream stayed dead through
multiple full power cycles (USB *and* battery disconnected) that night.
Sending `Xc` (disable) produced only an ambiguous/garbled reply and did
not fix it (either not the right disable path on this firmware version,
or a reply-capture issue — never fully resolved). **Fix that worked**:
full `esptool erase_flash` (wipes the persisted module state along with
everything else in NVS/EEPROM) + reflash via Petoi Desktop App's Firmware
Uploader, Standard mode, BiBoard V1. Confirmed clean afterward: `gP`
streams real `ICM:` data again.

**Reflash gotchas hit in practice** (Petoi Desktop App, Mac):
- The Product dropdown defaults to **"Bittle"** (the older NyBoard/AVR
  line) — must be explicitly changed to **"Bittle X"**, which unlocks
  **BiBoard V1** as a Board-version option (that dropdown doesn't
  auto-update when Product changes, and silently keeps whatever board
  was previously selected).
- The Serial port dropdown may default to **`cu.debug-console`** even
  with the right board plugged in and detected — must be explicitly
  reselected to the actual device (`cu.usbmodem*`).
- A blank/erased board's port may show with a "non-preferred port"
  warning in the app — harmless, use it anyway; the raw OS-level device
  is unaffected by the erase (a separate USB bridge chip's own
  enumeration, independent of what's flashed to the ESP32's own flash).
- `esptool` (installed via `pip install esptool` into a throwaway venv)
  talks to this board fine as `ESP32-U4WDH (revision v3.1)` for the raw
  `chip_id`/`erase_flash` steps; the actual application reflash still
  needs Petoi's Desktop App (has the correct partition layout + all 4
  files: bootloader/partitions/`boot_app0`/application).
- Petoi's own documented recovery if a flash gets interrupted: power off,
  hold the BOOT button, power on while still holding it, to force ESP32
  download mode.

**Also confirmed, same investigation: bare lowercase `c` is the real
OpenCat calibration-mode trigger** (matches Petoi's official docs — one
of several documented entry methods), **not** a module-disable shortcut.
Sending it produces a `calib` banner + a 16-joint offset table, not a
"disable Camera" message. Don't send it outside an intentional
calibration flow — `opencat.is_safe()` already blocks it for exactly this
reason.

**Post-reflash state, 2026-09-29**: BiBoard is on current official
firmware (no longer `B10_251121`, now `B10_260527` — read via `?`'s
version banner); NVS/EEPROM is fully blank, meaning **calibration needs
to be done for real** (the only calibration ever done before this was the
boot-gesture entry with no actual +/- adjustments saved, so nothing of
value was lost) and **the onboard voice module will very likely need its
English-default fix re-applied** (`XAc`/`XAb`/`XAa`, see the voice module
section above) since that was EEPROM-persisted too.

**Checked GitHub `main` the same night for anything worth catching up
on — nothing urgent, one thing to know about.** `B10_260527` (2026-05-27)
is ~6 weeks behind `main`'s newest firmware-code commit (`DATE "260717"`,
2026-07-17); every commit in that gap was reviewed directly via the
GitHub API. None of it matters for us: the camera-kills-IMU bug above is
still present unfixed on `main` (a `camera.h` commit in the gap is a
comment-only clarification); a `moduleManager.h` refactor that also
touches Serial2 init resolves to the same pins (9/10) for
`BiBoard_V1_0` either way — no pinout regression; the rest is an
Xiaozhi-voice-UART echo feature (not applicable, we don't use a Xiaozhi
module) and unrelated marketing/README commits.

**One real, small thing this surfaced: the voice-module Chinese-default
bug (see the voice module section above, first hit 2026-09-28) has an
actual upstream root-cause fix — but it lands one day after our build.**
`main` commit `9cf4e8d` (2026-05-28) changes `configConstants.h`'s
factory EEPROM default for `EEPROM_CURRENT_LAN` from `'b'` (Chinese) to
`'a'` (English); a same-day commit (`b189c34`) simplifies
`voiceSyncAtStartup()`'s language-sync logic (the `Ac->Ab->Aa` special
case for English, matching our own manual workaround, is replaced with a
single `A<lan>` send). **Checked whether the Petoi Desktop App could get
us this fix: its release feed (`PetoiCamp/DesktopAppRelease`) tops out at
v1.2.9, published 2026-05-28 — the same version already installed and
used for tonight's reflash — so re-running it would just re-flash the
identical `260527` build, not the newer one.** Reaching the fix would
require building from raw GitHub source, which this project has
explicitly decided against (see `project_no_firmware_fork` memory: stock
firmware only, app layer over serial). **Decision: stay on `260527`,
keep applying the manual `XAc`/`XAb`/`XAa` workaround after every EEPROM
wipe** (already a known, working fix) rather than chase a one-day-newer
build that isn't packaged anywhere yet. Revisit only if Petoi ships a
Desktop App release newer than 1.2.9.

### Exception detection (`imu.h` `getImuException()`)

| exception | trigger |
|---|---|
| `IMU_EXCEPTION_FLIPPED` (-1) | `fabs(ypr[roll]) > 85°` **and** accel-Z near/below 0 |
| `IMU_EXCEPTION_LIFTED` (-2) | `pitch < -50°` or `pitch > 75°` |
| `IMU_EXCEPTION_KNOCKED` (-3) | Z-axis accel shock vs previous frame |
| `IMU_EXCEPTION_PUSHED` (-4) | X/Y accel shock ≈ 4.9 g (X) / 7.3 g (Y) |
| `IMU_EXCEPTION_FREEFALL` (-6) | — |
| `IMU_EXCEPTION_TURNING` (-7) | — |

`gFactor = GRAVITY / 8192 ≈ 0.00122`.

### Self-right auto-trigger (`reaction.h` `dealWithExceptions()`)

```c
if (gyroBalanceQ) {
  ...
  case IMU_EXCEPTION_FLIPPED:
    soundFallOver();
    token = 'k'; strcpy(newCmd, "rc"); newCmdIdx = -2;   // run skill "rc" once
}
```

- Fires **only if gyro assist is on** (`gyroBalanceQ`).
- Runs skill `rc` **once**, same skill for supine and side falls (no differentiation).
- **No retry / give-up logic** — if still flipped after `rc` finishes, the exception
  re-triggers next tick → effectively "keep trying `rc`" until upright or gyro off.

**Sim-fidelity gap (why self-right failed to train — see `self-righting-research.md`):**
our sim terminates the episode at 1.3 rad ≈ **74° tilt**, *below* the firmware's
85° `FLIPPED` line — the policy never sees the flipped state the real robot
recovers from. And the scripted `rc` keyframes were never an available action in
sim. Real-robot recovery = detect flip → scripted `rc` → repeat. To reproduce in
sim: raise/remove the tilt cutoff for a recovery window, and expose `rc_ref.npy`
(below) as a scripted action or imitation target.

## Skill keyframe format (`skill.h` `Skill::dataLen`)

`InstinctBittleESP.h` stores each skill as `const int8_t <name>[] PROGMEM = {…}`.

| period `p` | kind | header | frame |
|---|---|---|---|
| `p > 1` | **gait** (loops) | 4 bytes `[period, expRoll, expPitch, ratio]` | 8 int8 leg-joint angles (DOF 8..15) |
| `p == 1` | **posture** | 4 bytes | 16 int8 full-DOF angles |
| `p < -1` | **behaviour** | 7 bytes `[period, expRoll, expPitch, ratio, loopStart, loopEnd, loopCycles]` | 16 angles + 4 timing params |

`ratio` (`angleDataRatio`): 1 or 2 — angles are divided by it on storage if any
exceed 128, so multiply back on read. Petoi leg-column order
`[FLs,FRs,BRs,BLs, FLk,FRk,BRk,BLk]`; skill names end `F` (forward) or `L`
(turn-left); `R` variants are the L/R mirror (pure column swap, sagittal joints).

## Extracted references (`reference_gait/build_skill_reference.py`)

Generalises `build_wkf_reference.py` to any skill → `<name>_ref.npy`, shape
`(100, 8)`, radians, URDF joint order — same as `wkf_ref.npy`, so any is a
drop-in `FAC_IMITATION` anchor via `G2E_SKILL_REF=<name>` (env re-loads
`WKF_REF`/`STAND_POSE`; unset = wkF, byte-identical).

| ref | firmware | period | per-joint deg (min…max) | vs wkF | what it is |
|---|---|---|---|---|---|
| `wkf_ref` | `wkF` | 116 | knee-swing ≈ 42° | — | the standing walk (current anchor) |
| `cr_ref` | `crF` | 103 | shoulders 22…110, **knees −52…−29 (always flexed)** | **mean 34.8°** | **crawl — deep crouch, biggest coordination delta.** Best "add a skill" test anchor. |
| `tr_ref` | `trF` | 48 | knee-swing **48°** (widest) | mean 20.5° | trot — faster, bouncier, biggest foot lift |
| `vt_ref` | `vtF` | 37 | knees −22…9, higher shoulders | mean 11.7° | "step" — stiff marching step, *smaller* knee swing than wkF (not a high-step) |
| `bk_ref` | `bkF` | 43 | knee-swing 21° | mean 11.6° | backward walk |
| `rc_ref` | `rc` | 5 (behaviour) | knees to 200°, shoulders to −176° | mean 55° | **self-right keyframes** (approx — timing params dropped). Reference for the sim self-right work, not a locomotion gait. |

**Note for the adapter skill probe:** `cr` (crouch) is a better test skill than a
hand-tuned "high-step" `PAW_Z_TARGET` — it's a real firmware trajectory with the
largest limb-coordination difference from wkF, so it's the clearest yes/no on
"can a frozen base + adapter acquire a new skill." `tr` (trot) is the natural
second skill for the 2-skill control run. See `docs/rl/adapter-skill-probe-spec.md`.


## Pi UART (Serial-2) link — bring-up findings, 2026-09-30

- The BiBoard ignores the Pi's UART until the Serial module is enabled: send
  `XS` once over USB. `X?` prints the module table (`S,A,T,L,D,I,B,U,G,C,Q` and a
  `0/1` row); `S=1` means Serial-2 is on. It is persisted, so a reflash/erase
  wipes it -- redo `XS` (same class of post-reflash step as the voice-module fix).
  `XS` itself only echoes `X`; don't read silence as failure, check with `X?`.
- Serial-2 is `Serial2.begin(115200, SERIAL_8N1, UART_RX2=9, UART_TX2=10)` on
  BiBoard V1; when active it takes priority over USB for reading commands.
- Fastest link test, no motion: send `b16 10 12 12` from the Pi -- G2 chirps and
  the reply `b` comes back on the Pi's RX.
- **Framing differs from USB.** Over the Pi's UART the IMU stream's frames
  (`ICM: ...`) are terminated by a TAB, not a newline; only the `gP` echo line
  carries `\r\n`. `SerialLink._pop_record` splits IMU frames on tabs (non-IMU
  replies such as the `X?` table contain tabs and are left alone).
- Measured over the Pi's UART with the camera plugged into the Pi's USB: IMU
  exactly 5.0 Hz, so the camera on the Pi does not disturb the IMU (the
  camera-kills-IMU bug needs the BiBoard's own `XC` camera module).

## IMU calibration (`gc`) — needed for the firmware's gyro balance, 2026-10-01

- Symptom before calibrating: with firmware gyro balance ON (`gB`), `kbalance` made G2
  push its FR foot out and tilt the body ~19° roll / ~11° pitch (IMU-measured, steady);
  with balance OFF (`gb`) the same pose was level (roll -0.4°, pitch 1.7°). So the
  legs/servo calibration were fine and balance was chasing a wrong IMU zero. The
  `V2.1` learned-gait runs are unaffected -- `run_gait.py` turns balance off for the run.
- Fix: `gc` (`C_GYRO_CALIBRATE`) with G2 standing level and still. It silently runs a
  short routine in which the body rocks between the front and back legs for several
  seconds (no reply is printed, and the IMU readings jump during it -- wait it out).
- After: balance ON `kbalance` reads roll 0.8° / pitch -0.8° with std 0.2°; at rest the
  zero moved ~4° in roll (+0.9 -> -3.2). Redo after any reflash/erase. **Persists across a full
  power cycle** (checked 2026-10-01: balance-on `kbalance` still reads 1.0° / -1.1°).
- Anything using firmware balance (the scripted `kwkF` contender with gyro assist, voice
  skills, the `gB` that `run_gait` restores on exit) depends on this being calibrated.

## More bring-up facts (2026-10-01)

- `X?` prints the module table; the BiBoard's `?` prints only the name and version.
- `P` prints the battery voltage (`Voltage: 7.81 V`); readings lag a little and the pack read
  7.6-7.8 V (about half charge for a 2-cell pack) with no sag at a static stand.
- `f` (servo feedback) returned only an echo on this build, with the servos relaxed and powered, so
  real joint angles are not available through it.
- Petoi's `kcarpetF` gait, decoded (`reference_gait/carpet_ref.npy`): peak foot lift ~27 mm and stride
  ~36 mm vs scripted `wkF` ~9 mm / ~75 mm; it uses a different rest posture (shoulder mean ~61 deg,
  knee mean ~-11 deg vs ~47-53 / +6). On the real G2 it walked forward on hard floor (~1 ft 9 in in
  10 s) but walked in place on ~1/4 in carpet with the back-right leg sagging.
- While `gc` is running the IMU readings swing wildly and the body rocks; wait before reading it.


## Standing wobble (2026-10-04)

**Symptom:** standing on the calibration stand, G2 is steady at first (roll/pitch noise about 0.1 degrees), then (most often after rest, then stand; also after a nudge) swings in roll and pitch for a minute or more. It sometimes stops by itself.

**Measured with `gait/stand_log.py`** (passive: IMU print `gP` plus a `P` voltage read, no motion commands; the `g2-voice` service stopped so only one process uses the port). Logs: `~/g2_runs/stand01..05*.csv` on the Pi.
- Episodes: roll up to ~4-6 degrees and pitch up to ~9-11 degrees peak-to-peak; one sustained run settled into a steady cycle at **about 1.9 Hz** (roll, pitch and the accelerometer all agree), pitch ~±5 degrees by the accelerometer. At 5 Hz sampling, 1.9 Hz could also be an alias of ~3.1 Hz.
- It is **real body motion**, not an IMU glitch: a tilt computed from the accelerometer alone (gravity direction, independent of the firmware's fusion) swings as much or more than the fused roll/pitch.
- **Not the battery** (7.86-7.94 V throughout) and **not the Pi's periodic `P` read** (the service was off).
- **A/B with firmware gyro balance off (`gb`):** calm from the first second, and a deliberate nudge (6.7 degrees peak-to-peak) died out in under 10 seconds. With balance on, comparable nudges ring for 40+ seconds.
- Conclusion: the balance feedback loop, fed by an IMU that updates at 5 Hz (see the IMU rate notes above), is marginally stable and locks into a limit cycle once disturbed; some starts (a stand-up from rest) disturb it without any touch.
- Side notes: the firmware's accumulated yaw counter can jump by exactly 360 degrees mid-episode (an unwrap artifact; the wrapped yaw is unchanged), and the front-left shoulder servo's faults (see `rl/real-walk-log.md`) may make it easier to excite but are not needed to explain it.

**Fix (2026-10-04, `pi_pipeline/gait/stand_guard.py`):** (1) firmware gyro balance is kept off while G2 is idle: the voice service sends `gb` at start and every 60 s, and the serial actuator sends `gB` just before a firmware gait skill and `gb` just after it (and after rest or any posture); (2) a guard thread reads the 5 Hz IMU print and, if roll or pitch swings at least 0.8 degrees (standard deviation) with at least 4 mean-crossings per 4-second window for 4 s straight, sends `gb`. Replaying the five logs: it trips about 5 s after a wobble starts in every log that has one, and never on the balance-off log. It also catches stands started by the BiBoard's own voice module (those never pass through the Pi). Everything pauses while a gait runs, and for 8 s after any command the Pi sends. With `G2_BALANCE_OFF_IDLE=0` the guard re-enables balance (`gB`) after 5 minutes of quiet, doubling the wait if the wobble comes back within a minute. The service now opens ONE locked serial link shared by the actuator, the battery watch and the guard, and turns on the IMU print (`gP`) for the guard.
