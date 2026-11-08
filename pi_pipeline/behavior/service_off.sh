#!/bin/bash
# Stop the g2-voice service the safe way (owner, 2026-11-08: "don't leave G2 standing when the voice service is offline because I can't put him in rest myself"):
#   pi_pipeline/behavior/service_off.sh
# lays him down first, then stops the service. With the service stopped nothing holds or moves the servos, so a standing G2 would stay standing until someone rests him.
# He is laid in the rest position whatever the tilt (owner, 2026-11-08: always rest him after a fall; a krest to one lying on his side once dropped him again, which he accepts). If the board does not answer nothing can be sent and it says so.
cd "$(dirname "$0")/../.." || exit 1
systemctl is-active --quiet g2-voice && sudo systemctl stop g2-voice && sleep 2
pi_pipeline/.venv/bin/python - <<'P' 2>&1 | grep -v "^LOG\|unreadable"
import time
from pi_pipeline.link.serial_link import SerialLink
from pi_pipeline.behavior import ball_chase as chase
lk = SerialLink("/dev/serial0"); lk.connect(); time.sleep(0.8)
r = chase.SerialRobot(lk)
j = chase.read_joints(lk, timeout_s=1.5)
pose = chase.classify_pose(j) if j else None
t = r._tilt(0.8)
if pose == "rest":
    print("service off; G2 already at rest")
elif pose is None and t is None:
    print("service off; the board does not answer (pose and tilt unreadable): nothing could be sent. Check the Pi-to-BiBoard plug.")
else:
    lk.send("krest", read_reply=False, settle=0.0)
    time.sleep(3.0)
    j2 = chase.read_joints(lk, timeout_s=1.5)
    print(f"service off; krest sent (pose was {pose}, tilt {t}), pose now:", chase.classify_pose(j2) if j2 else None)
P
