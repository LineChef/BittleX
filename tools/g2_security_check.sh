#!/usr/bin/env bash
# Read-only security check of G2's Pi (2026-11-17): what listens on the network, how SSH is set up, the firewall, updates, who can log in, radios, file permissions, and the .env's key NAMES.
#   tools/g2_security_check.sh
# Changes nothing and prints no secret: the .env is checked by names only (rule A2) plus its mode and owner, and the API key's expiry DATE line (not a secret). Needs G2_PI. A check that cannot run
# (no passwordless sudo, a tool not installed) says "could not verify": it never reads as passed. Keep the results private (not in the repo); the checklist in docs/guides/pi-bring-up.md is generic advice.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'bash -s' <<'REMOTE' || { echo "could not verify: the Pi did not answer" >&2; exit 3; }
echo "== OS and patch level"; . /etc/os-release; echo "$PRETTY_NAME, kernel $(uname -r), up $(uptime -p)"
echo "pending upgrades: $(apt list --upgradable 2>/dev/null | grep -vc '^Listing')"
echo "unattended-upgrades: $(systemctl is-enabled unattended-upgrades 2>&1 | head -1)"
echo "== listening sockets (proto local-address process)"
ss -tulnp 2>/dev/null | awk 'NR>1 {print $1, $5, $7}' | sort -u | head -20
echo "== SSH effective settings"
s=$( (sudo -n sshd -T 2>/dev/null || sshd -T 2>/dev/null) | grep -iE '^(passwordauthentication|permitrootlogin|pubkeyauthentication|kbdinteractiveauthentication|permitemptypasswords|x11forwarding) ' )
[ -n "$s" ] && echo "$s" || echo "could not verify (sshd -T needs root; no passwordless sudo)"
echo "authorized keys: $(grep -cE '^(ssh|ecdsa|sk-)' ~/.ssh/authorized_keys 2>/dev/null || echo 0)"
echo "ssh logins in the last 7 days: accepted $(journalctl -u ssh --since '7 days ago' --no-pager 2>/dev/null | grep -c 'Accepted'), failed $(journalctl -u ssh --since '7 days ago' --no-pager 2>/dev/null | grep -c 'Failed')"
echo "== firewall"
if ! sudo -n true 2>/dev/null; then echo "could not verify (no passwordless sudo)"
else f=$(sudo -n ufw status 2>/dev/null | head -2); n=$(sudo -n nft list ruleset 2>/dev/null | head -2)
  if [ -n "$f" ]; then echo "$f"; elif [ -n "$n" ]; then echo "nftables rules present"; else echo "no firewall rules found (ufw not active, nftables empty)"; fi; fi
echo "== accounts that can log in, and sudo"
getent passwd | awk -F: '$7 !~ /nologin|false|sync/ {print $1, $7}'
echo "sudo group: $(getent group sudo | cut -d: -f4)"
sudo -n true 2>/dev/null && echo "passwordless sudo: yes for this account" || echo "passwordless sudo: no"
echo "== radios and discovery"
for u in avahi-daemon bluetooth hciuart wpa_supplicant; do echo "$u: $(systemctl is-active $u 2>&1 | head -1)"; done
echo "== data at rest"
echo "encrypted volumes (crypt): $(lsblk -no TYPE 2>/dev/null | grep -c crypt)"
stat -c "%a %U %n" ~/.local/share/g2 ~/bittleX/.env ~/.local/share/g2/goal_journal.jsonl 2>/dev/null
for f in ~/.local/share/g2/*.db ~/g2_memory*.db; do [ -f "$f" ] && stat -c "%a %U %n" "$f"; done 2>/dev/null | head -4
echo "== .env on the Pi: key names only (values are never printed)"
cut -d= -f1 ~/bittleX/.env 2>/dev/null | grep -vE '^(#|$)' | sort | tr '\n' ' '; echo
echo "ANTHROPIC_API_KEY set: $(grep -c '^ANTHROPIC_API_KEY=.' ~/bittleX/.env 2>/dev/null)"
grep '^ANTHROPIC_API_KEY_EXPIRES=' ~/bittleX/.env 2>/dev/null | head -1
REMOTE
