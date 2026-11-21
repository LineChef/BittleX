"""The Mac's throw tally (behavior/throw_tally.py): rows with the sideways offset, an older file migrated, the summary per script and grip."""
from pi_pipeline.behavior import throw_tally as tt


def test_an_older_file_gets_the_sideways_and_note_columns_and_keeps_its_rows(tmp_path):
    p = str(tmp_path / "t.csv")
    open(p, "w").write("time,script,inches,pitch_deg,roll_deg,pack_pct,log,grip\n2026-11-21 2:58 PM,lob,21,31.0,4.9,98,x,claw tips\n")
    tt.add("lob", 25, side_in=-2, grip="full cradle", p=p, now="t2")
    rows = tt.read(p)
    assert [r["inches"] for r in rows] == ["21", "25"] and rows[0]["side_in"] == "" and rows[1]["side_in"] == "-2" and rows[1]["grip"] == "full cradle"
    assert open(p).readline().strip().split(",")[-2:] == ["side_in", "note"]


def test_the_summary_groups_by_script_and_grip_and_reports_the_sideways_spread(tmp_path):
    p = str(tmp_path / "t.csv")
    for inches, side in ((24, -1), (25, 3), (26, None)):
        tt.add("lob", inches, side_in=side, grip="full cradle", p=p)
    tt.add("lob", 21, grip="claw tips", p=p)
    tt.add("lob", None, grip="full cradle", note="not seen", p=p)                                          # no distance: not counted
    s = {(x["script"], x["grip"]): x for x in tt.summary(tt.read(p))}
    full = s[("lob", "full cradle")]
    assert full["n"] == 3 and full["mean"] == 25.0 and (full["low"], full["high"]) == (24, 26) and full["side_n"] == 2 and full["side_max"] == 3 and full["side_mean"] == 1.0
    assert s[("lob", "claw tips")]["n"] == 1 and s[("lob", "claw tips")]["side_mean"] is None
