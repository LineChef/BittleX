# Reference climb frames

Extracted 2026-09-19 from the official PetoiCamp reference video ("The Power
of Palm-Sized Robotics | Bittle Climbs a Step"),
https://www.youtube.com/watch?v=rRkVR3PO1o8 (real Bittle hardware climbing a
cardboard-box step, not simulated). Downloaded via `yt-dlp` (format 134,
640x360) + frames extracted via `ffmpeg` at 1.5fps, then hand-picked the 7
frames below that best capture each phase of the motion. Source video not
committed (copyright) -- these still frames are for internal reference only
when tuning `rl_training/opencat-gym/crawl_climb.py`, not for redistribution.

## The phases, in order

**01-front-leg-reach.png** -- Robot approaches the box with the front-left
leg already lifted and reaching up and forward, well before the body is
close. The reach is big: shoulder rotated high, leg nearly fully extended,
going for a point well past the near edge of the box.

**02-front-feet-plant.png** -- Front foot down on top of the box, planted
deep (well past the edge, not right at the lip). Body still mostly behind/
below, rear legs still flat on the table.

**03-steep-arch-rear-extended.png** -- The most dramatic frame. Front feet
now secured on top, and the REAR LEGS ARE NEARLY FULLY EXTENDED (straight,
tall), driving the body up into a steep, almost-vertical mantle position --
back arched high, tail straight out. This is the "tall stance = leverage"
mechanism directly on screen: the rear legs aren't stepping yet, they're
just standing as tall/straight as possible, and that alone rotates the body
up and forward over the front anchor point.

**04-first-rear-leg-lifts.png** -- Body has come down to a shallower angle
(still steep, but leveling), rear legs still planted, then ONE rear leg
lifts off the ground while the other stays firmly planted -- confirms the
"one leg extended for support while the other steps" behavior.

**05-body-arches-rear-closes-in.png** -- Back arched (cat-stretch shape),
rear legs still mostly on the table but visibly closer to the box now.
Front legs bent in a normal standing posture (NOT collapsed/retracted) even
though they're bearing significant weight here.

**06-all-four-nearly-up.png** -- Rear legs now up near/on the box edge,
body still somewhat arched, front standing normally.

**07-final-standing-tall.png** -- THE KEY REFERENCE FRAME for the "sitting
on its belly" problem. All four feet planted on top of the box, and the
robot is standing TALL, LEVEL, and NATURALLY -- legs in a normal moderate
bend (nothing like our simulated result's ~90deg front-knee fold), body
well clear of the platform surface, not sunk down between the legs at all.

## What this confirms vs. what's still open in our sim (as of 2026-09-19)

- Confirms the front legs plant DEEP (matches our "slide deeper" fix).
- Confirms the rear-leg-extended "tall stance" IS the leverage mechanism
  during the steep-arch phase (frame 03) -- not cosmetic.
- Confirms one-leg-extended-while-other-steps (frame 04) -- something we
  tried and had to revert (broke reliability); worth another isolated
  attempt now that the tuck-swing-extend mechanism works.
- Frame 07 is the target for the still-open "front legs go limp / sitting
  on belly" problem -- our sim's front knee ends up near its 90deg physical
  limit by the time all four feet are secured (see
  `docs/rl/crawl-climb-session-checkpoint.md`, "UPDATE 4"), nothing like
  this frame's natural, moderate standing bend. The real robot never
  appears to over-flex the front knee this way, which suggests OUR pull/
  advance mechanism (accumulating knee flex across the initial secure, the
  slide-deeper depth fix, AND the same-side leverage advance, with no
  compensating extension anywhere in between) diverges from how the real
  gait manages front-leg posture throughout the climb, not just at the end.
