"""Survey stops and voice naming (behavior/survey.py), the driver's choreography for them, the camera binding and the picture saver. Fakes only."""
import json
import random
import types

from pi_pipeline.behavior import BehaviorDriver, DriverInputs, EffectKind, Mode
from pi_pipeline.behavior.bindings import DriverBindings
from pi_pipeline.behavior.driver import Effect
from pi_pipeline.behavior.explore import ExploreAction, ExploreDecision
from pi_pipeline.behavior.explore_listener import ExploreListener
from pi_pipeline.behavior.survey import Survey, SurveyConfig, clean_name, naming_plan, parse_naming, survey_plan
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.exploration_pictures import ExplorationPictureSaver
from pi_pipeline.vision.snapshot import Snapshot


class Clk:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def adv(self, dt):
        self.t += dt


def mk(survey=True):
    c = Clk()
    d = BehaviorDriver(BehaviorParams(), clock=c, rng=random.Random(0))
    c.adv(11)                                       # past the driver's settle grace, as the driver tests do
    if survey:
        d.enable_survey()
    return d, c


def leg_done(d):
    d.explorer.decide = lambda frame, now: ExploreDecision(ExploreAction.HOLD, reason="leg done")


def walking(d):
    d.explorer.decide = lambda frame, now: ExploreDecision(ExploreAction.WANDER, reason="on leg")


def run_for(d, c, seconds, step=0.25):
    """Tick for `seconds`; returns every effect produced, in order."""
    out = []
    end = c.t + seconds
    while c.t < end:
        out += d.tick(DriverInputs(frame=[])).effects
        c.adv(step)
    return out


def test_survey_cooldown_and_plan_order():
    s = Survey(SurveyConfig(cooldown_s=15.0), clock=lambda: 100.0)
    assert s.ready(100.0)
    s.began(100.0)
    assert not s.ready(110.0) and s.ready(115.0)
    plan = survey_plan(SurveyConfig())
    assert [k for _, k, _, _ in plan] == ["stop", "skill", "skill", "shot", "skill", "shot", "skill", "diag"]
    assert [p for _, k, p, _ in plan if k == "skill"] == ["kup", "kbuttUp", "ksit", "kup"]            # stand, look down, look up, stand
    assert [p for _, k, p, _ in plan if k == "shot"] == ["look_down", "look_up"]
    delays = [d for d, *_ in plan]
    assert delays == sorted(delays)


def test_naming_phrases_and_names():
    assert parse_naming("This is my red mug.") == "red mug"
    assert parse_naming("remember this as the blue ball") == "blue ball"
    assert parse_naming("that's a stapler") == "stapler"
    assert parse_naming("what is this") == "" and parse_naming("go ahead and look around") == "" and parse_naming("this is") == ""
    assert clean_name("A Red Mug!!") == "a red mug" and clean_name("  ") == ""
    assert [k for _, k, _, _ in naming_plan("mug", SurveyConfig())].count("shot") == 1


def test_driver_surveys_at_the_end_of_a_leg_then_walks_on():
    d, c = mk()
    assert d.tick(DriverInputs(arm_explore=True, frame=[])).mode is Mode.EXPLORE
    leg_done(d)
    t = d.tick(DriverInputs(frame=[]))
    assert EffectKind.STOP in [e.kind for e in t.effects]
    walking(d)                                           # from now on the explorer would keep walking, if the choreography let it
    effects = run_for(d, c, 12.0)
    skills = [e.payload for e in effects if e.kind is EffectKind.SKILL]
    shots = [e.payload for e in effects if e.kind is EffectKind.CAPTURE]
    assert skills == ["kup", "kbuttUp", "ksit", "kup"] and shots == [("shot", "look_down"), ("shot", "look_up")]
    assert not any(e.kind is EffectKind.WALK for e in effects[:len(effects) // 2])                  # no walking while it is looking
    assert any(e.kind is EffectKind.WALK for e in effects)                                         # and it walks on afterwards


def test_survey_does_not_repeat_inside_the_cooldown_and_is_off_by_default():
    d, c = mk()
    d.tick(DriverInputs(arm_explore=True, frame=[]))
    leg_done(d)
    d.tick(DriverInputs(frame=[]))
    walking(d)
    run_for(d, c, 11.0)
    leg_done(d)
    again = d.tick(DriverInputs(frame=[]))
    assert not any(e.kind is EffectKind.CAPTURE for e in run_for(d, c, 3.0)) and again.mode is Mode.EXPLORE
    off, c2 = mk(survey=False)
    off.tick(DriverInputs(arm_explore=True, frame=[]))
    leg_done(off)
    assert not any(e.kind is EffectKind.CAPTURE for e in run_for(off, c2, 12.0))


def test_a_spoken_name_makes_one_look_down_picture_and_confirms_aloud():
    d, c = mk()
    t = d.tick(DriverInputs(name_request="Mug", frame=[]))
    assert EffectKind.STOP in [e.kind for e in t.effects]
    effects = t.effects + run_for(d, c, 12.0)
    assert [e.payload for e in effects if e.kind is EffectKind.CAPTURE] == [("shot", "name:mug")]
    assert [e.payload for e in effects if e.kind is EffectKind.SPEAK] == ["Okay, I will remember the mug."]
    assert [e.payload for e in effects if e.kind is EffectKind.SKILL][:2] == ["kup", "kbuttUp"]
    off, c2 = mk(survey=False)
    assert not any(e.kind is EffectKind.CAPTURE for e in off.tick(DriverInputs(name_request="mug", frame=[])).effects)       # needs enable_survey


def test_the_camera_binding_takes_one_picture_per_shot_effect():
    shots = []
    cam = types.SimpleNamespace(snapshot=lambda kind: shots.append(kind))
    b = DriverBindings(camera=cam)
    assert b.dispatch([Effect(EffectKind.CAPTURE, ("shot", "look_up"))]) == ["snapshot:look_up"] and shots == ["look_up"]
    assert DriverBindings().dispatch([Effect(EffectKind.CAPTURE, ("shot", "look_up"))]) == ["drop:snapshot"]            # no camera: dropped, no crash


class FakeSource:
    def __init__(self, snap):
        self.snap = snap

    def snapshot(self):
        return self.snap


def test_saver_writes_the_picture_and_its_sidecar_in_the_right_folder(tmp_path):
    snap = Snapshot(b"\xff\xd8\xff\xe0fake\xff\xd9", 240, 240, [("face", 0.91, 0.5, 0.5, 0.2, 0.2)])
    clock = types.SimpleNamespace(t=1791387600.123)
    saver = ExplorationPictureSaver(FakeSource(snap), str(tmp_path), clock=lambda: clock.t)
    p1 = saver("look_down")
    p2 = saver("name:Red Mug")
    assert "/survey/" in p1 and p1.endswith(".jpg") and "/named/red-mug/" in p2
    meta = json.loads(open(p1[:-4] + ".json").read())
    assert meta["pose"] == "look_down" and meta["name"] is None and meta["detections"][0]["label"] == "face" and meta["width"] == 240
    assert json.loads(open(p2[:-4] + ".json").read())["name"] == "Red Mug" and saver.count == 2
    assert ExplorationPictureSaver(FakeSource(None), str(tmp_path))("look_up") is None                                 # no picture: nothing written


def test_listener_posts_a_naming_request_and_answers():
    posts, said = [], []
    rt = types.SimpleNamespace(post=lambda **kw: posts.append(kw), halt=lambda: None, release=lambda: None)
    lst = ExploreListener(None, None, said.append, rt, lambda: [])
    assert lst.handle("this is my red mug") == "Okay, let me look at the red mug."
    assert posts == [{"name_request": "red mug"}] and said
    assert lst.handle("what is this") is None or posts == [{"name_request": "red mug"}]


def test_pictures_can_be_trashed_restored_and_only_emptying_the_trash_deletes(tmp_path):
    from pi_pipeline.vision import exploration_pictures as EP
    snap = Snapshot(b"\xff\xd8\xff\xe0fake\xff\xd9", 240, 240, [])
    saver = ExplorationPictureSaver(FakeSource(snap), str(tmp_path / "pics"), clock=lambda: 1791387600.5)
    p = saver("name:Mug")
    rel = EP.list_pictures(str(tmp_path / "pics"))[0]["path"]
    assert rel.startswith("named/mug/") and EP.list_pictures(str(tmp_path / "pics"))[0]["name"] == "Mug"
    assert EP.trash_pictures(str(tmp_path / "pics"), [rel]) == [rel]
    assert EP.list_pictures(str(tmp_path / "pics")) == [] and len(EP.list_trash(str(tmp_path / "pics"))) == 1
    assert not (tmp_path / "pics" / rel).exists() and (tmp_path / "pics_trash" / rel).exists() and (tmp_path / "pics_trash" / rel.replace(".jpg", ".json")).exists()
    assert EP.restore_pictures(str(tmp_path / "pics"), [rel]) == [rel] and (tmp_path / "pics" / rel).exists() and (tmp_path / "pics" / rel.replace(".jpg", ".json")).exists()
    EP.trash_pictures(str(tmp_path / "pics"), [rel])
    assert EP.empty_trash(str(tmp_path / "pics")) == 1 and EP.list_trash(str(tmp_path / "pics")) == []
    import pytest
    with pytest.raises(ValueError):
        EP.trash_pictures(str(tmp_path / "pics"), ["../../etc/passwd.jpg"])               # never outside the picture folder


def test_a_near_duplicate_is_not_saved_a_different_picture_is(tmp_path):
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    import io
    from PIL import Image
    def jpeg(pattern):
        im = Image.new("L", (64, 64))
        px = im.load()
        for x in range(64):
            for y in range(64):
                px[x, y] = 255 if pattern(x, y) else 0
        buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG"); return buf.getvalue()
    left, top = jpeg(lambda x, y: x < 32), jpeg(lambda x, y: y < 32)
    seq = iter([Snapshot(left, 64, 64, []), Snapshot(left, 64, 64, []), Snapshot(top, 64, 64, [])])
    class Src:
        def snapshot(self): return next(seq)
    t = [1791387600.0]
    def clock():
        t[0] += 1.0
        return t[0]
    saver = ExplorationPictureSaver(Src(), str(tmp_path), clock=clock)
    assert saver("look_down") is not None
    assert saver("look_down") is None and saver.duplicates == 1                   # the same view again: not written
    assert saver("look_down") is not None and saver.count == 2                      # a different view: kept
