#!/bin/bash
# After the ARMW training (rl_training/opencat-gym/phase_armw.py) completes (user, 2026-11-03: promote the new policy to the new default, deploy it to the Pi the next time it comes online, commit and push):
#   1. waits for "ARMW COMPLETE" in the phase log;
#   2. only if the run's verdict is PASS (a failing policy is never put on the robot): adds the hardware epoch for the wide shoulders, promotes ARMWcand as the arm's gait
#      (promote_release.py --attachment-only: the arm is the fitted attachment; DEFAULT_POLICY, the head's and no-attachment policy, stays), which runs the tests, commits and pushes;
#   3. deploys to the Pi when it is online and idle (tools/g2_deploy_when_online.sh, waits up to 48 h).
# Log: ~/g2_logs/armw_finish.log. Needs G2_PI in the environment.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; GYM="$ROOT/rl_training/opencat-gym"; LOG="$HOME/g2_logs/armw_finish.log"; mkdir -p "$HOME/g2_logs"
say() { echo "[$(date '+%I:%M %p')] $*" >> "$LOG"; }
until grep -q "ARMW COMPLETE" "$GYM/trained/phase_armw.log" 2>/dev/null; do sleep 120; if [ -f "$GYM/trained/armw_halt" ]; then say "training halted ($(head -c 200 "$GYM/trained/armw_halt")): nothing promoted; waiting"; sleep 600; fi; done
say "training complete"
if ! grep -q "VERDICT: PASS against ARM1X" "$GYM/trained/phase_armw.log"; then say "verdict is not PASS: NOT promoted, NOT deployed (see trained/phase_armw.log)"; exit 3; fi
cd "$ROOT" || exit 1
python3 - <<'PY' >> "$LOG" 2>&1
import json
p = "pi_pipeline/telemetry/hardware_epochs.json"
t = open(p).read()
if "hw-2026-11-03" not in t:
    new = ',\n  {"id": "hw-2026-11-03", "start": "2026-11-03T00:00", "fit_ok": true, "note": "0.2 in wide shoulder parts fitted on the stock feet (the CLpaw paws did not fit); about 540 g, not weighed. Sim build arm_wide. Start time approximate (the day, to confirm)."}\n]'
    i = t.rstrip().rfind("]")
    open(p, "w").write(t[:i].rstrip() + new + "\n")
PY
git add pi_pipeline/telemetry/hardware_epochs.json && git commit -qm "Hardware epoch: the 0.2 in wide shoulders on the stock feet" >> "$LOG" 2>&1 && git push -q >> "$LOG" 2>&1
cd "$GYM" || exit 1
if ../../.venv/bin/python promote_release.py --candidate trained/ARMWcand_ppo.onnx --name ARMW --attachment arm --payload-profile arm --attachment-only --note "wide shoulders, stock feet (ARMW)" >> "$LOG" 2>&1; then
  say "ARMW promoted for the arm (committed and pushed by promote_release)"
else
  say "promote_release failed (exit $?): NOT deployed"; exit 4
fi
cd "$ROOT" && bash tools/g2_deploy_when_online.sh --max-hours 48 >> "$LOG" 2>&1 && say "DEPLOYED to the Pi" || say "deploy did not happen (Pi never answered within 48 h or the deploy failed): run tools/g2_deploy_when_online.sh"
