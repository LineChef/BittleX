from pi_pipeline.util.disk import DiskWatch, warning_text


def test_no_warning_below_the_threshold_and_a_clear_one_above():
    assert warning_text(84.9, 4.0, 85) is None
    msg = warning_text(87.2, 3.1, 85)
    assert "87%" in msg and "3.1 GB" in msg and "g2_logs" in msg


class _Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_warns_once_then_repeats_only_after_the_interval_and_rearms_when_it_drops():
    clock, level = _Clock(), {"pct": 86.0}
    w = DiskWatch(85, repeat_s=100, status=lambda _p: (level["pct"], 3.0), clock=clock)
    assert w.tick() is not None            # first crossing
    clock.t = 50
    assert w.tick() is None                # still above, too soon to repeat
    clock.t = 150
    assert w.tick() is not None            # reminder after the repeat interval
    level["pct"] = 70.0
    assert w.tick() is None                # back below: re-armed
    level["pct"] = 90.0
    clock.t = 160
    assert w.tick() is not None            # crosses again: warns straight away
