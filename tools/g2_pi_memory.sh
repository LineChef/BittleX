#!/usr/bin/env bash
# The Pi Zero 2 W has 463 MB; the voice service holds about 315 MB of it (2026-11-06 measurements in docs/hardware/pi-power.md). What is set and what this changes:
#   status   memory, swap (zram first, the SD swap files after), the zram size and compression, ModemManager
#   apply    zram 128 -> 256 MB (takes effect at the next reboot: the generator reads it at boot; compressed about 2.6x, so it holds more before anything reaches the SD card) and stop + disable ModemManager
#            (no modem; about 3 MB). Backs up /etc/systemd/zram-generator.conf first.
#   revert   put the backup back and re-enable ModemManager
# Already in place and left alone: zram swap at priority 100 (lz4), SD swap files after it, vm.swappiness 100 (right for zram first), gpu_mem 16.
set -euo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
case "${1:-status}" in
  status) ssh "$G2_PI" 'free -m | head -2; echo; cat /proc/swaps; echo; echo "zram size: $(( $(cat /sys/block/zram0/disksize) / 1048576 )) MB ($(cat /sys/block/zram0/comp_algorithm | grep -o "\[[a-z0-9]*\]"))"; cat /etc/systemd/zram-generator.conf; echo "ModemManager: $(systemctl is-enabled ModemManager 2>&1) / $(systemctl is-active ModemManager 2>&1)"' ;;
  apply) ssh "$G2_PI" 'f=/etc/systemd/zram-generator.conf; sudo -n cp -p $f $f.g2-backup && sudo -n sed -i "s/^zram-size = .*/zram-size = 256/" $f && grep zram-size $f; sudo -n systemctl disable --now ModemManager 2>&1 | tail -1; echo "zram 256 MB applies at the next reboot"' ;;
  revert) ssh "$G2_PI" 'f=/etc/systemd/zram-generator.conf; sudo -n cp -p $f.g2-backup $f && grep zram-size $f; sudo -n systemctl enable --now ModemManager 2>&1 | tail -1' ;;
  *) sed -n 2,9p "$0"; exit 2 ;;
esac
