import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import img_info as ii  # noqa: E402


def test_png_gif_and_svg_sizes_are_read_from_their_headers(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 480) + b"\x08\x06\x00\x00\x00" + b"\x00" * 8)
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a" + struct.pack("<HH", 32, 16) + b"\x00" * 8)
    svg = tmp_path / "a.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60"></svg>')
    assert ii.image_size(str(png)) == (640, 480) and ii.image_size(str(gif)) == (32, 16) and ii.image_size(str(svg)) == (120, 60)
    assert ii.image_size(str(tmp_path / "missing.png")) is None


def test_an_svg_with_a_script_a_handler_or_an_outside_reference_is_unsafe():
    assert ii.svg_problems('<svg viewBox="0 0 1 1"><path d="M0 0"/></svg>') == []
    bad = ii.svg_problems('<svg><script>x()</script><rect onclick="x()"/><image href="https://x/y.png"/><style>@import url(http://x/a.css);</style></svg>')
    assert len(bad) >= 4
