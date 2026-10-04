#!/usr/bin/env bash
# Manage the Wi-Fi networks G2's Pi will auto-join (NetworkManager, Raspberry Pi OS Bookworm), from the Mac over ssh.
#   g2wifi list                 saved networks + priority + which one is active
#   g2wifi status               current connection and IP
#   g2wifi scan                 which networks the Pi can see right now (are your saved ones in range?)
#   g2wifi add <ssid>           save a network as a BACKUP (asks for the password; priority 50, below home's 100)
#   g2wifi remove <ssid>        forget a saved network (refuses the one currently in use)
# Needs  export G2_PI=<user>@g2pi.local.  Do the `add` while G2 is still on a network you can reach (e.g. at home);
# away from home the Pi then joins the saved network (e.g. your phone hotspot) by itself, and the Mac must be on it too.
# The password is sent over ssh on stdin (never in the repo, your shell history, or this machine's process list);
# NetworkManager stores it on the Pi in root-only files.
set -euo pipefail
host="${G2_PI:?set G2_PI=<user>@g2pi.local}"
rssh() { ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" "$@"; }
cmd="${1:-}"; shift || true
case "$cmd" in
  list)
    rssh 'nmcli -t -f NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY,ACTIVE connection show | grep ":802-11-wireless:" |
          awk -F: "{printf \"%-28s autoconnect=%-3s priority=%-4s %s\n\", \$1, \$3, \$4, (\$5==\"yes\" ? \"<- active\" : \"\")}"' ;;
  status)
    rssh 'nmcli -t -f DEVICE,STATE,CONNECTION device | grep "^wlan0"; ip -4 -o addr show wlan0 | awk "{print \$4}"' ;;
  scan)
    rssh 'sudo nmcli device wifi rescan >/dev/null 2>&1; sleep 4; nmcli -t -f IN-USE,SSID,SIGNAL device wifi list | awk -F: "\$2!=\"\"{printf \"%s %-30s signal %s\n\", (\$1==\"*\"?\"*\":\" \"), \$2, \$3}" | sort -u -k2,2' ;;
  add)
    ssid="${1:?usage: g2wifi add <ssid>}"
    read -r -s -p "Wi-Fi password for \"$ssid\" (8-63 chars; empty = open network): " psk; echo
    [ -z "$psk" ] || { [ ${#psk} -ge 8 ] && [ ${#psk} -le 63 ]; } || { echo "password must be 8-63 characters" >&2; exit 1; }
    printf '%s\n%s\n' "$ssid" "$psk" | rssh 'IFS= read -r SSID; IFS= read -r PSK
      sudo nmcli connection delete id "$SSID" >/dev/null 2>&1 || true
      if [ -n "$PSK" ]; then
        sudo nmcli connection add type wifi con-name "$SSID" ssid "$SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
          connection.autoconnect yes connection.autoconnect-priority 50 >/dev/null
      else
        sudo nmcli connection add type wifi con-name "$SSID" ssid "$SSID" \
          connection.autoconnect yes connection.autoconnect-priority 50 >/dev/null
      fi
      echo "saved \"$SSID\" (priority 50; the Pi prefers higher-priority networks that are in range)"'
    unset psk ;;
  remove)
    ssid="${1:?usage: g2wifi remove <ssid>}"
    printf '%s\n' "$ssid" | rssh 'IFS= read -r SSID
      if nmcli -t -f NAME,ACTIVE connection show | grep -qxF "$SSID:yes"; then echo "refusing: \"$SSID\" is the connection in use" >&2; exit 1; fi
      sudo nmcli connection delete id "$SSID"' ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; [ -z "$cmd" ] || exit 1 ;;
esac
