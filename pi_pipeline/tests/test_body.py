"""personality/body.py: a low battery, a recent fall and the last exploration colour G2's mood, and every note expires."""
from pi_pipeline.personality import body


def test_notes_round_trip_and_expire(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_BODY_STATE", str(tmp_path / "b.json"))
    assert body.hint() == "" and body.idle_mult() == 1.0
    body.note_battery("LOW", now=1000.0)
    assert "battery is low" in body.hint(now=1001.0) and body.idle_mult(now=1001.0) == 0.75
    assert body.hint(now=1000.0 + body.BATTERY_S + 1) == ""                     # an old alert no longer colours him
    body.note_battery("critical", now=2000.0)
    assert "critically low" in body.hint(now=2001.0) and body.idle_mult(now=2001.0) == 0.6
    body.note_fall(now=2000.0)
    h = body.hint(now=2001.0)
    assert "fell over" in h and "critically low" in h
    assert "fell over" not in body.hint(now=2000.0 + body.FALL_S + 1)


def test_the_last_exploration_shapes_the_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_BODY_STATE", str(tmp_path / "b.json"))
    body.note_exploration({"seen": {"chair": 2, "dog": 1}, "events": {}, "stops": 4}, now=100.0)
    assert "went well" in body.hint(now=200.0)
    body.note_exploration({"seen": {}, "events": {"wall.hit": 4}, "stops": 1}, now=300.0)
    assert "bumpy" in body.hint(now=400.0) and body.idle_mult(now=400.0) == 1.0


def test_off_and_a_broken_file_are_harmless(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_BODY_STATE", "off")
    body.note_fall()
    assert body.hint() == ""
    p = tmp_path / "b.json"
    p.write_text("not json")
    monkeypatch.setenv("G2_BODY_STATE", str(p))
    assert body.hint() == "" and body.idle_mult() == 1.0
    body.note_fall()
    assert "fell over" in body.hint()


def test_the_driver_settles_sooner_when_the_body_says_so():
    import random
    from pi_pipeline.behavior import BehaviorDriver, DriverInputs
    from pi_pipeline.personality.traits import BehaviorParams
    d = BehaviorDriver(BehaviorParams(), clock=lambda: 1000.0, rng=random.Random(0))
    d.tick(DriverInputs(frame=[]))
    base = d.idle.cfg.sit_after_s
    d.tick(DriverInputs(frame=[], body_idle_mult=0.75))
    assert abs(d.idle.cfg.sit_after_s - base * 0.75) < 1e-9
