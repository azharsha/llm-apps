"""Triage Agent — synthesizes all domain results into TriageOutput.

[PRD §4.1] Agent 12: Triage Agent.
[H-03] po_verdict is Python-computed (not LLM-computed).
[LAST-S4] SILICON_STEPPING_UNRESOLVED upgrades po_verdict to CONDITIONAL minimum.
[N-US-03] Triage token budget: 500-token domain summaries (structured, no raw dmesg).
           boot_context passed as metadata dict.
[FINAL-C1] signing_key_id + HMAC fields in TriageOutput.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

import anthropic
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

from poagent.agents.specialist import DomainResult, Finding
from poagent.agents.prompts import TRIAGE_SYSTEM_PROMPT, TRIAGE_USER_TEMPLATE
from poagent.codes import (
    SILICON_STEPPING_UNRESOLVED,
    PANIC_DETECTED_WARNING,
    AGENT_API_RETRY,
)

log = structlog.get_logger(__name__)

_VERDICT_ORDER = {"PASS": 0, "CONDITIONAL": 1, "FAIL": 2}
_VERDICT_FROM_STATUS = {
    "pass": "PASS",
    "warning": "PASS",          # warnings don't fail verdict alone
    "conditional": "CONDITIONAL",
    "fail": "FAIL",
    "dependent_fail": "FAIL",
    "aborted": "CONDITIONAL",
    "skip": "PASS",
    "enum_fail": "CONDITIONAL",
    "skip_debugfs": "PASS",
}


def _verdict_max(a: str, b: str) -> str:
    """Return the higher-severity verdict."""
    order = _VERDICT_ORDER
    return a if order.get(a, 0) >= order.get(b, 0) else b


@dataclass
class RootCauseHypothesis:
    """Structured root cause hypothesis from Triage Agent."""
    hypothesis: str
    confidence: float
    affected_domains: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


@dataclass
class CrossSubsystemLink:
    """Documented relationship between cause and effect domains."""
    cause_domain: str
    effect_domain: str
    relationship: str
    failed_clock: Optional[str] = None


@dataclass
class TriageOutput:
    """Full structured triage output.

    [H-03] po_verdict is Python-computed.
    [FINAL-C1] signing_key_id + poagent_hmac_sha256 for report integrity.
    [N-US-03] domain_summaries contains only structured data, no raw dmesg.
    """
    schema_version: str = "5.8"
    run_id: str = ""
    board_name: str = ""
    timestamp: float = field(default_factory=time.time)
    po_verdict: Literal["PASS", "FAIL", "CONDITIONAL", "INCOMPLETE"] = "INCOMPLETE"
    po_verdict_reason: str = ""
    root_cause_hypotheses: list[RootCauseHypothesis] = field(default_factory=list)
    cross_subsystem_links: list[CrossSubsystemLink] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)  # CONDITIONAL mandatory box
    domain_summaries: list[dict] = field(default_factory=list)
    boot_context_meta: dict = field(default_factory=dict)
    ecc_correctable_t0: Optional[int] = None
    ecc_correctable_t1: Optional[int] = None
    ecc_correctable_delta: Optional[int] = None
    ecc_rate_per_min: Optional[float] = None
    ecc_uncorrectable_delta: Optional[int] = None
    dram_marginal: bool = False
    dram_uncorrectable: bool = False
    ecc_not_monitorable: bool = False
    signing_key_id: str = ""
    poagent_hmac_sha256: str = ""
    dmesg_supports_k: bool = True
    silicon_stepping_unresolved: bool = False

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        d = asdict(self)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ── po_verdict computation ────────────────────────────────────────────────────

def compute_po_verdict(
    domain_results: dict[str, DomainResult],
    boot_context: dict,
    preflight_aborted: bool = False,
    barrier_failed: bool = False,
    is_dry_run: bool = False,
) -> tuple[str, str]:
    """[H-03] Python-computed po_verdict and po_verdict_reason.

    Never delegated to the LLM.
    Returns (verdict, reason).
    """
    if preflight_aborted:
        return "INCOMPLETE", "Pre-flight gate failure — no agents launched"

    if barrier_failed:
        return "FAIL", "Rail Sanity Barrier failed — critical rail out of tolerance"

    if not domain_results:
        return "INCOMPLETE", "No domain results collected"

    # Compute verdict from all domain statuses
    verdict = "PASS"
    reasons: list[str] = []

    for domain, result in domain_results.items():
        domain_verdict = _VERDICT_FROM_STATUS.get(result.status, "CONDITIONAL")
        verdict = _verdict_max(verdict, domain_verdict)
        if domain_verdict in ("FAIL", "CONDITIONAL"):
            reasons.append(f"{domain}:{result.status}")

    # [LAST-S4] SILICON_STEPPING_UNRESOLVED → upgrade to CONDITIONAL minimum
    stepping = boot_context.get("silicon_stepping", {})
    silicon_unresolved = stepping.get("source") == "fallback"
    if silicon_unresolved:
        verdict = _verdict_max(verdict, "CONDITIONAL")
        reasons.append("SILICON_STEPPING_UNRESOLVED")

    # Kernel panics → upgrade to CONDITIONAL minimum
    kernel_panics = boot_context.get("kernel_panics_this_boot", [])
    panic_types = {p.get("pattern") for p in kernel_panics}
    if panic_types & {"panic", "bug", "gpf"}:
        verdict = _verdict_max(verdict, "CONDITIONAL")
        reasons.append("PANIC_DETECTED")

    reason = "; ".join(reasons) if reasons else "All domains passed"
    if silicon_unresolved:
        reason += "; SILICON_STEPPING_UNRESOLVED — identify stepping before DVT yield analysis"

    return verdict, reason


# ── Triage LLM agent ──────────────────────────────────────────────────────────

_TRIAGE_EMIT_TOOL = {
    "name": "emit_triage_result",
    "description": "Submit the complete triage analysis result. REQUIRED final call.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause_hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis": {"type": "string"},
                        "confidence": {"type": "number"},
                        "affected_domains": {"type": "array", "items": {"type": "string"}},
                        "actions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["hypothesis", "confidence"],
                },
            },
            "cross_subsystem_links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cause_domain": {"type": "string"},
                        "effect_domain": {"type": "string"},
                        "relationship": {"type": "string"},
                        "failed_clock": {"type": "string"},
                    },
                    "required": ["cause_domain", "effect_domain", "relationship"],
                },
            },
            "recommended_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of recommended actions (most impactful first).",
            },
            "action_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "For CONDITIONAL verdict — mandatory action items box in HTML report.",
            },
            "po_verdict_reason": {
                "type": "string",
                "description": "One-line justification for the PO verdict.",
            },
        },
        "required": ["root_cause_hypotheses", "recommended_actions", "po_verdict_reason"],
    },
}


@retry(
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _call_triage_claude(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    messages: list[dict],
) -> Any:
    return client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=messages,
        tools=[_TRIAGE_EMIT_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "any"},  # must use emit_triage_result
    )


def _build_triage_user_message(
    board_name: str,
    run_id: str,
    domain_results: dict[str, DomainResult],
    boot_context: dict,
    preflight_report: Optional[object],
    edac_delta: Optional[object],
) -> str:
    """Build the user message for the Triage Agent."""
    # Domain summaries — structured only, no raw dmesg
    domain_summaries = []
    for domain, result in domain_results.items():
        summary = result.to_summary_dict()
        domain_summaries.append(f"### {domain.upper()}\n"
                                + json.dumps(summary, indent=2))
    domain_summary_text = "\n\n".join(domain_summaries)

    # Boot context summary (no raw dmesg)
    bc = boot_context
    boot_summary_lines = [
        f"kernel_version: {bc.get('kernel_version', 'unknown')}",
        f"uname: {bc.get('uname', 'unknown')[:80]}",
        f"dmesg_supports_k: {bc.get('dmesg_supports_k', True)}",
        f"irq_storm: {bc.get('irq_storm') is not None}",
        f"kernel_panics_this_boot: {len(bc.get('kernel_panics_this_boot', []))} events",
        f"gate4_method5_only: {bc.get('gate4_method5_only', False)}",
        f"debugfs_available: {bc.get('debugfs_available', True)}",
    ]
    stepping = bc.get("silicon_stepping", {})
    if stepping:
        boot_summary_lines.append(
            f"silicon_stepping: platform={stepping.get('platform')} "
            f"source={stepping.get('source')} raw={stepping.get('raw', '')[:40]}"
        )
    boot_summary = "\n".join(boot_summary_lines)

    # Preflight summary
    if preflight_report is not None:
        gates = getattr(preflight_report, "gates", [])
        preflight_text = "\n".join(
            f"Gate {g.gate_num}: {g.name} — {g.severity}" +
            (f" ({g.detail[:60]})" if g.detail else "")
            for g in gates
        )
    else:
        preflight_text = "Pre-flight: ABORTED"

    # EDAC summary
    if edac_delta is not None:
        edac_text = (
            f"CE delta: {getattr(edac_delta, 'ce_delta', 'N/A')}, "
            f"rate: {getattr(edac_delta, 'ce_rate_per_min', 'N/A')}/min, "
            f"UE delta: {getattr(edac_delta, 'ue_delta', 'N/A')}, "
            f"marginal: {getattr(edac_delta, 'dram_marginal', False)}, "
            f"source: {getattr(getattr(edac_delta, 't0', None), 'source', 'unavailable')}"
        )
    else:
        edac_text = "EDAC: not available"

    # Stepping summary
    stepping_text = (
        f"Platform: {stepping.get('platform', 'unknown')}\n"
        f"Source: {stepping.get('source', 'unavailable')}\n"
        f"Raw: {stepping.get('raw', 'unavailable')}"
    )

    return TRIAGE_USER_TEMPLATE.format(
        board_name=board_name,
        run_id=run_id,
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        preflight_summary=preflight_text,
        boot_context_summary=boot_summary,
        domain_count=len(domain_results),
        domain_summaries=domain_summary_text,
        edac_summary=edac_text,
        stepping_summary=stepping_text,
    )


def run_triage_agent(
    domain_results: dict[str, DomainResult],
    boot_context: dict,
    config: object,
    api_key: str,
    run_id: str,
    board_name: str,
    preflight_report: Optional[object] = None,
    edac_delta: Optional[object] = None,
    preflight_aborted: bool = False,
    barrier_failed: bool = False,
) -> TriageOutput:
    """Run the Triage Agent and compute po_verdict.

    Returns TriageOutput with Python-computed po_verdict [H-03].
    """
    model: str = getattr(config, "model", "claude-sonnet-4-6")
    silicon_unresolved = (
        boot_context.get("silicon_stepping", {}).get("source") == "fallback"
    )

    # Build user message
    user_message = _build_triage_user_message(
        board_name=board_name,
        run_id=run_id,
        domain_results=domain_results,
        boot_context=boot_context,
        preflight_report=preflight_report,
        edac_delta=edac_delta,
    )

    # Call Triage LLM
    triage_data: dict = {}
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = _call_triage_claude(
            client=client,
            model=model,
            system=TRIAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                if block.name == "emit_triage_result":
                    triage_data = block.input or {}
                    break

    except RetryError as exc:
        log.error(AGENT_API_RETRY, agent="triage", error=str(exc))
        triage_data = {
            "root_cause_hypotheses": [],
            "recommended_actions": ["Retry triage — API error prevented analysis."],
            "po_verdict_reason": "Triage API error",
        }
    except Exception as exc:
        log.error("triage_agent_error", error=str(exc))
        triage_data = {
            "root_cause_hypotheses": [],
            "recommended_actions": [f"Triage failed: {exc}"],
            "po_verdict_reason": "Triage error",
        }

    # Python-computed po_verdict [H-03]
    po_verdict, po_verdict_reason = compute_po_verdict(
        domain_results=domain_results,
        boot_context=boot_context,
        preflight_aborted=preflight_aborted,
        barrier_failed=barrier_failed,
    )

    # Apply LLM verdict_reason (supplementary)
    llm_reason = triage_data.get("po_verdict_reason", "")
    if llm_reason:
        po_verdict_reason = f"{po_verdict_reason} | LLM: {llm_reason}"

    # Build structured results
    hypotheses = [
        RootCauseHypothesis(
            hypothesis=h.get("hypothesis", ""),
            confidence=float(h.get("confidence", 0.0)),
            affected_domains=h.get("affected_domains", []),
            actions=h.get("actions", []),
        )
        for h in triage_data.get("root_cause_hypotheses", [])
    ]

    links = [
        CrossSubsystemLink(
            cause_domain=l.get("cause_domain", ""),
            effect_domain=l.get("effect_domain", ""),
            relationship=l.get("relationship", ""),
            failed_clock=l.get("failed_clock"),
        )
        for l in triage_data.get("cross_subsystem_links", [])
    ]

    # EDAC fields
    ecc_t0 = ecc_t1 = ecc_delta_val = ecc_rate = ecc_ue = None
    dram_marginal = dram_uncorrectable = ecc_not_monitorable = False
    if edac_delta is not None:
        ecc_t0 = getattr(getattr(edac_delta, "t0", None), "ce", None)
        ecc_t1 = getattr(getattr(edac_delta, "t1", None), "ce", None)
        ecc_delta_val = getattr(edac_delta, "ce_delta", None)
        ecc_rate = getattr(edac_delta, "ce_rate_per_min", None)
        ecc_ue = getattr(edac_delta, "ue_delta", None)
        dram_marginal = getattr(edac_delta, "dram_marginal", False)
        dram_uncorrectable = getattr(edac_delta, "dram_uncorrectable", False)
        ecc_not_monitorable = getattr(edac_delta, "ecc_not_monitorable", False)

    # Boot context metadata (no raw dmesg)
    boot_meta = {
        k: v for k, v in boot_context.items()
        if k not in ("dmesg", "dmesg_raw")
    }

    output = TriageOutput(
        run_id=run_id,
        board_name=board_name,
        po_verdict=po_verdict,  # type: ignore[arg-type]
        po_verdict_reason=po_verdict_reason,
        root_cause_hypotheses=hypotheses,
        cross_subsystem_links=links,
        recommended_actions=triage_data.get("recommended_actions", []),
        action_items=triage_data.get("action_items", []),
        domain_summaries=[r.to_summary_dict() for r in domain_results.values()],
        boot_context_meta=boot_meta,
        ecc_correctable_t0=ecc_t0,
        ecc_correctable_t1=ecc_t1,
        ecc_correctable_delta=ecc_delta_val,
        ecc_rate_per_min=ecc_rate,
        ecc_uncorrectable_delta=ecc_ue,
        dram_marginal=dram_marginal,
        dram_uncorrectable=dram_uncorrectable,
        ecc_not_monitorable=ecc_not_monitorable,
        dmesg_supports_k=boot_context.get("dmesg_supports_k", True),
        silicon_stepping_unresolved=silicon_unresolved,
    )

    log.info("triage_complete",
             verdict=po_verdict,
             hypotheses=len(hypotheses),
             actions=len(output.recommended_actions))

    return output
