"""WatchdogKeepaliveThread — feeds watchdog during diagnostic run.

[FINAL-S1] Dedicated SSH connection outside semaphore pool.
Writes "w" (keepalive) via dd every interval_s seconds.

[LAST-C1] SSH failure is CRITICAL — sets abort_event immediately.
Unlike ThermalMonitorThread (WARNING only), a failed keepalive on an
active NOWAYOUT watchdog guarantees a board reboot in ≤wdt_timeout_s.

[LAST-S1] SELinux pre-check: reads /proc/self/attr/current before first write.
Non-unconfined_t context → WATCHDOG_SELINUX_BLOCKED CRITICAL + abort.
Uses dd (not echo redirect) for writes — dd returns EPERM; shell redirect masks it.
"""

from __future__ import annotations

import threading
from typing import Optional

import structlog

from poagent.codes import (
    WATCHDOG_KEEPALIVE_FAILED,
    WATCHDOG_SELINUX_BLOCKED,
    WATCHDOG_RUN_CONFLICT,
    WATCHDOG_NOWAYOUT_CANNOT_DISABLE,
)

log = structlog.get_logger(__name__)


class WatchdogKeepaliveThread(threading.Thread):
    """Background thread that writes keepalive to /dev/watchdog* every interval_s.

    Uses a dedicated SSH connection — NEVER competes with agent semaphore pool.
    """

    daemon = True  # dies automatically on main process exit

    def __init__(
        self,
        runner: object,
        device: str,
        interval_s: int = 10,
        abort_event: Optional[threading.Event] = None,
        wdt_timeout_s: Optional[int] = None,
        nowayout: bool = False,
    ) -> None:
        super().__init__(name="WatchdogKeepalive")
        self.runner = runner
        self.device = device
        self.interval_s = interval_s
        self.abort_event = abort_event
        self.wdt_timeout_s = wdt_timeout_s
        self.nowayout = nowayout
        self._stop_event = threading.Event()
        self.available = True

    @staticmethod
    def _check_selinux_context(runner: object) -> Optional[str]:
        """[LAST-S1] Return SELinux context string if available, None otherwise."""
        result = runner.exec(  # type: ignore[union-attr]
            "cat /proc/self/attr/current 2>/dev/null || echo ''",
            timeout=3.0, probe_name="watchdog_selinux_check"
        )
        ctx = result.stdout.strip()
        return ctx if ctx else None

    def _verify_first_write(self) -> bool:
        """[LAST-S1] Use dd to detect EPERM (shell redirect masks EPERM).

        Returns True if write succeeded.
        """
        result = self.runner.exec(  # type: ignore[union-attr]
            f"printf 'w' | dd of={self.device} bs=1 count=1 2>/dev/null",
            timeout=3.0, probe_name="watchdog_first_write"
        )
        return result.returncode == 0

    def _emit_critical(self, code: str, msg: str) -> None:
        log.error(code, msg=msg, device=self.device)

    def run(self) -> None:
        """Thread main loop."""
        # [LAST-S1] SELinux pre-check
        ctx = self._check_selinux_context(self.runner)
        if ctx and "unconfined_t" not in ctx:
            self._emit_critical(
                WATCHDOG_SELINUX_BLOCKED,
                f"SSH context '{ctx}' cannot write to {self.device} under SELinux enforcing. "
                f"Falling back to watchdog_keepalive=warn behavior.",
            )
            self.available = False
            if self.abort_event:
                self.abort_event.set()
            return

        # [LAST-S1] Verify first write via dd (not shell redirect)
        if not self._verify_first_write():
            self._emit_critical(
                WATCHDOG_SELINUX_BLOCKED,
                f"dd write to {self.device} returned non-zero (EPERM likely). "
                f"SELinux policy blocks watchdog writes from this SSH context.",
            )
            self.available = False
            if self.abort_event:
                self.abort_event.set()
            return

        log.info("watchdog_keepalive_started",
                 device=self.device,
                 interval_s=self.interval_s,
                 nowayout=self.nowayout)

        # Main keepalive loop
        while not self._stop_event.wait(timeout=self.interval_s):
            try:
                result = self.runner.exec(  # type: ignore[union-attr]
                    f"printf 'w' | dd of={self.device} bs=1 count=1 2>/dev/null",
                    timeout=3.0, probe_name="watchdog_keepalive_write"
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"dd write returned rc={result.returncode}"
                    )
                log.debug("watchdog_keepalive_write_ok", device=self.device)

            except Exception as exc:
                self.available = False
                remaining = (
                    f" Board will reboot in ≤{self.wdt_timeout_s}s."
                    if self.wdt_timeout_s else ""
                )
                nowayout_note = (
                    " NOWAYOUT set — watchdog cannot be stopped."
                    if self.nowayout else ""
                )
                self._emit_critical(
                    WATCHDOG_KEEPALIVE_FAILED,
                    f"SSH connection to {self.device} lost ({exc}).{nowayout_note}"
                    f"{remaining} Setting abort_event — checkpointing and exiting.",
                )
                if self.abort_event:
                    self.abort_event.set()
                break

        log.debug("watchdog_keepalive_stopped", device=self.device)

    def stop(self) -> None:
        """Signal the thread to stop. Call before join() at run end."""
        self._stop_event.set()


def check_watchdog_state(runner: object, config: object) -> dict:
    """[FINAL-S1] Detect active watchdog and assess run-conflict risk.

    Returns watchdog_state dict for boot_context.
    """
    state: dict = {
        "device": None,
        "timeout_s": None,
        "nowayout": None,
        "watchdogd_pid": None,
        "conflict": False,
        "dmesg_wdt": [],
    }

    # Step 1: Detect WDT device
    dev_check = runner.exec(  # type: ignore[union-attr]
        "ls /dev/watchdog0 /dev/watchdog 2>/dev/null | head -1",
        timeout=3.0, probe_name="watchdog_dev_check"
    )
    if not dev_check.stdout.strip():
        return state  # No watchdog device
    state["device"] = dev_check.stdout.strip().splitlines()[0]

    # Step 2: Read timeout
    wdctl = runner.exec(  # type: ignore[union-attr]
        f"wdctl -o timeout {state['device']} 2>/dev/null || "
        f"cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null || echo unknown",
        timeout=3.0, probe_name="watchdog_timeout"
    )
    raw = wdctl.stdout.strip()
    if raw.isdigit():
        state["timeout_s"] = int(raw)

    # Step 3: Check NOWAYOUT (WDIOF_MAGICCLOSE 0x0100 absent → NOWAYOUT)
    nowayout_result = runner.exec(  # type: ignore[union-attr]
        "cat /sys/class/watchdog/watchdog0/options 2>/dev/null || echo unknown",
        timeout=3.0, probe_name="watchdog_nowayout"
    )
    opts_raw = nowayout_result.stdout.strip()
    if opts_raw not in ("", "unknown"):
        try:
            opts = int(opts_raw, 16)
            state["nowayout"] = not bool(opts & 0x0100)  # WDIOF_MAGICCLOSE
        except ValueError:
            pass

    # Step 4: Check for running watchdogd
    wdd = runner.exec(  # type: ignore[union-attr]
        "pgrep -x watchdogd 2>/dev/null || echo ''",
        timeout=3.0, probe_name="watchdog_pid"
    )
    pid = wdd.stdout.strip()
    state["watchdogd_pid"] = int(pid) if pid.isdigit() else None

    # Step 5: Extract relevant dmesg lines
    wdt_dmesg = runner.exec(  # type: ignore[union-attr]
        "dmesg 2>/dev/null | grep -iE 'watchdog|wdt' | tail -10",
        timeout=3.0, probe_name="watchdog_dmesg"
    )
    state["dmesg_wdt"] = [l.strip() for l in wdt_dmesg.stdout.splitlines() if l.strip()]

    # Step 6: Assess conflict
    run_budget_s: int = getattr(config, "watchdog_conflict_threshold_s", 120)
    wdt_active = state["device"] is not None
    no_daemon = state["watchdogd_pid"] is None
    short_timeout = (
        state["timeout_s"] is not None and state["timeout_s"] <= run_budget_s
    )
    state["conflict"] = wdt_active and no_daemon and short_timeout

    if state["conflict"]:
        log.warning(WATCHDOG_RUN_CONFLICT,
                    device=state["device"],
                    timeout_s=state["timeout_s"],
                    nowayout=state["nowayout"])

    return state


def handle_watchdog_conflict(
    runner: object,
    config: object,
    wdt_state: dict,
    abort_event: Optional[threading.Event] = None,
) -> Optional[WatchdogKeepaliveThread]:
    """[FINAL-S1] Handle detected watchdog conflict.

    Returns WatchdogKeepaliveThread if mode==auto, else None.
    Raises RuntimeError if mode==warn (abort run).
    """
    mode: str = getattr(config, "watchdog_keepalive", "warn")

    if mode == "warn":
        log.error(
            WATCHDOG_RUN_CONFLICT,
            device=wdt_state["device"],
            timeout_s=wdt_state["timeout_s"],
            msg=(
                f"Watchdog active on {wdt_state['device']} with "
                f"{wdt_state['timeout_s']}s timeout, no watchdogd running. "
                f"Board will reboot mid-run. Disable WDT or extend timeout "
                f"beyond {getattr(config, 'watchdog_conflict_threshold_s', 120)}s, "
                f"then re-run. Or set watchdog_keepalive=auto to enable PoAgent keepalive."
            )
        )
        raise RuntimeError(f"{WATCHDOG_RUN_CONFLICT}: aborting")

    elif mode == "auto":
        # Spawn keepalive thread
        interval_s: int = getattr(config, "watchdog_keepalive_interval_s", 10)
        thread = WatchdogKeepaliveThread(
            runner=runner,
            device=wdt_state["device"],
            interval_s=interval_s,
            abort_event=abort_event,
            wdt_timeout_s=wdt_state.get("timeout_s"),
            nowayout=wdt_state.get("nowayout", False),
        )
        thread.start()
        log.info("watchdog_keepalive_active",
                 device=wdt_state["device"],
                 interval_s=interval_s)
        return thread

    elif mode == "disable":
        if wdt_state.get("nowayout"):
            log.error(
                WATCHDOG_NOWAYOUT_CANNOT_DISABLE,
                device=wdt_state["device"],
                msg=f"{wdt_state['device']} has NOWAYOUT set — cannot be stopped. "
                    "Use watchdog_keepalive=auto instead.",
            )
            raise RuntimeError(f"{WATCHDOG_NOWAYOUT_CANNOT_DISABLE}: aborting")
        # Write magic close character to stop timer
        runner.exec(  # type: ignore[union-attr]
            f"printf 'V' | dd of={wdt_state['device']} bs=1 count=1 2>/dev/null",
            timeout=3.0, probe_name="watchdog_disable"
        )
        log.info("watchdog_disabled", device=wdt_state["device"])
        return None

    else:
        raise ValueError(f"Unknown watchdog_keepalive mode: {mode!r}")
