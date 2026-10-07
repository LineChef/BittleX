"""Small control and status commands for the automatic run logs (run on the Pi; the g2floor / g2data aliases call them over ssh).

    python -m pi_pipeline.telemetry surface [LABEL]    show or set the floor G2 is on (hardwood, tile, carpet, ...)
    python -m pi_pipeline.telemetry status             runs captured, size, the newest runs and why they ended
    python -m pi_pipeline.telemetry epochs             the hardware epochs and the one in force now
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
    if cmd == "status":
        root = autolog.base_dir()
        sides = sorted(root.glob("*/*.json"))
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
