# High-step gait plan (opened 2026-10-10)

Goal: real extra ground clearance for G2 (cables, thresholds, rubble) behind the "hi step" voice mode, now that gait switching works (`pi_pipeline/gait/gait_mode.py`).

## Why a new gait is needed

Every scripted option so far is a knee-folded crouch or fell in the sim:

| Gait | Foot clearance (sim) | Result |
|---|---|---|
| normal walk (`wkF`) | 13.5 mm | the reference |
| `hsF` (what "hi step" plays today) | 17.8 mm | stays up open loop, but does not lift the feet; G2 does a crouching walk (user, 2026-10-10) |
| `hsB`, `hsC` | 25-27 mm | fell about 90% of episodes open loop |
| `carpetF` (firmware gait) | -- | tried on G2 2026-10-10, rejected by eye |

A tall step needs active balance, which is what a learned correction on top of a scripted base gives. The gait mode input, the voice switch and the mid-walk blend are already built; they wait for a policy trained for the mode (V6 sidecar has no `"modes"` key). Background: [`v6-staged-training-plan.md`](v6-staged-training-plan.md) "Track A / Track C".

## Path (user, 2026-10-10: "this is gonna be the path forward on getting some extra ground clearance")

1. **A better high-step base.** Two sources, both allowed by the no-LLM-authored-keyframes rule:
   - **Parameter sweep in the sim** of the generator (`rl_training/opencat-gym/reference_gait/build_highstep_reference.py`): shoulder lift, knee fold, rear boost, cycle time, stance width. Score with `gait_probe.py` (clearance, sway, falls, ledge ladders). Mac only.
   - **A hand-taught step** (puppeteering; decided 2026-10-10 after reading Petoi's Skill Composer, which only has sliders and never reads the joints back, so it is not used): our own tool, `pi_pipeline/gait/teach.py`. Two ways that work together: `hand` relaxes the servos, the user moves a leg, `grab` reads the eight angles from the servo feedback (`f`, else `j`); or `stand` then jog commands like `fl knee +5` / `fr shoulder 40`, each eased. `save` keeps a step. `check` proves the readback against the balance pose before it is trusted. Steps go to a JSON file, then `rl_training/opencat-gym/reference_gait/build_taught_step.py FILE --name N` makes `N_ref.npy`: a smooth closed path through the steps for the taught leg, copied to the other three legs with wkF's phase offsets (rear legs: wkF plus the taught change, or the taught angles with `--rear replace`). Open: the reply format of `f` / `j` is undocumented, so the first session starts with `raw` and `check`.
2. **Check the chosen base in the sim** (`gait_probe.py`) before G2 sees it.
3. **Track C, a fresh screening run** (3M cap; gate: the high step stays up, and the normal walk does not get worse) on that base: one network for both modes, about 20% of episodes in the opposite mode, some switching mid-episode, high step triggered by step-ups, rubble, boxes, snags and small thresholds. A 20M run only on the user's go. Never a continuation of a finished 20M.
4. **On G2** (on his feet on the floor, hands near; sim-only comparisons): short walks over a cable and the threshold strip, judged by eye; then deploy with `"modes": ["normal", "hi_step"]` in the sidecar.

## Needs from the user

- What G2 should step over and how tall it is (sets the clearance target; 25 mm is about 1 inch).
- Go for the sweep and for the Track C screening run.
- A teaching session (Block G of the hardware plan): the voice service stopped, G2 on his feet, hands near.

## After the hi-step: a climbing movement with the same method (user, 2026-10-10)

Once the hand-taught hi-step has walked on G2, the same method builds a movement for climbing obstacles (backlog B13 and B9). The hi-step is the trial run of the tooling (pose recorder, builder, sim check), so build the climb on what that taught us.
1. **Show the movement in key poses.** For a step up onto a box, hold G2 through the key poses by hand (or by direct jog commands if the joint read does not work): crouch low, rear up and plant both front feet on the box top, load the front legs and push with the rear legs, haul the body up, front feet forward, rear legs onto the box, stand on top. Each pose is recorded as eight joint angles.
2. **Build the sequence.** A one-shot movement (not a loop like the walk): the poses in order with the times between them, smooth between poses, with the stages the earlier climb work found (reach, plant, push, haul). The earlier scripted-base work (`rl_training/opencat-gym/crawl_climb.py`, the Petoi `cmh` reference) is a comparison, not a source of keyframes.
3. **Check it in the sim** on a box (start at 7.5 to 15 mm: nothing so far crosses above 7.5 mm), then raise the height one step at a time; look at the replay frames myself.
4. **Try it on G2 on the floor,** hands near, a low obstacle first (a book, 10 to 15 mm), judged by eye and logged.
5. **Voice and vision later:** a "climb" skill behind a voice command first; letting the vision estimator trigger it (an obstacle that is short and close, from the wall and obstacle estimator) only on the user's word.
Needs from the user: the obstacle heights that matter, and the first movement to teach (a step up onto a box is the plan). No policy training is part of this.
