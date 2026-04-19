# SPEC — Phase 5: Provider Implementations
## SoCTriage v5.0.0 · Intel · Qualcomm · AMD · NVIDIA · Generic

---

## ⚠️ PRD vs. Reality: Four Critical Discrepancies

Before reading the spec, these discrepancies between the PRD and the actual codebase
**must be confirmed by the user**. The spec is written against the actual code state.

### D-1: `SoCProvider` interface has 8 abstract methods, not 4

The PRD says the three locked abstract methods are `detect()`, `classify_ip()`,
and `get_known_issues()`. The actual `soc_provider.py` has:

```python
def name(self) -> str
def detect(self, raw_log: str) -> float          # ← takes str, returns float — NOT bool
def classify_ip(self, token_stream: list[dict]) -> list[dict]
def resolve_cascade(self, ip_hits: list[dict]) -> list[str]
def get_playbook(self, ip_block: str) -> dict
def decode_registers(self, raw_registers: dict[str, int]) -> dict
def get_register_maps(self) -> dict[str, dict[int, str]]
def get_hang_rules(self) -> list[HangRule]
```

`get_known_issues()` does **not** exist in the interface.
Phase 5 implements all 8 methods (not 3).

### D-2: `detect()` takes a raw log string, returns a float confidence score

The PRD describes `detect(self, token_stream: list[dict]) -> bool`.
The actual signature is `detect(self, raw_log: str) -> float` (0.0–1.0).
The registry already calls it this way in `provider_registry.py:detect_provider()`.

### D-3: Providers already exist as directory packages (stubs)

The PRD says to create `providers/intel_provider.py` etc.
The actual layout already exists:
```
soctriage/providers/
├── intel/      provider.py  ip_definitions.py  manifest.yaml  __init__.py
├── qualcomm/   provider.py  ip_definitions.py  manifest.yaml  __init__.py
├── amd/        provider.py  ip_definitions.py  manifest.yaml  __init__.py
├── nvidia/     provider.py  ip_definitions.py  manifest.yaml  __init__.py
└── generic/    provider.py  ip_definitions.py               __init__.py
```
All `provider.py` files have skeleton classes; all methods return `[]` or `{}`.
All `ip_definitions.py` files have named lists (e.g. `INTEL_IP_BLOCKS`) but empty
data structures (`IP_PATTERNS`, `CASCADE_GRAPH`, `PLAYBOOK`, `REGISTER_MAPS`, `HANG_RULES`).

The `ProviderRegistry` is already fully implemented in `core/provider_registry.py`.
No `providers/__init__.py` registry needs to be created.

### D-4: The 6 XFAILs are Phase 1/3 tests — not provider detection tests

The PRD claims Phase 5 converts 6 provider-detection XFAILs to PASSED.
The current 6 XFAILs in the suite are:

| Test | Phase | Reason |
|------|-------|--------|
| `test_ec01_normal_dmesg_no_anomalies` | Phase 1 | Normal dmesg streaming |
| `test_ec06_large_log_streaming` | Phase 1 | >100MB streaming |
| `test_ec10_empty_file_structured_error` | Phase 1 | Empty file error |
| `test_ec12_compressed_log_decompression` | Phase 1 | .gz/.bz2 decompression |
| `test_ec09_kasan_root_over_amdgpu` | Phase 3 | KASAN classification |
| `test_ec18_multi_gpu_per_pci_bus` | Phase 3 | Multi-GPU cascade |

Phase 5 provider work does **not** convert these.
Phase 5 will add **new** passing tests (not convert XFAILs).
After Phase 5: still 6 XFAIL + 668 existing + ~135 new = **~803 passed**.

---

## 1. Objective

Implement all five `SoCProvider` concrete classes by filling in every currently-stubbed
method. The output of Phase 5 is:

- Meaningful `detect()` confidence (keyword density + regex, already partially done)
- Working `classify_ip()` that maps token signals → named IP blocks with confidence
- Working `resolve_cascade()` that returns ordered fault propagation chains
- Working `get_playbook()` that returns structured fix steps per IP block
- Working `decode_registers()` that decodes raw hex register values to named fields
- Populated `get_register_maps()` (REGISTER_MAPS data in `ip_definitions.py`)
- Working `get_hang_rules()` returning `HangRule` objects for the stall classifier
- Optional: `get_known_issues()` as a non-ABC helper on each provider (not in interface)
- 135 new tests across 6 test files under `tests/test_providers/`

---

## 2. Immutable Files (must not change)

Per PRD §1.5:

```
soctriage/core/soc_provider.py
soctriage/core/token_rule.py
soctriage/core/tokenizer.py
soctriage/core/assembler.py
soctriage/core/classifier.py
soctriage/core/cascade.py
soctriage/core/ascii_diagram.py
soctriage/cli.py
soctriage/core/reporter.py
soctriage/core/token_rules/*.yaml
```

---

## 3. File Deliverables

### Modified (fill in stubs)

| File | Work |
|------|------|
| `soctriage/providers/intel/provider.py` | Implement all 8 methods |
| `soctriage/providers/intel/ip_definitions.py` | Populate IP_PATTERNS, CASCADE_GRAPH, PLAYBOOK, REGISTER_MAPS, HANG_RULES |
| `soctriage/providers/qualcomm/provider.py` | Implement all 8 methods |
| `soctriage/providers/qualcomm/ip_definitions.py` | Populate data |
| `soctriage/providers/amd/provider.py` | Implement all 8 methods |
| `soctriage/providers/amd/ip_definitions.py` | Populate data |
| `soctriage/providers/nvidia/provider.py` | Implement all 8 methods |
| `soctriage/providers/nvidia/ip_definitions.py` | Populate data |
| `soctriage/providers/generic/provider.py` | Implement all 8 methods |
| `soctriage/providers/generic/ip_definitions.py` | Minimal data (fallback) |

### New (create)

| File | Tests |
|------|-------|
| `tests/test_providers/__init__.py` | (empty) |
| `tests/test_providers/test_intel_provider.py` | 28 tests |
| `tests/test_providers/test_qualcomm_provider.py` | 30 tests |
| `tests/test_providers/test_amd_provider.py` | 30 tests |
| `tests/test_providers/test_nvidia_provider.py` | 20 tests |
| `tests/test_providers/test_generic_provider.py` | 15 tests |
| `tests/test_providers/test_provider_registry.py` | 12 tests |
| `tests/fixtures/phase5/` | 10 fixture log files |

---

## 4. SoCProvider Method Contracts

Each concrete provider must implement these exactly:

### `detect(self, raw_log: str) -> float`
- Returns confidence ∈ [0.0, 1.0]
- Current stub: counts keyword hits × 0.25, capped at 1.0
- Phase 5: add regex pattern matching on top of keyword counting
- `GenericProvider.detect()` always returns `0.1` (lowest priority)

### `classify_ip(self, token_stream: list[dict]) -> list[dict]`
- Input: `[{"type": tok.token_type, "raw": tok.raw}, ...]`
- Output: `[{"ip": str, "confidence": float, "subsystem": str, "notes": str}, ...]`
- Returns `[]` if no IP block identified
- Must never raise for any input (including empty list or unknown types)

### `resolve_cascade(self, ip_hits: list[dict]) -> list[str]`
- Input: output of `classify_ip()`
- Output: ordered list of IP block names, primary fault first
- Uses `CASCADE_GRAPH` from `ip_definitions.py`

### `get_playbook(self, ip_block: str) -> dict`
- Returns structured fix dict: `{"steps": [...], "references": [...], "notes": str}`
- Returns `{}` for unknown IP blocks (never raises)

### `decode_registers(self, raw_registers: dict[str, int]) -> dict`
- Input: `{"REGISTER_NAME": 0xDEADBEEF, ...}`
- Output: `{"REGISTER_NAME": {"raw": 0xDEADBEEF, "fields": {...}}, ...}`
- Uses `REGISTER_MAPS` from `ip_definitions.py`

### `get_register_maps(self) -> dict[str, dict[int, str]]`
- Returns `REGISTER_MAPS` from `ip_definitions.py`
- Already wired in stubs — just populate the data

### `get_hang_rules(self) -> list[HangRule]`
- Returns list of `HangRule(mode, signals, confidence)` objects
- Uses `HANG_RULES` from `ip_definitions.py`

### `get_known_issues(self, chip_gen: str, event_types: list[str]) -> list[dict]` *(non-ABC)*
- Not in the abstract interface — add as a regular method on each provider
- Returns known-issue dicts matching both chip_gen AND overlapping symptoms
- Schema per PRD §3.2: `{issue_id, title, chip_gens, symptoms, workaround, fixed_in, severity, url}`

---

## 5. Provider IP Block Tables (source of truth)

### Intel (15 IP blocks from `ip_definitions.py`)
`GUC, HUC, GT, RENDER, BLITTER, MEDIA, DISPLAY, LMEM, GGTT, PCIe, TBT, USB4, PMC, GSC, SAMedia`

Key `classify_ip()` mappings (from PRD §4.2):
- `firmware_event` + `GuC` raw → `GUC`, conf=0.95, subsystem=firmware
- `firmware_event` + `HuC` raw → `HUC`, conf=0.95, subsystem=firmware
- `gpu_event` + `gfx_0` raw → `RENDER`, conf=0.90, subsystem=gpu
- `reset_event` + `GPU HANG` raw → `RENDER`, conf=0.85, subsystem=gpu
- `intel_gtt_event` + `GGTT` raw → `GGTT`, conf=0.90, subsystem=interconnect
- `smmu_fault` + Intel IOMMU raw → `GGTT`, conf=0.85, subsystem=interconnect
- `pcie_error` + `i915` raw → `PCIe`, conf=0.80, subsystem=interconnect
- `display_event` + `CRTC` raw → `DISPLAY`, conf=0.85, subsystem=display

### Qualcomm (15 IP blocks from `ip_definitions.py`)
`ADRENO, SMMU, BIMC, CPUss, RPM, USB3, QMP, UFS, PCIe, LLCC, WCSS, LPASS, CAMSS, VENUS, PMIC`

Key mappings (from PRD §5.2):
- `gpu_event` + `kgsl`/`adreno` raw → `ADRENO`, conf=0.92, subsystem=gpu
- `qcom_adsp_crash` → `LPASS`, conf=0.98, subsystem=remoteproc
- `smmu_fault` + `arm-smmu` raw → `SMMU`, conf=0.90, subsystem=interconnect
- `ufs_event` + `ufshcd` raw → `UFS`, conf=0.92, subsystem=storage
- `spmi_event` → `PMIC`, conf=0.90, subsystem=power

### AMD (from `ip_definitions.py`, PRD §6.2)
`GFX_HUB, SDMA, VCN, MMHUB, HBM_ECC, RAS_HUB, PSP, PSP_SEV, PSP_TEE, HSMP, NBIO, IOMMU, PCIE_ROOT, PMFW, SMU, SVI3, CXL_ROOT, CXL_MEM, DCN, VCN_ENC`

Key mappings:
- `gpu_event` + `gfx` raw → `GFX_HUB`, conf=0.90, subsystem=gpu
- `amd_psp_fw_fail` → `PSP`, conf=0.98, subsystem=firmware
- `ras_event` → `RAS_HUB`, conf=0.95, subsystem=debug
- `memory_poison` → `HBM_ECC`, conf=0.95, subsystem=memory
- `power_event` + PMFW raw → `PMFW`, conf=0.88, subsystem=power

### NVIDIA (PRD §7.2)
`GR_ENGINE, COPY_ENGINE, GSP, GR_ENGINE (reset), PCIE_ROOT, FB_HUB, DISP_ENGINE, NVENC, PMU`

Key mappings:
- `firmware_event` + `GSP` raw → `GSP`, conf=0.95, subsystem=firmware
- `gpu_event` + `gr` raw → `GR_ENGINE`, conf=0.88, subsystem=gpu
- `reset_event` → `GR_ENGINE`, conf=0.85, subsystem=gpu

### Generic (fallback)
Minimal IP map by token_type only, conf=0.40, never raises.

---

## 6. Known Issues Data

Each provider has `get_known_issues()` returning a list. Minimum counts:
- Intel: 18 entries (including INTEL-DG2-001, INTEL-PVC-001, INTEL-TBT-001)
- Qualcomm: 20 entries (including QCOM-ADSP-001, QCOM-UFS-001, QCOM-SMMU-001)
- AMD: 22 entries (including AMD-MI300-001, AMD-MI200-001, AMD-PSP-001, AMD-RDNA2-001)
- NVIDIA: 12 entries (including NV-HOPPER-001, NV-AMPERE-001)
- Generic: 0 entries (returns `[]`)

---

## 7. Test Strategy

### Location
```
tests/test_providers/
├── __init__.py
├── test_intel_provider.py     # 28 tests
├── test_qualcomm_provider.py  # 30 tests
├── test_amd_provider.py       # 30 tests
├── test_nvidia_provider.py    # 20 tests
├── test_generic_provider.py   # 15 tests
└── test_provider_registry.py  # 12 tests
```

### Per-provider test coverage (template, repeated per provider)
```
detect():
  - Returns float ∈ [0.0, 1.0]
  - Returns ≥ 0.5 on matching fixture log (known keywords)
  - Returns 0.0 on completely alien log (competitor keywords only)

classify_ip():
  - Returns [] for empty token_stream
  - Returns [] for unknown token types (never raises)
  - Returns correct IP block for each key token type (one test per IP block)
  - All returned dicts have "ip", "confidence", "subsystem", "notes" keys
  - confidence ∈ [0.0, 1.0] for all entries

resolve_cascade():
  - Returns list[str]
  - Primary fault IP is first element
  - Returns [] for empty ip_hits

get_playbook():
  - Returns dict for known IP blocks
  - Returns {} (not raises) for unknown IP blocks

decode_registers():
  - Returns dict for known register names
  - Returns {} fields for unknown register names (not raises)

get_known_issues():
  - Returns list of dicts with required schema keys
  - Filters by chip_gen correctly
  - Returns [] for unknown chip_gen
```

### Registry tests
```
test_provider_registry.py:
  - auto_discover() finds all 5 providers
  - detect_provider() returns IntelProvider for Intel log
  - detect_provider() returns QualcommProvider for Qualcomm log
  - detect_provider() returns AMDProvider for AMD log
  - detect_provider() returns NvidiaProvider for NVIDIA log
  - detect_provider() returns GenericProvider for unknown log
  - GenericProvider is checked last (always matches)
  - list_providers() returns all 5 names
  - match_known_issues() returns AMD-MI300-001 for MI300X gpu_hang fixture
  - No provider raises for any valid or invalid input
  - Registry survives provider that raises in detect()
  - All providers are instances of SoCProvider
```

### Fixtures (`tests/fixtures/phase5/`)
Per PRD §11:
```
intel_dg2_guc_hang.log
intel_pvc_sriov_reset.log
intel_mtl_tbt_smmu.log
qcom_sm8550_adsp_suspend.log
qcom_sdm845_ufs_phy.log
amd_mi300_mmhub_stall.log
amd_navi21_gfx_hang.log
amd_psp_fw_fail.log
nvidia_h100_gsp_timeout.log
generic_unknown_soc.log
```

---

## 8. Code Style

- Follow existing provider style: no docstrings on simple methods, `_DETECT_KEYWORDS` list pattern
- Type annotations on all public methods (match `soc_provider.py` signatures exactly)
- Data in `ip_definitions.py` (not inline in `provider.py`) — keeps logic separate from data
- No external dependencies: stdlib + existing `soctriage` package only
- `classify_ip()` must never raise — wrap with try/except if pattern matching is risky
- Tests use `pytest`, no mocking of core modules
- `from __future__ import annotations` at top of every new file

---

## 9. CI Gate After Phase 5

| Metric | Target |
|--------|--------|
| New tests passing | 135 / 135 |
| Total suite | ~803 passed |
| Existing XFAILs | Still 6 (Phase 1/3 — not converted by Phase 5) |
| mypy on `providers/` | 0 errors |
| Coverage on new provider files | ≥ 85% |

---

## 10. Definition of Done

- [ ] All 135 AC-P5 tests pass
- [ ] `classify_ip()` never raises for any token type on all 10 Phase 5 fixtures
- [ ] `get_known_issues()` returns valid schema on all provider/chip_gen combos
- [ ] `detect_provider()` selects correct provider for each of the 10 Phase 5 fixtures
- [ ] Locked files unchanged (`git diff` on immutable files shows no changes)
- [ ] `mypy soctriage/providers/` → 0 errors
- [ ] Full pipeline runs: `tokenize → assemble → classify → analyse → provider.classify_ip()` on all fixtures without error

---

*Please confirm the 4 PRD discrepancies (§ top) before proceeding to planning.*
