# Utilities

Small helpers shared across the Pi code.

| Module | Role | Wired in? |
|---|---|---|
| `disk.py` | Warns once when the SD card passes a threshold, then reminds every few hours | yes |
| `tidy.py` | At voice-service start, deletes old diagnostic session folders (`~/g2_logs`) and walk logs (`~/g2_runs`); `G2_TIDY_DAYS=0` turns it off | yes |
| `supervisor.py` | Keeps a long-running worker thread alive: restarts it when it raises, returns or stops heart-beating, with exponential backoff and a give-up ceiling; all decisions in a pure, fake-clock-testable `WatchdogPolicy` | **no**: built and tested, no runtime module uses it yet (backlog item B27). The voice service as a whole is already restarted by systemd |
