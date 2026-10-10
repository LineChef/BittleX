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


def _real_jpeg():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (16, 16), (120, 90, 60)).save(b, "JPEG")
    return b.getvalue()


def test_survey_cooldown_and_plan_order():
    s = Survey(SurveyConfig(cooldown_s=15.0), clock=lambda: 100.0)
    assert s.ready(100.0)
    s.began(100.0)
    assert not s.ready(110.0) and s.ready(115.0)
    plan = survey_plan(SurveyConfig())
    assert [k for _, k, _, _ in plan] == ["skill", "skill", "skill", "shot", "diag"]                # no stop / rest step: the bow replaces the walk
    assert [p for _, k, p, _ in plan if k == "skill"] == ["ksit", "kbuttUp", "kup"]            # look up, look down, stand again (user, 2026-10-10)
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
    assert [e.payload for e in t.effects if e.kind is EffectKind.SKILL] == ["ksit"]       # the first thing is the look up
    assert EffectKind.STOP not in [e.kind for e in t.effects]                               # never a rest in the middle of exploring
    walking(d)                                           # from now on the explorer would keep walking, if the choreography let it
    during = run_for(d, c, 5.9)                         # the plan runs to 5.6 s (1.8 + 1.8 + the 2.0 s stand settle): kbuttUp, kup and the picture fall inside this window
    skills = [e.payload for e in during if e.kind is EffectKind.SKILL]
    shots = [e.payload for e in during if e.kind is EffectKind.CAPTURE]
    assert skills == ["kbuttUp", "kup"] and shots == [("shot", "after_bow")]
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
    effects = t.effects + run_for(d, c, 8.6)             # bow, look up, stand, settle, picture, confirm: the plan is over at about 8.4 s (3.3 s stand settle)
    assert EffectKind.STOP not in [e.kind for e in effects]
    assert [e.payload for e in effects if e.kind is EffectKind.SKILL] == ["ksit", "kbuttUp", "kup"]          # the same sequence as the survey
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
    snap = Snapshot(_real_jpeg(), 240, 240, [("face", 0.91, 0.5, 0.5, 0.2, 0.2)])
    clock = types.SimpleNamespace(t=1791387600.123)
    saver = ExplorationPictureSaver(FakeSource(snap), str(tmp_path), clock=lambda: clock.t)
    p1 = saver("after_bow")
    p2 = saver("name:Red Mug")
    assert "/survey/" in p1 and p1.endswith(".jpg") and "/named/red-mug/" in p2
    meta = json.loads(open(p1[:-4] + ".json").read())
    assert meta["pose"] == "after_bow" and meta["name"] is None and meta["detections"][0]["label"] == "face" and meta["width"] == 240
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
    snap = Snapshot(_real_jpeg(), 240, 240, [])
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


def test_a_near_duplicate_is_not_saved_a_different_picture_is(tmp_path, monkeypatch):
    monkeypatch.setattr("pi_pipeline.vision.exploration_pictures._badly_exposed", lambda jpeg: False)      # these test pictures are black and white patterns: no exposure retake here
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
    for phrase in ("end exploration mode", "end explore mode", "exit exploration mode", "stop exploration mode", "exploration mode off", "end exploration mode please", "cancel exploration", "cancel exploration mode", "cancel exploration mode please", "cancel explore mode"):
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
    lst = ExploreListener(wake, stt, said.append, rt, lambda: [], settle_s=0.0)
    holder["lst"] = lst
    with caplog.at_level(logging.INFO, logger="g2.behavior.explore_listener"):
        lst._run()
    text = caplog.text
    assert "nothing recognized after the wake word" in text and "naming request: 'dishwasher'" in text and "not a command I know in exploration" in text
    assert said == ["I didn't catch that.", "Okay, let me look at the dishwasher.", "I didn't understand that."]
    assert [x for x in posts if "listen_hold" not in x] == [{"name_request": "dishwasher"}]      # (each wake word also asks him to stand still while he listens)


def test_the_voice_loop_says_i_am_online_when_it_is_ready_and_only_when_asked_to():
    import types as _t
    from pi_pipeline.voice.loop import VoiceLoop
    for announce, expect in ((True, ["G2 online."]), (False, [])):
        said = []
        stt = _t.SimpleNamespace(listen=lambda timeout_s=None: "")
        wake = _t.SimpleNamespace(wait=lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        tts = _t.SimpleNamespace(speak=lambda x: said.append(x))
        act = _t.SimpleNamespace(perform=lambda s, **k: None, stop=lambda: None, close=lambda: None)
        cue = _t.SimpleNamespace(set=lambda s: None)
        lp = VoiceLoop(wake_word=wake, stt=stt, conversation=_t.SimpleNamespace(), tts=tts, actuator=act, cue=cue, announce_online=announce)
        lp.run_forever()
        assert said == expect, announce


def test_the_wake_word_in_an_exploration_session_stands_him_still_for_the_command_window():
    from pi_pipeline.behavior.explore import Explorer
    posted = []
    class RT:
        def post(self, **kw): posted.append(kw)
    from pi_pipeline.behavior.explore_listener import ExploreListener
    import types, threading
    stt = types.SimpleNamespace(listen=lambda timeout_s=None: "cancel exploration")
    wake = types.SimpleNamespace(wait=lambda: None)
    ended = []
    lst = ExploreListener(wake, stt, lambda t: None, RT(), lambda: [], on_stop=lambda: ended.append(1), settle_s=0.0)
    wake_calls = [0]
    def wait_once():
        wake_calls[0] += 1
        if wake_calls[0] > 1:
            lst.stop()
    wake.wait = wait_once
    lst._run()
    assert {"listen_hold": True} in posted and ended == [1]


def test_listen_hold_makes_the_explorer_hold_and_the_exploration_end_words_are_in_the_tight_grammar():
    from pi_pipeline.behavior.explore import ExploreAction
    from pi_pipeline.voice.commands import grammar_phrases
    from pi_pipeline.tests.test_behavior import _explorer
    ex, p = _explorer("")
    ex.hold_for(10.0, 12.0)
    assert ex.decide([], now=11.0).action is ExploreAction.HOLD and ex.decide([], now=21.9).action is ExploreAction.HOLD
    g = grammar_phrases()
    assert "cancel exploration" in g and "gee two end exploration mode" in g


def test_first_picture_waits_and_the_pacing_comes_from_the_environment(monkeypatch):
    from pi_pipeline.behavior.survey import survey_config_from_env
    s = Survey(SurveyConfig(cooldown_s=40.0, first_delay_s=25.0), clock=lambda: 100.0)
    assert not s.ready(110.0) and s.ready(125.0)                  # nothing before 25 s of exploring
    s.began(125.0)
    assert not s.ready(150.0) and s.ready(165.0)                  # then at most one every 40 s
    assert Survey(SurveyConfig(), clock=lambda: 100.0).ready(100.0)   # the defaults still allow one at the end of the first leg
    monkeypatch.delenv("G2_SURVEY_COOLDOWN_S", raising=False)
    monkeypatch.delenv("G2_SURVEY_FIRST_S", raising=False)
    c = survey_config_from_env()
    assert (c.cooldown_s, c.first_delay_s) == (60.0, 30.0)
    monkeypatch.setenv("G2_SURVEY_COOLDOWN_S", "90")
    monkeypatch.setenv("G2_SURVEY_FIRST_S", "bad")
    c = survey_config_from_env()
    assert (c.cooldown_s, c.first_delay_s) == (90.0, 30.0)


def test_a_survey_stop_looks_up_down_then_left_and_right_with_a_throwaway_picture_each_then_settles_and_takes_the_real_one():
    from pi_pipeline.behavior.survey import SurveyConfig, survey_plan
    import math
    plan = survey_plan(SurveyConfig(looks=True))
    seq = [(k, p if k != "turn" else round(math.degrees(p))) for _, k, p, _ in plan if k in ("skill", "turn", "shot")]
    assert seq == [("skill", "ksit"), ("skill", "kbuttUp"), ("skill", "kup"),
                   ("turn", -45), ("skill", "kbalance"), ("shot", "look_left"),
                   ("turn", 90), ("skill", "kbalance"), ("shot", "look_right"),
                   ("turn", -45), ("skill", "kbalance"), ("shot", "after_bow")]
    times = [d for d, _, _, _ in plan]
    assert times == sorted(times)
    t_turn_left = next(d for d, k, p, _ in plan if k == "turn")
    t_stop_left = next(d for d, k, p, _ in plan if k == "skill" and p == "kbalance")
    assert abs((t_stop_left - t_turn_left) - (45 * 0.85 / 11.0 + 0.3)) < 1e-6          # the stop comes after the timed turn the walker will run
    assert [p for _, k, p, _ in survey_plan(SurveyConfig()) if k == "shot"] == ["after_bow"]          # the dataclass default stays one picture
    assert [p for _, k, p, _ in naming_plan("mug", SurveyConfig(looks=True)) if k == "shot"] == ["name:mug"]      # a named picture is not a look sequence


def test_the_looks_are_off_unless_the_environment_turns_them_on(monkeypatch):
    from pi_pipeline.behavior.survey import survey_config_from_env
    monkeypatch.delenv("G2_SURVEY_LOOKS", raising=False)
    assert survey_config_from_env().looks is False                       # off by default (2026-10-10)
    monkeypatch.setenv("G2_SURVEY_LOOKS", "1")
    assert survey_config_from_env().looks is True


def test_look_and_survey_pictures_do_not_feed_the_gallery_only_a_named_one_does(tmp_path):
    snap = Snapshot(_real_jpeg(), 240, 240, [])
    fed = []
    clock = types.SimpleNamespace(t=1791387600.0)
    saver = ExplorationPictureSaver(FakeSource(snap), str(tmp_path), clock=lambda: clock.t, on_saved=fed.append)
    p = saver("look_left")
    assert "/looks/" in p and fed == []                                  # never offered to the object gallery
    saver("after_bow")
    assert fed == []                                                      # a survey picture waits for the filter, your label and a promotion (user, 2026-10-10)
    p3 = saver("name:red mug")
    assert fed == [p3]                                                    # only a picture named by voice feeds the gallery


def test_a_slow_picture_does_not_make_the_steps_behind_it_fire_in_a_burst():
    from pi_pipeline.behavior.driver import Effect, _Choreo
    t = [0.0]
    ch = _Choreo(clock=lambda: t[0])
    ch.start("x", [(0.0, Effect(EffectKind.TURN, 0.5)), (1.0, Effect(EffectKind.CAPTURE, ("shot", "look_left"))), (2.0, Effect(EffectKind.TURN, 0.9)), (3.0, Effect(EffectKind.SKILL, "kbalance"))])
    t[0] = 1.0
    assert [e.kind for e in ch.pump()] == [EffectKind.TURN, EffectKind.CAPTURE]     # the picture is released alone
    t[0] = 9.0                                                            # the camera call blocked for 8 s
    assert ch.pump() == []                                               # what is left is re-timed from now, not fired at once
    t[0] = 10.0
    assert [e.kind for e in ch.pump()] == [EffectKind.TURN]
    t[0] = 11.0
    assert [e.kind for e in ch.pump()] == [EffectKind.SKILL]


def test_a_look_picture_is_quick_no_warm_up_no_retake_and_a_short_stillness_wait(tmp_path):
    snap = Snapshot(_real_jpeg(), 240, 240, [])
    waits, takes = [], []

    class Src(FakeSource):
        def snapshot(self, settle=None):
            takes.append(settle)
            return self.snap
    saver = ExplorationPictureSaver(Src(snap), str(tmp_path), wait_still=lambda t=6.0: waits.append(t))
    saver("look_left")
    saver("after_bow")
    assert waits == [2.0, 6.0] or waits == [2.0, waits[1]] and waits[0] == 2.0       # a look waits at most 2 s for stillness; the real picture keeps its wait
    assert takes[0] == 0                                                              # no camera warm-up for a throwaway look


def test_a_survey_stop_runs_the_firmware_check_skill_between_the_bow_and_the_stand_when_asked(monkeypatch):
    from pi_pipeline.behavior.survey import SurveyConfig, survey_config_from_env, survey_plan
    plan = survey_plan(SurveyConfig(check=True))
    assert [p for _, k, p, _ in plan if k == "skill"] == ["ksit", "kbuttUp", "kup", "kck", "kup"]       # up, down, stand, check, stand again
    t_ck = next(d for d, k, p, _ in plan if p == "kck")
    t_up = [d for d, k, p, _ in plan if p == "kup"][-1]
    assert abs((t_up - t_ck) - 3.0) < 1e-6                                          # the check skill gets 3 s to finish
    assert [p for _, k, p, _ in plan if k == "shot"] == ["after_bow"]               # one picture, standing, after the settle
    assert [p for _, k, p, _ in survey_plan(SurveyConfig()) if k == "skill"] == ["ksit", "kbuttUp", "kup"]
    monkeypatch.delenv("G2_SURVEY_CHECK", raising=False)
    assert survey_config_from_env().check is True
    monkeypatch.setenv("G2_SURVEY_CHECK", "0")
    assert survey_config_from_env().check is False
