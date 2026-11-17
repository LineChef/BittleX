"""tools/curate_class.py: the per-class cap keeps the protected and the best, spread over the bins; rejects and near-twins go first."""
import importlib.util
import os

spec = importlib.util.spec_from_file_location("curate_class", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "curate_class.py"))
cls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cls)


def H(i):
    return ((1 << 12) - 1) << (12 * i)                                                     # hashes far apart (24 bits differ), so they are not near-duplicates


def row(name, quality, dist=12.0, bearing=0.0, ok=True, why="", h=0):
    return {"file": name, "ok": ok, "why": why, "quality": quality, "dist_in": dist, "bearing_deg": bearing, "hash": h}


def test_the_cap_keeps_the_protected_and_the_best_and_spreads_over_distance():
    rows = [row("session_1_a.jpg", 0.1, ok=False, why="blurry", h=H(0))]                  # protected: kept whatever its score
    rows += [row(f"near_{i}.jpg", 0.5 + i / 100, dist=8.0, h=H(i + 1)) for i in range(6)]
    rows += [row("far_a.jpg", 0.2, dist=40.0, h=H(9)), row("bad.jpg", 0.0, ok=False, why="dark", h=H(10))]
    kept, dropped = cls.choose(rows, cap=4)
    assert "session_1_a.jpg" in kept and len(kept) == 4
    assert "far_a.jpg" in kept                                                            # the lone far picture fills its own bin before a fifth near one
    assert "near_5.jpg" in kept and dropped["bad.jpg"] == "dark"
    assert all(n in dropped for n in ("near_0.jpg", "near_1.jpg", "near_2.jpg"))          # the worst near ones are the ones dropped


def test_near_duplicates_collapse_to_the_best_one():
    rows = [row("a.jpg", 0.9, h=0b1111), row("b.jpg", 0.4, h=0b1110)]
    kept, dropped = cls.choose(rows, cap=10)
    assert kept == ["a.jpg"] and dropped["b.jpg"] == "near-duplicate"


def test_a_better_new_picture_replaces_the_worst_kept_one_at_the_cap():
    rows = [row(f"p{i}.jpg", 0.3 + i / 100, dist=8.0, h=H(i + 1)) for i in range(3)]
    kept, _ = cls.choose(rows, cap=3)
    assert sorted(kept) == ["p0.jpg", "p1.jpg", "p2.jpg"]
    kept, dropped = cls.choose(rows + [row("new.jpg", 0.95, dist=8.0, h=H(12))], cap=3)
    assert "new.jpg" in kept and dropped == {"p0.jpg": "over the cap (a better one fills the bin)"}
