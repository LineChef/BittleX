"""vision/guess_labels.py: the suggested label written into a survey picture's sidecar (owner, 2026-11-12). The gallery is only read; a picture with a person in it gets none."""
import json
import types

import pytest

from pi_pipeline.vision import guess_labels as GL


def test_the_closest_named_object_is_the_guess_when_it_is_close_enough_else_the_camera_label_else_none():
    near = [{"box": [0, 0, 1, 1], "closest": "dishwasher", "sim": 0.71}, {"box": [0, 0, 1, 1], "closest": "door", "sim": 0.4}]
    g = GL.make_guess({}, near)
    assert g["label"] == "dishwasher" and g["score"] == 0.71 and g["source"] == "gallery"
    far = [{"box": [0, 0, 1, 1], "closest": "door", "sim": 0.41}]
    assert GL.make_guess({}, far)["label"] is None                                              # too far: unknown, the closest is kept for the page
    det = GL.make_guess({"detections": [{"label": "cat", "score": 0.8}, {"label": "dog", "score": 0.4}]}, far)
    assert det["label"] == "cat" and det["source"] == "detector"                                 # the camera's own label when the gallery has nothing close
    assert GL.make_guess({"detections": [{"label": "cat", "score": 0.1}]}, far)["label"] is None  # a weak detection is not a guess


class _Img:
    size = (100, 100)

    def crop(self, box):
        return types.SimpleNamespace(size=(box[2] - box[0], box[3] - box[1]))


def _labeler(monkeypatch, tmp_path, *, sim=0.8, name="mug", quality=1.0, boxes=((0.1, 0.1, 0.6, 0.6),), min_sim=0.55, threaded=False):
    import pi_pipeline.vision.embedder as E
    import pi_pipeline.vision.interest as I
    monkeypatch.setattr(E, "to_image", lambda b: _Img())
    monkeypatch.setattr(I, "crop_quality", lambda c: quality)
    scorer = types.SimpleNamespace(min_quality=0.35, localizer=types.SimpleNamespace(candidates=lambda im: [types.SimpleNamespace(box=b) for b in boxes]),
                                   embedder=types.SimpleNamespace(embed=lambda c: [1.0, 0.0]))
    entry = types.SimpleNamespace(name=name) if name else None
    gallery = types.SimpleNamespace(match=lambda emb, named_only=True: (entry, sim))
    return GL.GuessLabeler(scorer, gallery, min_sim=min_sim, threaded=threaded)


def _picture(tmp_path, meta=None):
    jpg = tmp_path / "after_bow_1.jpg"
    jpg.write_bytes(b"x")
    (tmp_path / "after_bow_1.json").write_text(json.dumps(meta if meta is not None else {"kind": "after_bow", "file": "after_bow_1.jpg", "detections": []}))
    return jpg


def test_the_guess_is_written_into_the_sidecar_and_the_rest_of_it_is_kept(monkeypatch, tmp_path):
    jpg = _picture(tmp_path)
    lab = _labeler(monkeypatch, tmp_path, sim=0.77, name="mug")
    g = lab.guess_for(jpg)
    meta = json.loads((tmp_path / "after_bow_1.json").read_text())
    assert g["label"] == "mug" and meta["guess"]["label"] == "mug" and meta["guess"]["score"] == 0.77 and meta["kind"] == "after_bow" and meta["file"] == "after_bow_1.jpg"
    assert meta["guess"]["objects"][0]["closest"] == "mug" and not list(tmp_path.glob("*.tmp"))


def test_an_unknown_thing_keeps_the_closest_name_and_a_person_gets_no_guess(monkeypatch, tmp_path):
    jpg = _picture(tmp_path)
    far = _labeler(monkeypatch, tmp_path, sim=0.3, name="door")
    g = far.guess_for(jpg)
    assert g["label"] is None and g["objects"][0]["closest"] == "door" and g["objects"][0]["sim"] == 0.3
    person = tmp_path / "p"
    person.mkdir()
    pj = _picture(person, {"kind": "after_bow", "detections": [{"label": "person", "score": 0.9}]})
    lab = _labeler(monkeypatch, tmp_path, sim=0.9)
    assert lab.guess_for(pj) is None and lab.skipped == 1 and "guess" not in json.loads((person / "after_bow_1.json").read_text())
    nothing = _labeler(monkeypatch, tmp_path, quality=0.1)                                       # a region too poor to judge is not matched at all
    assert nothing.guess_for(_picture(tmp_path))["objects"] == []


def test_a_failure_never_raises_and_the_background_thread_works_the_queue(monkeypatch, tmp_path):
    lab = _labeler(monkeypatch, tmp_path, threaded=True)
    assert lab.guess_for(tmp_path / "missing.jpg") is None and lab.failed == 1                 # no such file: logged, not raised
    jpg = _picture(tmp_path)
    lab(str(jpg))
    assert lab.wait(10.0)
    assert json.loads((tmp_path / "after_bow_1.json").read_text())["guess"]["label"] == "mug"
