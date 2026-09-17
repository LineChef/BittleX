# Petoi OpenCat skills — what's worth pulling into G2

Survey 2026-09-08. Source: `rl_training/opencat-gym/reference_gait/InstinctBittleESP.h`
(local copy of OpenCat's built-in skill table). ~90 named skills. All callable on
the real robot as `k<name>` over serial (see `pi_pipeline/link/opencat.py`).
Format: header `[period, expRoll, expPitch, ratio]` — `period > 1` = looping gait,
`period < -1` = one-shot behaviour (`abs(period)` keyframes). Decode with
`reference_gait/build_skill_reference.py <name>` → `<name>_ref.npy` (radians, URDF
order), the same format the RL env / SkillSwitch consume.

## High value for this project

| skill | what it is | use for G2 |
|---|---|---|
| **`rc`** (recover) | scripted self-right, slow falls | already have `rc_ref.npy`; the firmware self-right the get-up work leans on. Pair with the FAC_BALANCE stumble-catch. |
| **`balance`** | **verified 2026-09-15, not what the name suggests.** Decoded directly from `InstinctBittleESP.h` + replayed in PyBullet: it's a static single-frame pose, all 8 leg joints to 30° — **byte-identical to `up`** (the neutral-stand pose). In sim the body drops *lower* and all 4 legs splay out/up, not a dynamic balancing act. Matches the community description of `kbalance` as a **calibration-check pose** (moves limbs symmetrically to verify servo calibration), not a trick. Already correctly used in code as the emergency-freeze/post-recovery settle token (`pi_pipeline/link/opencat.py` `BALANCE`, `pi_pipeline/behavior/emergency.py`) — that usage was already accurate. Only `pi_pipeline/voice/skills.py`'s Claude-facing description was wrong ("stand and actively balance") — corrected 2026-09-15 to "settle into a low, stable stand (same pose as 'stand')". **Does not produce the hind-leg-rearing "stand up" motion** seen in Petoi's `stand.gif` demo. See the `bx`/`showOff`/`chr`/`lucky` row below for the actual candidate check. |
| **`bx` / `showOff` / `chr` / `lucky`** | **Checked 2026-09-15 as two-legged-stand candidates — none confirmed.** Picked by name (`bx` = "box", `showOff`, `chr` = "cheer", `lucky`) after `balance` turned out not to be the trick, decoded + replayed each in PyBullet (spawn standing, play the keyframes, check final body height/pitch/roll): `showOff` and `chr` stand **taller and stiffer-legged but still on all 4 feet** (body height 0.087 m vs ~0.04 m normal stand) — not bipedal. `bx` and `lucky` both **tip the robot onto its back** in sim (roll → 180°) rather than settling into a balanced pose. **Inconclusive, not a clean no** — `bx`/`lucky` are dynamic, momentum-based tricks; a slow static keyframe-interpolation replay with no real foot friction is the same category of sim limitation that failed on the `cmh` climb keyframe (`docs/rl/hardware-gated-backlog.md` H7), not proof the real robot can't do them. **No stock Bittle skill confirms a working two-legged stand** — if wanted, treat as untested, hardware-gated, same status as `cmh`/climb: verify for real once the body's here, don't assume from firmware alone either way. |
| **`buttUp`** (play-bow / downward-dog) | posture, nose-down pitch +15° | the **INSPECT peer-pose** the sim couldn't hold — Petoi already tuned it. Port as the INSPECT scaffold (tilt camera down at a near obstacle). |
| **`carpetF` / `carpetL`** | walk gait tuned for **carpet** | directly targets the known "G2 stalls on carpet" problem. Decode + A/B vs `wkF` on the carpet cell. |
| **`str`** (stretch) | "just woke up" stretch posture | idle / wake behaviour for the autonomous layer. |
| **`snf`** (sniff) | head-down sniffing loop | **explore mode** — G2 sniffs around a new spot. |
| **`scrh`** (scratch) | dog scratching, nose-down | idle personality behaviour. |
| **`zz`** (zzz) | curl up to sleep | **sleep mode / idle-REST** (the user's power priority). |
| **`nd`** (nod) | head nod | acknowledgement / "yes" in the voice + personality loop. |
| **`sit`** | sit posture | idle, "stay", greeting. |
| **`gdb`** (give paw / shake) | offer a paw, nose-down | **"G2, meet X"** enrollment + bonds; social greeting. |
| **`fiv`** (high-five) / **`hi`** (wave) | social gesture | personality / interaction. |
| **`jpF`** (jump forward) | genuine dynamic crouch-load-then-hop | (a) an "excited" expressive move; (b) the *untested* dynamic path for clearing an obstacle on hardware, where static climb failed. |
| **`phF`** (pounce forward) | pounce | play behaviour; could pair with vision ball/target tracking. |
| **`hunt`** | seeking / hunting routine | tie into vision tracking / the avoider. |

## Lower priority / situational

> **Decision 2026-09-15 — no flipping or rolling behavior, mounted-payload
> risk.** G2 carries a Pi + PiSugar stack (~61–78 g, see
> [`specs.md`](specs.md) "Mounted payload weight") on a printed standoff
> bracket off the rear frame (`docs/build/biboard-pi-connector.md`), not
> the molded body shell — not built to survive a hard tumble/flip impact, and
> the extra elevated mass shifts G2's moment of inertia away from what these
> tricks were tuned for on a bare unit. **Excluded from `perform_skill` /
> voice / any built-in "do a trick" set:** `flip`, `flipD`, `flipF`, `bf`,
> `tbl` (tumble), `rl` (roll, as a trick — the get-up-chain use in `rc`/H9
> recovery work is unaffected, that's a fall-recovery path not a voluntary
> trick), `bx` ("box" — already observed tipping the sim robot onto its back,
> consistent with this concern), `lucky` (same tip-over behavior observed).
> Applies for the life of the Pi/PiSugar mount; revisit only if the mount is
> redesigned to be impact-rated.
>
> **`excited` skipped too (2026-09-15).** Investigated as a possible turn-in-place
> substitute (see `docs/project-plan.md`'s turning notes) — no confirmed
> firmware token, best-guess proxy was `tbl`-style bounce/rock, replayed in
> PyBullet with explicit yaw tracking: ~1° net yaw over 3 cycles, no real
> turning effect. Moot now anyway since its likely underlying motion is the
> same bounce/tumble category excluded above for payload risk. Turning stays
> on the already-working firmware path (`wkL`/`wkR`/`bk`, foot-slip + gyro
> assist).

- ~~`rl` (roll), `tbl` (tumble)~~ — **excluded, see note above.** `lnd` (land), `dropRec` (drop-recover) — recovery variants; useful if get-up work widens beyond `rc`.
- ~~`bf` / `flip`~~ — **excluded, see note above.** `ff` / `showOff` / `pu` / `pu1` / `clap` — acrobatic tricks / demos. Personality "do a trick" commands.
- **`mw` / `wh`** — the OpenCat sound-emote skills: a short body motion paired with a vocalisation. The voice layer already does TTS; these add body language.
- **`dg` (dig), `pee`** — comedic dog behaviours; explore/personality flavour.
- **`gpF/gpL` (gallop), `vtF` (vault), `bk*` (backward)** — extra locomotion; `bk_ref` already decoded. Gallop = a faster gait if top speed ever matters.
- **`kc` (kick), ~~`bx` (box)~~ (excluded, see note above), `toss`/`ts`** — object interaction; relevant only if a manipulation/play feature is added.

## Not relevant

- **`*ArmF` / `*ArmL`** (wkArmF, trArmF, crArmF, vtArmF, bkArmF), **`pick*` / `put*` / `gdb` arm variants**, **`lftF/lftL`, `hg` (hang), `hds`, `hsk`, `hu`, `knock`, `launch`, `lpov`, `lucky`, `ang`, `pd`, `ck`** — arm-equipped Bittle or unclear/one-off. G2 has no arm.

## How to bring one in

1. `python reference_gait/build_skill_reference.py <name>` → `<name>_ref.npy`.
2. For a **locomotion** skill (carpet, gallop): treat like `tr_ref` — a SkillSwitch
   `GaitMode` or a `deploy_map` gait token.
3. For a **posture / one-shot** (buttUp, str, snf, gdb, nd): drive it from the
   behaviour layer (`pi_pipeline/behavior/`) as a `k<name>` serial call on
   hardware, or via `_abs_joint_override` in sim; wire triggers (idle timer,
   explore state, person-detected, voice intent).
4. `rc` / recovery: integrate with `pi_pipeline/link/recovery.py` (the FallPose
   ladder already references `DROP_RECOVER`).
