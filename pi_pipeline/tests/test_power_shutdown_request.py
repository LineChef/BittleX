"""The wrap-up's power-down request (power/shutdown_request.py): the voice service takes the file and hands "shut down" to the voice loop, the path that says Powering down."""
import threading
import time

from pi_pipeline.power import shutdown_request as sr


def test_a_request_is_taken_and_handed_to_the_voice_loop_as_shut_down(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_SHUTDOWN_REQUEST", str(tmp_path / "req"))
    got, stop = [], threading.Event()
    t = sr.watch(got.append, interval=0.05, stop=stop)
    assert not sr.pending()
    sr.request()
    assert sr.pending()
    for _ in range(100):
        if got:
            break
        time.sleep(0.05)
    stop.set()
    t.join(2)
    assert got == ["shut down"] and not sr.pending()                                                  # taken: the file is gone, which is how the script knows


def test_the_phrase_is_a_clear_shutdown_the_voice_loop_powers_off_on():
    from pi_pipeline.voice.commands import is_clear_shutdown
    assert is_clear_shutdown(sr.PHRASE)
