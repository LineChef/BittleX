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

- **`rl`** (roll), **`tbl`** (tumble), **`lnd`** (land), **`dropRec`** (drop-recover) — recovery variants; useful if get-up work widens beyond `rc`.
- **`bf` / `ff` / `flip` / `showOff` / `pu` / `pu1` / `clap`** — acrobatic tricks / demos. Personality "do a trick" commands.
- **`mw` / `wh`** — the OpenCat sound-emote skills: a short body motion paired with a vocalisation. The voice layer already does TTS; these add body language.
- **`dg` (dig), `pee`** — comedic dog behaviours; explore/personality flavour.
- **`gpF/gpL` (gallop), `vtF` (vault), `bk*` (backward)** — extra locomotion; `bk_ref` already decoded. Gallop = a faster gait if top speed ever matters.
- **`kc` (kick), `bx` (box), `toss`/`ts`** — object interaction; relevant only if a manipulation/play feature is added.

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
