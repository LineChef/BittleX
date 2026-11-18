"""Every policy walk logs how it ended and who asked it to stop (2026-11-18: seven of twelve tile-roam walks ended before the first step and nothing said why)."""
import logging

from pi_pipeline.gait.policy_walker import PolicyWalker


def test_the_walk_logs_its_end_reason_and_who_stopped_it(caplog):
    def fake_run(link, cmd, seconds, hz, *a, stop_event=None, **kw):
        stop_event.wait(5)
        return "stopped"

    w = PolicyWalker(link=object(), run_fn=fake_run)
    with caplog.at_level(logging.INFO, logger="g2.policy_walker"):
        w.walk(5)
        w.stop(rest=False)
        w._thread.join(5)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "policy walk ended: stopped after" in text and "stop asked by" in text and "test_the_walk_logs_its_end_reason_and_who_stopped_it" in text
