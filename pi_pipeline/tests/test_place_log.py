"""Place memory P1: the survey-stop records (behavior/place_log.py) and the hook in the picture saver."""
import json
from types import SimpleNamespace

from pi_pipeline.behavior.place_log import PlaceLog, read_stops
from pi_pipeline.vision.exploration_pictures import ExplorationPictureSaver


def _jpeg(color=(120, 90, 60)):
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (48, 48), color).save(b, "JPEG")
    return b.getvalue()


def test_records_chain_the_legs_and_survive_missing_pieces(tmp_path):
    t = [1000.0]
    yaws = iter([10.0, 350.0, None])
    walls = SimpleNamespace(state="clear", nearest_in=40.0, group_in=[40.0, None], cam=object())
    log = PlaceLog(str(tmp_path), yaw_fn=lambda: next(yaws), wall_fn=lambda: walls, embed_fn=lambda b: [0.6, 0.8], clock=lambda: t[0], session="s1")
    pic = tmp_path / "survey" / "20261010" / "after_bow_1.jpg"
    pic.parent.mkdir(parents=True)
    pic.write_bytes(b"x")
    a = log.record_stop(str(pic), {"detections": [{"label": "cat"}]})
    t[0] += 30
    b = log.record_stop(None, {}, jpeg=b"y")                      # a near-duplicate that was not kept
    t[0] += 20
    c = log.record_stop(str(pic), {})
    assert a["n"] == 1 and a["picture"] == "survey/20261010/after_bow_1.jpg" and a["since_prev_s"] is None and a["yaw_change"] is None and a["embedding"] == [0.6, 0.8]
    assert a["wall"] == {"state": "clear", "nearest_in": 40.0, "group_in": [40.0, None]} and a["detections"] == [{"label": "cat"}]
    assert b["picture"] is None and b["since_prev_s"] == 30.0 and b["yaw_change"] == -20.0          # 10 -> 350 is 20 degrees to the left
    assert c["yaw"] is None and c["yaw_change"] is None and c["since_prev_s"] == 20.0
    rows = read_stops(str(tmp_path / "place_stops.jsonl"))
    assert [r["n"] for r in rows] == [1, 2, 3] and all(r["session"] == "s1" for r in rows)


def test_a_failing_embedder_or_writer_never_raises(tmp_path):
    def boom(_b):
        raise RuntimeError("no pillow")
    log = PlaceLog(str(tmp_path), embed_fn=boom, session="s")
    rec = log.record_stop(None, {}, jpeg=b"z")
    assert rec["embedding"] is None and rec["embedder"] is None
    blocked = tmp_path / "file"
    blocked.write_text("not a folder")
    assert PlaceLog(str(blocked / "sub"), session="s").record_stop(None, {}, jpeg=_jpeg()) is None


def test_the_saver_reports_survey_stops_only_including_near_duplicates(tmp_path):
    jpg = _jpeg()
    src = SimpleNamespace(snapshot=lambda settle=None: SimpleNamespace(jpeg=jpg, width=48, height=48, detections=[("cat", 0.6, 0.5, 0.5, 0.2, 0.2)]))
    seen = []
    saver = ExplorationPictureSaver(src, str(tmp_path), on_survey_stop=lambda path, meta, jpeg: seen.append((path, meta, jpeg)))
    p1 = saver("after_bow")
    p2 = saver("after_bow")                                         # the same view: not kept, but still a stop
    saver("look_left")                                              # a throwaway look is not a stop
    saver("name:mug")
    assert p1 and p2 is None and len(seen) == 2
    assert seen[0][0] == p1 and seen[0][1]["detections"][0]["label"] == "cat" and seen[1][0] is None and seen[1][2] == jpg
    log = PlaceLog(str(tmp_path), session="s")
    rec = log.record_stop(*seen[0])
    assert rec["picture"].startswith("survey/") and len(rec["embedding"]) == 101
    assert json.loads((tmp_path / "place_stops.jsonl").read_text().splitlines()[0])["n"] == 1
