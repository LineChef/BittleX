"""The contact sheet maker of `g2video` (tools/video_tool/sheet.py), on pictures made up in code."""
import importlib.util
import os

from PIL import Image

SPEC = importlib.util.spec_from_file_location("video_sheet", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "video_tool", "sheet.py"))
sheet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sheet)


def test_the_sheet_puts_every_frame_in_a_grid_and_says_how_many(tmp_path):
    for i in range(5):
        Image.new("RGB", (64, 36), (40 * i, 10, 10)).save(tmp_path / f"f{i:04d}.png")
    out = str(tmp_path / "sheet.png")
    assert sheet.make_sheet(str(tmp_path), out, 5.0, 0.08, cols=4, tile=(100, 60)) == 5
    im = Image.open(out)
    assert im.size == (400, 120)                                                                    # 4 columns, 2 rows of 100 x 60 tiles
    assert sheet.make_sheet(str(tmp_path / "none"), str(tmp_path / "x.png"), 0, 1) == 0             # no frames: nothing written
