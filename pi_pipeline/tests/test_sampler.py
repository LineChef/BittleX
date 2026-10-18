"""diag/sampler.py: the sampling profiler that measures which threads run Python code during a session."""
import threading
import time

from pi_pipeline.diag.sampler import Sampler


def test_a_busy_thread_is_counted_as_running_and_a_sleeping_one_as_waiting(tmp_path):
    stop = threading.Event()

    def busy():
        while not stop.is_set():
            sum(i * i for i in range(2000))

    def idle():
        while not stop.is_set():
            stop.wait(0.01)                                       # a Python-level wait the fallback can see (the Pi uses CPU time instead)

    ths = [threading.Thread(target=busy, name="busy", daemon=True), threading.Thread(target=idle, name="idle", daemon=True)]
    for t in ths:
        t.start()
    s = Sampler(interval_s=0.005, cpu_fn=None)
    for _ in range(60):
        s.sample_once()
        time.sleep(0.002)
    stop.set()
    for t in ths:
        t.join(1.0)
    assert s.samples["busy"] >= 50 and s.running["busy"] / s.samples["busy"] > 0.8
    assert s.running["idle"] / max(1, s.samples["idle"]) < 0.3
    text = s.report()
    assert "busy" in text and "test_sampler.py" in text
    assert s.write(tmp_path).read_text() == text


def test_start_and_stop_run_in_the_background():
    s = Sampler(interval_s=0.005).start()
    time.sleep(0.05)
    s.stop()
    assert s.samples and s.stopped is not None


def test_on_linux_cpu_time_decides_running():
    ticks = {"t": 0}

    class T:
        name, native_id = "walk", 7

    import sys as _sys
    frame = _sys._getframe()
    s = Sampler(cpu_fn=lambda nid: ticks["t"])
    for step in (0, 1, 1, 3):                                     # first sample is the baseline; then +1, +0, +2 ticks
        ticks["t"] = step
        s.sample_once(frames={123: frame}, threads={123: T()})
    assert s.samples["walk"] == 4 and s.running["walk"] == 2 and s.cpu_ticks["walk"] == 3
