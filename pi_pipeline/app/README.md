# App (the whole robot)

`python -m pi_pipeline.app` runs the whole robot as one program: the voice loop and the behavior runtime side by side over one shared serial link. This package is **the only place with real I/O wiring**; every other package takes injected dependencies.

| Module | Role |
|---|---|
| `__main__.py` | Starts the voice loop and the `BehaviorRuntime` together, owns the emergency-stop latch (`--halt`, `--release`, `SIGUSR1`/`SIGUSR2`) and bench mode (`--bench`) |
| `sinks.py` | The real `DriverBindings` sinks, serial and power backed; `build_bindings()` |
| `sensors.py` | `SensorHub`: turns the IMU stream and the detection feed into the small dict of state the behavior driver reads each tick |

Mock by default (no serial, dry-run power); `--serial` talks to the BiBoard; `--trace FILE` logs every command sent. Emergency stop and bench mode: [`../../docs/guides/operating-g2.md`](../../docs/guides/operating-g2.md). The driver and bindings pattern: [`../behavior/README.md`](../behavior/README.md). The voice service that runs at boot is a separate entry point (`python -m pi_pipeline.voice --mode voice`, installed by `install_voice_service.sh`) and does not run this app.
