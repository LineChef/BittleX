# Petoi / OpenCat firmware reference

Confirmed from `PetoiCamp/OpenCatEsp32` source (the IMU serial
protocol and line format are re-verified against `main`), the
BiBoard/ESP32 firmware that runs on G2 (Bittle X). Captured so the
knowledge isn't lost between sessions. Verify against the repo if firmware
has moved on.

Repositories
------------

- `PetoiCamp/OpenCatEsp32` (aka `OpenCatEsp32-Quadruped-Robot`): **BiBoard/ESP32 firmware — this is G2's.**
- `PetoiCamp/OpenCat`: NyBoard/AVR firmware (older boards)
- `PetoiCamp/OpenCat-Old`: legacy

`OpenCatEsp32/src/`: `src.ino` (serial parser / main loop), `imu.h` + `mpu6050/`
(IMU fusion + exception detection), `reaction.h` (`dealWithExceptions()` — auto
recovery), `skill.h` (skill runtime — a copy is vendored at
`rl_training/opencat-gym/reference_gait/skill.h`), `InstinctBittleESP.h` (keyframe
data — vendored), `OpenCat.h` (token macros + config constants).

**No official Petoi RL/sim repo.** Petoi points to community work: `ger01d/opencat-gym`
(the lineage of `rl_training/opencat-gym`) and `ger01d/opencat-gym-sim2real`, plus
forum MuJoCo/Isaac efforts. The fork is already the canonical community base.

Serial command tokens (`OpenCat.h` `T_*` macros)
------------------------------------------------

Newline-terminated ASCII over UART. Confirmed set:

**Confirmed against the real BiBoard: commands produce more than
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

**A second layer: a real, undocumented
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

Onboard voice-recognition module (`X<letter>` commands)
-------------------------------------------------------

BiBoard V1 carries a built-in offline voice-recognition module + speaker
(`project-plan.md`'s parts notes), separate from the `T_*` command parser
above and not decoded from the project's own firmware source — confirmed instead
from [Petoi's official docs](https://docs.petoi.com/extensible-modules/voice-command-module)
and against the real board:

- `XAa`: set English as default language
- `XAb`: set Chinese as default language
- `XAc`: enable the voice module
- `XAd`: disable the voice module
- `XAe`: enter learning mode

Not blocked by `opencat.is_safe()` (only `c`/`cd` are). There's also a
physical dial switch on the bottom of the BiBoard extension hat (Bittle X
only) that must be set to "Voice Command" — unchecked here since the
module was otherwise responsive. Voice commands: "play sound" tests
liveness (replies with a "Do-Re-Mi" tone, works regardless of language --
tests only that it's not muted); "be quiet" mutes it; "bing bing" is the
spoken equivalent of `XAa` (switch to English).

Switching it on and off: speak to G2. **"Be quiet"** makes the module ignore basic commands such as "rest";
**"play sound"** turns them back on (Do-Re-Mi tone). Per Petoi's docs the module listens continuously with **no wake word**, has 40 fixed
commands (two languages) plus up to 10 you record yourself in learning mode; **"rest" is one of the fixed commands, "stop" is not.**
While it is on, a phrase meant for the Pi can also trigger it.

**Do NOT send `Xa` (lowercase) — or `XAd` — to "disable" it over serial.** The board only ever replies `X` to these, so there is no
confirmation, and the module's on/off state is saved in the board's settings across reboots. After `Xa` was sent, the module
kept listening and said "ok" to "stand up", but G2 did nothing, even after a reboot: voice commands had silently stopped working.
**`XA` (uppercase) fixed it** (voice commands worked again right after). Rule of thumb from `moduleManager.h`: `X` + uppercase letter
enables a module, `X` + lowercase disables it, and neither prints anything useful. Use the spoken switch above instead. Symptom to
remember: module answers "ok" but the body does not move → send `XA`, and check the dial on the hat is on "Voice Command".

**Known fault: the module can get stuck defaulting to Chinese, with voice commands unresponsive, for no identified trigger.** Matches a closed PetoiCamp/OpenCatEsp32-Quadruped-Robot PR
(#51) where an identical symptom on BiBoard V1.0 was root-caused to the
module getting stuck in a bad persistent armed state that survives
reboots/reflashes -- not a firmware bug, and the author's own code-level
fix attempt was a red herring. Recovery: send `XAc` (enable),
waiting ~1.2s, `XAb` (confirmed via its own reply: `Default language:
Chinese` -- so this *was* the stuck state), waiting ~1.2s, then `XAa`
(confirmed via reply: `Default language: English`). Verified working
after (both "play sound" and an actual English command). If this recurs,
this sequence is the first thing to try again before assuming a deeper
fault.

**A full erase and reflash wipes the language setting too.** The same fix applies right after a reflash and servo recalibration: `XAc` → `XAb` (confirmed stuck: `Default language:
Chinese`) → `XAa` (confirmed: `Default language: English`), then verified
live by voice again ("play sound" + an actual command). Not a new
incident — this module's state lives in the same EEPROM/NVS wiped by
`esptool erase_flash`, so re-applying this sequence is now an expected
step after any future full reflash, not a fault to re-diagnose.

- `k<skill>`: name: `T_SKILL`; meaning: run a named skill — `kwkF`, `ksit`, `kbalance`, `kcrF`, `ktrF`
- `m<idx> <deg> …`: name: `T_INDEXED_SIMULTANEOUS_ASC`; meaning: move joint(s), chainable — `m0 30 8 -35`
- `b<note> <dur> …`: name: `T_BEEP`; meaning: buzzer melody: pairs of (note, duration)
- `d`: name: `T_REST`; meaning: rest posture, servos off (ends a looping gait)
- `P`: name: `T_POWER`; meaning: **print battery voltage** — confirmed against the real BiBoard (`check_serial send P` → `Voltage: 8.02 V`, healthy for the 7.4 V 2S pack)
- `j` / `j <idx>`: name: `T_JOINTS`; meaning: **return all joint angles / one joint**
- `f`: name: `T_SERVO_FEEDBACK`; meaning: servo position feedback (if the servo chip supports it)
- `g`: name: `T_GYRO`; meaning: gyro function toggle (bare `g`)
- `gU` / `gu`: name: `C_GYRO_UPDATE` / `_OFF`; meaning: continuous gyro data update on/off (already **on by default from boot** — `updateGyroQ = true` is set during IMU init, so `gU` is rarely needed just to get data flowing)
- `gB` / `gb`: name: `C_GYRO_BALANCE` / `_OFF`; meaning: turn gyro balancing on/off
- `gc`: name: `C_GYRO_CALIBRATE`; meaning: calibrate the IMU
- `gP`: name: `C_PRINT` (in the `g`-context); meaning: **start CONTINUOUS 6-axis print** — sets `printGyroQ = true`, which is what actually makes `readEnvironment()` call `print6Axis()` every loop
- `gp`: name: `C_PRINT_OFF`; meaning: stop it — **NOT symmetric with `gP`**, this is "print once then stop", not a toggle; sending `gP` twice does not turn it off
- `p`: name: `T_PAUSE`; meaning: pause
- `t`: name: `T_TILT`; meaning: tilt command
- `c` / `cd`: name: calibration / factory; meaning: **never send from the pipeline**

- b<note> <dur> …: Note = semitone number, C3 = 14, C4 = 26, **1-35 is the usable range (loudest at the low end)**, 0 or -1 = rest. Duration = a divisor of one second (`b14 4` = note 14 for 1/4 s, **not milliseconds**), so a longer note is a smaller number. Chain as many pairs as fit; keep a token short (~60 chars). `b<1-10>` on its own sets the volume per Petoi's serial-protocol page (unconfirmed on this board, see the research note); a bare `b` toggles mute -- never send it


Confirmed: `v`/`V` is not a real token (no match anywhere in the command parser of the current `main` source). The board silently ignores it and streams *zero* IMU data, so `pi_pipeline/gait/run_gait.py` and `sysid_collect.py` start the IMU print with `gP` and stop it with `gp`, matching the `T_GYRO`+`C_PRINT` mechanism traced above.

IMU
---

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

### Confirmed serial line format (`imu.h` `print6Axis()`)

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

**No angular rate, 5 Hz ceiling — how the Pi side handles it.**
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

**Current firmware prints the IMU at 5.0 Hz.** `run_gait.py --probe-imu` on the real BiBoard (firmware `B10_260527`) measures exactly 5.0 Hz (25 lines in 5 s), the documented `PRINT6AXIS_MIN_INTERVAL` cap. An older build (`B10_251121`, a 2025-11 build) printed about 249 Hz raw (1246 lines in 5 s, of which 500 were distinct 6-axis values, about 100 Hz of distinct samples) and 93 Hz under the control loop's 80 Hz command stream (`--probe-imu-load`). The rate therefore depends on the firmware build: read the version with `?` before relying on it.
- Chip: The prefix is `ICM:` (ICM42670, not MPU6050).
- Units: `az` reads about 9.9 at rest, so the accelerometer is in m/s², not g.
- Banner: `?` prints a two-line banner, line 1 `Bittle X` and line 2 the version string. A single read takes only line 1 and leaves line 2 as backlog for the next read, the same class of bug as the `allmoves` desync described below.
- Reflash: A full flash erase and reflash to Petoi's current official firmware through the Desktop App is the fix for both the stale IMU timing and the camera bug described below.

Practical upshot: the walking policies are trained under the correct assumption for G2's current firmware (`IMU_HOLD_STEPS=16`, 5 Hz).

Onboard voice module + camera: EEPROM-persisted module state (`moduleManager.h`)
------------------------------------------------------------

Separate from the serial tokens above — a status/enable table for
BiBoard's extension modules, confirmed from `src/moduleManager.h`:

- `S`: module: Serial (Grove_Serial, i.e. Pi/UART2); letter: `B`; module: Backtouch
- `A`: module: Voice; letter: `U`; module: Ultrasonic
- `T`: module: Touch; letter: `G`; module: Gesture
- `L`: module: Light; letter: `C`; module: Camera
- `D`: module: infrared Distance; letter: `Q`; module: Quick_demo

Printed as `?`'s status dump: a header row of these letters, then a `0`/`1`
row (also reachable via `X`+letter, e.g. `XC`'s enable prints it). **`G`
here is Gesture, not Gyro/IMU** — easy to misread and chase the wrong flag
(the real mechanism is described below).

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

**The bug this causes: enabling Camera (`XC`) permanently
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
  was selected before).
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
- The Firmware Uploader's port dropdown draws only three rows; with more ports (Bluetooth ones) the BiBoard's can be hidden and the upload goes to
  `cu.debug-console`. Flash from the terminal with the app's own command instead.
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

**State after a full reflash:** the BiBoard runs the current official firmware (`B10_260527` at the time of writing, read from the `?` version banner). NVS/EEPROM is fully blank, so **calibration must be redone** and **the onboard voice module needs its English-default fix re-applied** (`XAc`/`XAb`/`XAa`, see the voice module section above), because both are EEPROM-persisted.

**Upstream firmware check.** `B10_260527` is about 6 weeks behind `main`'s newest firmware-code commit. Nothing in that gap affects the project: the camera-kills-IMU bug above is still present on `main` (a `camera.h` commit in the gap is a comment-only clarification); a `moduleManager.h` refactor that also touches Serial2 init resolves to the same pins (9/10) for `BiBoard_V1_0`, so there is no pinout regression; and the rest is an Xiaozhi-voice-UART echo feature (not applicable, because the project does not use a Xiaozhi module) and unrelated marketing and README commits.

**Voice-module language default.** `main` commit `9cf4e8d` changes `configConstants.h`'s factory EEPROM default for `EEPROM_CURRENT_LAN` from `'b'` (Chinese) to `'a'` (English), and a commit the same day (`b189c34`) simplifies `voiceSyncAtStartup()`'s language-sync logic (the `Ac->Ab->Aa` special case for English, which matches the project's own manual workaround, becomes a single `A<lan>` send).
The Petoi Desktop App cannot provide this fix: its release feed (`PetoiCamp/DesktopAppRelease`) tops out at v1.2.9, the version used for the reflash, which flashes the identical `260527` build. Reaching the fix would require building from raw GitHub source, which this project does not do (stock firmware only, app layer over serial).
The project stays on `260527`, applies the manual `XAc`/`XAb`/`XAa` workaround after every EEPROM wipe, and revisits this only if Petoi ships a Desktop App release newer than 1.2.9.

### Exception detection (`imu.h` `getImuException()`)

- `IMU_EXCEPTION_FLIPPED` (-1): `fabs(ypr[roll]) > 85°` **and** accel-Z near/below 0
- `IMU_EXCEPTION_LIFTED` (-2): `pitch < -50°` or `pitch > 75°`
- `IMU_EXCEPTION_KNOCKED` (-3): Z-axis accel shock vs previous frame
- `IMU_EXCEPTION_PUSHED` (-4): X/Y accel shock ≈ 4.9 g (X) / 7.3 g (Y)
- `IMU_EXCEPTION_FREEFALL` (-6) —
- `IMU_EXCEPTION_TURNING` (-7) —

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
- No retry / give-up logic if still flipped after `rc` finishes, the exception
  re-triggers next tick → effectively "keep trying `rc`" until upright or gyro off.

**Sim-fidelity gap (why self-right failed to train — see `self-righting-research.md`):**
the sim terminates the episode at 1.3 rad ≈ **74° tilt**, *below* the firmware's
85° `FLIPPED` line — the policy never sees the flipped state the real robot
recovers from. And the scripted `rc` keyframes were never an available action in
sim. Real-robot recovery = detect flip → scripted `rc` → repeat. To reproduce in
sim: raise/remove the tilt cutoff for a recovery window, and expose `rc_ref.npy`
(below) as a scripted action or imitation target.

How OpenCat gaits are structured
--------------------------------

From `PetoiCamp/OpenCat` (AVR/NyBoard) and `PetoiCamp/OpenCatEsp32` (ESP32/BiBoard, the actual Bittle X firmware). Background for how the learned gait differs from the scripted ones.

- Every named skill (walk, trot, crawl, sit, kick, …) is a **hand-authored
  keyframe animation** — a compact `const int8_t[] PROGMEM` array of servo angles,
  one per skill, in flash. `InstinctBittleESP.h` defines ~93 of them.
- Two parallel arrays connect it: `skillNameWithType[]` (e.g. `"wkFI"`, `"trFI"`,
  `"sitI"` — trailing `I`/`N` = Instinct/built-in vs. Newbility/user-taught) and
  `progmemPointer[]` (pointer to each skill's frames). A serial command like
  `kwkF` looks up the name and plays its frames.
- Each array's header encodes frame count/period and a direction/type flag. A
  positive period is a **looping gait** (walk, trot — cycled continuously, blended
  in real time with IMU balance correction via `gyroBalanceQ`); a negative period
  is a **one-shot behavior** (sit, push-up — some wait on an IMU trigger angle
  mid-sequence).
- 16 servo channels total: 4 for head/tail/gripper, 12 for the legs — 8 of those
  (shoulder + knee ×4) are `WALKING_DOF`, the joints gait keyframes drive.
- Why it matters here: this is the opposite of the RL approach. The trained
  policy needs its own runtime path to drive the same 8 walking servos — either
  bypassing the skill-array system or injecting learned frames in the same format
  — rather than selecting from `skillNameWithType`.

Skill keyframe format (`skill.h` `Skill::dataLen`)
--------------------------------------------------

`InstinctBittleESP.h` stores each skill as `const int8_t <name>[] PROGMEM = {…}`.

- `p > 1`: kind: **gait** (loops); header: 4 bytes `[period, expRoll, expPitch, ratio]`; frame: 8 int8 leg-joint angles (DOF 8..15)
- `p == 1`: kind: **posture**; header: 4 bytes; frame: 16 int8 full-DOF angles
- `p < -1`: kind: **behaviour**; header: 7 bytes `[period, expRoll, expPitch, ratio, loopStart, loopEnd, loopCycles]`; frame: 16 angles + 4 timing params

`ratio` (`angleDataRatio`): 1 or 2 — angles are divided by it on storage if any
exceed 128, so multiply back on read. Petoi leg-column order
`[FLs,FRs,BRs,BLs, FLk,FRk,BRk,BLk]`; skill names end `F` (forward) or `L`
(turn-left); `R` variants are the L/R mirror (pure column swap, sagittal joints).

Extracted references (`reference_gait/build_skill_reference.py`)
------------------------------------------------------------

Generalises `build_wkf_reference.py` to any skill → `<name>_ref.npy`, shape
`(100, 8)`, radians, URDF joint order — same as `wkf_ref.npy`, so any is a
drop-in `FAC_IMITATION` anchor via `G2E_SKILL_REF=<name>` (env re-loads
`WKF_REF`/`STAND_POSE`; unset = wkF, byte-identical).

- `wkf_ref`: firmware: `wkF`; period: 116; per-joint deg (min…max): knee-swing ≈ 42°; vs wkF: —; what it is: the standing walk (current anchor)
- `cr_ref`: firmware: `crF`; period: 103; per-joint deg (min…max): shoulders 22…110, **knees −52…−29 (always flexed)**; vs wkF: **mean 34.8°**; what it is: **crawl — deep crouch, biggest coordination delta.** Best "add a skill" test anchor.
- `tr_ref`: firmware: `trF`; period: 48; per-joint deg (min…max): knee-swing **48°** (widest); vs wkF: mean 20.5°; what it is: trot — faster, bouncier, biggest foot lift
- `vt_ref`: firmware: `vtF`; period: 37; per-joint deg (min…max): knees −22…9, higher shoulders; vs wkF: mean 11.7°; what it is: "step" — stiff marching step, *smaller* knee swing than wkF (not a high-step)
- `bk_ref`: firmware: `bkF`; period: 43; per-joint deg (min…max): knee-swing 21°; vs wkF: mean 11.6°; what it is: backward walk
- `rc_ref`: firmware: `rc`; period: 5 (behaviour); per-joint deg (min…max): knees to 200°, shoulders to −176°; vs wkF: mean 55°; what it is: **self-right keyframes** (approx — timing params dropped). Reference for the sim self-right work, not a locomotion gait.

Note for the adapter skill probe: `cr` (crouch) is a better test skill than a
hand-tuned "high-step" `PAW_Z_TARGET` — it's a real firmware trajectory with the
largest limb-coordination difference from wkF, so it's the clearest yes/no on
"can a frozen base + adapter acquire a new skill." `tr` (trot) is the natural
second skill for the 2-skill control run. See `docs/planned/adapter-skill-probe-spec.md`.


Pi UART (Serial-2) link — bring-up findings
-------------------------------------------

- The BiBoard ignores the Pi's UART until the Serial module is enabled: send
  `XS` once over USB. `X?` prints the module table (`S,A,T,L,D,I,B,U,G,C,Q` and a
  `0/1` row); `S=1` means Serial-2 is on. It is persisted, so a reflash/erase
  wipes it -- redo `XS` (same class of post-reflash step as the voice-module fix).
  `XS` itself only echoes `X`; don't read silence as failure, check with `X?`.
- Serial-2 is `Serial2.begin(115200, SERIAL_8N1, UART_RX2=9, UART_TX2=10)` on
  BiBoard V1; when active it takes priority over USB for reading commands.
- Fastest link test, no motion: send `b16 10 12 12` from the Pi -- G2 chirps and
  the reply `b` comes back on the Pi's RX.
- Framing differs from USB: Over the Pi's UART the IMU stream's frames
  (`ICM: ...`) are terminated by a TAB, not a newline; only the `gP` echo line
  carries `\r\n`. `SerialLink._pop_record` splits IMU frames on tabs (non-IMU
  replies such as the `X?` table contain tabs and are left alone).
- Measured over the Pi's UART with the camera plugged into the Pi's USB: IMU
  exactly 5.0 Hz, so the camera on the Pi does not disturb the IMU (the
  camera-kills-IMU bug needs the BiBoard's own `XC` camera module).

IMU calibration (`gc`) — needed for the firmware's gyro balance
--------------------------------------

- Symptom before calibrating with firmware gyro balance ON (`gB`), `kbalance` made G2
  push its FR foot out and tilt the body ~19° roll / ~11° pitch (IMU-measured, steady);
  with balance OFF (`gb`) the same pose was level (roll -0.4°, pitch 1.7°). So the
  legs/servo calibration were fine and balance was chasing a wrong IMU zero. The
  `V2.1` learned-gait runs are unaffected -- `run_gait.py` turns balance off for the run.
- Fix: `gc` (`C_GYRO_CALIBRATE`) with G2 standing level and still. It silently runs a
  short routine in which the body rocks between the front and back legs for several
  seconds (no reply is printed, and the IMU readings jump during it -- wait it out).
- After: balance ON `kbalance` reads roll 0.8° / pitch -0.8° with std 0.2°; at rest the
  zero moved ~4° in roll (+0.9 -> -3.2). Redo after any reflash/erase. **Persists across a full
  power cycle** (checked: balance-on `kbalance` still reads 1.0° / -1.1°).
- Anything using firmware balance (the scripted `kwkF` contender with gyro assist, voice
  skills, the `gB` that `run_gait` restores on exit) depends on this being calibrated.
