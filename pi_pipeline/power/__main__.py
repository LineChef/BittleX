"""python -m pi_pipeline.power  status | headless | interactive | governor <name> | wifi on|off | leds-off"""
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
    elif cmd == "leds-off":
        print("\n".join(P.disable_onboard_leds()))
    else:
        print(__doc__); sys.exit(2)


if __name__ == "__main__":
    main()
