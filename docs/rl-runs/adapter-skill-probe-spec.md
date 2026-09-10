# Adapter skill probe — implementation spec

**Status:** SPECCED, NOT BUILT. Lives on `development` (this doc only, no code).
The throwaway `adapter-skill-probe` branch was deleted 2026-09-07 — it only ever
held an older copy of this spec. Deferred; resume by branching fresh from
`development`. Phase D A/B still running (see `vision-goal-locomotion-plan.md`
START HERE) and is unaffected.

Note: `cr_ref.npy` / `tr_ref.npy` and the `G2E_SKILL_REF` env hook this spec
needs are already committed on `development` (commit b45b726).

---

## Why

Phases A/C proved a **full finetune** of a grafted base fails here (reward −72%,
goal-reach 0%). This probe tests a different recipe: **freeze the base, train only
a small added adapter module.** The base cannot forget because its weights never
move. If this works, the project architecture becomes "one stable base + cheap
per-skill adapters" — every future capability is a ~2M run, not a 20M gamble.

Decides the post-Phase-D direction. Does **not** replace Phase D — both
architectures need Phase D's "does the terrain feature give real leverage" answer,
and `abD_blind` is a reusable cluttered-course baseline / base-init candidate
either way.

## Three runs

| tag | what | steps | purpose |
|---|---|---|---|
| `probe_ref` | from scratch, single skill (high-step only) | 2e6 | yardstick — what learning this skill looks like with nothing competing |
| `probe_adapterA` | frozen `run20m_ppo` + zero-init adapter, **adapter-only** training, high-step skill | 2e6 | the actual test |
| `probe_ctrlB` | from scratch, 2-skill (normal + high-step, per-episode one-hot) | 3e6 | control — can a net of this class hold skill + normal, both intact |

`probe_ref` is the shared yardstick both A and B are measured against (A-vs-B
head-to-head is NOT a controlled comparison — different init/params/budget — and
was never meant to be; each run's binary yes/no is what feeds the 2×2).

## Skill = crouch-walk (anchored to the firmware `cr` gait)

**Updated 2026-09-07:** use the built-in OpenCat `crF` (crawl) trajectory as the
skill target, not a hand-tuned `PAW_Z_TARGET` high-step. Reasons:
- `cr_ref.npy` (from `reference_gait/build_skill_reference.py crF`) is a real
  firmware trajectory with the **largest limb-coordination difference from wkF**
  of any built-in gait (mean 34.8° / joint; knees held flexed −52…−29° the whole
  cycle) — the clearest possible yes/no on "can a frozen base + adapter acquire a
  genuinely different gait."
- No new reward term: it's a drop-in `FAC_IMITATION` anchor via `G2E_SKILL_REF=cr`
  (the env re-loads `WKF_REF`/`STAND_POSE`; unset = wkF, byte-identical).
- `tr` (trot, `tr_ref.npy`, widest foot lift) is the natural **second** skill for
  the 2-skill control run.
- The earlier "high-step" pick was based on `vt` — but extraction showed `vtF` is
  a stiff *marching* step with a *smaller* knee swing than wkF, not a high-step.
  See `docs/research/petoi-firmware-reference.md`.

Mechanism: `SKILL_MODE` appends one obs float `skill ∈ {0,1}` (per-episode). When
`skill == 1`, the imitation anchor is `cr_ref.npy` and `STAND_POSE` follows it;
when 0, it's `wkF`. The policy learns to switch gait on the bit.

### Env changes (`opencat_gym_env.py`) — follow the `_g2e` pattern, all default-off = byte-identical

New knobs near the other `_g2e` blocks (~line 455):
```
SKILL_MODE            = _g2e("SKILL_MODE", False)      # master switch; off => obs + reward unchanged, run20m_ppo byte-identical
SKILL_HIGHSTEP_TARGET = _g2e("SKILL_HIGHSTEP_TARGET", 0.045)  # raised swing-foot target when skill active (nominal PAW_Z_TARGET = 0.020)
SKILL_PROB            = _g2e("SKILL_PROB", 1.0)        # per-episode prob the skill is active; 1.0 = single-skill, 0.5 = 2-skill
```

Obs (1 float appended, AFTER terrain/goal/cliff so ordering stays stable):
- `__init__` (~line 547): `_n_obs = SIZE_OBSERVATION + (4 if TERRAIN_FEATURE else 0) + (4 if GOAL_MODE else 0) + (3 if CLIFF else 0) + (1 if SKILL_MODE else 0)`
- `reset()` (~line 1326): sample `self._skill_highstep = float(np.random.rand() < SKILL_PROB)` (only when SKILL_MODE; else attr = 0.0)
- Both obs assembly points — `step()` `np.hstack` (~line 1256) and `reset()` `np.concatenate` (~line 1681): append `[self._skill_highstep]` when SKILL_MODE. **Check both; they are separate code paths.**

Reward (~line 685–688, the `paw_clearance` accumulation):
```
_pz_target = SKILL_HIGHSTEP_TARGET if getattr(self, "_skill_highstep", 0.0) > 0.5 else PAW_Z_TARGET
paw_clearance += (paw_z_pos - _pz_target)**2 * np.linalg.norm(...)
```
Existing `FAC_CLEARANCE * paw_clearance` term does the rest.

## Adapter policy (`adapter_policy.py` + `train_adapter.py`)

- **Base:** `run20m_ppo` (278-d, blind). Probe env with `SKILL_MODE=1` is 279-d.
  First widen the base with the graft mechanism (1 zero column) so the frozen base
  ignores the skill dim:
  `env G2E_SKILL_MODE=1 python graft_terrain_policy.py --src trained/run20m_ppo --dst trained/run20m_graft279_skill`
  (graft already parity-checks; expect max|Δaction| < 1e-4.)
- **Adapter module:** small MLP `[279 → 64 → 64 → 8]`, final layer weight+bias
  **zero-init**. Reads the full obs (incl. skill bit).
- **Policy:** subclass `stable_baselines3.common.policies.ActorCriticPolicy`.
  `action_mean = frozen_base_action_path(obs) + adapter(obs)`.
  Freeze `features_extractor`, `mlp_extractor`, `action_net`. Trainable: adapter +
  the whole value path (`mlp_extractor` vf side is shared — simplest is to let the
  value path train; it is not deployed, harmless).
- **log_std:** RESET to `log(0.3)` at init and leave trainable. The converged base
  std is ~0 → zero exploration for the new skill → Run A cannot learn without this.
- **Parity check (before any training):** with adapter zeroed, `action_mean` must
  equal base `action_mean` to < 1e-5 over N random obs. Mirror the check loop in
  `graft_terrain_policy.py`.
- **Smoke:** ~2k steps `DummyVecEnv`; assert base params unchanged and adapter
  params changed after one update. Then commit.

## Driver `run_adapter_probe.sh` (mirror `run_ab_vision.sh`)

```
SKILL_CFG="G2E_SKILL_MODE=1 G2E_SKILL_HIGHSTEP_TARGET=0.045"
# 1. reference
env $SKILL_CFG G2E_SKILL_PROB=1.0 $PY train.py --tag probe_ref --steps 2e6
# 2. graft + adapter
env $SKILL_CFG $PY graft_terrain_policy.py --src trained/run20m_ppo --dst trained/run20m_graft279_skill
env $SKILL_CFG G2E_SKILL_PROB=1.0 $PY train_adapter.py --base trained/run20m_graft279_skill --tag probe_adapterA --steps 2e6
# 3. control
env $SKILL_CFG G2E_SKILL_PROB=0.5 $PY train.py --tag probe_ctrlB --steps 3e6
# evals (all to trained/adapter_probe_eval.txt):
#  - skill acquisition: swing-foot peak height, skill-on vs skill-off, each run vs probe_ref
#    (new eval_skill_highstep.py: ~20 ep, per-foot swing apex; or extend eval_obstacle_response.py)
#  - regression: benchmark_decathlon.py each, OBSTACLE-FREE / cruise cells only (skill-off), vs run20m_ppo
#  - Run A ablation: base-alone vs base+adapter on cruise cells (skill-off) -- adapter must not disturb flat-ground gait
say "=== ADAPTER PROBE COMPLETE ==="
```
Log → `trained/adapter_probe_results.log`. Milestone lines: `probe_ref done`,
`probe_adapterA done`, `probe_ctrlB done`, `ADAPTER PROBE COMPLETE`.

## Verdict (2×2)

| A learns skill | B learns skill | Read |
|---|---|---|
| yes | — | **adapters viable** → architecture = stable base + cheap per-skill adapters |
| no | yes | base too specialized → need a fresh **multi-skill base** first (seed from `run20m_ppo`), then adapters on that |
| no | no | skill too hard at this budget OR this net class can't hold it → rethink the target skill, not the architecture |

Run A must ALSO show ~0 regression on the obstacle-free cells (expected by
construction with a frozen base — confirm it).

## Relationship to Phase D and the planned Tier-B 20M

Deferring this probe costs nothing from Phase D. `abD_vision` / `abD_blind` are
durable checkpoints; they wait. When the probe is built:
- **Frozen base:** prefer `abD_blind` over `run20m_ppo` if Phase D shows it is a
  strong cluttered-course walker with no obstacle-free regression — it has already
  seen ledges/rubble/slopes/tall obstacles and carries the anti-stall behaviour.
- **Test skill:** let the Phase D result pick it — `high-step` if low obstacles
  are the gap, `brace/slow` if tall ones are.

**Downstream payoff:** if this probe says adapters are viable AND Phase D says
vision wins, design Tier B's fresh ~20M as the **multi-skill base** from step 0
(skill-code input + skill distribution). The base gets built for the cost of a run
already planned, instead of a separate 20M later. Requires the cheap probe to run
first — which is this plan.

## Report

ONE HTML artifact covering **both** Phase D and the adapter probe. Reuse
`tools/build_decathlon_report.py` style (verdict banner, per-cell scorecard,
embedded GIFs). Sections: (1) Phase D vision-vs-blind verdict, (2) adapter probe
2×2 + skill-acquisition plot + regression check, (3) architecture recommendation.

## Resume checklist

1. `git checkout development && git pull && git checkout -b adapter-skill-probe`
2. Env knobs per "Env changes" above; grep-verify both obs assembly points.
3. `adapter_policy.py` + `train_adapter.py`; parity check → smoke → **commit**.
4. `run_adapter_probe.sh`; run only after Phase D compute is free; arm a Monitor on
   `trained/adapter_probe_results.log`.
5. On `ADAPTER PROBE COMPLETE`: build the combined report; update
   `docs/project-plan.md` + memory; decide architecture per the 2×2.

## State at spec time (2026-09-07, updated ~11 PM ET)

No adapter policy / training code written. Prereqs that ARE done on `development`
(commit b45b726): `reference_gait/build_skill_reference.py`, `cr_ref.npy` /
`tr_ref.npy` / `vt_ref.npy` / `bk_ref.npy` / `rc_ref.npy`, and the
`G2E_SKILL_REF` env hook (swaps the `FAC_IMITATION` anchor; unset = wkF,
byte-identical). Phase D A/B running (`run_ab_vision.sh`, ETA early Tue 09-08).
`run20m_ppo` frozen fallback untouched.
