"""python -m pi_pipeline.power  status | headless | interactive | governor <name> | wifi on|off | leds-off
                               | runtime [list] | runtime add <seconds> | runtime forget <index> | runtime path"""
from __future__ import annotations

import json
import sys

from . import power as P


def main(argv=None):
    a = (argv or sys.argv[1:]) or ["status"]
    cmd = a[0]
    if cmd == "status":
        print(json.dumps(P.status(), indent=2))
    elif cmd == "headless":
        print(json.dumps(P.apply_headless_profile(), indent=2, default=str))
    elif cmd == "interactive":
        print(json.dumps(P.apply_interactive_profile(), indent=2, default=str))
    elif cmd == "governor" and len(a) > 1:
        print("\n".join(P.set_cpu_governor(a[1])))
    elif cmd == "wifi" and len(a) > 1:
        print(P.set_wifi_power_save(a[1] == "on"))
    elif cmd == "runtime":
        _runtime(a[1:])
    elif cmd == "leds-off":
        print("\n".join(P.disable_onboard_leds()))
    else:
        print(__doc__); sys.exit(2)


def _runtime(a):
    """The Pi's measured runtimes on one charge (see runtime_tracker.py)."""
    from ..config import settings
    from .runtime_tracker import RuntimeTracker
    t = RuntimeTracker(settings.pi_runtime_log)
    sub = a[0] if a else "list"
    if sub == "path":
        print(t.path)
    elif sub == "add" and len(a) > 1:
        t.add_run(float(a[1]), source="manual")
        print(f"added a run of {float(a[1]) / 3600:.2f} h")
    elif sub == "forget" and len(a) > 1:
        print("ignored" if t.forget_run(int(a[1])) else "no such run")
    else:
        runs = t.runs()
        for i, r in enumerate(runs):
            print(f"{i}: {r['runtime_s'] / 3600:5.2f} h  {r.get('source', '?'):9s} {'counted' if r.get('counted', True) else 'IGNORED'}")
        mean = t.mean_runtime_s()
        print(f"mean of counted runs: {mean / 3600:.2f} h  (warns at {0.8 * mean / 3600:.2f} h up)" if mean else "no runs recorded yet")


if __name__ == "__main__":
    main()
