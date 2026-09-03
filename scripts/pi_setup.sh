#!/usr/bin/env bash
# G2 Pi Zero 2 W bring-up -- one command, hands-off.
#
#   git clone -b development https://github.com/LineChef/BittleX
#   bash BittleX/scripts/pi_setup.sh
#
# Phase 1 (interactive, ~10-25 min): you'll be asked for your sudo password once.
#   wifi power-save off, apt full-upgrade, base packages, swap (zram+swapfile),
#   serial/UART -> /dev/ttyAMA0 (disable-bt). Installs a @reboot hook, then reboots.
#   >>> your SSH session will drop at the reboot -- that's expected.
#
# Phase 2 (automatic on next boot, ~5-10 min, no sudo):
#   verify serial, create venv, install onnxruntime, run the [276-256-256-8]
#   policy-inference benchmark, 2-min thermal/wifi stress test. Writes
#   ~/g2_pi_report.txt, uploads it, writes the URL to ~/g2_report_url.txt,
#   removes its own @reboot hook, touches ~/g2_pi_DONE.
#
# You: wait ~15 min after the reboot, ssh back in, then:
#   cat ~/g2_report_url.txt      # give this URL to Claude
#   cat ~/g2_pi_report.txt       # or read it yourself
#
# Escape hatches:
#   bash pi_setup.sh --manual        # do phase 1, but DON'T auto-reboot (you reboot + rerun --post-reboot)
#   bash pi_setup.sh --post-reboot   # run phase 2 by hand
#   bash pi_setup.sh --status        # where are we
#
# Mirrors docs/research/pi-bring-up.md sections 3-8. Robot / BiBoard not required.
set -u

REPORT="$HOME/g2_pi_report.txt"
URLFILE="$HOME/g2_report_url.txt"
DONE="$HOME/g2_pi_DONE"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
BOOTS="$HOME/.g2_boot_count"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mBAD\033[0m  %s\n' "$*"; }
log()  { printf '%s\n' "$*" | tee -a "$REPORT" ; }

# --------------------------------------------------------------- phase 1 (sudo)
phase1() {
  local auto="$1"   # 1 = install @reboot hook + reboot; 0 = stop after config
  : > "$REPORT"
  say "PHASE 1  system config (needs sudo -- you'll be prompted once)"
  log "== G2 Pi bring-up report =="
  log "date: $(date -u +%FT%TZ)"
  log "os: $(grep -o 'PRETTY_NAME=.*' /etc/os-release | cut -d'\"' -f2)  kernel: $(uname -r)  arch: $(uname -m)"
  log "model: $(tr -d '\0' </proc/device-tree/model 2>/dev/null)"
  [ "$(uname -m)" = aarch64 ] && ok "64-bit OS" || { bad "arch $(uname -m) -- need aarch64, stop and re-flash"; exit 1; }

  # keep sudo alive for the whole run
  sudo -v || { bad "no sudo"; exit 1; }
  ( while true; do sudo -n true; sleep 50; done ) & local keep=$!
  trap 'kill $keep 2>/dev/null' EXIT

  say "1/4  wifi power-save off"
  sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF
  sudo systemctl restart NetworkManager; sleep 8
  local ps; ps="$(iw dev wlan0 get power_save 2>/dev/null | awk '{print $NF}')"
  [ "$ps" = off ] && ok "power_save off" || warn "power_save='$ps' (should be off after reboot)"
  log "wifi_powersave: ${ps:-unknown}"

  say "2/4  apt update / full-upgrade / base packages  (slow -- do not interrupt)"
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y full-upgrade
  sudo apt-get install -y git python3-venv python3-dev build-essential stress-ng systemd-zram-generator
  ok "packages done"

  say "3/4  swap (zram 128M lz4 + 1G swapfile)"
  sudo tee /etc/systemd/zram-generator.conf >/dev/null <<'EOF'
[zram0]
zram-size = 128
compression-algorithm = lz4
EOF
  sudo systemctl daemon-reload
  sudo systemctl restart systemd-zram-setup@zram0 2>/dev/null || true
  if ! swapon --show 2>/dev/null | grep -q /swapfile; then
    sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  fi
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw,pri=10 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo 'vm.swappiness=100' | sudo tee /etc/sysctl.d/99-swap.conf >/dev/null
  sudo sysctl --system >/dev/null
  log "swap: $(swapon --show=NAME,SIZE,PRIO --noheadings 2>/dev/null | tr '\n' ';')"
  swapon --show 2>/dev/null | grep -q zram && ok "swap active" || warn "swap not showing"

  say "4/4  serial / UART -> ttyAMA0 (disable-bt)"
  sudo raspi-config nonint do_serial_cons 1 2>/dev/null || sudo raspi-config nonint do_serial 1 2>/dev/null || true
  sudo raspi-config nonint do_serial_hw 0 2>/dev/null || true
  grep -q '^enable_uart=1'        /boot/firmware/config.txt || echo 'enable_uart=1'        | sudo tee -a /boot/firmware/config.txt >/dev/null
  grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt || echo 'dtoverlay=disable-bt' | sudo tee -a /boot/firmware/config.txt >/dev/null
  sudo systemctl disable --now hciuart 2>/dev/null || true
  sudo systemctl disable --now serial-getty@ttyAMA0.service serial-getty@serial0.service 2>/dev/null || true
  groups | grep -qw dialout || sudo usermod -aG dialout "$USER"
  ok "serial config written (activates on reboot)"

  if [ "$auto" = 1 ]; then
    say "installing @reboot hook for phase 2, then rebooting"
    echo 0 > "$BOOTS"
    ( crontab -l 2>/dev/null | grep -v 'g2 pi_setup post-reboot' ; \
      echo "@reboot /bin/bash '$SELF' --post-reboot >> \$HOME/g2_setup.log 2>&1  # g2 pi_setup post-reboot" ) | crontab -
    crontab -l | grep -q post-reboot && ok "@reboot hook installed" || { bad "crontab install failed -- run 'bash $SELF --post-reboot' yourself after reboot"; }
    log "phase1: done, rebooting for phase 2"
    printf '\n\033[1;33m>>> rebooting now. SSH will drop. Wait ~15 min, ssh back in, then:\n>>>   cat ~/g2_report_url.txt\033[0m\n\n'
    sleep 3
    sudo reboot
  else
    say "PHASE 1 done (--manual: no auto-reboot)"
    echo "Now:  sudo reboot   then:  bash $SELF --post-reboot"
  fi
}

# --------------------------------------------------------------- phase 2 (no sudo)
phase2() {
  # guard against a reboot loop if something wedges
  local n; n=$(( $(cat "$BOOTS" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$BOOTS"
  if [ "$n" -gt 4 ]; then
    crontab -l 2>/dev/null | grep -v 'g2 pi_setup post-reboot' | crontab -
    echo "phase2: aborted after $n boots" | tee -a "$REPORT"; exit 1
  fi

  say "PHASE 2  benchmark + stress  (auto, boot #$n)"
  log ""
  log "-- phase 2 ($(date -u +%FT%TZ)) --"
  log "throttled: $(vcgencmd get_throttled)   temp: $(vcgencmd measure_temp)"
  log "mem: $(free -h | awk '/Mem:/{print $2" total, "$7" avail"}')   disk: $(df -h / | awk 'NR==2{print $4" free"}')"

  local s; s="$(readlink -f /dev/serial0 2>/dev/null)"
  log "serial0 -> ${s:-none}   (want /dev/ttyAMA0)"
  [ "$s" = /dev/ttyAMA0 ] && ok "serial on PL011" || warn "serial0 -> ${s:-none}"
  local ps; ps="$(iw dev wlan0 get power_save 2>/dev/null | awk '{print $NF}')"
  log "wifi_powersave: ${ps:-unknown}"

  say "onnxruntime install + policy benchmark"
  mkdir -p "$HOME/g2" && cd "$HOME/g2"
  [ -d .venv ] || python3 -m venv .venv
  . .venv/bin/activate
  pip -q install --upgrade pip
  if pip -q install numpy onnx onnxruntime; then
    python - <<'PY' 2>&1 | tee -a "$HOME/g2_pi_report.txt"
import time, numpy as np, onnx, onnxruntime as ort
from onnx import helper, TensorProto
IN,H,OUT,HZ = 276,256,8,80
rng = np.random.default_rng(0)
def lin(nm,i,o):
    return (helper.make_tensor(nm+"_w",TensorProto.FLOAT,[i,o],(rng.standard_normal(i*o)*0.05).astype(np.float32)),
            helper.make_tensor(nm+"_b",TensorProto.FLOAT,[o],np.zeros(o,np.float32)))
w1,b1=lin("l1",IN,H); w2,b2=lin("l2",H,H); w3,b3=lin("l3",H,OUT)
nd=[helper.make_node("Gemm",["x","l1_w","l1_b"],["h1"]),helper.make_node("Tanh",["h1"],["a1"]),
    helper.make_node("Gemm",["a1","l2_w","l2_b"],["h2"]),helper.make_node("Tanh",["h2"],["a2"]),
    helper.make_node("Gemm",["a2","l3_w","l3_b"],["y"])]
g=helper.make_graph(nd,"mlp",
   [helper.make_tensor_value_info("x",TensorProto.FLOAT,[1,IN])],
   [helper.make_tensor_value_info("y",TensorProto.FLOAT,[1,OUT])],[w1,b1,w2,b2,w3,b3])
onnx.save(helper.make_model(g,opset_imports=[helper.make_opsetid("",13)]),"policy_stub.onnx")
so=ort.SessionOptions(); so.intra_op_num_threads=2
sess=ort.InferenceSession("policy_stub.onnx",so,providers=["CPUExecutionProvider"])
x=rng.standard_normal((1,IN)).astype(np.float32)
for _ in range(50): sess.run(None,{"x":x})
N=2000; t=time.perf_counter()
for _ in range(N): sess.run(None,{"x":x})
dt=(time.perf_counter()-t)/N*1e3; budget=1000/HZ
print(f"onnxruntime MLP [276-256-256-8]: {dt:.3f} ms/call ({1000/dt:.0f}/s) | 80Hz budget {budget:.1f} ms -> "
      + (f"OK ({100*dt/budget:.0f}% of budget)" if dt<budget else "TOO SLOW"))
PY
  else
    log "onnxruntime_install: FAILED (see g2_setup.log for pip error)"
    bad "onnxruntime install failed"
  fi

  say "thermal / wifi stress (2 min)"
  ( for i in $(seq 1 12); do sleep 10; printf 'stress t+%ds  %s  %s\n' $((i*10)) "$(vcgencmd measure_temp)" "$(vcgencmd get_throttled)" >> "$REPORT"; done ) &
  local mon=$!
  stress-ng --cpu 4 --timeout 120s --metrics-brief >>"$REPORT" 2>&1
  wait $mon
  log "post_stress: $(vcgencmd measure_temp)  $(vcgencmd get_throttled)"

  say "done -- uploading report"
  crontab -l 2>/dev/null | grep -v 'g2 pi_setup post-reboot' | crontab -   # remove the hook
  local url=""
  url="$(curl -s --max-time 20 --data-binary @"$REPORT" https://paste.rs 2>/dev/null)"
  [ -z "$url" ] && url="$(curl -s --max-time 20 -F"file=@$REPORT" https://0x0.st 2>/dev/null)"
  if [ -n "$url" ]; then echo "$url" > "$URLFILE"; ok "report at: $url"; else
    echo "(upload failed -- read ~/g2_pi_report.txt directly)" > "$URLFILE"; warn "upload failed"
  fi
  touch "$DONE"
  say "ALL DONE.  ssh in and run:  cat ~/g2_report_url.txt"
}

# --------------------------------------------------------------- dispatch
case "${1:-}" in
  --post-reboot) phase2 ;;
  --manual)      phase1 0 ;;
  --status)
    [ -f "$DONE" ] && echo "DONE. report: $(cat "$URLFILE" 2>/dev/null)" && exit 0
    crontab -l 2>/dev/null | grep -q post-reboot && echo "phase 1 done; phase 2 pending next boot (boot count $(cat "$BOOTS" 2>/dev/null||echo 0))" || echo "not started / phase 1 not finished"
    ;;
  "")            phase1 1 ;;
  *) echo "usage: pi_setup.sh [--manual | --post-reboot | --status]"; exit 2 ;;
esac
