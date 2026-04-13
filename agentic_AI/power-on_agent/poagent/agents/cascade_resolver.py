"""Clock Cascade Failure Resolver — runs between Phase 1 and Phase 2 result finalization.

[CG-04] Uses clock_dependency_map to identify cascading failures.
[N-CG-02] If Phase 1 status == "aborted" → tag all clock-dependent subsystems
           LOW_CONFIDENCE_PHASE1_INCOMPLETE, emit ORCHESTRATOR_WARNING, return.
           Empty failed_clocks is NOT "no failures" — do not skip resolver silently.

Phase 1 provides: failed_clocks: list[str] (clock names that failed to lock/enable).
The resolver walks the dependency graph and demotes affected Phase 2 results
to status="dependent_fail" so Triage Agent groups them as a single root cause.
"""

from __future__ import annotations

from typing import Any

import structlog

from poagent.codes import (
    CLOCK_TOPOLOGY_UNKNOWN,
    CLOCK_TOPOLOGY_CONSUMER_UNKNOWN,
)

log = structlog.get_logger(__name__)


def _get_all_consumers(
    failed_clk: str,
    clock_dependency_map: dict[str, dict],
) -> set[str]:
    """Walk the clock dependency graph downward from failed_clk.

    Finds all downstream consumers (subsystem domain names) that depend
    on the failed clock, directly or transitively.
    """
    consumers: set[str] = set()
    visited: set[str] = set()
    queue = [failed_clk]

    while queue:
        clk = queue.pop(0)
        if clk in visited:
            continue
        visited.add(clk)

        entry = clock_dependency_map.get(clk, {})
        # Direct consumers (domain names)
        for consumer in entry.get("consumers", []):
            consumers.add(consumer)

        # Find child clocks (those whose parent is this clock)
        for child_clk, child_entry in clock_dependency_map.items():
            if child_entry.get("parent") == clk and child_clk not in visited:
                queue.append(child_clk)

    return consumers


def resolve_clock_cascades(
    phase1_result: Any,
    phase2_results: dict[str, Any],
    clock_dependency_map: dict[str, dict],
) -> dict[str, Any]:
    """Resolve clock cascade failures across Phase 1 and Phase 2 results.

    [N-CG-02] If Phase 1 aborted: tag clock-dependent Phase 2 results as
    LOW_CONFIDENCE_PHASE1_INCOMPLETE and emit ORCHESTRATOR_WARNING.

    Args:
        phase1_result: DomainResult from Phase 1 Power & Clocking Agent.
                       Must have .status and .get_failed_clocks() or .raw_data["failed_clocks"].
        phase2_results: dict[domain_name → DomainResult] from Phase 2 agents.
        clock_dependency_map: {clock_name: {parent: str, consumers: [domain]}}

    Returns:
        Updated phase2_results dict with cascade annotations applied.
    """
    if not clock_dependency_map:
        log.debug("cascade_resolver_no_map")
        return phase2_results

    phase1_status = getattr(phase1_result, "status", "aborted")

    # [N-CG-02] Phase 1 aborted — cannot do cascade resolution
    if phase1_status == "aborted":
        # Find all clock-dependent subsystems
        clock_dependent: set[str] = set()
        for clk, entry in clock_dependency_map.items():
            for consumer in entry.get("consumers", []):
                clock_dependent.add(consumer)

        for domain in clock_dependent:
            if domain in phase2_results:
                result = phase2_results[domain]
                # Add LOW_CONFIDENCE_PHASE1_INCOMPLETE tag
                tags = getattr(result, "confidence_tags", [])
                if isinstance(tags, list):
                    tags.append("LOW_CONFIDENCE_PHASE1_INCOMPLETE")
                else:
                    try:
                        object.__setattr__(result, "confidence_tags",
                                           ["LOW_CONFIDENCE_PHASE1_INCOMPLETE"])
                    except (AttributeError, TypeError):
                        pass

        log.warning(
            "ORCHESTRATOR_WARNING",
            msg=(
                "Phase 1 (Power & Clocking Agent) timed out "
                "— clock cascade analysis unavailable. All Phase 2 failures in "
                "clock-dependent subsystems are unresolved until Phase 1 completes. "
                "Re-run with a higher agent_timeout_seconds or --subsystem power_clocking."
            ),
            affected_domains=sorted(clock_dependent),
        )
        return phase2_results

    # Phase 1 completed — extract failed clocks
    failed_clocks: list[str] = []
    if hasattr(phase1_result, "get_failed_clocks"):
        failed_clocks = phase1_result.get_failed_clocks()
    elif hasattr(phase1_result, "raw_data"):
        raw = getattr(phase1_result, "raw_data", {}) or {}
        failed_clocks = raw.get("failed_clocks", [])

    if not failed_clocks:
        log.debug("cascade_resolver_no_failed_clocks", phase1_status=phase1_status)
        return phase2_results

    log.info("cascade_resolver_running",
             failed_clocks=failed_clocks,
             phase1_status=phase1_status)

    # For each failed clock, walk dependency graph and demote affected subsystems
    for failed_clk in failed_clocks:
        if failed_clk not in clock_dependency_map:
            log.debug("cascade_resolver_clock_not_in_map", clock=failed_clk)
            continue

        affected_domains = _get_all_consumers(failed_clk, clock_dependency_map)
        if not affected_domains:
            continue

        log.info("cascade_resolver_cascade_found",
                 failed_clock=failed_clk, affected=sorted(affected_domains))

        for domain in affected_domains:
            if domain not in phase2_results:
                continue

            result = phase2_results[domain]
            current_status = getattr(result, "status", "")

            if current_status in ("fail", "warning", "conditional"):
                # Demote to dependent_fail
                try:
                    object.__setattr__(result, "status", "dependent_fail")
                    object.__setattr__(result, "cascade_root", failed_clk)
                    old_summary = getattr(result, "summary", "")
                    new_summary = (
                        f"DEPENDENT_FAIL — root cause is failed clock "
                        f"'{failed_clk}' (owned by Power & Clocking domain). "
                        f"Subsystem cannot function without its clock source. "
                        f"Fix clock failure first. | Original: {old_summary}"
                    )
                    object.__setattr__(result, "summary", new_summary)
                except (AttributeError, TypeError):
                    # DomainResult may be frozen dataclass — use dict approach
                    phase2_results[domain] = _annotate_result(result, failed_clk)

                log.info("cascade_resolver_demoted",
                         domain=domain, failed_clock=failed_clk)

    return phase2_results


def _annotate_result(result: Any, failed_clk: str) -> Any:
    """Create annotated copy of result with cascade_root set.

    Handles both frozen dataclasses and mutable objects.
    """
    from dataclasses import replace, fields, is_dataclass
    if is_dataclass(result) and not isinstance(result, type):
        try:
            field_names = {f.name for f in fields(result)}
            kwargs: dict = {}
            if "status" in field_names:
                kwargs["status"] = "dependent_fail"
            if "cascade_root" in field_names:
                kwargs["cascade_root"] = failed_clk
            if "summary" in field_names:
                old = getattr(result, "summary", "")
                kwargs["summary"] = (
                    f"DEPENDENT_FAIL — root cause: failed clock '{failed_clk}'. "
                    f"Original: {old}"
                )
            return replace(result, **kwargs)
        except Exception:
            pass
    # Fallback: return unchanged
    return result


def enrich_clock_map_from_debugfs(
    runner: object,
    clock_dependency_map: dict[str, dict],
    debugfs_available: bool,
) -> dict[str, dict]:
    """[CG-04] Source 2: Walk debugfs clock tree to fill in parent links.

    Reads /sys/kernel/debug/clk/<name>/clk_parent for each known clock.
    Only executed if debugfs_available=True.
    Returns updated (possibly unchanged) map.
    """
    if not debugfs_available:
        log.debug("clock_map_debugfs_skip", reason="debugfs not available")
        return clock_dependency_map

    try:
        # Get list of clock names from debugfs
        result = runner.exec(  # type: ignore[union-attr]
            "ls /sys/kernel/debug/clk/ 2>/dev/null | head -200",
            timeout=5.0, probe_name="clock_map_debugfs_ls"
        )
        clk_names = [n.strip() for n in result.stdout.splitlines() if n.strip()]

        updates = 0
        for clk_name in clk_names:
            parent_result = runner.exec(  # type: ignore[union-attr]
                f"cat /sys/kernel/debug/clk/{clk_name}/clk_parent 2>/dev/null",
                timeout=2.0, probe_name="clock_map_parent_read"
            )
            parent = parent_result.stdout.strip()
            if parent and parent != "none":
                # Update or add to map
                if clk_name not in clock_dependency_map:
                    clock_dependency_map[clk_name] = {"parent": parent, "consumers": []}
                elif not clock_dependency_map[clk_name].get("parent"):
                    clock_dependency_map[clk_name]["parent"] = parent
                    updates += 1

        log.debug("clock_map_debugfs_enriched", clocks_found=len(clk_names), updates=updates)

    except Exception as exc:
        log.debug("clock_map_debugfs_failed", error=str(exc))

    return clock_dependency_map
