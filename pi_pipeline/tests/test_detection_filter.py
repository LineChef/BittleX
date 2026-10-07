"""vision/detection_filter.py: fewer false cats and dogs. Animal classes need a score, a plausible shape and several frames in a row; everything else passes untouched."""
import json

from pi_pipeline.vision.detection_filter import AnimalDetectionFilter, DetectionLog, FilterConfig
from pi_pipeline.vision.feed import Detection


def det(label, score, cx=0.5, cy=0.5, w=0.3, h=0.35):
    return Detection(label, score, cx - w / 2, cy - h / 2, w, h)


def run(f, frames):
    return [[d.label for d in f(fr)] for fr in frames]


def test_a_real_looking_cat_counts_only_after_three_frames_in_a_row():
    f = AnimalDetectionFilter()
    assert run(f, [[det("cat", 0.8)]] * 4) == [[], [], ["cat"], ["cat"]]


def test_a_frame_without_it_breaks_the_run():
    f = AnimalDetectionFilter()
    assert run(f, [[det("cat", 0.8)], [det("cat", 0.8)], [], [det("cat", 0.8)], [det("cat", 0.8)], [det("cat", 0.8)]]) == [[], [], [], [], [], ["cat"]]


def test_the_two_kitchen_false_positives_are_dropped_at_every_frame():
    f = AnimalDetectionFilter()
    floor_cat = det("cat", 0.90, cx=0.487, cy=0.596, w=1.0, h=0.79)          # a box over the whole floor view, score 0.9
    floor_dog = det("dog", 0.54, cx=0.596, cy=0.683, w=0.781, h=0.233)       # a low flat strip, score 0.54
    assert run(f, [[floor_cat], [floor_dog]] * 4) == [[]] * 8
    assert f.reject_reason(floor_cat).startswith("box covers") and f.reject_reason(floor_dog).startswith("score")
    assert f.reject_reason(det("dog", 0.9, cx=0.6, cy=0.7, w=0.78, h=0.23)).startswith("flat wide")                      # a strong score does not save a strip of floor


def test_people_and_faces_pass_untouched_whatever_their_score_or_shape():
    f = AnimalDetectionFilter()
    frame = [det("face", 0.2, w=1.0, h=1.0), det("person", 0.1, w=0.9, h=0.2)]
    assert run(f, [frame]) == [["face", "person"]]


def test_two_boxes_of_one_label_in_a_frame_count_as_one_frame():
    f = AnimalDetectionFilter(FilterConfig(confirm_frames=2))
    two = [det("cat", 0.8, cx=0.3), det("cat", 0.8, cx=0.7)]
    assert run(f, [two, two]) == [[], ["cat", "cat"]]


def test_settings_build_the_filter(monkeypatch):
    import types
    s = types.SimpleNamespace(vision_animal_labels="Cat, fox", vision_animal_min_score=70, vision_animal_confirm_frames=2)
    f = AnimalDetectionFilter.from_settings(s)
    assert f.cfg.animal_labels == ("cat", "fox") and f.cfg.min_score == 0.7 and f.cfg.confirm_frames == 2


def test_the_detection_log_writes_throttled_json_lines_and_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_DETECTION_LOG", "on")
    t = [1_000_000.0]
    dl = DetectionLog(tmp_path, clock=lambda: t[0])
    f = AnimalDetectionFilter(on_event=dl)
    floor = det("cat", 0.9, w=1.0, h=0.79)
    for _ in range(5):
        f([floor])                                                    # five frames inside one second: one line
    t[0] += 2.0
    f([floor])
    lines = [json.loads(x) for p in tmp_path.glob("*.jsonl") for x in p.read_text().splitlines()]
    assert len(lines) == 2 and lines[0]["outcome"] == "dropped" and lines[0]["label"] == "cat" and "covers" in lines[0]["reason"]
    monkeypatch.setenv("G2_DETECTION_LOG", "off")
    quiet = DetectionLog(tmp_path / "off")
    AnimalDetectionFilter(on_event=quiet)([floor])
    assert not (tmp_path / "off").exists()


def test_the_serial_feed_applies_the_filter_to_every_frame(monkeypatch):
    import sys
    import time
    import types
    from pi_pipeline.vision.feed import SerialDetectionFeed

    class Ser:
        def __init__(self):
            self.n = 0

        def write(self, d):
            pass

        def readline(self):
            self.n += 1
            if self.n > 3:
                raise StopIteration
            return (json.dumps({"name": "INVOKE", "type": 1, "data": {"resolution": [240, 240], "boxes": [[120, 120, 240, 190, 90, 0]]}}) + "\r\n").encode()

        def reset_input_buffer(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(time, "sleep", lambda s: None)
    ser = Ser()
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=lambda *a, **k: ser))
    f = SerialDetectionFeed("/dev/null", auto_start=False, labels=["cat"], detection_filter=AnimalDetectionFilter())
    f._ser = ser
    got = []
    try:
        for fr in f.frames():
            got.append(fr)
    except (StopIteration, RuntimeError):
        pass
    assert got == [[], [], []]                                         # a 240 x 190 box in a 240 frame is the whole view: dropped each time
