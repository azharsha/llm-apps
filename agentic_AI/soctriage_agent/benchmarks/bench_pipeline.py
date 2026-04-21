"""
bench_pipeline.py — Phase 8 performance benchmarks.

Run: pytest benchmarks/ --benchmark-only -q
"""
import pytest
from pathlib import Path

from soctriage.core.input_handler import open_log
from soctriage.core.token_rule    import TokenRuleRegistry
from soctriage.core.tokenizer     import tokenize
from soctriage.core.assembler     import assemble, LogEvent
from soctriage.core.classifier    import classify_all
from soctriage.core.cascade       import analyse
from soctriage.core.reporter      import render_json

FIXTURE_AMD   = Path(__file__).parent.parent / "tests/fixtures/phase7/amd_mi300_critical.log"
FIXTURE_INTEL = Path(__file__).parent.parent / "tests/fixtures/phase7/intel_dg2_error.log"
FIXTURE_QCOM  = Path(__file__).parent.parent / "tests/fixtures/phase7/qcom_adsp_critical.log"


@pytest.fixture(scope="module")
def registry() -> TokenRuleRegistry:
    r = TokenRuleRegistry()
    r.load_defaults()
    return r


def _run_pipeline(path: Path, reg: TokenRuleRegistry) -> str:
    line_iter, _ = open_log(str(path))
    tokens  = list(tokenize(line_iter, rule_registry=reg))
    events  = list(classify_all(assemble(iter(tokens))))
    cascade = analyse(events)
    return render_json(cascade)


@pytest.mark.benchmark(group="phase1")
def test_bench_input_handler(benchmark):  # type: ignore[no-untyped-def]
    benchmark(lambda: open_log(str(FIXTURE_AMD)))


@pytest.mark.benchmark(group="phase2")
def test_bench_tokenize(benchmark, registry: TokenRuleRegistry) -> None:  # type: ignore[no-untyped-def]
    benchmark(lambda: list(tokenize(open_log(str(FIXTURE_AMD))[0], rule_registry=registry)))


@pytest.mark.benchmark(group="phase4")
def test_bench_cascade_analyse_amd(benchmark, registry: TokenRuleRegistry) -> None:  # type: ignore[no-untyped-def]
    line_iter, _ = open_log(str(FIXTURE_AMD))
    tokens = list(tokenize(line_iter, rule_registry=registry))
    events = list(classify_all(assemble(iter(tokens))))
    benchmark(lambda: analyse(events))


@pytest.mark.benchmark(group="phase4")
def test_bench_cascade_10k_events(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Performance regression guard from Phase 4 EC-27: 500ms at 10k events."""
    events = [
        LogEvent(
            event_id=i,
            event_type="gpuhang",
            severity="error",
            subsystem="gpu",
            ip_block="GFXHUB",
            tokens=[],
            start_line=i * 10,
            end_line=i * 10 + 9,
            arch="x86_64",
            chip_gen="amd_cdna3",
            kernel_ver="6.8.0-45-generic",
            confidence=0.8,
            raw_text="gpu hang",
            has_call_trace=False,
            has_registers=False,
            provider_name="amd",
        )
        for i in range(10_000)
    ]

    def run() -> None:
        result = analyse(events)
        assert result.analysis_ns < 500_000_000, "analyse exceeded 500ms on 10k events"

    benchmark(run)


@pytest.mark.benchmark(group="full_pipeline")
def test_bench_full_pipeline_amd(benchmark, registry: TokenRuleRegistry) -> None:  # type: ignore[no-untyped-def]
    benchmark(lambda: _run_pipeline(FIXTURE_AMD, registry))


@pytest.mark.benchmark(group="full_pipeline")
def test_bench_full_pipeline_intel(benchmark, registry: TokenRuleRegistry) -> None:  # type: ignore[no-untyped-def]
    benchmark(lambda: _run_pipeline(FIXTURE_INTEL, registry))


@pytest.mark.benchmark(group="full_pipeline")
def test_bench_full_pipeline_qcom(benchmark, registry: TokenRuleRegistry) -> None:  # type: ignore[no-untyped-def]
    benchmark(lambda: _run_pipeline(FIXTURE_QCOM, registry))
