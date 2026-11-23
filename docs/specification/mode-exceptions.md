# Mode exceptions

G2 behaves the same in every mode (the voice service, the exploration, the ball chase and the goals, the test drills). A behavior that is different in one mode is allowed only when it was explicitly requested. This page is the register of those requests; it is empty on purpose.

An exception needs all of these, or the mode consistency check (`tools/check_modes.py`) fails:

- **The request:** the exact wording of the request and its date, written here.
- **The code:** the lines that differ carry the tag `MODE-SPECIFIC(file name, date)`, and this page names the same file.
- **The scope:** which mode differs and what it does differently, in one sentence.

Registered exceptions:

- The attentive look (the attentive bout, the live follow, the camera-only checks and the lift calibration):
  - The request (2026-11-15): "when we do this kind of look, no sound from the camera when we take a picture. turn that sound off for pictures when we do this kind of look."
  - The code: `behavior/attentive_bout.py`, `behavior/gallery_target.py`, `behavior/lift_cal.py`, `behavior/punt_watch_test.py` and `vision/stream_probe.py` build their camera with `click=False`.
  - The scope: in these looks the camera takes its pictures without the shutter click. Every other mode keeps the double click on every picture.
- The attention pose right after a lob:
  - The request (2026-11-23): the owner approved the proposal to give the move gate one narrow exception so the attention pose can follow a lob at once (the proposal: "for a few seconds after a lob, a pitch that matches the lob's known end pose (about -28 degrees, with roll under 12) doesn't count as a sag").
  - The code: `behavior/ball_chase.py` (`LOB_END_PITCH_DEG`, `LOB_END_S`, `SerialRobot.expect_lob_end` and the claw look's gate in `sit_down`); only a caller that has just played the lob and calls `expect_lob_end` gets it (`behavior/basket_run.py`).
  - The scope: after a lob the body stands pitched about 28 degrees nose-down with the claw up; for 20 seconds that pose is accepted by the claw look's move gate (roll still inside the gate) instead of laying him down and standing him up first.

