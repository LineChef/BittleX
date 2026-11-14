"""G2's body limits that EVERY mode shares (owner, 2026-11-13: "any change we make to G2 in any mode should apply to all modes").

One definition of a fall and of a deaf board, read by the stand guard, the ball chase, the exploration, the voice service and the test scripts. A mode never defines its own: change a number here and it changes
everywhere. (`tools/check_modes.py` and `tests/test_mode_parity.py` fail when a mode does.)
"""
from __future__ import annotations

FALL_DEG = 60.0          # the body tilt (the larger of roll and pitch) past which G2 has fallen; set by the owner, 2026-11-13: 60 degrees in every mode
FALL_HOLD_S = 0.3        # the tilt must last this long before it is a fall (a stand-up's lurch is not)
FALL_REARM_DEG = 40.0    # the fall guard re-arms once he is back under this tilt
SILENT_END_S = 20.0      # the board sends no motion data for this long: it is not answering, the mode ends and G2 is laid down
