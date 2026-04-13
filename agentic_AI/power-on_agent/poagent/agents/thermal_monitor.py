"""ThermalMonitorThread — Phase 2 thermal safety monitor.

[SG-01] Spawned at Phase 2 start. Uses a SEPARATE SSH connection outside
the agent semaphore pool. Polls thermal_zone*/temp every 5s.

[N-SG-03] Per-zone-type thresholds from config.thermal_zone_thresholds.
Zone types discovered at startup by reading thermal_zone*/type.

On breach: set pause_event → all agents pause BEFORE semaphore acquisition.
After cooldown: clear pause_event (resume) or set abort_event (THERMAL_ABORT).

[H-05] ThermalMonitorThread connection failure → THERMAL_MONITOR_UNAVAILABLE
warning. Run continues WITHOUT thermal monitoring. Never fatal.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from poagent.codes import (
    THERMAL_MONITOR_UNAVAILABLE,
    THERMAL_ABORT,
    THERMAL_BREACH_PAUSING,
    THERMAL_RESUME,
)

log = structlog.get_logger(__name__)


@dataclass
class ThermalSnapshot:
    """Snapshot captured at breach time."""
    timestamp: float
    zone_temps: dict[str, int]   # zone_path → temp_mc
    zone_types: dict[str, str]   # zone_path → zone_type
    breaching_zone: str
    breaching_zone_type: str
    temp_mc: int
    threshold_mc: int
    semaphore_holder_count: int = 0

    @property
    def temp_c(self) -> float:
        return self.temp_mc / 1000.0

    @property
    def threshold_c(self) -> float:
        return self.threshold_mc / 1000.0


class ThermalMonitorThread(threading.Thread):
    """Dedicated thermal monitoring thread for Phase 2.

    [H-05] Uses runner that is a SEPARATE SSH connection, not from the agent pool.
    Construction: connect the runner before passing it in, catch connection errors here.
    """

    def __init__(
        self,
        runner: object,
        pause_event: threading.Event,
        abort_event: threading.Event,
        config: object,
        ssh_semaphore: Optional[threading.Semaphore] = None,
    ) -> None:
        super().__init__(name="ThermalMonitorThread", daemon=True)
        self.runner = runner
        self.pause_event = pause_event
        self.abort_event = abort_event
        self.config = config
        self._ssh_semaphore = ssh_semaphore  # for semaphore_holder_count snapshot
        self._stop_event = threading.Event()
        self.thermal_log: list[tuple[float, dict[str, int]]] = []
        self.snapshots: list[ThermalSnapshot] = []
        self.available = True  # False if setup fails [H-05]
        self.zone_type_map: dict[str, str] = {}  # zone_path → zone_type

    # ── Setup ─────────────────────────────────────────────────────────────

    def _discover_zone_types(self) -> None:
        """[N-SG-03] Read thermal_zone*/type once at startup."""
        try:
            zones = self.runner.glob("/sys/class/thermal/thermal_zone*")  # type: ignore[union-attr]
            for zone in zones:
                type_str = self.runner.read_file(f"{zone}/type").strip()  # type: ignore[union-attr]
                if type_str:
                    self.zone_type_map[zone] = type_str
            log.debug("thermal_zones_discovered", count=len(self.zone_type_map),
                      zones=self.zone_type_map)
        except Exception as exc:
            log.debug("thermal_zone_type_discover_failed", error=str(exc))

    def _threshold_for_zone(self, zone_path: str) -> int:
        """[N-SG-03] Return threshold in millicelsius for a zone."""
        zone_type = self.zone_type_map.get(zone_path, "default")
        thresholds: dict = getattr(self.config, "thermal_zone_thresholds", {})
        # Default values from PRD §3.5
        defaults = {
            "cpu-thermal": 95,
            "gpu-thermal": 95,
            "charger": 110,
            "board": 75,
            "skin": 55,
            "default": 95,
        }
        threshold_c = thresholds.get(zone_type, thresholds.get("default",
                                     defaults.get(zone_type, defaults["default"])))
        return int(threshold_c) * 1000  # → millicelsius

    # ── Thermal read ──────────────────────────────────────────────────────

    def _read_thermal_zones(self) -> dict[str, int]:
        """Read all thermal zones. Returns {zone_path: temp_mc}."""
        result = {}
        try:
            zones = self.runner.glob("/sys/class/thermal/thermal_zone*")  # type: ignore[union-attr]
            for zone in zones:
                raw = self.runner.read_file(f"{zone}/temp")  # type: ignore[union-attr]
                try:
                    result[zone] = int(raw.strip())
                except ValueError:
                    pass
        except Exception as exc:
            log.debug("thermal_read_failed", error=str(exc))
        return result

    # ── Breach handling ───────────────────────────────────────────────────

    def _handle_breach(
        self,
        zone_path: str,
        zone_type: str,
        temp_mc: int,
        threshold_mc: int,
        all_temps: dict[str, int],
    ) -> None:
        """Pause all agents, wait for cooldown, then resume or abort."""
        semaphore_count = 0
        if self._ssh_semaphore is not None:
            semaphore_count = getattr(self._ssh_semaphore, "_value", 0)

        snapshot = ThermalSnapshot(
            timestamp=time.time(),
            zone_temps=all_temps,
            zone_types=dict(self.zone_type_map),
            breaching_zone=zone_path,
            breaching_zone_type=zone_type,
            temp_mc=temp_mc,
            threshold_mc=threshold_mc,
            semaphore_holder_count=semaphore_count,
        )
        self.snapshots.append(snapshot)

        log.warning(
            THERMAL_BREACH_PAUSING,
            zone=zone_path,
            zone_type=zone_type,
            temp_c=round(temp_mc / 1000, 1),
            threshold_c=round(threshold_mc / 1000, 1),
            semaphore_holders=semaphore_count,
        )

        # Signal all agents to pause
        self.pause_event.set()

        cooldown_s: float = getattr(self.config, "thermal_cooldown_s", 60)
        time.sleep(cooldown_s)

        # Re-check all zones after cooldown
        temps_after = self._read_thermal_zones()
        still_hot = any(
            t >= self._threshold_for_zone(z)
            for z, t in temps_after.items()
        )

        if not still_hot:
            log.info(THERMAL_RESUME,
                     zone=zone_path,
                     temp_after_c=round(temps_after.get(zone_path, 0) / 1000, 1))
            self.pause_event.clear()
        else:
            log.error(THERMAL_ABORT,
                      zone=zone_path,
                      temps_after={z: round(t / 1000, 1) for z, t in temps_after.items()})
            self.abort_event.set()

    # ── Thread main loop ──────────────────────────────────────────────────

    def run(self) -> None:
        """Thread main loop. Polls thermal zones until stop() called."""
        # Discover zone types at startup
        try:
            self._discover_zone_types()
        except Exception as exc:
            log.warning(THERMAL_MONITOR_UNAVAILABLE, phase="zone_discovery", error=str(exc))
            self.available = False
            return

        poll_interval: float = getattr(self.config, "thermal_poll_interval_s", 5)

        while not self._stop_event.is_set():
            temps = self._read_thermal_zones()
            if temps:
                self.thermal_log.append((time.time(), temps))

            # Check each zone against its own threshold [N-SG-03]
            breached = False
            for zone_path, temp_mc in temps.items():
                threshold_mc = self._threshold_for_zone(zone_path)
                if temp_mc >= threshold_mc:
                    zone_type = self.zone_type_map.get(zone_path, "unknown")
                    self._handle_breach(zone_path, zone_type, temp_mc, threshold_mc, temps)
                    breached = True
                    break  # One breach pauses all — handle one at a time

            if self.abort_event.is_set():
                break

            if not breached:
                self._stop_event.wait(timeout=poll_interval)

        log.debug("thermal_monitor_stopped")

    def stop(self) -> None:
        """Signal the thread to stop. Call before join()."""
        self._stop_event.set()

    def get_peak_temperature(self) -> Optional[tuple[str, float]]:
        """Return (zone_path, peak_temp_c) from all snapshots."""
        if not self.snapshots:
            return None
        hottest = max(self.snapshots, key=lambda s: s.temp_mc)
        return (hottest.breaching_zone, hottest.temp_c)

    @property
    def had_breach(self) -> bool:
        return len(self.snapshots) > 0

    @property
    def did_abort(self) -> bool:
        return self.abort_event.is_set()


def make_thermal_monitor(
    board_ip: str,
    config: object,
    pause_event: threading.Event,
    abort_event: threading.Event,
    ssh_semaphore: Optional[threading.Semaphore] = None,
) -> ThermalMonitorThread:
    """Create ThermalMonitorThread with its own dedicated SSH connection.

    [H-05] Connection failure → THERMAL_MONITOR_UNAVAILABLE warning.
    Returns a ThermalMonitorThread with available=False if setup fails.
    """
    from poagent.probes.base import ProbeRunner

    try:
        thermal_runner = ProbeRunner(
            domain="thermal_monitor",
            board_ip=board_ip,
            pause_event=pause_event,
            abort_event=abort_event,
            # Thermal monitor uses its OWN semaphore — doesn't compete with agents
            ssh_semaphore=threading.Semaphore(1),
        )
        thermal_runner.via_ssh(
            host=board_ip,
            user=getattr(config, "ssh_user", "root"),
            key_file=getattr(config, "ssh_key_file", None),
            password=getattr(config, "ssh_password", None),
            port=getattr(config, "ssh_port", 22),
        )
        monitor = ThermalMonitorThread(
            runner=thermal_runner,
            pause_event=pause_event,
            abort_event=abort_event,
            config=config,
            ssh_semaphore=ssh_semaphore,
        )
        log.info("thermal_monitor_created", board_ip=board_ip)
        return monitor

    except Exception as exc:
        log.warning(THERMAL_MONITOR_UNAVAILABLE,
                    board_ip=board_ip, error=str(exc),
                    msg="Phase 2 continues without thermal monitoring")
        # Return a non-functional monitor with available=False
        dummy_runner = object()  # will never be used
        monitor = ThermalMonitorThread(
            runner=dummy_runner,
            pause_event=pause_event,
            abort_event=abort_event,
            config=config,
        )
        monitor.available = False
        return monitor
