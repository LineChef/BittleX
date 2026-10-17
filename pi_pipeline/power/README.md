# Power

The Pi's power levers and everything about batteries. Design and measurements: [`../../docs/hardware/pi-power.md`](../../docs/hardware/pi-power.md). Operator view: [`../../docs/guides/operating-g2.md`](../../docs/guides/operating-g2.md). Thresholds and switches: [`../../docs/guides/settings-switches.md`](../../docs/guides/settings-switches.md).

| Module | Role |
|---|---|
| `power.py` | Three idle levers with no autonomy risk: disable unused peripherals (LEDs), Wi-Fi power-save, CPU governor. Degrades to a dry-run print off the Pi |
| `battery.py` | G2's low-battery watch: reads the 2-cell pack voltage with the firmware `P` command, decides low and critical, alerts. Also read under load by the walk loop |
| `status.py` | What G2 says when asked about his power: percent, never volts |
| `runtime_tracker.py` | Measures how long the Pi lasts on a charge (an intentional timed test) and warns near the end of that runtime; the PiSugar S has no readout |
| `sleep_watch.py` | Power-saving sleep after a rest with no activity (a sigh, then a yawn on waking); default after 5 minutes (`G2_SLEEP_AFTER_S`) |
| `power_log.py` | An always-on power diary (start and stop, sleep and wake, heartbeats), one flushed JSON line per event |

```bash
python -m pi_pipeline.power status                  # peripherals, Wi-Fi power-save, governor
python -m pi_pipeline.power headless | interactive  # power profiles
python -m pi_pipeline.power governor <name> | wifi on|off | leds-off
python -m pi_pipeline.power stats | log [N]         # sleeps and wakes; the last N power-log lines
python -m pi_pipeline.power runtime [list]          # measured full-charge runs and their mean
python -m pi_pipeline.power runtime test start|status|collect|cancel
```
