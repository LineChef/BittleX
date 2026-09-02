#!/usr/bin/env bash
# pi_pipeline/setup_pi.sh
# One-shot OS provisioning for the Raspberry Pi Zero 2 W that rides on G2.
# Idempotent — safe to re-run. Details + rationale: docs/research/pi-bring-up.md
#
# Run once over SSH after the first boot, as the normal user (not root):
#     bash ~/bittleX/pi_pipeline/setup_pi.sh
# Then reboot if it says to (UART / config.txt changes need it).
#
# It does NOT create the Python venv or install pi_pipeline — that's the last
# step, printed at the end.

set -euo pipefail

cyan()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m    ok  %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m    !   %s\033[0m\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
  echo "Run as the normal user (e.g. g2), not root — the script uses sudo where needed." >&2
  exit 1
fi
sudo -v

# Bookworm moved the boot partition to /boot/firmware; older layout is /boot.
BOOTCFG=/boot/firmware/config.txt;  [ -f "$BOOTCFG" ]  || BOOTCFG=/boot/config.txt
CMDLINE=/boot/firmware/cmdline.txt;  [ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
[ -f "$BOOTCFG" ] || { echo "cannot find config.txt (looked in /boot/firmware and /boot)"; exit 1; }
cyan "boot config: $BOOTCFG"

REBOOT_NEEDED=0

# --------------------------------------------------------------------------
cyan "1/4  Wi-Fi power-save -> OFF  (brcmfmac stalls SSH under load otherwise)"
sudo install -d -m 755 /etc/NetworkManager/conf.d
printf '[connection]\nwifi.powersave = 2\n' \
  | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null
ok "wrote /etc/NetworkManager/conf.d/wifi-powersave-off.conf"
# nudge the live connection too (no disconnect); full effect after reboot
conn=$(nmcli -t -f NAME connection show --active 2>/dev/null | head -n1 || true)
if [ -n "${conn:-}" ]; then
  sudo nmcli connection modify "$conn" 802-11-wireless.powersave 2 || true
  ok "live connection '$conn' set to powersave off"
fi
iw dev wlan0 get power_save 2>/dev/null | sed 's/^/    /' || true

# --------------------------------------------------------------------------
cyan "2/4  swap:  small lz4 zram  +  1 GB swapfile backstop  (512 MB RAM is tight)"
sudo apt-get install -y -qq systemd-zram-generator >/dev/null
printf '[zram0]\nzram-size = 128\ncompression-algorithm = lz4\n' \
  | sudo tee /etc/systemd/zram-generator.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart systemd-zram-setup@zram0.service 2>/dev/null \
  || sudo systemctl start /dev/zram0 2>/dev/null || true
ok "zram0 configured (128 MB pool, lz4)"

if [ ! -f /swapfile ]; then
  sudo fallocate -l 1G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw,pri=10 0 0' | sudo tee -a /etc/fstab >/dev/null
  ok "created /swapfile (1 GB, priority 10 — below zram)"
else
  sudo swapon /swapfile 2>/dev/null || true
  ok "/swapfile already present"
fi
echo 'vm.swappiness=100' | sudo tee /etc/sysctl.d/99-swap.conf >/dev/null
sudo sysctl -q -w vm.swappiness=100
swapon --show=NAME,TYPE,SIZE,PRIO --noheadings 2>/dev/null | sed 's/^/    /' || true

# --------------------------------------------------------------------------
cyan "3/4  apt: git, venv, build tools, PortAudio"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv python3-dev build-essential libportaudio2
ok "installed: git python3-venv python3-dev build-essential libportaudio2"

# --------------------------------------------------------------------------
cyan "4/4  serial: disable Bluetooth, take the stable PL011 for the BiBoard link"
add_cfg() {   # append a line to config.txt at most once
  if grep -qxF "$1" "$BOOTCFG"; then
    ok "config.txt already has: $1"
  else
    echo "$1" | sudo tee -a "$BOOTCFG" >/dev/null
    REBOOT_NEEDED=1
    ok "config.txt += $1"
  fi
}
add_cfg "enable_uart=1"
add_cfg "dtoverlay=disable-bt"

sudo systemctl disable --now hciuart.service            2>/dev/null || true
sudo systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
sudo systemctl disable --now serial-getty@serial0.service 2>/dev/null || true
ok "disabled hciuart + serial login shell"

if grep -qE 'console=serial0|console=ttyAMA0' "$CMDLINE" 2>/dev/null; then
  sudo sed -i -E 's/console=(serial0|ttyAMA0),[0-9]+ ?//g' "$CMDLINE"
  REBOOT_NEEDED=1
  ok "removed serial console from $(basename "$CMDLINE")"
fi

if grep -qE '^\s*dtoverlay=w1-gpio' "$BOOTCFG" 2>/dev/null; then
  warn "1-wire (w1-gpio) is enabled on GPIO4 — comment it out if the BiBoard link misbehaves"
else
  ok "1-wire not enabled (GPIO4 free)"
fi

# --------------------------------------------------------------------------
cyan "summary"
echo "    RAM / swap:"
free -h | sed 's/^/      /'
echo "    serial:  /dev/ttyAMA0  (alias /dev/serial0)  once rebooted  —  BiBoard link @ 115200"
echo
if [ "$REBOOT_NEEDED" -eq 1 ]; then
  warn "config.txt / cmdline.txt changed  ->  REBOOT NOW:   sudo reboot"
else
  ok "no reboot needed"
fi
echo
echo "    next — create the venv and install pi_pipeline:"
echo "      cd ~/bittleX/pi_pipeline"
echo "      python3 -m venv .venv && . .venv/bin/activate"
echo "      pip install -U pip && pip install -r requirements.txt -r requirements-audio.txt"
echo "      python -m pytest -q            # expect 42 passed"
