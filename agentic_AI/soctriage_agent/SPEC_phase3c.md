# SPEC_phase3c — Hardware Decode Layer

**Phase**: 3c  **Depends on**: Phase 3 (496 PASSED · 6 XFAIL)  **Version**: 3c.1.0

---

## Purpose

Converts raw register dumps, firmware status words, and GPU stall indicators
inside `LogEvent.raw_text` into a structured `HardwareContext` object attached
to each event. Bridges Phase 3 (classification) → Phase 4 (cascade reasoning).

---

## New Files

| File | Role |
|---|---|
| `soctriage/core/hardware_decode.py` | Public API: `HardwareContext`, `HardwareRegister`, `decode_hardware()` |
| `soctriage/core/scan_dump_parser.py` | Parse register hex + firmware tokens → `HardwareContext` |
| `soctriage/core/wave_analyzer.py` | Derive engine/ring stall signals from parsed context |
| `soctriage/core/stall_classifier.py` | Classify stall type + confidence score |
| `tests/fixtures/phase3c/*.log` | 8 hardware-oriented kernel log snippets |
| `tests/test_scan_dump_parser.py` | 24 tests |
| `tests/test_wave_analyzer.py` | 16 tests |
| `tests/test_stall_classifier.py` | 16 tests |
| `tests/test_hardware_decode.py` | 14 tests |

---

## Key Data Structures

```python
@dataclass
class HardwareRegister:
    name: str           # e.g. "GRBM_STATUS"
    raw_value: int      # decoded integer
    width_bits: int     # 32 or 64
    decoded_fields: dict
    source_line: int

@dataclass
class HardwareContext:
    provider_name: str
    chip_gen: str
    registers: list[HardwareRegister]
    derived_signals: dict    # cp_stalled, mmhub_fault, guc_alive, etc.
    stall_type: str          # one of 8 categories
    stall_confidence: float  # 0.0–1.0
    evidence_lines: list[int]
    notes: list[str]
    def to_dict(self) -> dict: ...
```

`LogEvent` extension: `event.__dict__["hardware_context"] = ctx`

---

## Pipeline

```
parse_registers(event) → HardwareContext | None
    → analyse_waves(ctx, event) → HardwareContext
    → classify_stall(ctx, event) → HardwareContext
    → event.hardware_context = ctx
```

---

## Register Regex

```python
REGISTER_RE = re.compile(
    r"(?P<name>[A-Z][A-Z0-9_\[\]\.]+)\s*(?:=|:)\s*(?:0x)?(?P<hex>[0-9A-Fa-f]{1,16})"
)
```

Width: hex ≤ 8 chars → 32-bit, else → 64-bit. Malformed hex → note + skip.

---

## Stall Types (priority order)

1. `firmware_boot_fail` — psp/guc/gsp fail at boot
2. `firmware_runtime_crash` — adsp/cdsp/slpi SSR
3. `memory_translation_fault` — mmhub/gtt/smmu fault
4. `ras_uncorrectable` — ECC/RAS UE
5. `reset_storm` — reset_in_progress + gpu_reset/hang event type
6. `gpu_hard_stall` — engine stalled or no forward progress
7. `power_gating_fault` — rpmh timeout
8. `unknown_hardware_fault` — fallback

---

## Constraints

- NEVER modify: tokenrule.py, tokenizer.py, assembler.py, classifier.py,
  soc_provider.py, cli.py, reporter.py, token_rules/*.yaml
- `decode_hardware()` returns SAME list object
- Never raises on malformed hex
- Unknown registers preserved in HardwareContext.registers
- Phase 4 integration is advisory — works when hardware_context is None

---

## Acceptance Gate

70 new tests pass + full suite stays green + mypy 0 errors on 4 Phase 3c files.
