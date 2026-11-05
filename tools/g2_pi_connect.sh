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
up() { [ -n "$1" ] && nc -z -G 3 "$1" "$port" 2>/dev/null; }          # does something answer on the ssh port there? (a stale address otherwise ends as "Connection closed by UNKNOWN port 65535")
tried=""
try() { [ -n "$1" ] || return 1; tried="$tried $1"; up "$1" || return 1; mkdir -p "$(dirname "$cache")" && echo "$1" > "$cache"; exec nc "$1" "$port"; }
try "$(perl -e 'alarm shift; exec @ARGV' 2 dscacheutil -q host -a name "$host" 2>/dev/null | awk '/^ip_address:/ {print $2; exit}')"
try "$(perl -e 'alarm shift; exec @ARGV' 4 dns-sd -G v4 "$host" 2>/dev/null | awk '/^[0-9].* Add / {print $6; exit}')"     # the name lookup above found no IPv4 address (it can list only the IPv6 one): ask mDNS for it
try "$(cat "$cache" 2>/dev/null)"
try "$(arp -a 2>/dev/null | awk -v h="${host%.local}" '$1 == h {gsub(/[()]/, "", $2); print $2; exit}')"
if [ -n "$tried" ]; then echo "g2_pi_connect: $host is known at$tried but nothing answers on port $port: the Pi is off, not on this network, or its ssh service is down" >&2
else echo "g2_pi_connect: $host does not resolve and no address for it is known" >&2; fi
exit 1
