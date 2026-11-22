---
audience: contributor
kind: reference
---

# Throw and basket results

This page records what was measured when G2 picked a cylinder up from the floor and lobbed it, first at a ruler and then at a basket: how far and how straight the lob goes, how close the cylinder must be for the pick-up to work, how many throws went into a 5 inch basket at two distances, and what the logs showed about the sequence that runs it. It is the measurement record behind the throw-into-a-basket goal; the sequence itself is described in [Arm skills](arm-skills.md).

Setup and measurement
---------------------

- Floor: hardwood. G2 wears the arm and claw. The object is one cylinder (1 inch across) held in the claw.
- The lob is the `lob_soft` script played right after Petoi's `pickF`, started with `g2lob`: stand up from rest, pick the object up, a 0.5 s pause, the throw, rest. The gyro balance is off for the run.
- Distances are read along a ruler with its zero at the claw tip. At the start of every pick-up the claw was touching the cylinder. Sideways is measured in inches to the right of the aim line (negative is left).
- The distance recorded is where the cylinder first landed.
- The basket is circular, 5 inches across, with its centre at the stated distance. A throw counts as a make only if the cylinder ends up in the basket; a bounce out counts as a miss.
- Every number below was measured by hand and entered after each throw. The pack read 100 percent at the start and about 75 percent at the end of the runs.

Pick-up reach
-------------

`pickF` picks the cylinder up only from a very small area in front of the claw. One try per position, full-cradle grip:
- 2 inches out in front, centred: not picked up (out of reach).
- 1 inch out, centred: not picked up (barely out of reach).
- 0.5 inch out, centred: picked up, at the limit of the claw's reach.
- Touching the claw, 0.5 inch to the left: picked up, at the sideways limit.
- The sideways limit is 0.5 inch either side. Further to the left or right is a miss. The grab is best when the cylinder is right in front of the claw, and a poor grab gives a poor throw.

The window is about 1 inch wide and half an inch deep. An approach that stops G2 within half an inch of the cylinder, in both directions, is needed for him to pick it up on his own.

Lob distance and sideways spread
--------------------------------

Twenty throws from one start, each beginning with the pick-up (4 further runs in the series were not throws; they are listed below):
- Throw 1: 18 in, centred
- Throw 2: 21 in, centred
- Throw 3: 21 in, centred
- Throw 4: 19 in, centred
- Throw 5: 14 in, 2.5 in right
- Throw 6: 17 in, centred
- Throw 7: 11 in, 1 in right
- Throw 8: 19 in, centred
- Throw 9: 14 in, centred
- Throw 10: 11 in, centred
- Throw 11: 23 in, 1.5 in right
- Throw 12: 16 in, 1 in right
- Throw 13: 21 in, 0.5 in right
- Throw 14: 16 in, 2 in right
- Throw 15: 21 in, centred
- Throw 16: 21 in, centred
- Throw 17: 20 in, 1 in right
- Throw 18: 19 in, 2 in right
- Throw 19: 18 in, centred
- Throw 20: 16 in, 1 in right

- Distance: mean 17.8 in, median 18.5 in, spread (standard deviation) 3.4 in, range 11 to 23 in.
- Sideways: mean 0.6 in right of the line, spread 0.8 in, never more than 2.5 in off, and 16 of 20 within 1 inch.
- The first ten averaged 16.5 in and the last ten 19.1 in: no fade over the series.
- Body readings of the 20 runs: pitch 27.6 to 28.0 degrees nose-up and roll under 4 degrees every time.

Earlier throws, with the cylinder placed in the claw by hand
------------------------------------------------------------

- Claw-tip grip (the cylinder held by the tips of the claw): lob 21 in, line drive 19 in, and the cylinder was dragged out of the claw on other throws.
- Full-cradle grip (the claw wrapped around the cylinder): lob 25, 25 and 24 in (mean 24.7), line drive 26, 25 and 24 in (mean 25.0), `lob_soft` 23 in once.
- The lob and the line drive threw the same distance. The line drive pitches the body further (37 to 38 degrees against about 30 for the lob) and travels flatter; the lob arcs higher and was chosen for its cleaner look.
- The throws that began with `pickF` landed shorter (mean 17.8 in) than the hand-placed full-cradle throws (24 to 26 in). The grip after `pickF` is the likely cause; a block of hand-placed throws in the same session would confirm it.
- In slow-motion frames the cylinder leaves the claw at the start of the lunge, while the claw is still low, and the lob climbs while the line drive stays low. The clips used were ordinary speed (25 and 30 frames a second).

Basket, 18 inches out
---------------------

The first try went in and bounced out. Then ten throws with the basket's centre 18 inches out, centred:
- B1: miss, landed just short of the basket
- B2: miss, hit the front rim
- B3: made, went in and stayed
- B4: made, went in
- B5: miss, fell short of the basket
- B6: miss, hit the front rim
- B7: miss
- B8: miss, fell short
- B9: miss, hit the front rim
- B10: miss, short and right

Result: 2 of 10 made.

Basket, 16 inches out
---------------------

Ten throws with the basket's centre 16 inches out, centred:
- C1: made, went in
- C2: made, bounced in
- C3: miss, no detail
- C4: miss, hit the front rim
- C5: miss, hit the back rim
- C6: made, went in
- C7: made, went in
- C8: made, went in
- C9: made, went in
- C10: miss, hit the front rim

Result: 6 of 10 made, with four in a row at the end. Ten throws is a small sample, so the difference from 18 inches is encouraging but not settled. 16 inches is the best distance found so far.

Runs that were not throws
-------------------------

- Two missed pick-ups (the claw did not close on the cylinder) and one dropped cylinder: nothing valid thrown, the throw was repeated.
- Three runs where the board never took the throw (no `K` echo and the body did not move, pitch about 4 degrees against about 28). The body verdict still read `ok` in each, so the verdict alone does not show that a throw played.
- One run (C3) where the first send was not taken and the automatic second send worked.
- Two runs (C1, C4) read pitch 49 degrees and a `tipped` verdict with no fall; the cause is not found.

What the logs showed about the sequence
---------------------------------------

- A behavior skill such as `pickF` is aborted by any byte written to the board while it plays (the board answers `up`). The link therefore stays silent behind it until the board's end echo.
- With the gyro balance off the link holds a `gb` and writes it when it sees a `k`. An old `k` left from the stand-up released it 0.1 s into `pickF` in one run, so the claw never opened. The pick-up function now reads the port before sending `pickF` and waits for the first `k` after `pickF`'s own name line.
- `pickF` takes about 2.6 s. Waiting the full 10 s silence limit made G2 stand idle for about 8 s; the legs sag and the feet shake with the gyro balance on, so standing time is kept short. The idle stand after the stand-up is 2 s in every mode.
- The throw script is taken by the board only if it answers `K`. In about 3 of 20 runs it did not answer after a pick-up; the script runner now sends the script once more when there is no `K` and no motion, and records the first attempt in the log.
- With no pause between the end of `pickF` and the throw, the throw once went unplayed; with a 0.5 s pause it played in all but those few runs.
- The board's own lines in the command log carry the time the Pi read them, not the time the board sent them, so they bunch up while a skill runs.
- The throw's body pitch is the quickest check that it played: about 28 degrees for a throw and about 4 for a script that was not taken.

Open questions
--------------

- Why the board sometimes does not take the throw after a pick-up.
- Why two runs read 49 degrees of pitch with no fall.
- How much of the short and rim-hitting throws is the grab and how much is the throw itself: the grab quality (good, marginal, bad) should be recorded with each throw.
- Whether hand-placed throws after a block of pick-up throws really land 6 to 8 inches further.
- How to bring G2 to within half an inch of the cylinder on his own, and a pick-up with more reach.
