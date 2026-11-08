"""Make room before a big model loads (util/mem_budget.py)."""
from pi_pipeline.util import mem_budget as mb


def _clean():
    for n in list(mb._holders):
        mb.unregister(n)


def test_an_idle_other_model_is_released_when_the_load_would_not_fit():
    _clean()
    gone = []
    mb.register("embedder", lambda: gone.append("embedder") or True, lambda s: True)
    free = iter([95.0, 220.0])
    assert mb.make_room(90.0, keep="speech", free=lambda: next(free)) == ["embedder"] and gone == ["embedder"]
    _clean()


def test_a_model_in_use_is_never_released_and_nothing_is_released_when_it_fits():
    _clean()
    gone = []
    mb.register("embedder", lambda: gone.append(1) or True, lambda s: False)          # used a moment ago
    assert mb.make_room(90.0, keep="speech", free=lambda: 95.0) == [] and gone == []
    mb.register("embedder", lambda: gone.append(1) or True, lambda s: True)
    assert mb.make_room(90.0, keep="speech", free=lambda: 400.0) == [] and gone == []   # plenty of room
    assert mb.make_room(90.0, keep="embedder", free=lambda: 95.0) == []                # never releases itself
    _clean()


def test_no_reading_or_a_failing_holder_never_raises():
    _clean()
    mb.register("a", lambda: (_ for _ in ()).throw(RuntimeError("x")), lambda s: True)
    assert mb.make_room(90.0, keep="b", free=lambda: None) == []
    assert mb.make_room(90.0, keep="b", free=lambda: 50.0) == []
    _clean()
