"""G2's guards, built ONE way for every mode (owner, 2026-11-13: "any change we make to G2 in any mode should apply to all modes").

The voice service and the exploration used to build their own `StandGuard` with different options (the voice service had no deaf-board end and no walking-sag recovery; the exploration had both) and
their own copies of the sag recovery and the words said after a fall. Now a mode calls `install()` and supplies only what is really its own:
  - how it PAUSES its walking while a recovery runs (`hold` / `release`),
  - how it ENDS when a guard fires (`on_fall`, `on_silent`),
  - whether the guard stands aside (`is_busy`).
Everything else is here, the same for every mode: the thresholds (pi_pipeline/body.py), the sag recovery, the response to a deaf board, the words after a fall, the settings the guard runs with.
`tools/check_modes.py` fails when a mode builds a `StandGuard` itself.
"""
from __future__ import annotations

import logging
import threading

from .stand_guard import StandGuard

log = logging.getLogger("g2.body_guards")

FALL_WORDS = "I fell down. I have stopped."
DEAF_WORDS = "My motion sensor stopped answering. I have stopped. Please check the plug to the board."


def announce_fall(say, horn=None) -> threading.Thread:
    """The response to a fall that is the same in every mode: the losing horn, then the words. On its own thread, because it runs on the guard's or the walker's thread and must never wait for the speaker;
    the caller that must not exit before it has finished joins the returned thread."""
    def run():
        try:
            if horn is not None:
                horn()
        except Exception:  # noqa: BLE001
            log.debug("the fall horn failed", exc_info=True)
        try:
            say(FALL_WORDS)
        except Exception:  # noqa: BLE001
            log.debug("saying the fall words failed", exc_info=True)
    th = threading.Thread(target=run, name="fall-announce", daemon=True)
    th.start()
    return th


def lay_down_deaf_board(link, say, *, halt=None) -> threading.Thread:
    """The response to a board that has stopped sending motion data, the same in every mode: whatever is moving is halted, balance off and the rest command go out at once (a deaf board cannot confirm
    anything, so nothing is waited for), and he says why. The mode then ends itself. Returns the announcement thread."""
    if halt is not None:
        try:
            halt()
        except Exception:  # noqa: BLE001
            log.debug("halting for a deaf board failed", exc_info=True)
    for c in ("gb", "krest"):
        try:
            link.send(c, read_reply=False, settle=0.0)
        except Exception:  # noqa: BLE001
            log.debug("could not send %s to a deaf board", c, exc_info=True)

    def run():
        try:
            say(DEAF_WORDS)
        except Exception:  # noqa: BLE001
            log.debug("saying the deaf-board words failed", exc_info=True)
    th = threading.Thread(target=run, name="deaf-announce", daemon=True)
    th.start()
    return th


def make_sag_recover(*, new_consumer, release_consumer, hold=None, release=None):
    """The sag recovery every mode uses: the walking is held (`hold`), the legs go down into the attention pose and up again, back legs first (`ball_chase.SerialRobot.recover_sag`, on its own copy of
    the IMU stream), and the walking is released (`release`)."""
    def sag_recover(roll, pitch):
        from ..behavior.ball_chase import SerialRobot
        if hold is not None:
            hold()
        c = new_consumer()
        try:
            SerialRobot(c).recover_sag((pitch, roll))
        finally:
            if release is not None:
                try:
                    release()
                except Exception:  # noqa: BLE001
                    log.debug("releasing the walking after a sag failed", exc_info=True)
            try:
                release_consumer(c)
            except Exception:  # noqa: BLE001
                log.debug("releasing the IMU stream after a sag failed", exc_info=True)
    return sag_recover


def install(link, *, settings, new_consumer, release_consumer, is_busy, on_fall, on_silent, hold=None, release=None) -> StandGuard:
    """Build and start THE guard: fall, sag (standing and walking), wobble and a deaf board, with the settings every mode shares. `link` is where the last motion command is read (what he is doing now);
    `new_consumer()` gives the guard its own copy of the IMU stream. Returns the started StandGuard (its `note_activity` is for the actuator, its `stop` for the mode's end)."""
    def last() -> str:
        return str(getattr(link, "last_motion_command", "") or "")
    return StandGuard(new_consumer(), on_sag=make_sag_recover(new_consumer=new_consumer, release_consumer=release_consumer, hold=hold, release=release),
                      is_standing=lambda: last() not in ("", "d", "krest", "ksit", "kcalib"), is_busy=is_busy, guard=settings.stand_guard,
                      is_walking=lambda: last()[:3] in ("kwk", "kbk"), balance_off_idle=settings.balance_off_idle, reassert_s=settings.stand_reassert_s,
                      reenable_after_s=None if settings.balance_off_idle else 300.0, on_fall=on_fall, on_silent=on_silent).start()
