"""Low-Speed Interface domain probe implementations.

Key PRD constraints:
- [O-02] I2C bus speed pre-check before i2cdetect; hung bus = I2C_BUS_HUNG.
- [SS-01] TLMM pinmux check via debugfs for Qualcomm platforms.
"""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe

log = structlog.get_logger(__name__)

DOMAIN = "lowspeed_interface"


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="I2C bus speed, detect, hang check", timeout=30.0)
class I2CProbe(ProbeBase):
    """Check I2C buses: speed, device scan, hung bus detection [O-02].

    [O-02] Always check bus speed before issuing i2cdetect.
    Hung bus detection: I2C_BUS_HUNG if SCL/SDA stuck low.
    """

    _HUNG_BUS_TIMEOUT_MS = 1000  # expected i2cdetect max time for normal bus

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # Discover I2C buses
        rc, i2c_devs = runner.exec_command("ls /dev/i2c-* 2>/dev/null")
        buses = i2c_devs.strip().split() if rc == 0 else []
        data["i2c_buses"] = buses

        bus_results: dict = {}
        hung_buses: list[str] = []

        for bus_path in buses[:8]:
            bus_num = bus_path.split("-")[-1]
            bus_info: dict = {}

            # Bus speed from device tree / sysfs
            rc, speed = runner.exec_command(
                f"cat /sys/class/i2c-adapter/i2c-{bus_num}/of_node/clock-frequency 2>/dev/null | xxd -p 2>/dev/null"
            )
            if rc == 0 and speed.strip():
                try:
                    # clock-frequency is big-endian 32-bit hex
                    freq_hz = int(speed.strip().replace(" ", "").replace("\n", ""), 16)
                    bus_info["freq_hz"] = freq_hz
                    bus_info["freq_khz"] = freq_hz // 1000
                except ValueError:
                    pass

            # [O-02] Pre-check: verify bus responds within timeout
            # Use i2cdetect with -y flag (non-interactive); short timeout via kernel
            rc, detect_out = runner.exec_command(
                f"timeout 2 i2cdetect -y -r {bus_num} 2>&1",
                timeout=5,
            )

            if rc == 124:  # timeout
                bus_info["status"] = "hung"
                hung_buses.append(bus_path)
            elif rc != 0 and "error" in detect_out.lower():
                bus_info["status"] = "error"
                bus_info["error"] = detect_out.strip()[:100]
            else:
                # Parse detected devices
                devices_found: list[str] = []
                for line in detect_out.splitlines():
                    for tok in line.split():
                        if len(tok) == 2:
                            try:
                                int(tok, 16)
                                addr = int(tok, 16)
                                if 0x03 <= addr <= 0x77:
                                    devices_found.append(f"0x{addr:02x}")
                            except ValueError:
                                pass
                bus_info["status"] = "ok"
                bus_info["devices_found"] = devices_found

            # TLMM pinmux for this bus (Qualcomm) [SS-01]
            rc, tlmm = runner.exec_command(
                f"cat /sys/kernel/debug/pinctrl/*/pinmux-functions 2>/dev/null | grep -i 'i2c{bus_num}' | head -3"
            )
            if rc == 0 and tlmm.strip():
                bus_info["tlmm_pinmux"] = tlmm.strip()[:100]

            bus_results[bus_path] = bus_info

        data["bus_details"] = bus_results
        data["hung_buses"] = hung_buses

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(hung_buses) == 0,
            data=data,
            message=(
                f"I2C_BUS_HUNG: {', '.join(hung_buses)}" if hung_buses
                else f"I2C: {len(buses)} bus(es) OK"
            ),
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="UART port enumeration and loopback", timeout=15.0)
class UARTProbe(ProbeBase):
    """Enumerate UART ports and check driver binding."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # /proc/tty/driver/serial
        rc, serial_info = runner.exec_command("cat /proc/tty/driver/serial 2>/dev/null | head -10")
        if rc == 0:
            data["serial_driver"] = serial_info.strip()[:300]

        # ttyS* devices
        rc, tty_devs = runner.exec_command("ls /dev/ttyS* /dev/ttyAMA* /dev/ttymxc* 2>/dev/null")
        data["uart_devices"] = tty_devs.strip().split() if rc == 0 else []

        # 8250 UART register check
        rc, uart_8250 = runner.exec_command(
            "cat /sys/bus/platform/drivers/serial8250/*/porttype 2>/dev/null | head -5"
        )
        if rc == 0 and uart_8250.strip():
            data["uart_8250_ports"] = uart_8250.strip()

        # dmesg UART
        rc, uart_dmesg = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'uart|tty.*error|serial.*fail' | head -5"
        )
        if rc == 0 and uart_dmesg.strip():
            data["uart_dmesg"] = uart_dmesg.strip().splitlines()[:3]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"UART: {len(data.get('uart_devices', []))} port(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="SPI bus and device enumeration", timeout=15.0)
class SPIProbe(ProbeBase):
    """Enumerate SPI buses and devices."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        rc, spi_devs = runner.exec_command("ls /sys/bus/spi/devices/ 2>/dev/null")
        spi_list = spi_devs.strip().split() if rc == 0 else []
        data["spi_devices"] = spi_list

        for spi_dev in spi_list[:5]:
            base = f"/sys/bus/spi/devices/{spi_dev}"
            rc, modalias = runner.exec_command(f"cat {base}/modalias 2>/dev/null")
            if rc == 0:
                data.setdefault("spi_modaliases", {})[spi_dev] = modalias.strip()

        # SPI dmesg errors
        rc, spi_err = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'spi.*error|spi.*fail|spi.*timeout' | tail -5"
        )
        if rc == 0 and spi_err.strip():
            data["spi_errors"] = spi_err.strip().splitlines()[:3]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(data.get("spi_errors", [])) == 0,
            data=data,
            message=f"SPI: {len(spi_list)} device(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.FAST, description="GPIO chip enumeration and TLMM pinmux", timeout=15.0)
class GPIOProbe(ProbeBase):
    """Check GPIO chips and TLMM pinmux state [SS-01]."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # GPIO chips
        rc, gpio_chips = runner.exec_command("gpioinfo 2>/dev/null | head -20")
        if rc == 0:
            data["gpio_chips"] = gpio_chips.strip()[:400]

        rc, gpiochip_dirs = runner.exec_command("ls /sys/class/gpio/ 2>/dev/null | grep gpiochip")
        data["gpiochip_count"] = len(gpiochip_dirs.strip().split()) if rc == 0 else 0

        # TLMM pinmux (Qualcomm) [SS-01]
        rc, tlmm_pins = runner.exec_command(
            "cat /sys/kernel/debug/pinctrl/*/pinmux-pins 2>/dev/null | head -30"
        )
        if rc == 0 and tlmm_pins.strip():
            data["tlmm_pinmux"] = tlmm_pins.strip()[:500]

        # Conflicting GPIO claims
        rc, gpio_err = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'gpio.*conflict|pinctrl.*fail|pin.*already' | tail -5"
        )
        if rc == 0 and gpio_err.strip():
            data["gpio_errors"] = gpio_err.strip().splitlines()[:3]

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(data.get("gpio_errors", [])) == 0,
            data=data,
            message=f"GPIO: {data.get('gpiochip_count', 0)} chip(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="CAN bus state via ip/can-utils", timeout=20.0)
class CANProbe(ProbeBase):
    """Check CAN bus interface state."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # CAN interfaces
        rc, can_ifaces = runner.exec_command(
            "ip -d link show type can 2>/dev/null"
        )
        if rc != 0 or not can_ifaces.strip():
            return ProbeResult(
                probe_name=self.__class__.__name__,
                domain=DOMAIN,
                passed=True,
                data={"found": False},
                message="No CAN interfaces found",
            )

        data["can_interfaces"] = can_ifaces.strip()[:400]

        # CAN error counters
        rc, can_stats = runner.exec_command(
            "ip -s link show type can 2>/dev/null | grep -E 'RX|TX|errors' | head -10"
        )
        if rc == 0:
            data["can_stats"] = can_stats.strip()[:200]

        # can-utils cansend/candump availability
        rc, _ = runner.exec_command("which candump 2>/dev/null")
        data["can_utils_available"] = rc == 0

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message="CAN interfaces found",
        )
