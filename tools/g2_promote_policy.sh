#!/usr/bin/env bash
# Promote a trained policy to G2's default and deploy it the next time the Pi is online.
#   g2_promote_policy.sh TAG NAME [--dry-run]
#     TAG   the checkpoint under rl_training/opencat-gym/trained/ without .zip (e.g. v3_20m_ppo)
#     NAME  the deployed name (e.g. Release_CandidateV3): the files become trained/NAME_ppo.onnx and NAME_ppo.onnx.json
# Steps: export the ONNX with its sidecar (residual scale 30, command cadence i@27), point DEFAULT_POLICY at it, run the test suite, commit and push on the current branch (no trailers),
# then start tools/g2_deploy_when_online.sh in the background (waits up to 24 h for the Pi, rsyncs pi_pipeline/ and the policy, restarts g2-voice; ~/g2_logs/deploy_*.log).
# Rollback: set DEFAULT_POLICY back to the previous name (V2.1: Release_CandidateV2.1_ppo.onnx; its files stay on the Pi) and run tools/g2_deploy_when_online.sh --once.
set -uo pipefail
TAG="${1:?usage: $0 TAG NAME [--dry-run]}"; NAME="${2:?usage: $0 TAG NAME [--dry-run]}"; DRY=0; [ "${3:-}" = "--dry-run" ] && DRY=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; RL="$ROOT/rl_training/opencat-gym"; ONNX="trained/${NAME}_ppo.onnx"
run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else eval "$@"; fi; }
[ -f "$RL/trained/$TAG.zip" ] || { echo "no checkpoint $RL/trained/$TAG.zip"; exit 1; }
cd "$RL" || exit 1
run "../../.venv/bin/python export_onnx.py --model trained/$TAG --out $ONNX --residual-scale-deg 30 --cmd-send-every-n 3" || exit 1
cd "$ROOT" || exit 1
run "python3 - <<'PY'
import re
p='pi_pipeline/gait/residual_policy.py'; s=open(p).read()
s2=re.sub(r'DEFAULT_POLICY = \"[^\"]+\"', 'DEFAULT_POLICY = \"${NAME}_ppo.onnx\"', s, count=1)
assert s2 != s, 'DEFAULT_POLICY line not found or unchanged'
open(p,'w').write(s2)
PY" || exit 1
run "pi_pipeline/.venv/bin/pytest >/dev/null 2>&1" || { echo "the test suite fails with the new default: not committing"; exit 1; }
run "git add -f rl_training/opencat-gym/$ONNX rl_training/opencat-gym/$ONNX.json pi_pipeline/gait/residual_policy.py"
run "git commit -qm 'Promote $NAME to the default walking policy (V2.1 stays on the Pi as the fallback)'"
run "git push -q"
run "(nohup bash tools/g2_deploy_when_online.sh --max-hours 24 > ~/g2_logs/promote_deploy.out 2>&1 &)"
echo "promoted $TAG as $NAME; the deploy waits for the Pi (log ~/g2_logs/promote_deploy.out)"
