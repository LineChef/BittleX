"""Sleep mode -- the deep-idle state below `IdlePosture.RESTING` (behaviour-ideas B18).

RESTING already lies down and de-energises the leg servos. Sleep mode goes
further, for when G2 is parked and unattended for a long stretch:

  * curl up (`opencat.SLEEP` / `kzz`) instead of lying flat
  * vision off (camera `Xc`)
  * CPU governor down + Wi-Fi power-save on (`python -m pi_pipeline.power headless`)

and it only wakes on a real signal: an IMU tap / lift (the balance IMU is
always on anyway), a loud sound, the wake word, or an explicit command.

Pure logic + a clock, same shape as `idle_posture.py` / `mode_controller.py`.
Composes with `IdlePosture`: pass its RESTING status in each tick; on WAKE the
caller powers back up, uncurls, and hands control back to `IdlePosture` (which
will be roused via its own `on_activity`).

  AWAKE    -- not sleeping. IdlePosture owns the pose.
  DOZING   -- entering: caller curls up + powers down, then calls `settled()`
              (or it auto-advances after `settle_timeout_s`).
  ASLEEP   -- fully down. Only a wake signal leaves this state.
  ROUSING  -- waking: caller powers up + uncurls, then calls `wake_done()`
              (auto-completes after `rouse_timeout_s`).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class SleepState(Enum):
    AWAKE = "awake"
    DOZING = "dozing"
    ASLEEP = "asleep"
    ROUSING = "rousing"


class SleepAction(Enum):
    NONE = "none"
    ENTER_SLEEP = "enter_sleep"   # curl up (kzz) + vision off + power-save on
    WAKE = "wake"                 # power up + uncurl + hand back to IdlePosture


@dataclass
class SleepModeConfig:
    sleep_after_resting_s: float = 300.0   # continuous RESTING before auto-sleep
    person_present_blocks: bool = True     # a person nearby blocks *auto* sleep (command still works)
    min_sleep_s: float = 15.0              # ignore wake signals for this long after entering (anti-thrash)
    settle_timeout_s: float = 4.0          # DOZING auto-advances to ASLEEP if settled() never comes
    rouse_timeout_s: float = 5.0           # ROUSING auto-finishes if wake_done() never comes
    loud_sound_wakes: bool = True


class SleepMode:
    def __init__(self, cfg: SleepModeConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or SleepModeConfig()
        self._clock = clock
        self._state = SleepState.AWAKE
        self._since = clock()
        self._resting_since: float | None = None
        self._commanded = False
        self._reason = "init"

    @property
    def state(self) -> SleepState:
        return self._state

    @property
    def asleep(self) -> bool:
        return self._state in (SleepState.DOZING, SleepState.ASLEEP)

    @property
    def last_reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        self.__init__(self.cfg, clock=self._clock)

    def _enter(self, s: SleepState, now: float, reason: str):
        self._state = s
        self._since = now
        self._reason = reason
        return s, (SleepAction.ENTER_SLEEP if s is SleepState.DOZING
                   else SleepAction.WAKE if s is SleepState.ROUSING
                   else SleepAction.NONE)

    # --- events ---------------------------------------------------------------
    def on_command_sleep(self) -> None:
        """Explicit 'go to sleep' -- overrides the person-present block."""
        self._commanded = True

    def on_activity(self) -> None:
        """Any deliberate interaction -- rouse if sleeping."""
        now = self._clock()
        if self._state in (SleepState.DOZING, SleepState.ASLEEP):
            self._enter(SleepState.ROUSING, now, "activity -> rouse")

    def settled(self) -> None:
        if self._state is SleepState.DOZING:
            self._enter(SleepState.ASLEEP, self._clock(), "settled -> asleep")

    def wake_done(self) -> None:
        if self._state is SleepState.ROUSING:
            self._enter(SleepState.AWAKE, self._clock(), "wake choreography done -> awake")

    # --- tick ---------------------------------------------------------------
    def update(self, now: float | None = None, *, resting: bool,
               person_present: bool = False, loud_sound: bool = False,
               imu_tap: bool = False, wake_word: bool = False,
               ) -> tuple[SleepState, SleepAction]:
        now = self._clock() if now is None else now
        c = self.cfg

        # track how long IdlePosture has been in RESTING
        if resting:
            self._resting_since = self._resting_since or now
        else:
            self._resting_since = None

        wake_signal = imu_tap or wake_word or (loud_sound and c.loud_sound_wakes)

        if self._state is SleepState.ROUSING:
            if now - self._since >= c.rouse_timeout_s:
                return self._enter(SleepState.AWAKE, now, "rouse timed out -> awake")
            self._reason = "rousing, caller powering up"
            return self._state, SleepAction.NONE

        if self._state is SleepState.DOZING:
            if wake_signal:
                return self._enter(SleepState.ROUSING, now, "wake signal during doze -> rouse")
            if now - self._since >= c.settle_timeout_s:
                self._state = SleepState.ASLEEP
                self._since = now
                self._reason = "settle timed out -> asleep"
            else:
                self._reason = "dozing, caller curling up + powering down"
            return self._state, SleepAction.NONE

        if self._state is SleepState.ASLEEP:
            if not resting:
                # IdlePosture got roused out from under us -- follow it
                return self._enter(SleepState.ROUSING, now, "no longer resting -> rouse")
            if wake_signal and now - self._since >= c.min_sleep_s:
                kind = ("imu tap" if imu_tap else "wake word" if wake_word else "loud sound")
                return self._enter(SleepState.ROUSING, now, f"{kind} -> rouse")
            self._reason = ("asleep (min-sleep hold)" if wake_signal
                            else "asleep")
            return self._state, SleepAction.NONE

        # AWAKE: decide whether to fall asleep
        if self._commanded:
            self._commanded = False
            return self._enter(SleepState.DOZING, now, "commanded to sleep")
        if not resting:
            self._reason = "awake (not resting)"
            return self._state, SleepAction.NONE
        if person_present and c.person_present_blocks:
            self._reason = "awake (person present blocks auto-sleep)"
            return self._state, SleepAction.NONE
        rested = now - (self._resting_since or now)
        if rested >= c.sleep_after_resting_s:
            return self._enter(SleepState.DOZING, now,
                               f"{rested:.0f}s resting >= {c.sleep_after_resting_s:.0f}s")
        self._reason = f"awake (resting {rested:.0f}s / {c.sleep_after_resting_s:.0f}s)"
        return self._state, SleepAction.NONE


# caller maps these onto real commands / subprocess calls
ACTION_HINT = {
    SleepAction.ENTER_SLEEP: "kzz + camera Xc off + `python -m pi_pipeline.power headless`",
    SleepAction.WAKE: "`python -m pi_pipeline.power interactive` + camera on + kstr/kup, then IdlePosture.on_activity()",
    SleepAction.NONE: "",
}
