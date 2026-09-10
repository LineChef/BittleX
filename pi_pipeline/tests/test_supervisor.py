import threading
import time

from pi_pipeline.util.supervisor import (
    Decision, Supervisor, WatchAction, WatchdogConfig, WatchdogPolicy,
)


# --------------------------------------------------------------- WatchdogPolicy
def _pol(**cfg):
    return WatchdogPolicy(WatchdogConfig(**cfg))


def test_first_poll_wants_a_start():
    p = _pol()
    assert p.poll(0.0).action is WatchAction.RESTART


def test_healthy_worker_keeps_running():
    p = _pol(startup_grace_s=1.0, heartbeat_timeout_s=2.0)
    p.on_start(0.0)
    for t in range(1, 20):
        p.on_heartbeat(float(t) * 0.5)
        assert p.poll(float(t) * 0.5).action is WatchAction.RUN


def test_exit_triggers_a_restart():
    p = _pol()
    p.on_start(0.0)
    p.on_exit(1.0, RuntimeError("boom"))
    d = p.poll(1.0)
    assert d.action is WatchAction.RESTART
    assert "boom" in d.reason


def test_clean_return_is_also_a_restart():
    p = _pol()
    p.on_start(0.0)
    p.on_exit(1.0, None)
    d = p.poll(1.0)
    assert d.action is WatchAction.RESTART
    assert "returned" in d.reason


def test_stale_heartbeat_after_grace_triggers_restart():
    p = _pol(startup_grace_s=2.0, heartbeat_timeout_s=3.0)
    p.on_start(0.0)
    p.on_heartbeat(1.0)
    assert p.poll(3.5).action is WatchAction.RUN          # within grace+timeout of last beat
    d = p.poll(4.5)                                       # 3.5 s since last beat
    assert d.action is WatchAction.RESTART
    assert "no heartbeat" in d.reason


def test_startup_grace_suppresses_the_stale_check():
    p = _pol(startup_grace_s=5.0, heartbeat_timeout_s=1.0)
    p.on_start(0.0)
    assert p.poll(3.0).action is WatchAction.RUN          # no beats yet, but still in grace


def test_backoff_doubles_each_restart():
    p = _pol(backoff_base_s=0.5, backoff_max_s=10.0, max_restarts_in_window=99)
    delays = []
    for k in range(4):
        p.on_start(float(k))
        p.on_exit(float(k) + 0.1, RuntimeError("x"))
        delays.append(p.poll(float(k) + 0.1).delay_s)
    assert delays == [0.5, 1.0, 2.0, 4.0]


def test_gives_up_after_too_many_restarts_in_window():
    p = _pol(restart_window_s=60.0, max_restarts_in_window=3)
    for k in range(3):
        p.on_start(float(k))
        p.on_exit(float(k) + 0.1, RuntimeError("x"))
        assert p.poll(float(k) + 0.1).action is WatchAction.RESTART
    p.on_start(3.0)
    p.on_exit(3.1, RuntimeError("x"))
    d = p.poll(3.1)
    assert d.action is WatchAction.GIVE_UP
    assert p.given_up


def test_restart_window_prunes_so_slow_failures_recover():
    p = _pol(restart_window_s=10.0, max_restarts_in_window=2, startup_grace_s=0.0)
    # a failure every 20 s -- never more than 1 in the 10 s window
    for k in range(6):
        base = k * 20.0
        p.on_start(base)
        p.on_exit(base + 1.0, RuntimeError("x"))
        assert p.poll(base + 1.0).action is WatchAction.RESTART
    assert not p.given_up


# --------------------------------------------------------------- Supervisor
def _events():
    log = []
    return log, lambda sub, lvl, name, **kv: log.append((name, kv))


def _wait(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_supervisor_runs_a_worker_until_stopped():
    log, emit = _events()
    beats = [0]

    def worker(ctx):
        while not ctx.stopping.wait(0.02):
            ctx.beat()
            beats[0] += 1

    s = Supervisor("w", worker, emit=emit,
                   cfg=WatchdogConfig(heartbeat_timeout_s=1.0, startup_grace_s=0.5),
                   poll_interval_s=0.05)
    s.start()
    assert _wait(lambda: beats[0] > 3)
    s.stop()
    assert not s.alive
    assert s.restart_count == 0
    assert any(n == "worker.started" for n, _ in log)
    assert any(n == "worker.stopped" for n, _ in log)


def test_supervisor_restarts_a_crashing_worker_then_gives_up():
    log, emit = _events()
    starts = [0]

    def worker(ctx):
        starts[0] += 1
        raise RuntimeError("always dies")

    s = Supervisor("crasher", worker, emit=emit,
                   cfg=WatchdogConfig(startup_grace_s=0.0, backoff_base_s=0.02,
                                      backoff_max_s=0.05, restart_window_s=5.0,
                                      max_restarts_in_window=3),
                   poll_interval_s=0.03)
    s.start()
    assert _wait(lambda: s.given_up, timeout=4.0)
    s.stop()
    assert starts[0] >= 3
    assert any(n == "worker.gave_up" for n, _ in log)


def test_supervisor_restarts_a_worker_that_stops_beating():
    log, emit = _events()
    runs = [0]

    def worker(ctx):
        runs[0] += 1
        first = runs[0] == 1
        # run #1 beats a couple times then goes silent (but doesn't exit);
        # later runs beat normally until stopped
        n = 0
        while not ctx.stopping.wait(0.02):
            n += 1
            if first and n > 2:
                continue          # stop beating -- watchdog should notice
            ctx.beat()

    s = Supervisor("silent", worker, emit=emit,
                   cfg=WatchdogConfig(heartbeat_timeout_s=0.2, startup_grace_s=0.1,
                                      backoff_base_s=0.02, max_restarts_in_window=10),
                   poll_interval_s=0.03)
    s.start()
    assert _wait(lambda: runs[0] >= 2, timeout=4.0)     # got restarted after going silent
    s.stop()
    assert any(n == "worker.restart" for n, _ in log)


def test_supervisor_stop_is_idempotent_and_prompt():
    _, emit = _events()

    def worker(ctx):
        while not ctx.stopping.wait(0.05):
            ctx.beat()

    s = Supervisor("w", worker, emit=emit, poll_interval_s=0.05)
    s.start()
    time.sleep(0.15)
    t0 = time.monotonic()
    s.stop()
    s.stop()                              # second call must not raise / hang
    assert time.monotonic() - t0 < 2.0
    assert not s.alive
