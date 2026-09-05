"""Pi power-management helpers. See docs/research/pi-power.md and power.py."""
from __future__ import annotations

from .power import (
    BOOT_CONFIG_LINES,
    apply_headless_profile,
    apply_interactive_profile,
    disable_onboard_leds,
    get_cpu_governor,
    get_wifi_power_save,
    set_cpu_governor,
    set_wifi_power_save,
    status,
)

__all__ = [
    "status", "apply_headless_profile", "apply_interactive_profile",
    "set_cpu_governor", "get_cpu_governor", "set_wifi_power_save",
    "get_wifi_power_save", "disable_onboard_leds", "BOOT_CONFIG_LINES",
]
