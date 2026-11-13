"""gait/fall_recorder.py: the IMU trace around a fall, saved one file per fall."""
import json

from pi_pipeline.gait.fall_recorder import FallRecorder, summarize
from pi_pipeline.gait.stand_guard import StandGuard


def line(roll, pitch, ax=0.0, ay=0.0, az=9.8, yaw=0.0):
    return f"ICM: {ax:.2f} {ay:.2f} {az:.2f} {yaw:.1f} {pitch:.1f} {roll:.1f}"


def test_a_fall_is_saved_with_the_trace_and_the_side_he_rests_on(tmp_path):
    rec = FallRecorder(directory=tmp_path, pre_s=20.0, post_s=8.0)
    t = 0.0
    for _ in range(100):                                    # 20 s standing level at 5 Hz
        t += 0.2
        rec.feed(t, line(1.0, -1.0))
    for pitch in (-20.0, -45.0, -80.0, -110.0):             # over backwards
        t += 0.2
        rec.feed(t, line(2.0, pitch, ax=-5.0, az=5.0))
    rec.trigger(t, 110.0, standing=True)
    for _ in range(50):                                     # rests on his back: gravity along -x
        t += 0.2
        rec.feed(t, line(3.0, -100.0, ax=-9.8, az=-1.0))
    assert len(rec.saved) == 1
    doc = json.loads(rec.saved[0].read_text())
    s = doc["summary"]
    assert s["peak_tilt_deg"] >= 109 and s["floor_side_axis"] == "-x"
    assert s["first_over_20_s"] is not None and s["first_over_60_s"] is not None and s["tip_from_20_to_60_s"] >= 0
    assert doc["context"]["standing"] is True and doc["columns"][0] == "t_s"
    assert doc["trace"][0][0] < -15.0 and doc["trace"][-1][0] > 7.0          # the lead-in and the settle are both there


def test_only_one_record_per_fall_and_flush_writes_early(tmp_path):
    rec = FallRecorder(directory=tmp_path)
    rec.feed(1.0, line(0, 0))
    rec.trigger(1.1, 90.0)
    rec.trigger(1.2, 95.0)                                  # ignored: one fall
    rec.feed(1.3, line(80, 0))
    assert rec.flush() is not None and rec.flush() is None
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_summary_of_nothing_does_not_raise():
    assert summarize([]) == {"frames": 0}


def test_the_stand_guard_records_its_fall(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_FALL_DIR", str(tmp_path))

    class Link:
        last_motion_command = "kup"
        def __init__(self): self.queue, self.sent = [], []
        def poll_imu(self):
            q, self.queue = self.queue, []
            return q
        def send(self, c, **kw): self.sent.append(c)

    class Clock:
        t = 0.0
        def __call__(self): return self.t

    link, clock, falls = Link(), Clock(), []
    g = StandGuard(link, clock=clock, sleep=lambda s: None, on_fall=lambda: falls.append(1), is_busy=lambda: True, balance_off_idle=False)
    for i in range(80):
        clock.t += 0.2
        link.queue = [line(2.0, 0.0) if i < 10 else line(170.0, -100.0, ax=-9.8, az=0.0)]
        g.tick()
    assert falls == [1]
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text())
    assert doc["context"]["last_motion_command"] == "kup" and doc["summary"]["floor_side_axis"] == "-x"
