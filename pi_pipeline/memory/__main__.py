"""Inspect and edit G2's memory.  No API key needed.

    python -m pi_pipeline.memory facts                 # list durable facts
    python -m pi_pipeline.memory log [N]               # last N exchanges (default 20)
    python -m pi_pipeline.memory search "cat"          # relevance search the log
    python -m pi_pipeline.memory recall "tell me about my cat"   # what recall() would inject
    python -m pi_pipeline.memory remember "Their name is Sam."  # add a fact by hand
    python -m pi_pipeline.memory forget "Their name is Sam."    # remove a fact (text or id)
    python -m pi_pipeline.memory export [--scrub]      # dump everything (--scrub redacts before sharing)
    python -m pi_pipeline.memory wipe --yes            # clear everything
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..config import settings
from .memory import Memory
from .store import Store, scrub_text

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _private_terms() -> list[str]:
    """Names to redact for `export --scrub`: the .gitprivacy-terms denylist (dev
    machine) plus the names in G2_BONDS (works on the Pi, where that file isn't
    deployed)."""
    terms: list[str] = []
    f = _REPO_ROOT / ".gitprivacy-terms"
    if f.exists():
        terms += [ln.strip() for ln in f.read_text().splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    for entry in getattr(settings, "bonds_spec", "").split(";"):
        name = entry.split(":", 1)[0].strip()
        if name:
            terms.append(name)
    return terms


def main() -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.memory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("facts")
    p_log = sub.add_parser("log"); p_log.add_argument("n", type=int, nargs="?", default=20)
    p_se = sub.add_parser("search"); p_se.add_argument("query")
    p_re = sub.add_parser("recall"); p_re.add_argument("query")
    p_rem = sub.add_parser("remember"); p_rem.add_argument("fact")
    p_fo = sub.add_parser("forget"); p_fo.add_argument("needle")
    p_ex = sub.add_parser("export"); p_ex.add_argument("--scrub", action="store_true")
    p_wipe = sub.add_parser("wipe"); p_wipe.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    db = settings.memory_db_path
    print(f"[{db}]")

    if args.cmd == "facts":
        rows = Store(db).list_facts()
        for r in rows:
            print(f"  #{r['id']}  {r['fact']}   (added {r['ts'][:10]})")
        print(f"  {len(rows)} fact(s)")

    elif args.cmd == "log":
        for r in reversed(Store(db).recent_exchanges(args.n)):
            act = f"  [{r['actions']}]" if r["actions"] else ""
            print(f"  {r['ts'][:19]}\n    you: {r['user_text']}\n    g2 : {r['assistant_text']}{act}")

    elif args.cmd == "search":
        for r in Store(db).search_exchanges(args.query, limit=10):
            print(f"  {r['ts'][:10]}  you: {r['user_text']}\n              g2 : {r['assistant_text']}")

    elif args.cmd == "recall":
        ctx = Memory(settings).recall(args.query)
        print("\n--- context recall() would inject ---")
        print(ctx or "  (nothing)")

    elif args.cmd == "remember":
        print("  added" if Store(db).add_fact(args.fact) else "  already known / empty")

    elif args.cmd == "forget":
        print(f"  removed {Store(db).forget_fact(args.needle)} fact(s)")

    elif args.cmd == "export":
        st = Store(db)
        terms = _private_terms() if args.scrub else []
        clean = (lambda s: scrub_text(s, terms)) if args.scrub else (lambda s: s)
        if args.scrub:
            print("# scrubbed: date/time spans -> [when], private terms -> [name]."
                  " Skim before sharing -- this is a courtesy filter, not a guarantee.\n")
        print("## facts")
        for r in st.list_facts():
            print(f"- {clean(r['fact'])}")
        print("\n## exchanges")
        for r in reversed(st.recent_exchanges(10_000)):
            print(f"- ({r['ts'][:10]}) you: {clean(r['user_text'])}")
            print(f"                g2:  {clean(r['assistant_text'])}")

    elif args.cmd == "wipe":
        if not args.yes:
            print("  refusing without --yes")
            return
        Store(db).wipe()
        print("  memory cleared")


if __name__ == "__main__":
    main()
