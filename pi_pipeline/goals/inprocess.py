"""A goal session inside the voice service (user, 2026-11-05: "lets run goals inside the voice service. that seems to be what works best for exploration").

Until now a goal session was its own process: `g2goal run` / "G2, ball goal" stopped the voice service, opened /dev/serial0 afresh and started the service again at the end. That
hand-over is when the BiBoard so often went silent (docs/STATUS.md open problems 15 and 18: no answer to `P`, `?` or `gP`, no IMU frames, so the learned walk could not start and the
session ended `board_silent` after 9 seconds). The voice service never closes the port, so the session now borrows its parts instead, as an in-process exploration does
(`explore_session.run_inprocess`): the shared serial link, the IMU fan-out (this session reads its own copy), the camera and the speech engine. Nothing is stopped or restarted.

Two ways in, both ending in `run_goal_inprocess` on the voice-loop thread:
  * "G2, ball goal" by voice: `voice/__main__.py` runs it there when `ready()` (otherwise it falls back to the old hand-over, `goal_launch.py`);
  * `g2goal run GOAL` from the Mac: `delegate()` writes a request file; a watcher thread in the service hands the goal's start phrase to the voice loop (`wake.poke`), which takes it as
    if it had been said, so the same spoken confirmation, attachment check and `arm_goal` event follow. The CLI then follows the session's log (`SESSION_LOG`) until it ends.

`G2_GOAL_INPROCESS=0` turns it off (the old stop-and-restart hand-over is used). Stop with `g2ballstop` / `g2goal stop` as before (the same stop files). While the session runs the voice loop
is busy, so the wake word and the stop words are not heard (as in the old hand-over, where the service was stopped); the BiBoard's own voice module still obeys.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("g2.goal")

RUNNING = "~/.local/share/g2/goal_running"   # exists while a session runs in the service: the deploy and the sync wait for it (tools/g2_deploy_when_online.sh, tools/g2_sync.sh)
REQUEST = "~/.local/share/g2/goal_request.json"
SESSION_LOG = "~/.local/share/g2/goal_session.log"
STALE_REQUEST_S = 120.0                  # a request older than this is ignored: nobody is waiting for it any more
START_MARK, END_MARK, HANDOVER_MARK = "== START", "== END", "== HANDOVER"


def enabled() -> bool:
    return os.environ.get("G2_GOAL_INPROCESS", "1").strip().lower() not in ("0", "off", "false", "no")


def request_path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOAL_REQUEST", REQUEST))


def running_path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOAL_RUNNING", RUNNING))


def log_path() -> str:
    return os.path.expanduser(os.environ.get("G2_GOAL_SESSION_LOG", SESSION_LOG))


NEEDS_EXPLORATION = ("discover_objects",)                 # approaches that run an exploration roam: they need the service ready for an in-process exploration too


def ready(shared, goal_id: str | None = None) -> tuple[bool, str]:
    """Whether a goal can run inside the voice service, and why not."""
    if not enabled():
        return False, "G2_GOAL_INPROCESS is off"
    if shared is None or getattr(shared, "link", None) is None:
        return False, "no serial link"
    if getattr(shared, "camera", None) is None:
        return False, "no camera in this service"
    if goal_id in NEEDS_EXPLORATION:
        from ..explore_session import inprocess_ready
        ok, why = inprocess_ready(shared)
        if not ok:
            return False, f"this goal explores, and an exploration cannot run inside the service: {why}"
    return True, ""


# ---------------------------------------------------------------------------------------------------- the session's log (what the CLI follows)
def log_line(text: str) -> None:
    """Append one line to the session log (never raises) and to the service log."""
    log.info("%s", text)
    try:
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
    except OSError:
        pass


def log_size() -> int:
    try:
        return os.path.getsize(log_path())
    except OSError:
        return 0


def read_log_from(offset: int) -> tuple[str, int]:
    """(the text written to the session log since byte `offset`, the new offset). A log that shrank (rotated or cleared) is read from the start."""
    try:
        with open(log_path(), "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            if end < offset:
                offset = 0
            f.seek(offset)
            data = f.read()
            return data.decode("utf-8", "replace"), offset + len(data)
    except OSError:
        return "", offset


# ---------------------------------------------------------------------------------------------------- the request file
def request(goal_id: str) -> None:
    """Ask the running voice service to start this goal (written atomically)."""
    p = request_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"goal": goal_id, "time": time.time()}, f)
    os.replace(tmp, p)


def pending_request(now: float | None = None) -> str | None:
    """The goal id in a fresh request file, or None (no file, unreadable, or older than STALE_REQUEST_S)."""
    try:
        d = json.load(open(request_path()))
        if (time.time() if now is None else now) - float(d.get("time", 0)) > STALE_REQUEST_S:
            return None
        return str(d.get("goal") or "") or None
    except (OSError, ValueError, TypeError):
        return None


def clear_request() -> None:
    try:
        os.remove(request_path())
    except OSError:
        pass


def start_phrase(goal_id: str) -> str | None:
    """The first spoken start phrase of a task goal ("ball goal"), which the voice loop turns into the same command as if it had been said."""
    from . import spec
    g = spec.load()[0].get(goal_id)
    if g is None or getattr(g, "kind", "task") != "task" or not getattr(g, "start_words", ()):
        return None
    return g.start_words[0]


def watch(poke, *, interval: float = 1.0, stop: threading.Event | None = None) -> threading.Thread:
    """A daemon thread for the voice service: when `g2goal run` leaves a request, hand its goal's start phrase to the voice loop with `poke(phrase)`."""
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            try:
                gid = pending_request()
                if gid:
                    clear_request()
                    phrase = start_phrase(gid)
                    if phrase:
                        log_line(f"request for {gid}: handing {phrase!r} to the voice loop")
                        poke(phrase)
                    else:
                        log_line(f"{END_MARK} " + json.dumps({"goal": gid, "why": "no start phrase: not a task goal"}) + " ==")
            except Exception:  # noqa: BLE001 -- a bad request must not stop the watcher
                log.exception("goal request watcher")
            stop.wait(interval)

    t = threading.Thread(target=loop, name="goal-request", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------------------------------- the session
def run_goal_inprocess(shared, goal_id: str) -> dict:
    """Run one goal session on the calling (voice loop) thread with the service's own parts, and return the session summary. G2 is rested at the end, however it ended."""
    from . import spec
    from .__main__ import _stop_requested, stop_path
    from .approach import make
    from .runner import GoalSession
    from ..behavior.ball_chase import STOP_FILE as CHASE_STOP

    goals, _problems = spec.load()
    g = goals.get(goal_id)
    if g is None or getattr(g, "kind", "task") != "task":
        log_line(f"{START_MARK} {goal_id} ==")
        summary = {"goal": goal_id, "why": "not a task goal"}
        log_line(f"{END_MARK} " + json.dumps(summary) + " ==")
        return summary
    for f in (stop_path(), os.path.expanduser(CHASE_STOP)):
        try:
            os.remove(f)
        except OSError:
            pass
    announce = None
    if getattr(shared, "tts", None) is not None:
        def announce(text, _tts=shared.tts):
            if text:
                _tts.speak(text)
    log_line(f"{START_MARK} {goal_id} ==")
    try:
        os.makedirs(os.path.dirname(running_path()), exist_ok=True)
        open(running_path(), "w").write(goal_id + "\n")
    except OSError:
        pass
    shared.exploring.set()                    # the service's stand guard, battery watch and sleep watch stand aside meanwhile
    summary: dict = {"goal": goal_id, "why": "error"}
    try:
        approach = make(g.approach, shared=shared)
        res = GoalSession(g, approach, stop=_stop_requested, say=log_line, announce=announce).run()
        summary = {k: res.get(k) for k in ("session", "goal", "why", "attempts", "successes", "minutes", "lessons_saved") if k in res}
    except Exception as e:  # noqa: BLE001
        log.exception("goal session failed")
        log_line(f"the goal session failed: {type(e).__name__}: {e}")
        summary = {"goal": goal_id, "why": f"error: {type(e).__name__}"}
        try:
            shared.link.send("krest", read_reply=False, settle=0.0)       # never leave him up after a failure
        except Exception:  # noqa: BLE001
            pass
    finally:
        shared.exploring.clear()
        try:
            os.remove(running_path())
        except OSError:
            pass
        log_line(f"{END_MARK} " + json.dumps(summary, default=str) + " ==")
    return summary


# ---------------------------------------------------------------------------------------------------- the CLI side (`g2goal run`)
def service_active(unit: str = "g2-voice", run=subprocess.run) -> bool:
    try:
        return run(["systemctl", "is-active", "--quiet", unit], timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _parse_end(text: str) -> dict | None:
    for line in text.splitlines():
        i = line.find(END_MARK)
        if i >= 0:
            body = line[i + len(END_MARK):].strip().rstrip("=").strip()
            try:
                return json.loads(body)
            except ValueError:
                return {"why": "ended"}
    return None


def delegate(goal_id: str, *, say=print, start_wait_s: float = 45.0, poll_s: float = 0.5, sleep=time.sleep, clock=time.monotonic, run=subprocess.run) -> dict | None:
    """Ask the running voice service to run the goal and follow its log until it ends. Returns the session summary, or None when the service cannot take it
    (not running, or in-process goals are off: the caller then uses the old stop-and-run way)."""
    if not enabled() or not service_active(run=run):
        return None
    offset = log_size()
    request(goal_id)
    seen = ""
    t0 = clock()
    started = False
    while True:
        new, offset = read_log_from(offset)
        if new:
            for line in new.splitlines():
                say(line)
            seen += new
            if HANDOVER_MARK in new:                                   # the service could not run it itself and started the old separate session
                say("(the voice service started the goal as a separate session; follow it with `g2goal status` and `journalctl -u g2-goal -f`)")
                return {"goal": goal_id, "why": "handover"}
            if START_MARK in seen:
                started = True
            end = _parse_end(seen)
            if end is not None:
                return end
        if not started and clock() - t0 > start_wait_s:
            clear_request()
            say("the voice service did not take the goal in time (busy talking, or not listening): using the stop-and-run way")
            return None
        try:
            sleep(poll_s)
        except KeyboardInterrupt:                                      # Ctrl-C: ask the session to stop, then keep following until it says it has
            open(os.path.expanduser("~/.local/share/g2/goal_stop"), "w").close()
            say("stop requested: the session ends after the current move")
            deadline = clock() + 90
            while clock() < deadline:
                new, offset = read_log_from(offset)
                seen += new
                for line in new.splitlines():
                    say(line)
                end = _parse_end(seen)
                if end is not None:
                    return end
                sleep(poll_s)
            return {"goal": goal_id, "why": "stopped"}
