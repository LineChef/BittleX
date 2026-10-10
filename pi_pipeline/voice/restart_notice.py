"""Say "G2 online." when the voice loop has finished starting, so you can tell he is ready (after a restart, a deploy, power-up, or an exploration session handing the voice service back).

`G2_ANNOUNCE_ONLINE=off` silences it. Nothing here may ever stop the voice loop from starting."""
from __future__ import annotations

import logging

log = logging.getLogger("g2.restart_notice")

ONLINE_LINE = "G2 online."


def announce_online(speak) -> bool:
    log.info("voice loop restarted: announcing that G2 is online")
    try:
        speak(ONLINE_LINE)
        return True
    except Exception:  # noqa: BLE001
        log.debug("online announcement failed", exc_info=True)
        return False
