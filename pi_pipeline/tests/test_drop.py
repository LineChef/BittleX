"""The drop move (behavior/drop.py): arm up, claw open then closed, arm down; the jaw is never commanded with the arm down."""
from pi_pipeline.behavior import drop


class Robot:
    def __init__(self, fell_at=None):
        self.log, self.fell_at = [], fell_at

    def claw_pose(self, pan, lift):
        self.log.append(("claw_pose", lift))
        return "fell" if self.fell_at == lift else "ok"

    def _tx(self, cmd):
        self.log.append(("tx", cmd))


def test_the_drop_raises_the_arm_opens_then_closes_the_claw_and_lowers_the_arm():
    r = Robot()
    assert drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None) == "ok"
    assert r.log == [("claw_pose", 120.0), ("tx", "i2 60"), ("tx", "i2 0"), ("claw_pose", 0.0)]


def test_a_fall_while_raising_or_lowering_the_arm_stops_the_move_before_any_jaw_command():
    r = Robot(fell_at=120.0)
    assert drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None) == "fell" and r.log == [("claw_pose", 120.0)]
    r = Robot(fell_at=0.0)
    assert drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None) == "fell" and ("tx", "i2 0") in r.log
