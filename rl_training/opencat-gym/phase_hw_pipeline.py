"""Top-level driver for the real-hardware-IMU retrain (2026-09-28), chained
unattended per user instruction ("make sure these tests continue with out
intervention from you"):

  1. phase_r5_hw_sequential.py -- full staged 20M base run (Release_CandidateV2.1's
     recipe, with G2E_IMU_HOLD_STEPS corrected 16->1 to match the real IMU rate
     measured this session). Benchmarks itself against Release_CandidateV2.1's
     historic report only (trained/phase_yaw_tuning_report.json), per explicit
     user instruction -- does not re-run V2.1's benchmark.
  2. Gate: only if r5_hw beats-or-ties V2.1 on every category AND its yaw RMS
     is still elevated vs V2.1's own number does step 3 run. If r5_hw doesn't
     beat/tie V2.1, or yaw is already fine, step 3 is skipped -- either way
     the final report says so explicitly, per user instruction to report this.
  3. phase_r6_hw_yaw.py -- conditional yaw/drift tuning round, same shape as
     the process that produced V2.1 (3M lever screen -> winner to 10M).

Each subprocess is a separate `python phase_X.py` invocation (matching
run_pipeline.py's own phase_b() pattern) so state never bleeds between stages.
A STOP sentinel (rl_training/opencat-gym/STOP) is checked between stages,
same convention as docs/guides/automated-testing-loop.md.

    python phase_hw_pipeline.py
"""
import json
import os
import subprocess
import time

PY = "../../.venv/bin/python"
LOG = "trained/phase_hw_pipeline.log"
STOP_FILE = "STOP"


def log(msg):
    line = f"[hwpipe {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _stopped():
    if os.path.exists(STOP_FILE):
        log(f"STOP sentinel found ({STOP_FILE}) -- halting between stages, per "
            "docs/guides/automated-testing-loop.md convention")
        return True
    return False


def main():
    log("=== hw-imu retrain pipeline started ===")

    if not os.path.exists("trained/phase_r5_hw_gate_decision.json"):
        log("Stage 1: launching phase_r5_hw_sequential.py (base 20M run)")
        r = subprocess.run(f"{PY} phase_r5_hw_sequential.py", shell=True)
        if r.returncode != 0:
            log(f"Stage 1 FAILED (exit {r.returncode}) -- see trained/phase_r5_hw_sequential.log")
            return
    else:
        log("Stage 1: trained/phase_r5_hw_gate_decision.json already exists -- skipping "
            "(resume case; delete it to force a re-run)")

    if not os.path.exists("trained/phase_r5_hw_gate_decision.json"):
        log("Stage 1 did not produce a gate decision (likely failed its own 20M gate) -- "
            "stopping here, no tuning stage, no final report.")
        return

    gate = json.load(open("trained/phase_r5_hw_gate_decision.json"))
    log(f"Stage 1 gate decision: {gate}")

    if _stopped():
        return

    run_tuning = gate["beats_or_ties_v21"] and gate["yaw_needs_work"]
    if run_tuning:
        log("Stage 2: r5_hw beats/ties V2.1 AND yaw still needs work -- "
            "launching phase_r6_hw_yaw.py (conditional tuning round)")
        r = subprocess.run(f"{PY} phase_r6_hw_yaw.py", shell=True)
        if r.returncode != 0:
            log(f"Stage 2 FAILED (exit {r.returncode}) -- see trained/phase_r6_hw_yaw.log. "
                "Final report will note the tuning stage did not complete.")
    else:
        why = ("does not beat/tie Release_CandidateV2.1" if not gate["beats_or_ties_v21"]
               else "yaw/drift is already at or better than Release_CandidateV2.1's own number")
        log(f"Stage 2 SKIPPED -- {why}. Per user instruction: if we don't need the "
            "tuning run, skip it.")

    _write_final_report()
    log("=== hw-imu retrain pipeline complete -- see trained/phase_hw_pipeline_final.json ===")


def _write_final_report():
    gate1 = json.load(open("trained/phase_r5_hw_gate_decision.json"))
    tuning_ran = os.path.exists("trained/phase_r6_hw_gate_decision.json")
    gate2 = json.load(open("trained/phase_r6_hw_gate_decision.json")) if tuning_ran else None

    still_needs_tuning = None
    if gate1["beats_or_ties_v21"] and not gate1["yaw_needs_work"]:
        still_needs_tuning = False   # base run already good enough on yaw, tuning wasn't needed
    elif tuning_ran and gate2 is not None:
        still_needs_tuning = bool(gate2["losses"]) or not gate2["yaw_improved"]
    elif gate1["beats_or_ties_v21"] and gate1["yaw_needs_work"]:
        still_needs_tuning = True   # needed but stage 2 didn't complete (failure or STOP)

    report = dict(
        base_run=dict(
            interim_name="r5_hw_candidate",
            verdicts_vs_v21=gate1["verdicts"],
            beats_or_ties_v21=gate1["beats_or_ties_v21"],
            yaw_rms=gate1["yaw_rms"],
            heading_drift=gate1["heading_drift"],
            v21_yaw_rms=gate1["v21_yaw_rms"],
            report_path="trained/phase_r5_hw_sequential_report.json",
        ),
        tuning_run=(dict(
            ran=True,
            interim_name="r6_hw_yaw_candidate",
            losses_vs_base=gate2["losses"],
            yaw_improved=gate2["yaw_improved"],
            tuned_yaw_rms=gate2["tuned_yaw_rms"],
            base_yaw_rms=gate2["base_yaw_rms"],
            report_path="trained/phase_r6_hw_yaw_report.json",
        ) if tuning_ran else dict(ran=False)),
        still_needs_tuning=still_needs_tuning,
    )
    with open("trained/phase_hw_pipeline_final.json", "w") as f:
        json.dump(report, f, indent=2)
    log(f"Final report written: still_needs_tuning={still_needs_tuning}")


if __name__ == "__main__":
    main()
