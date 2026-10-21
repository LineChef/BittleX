"""The shared gait switch: spoken commands, the shared state file, the blend, policies that do not support a gait, and reaching it from the voice loop's command table."""
import json

from pi_pipeline.gait import gait_mode as gm
from pi_pipeline.voice.commands import match_local_command


def test_the_spoken_phrases_pick_the_right_gait_and_off_phrases_win():
    for t in ("hi step", "Hi step!", "high step", "G2, hi step", "hi step mode", "step mode"):
        assert gm.parse_gait_command(t) == "hi_step", t
    for t in ("walk normally", "Walk normally.", "normal walk", "hi step off", "high step off", "step mode off", "walk mode", "Walk mode!", "normal mode"):
        assert gm.parse_gait_command(t) == "normal", t
    for t in ("walk forward", "walk for ten seconds", "what is a high step", "I want you to take a long walk normally around the house tonight", "hello"):
        assert gm.parse_gait_command(t) is None, t


def test_the_command_table_returns_gait_before_walk():
    assert match_local_command("hi step") == "gait" and match_local_command("walk normally") == "gait"
    assert match_local_command("walk for ten seconds") == "walk" and match_local_command("walk forward") == "walk"


def test_state_is_shared_through_the_file_and_the_blend_runs_over_a_cycle(tmp_path):
    f = str(tmp_path / "mode.json")
    assert gm.current(f) == "normal" and gm.blend(f)[2] == 1.0
    gm.set_mode("hi_step", f, now=100.0)
    assert gm.current(f) == "hi_step"
    frm, to, a = gm.blend(f, now=100.0 + gm.BLEND_S / 2)
    assert (frm, to) == ("normal", "hi_step") and 0.45 < a < 0.55
    assert gm.blend(f, now=100.0 + 5 * gm.BLEND_S)[2] == 1.0
    gm.set_mode("normal", f, now=200.0)
    assert gm.blend(f, now=200.1)[:2] == ("hi_step", "normal")
    (tmp_path / "mode.json").write_text("not json")
    assert gm.current(f) == "normal"                                     # a damaged file means the normal gait, never a crash


def test_a_policy_without_the_mode_plays_the_scripted_gait_and_says_so(tmp_path):
    f = str(tmp_path / "mode.json")
    onnx = tmp_path / "p.onnx"
    (tmp_path / "p.onnx.json").write_text(json.dumps({"residual_scale_deg": 30.0}))
    gait, said = gm.request("hi step", str(onnx), f)
    assert gait == "hi_step" and "scripted walk" in said and "experimental" in said and gm.current(f) == "hi_step"
    assert gm.request("walk normally", str(onnx), f) == ("normal", "Walking normally.")      # the normal gait is always supported
    (tmp_path / "p.onnx.json").write_text(json.dumps({"modes": ["normal", "hi_step"]}))
    gait, said = gm.request("high step", str(onnx), f)
    assert gait == "hi_step" and said == "Hi step on." and gm.current(f) == "hi_step"      # a policy that knows it: no caveat
    assert gm.request("walk normally", str(onnx), f) == ("normal", "Walking normally.")


def test_the_walker_plays_the_scripted_base_in_hi_step_and_the_policy_otherwise(tmp_path, monkeypatch):
    import time
    from pi_pipeline.gait.policy_walker import PolicyWalker
    f = str(tmp_path / "mode.json")
    monkeypatch.setattr(gm, "STATE_PATH", f)
    calls = []

    def policy_run(lk, cmd, seconds, hz, fmt, dis, **kw):
        calls.append("policy")
        return "complete"

    def scripted(lk, cycles, hz, **kw):
        calls.append(("scripted", cycles, kw["ref_name"], kw["ramp_cycles"]))
        return "complete"

    def go():
        w = PolicyWalker(object(), run_fn=policy_run, foot_hold=None, scripted_fn=scripted)
        w.walk(5)
        for _ in range(100):
            if not w.busy:
                break
            time.sleep(0.01)
    go()
    gm.set_mode("hi_step", f)
    go()
    gm.set_mode("normal", f)
    go()
    assert calls == ["policy", ("scripted", 4, "hsF", 1.0), "policy"]


def test_openloop_plays_another_reference_stops_on_request_and_ends_standing_when_asked(tmp_path):
    import threading
    from pi_pipeline.gait import run_gait

    class Lk:
        def __init__(self):
            self.sent = []

        def send(self, cmd, read_reply=False, settle=0.0):
            self.sent.append(cmd)

        def poll_imu(self):
            return []

    class Stop(threading.Event):
        rest = False
        end_pose = "balance"
    ev, lk = Stop(), Lk()
    n = [0]

    def sleep(s):
        n[0] += 1
        if n[0] > 30:
            ev.set()
    reason = run_gait.openloop(lk, 3, 80, ramp_cycles=1.0, send_every=3, ref_name="hsF", stop_event=ev, sleep=sleep, fall_abort_deg=0)
    assert reason == "stopped" and "kbalance" in lk.sent and "d" not in lk.sent[-3:]


def test_the_double_beep_is_two_short_notes_and_speaker_sounds_are_off_in_tests(monkeypatch):
    from pi_pipeline.voice import prompt_tones as pt
    from pi_pipeline.voice.cues import LOW_CUES, SpeakerCue
    pcm = pt.render_double()
    assert 0.2 < pcm.size / 48000 < 0.4
    assert LOW_CUES["gait_switch"] == [(10, 8), (10, 8)]
    played = []
    SpeakerCue(player=lambda: played.append(1), stages=("gait_switch",)).set("gait_switch")
    assert played == [1]
    monkeypatch.setenv("G2_SPEAKER_SOUNDS", "0")
    assert pt.speaker_enabled() is False                      # conftest sets this for every test: no horn from the Mac
    monkeypatch.setenv("G2_SPEAKER_SOUNDS", "1")
    assert pt.speaker_enabled() is True


def test_switch_to_phrases_for_both_gaits():
    from pi_pipeline.gait.gait_mode import parse_gait_command
    for t in ("switched to a high step", "switch to a high step", "i step", "switch die step", "eye step", "switch to high step", "switch to hi step", "switch to highstep", "highstep", "switch to high step mode", "please switch to high step"):
        assert parse_gait_command(t) == "hi_step", t
    for t in ("switch to normal", "switch to walk mode", "switch to normal walking"):
        assert parse_gait_command(t) == "normal", t
    from pi_pipeline.voice.commands import match_local_command
    assert match_local_command("gee two switch to highstep") == "gait"


def test_compound_gait_then_request_and_the_claude_hint(tmp_path, monkeypatch):
    from pi_pipeline.gait import gait_mode as g
    assert g.split_compound("switch to high step and walk forward") == ("hi_step", "walk forward")
    assert g.split_compound("hi step and then walk forward") == ("hi_step", "walk forward")
    assert g.split_compound("walk forward and sit") is None and g.split_compound("tell me a joke") is None
    monkeypatch.setattr(g, "current", lambda: "hi_step")
    assert "HI STEP" in g.claude_hint() and "trot" in g.claude_hint()


def test_no_gait_is_ever_refused_for_a_policy_that_lacks_it(tmp_path, monkeypatch):
    f = str(tmp_path / "mode.json")
    onnx = tmp_path / "p.onnx"
    (tmp_path / "p.onnx.json").write_text(json.dumps({"residual_scale_deg": 30.0}))
    monkeypatch.setitem(gm.GAITS, "crawl", gm.Gait("crawl", ("crawl mode",), "Crawling.", "wkF"))      # a new gait with no special flags
    monkeypatch.setattr(gm, "parse_gait_command", lambda text: "crawl")
    gait, said = gm.request("crawl mode", str(onnx), f)
    assert gait == "crawl" and gm.current(f) == "crawl" and "Crawling." in said and "experimental" in said


def test_carpet_mode_and_the_default_gait_phrases():
    for t in ("carpet mode", "G2, carpet mode", "Carpet mode!", "switch to carpet mode", "carpet walk"):
        assert gm.parse_gait_command(t) == "carpet", t
    for t in ("switch to default gait", "G2, switch to default gait", "switch to the default gait", "default gait", "carpet mode off"):
        assert gm.parse_gait_command(t) == "normal", t
    for t in ("we're on carpet", "the floor is carpet", "carpet"):                 # floor answers, not gait switches
        assert gm.parse_gait_command(t) is None, t
    assert match_local_command("G2, carpet mode") == "gait" and match_local_command("switch to default gait") == "gait"


def test_carpet_mode_is_petois_firmware_gait_whatever_the_policy(tmp_path):
    f = str(tmp_path / "mode.json")
    v7 = tmp_path / "v7.onnx"
    (tmp_path / "v7.onnx.json").write_text(json.dumps({"residual_scale_deg": 30.0}))
    assert gm.GAITS["carpet"].skill == "kcarpetF" and gm.GAITS["hi_step"].skill is None
    assert gm.request("carpet mode", str(v7), f) == ("carpet", "Carpet mode on.") and gm.current(f) == "carpet"       # no caveat: it needs no policy
    assert not gm.uses_scripted(str(v7), "carpet") and gm.uses_scripted(str(v7), "hi_step")


def _fake_time():
    t = [0.0]
    return (lambda: t[0]), (lambda s: t.__setitem__(0, t[0] + max(float(s), 0.01)))


def test_the_walker_plays_the_firmware_carpet_skill_in_carpet_mode(tmp_path, monkeypatch):
    import time
    from pi_pipeline.gait import fw_skill_log
    from pi_pipeline.gait.policy_walker import PolicyWalker
    f = str(tmp_path / "mode.json")
    monkeypatch.setattr(gm, "STATE_PATH", f)
    gm.set_mode("carpet", f)
    sent = []

    class Link:
        def send(self, cmd, read_reply=False, settle=0.0):
            sent.append(cmd)

        def poll_imu(self):
            return []

    real, (clock, sleep) = fw_skill_log.walk_skill, _fake_time()
    monkeypatch.setattr(fw_skill_log, "walk_skill", lambda lk, tok, secs, ev: real(lk, tok, secs, ev, sleep=sleep, clock=clock))
    calls = []
    w = PolicyWalker(Link(), run_fn=lambda *a, **k: calls.append("policy") or "complete", foot_hold=None)
    w.walk(2.0)
    for _ in range(300):
        if not w.busy:
            break
        time.sleep(0.01)
    assert not calls                                              # the learned policy never ran
    assert sent[:3] == ["gB", "kbalance", "kcarpetF"] and sent[-3:] == ["kbalance", "gb", "d"], sent


def test_walk_skill_ends_in_a_balanced_stand_when_asked_not_to_rest_and_stops_on_request():
    import threading
    from pi_pipeline.gait.fw_skill_log import walk_skill
    clock, sleep = _fake_time()
    sent = []

    class Link:
        def send(self, cmd, read_reply=False, settle=0.0):
            sent.append(cmd)

        def poll_imu(self):
            return []

    stop = threading.Event()
    stop.rest = False                                             # exploration: leave him standing
    assert walk_skill(Link(), "kcarpetF", 2.0, stop, sleep=sleep, clock=clock) == "complete"
    assert sent[-2:] == ["kbalance", "gb"]
    assert "d" not in sent
    sent.clear()
    stop.set()                                                    # a stop before the walk starts: no gait token at all
    assert walk_skill(Link(), "kcarpetF", 2.0, stop, sleep=sleep, clock=clock) == "stopped" and "kcarpetF" not in sent


def test_the_floor_label_switches_carpet_mode_in_and_out(tmp_path):
    f = str(tmp_path / "mode.json")
    assert gm.floor_note("carpet", f) == " Carpet mode on." and gm.current(f) == "carpet"
    assert gm.floor_note("carpet", f) == ""                                         # already on: nothing to add
    assert gm.floor_note("hardwood", f) == " Back to my default gait." and gm.current(f) == "normal"
    gm.set_mode("hi_step", f)
    assert gm.floor_note("tile", f) == "" and gm.current(f) == "hi_step"           # a gait the person chose is left alone


def test_carpet_mode_loads_the_carpet_policy_file_and_the_default_gait_the_deployed_one(tmp_path, monkeypatch):
    from pi_pipeline.gait import residual_policy as rp
    monkeypatch.setattr(rp, "default_policy_path", lambda: "/pi/gait/Release_CandidateV7_ppo.onnx")
    monkeypatch.setattr(rp, "carpet_policy_path", lambda: None)
    assert rp.policy_for_gait("carpet") == "/pi/gait/Release_CandidateV7_ppo.onnx"         # no carpet policy yet: the default
    monkeypatch.setattr(rp, "carpet_policy_path", lambda: "/pi/gait/" + rp.CARPET_POLICY)
    assert rp.policy_for_gait("carpet") == "/pi/gait/" + rp.CARPET_POLICY
    assert rp.policy_for_gait("normal") == rp.policy_for_gait("hi_step") == "/pi/gait/Release_CandidateV7_ppo.onnx"
