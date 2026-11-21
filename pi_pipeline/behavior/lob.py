"""The lob: G2 stands up, picks the object up from the floor in front of him, and lobs it forward, as one fluid motion (owner, 2026-11-21).

One definition every way of asking for it shares: the `g2lob` shell command, the "G2, lob" voice command (`lob_launch.py`) and the tests all run `main()` here, which plays `behavior/scripts/lob_soft.json` through the scripted-skill
player (`scripted_skill`) with the pick-up first (`catapult.pick_up`: Petoi's `pickF`, waited out until its own end), a short pause, then the throw, the gyro balance off (with it on the feet shake while he stands) and the eased rest after.
The numbers are the ones the sequence was run with on G2: the amount 1.0 and the 0.5 s pause between the pick-up's end and the throw (`PICK_GAP_S`; the board took the throw after that pause and the 0 s pause failed once, 2026-11-21).
G2 on his feet or at rest on the floor, the object in front of the claw, a soft clear floor ahead, hands near. `python -m pi_pipeline.behavior.lob --dry-run` prints the frames and touches nothing.
"""
from __future__ import annotations

import sys

SCRIPT = "lob_soft"
AMOUNT = 1.0
PICK_GAP_S = 0.5


def args(extra: list | None = None) -> list:
    """The scripted-skill arguments of the lob; `extra` (for example ["--dry-run"]) is added at the end."""
    return [SCRIPT, "--amount", str(AMOUNT), "--pick", "--pick-gap", str(PICK_GAP_S), "--gyro-off"] + list(extra or [])


def main(argv: list | None = None) -> None:
    from . import scripted_skill
    scripted_skill.main(args(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
