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

    def sit_down(self):
        self.log.append(("attention", None))
        return "ok"


def test_the_drop_raises_the_arm_opens_then_closes_the_claw_and_lowers_the_arm():
    r = Robot()
    assert drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None) == "ok"
    assert r.log == [("claw_pose", 75.0), ("tx", "i2 60"), ("tx", "i2 0"), ("claw_pose", 0.0)]                          # standing: the arm to the drop lift, the jaw open and closed, the arm down
    r = Robot()
    drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None, lower=False)
    assert r.log == [("claw_pose", 75.0), ("tx", "i2 60"), ("tx", "i2 0")]                                           # the drill backs up with the arm still raised and lowers it itself
    r = Robot()
    drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None, attention=True)
    assert r.log[0] == ("attention", None)


def test_a_fall_while_raising_or_lowering_the_arm_stops_the_move_before_any_jaw_command():
    r = Robot(fell_at=75.0)
    assert drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None) == "fell" and r.log == [("claw_pose", 75.0)]
    r = Robot(fell_at=0.0)
    assert drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None) == "fell" and ("tx", "i2 0") in r.log


def test_the_drop_records_the_commands_the_arm_reads_the_phase_times_and_the_tilt():
    r = Robot()
    r._pitch, r._roll = [3.0, -7.5], [1.0, 2.0]
    reads = iter([[0, 120, 0], [0, 120, 58], [0, 120, 0], [0, 0, 0]])
    info = {}
    ticks = iter(range(0, 100))
    drop.drop_puck(r, say=lambda s: None, sleep=lambda s: None, read_arm=lambda: next(reads), info=info, clock=lambda: float(next(ticks)))
    assert info["commands"] == ["i2 60", "i2 0"]
    assert info["arm_reads"] == [["before opening", [0, 120, 0]], ["while open", [0, 120, 58]], ["after closing", [0, 120, 0]], ["arm down", [0, 0, 0]]]
    assert [p[0] for p in info["phases"]] == ["raised", "jaw open", "jaw closed", "lowered"] and info["tilt_max_deg"] == [[7.5, 2.0], [7.5, 2.0]] and info["arm_left_at"] == 0.0
