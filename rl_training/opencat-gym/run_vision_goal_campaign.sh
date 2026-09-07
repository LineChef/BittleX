#!/bin/bash
# Autonomous vision-goal campaign: 3M smoke (finetune) -> deterministic gate
# (gate_check.py) -> fresh 20M if GO, one retune if RETUNE, stop if STOP.
# Survives a Claude session ending: everything here runs detached on the box.
# Progress -> trained/campaign_results.log ; final marker at the end.
set -u
cd "$(dirname "$0")"
PY=../../.venv/bin/python
LOG=trained/campaign_results.log
say() { echo "[$(date '+%m-%d %H:%M')] $*" | tee -a "$LOG"; }

# --- shared env config (smoke + 20M) --------------------------------------
CFG_COMMON="G2E_TURN_BLEND=1 G2E_GOAL_MODE=1 G2E_TERRAIN_FEATURE=1 G2E_OBSTACLE_REWARD=1 G2E_CLIFF=1 \
G2E_EPISODE_LENGTH=1200 G2E_TRAIN_YAW=0.45 G2E_GOAL_BEARING_MAX=1.6 \
G2E_GOAL_AVOID_FRAC=0.12 G2E_GOAL_MOVING_FRAC=0.15 \
G2E_CLIFF_PROB=0.15 G2E_CLIFF_PLATFORM_HW=1.0 \
G2E_FAC_GOAL_PROGRESS=150 G2E_FAC_GOAL_FACE=25 G2E_FAC_HEADING_GOAL=2.0 \
G2E_FAC_OBS_STOP=0 G2E_FAC_OBS_BUMP=0.015 \
G2E_RANDOM_TERRAIN=0.05 G2E_RANDOM_TERRAIN_PROB=0.6 G2E_RANDOM_TERRAIN_MAX_H=0.07 \
G2E_OBSTACLE_COUNT=4 G2E_OBSTACLE_TALL_FRAC=0.25 G2E_OBSTACLE_SPAN_FRAC=0.08 \
G2E_OBSTACLE_X_HI=1.1 G2E_OBSTACLE_Y_SPREAD=0.14 \
G2E_LEDGE_HEIGHT=0.018 G2E_LEDGE_PROB=0.3 G2E_LEDGE_RANDOMIZE=1 \
G2E_RUBBLE_PROB=0.3 G2E_SLOPE_MAX_DEG=8 G2E_FAC_IMITATION=7"

CFG_RETUNE="G2E_GOAL_BEARING_MAX=1.1 G2E_FAC_GOAL_FACE=45 G2E_FAC_HEADING_GOAL=3.5 \
G2E_FAC_IMITATION=4 G2E_TRAIN_YAW=0.5"

evalgoal() {  # $1 = checkpoint tag, $2 = out json
  eval "env G2E_TURN_BLEND=1 G2E_GOAL_MODE=1 G2E_TERRAIN_FEATURE=1 G2E_CLIFF=1 G2E_EPISODE_LENGTH=1200 G2E_TRAIN_YAW=0.45 \
    $PY benchmark_goal.py trained/$1_ppo --episodes 12 --json-out $2" >> trained/${1}_eval.txt 2>&1
}

run_smoke() {  # $1 = tag, $2 = extra cfg
  say "smoke $1 start"
  eval "env $CFG_COMMON $2 $PY train.py --from trained/run20m_graft289 --tag $1 --steps 3e6 \
    --finetune-lr 1e-4 --finetune-target-kl 0.15" > trained/$1_console.log 2>&1
  local tb; tb=$(ls -dt trained/tensorboard_logs/PPO_* | head -1)
  evalgoal "$1" "trained/$1_goal.json"
  $PY gate_check.py "trained/$1_goal.json" "$tb" | tee -a "$LOG"
}

# ============================ run ========================================
say "=== campaign start (graft run20m_graft289, obs 289) ==="
run_smoke phaseC_s1 ""
D=$(grep -o 'DECISION=[A-Z_]*' "$LOG" | tail -1 | cut -d= -f2)
say "smoke 1 decision: $D"

if [ "$D" = "RETUNE" ]; then
  run_smoke phaseC_s2 "$CFG_RETUNE"
  D=$(grep -o 'DECISION=[A-Z_]*' "$LOG" | tail -1 | cut -d= -f2)
  say "retune decision: $D"
  WIN=phaseC_s2; EXTRA="$CFG_RETUNE"
else
  WIN=phaseC_s1; EXTRA=""
fi

if [ "$D" = "GO_20M" ]; then
  say "=== GO_20M: fresh 20M, config from $WIN ==="
  eval "env $CFG_COMMON $EXTRA $PY train.py --tag phaseC_20m --steps 20e6" > trained/phaseC_20m_console.log 2>&1
  say "20M done -- full eval"
  evalgoal phaseC_20m trained/phaseC_20m_goal.json
  eval "env $CFG_COMMON $EXTRA $PY benchmark_commanded.py --learned trained/phaseC_20m_ppo --json-out trained/phaseC_20m_commanded.json" >> trained/phaseC_20m_eval.txt 2>&1
  $PY benchmark_decathlon.py --learned trained/phaseC_20m_ppo --episodes 24 --json-out trained/phaseC_20m_decathlon.json >> trained/phaseC_20m_eval.txt 2>&1
  say "=== CAMPAIGN COMPLETE (20M + eval done) ==="
else
  say "=== CAMPAIGN STOPPED at gate: $D. No 20M. See recommendation. ==="
fi
