"""Sensors & Misc domain probe implementations.

Key PRD constraints:
- [N-SG-11] PSCI suspend: test only with CONFIG_PM_TEST_SUSPEND=y check first.
- Thermal zone probe provides per-zone temps for ThermalMonitorThread context.
"""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe

log = structlog.get_logger(__name__)

DOMAIN = "sensors_misc"


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="Thermal zone temperatures and types", timeout=15.0)
class ThermalZoneProbe(ProbeBase):
    """Read all thermal zone temperatures and types."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rc, tz_dirs = runner.exec_command("ls /sys/class/thermal/ 2>/dev/null | grep thermal_zone")
        zones = tz_dirs.strip().split() if rc == 0 else []

        zone_data: dict = {}
        overtemp_zones: list[str] = []

        for tz in zones[:20]:
            base = f"/sys/class/thermal/{tz}"
            rc, tz_type = runner.exec_command(f"cat {base}/type 2>/dev/null")
            rc2, tz_temp = runner.exec_command(f"cat {base}/temp 2>/dev/null")

            tz_name = tz_type.strip() if rc == 0 else tz
            temp_mc = int(tz_temp.strip()) if rc2 == 0 and tz_temp.strip().lstrip("-").isdigit() else None
            temp_c = temp_mc / 1000 if temp_mc is not None else None

            # Default overtemp threshold: 85°C (355mK)
            threshold_c = 85.0
            if board_profile:
                tz_specs = getattr(board_profile, "thermal_zones", {})
                if tz_name in tz_specs:
                    threshold_c = tz_specs[tz_name].get("threshold_c", 85.0)

            status = "ok"
            if temp_c is not None and temp_c >= threshold_c:
                status = "overtemp"
                overtemp_zones.append(tz)

            zone_data[tz] = {
                "type": tz_name,
                "temp_c": temp_c,
                "threshold_c": threshold_c,
                "status": status,
            }

            # Thermal trip points
            rc3, trips = runner.exec_command(
                f"cat {base}/trip_point_*/temp {base}/trip_point_*/type 2>/dev/null | head -10"
            )
            if rc3 == 0 and trips.strip():
                zone_data[tz]["trips"] = trips.strip()[:100]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(overtemp_zones) == 0,
            data={"thermal_zones": zone_data, "overtemp_zones": overtemp_zones},
            message=(
                f"Thermal overtemp: {', '.join(overtemp_zones)}" if overtemp_zones
                else f"Thermal: {len(zones)} zone(s), all within limits"
            ),
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="hwmon sensor values (voltage/current/fan/temp)", timeout=15.0)
class HwmonProbe(ProbeBase):
    """Read hwmon sensor values: temp, voltage, current, fan."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rc, hwmon_dirs = runner.exec_command("ls /sys/class/hwmon/ 2>/dev/null")
        hwmon_list = hwmon_dirs.strip().split() if rc == 0 else []

        sensor_data: dict = {}

        for hwmon in hwmon_list[:8]:
            base = f"/sys/class/hwmon/{hwmon}"
            rc, name = runner.exec_command(f"cat {base}/name 2>/dev/null")
            chip_name = name.strip() if rc == 0 else hwmon

            sensors: dict = {}

            # Temperature sensors
            rc, temps = runner.exec_command(f"cat {base}/temp*_input 2>/dev/null 2>&1")
            if rc == 0 and temps.strip():
                for i, val in enumerate(temps.strip().split(), 1):
                    if val.lstrip("-").isdigit():
                        sensors[f"temp{i}_c"] = int(val) / 1000

            # Voltage sensors (in*_input µV → mV)
            rc, volts = runner.exec_command(f"cat {base}/in*_input 2>/dev/null 2>&1")
            if rc == 0 and volts.strip():
                for i, val in enumerate(volts.strip().split(), 1):
                    if val.isdigit():
                        sensors[f"in{i}_mv"] = int(val)

            # Fan sensors (rpm)
            rc, fans = runner.exec_command(f"cat {base}/fan*_input 2>/dev/null 2>&1")
            if rc == 0 and fans.strip():
                for i, val in enumerate(fans.strip().split(), 1):
                    if val.isdigit():
                        sensors[f"fan{i}_rpm"] = int(val)

            sensor_data[chip_name] = sensors

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data={"hwmon_sensors": sensor_data},
            message=f"hwmon: {len(hwmon_list)} chip(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="IIO ADC/IMU device scan", timeout=20.0)
class IIOProbe(ProbeBase):
    """Scan IIO subsystem for ADC and IMU devices."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rc, iio_devs = runner.exec_command("ls /sys/bus/iio/devices/ 2>/dev/null")
        devices = iio_devs.strip().split() if rc == 0 else []

        if not devices:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No IIO devices found",
            )

        device_data: dict = {}
        for dev in devices[:8]:
            base = f"/sys/bus/iio/devices/{dev}"
            rc, name = runner.exec_command(f"cat {base}/name 2>/dev/null")
            dev_name = name.strip() if rc == 0 else dev

            rc, channels = runner.exec_command(f"ls {base}/ 2>/dev/null | grep 'in_'")
            channel_list = channels.strip().split() if rc == 0 else []

            device_data[dev] = {
                "name": dev_name,
                "channels": channel_list[:10],
            }

            # Read first available channel
            if channel_list:
                ch = channel_list[0]
                rc, val = runner.exec_command(f"cat {base}/{ch} 2>/dev/null")
                if rc == 0:
                    device_data[dev]["sample_value"] = val.strip()

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data={"iio_devices": device_data},
            message=f"IIO: {len(devices)} device(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="Battery/fuel gauge state", timeout=15.0)
class BatteryProbe(ProbeBase):
    """Read battery/fuel gauge state from power_supply sysfs."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        rc, psy_devs = runner.exec_command("ls /sys/class/power_supply/ 2>/dev/null")
        psy_list = psy_devs.strip().split() if rc == 0 else []

        if not psy_list:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No power supply devices found",
            )

        psy_data: dict = {}
        for psy in psy_list[:4]:
            base = f"/sys/class/power_supply/{psy}"
            info: dict = {}

            for attr in ["type", "status", "capacity", "voltage_now", "current_now", "health"]:
                rc, val = runner.exec_command(f"cat {base}/{attr} 2>/dev/null")
                if rc == 0 and val.strip():
                    info[attr] = val.strip()

            psy_data[psy] = info

        batteries = {k: v for k, v in psy_data.items() if v.get("type") == "Battery"}
        critical = [k for k, v in batteries.items() if v.get("capacity", "100").isdigit() and int(v["capacity"]) < 5]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(critical) == 0,
            data={"power_supplies": psy_data, "critical_batteries": critical},
            message=f"Battery: {len(batteries)} battery/batteries, {len(critical)} critical",
        )


@register_probe(
    DOMAIN, tier=ProbeTier.SLOW,
    description="PSCI suspend/resume test [N-SG-11]",
    timeout=60.0,
)
class SuspendProbe(ProbeBase):
    """Test PSCI suspend/resume if CONFIG_PM_TEST_SUSPEND is available [N-SG-11].

    Only runs with --allow-destructive-tests AND CONFIG_PM_TEST_SUSPEND enabled.
    """

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        config = getattr(board_profile, "_config", None)
        allow_destructive = getattr(config, "allow_destructive_tests", False) if config else False

        if not allow_destructive:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "allow_destructive_tests=False"},
                message="Suspend test skipped (requires --allow-destructive-tests)",
            )

        # Check CONFIG_PM_TEST_SUSPEND [N-SG-11]
        rc, pm_test = runner.exec_command("cat /sys/power/pm_test 2>/dev/null")
        if rc != 0 or not pm_test.strip():
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "CONFIG_PM_TEST_SUSPEND not enabled"},
                message="Suspend test skipped: CONFIG_PM_TEST_SUSPEND not available",
            )

        # pm_test available: run suspend with 'timers' test mode (safest)
        rc, _ = runner.exec_command("echo timers > /sys/power/pm_test 2>/dev/null")
        if rc != 0:
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"skipped": True, "reason": "cannot set pm_test=timers"},
                message="Suspend test skipped: cannot configure pm_test",
            )

        # Trigger suspend (returns after test completes)
        rc, suspend_out = runner.exec_command(
            "echo mem > /sys/power/state 2>&1",
            timeout=30,
        )

        # Restore pm_test to none
        runner.exec_command("echo none > /sys/power/pm_test 2>/dev/null")

        # Check dmesg for suspend errors
        rc2, dmesg_suspend = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'suspend|resume.*fail|pm.*error' | tail -10"
        )
        suspend_errors = []
        if rc2 == 0:
            suspend_errors = [l for l in dmesg_suspend.strip().splitlines()
                              if any(w in l.lower() for w in ("fail", "error", "abort"))]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=rc == 0 and len(suspend_errors) == 0,
            data={
                "suspend_rc": rc,
                "suspend_output": suspend_out.strip()[:200],
                "suspend_errors": suspend_errors[:5],
            },
            message=(
                f"Suspend: {len(suspend_errors)} error(s) in dmesg" if suspend_errors
                else "Suspend/resume cycle completed"
            ),
        )
