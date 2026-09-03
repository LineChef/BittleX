#!/usr/bin/env bash
# G2 Pi Zero 2 W bring-up -- self-resuming.
#
#   curl -sL https://raw.githubusercontent.com/LineChef/BittleX/development/scripts/pi_setup.sh -o pi_setup.sh
#   bash pi_setup.sh
#
# Run it, reboot when it tells you, run it again. Repeat until it says DONE.
# It figures out where it left off from ~/.g2_pi_stage. Nothing here needs the
# robot / BiBoard connected. Idempotent -- safe to re-run any stage.
#
# Mirrors docs/research/pi-bring-up.md sections 3-8.
set -u
STAGE_FILE="$HOME/.g2_pi_stage"
REPORT="$HOME/g2_pi_report.txt"
stage="$(cat "$STAGE_FILE" 2>/dev/null || echo 0)"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mBAD\033[0m  %s\n' "$*"; }
log()  { printf '%s\n' "$*" >> "$REPORT"; }
reboot_hint() { printf '\n\033[1;33m>>> REBOOT NOW:  sudo reboot\n>>> wait ~45s, ssh back in, then:  bash pi_setup.sh\033[0m\n\n'; }

# ---------------------------------------------------------------- assessment
assess() {
  : > "$REPORT"
  say "ASSESS  (report file: $REPORT)"
  local arch; arch="$(uname -m)"
  log "date: $(date -u +%FT%TZ)"
  log "os: $(grep -o 'PRETTY_NAME=.*' /etc/os-release | cut -d'"' -f2)  kernel: $(uname -r)  arch: $arch"
  [ "$arch" = "aarch64" ] && ok "64-bit OS ($arch)" || bad "arch is $arch -- need aarch64, re-flash with 64-bit Pi OS Lite"

  local thr; thr="$(vcgencmd get_throttled 2>/dev/null)"
  log "throttled: $thr   temp: $(vcgencmd measure_temp 2>/dev/null)"
  case "$thr" in
    *0x0*) ok "power health $thr" ;;
    *)     warn "power/thermal flags set: $thr  (0x50000=has-throttled-since-boot is usually fine; 0x50005 live = bad PSU)" ;;
  esac

  local ps; ps="$(iw dev wlan0 get power_save 2>/dev/null | awk '{print $NF}')"
  log "wifi_powersave: $ps"
  [ "$ps" = "off" ] && { ok "wifi power-save off"; PS_DONE=1; } || { warn "wifi power-save = $ps -- stage 1 will fix"; PS_DONE=0; }

  log "swap: $(swapon --show=NAME,SIZE,PRIO --noheadings 2>/dev/null | tr '\n' ';')"
  if swapon --show 2>/dev/null | grep -q zram && swapon --show 2>/dev/null | grep -q /swapfile; then
    ok "swap configured (zram + swapfile)"; SWAP_DONE=1
  else
    warn "swap incomplete -- stage 2 will set it up"; SWAP_DONE=0
  fi

  local ser=""; [ -e /dev/serial0 ] && ser="$(readlink -f /dev/serial0)"
  log "serial0 -> ${ser:-none}   config.txt: $(grep -hoE 'enable_uart=1|dtoverlay=disable-bt' /boot/firmware/config.txt 2>/dev/null | tr '\n' ',')"
  if [ "$ser" = "/dev/ttyAMA0" ] && grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt 2>/dev/null; then
    ok "serial on PL011 (ttyAMA0), BT disabled"; SER_DONE=1
  else
    warn "serial not on ttyAMA0 yet -- stage 3 will fix"; SER_DONE=0
  fi

  log "python: $(python3 --version 2>&1)"
  if [ -d "$HOME/g2/.venv" ] && "$HOME/g2/.venv/bin/python" -c 'import onnxruntime' 2>/dev/null; then
    ok "onnxruntime venv present"; ORT_DONE=1
  else
    warn "onnxruntime not installed -- stage 4"; ORT_DONE=0
  fi
  log "mem: $(free -h | awk '/Mem:/{print $2" total, "$7" avail"}')"
  log "disk: $(df -h / | awk 'NR==2{print $4" free of "$2}')"
}

# ---------------------------------------------------------------- stage 1
do_stage1() {
  say "STAGE 1  wifi power-save + system update"
  sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF
  sudo systemctl restart NetworkManager
  sleep 8
  local ps; ps="$(iw dev wlan0 get power_save 2>/dev/null | awk '{print $NF}')"
  [ "$ps" = "off" ] && ok "wifi power-save off" || warn "power-save still '$ps' (may need the reboot below)"
  say "apt update / full-upgrade  (5-20 min, don't interrupt)"
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y full-upgrade
  sudo apt-get install -y git python3-venv python3-dev build-essential stress-ng
  echo 2 > "$STAGE_FILE"
  ok "stage 1 done"
  reboot_hint
}

# ---------------------------------------------------------------- stage 2
do_stage2() {
  say "STAGE 2  swap (zram + swapfile)"
  sudo apt-get install -y systemd-zram-generator
  sudo tee /etc/systemd/zram-generator.conf >/dev/null <<'EOF'
[zram0]
zram-size = 128
compression-algorithm = lz4
EOF
  sudo systemctl daemon-reload
  sudo systemctl restart systemd-zram-setup@zram0 2>/dev/null || true
  if ! swapon --show 2>/dev/null | grep -q /swapfile; then
    sudo fallocate -l 1G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
  fi
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw,pri=10 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo 'vm.swappiness=100' | sudo tee /etc/sysctl.d/99-swap.conf >/dev/null
  sudo sysctl --system >/dev/null
  swapon --show && ok "swap active" || warn "swap not showing -- check 'swapon --show'"
  echo 3 > "$STAGE_FILE"
  ok "stage 2 done -- no reboot needed, continuing"
  do_stage3
}

# ---------------------------------------------------------------- stage 3
do_stage3() {
  say "STAGE 3  serial / UART for the BiBoard (config only, robot not needed)"
  sudo raspi-config nonint do_serial_cons 1 2>/dev/null || sudo raspi-config nonint do_serial 1 2>/dev/null || true
  sudo raspi-config nonint do_serial_hw 0 2>/dev/null || true
  grep -q '^enable_uart=1'          /boot/firmware/config.txt || echo 'enable_uart=1'          | sudo tee -a /boot/firmware/config.txt >/dev/null
  grep -q '^dtoverlay=disable-bt'   /boot/firmware/config.txt || echo 'dtoverlay=disable-bt'   | sudo tee -a /boot/firmware/config.txt >/dev/null
  sudo systemctl disable --now hciuart 2>/dev/null || true
  sudo systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
  sudo systemctl disable --now serial-getty@serial0.service 2>/dev/null || true
  groups | grep -qw dialout || { sudo usermod -aG dialout "$USER"; warn "added you to 'dialout' -- log out/in once after the reboot"; }
  echo 4 > "$STAGE_FILE"
  ok "stage 3 done"
  reboot_hint
}

# ---------------------------------------------------------------- stage 4
do_stage4() {
  say "STAGE 4  onnxruntime + synthetic policy benchmark"
  local s; s="$(readlink -f /dev/serial0 2>/dev/null)"
  [ "$s" = "/dev/ttyAMA0" ] && ok "serial0 -> ttyAMA0 (good)" || warn "serial0 -> ${s:-none} (expected ttyAMA0 -- check config.txt / reboot)"
  log "serial0_after_reboot: ${s:-none}"

  mkdir -p "$HOME/g2" && cd "$HOME/g2"
  [ -d .venv ] || python3 -m venv .venv
  . .venv/bin/activate
  pip -q install --upgrade pip
  if ! pip -q install numpy onnx onnxruntime; then
    bad "onnxruntime install FAILED -- copy the pip error above into your report"
    log "onnxruntime_install: FAILED"
    echo 5 > "$STAGE_FILE"; do_stage5; return
  fi
  python - <<'EOF'
import time, numpy as np, onnx, onnxruntime as ort
from onnx import helper, TensorProto
IN,H,OUT,HZ = 276,256,8,80
rng = np.random.default_rng(0)
def lin(nm,i,o):
    return (helper.make_tensor(nm+"_w",TensorProto.FLOAT,[i,o],(rng.standard_normal(i*o)*0.05).astype(np.float32)),
            helper.make_tensor(nm+"_b",TensorProto.FLOAT,[o],np.zeros(o,np.float32)))
w1,b1=lin("l1",IN,H); w2,b2=lin("l2",H,H); w3,b3=lin("l3",H,OUT)
nodes=[helper.make_node("Gemm",["x","l1_w","l1_b"],["h1"]),helper.make_node("Tanh",["h1"],["a1"]),
       helper.make_node("Gemm",["a1","l2_w","l2_b"],["h2"]),helper.make_node("Tanh",["h2"],["a2"]),
       helper.make_node("Gemm",["a2","l3_w","l3_b"],["y"])]
g=helper.make_graph(nodes,"mlp",
   [helper.make_tensor_value_info("x",TensorProto.FLOAT,[1,IN])],
   [helper.make_tensor_value_info("y",TensorProto.FLOAT,[1,OUT])],[w1,b1,w2,b2,w3,b3])
onnx.save(helper.make_model(g,opset_imports=[helper.make_opsetid("",13)]),"policy_stub.onnx")
so=ort.SessionOptions(); so.intra_op_num_threads=2
s=ort.InferenceSession("policy_stub.onnx",so,providers=["CPUExecutionProvider"])
x=rng.standard_normal((1,IN)).astype(np.float32)
for _ in range(50): s.run(None,{"x":x})
N=2000; t=time.perf_counter()
for _ in range(N): s.run(None,{"x":x})
dt=(time.perf_counter()-t)/N*1e3
budget=1000/HZ
verdict = f"OK ({100*dt/budget:.0f}% of {budget:.1f} ms budget)" if dt<budget else "TOO SLOW"
line=f"onnxruntime MLP [276-256-256-8]: {dt:.3f} ms/call  ({1000/dt:.0f}/s)  -> {verdict}"
print(line)
import pathlib; pathlib.Path.home().joinpath("g2_pi_report.txt").open("a").write(line+"\n")
EOF
  echo 5 > "$STAGE_FILE"
  ok "stage 4 done"
  do_stage5
}

# ---------------------------------------------------------------- stage 5
do_stage5() {
  say "STAGE 5  thermal / wifi-under-load (2 min)"
  ( for i in $(seq 1 12); do sleep 10; echo "  t+$((i*10))s  $(vcgencmd measure_temp)  $(vcgencmd get_throttled)"; done ) &
  local mon=$!
  stress-ng --cpu 4 --timeout 120s --metrics-brief 2>&1 | tail -4
  wait $mon
  local pk; pk="$(vcgencmd measure_temp)"
  log "post_stress_temp: $pk   throttled: $(vcgencmd get_throttled)"
  ok "stress test finished (peak temp $pk) -- if this SSH session didn't freeze, the power-save fix held"
  echo 99 > "$STAGE_FILE"
  finish
}

# ---------------------------------------------------------------- finish
finish() {
  say "DONE"
  echo "Report written to $REPORT :"
  echo "--------------------------------------------------"
  cat "$REPORT"
  echo "--------------------------------------------------"
  say "SHARE THE REPORT WITH CLAUDE"
  echo "The report has only system info + benchmark numbers (no secrets). Upload it:"
  echo
  echo "  curl -s --data-binary @$REPORT https://paste.rs ; echo"
  echo "     ...or...   cat $REPORT | nc termbin.com 9999"
  echo
  echo "Read the short URL it prints back to Claude."
}

# ---------------------------------------------------------------- driver
PS_DONE=0; SWAP_DONE=0; SER_DONE=0; ORT_DONE=0
assess

# On the very first run (stage 0), jump past whatever the assessment shows is
# already done, so we don't redo apt-upgrade etc. unnecessarily.
if [ "$stage" = 0 ]; then
  if   [ "$SER_DONE" = 1 ] && [ "$ORT_DONE" = 1 ]; then stage=5
  elif [ "$SER_DONE" = 1 ];                        then stage=4
  elif [ "$SWAP_DONE" = 1 ];                       then stage=3
  elif [ "$PS_DONE" = 1 ];                         then stage=2
  else                                                  stage=1
  fi
  echo "$stage" > "$STAGE_FILE"
  say "first run -> starting at stage $stage"
fi

case "$stage" in
  1)  do_stage1 ;;
  2)  do_stage2 ;;
  3)  do_stage3 ;;
  4)  do_stage4 ;;
  5)  do_stage5 ;;
  99) finish ;;
  *)  do_stage1 ;;
esac
