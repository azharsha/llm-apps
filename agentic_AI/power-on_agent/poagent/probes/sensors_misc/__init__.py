"""Sensors & Misc domain probes.

Covers: thermal zones, hwmon sensors, IIO ADC/IMU, battery/fuel gauge, PSCI suspend.
"""

from poagent.probes.sensors_misc.probes import (
    ThermalZoneProbe,
    HwmonProbe,
    IIOProbe,
    BatteryProbe,
    SuspendProbe,
)

__all__ = ["ThermalZoneProbe", "HwmonProbe", "IIOProbe", "BatteryProbe", "SuspendProbe"]
