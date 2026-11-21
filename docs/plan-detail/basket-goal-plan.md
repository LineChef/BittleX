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

## Hardware sessions

Session A (first, no recognition needed): start with the guided steps of `hw-session`; step 1's 20 lobs and the pick-up grid; a ruler or mat on the hardwood, a soft clear floor ahead, the pack above 70 percent, voice service off between runs (`g2stop voice`), each throw's distance and sideways offset reported and entered with `g2throws`. Stop on any fall and analyse it before the next run.
Session B: step 2's pictures (the owner's basket and the cylinder at the five distances), then the finder tuning on the Mac with the saved pictures.
Session C: steps 3 and 4 together once the finders pass.

## Open decisions (owner)

- The basket or bag: size, colour, shallow or deep. Its width in inches goes into its `ObjectSpec`.
- The cylinder: its length and the colours of its bands (red, yellow and green bands were noted earlier).
- The standoff the throw uses (measured in step 1) and how wide the opening must be.
