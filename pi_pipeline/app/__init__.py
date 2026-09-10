"""The integration layer -- the only place that wires everything together with
real I/O.

`behavior/`, `voice/`, `vision/`, `gait/`, `link/`, `power/` are each independent
and mock-testable. This package builds the real sinks and sources for them and
runs them as one program:

- `sinks.build_bindings(link, ...)` -> a `DriverBindings` backed by the serial
  link + `pi_pipeline.power` (the SKILL / STOP / WALK / TURN / HEAD / CHIRP /
  POWER / DIAG effects the behaviour driver emits).
- `sensors.SensorHub` -> the `sensors()` callable `BehaviorRuntime` wants
  (imu_level / imu_stable / held from the IMU stream, person_present from the
  detection feed).
- `__main__` -> `python -m pi_pipeline.app`: the voice loop + the behaviour
  runtime, side by side, mock by default (`--serial` to talk to the robot).
"""
from .sinks import (
    CameraSink, HeadSink, LockedLink, PowerSink, SerialActuatorSink,
    WalkerSink, build_bindings,
)
from .sensors import SensorHub

__all__ = [
    "build_bindings", "SerialActuatorSink", "HeadSink", "WalkerSink",
    "PowerSink", "CameraSink", "LockedLink", "SensorHub",
]
