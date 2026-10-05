"""python -m pi_pipeline.power  status | headless | interactive | governor <name> | wifi on|off | leds-off
                               | runtime [list] | runtime add <seconds> | runtime forget <index> | runtime path
                               | runtime test start|status|collect|cancel   (an intentional battery-life test; see runtime_tracker.py)"""
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
    if sub == "test":
        return _runtime_test(t, a[1:])
    if sub in ("unplugged", "plugged"):
        if sub == "unplugged":
            t.arm_now()
            full = t.mean_runtime_s(sources=("test",))
            print("counting from now (this boot only)" + (f"; the warning fires after {0.8 * full / 3600:.2f} h on battery" if full else
                                                        "; no timed-test runtime yet, so no warning"))
        else:
            t.disarm()
            print("charging: the battery warning is paused for this boot")
        return
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
        print(f"mean of counted runs: {mean / 3600:.2f} h" if mean else "no runs recorded yet")
        timed = t.mean_runtime_s(sources=("test",))
        state, secs = t.battery_state()
        now = {"paused": "PAUSED for this boot (you said plugged in; say \"you're unplugged\" to restart the count)",
               "since_unplugged": f"counting since you said unplugged: {(secs or 0) / 3600:.2f} h so far",
               "since_boot": f"counting from boot: {(secs or 0) / 3600:.2f} h so far"}[state]
        print((f"the warning uses timed-test runs only: {timed / 3600:.2f} h, so it fires after {0.8 * timed / 3600:.2f} h on battery; "
               if timed else "the warning uses timed-test runs only: none yet, so it is silent; ") + now)


def _runtime_test(t, a):
    import subprocess
    import sys
    action = a[0] if a else "status"
    if action == "start":
        if not t.arm():
            print("a test is already running on this boot (see `runtime test status`, or `runtime test cancel`)")
            return
        log = open(str(t.path) + ".heartbeat.log", "a")
        p = subprocess.Popen([sys.executable, "-m", "pi_pipeline.power", "runtime", "test", "run"],
                             stdout=log, stderr=log, start_new_session=True)
        t.set_pid(p.pid)
        print("battery test started. Unplug the charger and let the Pi run until the battery dies; power it again afterwards and "
              "the result is recorded (at the next voice-service start, or `runtime test collect`).\n"
              "Start it only from a FULL charge. A clean shutdown or reboot discards the test; `runtime test cancel` ends it by hand.")
    elif action == "run":                      # the heartbeat itself (started by `start`)
        t.run_heartbeat()
    elif action == "collect":
        print(t.collect() or "nothing to collect")
    elif action == "cancel":
        print("test cancelled" if t.cancel() else "no test in progress")
    else:
        cur = t.test()
        if not cur:
            print("no battery test in progress")
        else:
            up = (t.uptime_s() - cur["start_uptime_s"]) if cur.get("boot_id") == t._boot_id() else None
            print(f"test in progress; this boot has run {up / 3600:.2f} h of it" if up is not None
                  else "a test from a previous boot is waiting to be collected (`runtime test collect`)")


if __name__ == "__main__":
    main()
