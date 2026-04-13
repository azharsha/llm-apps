"""ProbeRunner — dual transport SSH (paramiko) / serial (pyserial).

[N-CG-05] SSH keepalive + single reconnect on transport error.
[SG-05] Serial flow control config + truncation retry.
[SG-06] Per-call timeout enforcement + timed_out_probe tracking.

All domain agents use ProbeRunner.exec() — SSH semaphore acquired
AFTER pause_event check (N-CG-03 threading contract).
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import paramiko
import structlog

from poagent.codes import SERIAL_TRUNCATION_RETRY, SERIAL_TRUNCATION_SUSPECTED

log = structlog.get_logger(__name__)


class ProbeTransportError(Exception):
    """Raised when SSH/serial transport fails unrecoverably."""


class ThermalAbortError(Exception):
    """Raised when abort_event is set by ThermalMonitorThread."""


@dataclass
class ExecResult:
    """Result of a single ProbeRunner.exec() call."""
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    timed_out_probe: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def stdout_sha256(self) -> str:
        return hashlib.sha256(self.stdout.encode()).hexdigest()

    @property
    def stdout_len(self) -> int:
        return len(self.stdout.encode())


class ProbeRunner:
    """Dual-transport probe runner: SSH (primary) + serial (fallback).

    All commands go through exec() which:
    1. Checks pause_event BEFORE acquiring SSH semaphore (N-CG-03)
    2. Checks abort_event
    3. Acquires SSH semaphore
    4. Runs command with per-call timeout
    5. Releases semaphore
    6. Logs to BoardCommandLog
    7. Handles truncation retry (serial)

    The semaphore is NEVER held across a thermal pause boundary.
    """

    def __init__(
        self,
        *,
        ssh_semaphore: Optional[threading.Semaphore] = None,
        pause_event: Optional[threading.Event] = None,
        abort_event: Optional[threading.Event] = None,
        audit_log: Optional[object] = None,
        domain: str = "unknown",
        run_id: str = "",
        board_ip: str = "",
        board_name: str = "",
    ) -> None:
        self._ssh_client: Optional[paramiko.SSHClient] = None
        self._serial: Optional[object] = None  # pyserial Serial object
        self._transport_type: str = "none"

        self._ssh_semaphore = ssh_semaphore or threading.Semaphore(4)
        self._pause_event = pause_event or threading.Event()
        self._abort_event = abort_event or threading.Event()
        self._audit_log = audit_log
        self._domain = domain
        self._run_id = run_id
        self._board_ip = board_ip
        self._board_name = board_name

        self._reconnect_attempted = False
        self._ssh_config: dict = {}
        self._serial_config: dict = {}

        self._timed_out_probes: list[str] = []

    # ── Transport setup ───────────────────────────────────────────────────

    def via_ssh(
        self,
        host: str,
        user: str = "root",
        key_file: Optional[str] = None,
        password: Optional[str] = None,
        port: int = 22,
        keepalive_interval_s: int = 30,
    ) -> "ProbeRunner":
        """Connect via SSH (paramiko). Key auth preferred; password fallback."""
        self._ssh_config = dict(
            host=host, user=user, key_file=key_file,
            password=password, port=port,
            keepalive_interval_s=keepalive_interval_s,
        )
        self._transport_type = "ssh"
        self._connect_ssh()
        return self

    def _connect_ssh(self) -> None:
        """Establish SSH connection with keepalive."""
        cfg = self._ssh_config
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        key = None
        if cfg.get("key_file"):
            try:
                key = paramiko.RSAKey.from_private_key_file(
                    str(cfg["key_file"]).replace("~", __import__("os").path.expanduser("~"))
                )
            except Exception as exc:
                log.debug("ssh_key_load_failed", error=str(exc))

        try:
            client.connect(
                hostname=cfg["host"],
                port=cfg.get("port", 22),
                username=cfg.get("user", "root"),
                pkey=key,
                password=cfg.get("password"),
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException:
            if key is not None and cfg.get("password"):
                # Key failed — try password
                client.connect(
                    hostname=cfg["host"],
                    port=cfg.get("port", 22),
                    username=cfg.get("user", "root"),
                    password=cfg.get("password"),
                    timeout=15,
                    allow_agent=False,
                    look_for_keys=False,
                )
            else:
                raise

        # [N-CG-05] Enable SSH keepalive to prevent TCP idle timeout
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(cfg.get("keepalive_interval_s", 30))

        self._ssh_client = client
        log.debug("ssh_connected", host=cfg["host"], port=cfg.get("port", 22))

    def via_serial(
        self,
        port: str,
        baud: int = 115200,
        user: str = "root",
        password: Optional[str] = None,
        login_timeout: int = 30,
        rtscts: bool = False,
        xonxoff: bool = False,
        baud_autodetect: bool = False,
    ) -> "ProbeRunner":
        """Connect via serial console (pyserial)."""
        import serial
        bauds_to_try = [baud]
        if baud_autodetect:
            bauds_to_try = [115200, 57600, 38400, 9600]

        last_exc: Optional[Exception] = None
        for baud_rate in bauds_to_try:
            try:
                ser = serial.Serial(
                    port=port,
                    baudrate=baud_rate,
                    timeout=1,
                    rtscts=rtscts,
                    xonxoff=xonxoff,
                )
                # Send CR/LF to trigger prompt
                ser.write(b"\r\n")
                time.sleep(0.5)

                # Login sequence
                deadline = time.time() + login_timeout
                while time.time() < deadline:
                    data = ser.read(256).decode("utf-8", errors="replace")
                    if "login:" in data:
                        ser.write(f"{user}\r".encode())
                        time.sleep(0.3)
                        ser.write(f"{password or ''}\r".encode())
                        time.sleep(0.5)
                    elif "#" in data or "$" in data:
                        # Verify prompt
                        ser.write(b"echo poagent_ready\r")
                        time.sleep(0.3)
                        resp = ser.read(256).decode("utf-8", errors="replace")
                        if "poagent_ready" in resp:
                            self._serial = ser
                            self._transport_type = "serial"
                            self._serial_config = dict(
                                port=port, baud=baud_rate,
                                rtscts=rtscts, xonxoff=xonxoff,
                            )
                            log.info("serial_connected", port=port, baud=baud_rate)
                            return self
                    time.sleep(0.2)
                ser.close()
            except Exception as exc:
                last_exc = exc
                continue

        raise ProbeTransportError(
            f"Serial connection failed on all baud rates: {last_exc}"
        )

    # ── Command execution ─────────────────────────────────────────────────

    def exec(
        self,
        cmd: str,
        timeout: float = 30.0,
        min_output_len: int = 0,
        probe_name: str = "",
    ) -> ExecResult:
        """Execute a command on the target board.

        [N-CG-03] Threading contract:
          1. Check pause_event BEFORE acquiring semaphore (never hold semaphore
             across a thermal pause boundary — see §3.5 for deadlock analysis)
          2. Check abort_event
          3. Acquire semaphore
          4. Run command
          5. Release semaphore (via context manager — always released)

        [SG-05] Serial truncation retry: if min_output_len > 0 and
        len(stdout) < min_output_len, retry once.
        """
        # Step 1: check thermal pause BEFORE acquiring semaphore
        if self._pause_event.is_set():
            self._pause_event.wait()

        # Step 2: check abort
        if self._abort_event.is_set():
            raise ThermalAbortError("Abort event set — run terminated")

        # Step 3: acquire semaphore only when thermal state is clear
        start_time = time.time()
        result: ExecResult
        try:
            with self._ssh_semaphore:
                result = self._run(cmd, timeout, probe_name)
        except paramiko.SSHException as exc:
            raise ProbeTransportError(f"SSH lost during thermal pause: {exc}") from exc

        # Step 4: [SG-05] truncation retry
        if (min_output_len > 0
                and self._transport_type == "serial"
                and len(result.stdout) < min_output_len):
            log.debug(SERIAL_TRUNCATION_RETRY,
                      cmd=cmd[:80], got=len(result.stdout), expected_min=min_output_len)
            with self._ssh_semaphore:
                result = self._run(cmd, timeout, probe_name)
            if len(result.stdout) < min_output_len:
                result.warnings.append(
                    f"{SERIAL_TRUNCATION_SUSPECTED}: output {len(result.stdout)} chars "
                    f"< expected min {min_output_len}. Enable flow control "
                    f"(rtscts or xonxoff) if this recurs."
                )

        duration_ms = int((time.time() - start_time) * 1000)
        self._log_command(cmd, result, duration_ms, probe_name)
        return result

    def _run(self, cmd: str, timeout: float, probe_name: str) -> ExecResult:
        """Internal: run command via active transport."""
        if self._transport_type == "ssh":
            return self._run_ssh(cmd, timeout, probe_name)
        elif self._transport_type == "serial":
            return self._run_serial(cmd, timeout)
        else:
            raise ProbeTransportError("No transport configured")

    def _run_ssh(self, cmd: str, timeout: float, probe_name: str) -> ExecResult:
        """Run command over SSH with single-reconnect on failure."""
        try:
            return self._exec_ssh_channel(cmd, timeout)
        except (paramiko.SSHException, socket.error) as exc:
            if not self._reconnect_attempted:
                log.debug("ssh_reconnecting", error=str(exc))
                self._reconnect_attempted = True
                try:
                    self._connect_ssh()
                    result = self._exec_ssh_channel(cmd, timeout)
                    self._reconnect_attempted = False
                    return result
                except Exception as reconnect_exc:
                    raise ProbeTransportError(
                        f"SSH reconnect failed: {reconnect_exc}"
                    ) from reconnect_exc
            raise ProbeTransportError(f"SSH error: {exc}") from exc

    def _exec_ssh_channel(self, cmd: str, timeout: float) -> ExecResult:
        """Execute command on SSH channel."""
        if not self._ssh_client:
            raise ProbeTransportError("SSH client not connected")

        try:
            stdin, stdout, stderr = self._ssh_client.exec_command(
                cmd, timeout=timeout
            )
            stdin.close()

            # Wait for completion with timeout
            channel = stdout.channel
            channel.settimeout(timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = channel.recv_exit_status()

            self._reconnect_attempted = False
            return ExecResult(stdout=out, stderr=err, returncode=rc)

        except socket.timeout:
            return ExecResult(
                stdout="",
                stderr="PROBE_TIMEOUT",
                returncode=-1,
                timed_out=True,
                timed_out_probe=self._current_probe,
            )

    def _run_serial(self, cmd: str, timeout: float) -> ExecResult:
        """Run command over serial console."""
        if not self._serial:
            raise ProbeTransportError("Serial not connected")
        ser = self._serial
        deadline = time.time() + timeout
        ser.write(f"{cmd}\r".encode())
        output_lines: list[str] = []
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="replace")
            if not line:
                if time.time() >= deadline:
                    return ExecResult(
                        stdout="".join(output_lines),
                        stderr="PROBE_TIMEOUT",
                        returncode=-1,
                        timed_out=True,
                    )
                continue
            # Detect shell prompt (end of command output)
            if line.strip().endswith(("#", "$")):
                break
            output_lines.append(line)
        return ExecResult(
            stdout="".join(output_lines),
            stderr="",
            returncode=0,
        )

    # ── Utility methods ───────────────────────────────────────────────────

    def read_file(self, path: str) -> str:
        """Read a file from the target board."""
        result = self.exec(f"cat {path} 2>/dev/null || echo ''", timeout=5.0)
        return result.stdout

    def path_exists(self, path: str) -> bool:
        """Check if path exists on target board."""
        result = self.exec(f"test -e {path} && echo yes || echo no", timeout=5.0)
        return result.stdout.strip() == "yes"

    def glob(self, pattern: str) -> list[str]:
        """Expand glob pattern on target board. Returns list of paths."""
        result = self.exec(f"ls -d {pattern} 2>/dev/null || true", timeout=5.0)
        return [p.strip() for p in result.stdout.splitlines() if p.strip()]

    def glob_read(self, pattern: str) -> list[str]:
        """Read contents of all files matching glob pattern."""
        paths = self.glob(pattern)
        results = []
        for p in paths:
            content = self.read_file(p).strip()
            if content:
                results.append(content)
        return results

    def exec_command(self, cmd: str, timeout: float = 30.0) -> tuple[int, str]:
        """Backward-compat wrapper: call exec() and return (returncode, stdout)."""
        result = self.exec(cmd, timeout=timeout)
        return result.returncode, result.stdout

    def scp_put(self, local_path: str, remote_path: str) -> None:
        """Upload a local file to the target board via SFTP (SSH only).

        Used by CProbeRunner to deploy compiled C probe binaries.
        """
        if self._transport_type != "ssh" or not self._ssh_client:
            raise ProbeTransportError("scp_put requires an active SSH connection")
        sftp = self._ssh_client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
            log.debug("scp_put_ok", local=local_path, remote=remote_path)
        finally:
            sftp.close()

    def collect_timed_out_probes(self) -> list[str]:
        """Return all probe names that timed out during this runner's lifetime."""
        return list(self._timed_out_probes)

    def _log_command(
        self,
        cmd: str,
        result: ExecResult,
        duration_ms: int,
        probe_name: str,
    ) -> None:
        """Append CommandLogEntry to BoardCommandLog."""
        if self._audit_log is None:
            return
        try:
            self._audit_log.append(  # type: ignore[union-attr]
                domain=self._domain,
                probe=probe_name,
                transport=self._transport_type,
                command=cmd,
                returncode=result.returncode,
                stdout_sha256=result.stdout_sha256,
                stdout_len=result.stdout_len,
                duration_ms=duration_ms,
                timed_out=result.timed_out,
            )
        except Exception as exc:
            log.warning("audit_log_write_failed", error=str(exc))

    @property
    def _current_probe(self) -> str:
        return ""  # subclasses may override

    def close(self) -> None:
        """Close all transport connections."""
        if self._ssh_client:
            try:
                self._ssh_client.close()
            except Exception:
                pass
            self._ssh_client = None
        if self._serial:
            try:
                self._serial.close()  # type: ignore[union-attr]
            except Exception:
                pass
            self._serial = None

    def __enter__(self) -> "ProbeRunner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
