"""Small control and status commands for the automatic run logs (run on the Pi; the g2floor / g2data aliases call them over ssh).

    python -m pi_pipeline.telemetry surface [LABEL]    show or set the floor G2 is on (hardwood, tile, carpet, ...)
    python -m pi_pipeline.telemetry status             runs captured, size, the newest runs and why they ended
    python -m pi_pipeline.telemetry epochs             the hardware epochs and the one in force now
    python -m pi_pipeline.telemetry label RUN TAG [NOTE..]  label a run with a data type (a person's label): snag_candidate, snag, fall, collision, pickup, steady_walk, short_segment, unfinished
    python -m pi_pipeline.telemetry labels [RUN]       the labels on one run, or the count of each tag across all runs
    python -m pi_pipeline.telemetry exclude RUN WHY..  flag a run so it is never used for fitting (a collision, a pick-up, ...); RUN is its name or a unique part, e.g. 141700
"""
import json
import sys

from . import autolog
from .epochs import epoch_at, load_epochs


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "status"
    if cmd == "surface":
        print(autolog.set_surface(a[1]) if len(a) > 1 else autolog.get_surface())
        return 0
    if cmd == "epochs":
        now = epoch_at()
        for e in load_epochs():
            print(("* " if now and e["id"] == now["id"] else "  ") + f"{e['id']}  from {e['start']}  fit_ok={e.get('fit_ok')}  {e.get('note', '')}")
        return 0
    if cmd == "label":
        from . import labels
        if len(a) < 3:
            print("usage: label RUN TAG [NOTE...]   tags: " + ", ".join(sorted(labels.KNOWN_TAGS)))
            return 2
        try:
            done = labels.add_labels(a[1], [{"tag": a[2], "note": " ".join(a[3:])}], by="user", method="manual")
        except ValueError as e:
            print(e)
            return 2
        print(f"labelled {done}: {a[2]}" if done else f"no single run matches {a[1]!r}")
        return 0 if done else 1
    if cmd == "labels":
        from . import labels
        if len(a) > 1:
            for x in labels.read_labels(a[1]):
                print(f"{x['tag']:15} {x['by']:6} {x['method']:12} conf={x['confidence']} window={x['t0']}..{x['t1']} {x.get('note', '')}")
        else:
            print(labels.summary() or "no labels yet")
        return 0
    if cmd == "exclude":
        if len(a) < 3:
            print("usage: exclude RUN REASON...")
            return 2
        done = autolog.exclude_run(a[1], " ".join(a[2:]))
        print(f"excluded {done}" if done else f"no single run matches {a[1]!r}")
        return 0 if done else 1
    if cmd == "status":
        root = autolog.base_dir()
        sides = autolog.run_sidecars(root)
        print(f"auto run logs: {len(sides)} run(s), {autolog.size_mb(root):.1f} MB in {root}; surface now: {autolog.get_surface()}")
        by: dict[str, int] = {}
        for s in sides:
            try:
                r = json.loads(s.read_text()).get("end_reason") or "running"
            except (OSError, ValueError):
                r = "unreadable"
            by[r] = by.get(r, 0) + 1
        if by:
            print("ended by: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
        bad = [s.stem for s in sides if json.loads(s.read_text()).get("excluded")] if sides else []
        if bad:
            print("excluded from fitting: " + ", ".join(bad))
        from . import labels as _labels
        tagged = _labels.summary(root)
        if tagged:
            print("labels: " + ", ".join(f"{k} {v}" for k, v in sorted(tagged.items())))
        for s in sides[-5:]:
            try:
                d = json.loads(s.read_text())
                print(f"  {s.stem}  {d.get('surface')}  {d.get('epoch')}  {d.get('end_reason')}  {d.get('duration_s')} s")
            except (OSError, ValueError):
                pass
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
