import types

from pi_pipeline.voice.__main__ import power_off_pi
from pi_pipeline.voice.commands import is_clear_shutdown, match_local_command
from pi_pipeline.voice.loop import VoiceLoop


def test_only_a_short_clear_command_counts_as_a_power_off():
    for text in ("shut down", "G2 shut down", "please shut yourself down", "power off", "shut down now", "time to shut down"):
        assert match_local_command(text) == "shutdown" and is_clear_shutdown(text), text
    for text in ("shut down but not the whole computer please thanks", "shut down?", "shut down if you don't mind", "why did you shut down",
                 "don't shut down", "", "shut down because it is late tonight"):
        assert not is_clear_shutdown(text), text


def make(script, **kw):
    heard, said, calls, events = list(script), [], [], []
    stt = types.SimpleNamespace(listen=lambda timeout_s=None: heard.pop(0) if heard else "")
    lp = VoiceLoop(wake_word=types.SimpleNamespace(wait=lambda: None), stt=stt,
                   conversation=types.SimpleNamespace(send=lambda *a, **k: None, set_mood_hint=lambda h: None, set_narration_hint=lambda h: None),
                   tts=types.SimpleNamespace(speak=said.append), actuator=types.SimpleNamespace(perform=lambda *a, **k: None, stop=lambda: None),
                   cue=types.SimpleNamespace(set=lambda s: None), follow_up_s=0.0, on_event=lambda **e: events.append(e),
                   shutdown_confirm_s=6.0, **kw)
    return lp, said, calls, events


def test_a_clear_shut_down_lies_down_waits_for_a_cancel_then_powers_off():
    lp, said, _, events = make(["shut down", ""], on_poweroff=lambda: said.append("<POWER OFF>"))
    lp._one_turn()
    assert {"shutdown": True} in events
    assert any("switching the computer off" in s and "cancel" in s for s in said)
    assert said[-2:] == ["Goodbye. Please flip my battery switch off.", "<POWER OFF>"]      # the goodbye is spoken BEFORE the power goes


def test_saying_cancel_in_the_window_keeps_the_pi_on():
    lp, said, _, _ = make(["shut down", "cancel"], on_poweroff=lambda: said.append("<POWER OFF>"))
    lp._one_turn()
    assert "<POWER OFF>" not in said and "Okay, staying on." in said


def test_other_cancel_words_also_work_and_a_stray_word_does_not():
    for reply, powered in (("wait", False), ("no", False), ("never mind", False), ("hello there", True)):
        lp, said, _, _ = make(["shut down", reply], on_poweroff=lambda: said.append("<POWER OFF>"))
        lp._one_turn()
        assert ("<POWER OFF>" in said) is powered, reply


def test_without_a_power_off_handler_or_for_an_unclear_phrase_it_is_the_old_lie_down_and_go_dormant():
    lp, said, _, events = make(["shut down"])                                        # no handler (e.g. text mode on a laptop)
    lp._one_turn()
    assert said == ["Okay, lying down and shutting down. Wake me when you need me."] and {"shutdown": True} in events
    lp2, said2, _, _ = make(["shut down but not the whole computer please thanks"], on_poweroff=lambda: said2.append("<POWER OFF>"))
    lp2._one_turn()
    assert "<POWER OFF>" not in said2 and said2[0].startswith("Okay, lying down and shutting down")


def test_a_failing_power_off_is_said_out_loud_not_swallowed():
    def boom():
        raise RuntimeError("sudo needs a password")
    lp, said, _, _ = make(["shut down", ""], on_poweroff=boom)
    lp._one_turn()
    assert said[-1] == "I lay down, but I couldn't switch the computer off."


def test_power_off_pi_lies_g2_down_then_runs_the_shutdown_only_on_linux():
    stopped, ran = [], []
    act = types.SimpleNamespace(stop=lambda: stopped.append(1))
    power_off_pi(act, run=lambda *a, **k: ran.append((a, k)), platform="linux", sleep=lambda s: None)
    assert stopped == [1] and ran[0][0][0] == ["sudo", "-n", "shutdown", "-h", "now"] and ran[0][1]["check"] is True
    ran.clear()
    power_off_pi(act, run=lambda *a, **k: ran.append(1), platform="darwin", sleep=lambda s: None)
    assert ran == []                                                                  # a laptop is never shut down
    bad = types.SimpleNamespace(stop=lambda: (_ for _ in ()).throw(RuntimeError("serial gone")))
    power_off_pi(bad, run=lambda *a, **k: ran.append(1), platform="linux", sleep=lambda s: None)
    assert ran == [1]                                                                 # a failing stop() does not prevent the shutdown


def test_gee_to_wake_word_run_into_command():
    from pi_pipeline.voice.commands import match_local_command, is_clear_shutdown
    assert match_local_command("gee to shut down") == "shutdown"
    assert is_clear_shutdown("gee to shut down")


def test_misheard_wake_word_variants_before_shutdown():
    from pi_pipeline.voice.commands import match_local_command
    for t in ("she to shut down", "jee too shut down", "hey gee to shut down"):
        assert match_local_command(t) == "shutdown"
