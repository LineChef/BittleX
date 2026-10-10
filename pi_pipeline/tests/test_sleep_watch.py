"""Power-saving sleep in the voice service (power/sleep_watch.py)."""
from pi_pipeline.power.sleep_watch import SleepWatch, WakeHook


def _watch(resting=True, busy=False, after=300.0):
    t = [0.0]
    ev = []
    w = SleepWatch(is_resting=lambda: resting, is_busy=lambda: busy, after_s=after, clock=lambda: t[0],
                   on_sleep=[lambda: ev.append("sigh")], on_wake=[lambda: ev.append("yawn")])
    return w, t, ev


def test_sleeps_after_the_rest_delay_and_wakes_once_with_a_yawn():
    w, t, ev = _watch()
    t[0] = 299.0
    assert w.tick() is False and not w.asleep
    t[0] = 301.0
    assert w.tick() is True and w.asleep and ev == ["sigh"]
    assert w.tick() is False                       # stays asleep, no second sigh
    assert w.wake() is True and ev == ["sigh", "yawn"] and not w.asleep
    assert w.wake() is False and ev == ["sigh", "yawn"]


def test_activity_or_not_resting_restarts_the_timer():
    w, t, ev = _watch()
    t[0] = 200.0
    w.note_activity()
    t[0] = 450.0
    assert w.tick() is False                       # only 250 s since the command
    w2, t2, ev2 = _watch(resting=False)
    t2[0] = 1000.0
    assert w2.tick() is False and not ev2
    w3, t3, ev3 = _watch(after=0)
    t3[0] = 1e6
    assert w3.tick() is False                      # 0 = off


def test_a_failing_step_does_not_stop_the_others_and_the_wake_hook_wakes():
    t = [0.0]
    ev = []
    def boom():
        raise RuntimeError("no speaker")
    w = SleepWatch(is_resting=lambda: True, after_s=10, clock=lambda: t[0], on_sleep=[boom, lambda: ev.append("wifi")], on_wake=[lambda: ev.append("up")])
    t[0] = 11
    assert w.tick() and ev == ["wifi"]

    class _Wake:
        phrase = "gee two"
        def wait(self):
            return "woke"
    hook = WakeHook(_Wake(), w)
    assert hook.wait() == "woke" and ev == ["wifi", "up"] and hook.phrase == "gee two"


def test_sigh_and_yawn_render():
    from pi_pipeline.voice import prompt_tones as pt
    for fn, lo, hi in ((pt.render_sigh, 1.2, 1.4), (pt.render_yawn, 1.3, 1.5)):
        y = fn()
        assert lo < y.size / 48000 < hi and abs(int(y.max())) > 300
