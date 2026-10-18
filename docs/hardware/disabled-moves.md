# Disabled moves (pod payload, 2026-10-18)

With the Pi pod and the AI head on (about 481 g, 46% of it over the front feet), any move that leaves G2 on three feet, extends the legs or jumps tips him over. The wave flipped him twice in one session (both times triggered by mis-heard speech), and the owner reported the same for the other one-foot moves.

`link/opencat.py` `DISABLED_SKILLS` lists the tokens; `SerialLink.send` refuses them for every caller (voice, gestures, survey) and plays the wrong-answer horn. The voice skills `wave` and `scratch` stay in Claude's list, marked disabled, so a request for them gets the horn and not a silent no.

## Audit

Scored from the firmware's own frames (`rl_training/opencat-gym/reference_gait/InstinctBittleESP.h`): the largest left-right asymmetry within a leg pair (a lifted foot), the knee range, and the largest front-rear shoulder difference (body tilt).

| Move (token) | Left-right asymmetry | Front-rear tilt | Decision |
|---|---|---|---|
| wave (`khi`) | 129 | 144 | disabled; flipped him twice |
| high five (`kfiv`) | 146 | 96 | disabled |
| scratch (`kscrh`) | 141 | 60 | disabled |
| shake paw (`kgdb`) | 22 | 71 (knee to 84) | disabled |
| hop (`kjpF`) | 0 | 60 | disabled (a jump; off by default already) |
| stretch (`kstr`) | 0 | 105 | kept, borderline: four feet but a strong lean; used by the wake-up |
| push-ups (`kpu`) | 40 | 80 | kept, borderline |
| play-bow (`kbuttUp`) | 0 | 45 | kept |
| nod, shake head, check around, come here, sit, stand, rest | 0 to 24 | 0 to 60 | kept |
| walk, trot, crawl, walk back | gaits | 13 to 26 | kept (walking gaits; trot and crawl untested on this payload) |

A kept move that tips him over on hardware goes into `DISABLED_SKILLS` the same way.
