# Paws and wide shoulders: printed, not yet installed

Two printed changes to G2's legs, both designed from simulator results and both printing as of 2026-10-24. Nothing here has been on G2 yet. The wide shoulder parts widen the track by 0.2 in per side; the paws are hinged clip-on feet that fit over the stock foot discs. This page records the design, the numbers behind it and what to check at installation. The simulator results are for the deployed walking policy (V7); they are evidence, not a hardware result.

## Wide shoulder parts

| | |
|---|---|
| What | The two Petoi side shoulders, reprinted wider at the two servo ends only. The rail between the front and rear servo windows is the unchanged Petoi part, so the top and inside keep the lid's footprint. Four servos and their legs move outward. |
| Added width | 0.2 in (5.08 mm) per side. Track 2.76 in to 3.16 in. |
| Construction | Each end is cut at \|X\| = 33.0 mm (inside the screw-hole pads) and \|Z\| >= 31 mm. The outer part (servo seat and screw holes) moves out by 5.08 mm, and the gap is filled with the shoulder's own cross-section at the cut. Servo height, fore-aft position and shaft angle do not change. |
| Source | `wide_shoulder_ends.scad` (parametric: `collar`, `cut_x`, `z0`), built on Petoi's `Bittle_SideShoulder.stl`. A 0.4 in variant exists and was not chosen. |
| Material and print | Print with infill, not solid: the simulator counted about 16 g of added mass in total and 16 g cost a little (1.2% to 2.5% falls). Weigh the printed pair and record it. |

Why 0.2 in: the joints all swing in the pitch plane, so the track can only be widened by a spacer. In the simulator (V7, 481 g, today's load) falls dropped from 8.1% to 2.3% with 0.2 in and 2.7% with 0.4 in, and the steep side slopes were fixed. At today's load 0.4 in is worse on 1 in step-downs (74% falls against 45% for 0.2 in; stock 70%) and on random ledges; it wins only at the 708 g one-pound goal (1.2% against 3.3% heavy-load falls). The simulator does not model servo torque, heat or shaft side load, and V7 is heading-blind, so turning is not tested.

## Paw ("seated" design)

| | |
|---|---|
| What | A printed foot shell that clips over the stock foot disc and pivots on it. The stock foot stays in the paw, sticking out 1.0 mm through an opening in the sole. No pin and no glue: two flaps with cone pegs push into the edges of the foot's hole. |
| Source and specs | `seated/wide_foot_part.scad` and `seated/SPECS.md` in the owner's prototypes folder (outside this repository); export with `openscad -o seated.stl -D show_pin=false wide_foot_part.scad`. SPECS.md holds the full dimension tables and the simulator notes. |
| Size | 21.8 mm (0.86 in) wide, 27.5 mm (1.08 in) long, 9.2 mm (0.36 in) tall. Pivot 4.5 mm above the sole on the foot's centre. |
| Mass | 3.25 g per paw at 100% infill (PETG, density 1.27 g/cm3 assumed). Print at 100% infill: the balance depends on it. Four paws add about 13 g. |
| Balance | The centre of mass sits within 0.1 mm of the pivot (hollow toe, heel 3 mm longer), so the toe stays up through the swing without a friction pin. |
| Stops | Toe up 30 degrees, toe down 13 degrees, hard stops of plastic on the shank. |
| Grip | Cone pegs on 1.0 mm thick, 2.5 mm wide flaps, preload 0.055 mm per side; estimated 1.8 mN.m of friction at the pivot plus load-dependent rim friction in the seats (estimates, not measured). |
| Sole | Flat from y = -7.5 to +5.5 mm, heel rolled up on a 5.2 mm radius (end rises about 3 mm), toe curled on a 30 mm radius. |

### The 2026-10-23 foot-shape update

A sole sweep in the simulator (CLpaw base, V7, free pivot, 300 episodes per cell) picked a wider sole with a tighter heel roll. Against the previous shape (18.2 mm wide, 8 mm heel radius):

- Falls on slopes, cross-slope and shoves at the one-pound load: about 13% to about 3%.
- Crossing the 0.6 in step about 50% faster (1.0 to 1.6 in/s) and the box obstacles faster (1.15 to 1.47 in/s).
- Unchanged: the 1.6 in step down (fails for every design), the 1 in step up (V7 stalls with or without paws), flat-ground walking.
- A gentler toe curl undid the gain, so the toe was left as it was.

The wider foot is `wing = 1.82` (extra width on each outer side only; the window, cheeks, seats, pegs and flaps did not move) and `heel_r = 5.2`. Stops and swing clearance were rechecked on the new STL with `paw_checks.py`: stops unchanged at 30.5 and 13.5 degrees, 0 of 49 hip and knee poses touch the body or thigh, and front and rear paws first touch each other at 30, 33 and 31 degrees of swing (stock shanks: 36).

### Simulator results for the paws (V7, heavy-load falls; stock 15.2%, 481 g 8.1%)

| Setup | Heavy-load falls |
|---|---|
| Seated paws, nominal grip | 1.8% |
| Seated paws, looser / tighter grip | 1.4% / 2.7% |
| Seated paws and 0.2 in wide shoulders | 0.1% |

These runs used the seated paw before the sole update. The new sole was confirmed on the CLpaw shape (same sole, free pivot), not re-run with the seated grip.

## Install checklist

1. Weigh the printed shoulder pair and the four paws; record the masses here.
2. Shoulders first, one change at a time. Check that each horn still seats on its spline, that the leg clears the body and that the servo cable has slack. Measure the track before and after (expected 3.16 in).
3. Fit one paw on a foot off the robot: it should drop in from the top and click, turn freely between the stops and not fall off when shaken. If it spins loosely or will not seat, the foot disc may differ from the 11.0 mm in Petoi's model (the design assumes it; unmeasured).
4. Fit the paw against the wide shoulder part and neighbouring legs. This was not checked: `paw_checks.py` uses the stock robot, and the left and right paw spacing is not tested.
5. First walk on his feet on the floor with hands near, V7 unchanged. Watch for loose shoulder screws after a few minutes, scrape and any paw that catches. Re-run the walk on each floor type before relying on it.
6. Do not retrain for the wider body yet; that is a separate decision.

## Not known

- Real print tolerances: nothing has been printed and fitted.
- The flaps flexing during walking (rigid in the simulator) and how long the PETG flaps last; the bend runs across the print layers, the weak direction.
- Floor friction against the foot and paw materials (one value in the simulator).
- The opening in the sole, the seats and the hollow toe, which the simulator fills in (collision uses the paw's convex hull).
- Whether servo load, heat or voltage change with the 0.2 in track (no servo model in the simulator).

## Files

The source files and STLs are not in this repository (the prototypes folder is outside it and ignored). A copy of the previous CLpaw and seated files, from before the 2026-10-23 sole update, is kept outside the repository in `~/.local/share/g2/paw_backups/2026-10-23_before_rank1/`.
