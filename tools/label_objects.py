#!/usr/bin/env python3
"""Review and label the B20 object-recognition gallery (`docs/behavior-ideas.md`
B20, `pi_pipeline/vision/object_gallery.py`).

The gallery recognises objects by visual similarity, not by name -- naming an
entry is a separate, optional, human step (see the module docstring). This is
that step, done locally: nothing here uploads or publishes anything, matching
the same "personal photos of things in the house stay off any external
service" rule as `training_data/`.

    python tools/label_objects.py generate <gallery_dir>            # writes review.html
    #   ... open review.html locally, fill in fields, click "Download labels.json" ...
    python tools/label_objects.py apply <gallery_dir> <labels.json>  # writes the gallery back

`generate` defaults to unlabeled entries only (`--all` to include named ones
too, e.g. to fix a typo or add a note later). `apply` treats every entry in
the downloaded JSON as authoritative for its fields -- a blank name stays
unnamed, `"discard": true` deletes the entry AND its crop image files.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from pi_pipeline.vision.object_gallery import ObjectGallery  # noqa: E402

INDEX_NAME = "gallery.json"


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def cmd_generate(args: argparse.Namespace) -> None:
    gdir = pathlib.Path(args.gallery_dir)
    gallery = ObjectGallery.load(gdir / INDEX_NAME)
    entries = [e for e in gallery.entries.values() if args.all or not e.labeled]
    entries.sort(key=lambda e: e.last_seen, reverse=True)  # most recent first

    if not entries:
        print("nothing to review" + ("" if args.all else " (try --all to include named entries)"))
        return

    cards = []
    for e in entries:
        imgs = "".join(
            f'<img src="{_html_escape(f)}" loading="lazy">' for f in e.crop_files
        ) or "<p class='none'>(no saved crop)</p>"
        cards.append(f"""
  <div class="card" data-id="{e.id}">
    <div class="thumbs">{imgs}</div>
    <div class="meta">
      <code>{e.id}</code> -- {e.sample_count} sample(s),
      first seen {e.first_seen:.0f}, last seen {e.last_seen:.0f}
    </div>
    <label>Name <input type="text" class="name" value="{_html_escape(e.name or '')}"></label>
    <label>Note <textarea class="note">{_html_escape(e.note or '')}</textarea></label>
    <label class="chk"><input type="checkbox" class="complete" {'checked' if e.locked else ''}>
      Complete -- stop collecting more samples of this</label>
    <label class="chk"><input type="checkbox" class="discard">
      Discard -- this isn't a useful entry (junk trigger, blur, etc.)</label>
  </div>""")

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Object gallery review</title>
<style>
  body {{ font: 14px system-ui, sans-serif; background: #1c1a16; color: #f1ede4;
         margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; }}
  .card {{ background: #262219; border: 1px solid #3a3527; border-radius: 8px;
          padding: 14px 16px; margin-bottom: 16px; max-width: 640px; }}
  .thumbs img {{ max-height: 140px; margin: 0 8px 8px 0; border-radius: 4px; }}
  .meta {{ color: #b7ae9e; font-size: 12px; margin-bottom: 8px; }}
  label {{ display: block; margin-top: 8px; }}
  label.chk {{ display: flex; align-items: center; gap: 6px; }}
  input[type=text], textarea {{ width: 100%; box-sizing: border-box; margin-top: 2px;
                                background: #14120f; color: #f1ede4;
                                border: 1px solid #3a3527; border-radius: 4px; padding: 6px; }}
  textarea {{ min-height: 40px; }}
  .none {{ color: #6b6656; font-style: italic; }}
  button {{ margin-top: 20px; padding: 10px 18px; font-size: 14px; cursor: pointer;
           background: #e8944a; border: none; border-radius: 6px; color: #14120f;
           font-weight: 600; }}
  #status {{ margin-top: 10px; color: #b7ae9e; }}
</style></head>
<body>
<h1>Object gallery review -- {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}</h1>
<p>Fill in what you want, then download the labels file and run
<code>label_objects.py apply {gdir} labels.json</code>.</p>
{''.join(cards)}
<button id="dl">Download labels.json</button>
<div id="status"></div>
<script>
document.getElementById('dl').addEventListener('click', function () {{
  var out = {{}};
  document.querySelectorAll('.card').forEach(function (card) {{
    var id = card.dataset.id;
    out[id] = {{
      name: card.querySelector('.name').value.trim() || null,
      note: card.querySelector('.note').value.trim() || null,
      complete: card.querySelector('.complete').checked,
      discard: card.querySelector('.discard').checked
    }};
  }});
  var blob = new Blob([JSON.stringify(out, null, 2)], {{type: 'application/json'}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels.json';
  a.click();
  document.getElementById('status').textContent = 'downloaded -- now run: label_objects.py apply '
    + {json.dumps(str(gdir))} + ' ~/Downloads/labels.json';
}});
</script>
</body></html>"""

    out = gdir / "review.html"
    out.write_text(html)
    print(f"wrote {out}  ({len(entries)} entries)")
    print(f"open it locally (file://{out.resolve()}), fill in fields, download labels.json")


def cmd_apply(args: argparse.Namespace) -> None:
    gdir = pathlib.Path(args.gallery_dir)
    index_path = gdir / INDEX_NAME
    gallery = ObjectGallery.load(index_path)
    labels = json.loads(pathlib.Path(args.labels_json).read_text())

    named = noted = completed = reopened = discarded = 0
    skipped = []
    for eid, fields in labels.items():
        if eid not in gallery.entries:
            skipped.append(eid)
            continue
        if fields.get("discard"):
            crops = gallery.discard(eid)
            for c in crops:
                p = gdir / c
                if p.exists():
                    p.unlink()
            discarded += 1
            continue
        name, note = fields.get("name"), fields.get("note")
        if name:
            gallery.set_name(eid, name, note)
            named += 1
        elif note is not None:
            gallery.entries[eid].note = note
            noted += 1
        if fields.get("complete"):
            gallery.mark_complete(eid)
            completed += 1
        else:
            if gallery.entries[eid].locked:
                gallery.mark_incomplete(eid)
                reopened += 1

    gallery.save(index_path)
    print(f"applied: {named} named, {noted} notes only, {completed} flagged complete, "
         f"{reopened} reopened, {discarded} discarded")
    if skipped:
        print(f"skipped {len(skipped)} id(s) not found in the gallery: {skipped}")
    print(f"saved {index_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="write a local HTML review page")
    g.add_argument("gallery_dir")
    g.add_argument("--all", action="store_true",
                   help="include already-named entries too (default: unlabeled only)")
    g.set_defaults(func=cmd_generate)

    a = sub.add_parser("apply", help="write reviewed labels back into the gallery")
    a.add_argument("gallery_dir")
    a.add_argument("labels_json")
    a.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
