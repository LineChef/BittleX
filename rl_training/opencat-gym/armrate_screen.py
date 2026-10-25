"""One 3M screen of the claw policy with the base walk played at its own pace (user, 2026-10-25): G2E_PHASE_RATE_NOM_CMD 0.064, the command at which Petoi's arm walk
really moves at one frame per step, so a 0.10 command plays it 1.56x faster and the base already goes the commanded speed (ARM1 played it at 1.0x, a 56% speed gap that the
policy closed with a longer reach: front shoulders 60-63 deg against Petoi's 55). Everything else is phase_arm's recipe.

    python armrate_screen.py        # train 3M as armrate, then score it into trained/arm_report/armrate.json
"""
import json
import os
import time

import phase_arm as A
import phase_v4 as P4
import run_pipeline as RP
import phase_v5 as V5

TAG, NOM = "armrate", "0.064"


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ["G2E_V5_LEDGE_TOP"] = V5.LEDGE_TOP
    A.set_base(A.ARM_REF)
    os.environ["G2E_PHASE_RATE_NOM_CMD"] = NOM
    out = f"trained/arm_report/{TAG}.json"
    if not os.path.exists(f"trained/{TAG}_ppo.zip"):
        A.log(f"{TAG} START: arm walk base at its own pace (PHASE_RATE_NOM_CMD {NOM}), claw payload, V7 recipe, 3M, about 23 min, done about {A.clock_in(23)}")
        RP.launch(TAG, P4.job_env(TAG, A.BASE6, 42, extra={"G2E_SKILL_REF": A.ARM_REF, "G2E_PHASE_RATE_NOM_CMD": NOM, "G2E_HEALTH_WARN_ONLY": "1"}), steps=V5.SCREEN_STEPS, base=False)
        ok, why = RP.wait_for_finish(TAG)
        if not ok:
            A.log(f"{TAG} FAILED: {why}")
            return
    t0 = time.time()
    res = A.score(f"trained/{TAG}_ppo", A.ARM_REF, 100, 40)
    os.makedirs("trained/arm_report", exist_ok=True)
    json.dump(res, open(out, "w"))
    A.log(f"{TAG} SCORED in {(time.time() - t0) / 60:.0f} min | {V5.summary(res)}")
    A.log(f"{TAG} COMPLETE")


if __name__ == "__main__":
    main()
