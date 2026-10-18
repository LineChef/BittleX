"""Build pi_pipeline/link/skill_frames.json: the first and last leg frame of every built-in firmware skill, decoded from InstinctBittleESP.h.

The serial link eases the legs from where they are into a skill's first frame before sending the skill (pi_pipeline/link/transitions.py), so the firmware's own
fast jump into the skill becomes a short ramp. The Pi does not deploy rl_training/, so the frames it needs are written here, once, into a small JSON file next to the link.

    python tools/gen_skill_frames.py           # rewrite the JSON
    python tools/gen_skill_frames.py --check   # exit 1 if the JSON is out of date (a test runs this)

Frames are servo degrees for joints 8..15 in Petoi order [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk], with the skill's angle ratio applied.
Layout per skill type (same as rl_training/opencat-gym/reference_gait/build_skill_reference.py):
  posture   period 1:  4-byte header, then 16 DOF
  gait      period >1: 4-byte header, then period x 8 leg joints
  behaviour period <0: 7-byte header, then |period| x (16 DOF + 4 timing values)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "rl_training" / "opencat-gym" / "reference_gait" / "InstinctBittleESP.h"
OUT = ROOT / "pi_pipeline" / "link" / "skill_frames.json"


def build(text: str) -> dict:
    names_m = re.search(r"skillNameWithType\[\]\s*=\s*\{(.*?)\};", text, re.S)
    names = [n[:-1] for n in re.findall(r'"([^"]+)"', names_m.group(1))]          # the last letter is the skill's type tag (I / N)
    out = {}
    for name in names:
        m = re.search(r"const int8_t %s\[\] PROGMEM = \{(.*?)\};" % re.escape(name), text, re.S)
        if not m:
            continue
        nums = [int(x) for x in re.findall(r"-?\d+", m.group(1))]
        period, ratio = nums[0], nums[3]
        if period == 1:
            kind, frames = "posture", [nums[4:20]]
            frames = [f[8:16] for f in frames]
        elif period > 1:
            kind = "gait"
            frames = [nums[4 + k * 8: 12 + k * 8] for k in (0, period - 1)]
        elif period < 0:
            kind, n, stride = "behaviour", -period, 20
            frames = [nums[7 + k * stride: 7 + k * stride + 16][8:16] for k in (0, n - 1)]
        else:
            continue
        frames = [[v * ratio for v in f] for f in frames]
        out[name] = {"kind": kind, "first": frames[0], "last": frames[-1]}
    return dict(sorted(out.items()))


def render(table: dict) -> str:
    lines = ["{"]
    items = list(table.items())
    for i, (name, row) in enumerate(items):
        lines.append(f'  "{name}": {json.dumps(row, separators=(", ", ": "))}' + ("," if i < len(items) - 1 else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = render(build(SRC.read_text()))
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(ROOT)} is out of date: run python tools/gen_skill_frames.py")
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(json.loads(text))} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
