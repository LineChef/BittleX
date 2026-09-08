#!/bin/bash
# A/B: does a from-scratch gait trained WITH the forward terrain feature beat an
# identical BLIND from-scratch gait, on a cluttered course with an anti-stall
# reward? Both fresh 20M, same course / rewards / loosened imitation anchor --
# the ONLY difference is G2E_TERRAIN_FEATURE. Fully hands-off; survives a Claude
# session ending. Progress -> trained/ab_vision_results.log.
set -u
cd "$(dirname "$0")"
PY=../../.venv/bin/python
LOG=trained/ab_vision_results.log
say() { echo "[$(date '+%m-%d %H:%M')] $*" | tee -a "$LOG"; }

CFG="G2E_FAC_NOSTALL=22 G2E_FAC_NOSTALL_BONUS=8 G2E_FAC_IMITATION=5 \
G2E_RANDOM_TERRAIN=0.06 G2E_RANDOM_TERRAIN_PROB=0.85 G2E_RANDOM_TERRAIN_MAX_H=0.09 \
G2E_OBSTACLE_COUNT=5 G2E_OBSTACLE_TALL_FRAC=0.30 G2E_OBSTACLE_SPAN_FRAC=0.10 \
G2E_OBSTACLE_X_HI=1.0 G2E_OBSTACLE_Y_SPREAD=0.10 \
G2E_LEDGE_HEIGHT=0.018 G2E_LEDGE_PROB=0.35 G2E_LEDGE_RANDOMIZE=1 \
G2E_RUBBLE_PROB=0.35 G2E_SLOPE_MAX_DEG=10"

train() {  # $1 = tag, $2 = "1" for vision else "0"
  say "train $1 (TERRAIN_FEATURE=$2) start"
  eval "env $CFG G2E_TERRAIN_FEATURE=$2 $PY train.py --tag $1 --steps 20e6" > trained/$1_console.log 2>&1
  local tb; tb=$(ls -dt trained/tensorboard_logs/PPO_* | head -1)
  say "train $1 done -- tb $tb"
}

say "=== A/B vision-in-the-loop: 2x fresh 20M, only diff is TERRAIN_FEATURE ==="
train abD_vision 1
train abD_blind 0

say "--- eval: obstacle-course behaviour, matched seeds ---"
eval "env $CFG G2E_TERRAIN_FEATURE=1 $PY eval_obstacle_response.py trained/abD_vision_ppo --episodes 40 --json-out trained/abD_vision_obs.json" > trained/abD_eval.txt 2>&1
eval "env $CFG G2E_TERRAIN_FEATURE=0 $PY eval_obstacle_response.py trained/abD_blind_ppo  --episodes 40 --json-out trained/abD_blind_obs.json" >> trained/abD_eval.txt 2>&1
say "--- eval: decathlon (base-capability regression check) ---"
# the vision policy is obs-282; the decathlon env must build 282-d obs too, so it
# needs G2E_TERRAIN_FEATURE=1 (missing here on the first Phase D run -> obs-shape
# crash, no abD_vision_deca.json).
eval "env $CFG G2E_TERRAIN_FEATURE=1 $PY benchmark_decathlon.py --learned trained/abD_vision_ppo --episodes 24 --json-out trained/abD_vision_deca.json" >> trained/abD_eval.txt 2>&1
eval "env $CFG G2E_TERRAIN_FEATURE=0 $PY benchmark_decathlon.py --learned trained/abD_blind_ppo  --episodes 24 --json-out trained/abD_blind_deca.json"  >> trained/abD_eval.txt 2>&1

say "--- reward curves ---"
$PY - <<'EOF' 2>/dev/null | tee -a "$LOG"
import glob, os
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
for d in sorted(glob.glob("trained/tensorboard_logs/PPO_*"), key=os.path.getmtime)[-2:]:
    ea = EventAccumulator(d); ea.Reload()
    s = ea.Scalars("rollout/ep_rew_mean")
    print(f"{os.path.basename(d)}  {s[0].value:.0f} -> {s[-1].value:.0f}  steps {s[-1].step}")
EOF

say "=== A/B COMPLETE -- see trained/abD_eval.txt (vision vs blind) ==="
