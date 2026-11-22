# The picture library: where G2's exploration pictures live

What happens to a picture G2 takes while exploring, which folder holds what, and which parts can be rebuilt. The pictures are local only: `training_data/` is gitignored, nothing is uploaded, and the repository holds none of it. How exploration takes the pictures: [`../guides/exploration-mode.md`](../guides/exploration-mode.md). This is separate from the camera-model training library (`G2_LIB_ROOT`, default `~/Desktop/G2Memory/g2_vision_library`): [`../guides/train-vision-model.md`](../guides/train-vision-model.md).

The flow
--------

1. On the Pi: An exploration session takes survey pictures (240 × 240) at stops, and the voice commands "look" and "name this" take more. Each picture has a JSON sidecar (file, kind, pose, name, time, size, detections, exposure, and how it was named). They are kept in `~/.local/share/g2/explore_pictures/`.
2. Pull to the Mac: `g2pics pull` copies them to `~/Desktop/G2Memory/g2_pictures/explore/`. Wall pictures and the instant contact pictures from a wall hit are kept in separate places and are diagnostics, never training data.
3. Curate: `g2groom` at the start of a session (or `g2bg`, the optional 30-minute loop) runs `tools/g2_curate_auto.sh`, which re-curates everything pulled into `training_data/exploration/auto/` and replaces the previous result only when the new one is complete. Curation scores lighting, contrast and sharpness, sets aside bad and near-duplicate pictures, and **leaves out any picture with a person in it**. `g2picscurate` does the same by hand into a dated folder.
4. Review and name: `g2pics` opens the review page ([`README.md`](README.md)): hidden-by-default filtering of bad quality and duplicates, a Name button, an X on each picture (a Trash with Undo).
5. Promote: Promoting a labelled picture copies it to `training_data/exploration/promoted/<name>/` and queues it for the robot. The Pi's object gallery learns it under that name automatically: at once when no exploration is running, otherwise at the start of the next session (`vision/promoted_loader.py`). A picture whose look-alike already has a different name is reported as a conflict instead of loaded. Un-promoting does not remove anything from the gallery.

Folders
-------

- `training_data/exploration/auto/`: Holds: The current curated set: `keep/survey/<date>/` survey pictures, `keep/named/<name>/` named objects, `contact/` overview thumbnails per group, `manifest.json`, `summary.txt`; Rebuilt?: Yes, every 30 minutes from `~/Desktop/G2Memory/g2_pictures/explore`
- Class cap: no class keeps more than 250 pictures. The chase's picture saver skips poor pictures (dark, blown out, flat, blurry) and near-twins of the last few it saved, adds at most 40 a session, and at the cap replaces the lowest-scored picture only with a better one. The nightly pass (`g2_curate_auto.sh`, `tools/curate_class.py --all-promoted`) does the same for the Mac copy, moves the dropped ones to `G2Memory/_pruned/` instead of deleting, and never trims a picture a person named by hand.
- Grooming: at the start of every hardware session `g2groom` syncs what is due from the Pi, then runs `tools/g2_groom.py`, which keeps each auto-saved class under the named pictures to its best 250, collapses near-twins in the behaviour picture folders (`bout`, `watch`, `stream`, `seen`, `contact`, `explore/survey`) and caps the training classes under `promoted/`. Only those folders are ever touched: calibration pictures (the wall shots and ring, lift, step and claw calibration, anything beside a labels file) and hand-named or promoted pictures are never groomed. It applies when `~/.local/share/g2/groom.json` holds `{"apply": true}` (`g2groom on`); the extras are moved to `G2Memory/_pruned/` and deleted after 14 days, and the same removal goes to the Pi's own trash, which the Pi empties after 14 days too.
- `training_data/exploration/promoted/<name>/`: Holds: The labelled pictures you promoted: the training data the gallery learns from; Rebuilt?: **No**; this is the one to protect
- `training_data/exploration/<date_time>/`: Holds: A manual curation from `g2picscurate`; the first one holds a few pictures `auto/` no longer has; Rebuilt?: Not automatically
- `~/Desktop/G2Memory/g2_pictures/explore/`: Holds: The pulled originals, with the review page's state (`promoted.json`, `unpromoted.json`, `people.json`); Rebuilt?: Pull again from the Pi

Everything under `training_data/` is local. Back up `promoted/` if the pictures matter; it is small.

Wall pictures
-------------

Three kinds of wall picture exist, each in its own place, and they do different jobs. Walls are background to the object pipeline, so a wall is never an object class in the review page's Pictures tab.

- Calibration sets: `~/g2_wall_calibration/<set>/` on the Pi, copied to `~/Desktop/G2Memory/g2_pictures/wall_calibration/<set>/` by the sync. These are the only pictures that build the wall calibration. They are taken by hand with `g2calpic SET INCHES`, with the camera at a ruler-measured distance from a flat wall, and nothing else writes there. Each set has a hash manifest, its files are read-only, the picture tools refuse to delete, trash or restore them, the groom never touches them, and `tools/g2_cal_verify.py` pins each set on the Mac the first time it is seen and reports any change, missing file or added file afterwards.
- Ordinary shots: `~/g2_wall_pics` on the Pi and the loose `shot_*` files in `g2_pictures/wall/` on the Mac, taken by hand with `g2look`. The 43 from before the claw camera are kept as history; they are not a usable yardstick for the claw camera.
- Roam pictures: `wall/ring/` on the Mac, from the Pi's `~/.local/share/g2/wall_pics`. The wall estimator saves one for every near or blocked look and one clear look every five minutes during any exploration, roam or goal, and the Pi keeps only the newest 20 (the Mac keeps them all). They are for checking the detector, not for calibrating it: they have no measured distance, and they are mostly the detector's own near claims. Label them in the Walls tab (`nothing` for no wall within about a foot) and score a detector on them with `python -m pi_pipeline.vision.wall_replay DIR --score`.

Keeping labels clean
--------------------

A name lives in four places: the picture's sidecar, its `named/<name>/` folder in the pulled pictures, the promotion record, and, once learned, the Pi's gallery. So fix a wrong or misspelled name in the **review page** (select the picture, use Name with the corrected word), never by renaming a folder by hand. A hand-renamed folder would be rebuilt with the old name at the next curation. A name the gallery has already learned stays there after the picture is un-promoted.

Voice naming can mishear (a name like "been fine" or "not what I said I said" came from a mis-transcribed word): check the names on the page after a naming session. Review rules in force: only labelled pictures are promoted, a picture with a person in it is never promoted, and nothing about what is in the house is shared or uploaded.

Grooming and cleanup
--------------------

The galleries are kept from growing without end by one routine, `g2groom`, which runs at the start of every hardware session and can be run anytime (`g2groom`, or the cleanup skill). It does these things in order:

1. Syncs what is due from the Pi (`tools/g2_sync.sh run`), which also sends the edits queued from the review page.
2. Caps each auto-saved class under the named pictures (the chase's green ball pictures) at 250: the best pictures stay by quality, near-duplicates collapse, and the rest are spread over distance and bearing.
3. Collapses near-duplicates in the behaviour picture folders (`bout`, `watch`, `stream`, `seen`, `contact`, `explore/survey`).
4. Caps the training classes under `promoted/` at 250 (`tools/curate_class.py --all-promoted`).
5. Moves what it removes to `~/Desktop/G2Memory/_pruned/groom_<date>/` (deleted after 14 days) and queues the same removal for the Pi, whose own trash is restorable and empties itself after 14 days.

What it never touches:

- Recognition sets: `~/Desktop/G2Memory/g2_pictures/recognition_sets/<set>/` on the Mac only (the cylinder and basket pictures for the finders are the first, `cylinder_basket`): a copy of the pictures with their labels, hash-checked against a pinned manifest and made read-only like the wall calibration sets (`python3 tools/g2_cal_verify.py --root ~/Desktop/G2Memory/g2_pictures/recognition_sets`; the sync and the session preflight run it). The Pi keeps its own originals. The clean-up refuses any folder with "recog" in its name.
- The Calibration tab of the review page (`g2pics`): every picture set that exists to calibrate or recognise something, in two dropdowns, read-only (no delete, no relabel). The first dropdown is the object: Cylinder, Basket, Ball, Wall or Claw. The second is the set for that object: for the cylinder its distance series, other faces, on its side, bearing checks, throw setup and held in the claw (good and bad grip); for the basket its distance series and bearing checks; for the ball the hand-taken calibration sessions and the no-ball examples; for the wall the wall shot sets and the wall calibration sets; for the claw its sessions. Ordinary look pictures, the auto-saved ball chase pictures and everything else stay out. The hand-taken `session_*` pictures are never groomed. The lift, step and localizer calibration folders are to be added.
- Calibration and recognition pictures: the wall shots and the wall ring, the lift, step and claw calibration, `wall_new1`, the localizer check, and anything beside a labels file. The groom works from an allowlist of folders, so a new folder is never groomed until it is added on purpose.
- People pictures (the vision library, the person captures) and hand-named or promoted pictures.

It applies only when `~/.local/share/g2/groom.json` holds `{"apply": true}` (`g2groom on`; `g2groom off` makes it report only). The chase's picture saver on the Pi applies the same limits as the pictures are taken: it skips dark, blown-out, flat and blurry pictures and near-twins of the last few saved, adds at most 40 a session, and at 250 replaces the lowest-scored picture only with a better one.

Other cleanup tools, each a dry run by default:

- `python tools/find_unreadable.py`: pictures that cannot be decoded even when a few missing end bytes are tolerated (the camera often cuts a picture short by a few bytes, and those are fine). `--delete` removes them and queues the Pi's trash.
- `python tools/gallery_report.py`: near-duplicates and size against a budget for the local galleries, with contact sheets in `~/Desktop/G2Memory/_dedup_reports/`; `--apply` moves the extras aside.
- `python tools/curate_class.py FOLDER`: keeps one class under a cap.
- The Pictures tab of the review page shows the gallery's size against its budget.

A sync from the Pi does not undo the grooming: the pull copies without deleting, and a groomed picture is no longer in the Pi's pictures folder (it is in the Pi's trash), so it is not copied back. The behaviour folders on the Mac (`bout`, `watch`, `stream` and the others) are one-time copies that the sync never refreshes, and the wall pictures it does refresh are calibration pictures that the grooming never touches. The order matters when the Pi was off during a groom: the queued removals are sent at the start of the next sync, before it pulls.

To undo a removal: move the picture back from `~/Desktop/G2Memory/_pruned/` on the Mac, and on the Pi restore it from its trash (`python -m pi_pipeline.vision.exploration_pictures restore PATH`, or `pi_pipeline.vision.claw_pictures` for the behaviour pictures).

The far-ball class: `training_data/exploration/promoted/greenball-far/` holds pictures where the ball is 20 pixels or smaller across (about 4 to 5 feet away), labelled from the existing green ball pictures. It is local until it is promoted to the robot's gallery.

