"""Probe registry — ProbeBase, ProbeTier, and @register_probe decorator.

All domain probes inherit from ProbeBase and register themselves
via @register_probe. The orchestrator uses the registry to discover
which probes to run for a given domain and tier.

Tiers:
  FAST     — runs always; expected < 5s; no LLM call
  STANDARD — default tier; may call LLM
  SLOW     — optional deep probes; e.g., memtester, long EDAC reads
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Type

import structlog

log = structlog.get_logger(__name__)


class ProbeTier(Enum):
    """Probe execution tier."""
    FAST = auto()       # Always run; < 5s; no LLM
    STANDARD = auto()   # Default; may invoke LLM
    SLOW = auto()       # Optional deep probes (memtester, long reads)


@dataclass
class ProbeMetadata:
    """Metadata for a registered probe."""
    name: str
    domain: str
    tier: ProbeTier
    description: str
    timeout: float  # seconds
    probe_class: Type["ProbeBase"]


# Global probe registry: domain → list[ProbeMetadata]
_REGISTRY: dict[str, list[ProbeMetadata]] = {}


def register_probe(
    domain: str,
    tier: ProbeTier = ProbeTier.STANDARD,
    description: str = "",
    timeout: float = 30.0,
) -> Callable:
    """Decorator to register a ProbeBase subclass in the probe registry.

    Usage:
        @register_probe(domain="storage", tier=ProbeTier.FAST, timeout=10.0)
        class NVMePresenceProbe(ProbeBase):
            ...
    """
    def decorator(cls: Type["ProbeBase"]) -> Type["ProbeBase"]:
        meta = ProbeMetadata(
            name=cls.__name__,
            domain=domain,
            tier=tier,
            description=description or cls.__doc__ or "",
            timeout=timeout,
            probe_class=cls,
        )
        _REGISTRY.setdefault(domain, []).append(meta)
        log.debug("probe_registered", probe=cls.__name__, domain=domain, tier=tier.name)
        return cls
    return decorator


def get_probes(
    domain: str,
    max_tier: ProbeTier = ProbeTier.STANDARD,
) -> list[ProbeMetadata]:
    """Return all registered probes for a domain up to max_tier.

    Probes are ordered: FAST first, then STANDARD, then SLOW (if allowed).
    """
    tier_order = {ProbeTier.FAST: 0, ProbeTier.STANDARD: 1, ProbeTier.SLOW: 2}
    allowed_tiers = {t for t in ProbeTier if tier_order[t] <= tier_order[max_tier]}
    probes = [m for m in _REGISTRY.get(domain, []) if m.tier in allowed_tiers]
    probes.sort(key=lambda m: tier_order[m.tier])
    return probes


def get_all_domains() -> list[str]:
    """Return all registered domains."""
    return sorted(_REGISTRY.keys())


class ProbeBase:
    """Base class for all domain probes.

    Subclasses must implement run() and be decorated with @register_probe.

    The runner is a ProbeRunner instance already connected to the target board.
    The board_profile is a BoardProfile with DTS-derived specifications.
    The config is the PoAgentConfig for this run.
    """

    def __init__(
        self,
        runner: object,
        board_profile: object,
        config: object,
    ) -> None:
        self._runner = runner
        self._board_profile = board_profile
        self._config = config

    def run(self) -> "ProbeResult":
        """Execute the probe. Subclasses must implement this."""
        raise NotImplementedError(f"{self.__class__.__name__}.run() not implemented")

    def exec(self, cmd: str, timeout: Optional[float] = None, **kwargs: object) -> object:
        """Convenience wrapper around runner.exec()."""
        kw = {}
        if timeout is not None:
            kw["timeout"] = timeout
        kw.update(kwargs)
        return self._runner.exec(cmd, probe_name=self.__class__.__name__, **kw)  # type: ignore[union-attr]

    def run_c_probe(
        self,
        source: str,
        args: list[str],
        timeout: float = 10.0,
    ) -> dict:
        """[CP-04] Deploy and run a C probe binary on the target board.

        Returns parsed JSON dict from the binary's stdout.

        Raises:
            CProbeDeploySkipped   — insufficient memory
            CProbeCompileError    — on-target gcc failed
            CProbeIntegrityError  — SHA-256 mismatch
            CProbeExecError       — binary exited non-zero or bad JSON
        """
        from poagent.probes.c_probe_runner import CProbeRunner
        if not hasattr(self, "_c_runner"):
            self._c_runner = CProbeRunner(self._runner, self._config)
        return self._c_runner.run_c_probe(source, args, timeout=timeout)


@dataclass(frozen=True)
class ProbeResult:
    """Immutable result of a single ProbeBase.run() call.

    severity: "PASS" | "FAIL" | "CONDITIONAL" | "INCOMPLETE" | "SKIP"
    findings: list of human-readable finding strings
    raw_data: arbitrary dict for structured data (e.g., parsed sensor values)
    timed_out: True if any sub-probe timed out
    timed_out_probes: list of probe names that timed out

    Backward-compat kwargs (deprecated):
      passed  → severity="PASS"/"FAIL"
      data    → raw_data
      message → findings[0]
    """
    probe_name: str
    domain: str
    severity: str = ""
    findings: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
    timed_out: bool = False
    timed_out_probes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Backward-compat fields — set these OR use severity/findings/raw_data
    passed: Optional[bool] = field(default=None, repr=False, compare=False)
    data: Optional[dict] = field(default=None, repr=False, compare=False)
    message: Optional[str] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Map old-style kwargs → canonical fields (frozen: use object.__setattr__)
        if self.passed is not None and not self.severity:
            object.__setattr__(self, "severity", "PASS" if self.passed else "FAIL")
        if not self.severity:
            object.__setattr__(self, "severity", "INCOMPLETE")
        if self.data is not None and not self.raw_data:
            object.__setattr__(self, "raw_data", self.data)
        if self.message is not None and not self.findings:
            object.__setattr__(self, "findings", [self.message])

    @property
    def is_fail(self) -> bool:
        return self.severity == "FAIL"

    @property
    def is_pass(self) -> bool:
        return self.severity == "PASS"

    @property
    def is_conditional(self) -> bool:
        return self.severity == "CONDITIONAL"

    @property
    def is_incomplete(self) -> bool:
        return self.severity == "INCOMPLETE"
