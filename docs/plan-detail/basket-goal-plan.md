# Basket goal plan: throw the cylinder into a basket and learn from the result

Written 2026-11-21. Goal (owner): a new goal for G2. He picks the cylinder up, takes a bearing on a basket or bag the owner chooses, lines up a shot, throws, then looks (the active look) to see whether it went in, and keeps count of how often it does so his aim can improve. After a miss he finds the cylinder again, picks it up, walks out to range, pivots back toward the basket and tries again, reusing what the ball goal already does. Varying the throw's distance within about 2 feet comes after a reliable basket test case exists. Steps 1 to 7 approved 2026-11-21.

## Where it starts (verified 2026-11-21)

- The throw: `g2lob` (stand, `pickF`, `lob_soft`, rest) works. The full-cradle grip threw 24 to 26 inches over six throws (lob 24.7 mean, line drive 25.0). Sideways offset has never been recorded. The distance is one setting only; the earlier knob data (legs 70, 50, 30, 10 percent of the way before the whip threw 4, 12, 17, 15 to 18 inches) used the claw-tip grip and needs repeating.
- The ball goal is the model for the loop but is not reliable: "works some of the time", success about one in ten in later sessions, falls during turns the main problem. The retry loop leans on those parts.
- Perception: the camera's chip runs only a frozen face model. The ball finder works on the pictures on the Pi with colour rules, so the cylinder and basket finders follow it. Distance in the finders is a first guess (`FOCAL_PX`, from the ball's constant) until calibrated.
- Throw range is about 24 inches, so the basket must stand that far in front of G2 and he must stop within a few inches of it; the ball punt approach is good to about 5 inches.

## What is built ahead of hardware (not deployed, not run on G2)

- `vision/object_finder.py`: finds one colour blob (the basket, an `ObjectSpec` with its colour and real width) or a banded cylinder (at least two touching band colours); returns bearing, distance by width and the blob's box. Tested on synthetic pictures only.
- `goals/basket_outcome.py`: made, missed, not seen or no basket, from the finders' readings after the throw; a cylinder not seen is unknown, never a make.
- `behavior/throw_tally.py` and `g2throws`: the Mac's throw tally with the sideways offset and a summary per script and grip.

## Steps

1. Throw and pick-up data. 20 lobs from one marked start, on a ruler or mat, full cradle; each one's distance and sideways offset into `g2throws add lob INCHES --side IN --grip "full cradle"`. Then a grid of cylinder positions in front of the claw to find where `pickF` still takes it (the object, the position and whether it came up). Pass: the mean, range and sideways spread of 20 throws, and a map of where the pick-up works. These size the basket and set the pick-up standoff.
2. Recognition by colour, no download. Sample the cylinder's band colours and the basket's colour from pictures (one picture each, from the claw camera, at 12, 18, 24, 30 and 36 inches; never calibration folders), tune the `ObjectSpec`s, and calibrate `FOCAL_PX` against measured distances. Pass: both found at 6 to 40 inches on hardwood in at least 9 of 10 pictures with a bearing within 5 degrees and a distance within 15 percent. Gate: if colour rules cannot do it, make a download request (a trained detector) and stop; nothing is downloaded before then.
3. Aim and throw. G2 finds the basket, walks to the standoff, pivots to its bearing and throws. The lob function gets an aim parameter (a heading change) that every caller shares; a new default stays off until the owner has watched it. The cylinder is placed by hand and the owner counts makes and misses. Pass: ten shots with the sideways error and the make count recorded.
4. The outcome look. After the throw the active look takes pictures of the basket's side of the floor and `classify_throw` calls it. Pass: the call agrees with the owner's count on at least 9 of 10 throws; a light, shallow basket is preferred so the cylinder is visible inside.
5. The retry loop, after steps 1 to 4 are reliable and the ball goal's turn falls are understood. After a miss: look for the cylinder (directed look at where it landed), approach, `pickF`, walk back to the standoff, pivot to the basket, throw again; capped in attempts, a fall ends it, the battery gate before every attempt.
6. The goal wrapper. A `basket` approach in `goals/` (knobs: standoff inches, heading offset, and later the range setting; scorer codes: made, missed, cylinder never found, basket not found, could not line up, fell); the journal and report are shared; a voice start phrase and a place in "G2, practise". No API call anywhere in it.
7. Variable distance, after a reliable basket test case exists: a table of throw setting to distance with the full cradle (two or three strengths first), then a choice by the basket's measured distance, learned per distance band by the judge.

## Result of the pick-up grid (2026-11-22, session A, full cradle, hardwood)

`pickF` takes the cylinder only from a very small area: 0 to 0.5 inch out in front of the claw and up to 0.5 inch either side. At 1 inch out and at 2 inches out, centred, it missed (the owner judged 1 inch barely beyond reach); at 0.5 inch out centred and 0.5 inch to the left it picked it up, at the limit (the owner: best grip with the cylinder right in front of the claw, and the same limit to the right, so no further grid runs). The window is about 1 inch wide and half an inch deep. Consequence for the plan: the retry loop's approach has to stop within half an inch of the cylinder in both directions, far tighter than the ball goal's approach (about 5 inches) and the camera's distance reading (about 1 inch). Options to decide before step 5: a fine approach in small nudges, or a pick-up with more reach authored with the pose editor. Steps 1's 20 lobs are unaffected (the cylinder is placed by hand).

## Measurement conventions (owner, 2026-11-22)

- Distances are measured along a ruler with its zero at the claw tip, and at the start of every pick-up the claw was touching the cylinder.
- The basket is circular, 5 inches across, and its centre was at the stated distance (16 inches is the best so far; 18 inches was too far). Its opening spans about 2.5 inches either side of that centre.
- A bad pick-up means a bad throw, so the pick-up has to be right every time: the grab quality (good, marginal, bad) is worth recording with each throw.
- A bounce-out counts as a miss.

## Result of the 20 lobs and the first basket block (2026-11-22, session A, `g2lob`: stand, `pickF`, `lob_soft`, full cradle, hardwood)

- 20 lobs from one start, each starting with the pick-up: landing distance mean 17.8 inches, median 18.5, spread 3.4, range 11 to 23. Sideways: mean 0.6 inch right, spread 0.8, never over 2.5 inches, 16 of 20 within 1 inch. No fade over the series (first 10 averaged 16.5, last 10 19.1). Yesterday's hand-placed throws went 24 to 26 inches, so the grip after `pickF` is probably the cause of the shorter, more variable throws; the owner noted that the claw nearly has to touch the cylinder for a good grip. A control block of hand-placed throws would show it.
- Four runs in the 20 were not throws: one missed pick-up, one dropped cylinder, and two where the board never took the script (no `K`, no motion, about 3 of 20 over the morning). Cause not found; the script runner now sends the script once more when it sees that, and the 7 runs after it had none.
- First basket try, basket 18 inches out, centred: the cylinder went in and bounced out (proof of concept). Rule agreed: a bounce-out counts as a miss, since the look after the throw can only judge where the cylinder ended up.
- The basket block of 10 at 18 inches, centred: 2 made, 4 short, 3 front rim, 1 miss without detail. Sideways was not the problem; distance was. The owner noted some misses were bad claw grabs. Next: note the grab quality (good, marginal, bad) with every throw, then repeat the block.
- The second basket block of 10 with the basket moved 2 inches closer, 16 inches out and centred: 6 made (C1, C2, C6, C7, C8, C9), 2 front-rim misses (C4, C10), 1 back-rim miss (C5), 1 miss without detail (C3). Four makes in a row at the end (C6 to C9). C2 went in with a bad grab and a bounce. Two runs read pitch 49 and a `tipped` verdict (C1 and C4) with no fall; cause not found. One run needed the script resent (C3). 6 of 10 against 2 of 10 at 18 inches: ten throws each is a small sample, but moving the basket in closer to the middle of the landing spread helped.
- Pick-up window found on the way (see the result above): the cylinder has to be within about half an inch of the claw.

## Hardware sessions

The ordered hardware plan is the numbered list "What happens next" in `docs/STATUS.md`, so it lives in one place. Session A (throw data, pick-up reach, two basket blocks) and the recognition pictures of session B are done. The first thing next session is finishing the bad claw grab calibration, then the grip check in the lift sequence, the walking paces and a backward walk, more basket pictures for the distance reading, the after-throw look, the line-up alone, and a full attempt; the goal wrapper comes last.

## Open decisions (owner)

- The basket or bag: size, colour, shallow or deep. Its width in inches goes into its `ObjectSpec`.
- The cylinder: its length and the colours of its bands (red, yellow and green bands were noted earlier).
- The standoff the throw uses (measured in step 1) and how wide the opening must be.

## The full sequence (owner's description and decisions, 2026-11-22)

Start: G2 at rest, the cylinder in front of the claw, the basket straight ahead with its centre 16 inches from the claw tip. One attempt:
1. Stand up, pick the cylinder up, take the grip picture (log only; the throw always goes ahead).
2. Throw.
3. Look with the claw at 120 degrees for the cylinder on the floor, found by its bright colours. Seen anywhere: a miss. Not seen: counted as a make, or lost, and the run stops for a reset (the owner returns the cylinder). How to tell these apart is for later.
4. After a miss: walk to the cylinder, fine approach, pick it up (grip check), find the basket, get to 16 inches from it facing it, align, check the alignment by picture, shoot again.

Rules: 5 attempts per run. The owner returns the cylinder only after a make or when it goes out of view, at first. If G2 cannot align he keeps trying until he can. He must never bump the basket (a minimum approach distance). The cylinder gets no marker.

Later: use the claw to dump the basket out after a successful shot; a better way to tell a make from a lost cylinder; a different way to handle a lost cylinder; making the retrieval fully autonomous.

## Line-up for the next shot (built 2026-11-22, not run on G2)

Decided (owner): after a pick-up G2 finds the basket again from a fresh look before deciding anything, then lines up by option 3 of the proposal: stay facing the basket and walk forward or backward until the camera reads 16 inches from the claw tip, pivot-scan until the basket is in view when it is not, walk closer when it is far off, never come within 6 inches of the basket (a buffer), keep trying until aligned.
- `behavior/basket_lineup.py`: a pure decision function and a loop with the mover and the picture handed in, tested with a simulated room (never ends inside the buffer, backs up before turning when close, scans up to a full circle, gives up after 12 corrections for a reset). The tolerance is plus or minus 2.5 inches and 3 degrees. The movers (the walk forward, the back-up, the pivot and the arc nudge, with measured paces) are NOT written: the paces must be measured on G2 first, and a backward walk with the arm and a held cylinder has never been tried.
- `vision/basket_finder.py`: the basket by its pale orange colour, bearing from its centre column and distance from its width, fitted to the recorded pictures. On those pictures the distance (from the claw tip) read 14.6 for 12 inches, 17.4 for 18, 24.5 for 24, 34.7 for 30 and 40.1 for 36, and 14.6 and 12.8 for the two taken at 16 inches (lift 0 and lift 120), so it is good to about 1 inch from 18 to 24 inches but off by up to 3 inches near 16 and 4 past 30. The bearing read within about 3 degrees for a centred basket and 12.7 and 13.2 degrees for 6 inches left and right at 24 inches (13 expected). It needs more pictures in the operating pose, from 12 to 24 inches in inch steps at claw lift 120 (and the same at the pose after a pick-up), before the distance tolerance is tightened.
- Next: measure the walking paces (forward, back, pivot cycle) and a backward walk holding the cylinder, write the movers, calibrate the finder, then the cylinder finder and the after-throw look.

## Where we left off (2026-11-22, session cut short)

The Pi's own battery ran flat in the middle of the bad-grab pictures (about 3.3 hours after its boot at 8:54 AM; the Pi runs from a separate battery from G2's servo pack, so the pack gauge never showed it). G2 was left in an unknown pose with the servos sagging; nothing was lost on the Mac. The recognition pictures are on the Pi's card (`recog` set, shots 051 to 081) and have not been pulled to the Mac.

Done: the pick-up reach grid, the 20 lobs, two basket blocks (6 of 10 at 16 inches), the recognition picture set (see the results page, 31 pictures), and the finding that a held cylinder is visible at the bottom centre at claw lifts 0, 60 and 120.

Approved but not built (owner, 2026-11-22; the throw always goes ahead whatever the look says, so it is logging only):
1. A grip-look function: read the bottom centre of the picture for a large block of the cylinder's colours (provisional rule from the good grips: at least 1,000 saturated pixels in the bottom region, centred near row 205 or lower and column 95 to 175), reporting held or not with the numbers; tested on pictures made up in code.
2. One picture right after `pickF` in the shared lift sequence (`scripted_skill` after `catapult.pick_up`, switched on by `lob.py`): the camera opened and warmed up during the stand-up, the picture saved on the Pi with the run, the result in the run log; a camera failure is logged and the throw goes ahead. It adds about 1.5 to 3 seconds before the throw and ships behind a switch to watch on a first run.
3. The grab quality in the tally (`g2throws add ... --grab good|marginal|bad`), shown next to the automatic look in `g2lastrun`, to compare them.
4. A calibration set of about 10 deliberate poor grabs and 10 good ones to set the threshold.

First steps next session: deploy what is waiting (`bash tools/g2_deploy_safe.sh`), check the Pi is up and its battery, pull the data (`sync-data`), confirm G2's posture by eye, then the list in `docs/STATUS.md`.

## The goal stage: brainstorm notes (a loose outline, to be changed by the hardware findings)

Kept so the goal does not have to be rethought from nothing. Nothing here is built. Each part says what could change it.
- Framework (verified): a goal is a `Goal` entry (attempts per session, minutes, minimum pack percent, start phrases, the attachment it needs) plus an approach class registered in `goals/` that brings its knobs, one attempt, a scorer, a table of which knob to change after which kind of failure, and which stage judges each knob. The shared session loop gates each attempt on the battery, journals it and lets the judge change one knob at a time; knobs marked "ask" are only suggested to the person. The punt goal (`goals/ball_punt.py`) is the template. No API call anywhere in a goal.
- Id and name: `basket_throw`, "Throw into the basket"; start by a `g2basket` shell command first, a spoken phrase ("basket goal") and a place in "G2, practise" only once it is wired; `needs_attachment` arm; 5 attempts per run; minutes about 15; the servo pack gate about 40 percent plus a new Pi battery gate in the approach's battery check (the Pi ran flat once).
- An attempt: one throw (5 per run), with the retrieval folded into the start of the next attempt. Could change if retrieval does not work (then a run is attempts with the cylinder returned by hand) or if a full cycle takes too long for the Pi's battery.
- Stages: pick-up, line-up, throw. A bad grip is blamed on the pick-up stage and not on the shot distance (a bad pick-up means a bad throw). Could change with the grip check's reliability.
- Knobs: the shot distance (16 inches from the claw tip; 12 to 20) and a heading offset (0 degrees; plus or minus 6), both "ask" at first; the alignment tolerances; the 6 inch buffer fixed; the throw script variant. The shot distance step must be larger than the basket finder's distance error (about plus or minus 3 inches now), so its step depends on the distance calibration.
- Outcome codes: made; missed short; missed long; front rim; back rim; missed to a side; not seen (a make or a lost cylinder: counted as a make provisionally, with a confirm step at the end of the run, and the run stops for a reset); pick-up failed (claw missed, dropped, grip check says nothing held); basket not found; could not align; cylinder lost; fell; battery. Which of these can be told apart depends on the after-throw look test (the cylinder is only findable out to about 15 inches from the claw tip).
- Conditions: the basket's size (5 inches) joins the attachment, floor and hardware epoch, so changing the basket never mixes results.
- Success: a make is 1; an unconfirmed make counts until it is corrected.
- Stages of the build: 1, the goal and scoring with a hand-fed attempt (the lift sequence, then the person types the result and the grab quality) so runs are tracked; 2, the grip look and the after-throw look give the result automatically; 3, the line-up and retrieval; 4, learning and the voice start. Version 1 is only worth building once the tests in the status list have answered the questions above.
- Later: dump the basket with the claw after a make; a better way to tell a make from a lost cylinder; handling a lost cylinder; fully autonomous retrieval.
