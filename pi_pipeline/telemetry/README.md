# telemetry/

Automatic capture of every walk, so real-robot data turns into sim calibration without anyone asking. The full plan and the Mac-side steps (`g2_ingest.py`, `g2_calibrate.py`): [`../../docs/rl/real-data-pipeline.md`](../../docs/rl/real-data-pipeline.md).

| Module | Role |
|---|---|
| `autolog.py` | Every policy walk (and scripted walk) with no explicit `--log` writes `~/g2_runs/auto/<date>/<kind>_<time>.csv` plus a JSON sidecar: kind, hardware epoch, floor, policy, commands, why it ended. It must never stop a walk; `G2_AUTOLOG=off` disables it (the tests do) |
| `epochs.py`, `hardware_epochs.json` | Dated hardware changes. Fits use the current epoch only; the user says when hardware changes |
| `labels.py` | Data-type labels for captured runs (snag, fall, collision, pick-up, steady walk, …) |

```bash
python -m pi_pipeline.telemetry surface [LABEL]       # show or set the floor (hardwood, tile, carpet, …)
python -m pi_pipeline.telemetry status                # runs captured, the newest, and why they ended
python -m pi_pipeline.telemetry epochs                # the hardware epochs and the one in force
python -m pi_pipeline.telemetry label RUN TAG [NOTE]  # label a run (a person's label)
python -m pi_pipeline.telemetry labels [RUN]
python -m pi_pipeline.telemetry exclude RUN WHY       # keep a run out of fitting for good
```

On the Mac the `g2floor` and `g2data` helpers call these over ssh ([`../../docs/guides/shell-helpers.md`](../../docs/guides/shell-helpers.md)).
