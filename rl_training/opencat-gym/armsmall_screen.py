"""One 3M screen of the claw policy held close to Petoi's arm walk and level (user, 2026-10-25): ARM1R rolled 7+ deg on hardware (Petoi's walk 3.5) with the front shoulders at 56 deg.
The reward had almost nothing against roll (tilt^2 x 3: 0.03 per step at 6 deg) and a soft imitation term (a 7 deg over-reach cost 0.26 of 16). This screen changes only those:
  IMITATION_SHARPNESS 2 -> 8   a 7 deg over-reach on both front shoulders now costs about 1 point
  FAC_ROLL 100, FAC_ROLL_RATE 5   roll angle^2 and roll rate^2, ramped with the other penalties
  RESIDUAL_SCALE_DEG 30 -> 15   the policy can stray at most 15 deg from the base walk
  BODY_MASS_SCALE 0.944 -> 1.0555   the real G2 with the arm weighs 532 g (sim 502 g); the 30 g goes on the body (front weight share already matches: 52.6% real)
Base walk, payload, recipe and the 0.064 playback pace are ARM1R's.

    python armsmall_screen.py        # train 3M as armsmall, then score it into trained/arm_report/armsmall.json
"""
import json
import os
import time

import phase_arm as A
import phase_v4 as P4
import run_pipeline as RP
import phase_v5 as V5

TAG = "armsmall"
CHANGES = {"G2E_PHASE_RATE_NOM_CMD": "0.064", "G2E_IMITATION_SHARPNESS": "8", "G2E_FAC_ROLL": "100", "G2E_FAC_ROLL_RATE": "5",
           "G2E_RESIDUAL_SCALE_DEG": "15", "G2E_BODY_MASS_SCALE": "1.0555"}
PHYSICS = ("G2E_PHASE_RATE_NOM_CMD", "G2E_RESIDUAL_SCALE_DEG", "G2E_BODY_MASS_SCALE")


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    A.set_base(A.ARM_REF)
    os.environ.update(CHANGES)                    # the trainer and the scorers read the physics (mass, residual scale, pace) from this process
    os.environ["G2E_SCORE_OVERRIDES"] = ",".join(f"{k}={CHANGES[k]}" for k in PHYSICS)     # ... and the scoring profile, ladder workers included, takes them over its own
    out = f"trained/arm_report/{TAG}.json"
    if not os.path.exists(f"trained/{TAG}_ppo.zip"):
        A.log(f"{TAG} START: arm walk held close (imitation sharpness 8, roll terms, residual 15 deg), 532 g claw world, 3M, about 23 min, done about {A.clock_in(23)}")
        RP.launch(TAG, P4.job_env(TAG, A.BASE6, 42, extra={"G2E_SKILL_REF": A.ARM_REF, "G2E_HEALTH_WARN_ONLY": "1", **CHANGES}), steps=V5.SCREEN_STEPS, base=False)
        ok, why = RP.wait_for_finish(TAG)
        if not ok:
            A.log(f"{TAG} FAILED: {why}")
            return
    t0 = time.time()
    res = A.score(f"trained/{TAG}_ppo", A.ARM_REF, 100, 40)
    os.makedirs("trained/arm_report", exist_ok=True)
    json.dump(res, open(out, "w"))
    A.log(f"{TAG} SCORED in {(time.time() - t0) / 60:.0f} min | {V5.summary(res)}")
    # ARM1R (residual 30) in the same 532 g world, so the two compare on one body
    os.environ["G2E_RESIDUAL_SCALE_DEG"] = "30"
    os.environ["G2E_SCORE_OVERRIDES"] = "G2E_PHASE_RATE_NOM_CMD=0.064,G2E_RESIDUAL_SCALE_DEG=30,G2E_BODY_MASS_SCALE=1.0555"
    t0 = time.time()
    res = A.score("trained/armr_s4_ppo", A.ARM_REF, 100, 40)
    json.dump(res, open("trained/arm_report/armr_532g.json", "w"))
    A.log(f"ARM1R at 532 g SCORED in {(time.time() - t0) / 60:.0f} min | {V5.summary(res)}")
    A.log(f"{TAG} COMPLETE")


if __name__ == "__main__":
    main()
