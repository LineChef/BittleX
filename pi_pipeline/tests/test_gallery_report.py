"""tools/gallery_report.py: near-duplicate groups keep the best (or a hand-named) picture and list the rest as extras."""
import importlib.util
import os

spec = importlib.util.spec_from_file_location("gallery_report", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "gallery_report.py"))
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)


def H(i):
    return ((1 << 12) - 1) << (12 * i)


def row(name, quality, h, hand=False):
    return {"path": name, "size": 1000, "hash": h, "quality": quality, "hand": hand}


def test_groups_keep_the_best_and_never_list_a_hand_named_picture_as_an_extra():
    rows = [row("a1", 0.9, H(0)), row("a2", 0.5, H(0) ^ 0b11), row("a3", 0.7, H(0) ^ 0b1), row("b1", 0.4, H(3)), row("h", 0.1, H(0) ^ 0b111, hand=True)]
    gs = gr.groups(rows)
    assert len(gs) == 1 and gs[0][0]["path"] == "h"                    # a hand-named picture leads its group
    assert sorted(r["path"] for r in gr.extras(gs)) == ["a1", "a2", "a3"]
    rows[-1]["hand"] = False
    gs = gr.groups(rows)
    assert gs[0][0]["path"] == "a1" and sorted(r["path"] for r in gr.extras(gs)) == ["a2", "a3", "h"]       # the best scored stays


def test_promoted_named_auto_and_person_pictures_are_never_extras():
    for part in ("promoted", "named", "auto", "person"):
        assert gr._hand(f"/x/{part}/greenball/a.jpg") is True
    assert gr._hand("/x/explore/survey/a.jpg") is False
