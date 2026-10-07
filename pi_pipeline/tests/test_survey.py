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
    assert [k for _, k, _, _ in plan] == ["skill", "skill", "skill", "shot", "diag"]                # no stop / rest step: the bow replaces the walk
    assert [p for _, k, p, _ in plan if k == "skill"] == ["kbuttUp", "ksit", "kup"]            # look down, look up, stand again
    assert [p for _, k, p, _ in plan if k == "shot"] == ["after_bow"]
    delays = [d for d, *_ in plan]
    assert delays == sorted(delays)


def test_naming_phrases_and_names():
    assert parse_naming("This is my red mug.") == "red mug"
    assert parse_naming("remember this as the blue ball") == "blue ball"
    assert parse_naming("that's a stapler") == "stapler"
    assert parse_naming("what is this") == "" and parse_naming("go ahead and look around") == "" and parse_naming("this is") == ""
    assert clean_name("A Red Mug!!") == "a red mug" and clean_name("  ") == ""
    named = naming_plan("mug", SurveyConfig())
    assert [k for _, k, _, _ in named].count("shot") == 1
    assert [p for _, k, p, _ in named if k == "skill"] == [p for _, k, p, _ in survey_plan(SurveyConfig()) if k == "skill"]            # one picture sequence for every picture
    shot_t = next(d for d, k, _, _ in named if k == "shot")
    assert [k for d, k, _, _ in named if d > shot_t] == ["speak", "diag"]                                                          # standing and settled before the picture, confirmation after


def test_driver_surveys_at_the_end_of_a_leg_then_walks_on():
    d, c = mk()
    assert d.tick(DriverInputs(arm_explore=True, frame=[])).mode is Mode.EXPLORE
    leg_done(d)
    t = d.tick(DriverInputs(frame=[]))
    assert [e.payload for e in t.effects if e.kind is EffectKind.SKILL] == ["kbuttUp"]       # the first thing is the bow itself
    assert EffectKind.STOP not in [e.kind for e in t.effects]                               # never a rest in the middle of exploring
    walking(d)                                           # from now on the explorer would keep walking, if the choreography let it
    during = run_for(d, c, 7.1)                         # the plan runs to 7.3 s: ksit, kup and the picture fall inside this window
    skills = [e.payload for e in during if e.kind is EffectKind.SKILL]
    shots = [e.payload for e in during if e.kind is EffectKind.CAPTURE]
    assert skills == ["ksit", "kup"] and shots == [("shot", "after_bow")]
    assert not any(e.kind in (EffectKind.WALK, EffectKind.STOP) for e in during)          # no walking while looking, and no rest
    after = run_for(d, c, 3.0)
    assert any(e.kind is EffectKind.WALK for e in after)                                  # and it walks on afterwards


def test_survey_does_not_repeat_inside_the_cooldown_and_is_off_by_default():
    d, c = mk()
    d.tick(DriverInputs(arm_explore=True, frame=[]))
    leg_done(d)
    d.tick(DriverInputs(frame=[]))
    walking(d)
    run_for(d, c, 11.0)
    leg_done(d)
    again = d.tick(DriverInputs(frame=[]))
    assert EffectKind.STOP not in [e.kind for e in again.effects]                                 # a leg ending inside the cooldown does not lie down either
    assert not any(e.kind is EffectKind.CAPTURE for e in run_for(d, c, 3.0)) and again.mode is Mode.EXPLORE
    off, c2 = mk(survey=False)
    off.tick(DriverInputs(arm_explore=True, frame=[]))
    leg_done(off)
    assert not any(e.kind is EffectKind.CAPTURE for e in run_for(off, c2, 12.0))


def test_a_spoken_name_takes_its_picture_like_a_survey_stop_and_confirms_aloud():
    d, c = mk()
    t = d.tick(DriverInputs(name_request="Mug", frame=[]))
    effects = t.effects + run_for(d, c, 7.3)             # bow, look up, stand, settle, picture, confirm: the plan is over at about 7.7 s
    assert EffectKind.STOP not in [e.kind for e in effects]
    assert [e.payload for e in effects if e.kind is EffectKind.SKILL] == ["kbuttUp", "ksit", "kup"]          # the same sequence as the survey (user, 2026-10-07)
    assert [e.payload for e in effects if e.kind is EffectKind.CAPTURE] == [("shot", "name:mug")]
    assert [e.payload for e in effects if e.kind is EffectKind.SPEAK] == ["Okay, I will remember the mug."]
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


def test_end_exploration_mode_ends_the_session_and_never_arms_or_halts():
    from pi_pipeline.voice.commands import match_local_command
    for phrase in ("end exploration mode", "end explore mode", "exit exploration mode", "stop exploration mode", "exploration mode off", "end exploration mode please"):
        assert match_local_command(phrase) == "end_explore", phrase
    assert match_local_command("exploration mode") == "explore" and match_local_command("that's enough") == "unexplore"          # the existing commands are unchanged
    ended, said, posts = [], [], []
    rt = types.SimpleNamespace(post=lambda **kw: posts.append(kw), halt=lambda: posts.append("HALT"), release=lambda: None)
    lst = ExploreListener(None, None, said.append, rt, lambda: [], on_stop=lambda: ended.append(1))
    assert lst.handle("end exploration mode") == "Okay, ending exploration mode."
    assert ended == [1] and posts == []                                              # the session closes; no halt, no arm, no disarm
    assert lst.handle("that's enough") == "Okay, that's enough." and posts == [{"disarm_explore": True}] and ended == [1]


def test_restart_voice_phrases_and_the_exploration_session_hands_back_to_a_fresh_voice_service():
    from pi_pipeline.voice.commands import match_local_command
    for phrase in ("restart your voice service", "reset the voice service", "restart voice", "reset your voice", "reload your voice"):
        assert match_local_command(phrase) == "restart_voice", phrase
    assert match_local_command("restart") is None and match_local_command("reset your memory") != "restart_voice"          # nothing broader than the voice service
    ended, said = [], []
    rt = types.SimpleNamespace(post=lambda **kw: None, halt=lambda: None, release=lambda: None)
    lst = ExploreListener(None, None, said.append, rt, lambda: [], on_stop=lambda: ended.append(1))
    assert lst.handle("restart your voice service") == "Okay, restarting my voice." and ended == [1]


def test_the_exploration_listener_says_when_the_wake_word_registered_but_no_speech_was_caught(caplog):
    import logging
    heard = ["", "this is the dishwasher", "blah blah"]
    said, posts = [], []
    rt = types.SimpleNamespace(post=lambda **kw: posts.append(kw), halt=lambda: None, release=lambda: None)
    holder = {}
    calls = {"n": 0}

    def wait():
        calls["n"] += 1
        if calls["n"] > 3:
            holder["lst"].stop()

    wake = types.SimpleNamespace(wait=wait)
    stt = types.SimpleNamespace(listen=lambda timeout_s=None: heard.pop(0) if heard else "")
    lst = ExploreListener(wake, stt, said.append, rt, lambda: [])
    holder["lst"] = lst
    with caplog.at_level(logging.INFO, logger="g2.behavior.explore_listener"):
        lst._run()
    text = caplog.text
    assert "nothing recognized after the wake word" in text and "naming request: 'dishwasher'" in text and "not a command I know in exploration" in text
    assert said == ["I didn't catch that.", "Okay, let me look at the dishwasher.", "I didn't understand that."]
    assert posts == [{"name_request": "dishwasher"}]


def test_the_voice_loop_says_i_am_online_when_it_is_ready_and_only_when_asked_to():
    import types as _t
    from pi_pipeline.voice.loop import VoiceLoop
    for announce, expect in ((True, ["I am online."]), (False, [])):
        said = []
        stt = _t.SimpleNamespace(listen=lambda timeout_s=None: "")
        wake = _t.SimpleNamespace(wait=lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        tts = _t.SimpleNamespace(speak=lambda x: said.append(x))
        act = _t.SimpleNamespace(perform=lambda s, **k: None, stop=lambda: None, close=lambda: None)
        cue = _t.SimpleNamespace(set=lambda s: None)
        lp = VoiceLoop(wake_word=wake, stt=stt, conversation=_t.SimpleNamespace(), tts=tts, actuator=act, cue=cue, announce_online=announce)
        lp.run_forever()
        assert said == expect, announce
