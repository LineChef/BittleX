"""Power-management helpers for the Pi Zero 2 W (PiSugar-fed).

Three idle-state levers with zero autonomy risk (see docs/research/pi-power.md):
  1. disable unused peripherals   (onboard LEDs now; audio/camera-LED via boot config)
  2. Wi-Fi power-save toggle       (on when headless -- +~200 ms/API call, breaks streaming)
  3. CPU governor                  (ondemand -- NOT powersave; verify no control-tick jitter)

Everything degrades to a dry-run print when the sysfs / tools aren't present
(i.e. not on a Pi), so this is safe to import and unit-test on a laptop.

    python -m pi_pipeline.power status
    python -m pi_pipeline.power headless      # power-save profile for autonomous ops
    python -m pi_pipeline.power interactive   # full-power profile while a human is connected
"""
from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

# Boot-config lines (need a reboot; can't be set at runtime). Add to
# /boot/firmware/config.txt -- see docs/research/pi-set-up.md.
BOOT_CONFIG_LINES = [
    "dtparam=audio=off",          # no 3.5mm / HDMI audio in use
    "dtoverlay=disable-bt",       # already set for the serial port; harmless if duplicated
    "disable_splash=1",
    "dtparam=act_led_trigger=none",
    "dtparam=act_led_activelow=off",
    "camera_auto_detect=1",       # keep -- the Grove cam is external, but leave CSI probe on
]

_WIFI_IF = "wlan0"
_GOV_GLOB = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
_LED_GLOB = "/sys/class/leds/*/brightness"


def _on_pi() -> bool:
    return Path("/sys/firmware/devicetree/base/model").exists() or Path(_GOV_GLOB.split("*")[0]).exists()


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return p.returncode == 0, (p.stdout or p.stderr).strip()
    except (FileNotFoundError, PermissionError, subprocess.SubprocessError) as e:
        return False, repr(e)


# --- 1. unused peripherals ---------------------------------------------------
def disable_onboard_leds(dry_run: bool | None = None) -> list[str]:
    """Turn the Pi's onboard ACT/PWR LEDs off (runtime). Returns actions taken."""
    dry = (not _on_pi()) if dry_run is None else dry_run
    acts = []
    for path in glob.glob(_LED_GLOB):
        acts.append(f"echo 0 > {path}")
        if not dry:
            try:
                Path(path).write_text("0")
            except (PermissionError, OSError) as e:
                acts[-1] += f"  [FAILED: {e}]"
    if not acts:
        acts.append("(no /sys/class/leds/*/brightness -- not on a Pi)")
    return acts


# --- 2. Wi-Fi power save ----------------------------------------------------
def set_wifi_power_save(on: bool, dry_run: bool | None = None) -> tuple[bool, str]:
    dry = (not shutil.which("iw")) if dry_run is None else dry_run
    cmd = ["iw", "dev", _WIFI_IF, "set", "power_save", "on" if on else "off"]
    if dry:
        return True, "DRY-RUN: " + " ".join(cmd)
    return _run(cmd)


def get_wifi_power_save() -> str:
    ok, out = _run(["iw", "dev", _WIFI_IF, "get", "power_save"])
    return out if ok else "unknown"


# --- 3. CPU governor ------------------------------------------------------------
def set_cpu_governor(name: str = "ondemand", dry_run: bool | None = None) -> list[str]:
    """Set the scaling governor on every core. Use 'ondemand' (fast ramp), NOT
    'powersave' -- powersave pins the clock low and will drop control ticks."""
    if name == "powersave":
        raise ValueError("refusing 'powersave' -- it drops 80 Hz control ticks; use 'ondemand'")
    dry = (not glob.glob(_GOV_GLOB)) if dry_run is None else dry_run
    acts = []
    for path in glob.glob(_GOV_GLOB):
        acts.append(f"echo {name} > {path}")
        if not dry:
            try:
                Path(path).write_text(name)
            except (PermissionError, OSError) as e:
                acts[-1] += f"  [FAILED: {e}]"
    if not acts:
        acts.append(f"DRY-RUN: would set governor '{name}' (no cpufreq sysfs -- not on a Pi)")
    return acts


def get_cpu_governor() -> str:
    g = glob.glob(_GOV_GLOB)
    if not g:
        return "unknown"
    try:
        vals = {Path(p).read_text().strip() for p in g}
        return next(iter(vals)) if len(vals) == 1 else f"mixed:{sorted(vals)}"
    except OSError:
        return "unknown"


# --- profiles --------------------------------------------------------------
def apply_headless_profile(dry_run: bool | None = None) -> dict:
    """Autonomous ops, no human connected: max runtime."""
    return {
        "leds": disable_onboard_leds(dry_run),
        "wifi_power_save": set_wifi_power_save(True, dry_run),
        "governor": set_cpu_governor("ondemand", dry_run),
    }


def apply_interactive_profile(dry_run: bool | None = None) -> dict:
    """Human connected (SSH / streaming): responsiveness over runtime."""
    return {
        "wifi_power_save": set_wifi_power_save(False, dry_run),
        "governor": set_cpu_governor("ondemand", dry_run),
    }


def status() -> dict:
    return {
        "on_pi": _on_pi(),
        "cpu_governor": get_cpu_governor(),
        "wifi_power_save": get_wifi_power_save(),
        "boot_config_lines_needed": BOOT_CONFIG_LINES,
    }
