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

## Other decoded OpenCat skills

`build_skill_reference.py <name>` parses any built-in skill from
`InstinctBittleESP.h` into the same `(N, 8)` rad / URDF-order format (gaits →
resampled to 100; behaviours → keyframes, approximate; `period == 1` postures →
`(1, 8)`). Decoded so far:

| ref | skill | what / used for |
|---|---|---|
| `tr_ref` `bk_ref` `wkl_ref` `wkr_ref` `vt_ref` `cr_ref` `rc_ref` `highstep_ref` | trot / back / turn-L/R / vault / crouch / recover / authored high-step | SkillSwitch gaits + get-up |
| `cmh_ref` | `cmh` climb (22 kf, 3× crawl loop) | Phase F climb base — **does not climb in sim** (see plan doc); kept for hardware |
| `carpet_ref` | `carpetF` | carpet-tuned walk — `CarpetDetector` (`pi_pipeline/gait/carpet.py`) recommends it on sustained slip |
| `buttUp_ref` | `buttUp` play-bow | **INSPECT peer pose** — holds a real +22° nose-down bow (a level `cr_ref` crouch did not); wired as `SkillRefs.inspect` |
| `jp_ref` | `jpF` jump forward | dynamic crouch-load-then-hop — expressive "excited" tell; untested obstacle-clear avenue |
| `str_ref` `sit_ref` `zz_ref` | stretch / sit / sleep postures | personality idle / sleep |
| `snf_ref` `scrh_ref` `nd_ref` `gdb_ref` `fiv_ref` `hi_ref` | sniff / scratch / nod / shake-paw / high-five / wave | expressive gestures — `pi_pipeline/behavior/gestures.py` decides when |

On hardware these are just `k<name>` serial calls (`pi_pipeline/link/opencat.py`);
the `_ref.npy` files are for sim replay / SkillSwitch.
