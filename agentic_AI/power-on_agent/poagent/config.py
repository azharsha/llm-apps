"""PoAgent configuration dataclass.

Loaded once at startup. All runtime state is passed explicitly —
no module-level mutable globals.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class PoAgentConfig:
    """Full configuration for a PoAgent run.

    Fields map directly to PRD §§3–16. Defaults are the PRD-mandated values.
    """

    # ── Target board ──────────────────────────────────────────────────────
    host: str = ""
    port: int = 22
    ssh_user: str = "root"
    ssh_key_file: str = "~/.ssh/id_rsa"
    # ssh_password: never stored — read from POAGENT_SSH_PASSWORD at connect time
    board_name: str = "unknown"

    # ── Serial transport ──────────────────────────────────────────────────
    serial_port: str = ""
    serial_baud: int = 115200
    baud_autodetect: bool = True
    serial_user: str = "root"
    # serial_password: never stored — read from POAGENT_SERIAL_PASSWORD
    serial_login_timeout: int = 30
    rtscts: bool = False
    xonxoff: bool = False

    # ── SSH / semaphore ───────────────────────────────────────────────────
    # [H-05] default 3 — ThermalMonitorThread uses +1 dedicated slot outside pool
    # [LAST-C1] lowered to 2 at runtime when watchdog_keepalive == "auto"
    max_concurrent_ssh: int = 3
    ssh_keepalive_interval_s: int = 30  # [N-CG-05]

    # ── Gate timeouts ─────────────────────────────────────────────────────
    boot_wait_timeout: int = 180  # Gate 2 poll limit (seconds)
    min_uptime_seconds: int = 10  # Gate 4 minimum uptime
    init_type: Literal["auto", "systemd", "sysvinit", "busybox"] = "auto"
    gate4_sentinel_path: str = "/tmp/poagent_ready"
    gate4_sentinel_stable_count: int = 3  # [FINAL-S4]

    # ── BMC / PDU (Gate 1) ────────────────────────────────────────────────
    bmc_host: str = ""
    pdu_host: str = ""
    pdu_outlet: int = 0

    # ── Rail Sanity Barrier ───────────────────────────────────────────────
    barrier_pre_read_settle_ms: int = 500  # [N-CG-01] settle delay before first PMBus read

    # ── IRQ storm ─────────────────────────────────────────────────────────
    irq_storm_threshold: int = 1000  # IRQs/second PER CPU per line
    irq_storm_sample_ms: int = 1000  # sampling window in ms
    per_cpu_threshold: bool = True   # [N-SG-02] normalize by online CPU count

    # ── Thermal monitor ───────────────────────────────────────────────────
    thermal_poll_interval_s: int = 5
    cooldown_s: int = 60
    thermal_zone_thresholds: dict[str, int] = field(default_factory=lambda: {
        "cpu-thermal": 95,
        "gpu-thermal": 95,
        "charger": 110,
        "board": 75,
        "skin": 55,
        "default": 95,
    })

    # ── Agent timeouts ────────────────────────────────────────────────────
    agent_timeout_seconds: int = 120

    # ── Watchdog [FINAL-S1] ───────────────────────────────────────────────
    watchdog_keepalive: Literal["auto", "warn", "disable"] = "warn"
    watchdog_conflict_threshold_s: int = 120
    watchdog_keepalive_interval_s: int = 10

    # ── memtester [FINAL-S2] ──────────────────────────────────────────────
    memtester_max_mb: int = 256
    memtester_fraction: float = 0.6  # fraction of available RAM to use

    # ── C probe deployment [H-04] ─────────────────────────────────────────
    min_deploy_memory_mb: int = 64

    # ── USB-C PD ──────────────────────────────────────────────────────────
    pd_contract_timeout_s: int = 5
    pd_retry_interval_s: int = 2

    # ── Kernel panic detection [R-01] ─────────────────────────────────────
    kern_log_fallback: bool = True  # also grep /var/log/kern.log if present

    # ── Claude API [N-PG-04] ──────────────────────────────────────────────
    model: str = "claude-sonnet-4-6"
    api_max_retries: int = 5
    api_max_wait_s: int = 120

    # ── Storage ───────────────────────────────────────────────────────────
    allow_destructive_tests: bool = False
    unsafe_shutdown_mode: Literal["ci_mode", "production_mode"] = "ci_mode"

    # ── Log rotation [FINAL-H2] ───────────────────────────────────────────
    log_retention_days: int = 30
    log_max_total_mb: int = 500
    log_size_rotation_exempt: bool = False   # [LAST-S3]
    log_active_atime_window_s: int = 3600    # [LAST-S3]

    # ── Gate 4 sentinel ───────────────────────────────────────────────────
    # overlay validation mode [FINAL-S5]
    overlay_confirm_mode: Literal["interactive", "pre_validated", "strict"] = "interactive"
    confirm_overlay_flag_set: bool = False

    # ── Checkpoint / resume ───────────────────────────────────────────────
    run_id: str = ""
    force_resume: bool = False

    # ── Batch mode ────────────────────────────────────────────────────────
    fleet_workers: int = 8

    # ── Runtime state (mutable — not frozen) ─────────────────────────────
    # These are set during the run; NOT config file values.
    boot_context: dict = field(default_factory=dict)
    debugfs_available: bool = True

    # Shared threading events (set by orchestrator at startup)
    _pause_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _abort_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _wdt_keepalive_thread: object = field(default=None, repr=False)

    # SSH semaphore (set at orchestrator startup based on max_concurrent_ssh)
    _ssh_semaphore: threading.Semaphore = field(
        default=None, repr=False  # type: ignore[assignment]
    )

    def __post_init__(self) -> None:
        # Validate that passwords are NOT in config (they must come from env)
        if not self._ssh_semaphore:
            self._ssh_semaphore = threading.Semaphore(self.max_concurrent_ssh)

    def lower_concurrent_ssh_for_watchdog(self) -> None:
        """[LAST-C1] Lower max_concurrent_ssh to 2 when watchdog_keepalive=auto.

        2 (semaphore) + 1 (thermal) + 1 (wdt) = 4, within Dropbear MaxSessions=4.
        """
        self.max_concurrent_ssh = 2
        self._ssh_semaphore = threading.Semaphore(2)


def load_config(**overrides: object) -> PoAgentConfig:
    """Load configuration with environment variable defaults.

    Environment variables take precedence over dataclass defaults.
    Explicit kwargs take precedence over environment variables.
    """
    env_model = os.environ.get("POAGENT_MODEL", "claude-sonnet-4-6")
    cfg = PoAgentConfig(model=env_model)
    for key, value in overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
