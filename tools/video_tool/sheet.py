"""A contact sheet from a folder of frame pictures (tools/video_tool/g2video.sh): the frames in a grid, each labelled with its time. Needs Pillow (the pi_pipeline venv has it)."""
import glob
import sys

from PIL import Image, ImageDraw


def make_sheet(frames_dir: str, out: str, t0: float, dt: float, cols: int = 4, tile: tuple = (426, 240)) -> int:
    files = sorted(glob.glob(frames_dir + "/f*.png"))
    if not files:
        return 0
    w, h = tile
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h))
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB").resize((w, h))
        ImageDraw.Draw(im).text((4, 4), f"{t0 + i * dt:.2f}s", fill=(255, 255, 0))
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet.save(out)
    return len(files)


if __name__ == "__main__":
    n = make_sheet(sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
    print(f"{n} frames in {sys.argv[2]}")
    sys.exit(0 if n else 1)
