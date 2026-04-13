"""Low-Speed Interface domain probes.

Covers: I2C bus speed/hang, UART, SPI, GPIO, CAN, TLMM pinmux.
"""

from poagent.probes.lowspeed_interface.probes import (
    I2CProbe,
    UARTProbe,
    SPIProbe,
    GPIOProbe,
    CANProbe,
)

__all__ = ["I2CProbe", "UARTProbe", "SPIProbe", "GPIOProbe", "CANProbe"]
