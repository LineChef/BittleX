# Place memory plan (B11): G2 learns which room he is in and how rooms connect

Agreed with the user 2026-10-10: **rooms** (not finer spots), tag the existing pictures by hand, collect more pictures in 2 to 3 rooms. Idea and history: [`../behavior-ideas.md`](../behavior-ideas.md) B11. Where the work stands: [`../STATUS.md`](../STATUS.md).

## Design

- **A room is a set of saved views**, not one picture. At floor height a spot looks different in every direction, and timed left/right looks are off, so recognition asks which room's saved pictures look most like the one just taken.
- **A survey stop records**: the picture embedding (`vision/embedder.py`), the 5-slice wall-distance profile (`vision/wall_distance.py`), the detector labels and any named objects recognised (`vision/recognizer.py`), the IMU yaw, and the leg that led to it (seconds walked, heading change, why it ended).
- **Chaining:** the room guess is a vote over the last 3 to 5 stops, never one picture (consecutive stops are almost always in the same room; this is the defence against two similar corners).
- **Rooms are named by the user** ("this is the kitchen" by voice, and the Room button in `g2pics`); G2 never invents a room name.
- **The map links rooms, not coordinates.** A change of the voted room across one leg becomes a link (hallway to kitchen, about N legs). Yaw restarts every session, so a direction is only kept relative to a landmark.
- **All local on the Pi, no API calls.** The work happens at a survey stop (G2 standing still, at most once per 15 s), so it does not add to the late ticks while walking. Place facts reach Claude through the normal memory facts.
- **Storage:** P1 writes `place_stops.jsonl` beside the exploration pictures (so `g2pics pull` brings it to the Mac, and it stays apart from the memory database); P2 decides whether places move into the database.

## Phases and gates

| Phase | What | Gate |
|---|---|---|
| **P0** | Test on the saved pictures: rooms set by hand in `g2pics`, `python tools/eval_rooms.py` | 3-stop vote picks the right room >= 75% on a returning visit (other days only), with the histogram embedder. If it fails: a learned image model (a download: ask first, CLAUDE.md security protocol) |
| **P1** (built 2026-10-10, not yet deployed; `behavior/place_log.py`) | Record only: exploration writes stops and legs; behavior unchanged | A real session gives a complete chain; no extra late ticks; tests pass |
| **P2** | "Where are you?": naming rooms by voice, the vote over recent stops, a local spoken answer ("I think the kitchen" / "not sure yet"); Places view in `g2pics` | Right room >= 80% over 2 sessions in at least 2 rooms |
| **P3** | The map: room links from transitions, "the hallway leads to the kitchen" facts, rooms attached to the existing "the dog is often to the left" notes | Links match the house as the user would draw it |
| **P4** | "Go to the kitchen" (later) | Needs a closed-loop turn and wall avoidance trusted on several wall types (both open) |

## Phase P0: how to run it

1. `g2pics pull`, then `g2pics`: on the Pictures tab, the **Room** button on a picture (or **Set the room of all N** in a group header) sets its room; **Show only the N without a room** finds what is left. Rooms are kept on the Mac in `~/g2_pictures/explore/rooms.json`, by picture file name (so naming a picture does not lose it).
2. `python tools/eval_rooms.py` (add `--embedder onnx:/path/model.onnx` to compare a learned model). It needs 2+ rooms; the honest "returning visit" test also needs a room seen on 2+ days.
3. **More pictures:** one roam in each of 2 to 3 rooms (kitchen, hallway, living room), on different days if possible, then pull and tag.

## Risks

- Perceptual aliasing (similar corners): the vote over stops, plus the wall profile as a second clue.
- Light changes through the day: several visits per room; the "other days only" test measures this.
- Furniture moves: each saved view carries a visit count and last-seen time, and old views fade (P2).
- Only 42 survey pictures exist (4 days, mostly the kitchen): P0 may say "need more data" before it says pass or fail.
