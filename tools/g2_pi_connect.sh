#!/usr/bin/env bash
# ssh ProxyCommand for G2's Pi: connect by name, or by its last known address when the name does not resolve.
# On 2026-10-18 the Mac's lookup of g2pi.local failed several times while the Pi was up and answering on its address, and every g2* tool, deploy and
# alias failed with it. Installed by tools/g2_pi_ssh_setup.sh as a `Host g2pi.local` block in ~/.ssh/config, so every ssh / rsync / scp to the Pi goes
# through here with no change to the tools; ssh still checks the Pi's host key under the name g2pi.local, so a wrong address fails, never connects.
#   g2_pi_connect.sh HOST [PORT]
# Order: the name (2 s cap: a failed lookup otherwise hangs 10 s), then the address saved the last time the name worked
# (~/.local/share/g2/pi_last_ip), then the router's address table (`arp -a` lists the Pi by its short name).
host="$1"; port="${2:-22}"
cache="$HOME/.local/share/g2/pi_last_ip"
ip=$(perl -e 'alarm shift; exec @ARGV' 2 dscacheutil -q host -a name "$host" 2>/dev/null | awk '/^ip_address:/ {print $2; exit}')
if [ -n "$ip" ]; then
  mkdir -p "$(dirname "$cache")" && echo "$ip" > "$cache"
  exec nc "$ip" "$port"
fi
ip=$(cat "$cache" 2>/dev/null)
if [ -z "$ip" ] || ! nc -z -G 2 "$ip" "$port" 2>/dev/null; then
  ip=$(arp -a 2>/dev/null | awk -v h="${host%.local}" '$1 == h {gsub(/[()]/, "", $2); print $2; exit}')
fi
[ -n "$ip" ] || { echo "g2_pi_connect: $host does not resolve and no address for it is known" >&2; exit 1; }
mkdir -p "$(dirname "$cache")" && echo "$ip" > "$cache"
exec nc "$ip" "$port"
