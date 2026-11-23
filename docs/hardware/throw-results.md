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

Recognition pictures
--------------------

Claw-camera pictures (240 by 240 pixels) for the cylinder and basket finders, 31 in all, kept in the `recog` picture set on the Pi and never in the repository.
- Conditions: attention pose with the claw raised to 120 degrees (the standing camera view), hardwood floor, the camera held still while the objects were moved. Distances are measured from the claw tip; the lens sits 2 inches behind the tip, so add 2 inches for the distance from the lens. The basket distance is to its centre. The cylinder's "face" labels (A to D) are approximate quarter turns, meant as a sample of how it looks from all around.
- Cylinder flat on the floor, face A, centred: 6, 9, 12, 15, 18 and 24 inches. Faces B, C and D at 18 inches. Face A at 12 inches, 3 inches to the left and to the right.
- Cylinder on its side, centred: angles A to D at 12 inches, and angle A at 18 inches.
- Basket, centred: 12, 18, 24, 30 and 36 inches; at 24 inches, 6 inches to the left and to the right.
- The throw setup (basket centre 16 inches, cylinder touching the claw): at claw lift 0 (one frame came out grey and blurry and was retaken) and at lift 120.
- Cylinder held in the claw after a real pick-up: resting, then standing at lift 0, 60 and 120. One more held with a deliberately bad grab, standing at lift 0.
- Findings on size: the cylinder is about 20 pixels across at 6 inches from the claw tip, 14 to 15 at 9, 10 to 12 at 12, and only a 4 to 5 pixel speck at 18 inches, so it can be found by colour only within about 15 inches of the claw tip. The basket is about 40 pixels wide at 12 inches from the claw tip, close to the 39 pixels the width model predicts for a 5 inch object 14 inches from the lens (110 pixels per inch at one inch).
- Findings on colour: the basket is a pale orange cup that stands out from the grey hardwood and wall. The cylinder shows green, red or orange and white, and the pair visible changes with its rotation, so the finder needs a palette of all its colours and a size check.
- Findings on the held cylinder: at lift 0, 60 and 120 the held cylinder fills the bottom centre between the jaws as a large rounded block of colour, so a good grip can be recognised from that block. Measured on the three good-grip pictures: about 1,700 to 1,860 saturated pixels in the bottom region (rows 120 to 240, columns 40 to 200), centred near column 135 and row 222. A cylinder on the floor touching the claw at lift 0 is centred higher (row about 177), and at lift 120 only a small sliver shows. These come from three pictures, so any threshold is provisional until poor grips are measured.
- Exposure: the first twelve pictures had a mean brightness of 116 to 139 (the camera's target is 85 to 140). It rose to 156 as the daylight changed and fell again after the robot was turned; 4 to 7 percent of pixels were blown out on the later pictures, mostly the bright window behind the objects.
- Bad-grab calibration (attention pose, hand-placed cylinder, colour block in the bottom region as area in pixels, centre column and centre row): the grip look's colour block did not separate bad grabs from good ones, so it stays a log-only picture and sets no threshold.
  - Claw at lift 0, bad grabs: held by the tips 1,354 px, column 108, row 194 (unclear); tilted 3,926 px, column 103, row 205 (unclear); barely touching 3,120 px, column 125, row 210 (good).
  - Claw at lift 120, bad grabs: tips 3,082 px, column 125, row 211; partial grip a bit past the tips 2,395 px, column 121, row 216; held near one end 2,546 px, column 118, row 217; tilted 2,246 px, column 111, row 217; held low in the jaws 1,607 px, column 112, row 220. All five read good.
  - Claw at lift 120, three fully cradled grips placed by hand: 1,734 px, column 97, row 221 (unclear); 3,526 px, column 116, row 220 (unclear); 1,902 px, column 113, row 208 (good).
  - Reading: good grips span 1,734 to 3,526 px and columns 97 to 116, bad grabs span 1,607 to 3,926 px and columns 103 to 125, so area, column and row overlap. The earlier good grips taken after a real pick-up (about column 135, row 222) were not reproduced by hand-placed ones.
- Grip look in three lifts (`g2lob --grip-look`, basket 16 inches out, no landing distances taken): the check read unclear every time (2,179 px, column 126, row 165; 3,733 px, column 104, row 187; 1,970 px, column 121, row 155). By eye the grip was good after the pick-up in all three; in two the cylinder was dropped during the throw, in one it went past the basket over the back rim. A dedicated series was not run: the look is captured on every lift instead.
- Basket distance readings (attention pose, claw at lift 120, the tape started at the claw tip, hardwood): the basket finder's distance from the claw tip against the measured distance, in inches.
  - 12 measured: read 9.3 (width 63 px). 14: 11.8 (54 px). 15: 13.7 (49 px). 16: 16.1 (44 px).
  - 17: 17.4 (42 px). 18: 18.0 (41 px). 20: 21.3 (37 px). 22: 25.8 (33 px).
  - The finder is within 0.4 inch from 16 to 18 inches and off by up to 2.7 short at 12 and 3.8 long at 22. A fit of distance as a constant divided by the width gives about 731 divided by the width in pixels and lands within 0.6 inch at all eight distances; a second constant does not improve it. Bearing read within 0.7 degrees of centred in every picture.

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
