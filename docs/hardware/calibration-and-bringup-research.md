# Calibration & first-power-on: research from Petoi's official docs

Pre-build research (Bittle X hasn't arrived yet) — cross-checking our own
bring-up plan (`pi_pipeline/bringup.py`, `docs/project-plan.md` "When the
hardware arrives") against Petoi's official Bittle X V2 user manual and doc
center, to catch gaps before the stand-only bring-up starts. Genuinely new
findings only; anything already correctly captured elsewhere (e.g. BiBoard
V1 vs V0 wiring, already right in `build/biboard-pi-connector.md`) isn't
repeated here.

## 1. "Ships calibrated" is optimistic — it's actually "coarse-tuned"

`bringup.py` step 1 currently says Bittle X "ships calibrated; only
fine-tune if movement looks off once it's together." The official unboxing
page is more direct: **pre-assembled units are only coarse-tuned** —
calibration is called out as still needed for good performance, not framed
as optional/only-if-it-looks-wrong.

**Action**: treat step 3 (range-of-motion + calibration) as an expected,
routine pass, not a conditional one — go in planning to do it, not planning
to skip it.

## 2. Joints must be set to a specific "bootup posture" before power-on

Confirmed from the official unboxing steps: joints need to be in the
correct bootup posture *before* the battery is switched on, not just at
rest in whatever position they happen to be. The bootup posture is the
neutral/centered position all servos expect at power-up — the manual shows
this visually (diagram, not text) on the unboxing page. **Look at the
actual diagram at bring-up time** (`bittle-x.petoi.com/2-open-the-box`) to
match the posture by eye before that first battery long-press — don't
just power on however the joints happen to sit out of the box.

## 3. Powering on with the robot "one side up" auto-enters calibration mode

Robots manufactured after 2022 (which covers Bittle X V2) will boot
directly into calibration mode if powered on while tilted onto one side.
This is one of five ways into calibration mode:

1. **Boot gesture** — long-press the battery button while the robot is
   tilted "one side up."
2. **Petoi mobile app** — calibration panel, needs the app paired first.
3. **Petoi Desktop App** — "Joint Calibrator" button.
4. **Arduino IDE serial monitor** — type `c` and send.
5. **IR remote** — row 3, column 3 (Bittle X V2 / BiBoard V1 has **no** IR
   receiver per `hardware/self-righting.md`, so this one's not available to
   us).

**Relevant to us**: method 4 confirms the actual serial token is bare `c`,
not `c16` — `bringup.py` and `project-plan.md` both currently say `c16`.
Worth a quick correction, or at minimum verifying against the real BiBoard
once serial is up (`check_serial` already refuses both `c` and `cd`
prefixes by design, so this doesn't change any code — just the docs/step
text). Method 1 (the boot-gesture route) is also worth keeping in mind as a
recovery path if the app/serial link isn't working yet but a calibration
check is needed — it needs nothing but the robot and a flat-ish surface to
tilt it on.

## 4. Do NOT attach legs before first entering calibration mode — for from-scratch calibration only

The official joint-calibration doc has a specific warning: entering
calibration mode with legs already mounted on the servo horns risks legs
swinging into each other or the body as the servos power up into arbitrary
positions, which can jam/damage a servo if something gets physically stuck.

**This does not apply to us directly** — Bittle X V2 here is the
pre-assembled unit, and Petoi's own calibration page confirms pre-assembled
units do *not* need the head/legs detached for calibration touch-ups (the
app's +/- buttons just nudge already-mounted joints). The warning matters
only if a joint ever needs re-seating on its horn (e.g. after a servo
swap) — in that specific case, detach the leg, enter calibration mode
first, align, and only then re-attach, rather than powering on with a
loose/misaligned leg already on.

## 5. New-unit servo gears can feel "stuck" — this is a protection algorithm, not a fault

If a leg doesn't move despite a correct, received command, the official
docs say this is expected on a fresh unit: tight new gears can trigger a
servo protection algorithm that reduces force on the joint (matches what's
already noted independently in `hardware/servo-thermal.md` for the thermal
case — same protection mechanism, different trigger). Fix: rotate the
joint by hand with moderate, deliberate resistance until it "unsticks" /
seats properly, before assuming it's a wiring or command problem.

**Action**: add this as the first thing to check during step 3's
range-of-motion pass if any single joint seems unresponsive or weak —
before touching wiring, serial config, or firmware.

## 6. Two small mechanical notes worth having on hand at assembly time

- **Neck cable routing**: route the neck cable from the knee side toward
  the shoulder side when reassembling/servicing — routing it the other way
  risks pinching against the frame during head movement.
- **Silicone toe covers**: leave them off for normal indoor walking/testing
  — they're for extra grip on specific slick-surface tasks, and otherwise
  amplify surface irregularities (more stumbles on uneven carpet, not
  fewer). Relevant directly to the still-open carpet-mode work
  (`project_carpet_mode` memory) — toe covers would be a confound, not a
  fix, for carpet slip.

## What this changes in our plan

Nothing structural — Phase 0's stand-only sequence
(assemble → range-of-motion → calibrate → `firstmove` → `allmoves`) already
matches the official order. The concrete deltas:

- [ ] Update `bringup.py` step 1/3 wording: calibration is routine, not
      conditional (§1).
- [ ] At step 2 (joints before power-on), actually pull up
      `bittle-x.petoi.com/2-open-the-box`'s bootup-posture diagram rather
      than eyeballing a "neutral-looking" pose (§2).
- [ ] Correct `c16` → `c` in `bringup.py` / `project-plan.md` step text, or
      verify the real token once serial is confirmed (§3) — `check_serial`
      itself already blocks both by design, so this is docs-only.
- [ ] Note the boot-gesture calibration entry (§3, method 1) as a fallback
      if serial/app access isn't working yet.
- [ ] Add the "gears feel stuck = protection algorithm, rotate by hand
      first" check to step 3's range-of-motion pass, before assuming a
      wiring/firmware problem (§5).

## Sources

- [2 Open the Box — Bittle X User Manual](https://bittle-x.petoi.com/2-open-the-box)
- [3 Assembling & Board Setup — Bittle X User Manual](https://bittle-x.petoi.com/3-assembling-and-board-setup)
- [4 Calibration — Bittle X User Manual](https://bittle-x.petoi.com/4-calibration)
- [6 Calibration — Bittle User Manual](https://bittle.petoi.com/6-calibration) (same calibrator interface as Bittle X, more detail on the procedure itself)
- [Bittle app guide — Petoi Doc Center](https://docs.petoi.com/mobile-app/app-guide/bittle)
- [Petoi Doc Center home](https://docs.petoi.com/)
