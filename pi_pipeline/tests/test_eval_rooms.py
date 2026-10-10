"""tools/eval_rooms.py (place memory phase P0) on made-up pictures: two rooms with different colours over two days."""
import json

import pytest

pytest.importorskip("PIL")
pytest.importorskip("numpy")


def _make(root, name, day, hhmmss, color, noise):
    from PIL import Image
    d = root / "survey" / day
    d.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (64, 64), color)
    for x in range(0, 64, 8):                       # a little texture so the pictures differ from each other
        for y in range(0, 64, 8):
            img.putpixel((x, y), (noise, noise, noise))
    img.save(d / f"{name}.jpg")
    (d / f"{name}.json").write_text(json.dumps({"time": f"2026-10-{day[-2:]} {hhmmss}"}))


def test_rooms_with_different_looks_are_told_apart_across_days_and_the_gate_passes(tmp_path):
    from tools import eval_rooms as er
    rooms = {}
    for day in ("20261008", "20261009"):
        for k in range(6):
            kitchen, hall = ((200, 190, 170), (60, 70, 120))
            for room, col in (("kitchen", kitchen), ("hallway", hall)):
                n = f"{room}_{day}_{k}"
                _make(tmp_path, n, day, f"{10 + (0 if room == 'kitchen' else 1)}:{k * 10:02d}:00", tuple(c + k * 3 for c in col), 20 * k)
                rooms[n + ".jpg"] = room
    (tmp_path / "rooms.json").write_text(json.dumps(rooms))
    items, bad, untimed = er.load(tmp_path)
    assert len(items) == 24 and bad == 0 and untimed == 0
    name, room_names, days, res = er.evaluate("histogram", items, same_stop_s=60, topk=2, window=3)
    assert room_names == ["hallway", "kitchen"] and all(len(d) == 2 for d in days.values())
    assert res["session"]["acc"] == 1.0 and res["session"]["vote"] == 1.0 and res["session"]["n"] == 24
    assert er.main(["--root", str(tmp_path), "--topk", "2", "--same-stop-s", "60"]) == 0


def test_it_asks_for_room_labels_when_there_are_fewer_than_two_rooms(tmp_path, capsys):
    from tools import eval_rooms as er
    assert er.main(["--root", str(tmp_path)]) == 1
    assert "at least 2 rooms" in capsys.readouterr().out
