import random

from pi_pipeline.behavior.gestures import (
    Gesture, GestureConfig, GesturePicker, GESTURE_TOKEN, _IDLE_SET, _GREETING_SET,
)


def _picker(**cfg):
    t = [1000.0]
    p = GesturePicker(GestureConfig(**cfg), clock=lambda: t[0], rng=random.Random(0))
    return p, t


def test_every_gesture_has_a_token():
    for g in Gesture:
        if g is Gesture.NONE:
            continue
        assert g in GESTURE_TOKEN and GESTURE_TOKEN[g].startswith("k")


def test_no_fidget_until_idle_long_enough():
    p, _ = _picker(idle_min_quiet_s=12.0)
    assert p.update(idle_quiet_s=5.0) is Gesture.NONE
    assert "not idle long enough" in p.last_reason


def test_no_fidget_when_gated():
    p, _ = _picker()
    assert p.update(idle_quiet_s=60.0, can_gesture=False) is Gesture.NONE


def test_idle_fidget_eventually_fires_and_is_in_the_idle_set():
    p, t = _picker(idle_interval_s=10.0, idle_min_quiet_s=1.0)
    got = Gesture.NONE
    for _ in range(400):
        t[0] += 1.0
        got = p.update(idle_quiet_s=100.0)
        if got is not Gesture.NONE:
            break
    assert got in _IDLE_SET


def test_idle_gesture_respects_its_own_cooldown():
    p, t = _picker(idle_interval_s=5.0, idle_min_quiet_s=1.0, idle_cooldown_s=120.0)
    seen = []
    for _ in range(600):
        t[0] += 1.0
        g = p.update(idle_quiet_s=100.0)
        if g is not Gesture.NONE:
            seen.append((t[0], g))
    # no gesture repeats inside 120 s
    for i in range(1, len(seen)):
        for j in range(i):
            if seen[i][1] is seen[j][1]:
                assert seen[i][0] - seen[j][0] >= 120.0


def test_greeting_picks_from_greeting_set_and_cools_down():
    p, t = _picker(greet_cooldown_s=45.0)
    g1 = p.greeting()
    assert g1 in _GREETING_SET
    assert p.greeting() is Gesture.NONE          # immediate second call -> cooldown
    t[0] += 46.0
    assert p.greeting() in _GREETING_SET


def test_sniff_find_cooldown():
    p, t = _picker(explore_sniff_cooldown_s=20.0)
    assert p.sniff_find() is Gesture.SNIFF
    assert p.sniff_find() is Gesture.NONE
    t[0] += 21.0
    assert p.sniff_find() is Gesture.SNIFF


def test_excited_hop_is_hard_rate_limited():
    p, t = _picker(hop_cooldown_s=300.0)
    assert p.excited_hop() is Gesture.HOP
    t[0] += 120.0
    assert p.excited_hop() is Gesture.NONE
    t[0] += 200.0
    assert p.excited_hop() is Gesture.HOP
