# The picture library: where G2's exploration pictures live

What happens to a picture G2 takes while exploring, which folder holds what, and which parts can be rebuilt. The pictures are local only: `training_data/` is gitignored, nothing is uploaded, and the repository holds none of it. How exploration takes the pictures: [`../guides/exploration-mode.md`](../guides/exploration-mode.md); the plan behind recognition: [`../planned/exploration-object-learning-plan.md`](../planned/exploration-object-learning-plan.md). This is separate from the camera-model training library (`G2_LIB_ROOT`, default `~/Desktop/g2_vision_library`): [`../guides/train-vision-model.md`](../guides/train-vision-model.md).

## The flow

1. **On the Pi.** An exploration session takes survey pictures (240 × 240) at stops, and the voice commands "look" and "name this" take more. Each picture has a JSON sidecar (file, kind, pose, name, time, size, detections, exposure, and how it was named). They are kept in `~/.local/share/g2/explore_pictures/`.
2. **Pull to the Mac.** `g2pics pull` copies them to `~/g2_pictures/explore/`. Wall pictures and the instant contact pictures from a wall hit are kept in separate places and are diagnostics, never training data.
3. **Curate, automatically.** The background loop (`g2bg`, every 30 minutes) runs `tools/g2_curate_auto.sh`, which re-curates everything pulled into `training_data/exploration/auto/` and replaces the previous result only when the new one is complete. Curation scores lighting, contrast and sharpness, sets aside bad and near-duplicate pictures, and **leaves out any picture with a person in it**. `g2picscurate` does the same by hand into a dated folder.
4. **Review and name.** `g2pics` opens the review page ([`README.md`](README.md)): hidden-by-default filtering of bad quality and duplicates, a Name button, an X on each picture (a Trash with Undo).
5. **Promote.** Promoting a labelled picture copies it to `training_data/exploration/promoted/<name>/` and queues it for the robot. The Pi's object gallery learns it under that name automatically: at once when no exploration is running, otherwise at the start of the next session (`vision/promoted_loader.py`). A picture whose look-alike already has a different name is reported as a conflict instead of loaded. Un-promoting does not remove anything from the gallery.

## Folders

| Folder | Holds | Rebuilt? |
|---|---|---|
| `training_data/exploration/auto/` | The current curated set: `keep/survey/<date>/` survey pictures, `keep/named/<name>/` named objects, `contact/` overview thumbnails per group, `manifest.json`, `summary.txt` | Yes, every 30 minutes from `~/g2_pictures/explore` |
| `training_data/exploration/promoted/<name>/` | The labelled pictures you promoted: the training data the gallery learns from | **No**; this is the one to protect |
| `training_data/exploration/<date_time>/` | A manual curation from `g2picscurate`; the first one, from 2026-10-07, holds a few pictures `auto/` no longer has | Not automatically |
| `~/g2_pictures/explore/` | The pulled originals, with the review page's state (`promoted.json`, `unpromoted.json`, `people.json`) | Pull again from the Pi |

Everything under `training_data/` is local. Back up `promoted/` if the pictures matter; it is small.

## Keeping labels clean

A name lives in four places: the picture's sidecar, its `named/<name>/` folder in the pulled pictures, the promotion record, and, once learned, the Pi's gallery. So fix a wrong or misspelled name in the **review page** (select the picture, use Name with the corrected word), never by renaming a folder by hand. A hand-renamed folder would be rebuilt with the old name at the next curation. A name the gallery has already learned stays there after the picture is un-promoted.

Voice naming can mishear (a name like "been fine" or "not what I said I said" came from a mis-transcribed word): check the names on the page after a naming session. Review rules in force: only labelled pictures are promoted, a picture with a person in it is never promoted, and nothing about what is in the house is shared or uploaded.
