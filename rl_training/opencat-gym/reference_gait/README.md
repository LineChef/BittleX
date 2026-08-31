# wkF reference gait (for the imitation reward)

Bittle's built-in `wkF` (walk-Forward) keyframe gait, extracted from OpenCatEsp32
so the RL policy can be rewarded for matching it (`FAC_IMITATION` in
`opencat_gym_env.py`).

- `InstinctBittleESP.h`, `skill.h` — vendored from `PetoiCamp/OpenCatEsp32@main`
  (the gait array + the header/format definition).
- `build_wkf_reference.py` — parses the 116-frame `wkF` array, remaps Petoi's
  joint-8..15 order `[FLs,FRs,BRs,BLs,FLk,FRk,BRk,BLk]` to the URDF's
  leg-interleaved `[FLs,FLk,FRs,FRk,BRs,BRk,BLs,BLk]`, converts deg->rad,
  resamples the cycle to 100 frames (= `TIME_PHASE_PERIOD`). Output: `wkf_ref.npy`.
- `verify_wkf_reference.py` — drives the URDF open-loop through `wkf_ref.npy` and
  scores sign/mirroring variants by forward distance + not falling.
  **Result: `identity` (direct mapping, no sign flips) walks +0.48 m over 4
  cycles without falling.** `wkf_openloop.gif` is that playback.
- `wkf_ref.npy` — (100, 8) float, radians, URDF joint order. Loaded by the env.

Rebuild: `python build_wkf_reference.py && python verify_wkf_reference.py`
