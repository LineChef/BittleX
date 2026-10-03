# How OpenCat gaits are structured

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> the reference on how OpenCat gaits are structured. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Reference: how OpenCat gaits are structured

From `PetoiCamp/OpenCat` (AVR/NyBoard) and `PetoiCamp/OpenCatEsp32` (ESP32/BiBoard
— the actual Bittle X firmware). Background for Phase 3 (contrast with the RL
approach) and Phase 5 (sending commands).

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
- **Why it matters here:** this is the opposite of the RL approach. The trained
  policy needs its own runtime path to drive the same 8 walking servos — either
  bypassing the skill-array system or injecting learned frames in the same format
  — rather than selecting from `skillNameWithType`.
