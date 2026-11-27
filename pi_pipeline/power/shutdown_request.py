"""Ask the running voice service to power the Pi down the way a spoken "shut down" does (owner, 2026-11-27: G2 must say "Powering down" whenever the shutdown signal is sent, so the owner knows the Pi is shutting down before the power is cut).

The wrap-up (`tools/g2_session_shutdown.sh`) touches a request file over ssh; the voice service's watcher takes it and hands "shut down" to the voice loop, so ONE path does it every time: the loop says "Powering down.", listens `shutdown_confirm_s` for "cancel", lies G2 down and sends `sudo shutdown -h now` (`voice/__main__.power_off_pi`). The watcher deletes the file when it takes the request, which is how the script knows the service heard it."""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger("g2.power")
PHRASE = "shut down"


def request_path() -> str:
    return os.path.expanduser(os.environ.get("G2_SHUTDOWN_REQUEST", "~/.local/share/g2/shutdown_request"))


def pending() -> bool:
    return os.path.exists(request_path())


def clear() -> None:
    try:
        os.remove(request_path())
    except OSError:
        pass


def request() -> None:
    """What the wrap-up does over ssh (`touch`), for tests and by-hand use."""
    p = request_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()


def watch(poke, *, interval: float = 1.0, stop: threading.Event | None = None) -> threading.Thread:
    """A daemon thread for the voice service: when a power-down request appears, take it (delete the file) and hand "shut down" to the voice loop with `poke`."""
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            try:
                if pending():
                    clear()
                    log.info("power-down requested from outside: handing %r to the voice loop", PHRASE)
                    poke(PHRASE)
            except Exception:  # noqa: BLE001 -- a bad request must not stop the watcher
                log.exception("power-down request watcher")
            stop.wait(interval)

    t = threading.Thread(target=loop, name="power-down-request", daemon=True)
    t.start()
    return t
