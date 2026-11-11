# Disabled moves (pod payload, 2026-10-18)

With the Pi pod and the AI head on (about 481 g, 46% of it over the front feet), any move that leaves G2 on three feet, extends the legs or jumps tips him over. The wave flipped him twice in one session (both times triggered by mis-heard speech), and the owner reported the same for the other one-foot moves.

`link/opencat.py` `DISABLED_SKILLS` lists the tokens; `SerialLink.send` refuses them for every caller (voice, gestures, survey) and plays the wrong-answer horn. The voice skills `wave` and `scratch` stay in Claude's list, marked disabled, so a request for them gets the horn and not a silent no.

## Audit

Scored from the firmware's own frames (`rl_training/opencat-gym/reference_gait/InstinctBittleESP.h`): the largest left-right asymmetry within a leg pair (a lifted foot), the knee range, and the largest front-rear shoulder difference (body tilt).

- **wave (`khi`)**: Left-right asymmetry: 129; Front-rear tilt: 144; Decision: disabled; flipped him twice
- **high five (`kfiv`)**: Left-right asymmetry: 146; Front-rear tilt: 96; Decision: disabled
- **scratch (`kscrh`)**: Left-right asymmetry: 141; Front-rear tilt: 60; Decision: disabled
- **shake paw (`kgdb`)**: Left-right asymmetry: 22; Front-rear tilt: 71 (knee to 84); Decision: disabled
- **hop (`kjpF`)**: Left-right asymmetry: 0; Front-rear tilt: 60; Decision: disabled (a jump; off by default already)
- **stretch (`kstr`)**: Left-right asymmetry: 0; Front-rear tilt: 105; Decision: kept, borderline: four feet but a strong lean; used by the wake-up
- **push-ups (`kpu`)**: Left-right asymmetry: 40; Front-rear tilt: 80; Decision: kept, borderline
- **play-bow (`kbuttUp`)**: Left-right asymmetry: 0; Front-rear tilt: 45; Decision: kept
- **nod, shake head, check around, come here, sit, stand, rest**: Left-right asymmetry: 0 to 24; Front-rear tilt: 0 to 60; Decision: kept
- **walk, trot, crawl, walk back**: Left-right asymmetry: gaits; Front-rear tilt: 13 to 26; Decision: kept (walking gaits; trot and crawl untested on this payload)

A kept move that tips him over on hardware goes into `DISABLED_SKILLS` the same way.
