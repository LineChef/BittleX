#!/usr/bin/env bash
# pi_pipeline/install_voice_service.sh
# Start the G2 voice loop automatically whenever the Pi boots (a systemd service).
# Run on the Pi as the normal user, after pi_pipeline + its venv + models are in place:
#     bash ~/bittleX/pi_pipeline/install_voice_service.sh            # install + enable + start now
#     bash ~/bittleX/pi_pipeline/install_voice_service.sh --dry-run  # print the unit, change nothing
#     bash ~/bittleX/pi_pipeline/install_voice_service.sh --remove    # stop + disable + delete it
# Idempotent. Logs:  journalctl -u g2-voice -f     Stop for a test:  sudo systemctl stop g2-voice
# Settings (speech output, gait cap, API key, ...) come from ~/bittleX/.env, e.g. G2_TTS=print,
# G2_MAX_GAIT_S=5; restart after editing:  sudo systemctl restart g2-voice
set -euo pipefail

UNIT=/etc/systemd/system/g2-voice.service
ROOT="${G2_ROOT:-$HOME/bittleX}"
PY="$ROOT/pi_pipeline/.venv/bin/python"

render() {
cat <<EOF
[Unit]
Description=G2 voice loop (wake word, speech-to-text, Claude, serial actuator)
After=network-online.target sound.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
User=$(id -un)
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONFAULTHANDLER=1
ExecStart=$PY -m pi_pipeline.voice --mode voice --actuator serial
Restart=on-failure
RestartSec=1

[Install]
WantedBy=multi-user.target
EOF
}

case "${1:-install}" in
  --dry-run) render; exit 0 ;;
  --remove)
    sudo systemctl disable --now g2-voice 2>/dev/null || true
    sudo rm -f "$UNIT"; sudo systemctl daemon-reload
    echo "g2-voice service removed"; exit 0 ;;
  install) ;;
  *) echo "usage: $0 [--dry-run|--remove]" >&2; exit 2 ;;
esac

if [ "$(id -u)" -eq 0 ]; then echo "Run as the normal user, not root." >&2; exit 1; fi
[ -x "$PY" ] || { echo "no venv at $PY -- set up pi_pipeline first (see docs/guides/pi-bring-up.md)" >&2; exit 1; }
[ -f "$ROOT/.env" ] || echo "warning: $ROOT/.env missing -- the loop needs ANTHROPIC_API_KEY there" >&2

render | sudo tee "$UNIT" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable g2-voice
sudo systemctl restart g2-voice
sleep 3
systemctl --no-pager --lines=5 status g2-voice || true
echo "installed: starts on every boot. Logs: journalctl -u g2-voice -f"
