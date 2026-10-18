"""python -m pi_pipeline.attachments status | list | use NAME | save ATTACHMENT POLICY [--trim T] [--payload P] [--note N]

    status   the fitted attachment and the gait it will run (and why)
    list     every attachment, its firmware model and its saved gaits
    use      set the fitted attachment on this machine (the state file); restart the voice service afterwards (g2attach does both)
    save     make POLICY the attachment's current gait (edits gait_profiles.json in the repo: commit it, then deploy)
"""
import argparse
import sys

from . import ATTACHMENTS, current, gait_for, load_profiles, register, use


def _status() -> int:
    att = current()
    g = gait_for(att)
    print(f"attachment: {att} ({ATTACHMENTS[att].description})")
    print(f"gait: {g.why}")
    if g.path:
        print(f"  policy {g.path}" + (f", trim {g.trim}" if g.trim else ", trim: the policy default"))
    return 0


def _list() -> int:
    prof = load_profiles()
    for name, a in ATTACHMENTS.items():
        fw = " or ".join(a.firmware_models) or "any"
        print(f"{name}: {a.description}; firmware {fw}")
        p = prof.get(name, {})
        print(f"  sim payload: {p.get('payload_profile') or 'not set'}")
        cur = p.get("current")
        print(f"  current: {cur['policy']} (trim {cur.get('trim') or 'default'}, saved {cur.get('saved')})" if cur
              else "  current: none saved (runs the legacy DEFAULT_POLICY)")
        for e in reversed(p.get("history", [])):
            print(f"  earlier: {e['policy']} (trim {e.get('trim') or 'default'}, saved {e.get('saved')})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pi_pipeline.attachments")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("list")
    u = sub.add_parser("use")
    u.add_argument("name", choices=list(ATTACHMENTS))
    s = sub.add_parser("save")
    s.add_argument("attachment", choices=list(ATTACHMENTS))
    s.add_argument("policy")
    s.add_argument("--trim", default=None)
    s.add_argument("--payload", default=None, help="the sim payload profile the policy was trained on (e.g. pod)")
    s.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.cmd in (None, "status"):
        return _status()
    if a.cmd == "list":
        return _list()
    if a.cmd == "use":
        use(a.name)
        print(f"attachment set to {a.name}")
        for step in ATTACHMENTS[a.name].checklist:
            print(f"  - {step}")
        return _status()
    if a.cmd == "save":
        register(a.attachment, a.policy, trim=a.trim, payload_profile=a.payload, note=a.note)
        print(f"saved {a.policy} as the current gait for {a.attachment}; commit pi_pipeline/attachments/gait_profiles.json and deploy")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
