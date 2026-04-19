# Phase 5 Implementation Plan — Provider Implementations
## SoCTriage v5.0.0

---

## Dependency Graph

```
T1: Infrastructure (fixtures dir, test package)
    │
    ├── T2: GenericProvider (simplest, no ip_definitions)
    ├── T3: IntelProvider   (ip_definitions + provider + 28 tests + 3 fixtures)
    ├── T4: QualcommProvider(ip_definitions + provider + 30 tests + 2 fixtures)
    ├── T5: AMDProvider     (ip_definitions + provider + 30 tests + 3 fixtures)
    └── T6: NVIDIAProvider  (ip_definitions + provider + 20 tests + 1 fixture)
              │
              └── T7: Registry tests (12 tests, needs all 5 providers)
                        │
                        └── T8: Final verification (full suite + mypy + locked file check)
```

T2–T6 are **parallel** — no inter-provider dependencies.
T7 requires T2–T6 complete. T8 requires T7 complete.

---

## One-time Alignment Notes

Before implementing, confirm against actual codebase (not PRD):

| Item | Actual (codebase) | PRD claim |
|------|-------------------|-----------|
| AMD IP blocks | `GFX, SDMA, GMC, VCN, PSP, RLC, MEC, KFD, IH, DCN, MMHUB, GCHUB, JPEG, SMU` | Different names |
| NVIDIA IP blocks | `GPC, SM, L2, FBPA, NVLink, PCIe, PMU, SEC2, GSP, DISPLAY` | Different names |
| Generic ip_definitions.py | Does not exist | PRD assumes it does |
| ProviderRegistry | `core/provider_registry.py` (complete) | PRD says to create |
| detect() signature | `detect(raw_log: str) -> float` | PRD says bool |

**Rule**: Use actual ip_definitions.py IP block names as canonical; the PRD's names are guidance only.

---

## T1 — Test Infrastructure

**Goal**: Create the empty scaffolding needed before any provider tests can run.

### Files to create
- `tests/test_providers/__init__.py` — empty
- `tests/fixtures/phase5/` — empty directory (populated per provider task)

### Acceptance criteria
- `pytest tests/test_providers/` runs without import errors (zero tests collected is fine)
- `tests/fixtures/phase5/` directory exists

### Verification
```bash
python3 -m pytest tests/test_providers/ --collect-only
ls tests/fixtures/phase5/
```

---

## T2 — GenericProvider

**Goal**: Implement `classify_ip()` (minimal fallback logic), write 15 tests.

`detect()` is already correct (returns 0.1). The other no-op stubs are correct as-is.

### Files to modify
- `soctriage/providers/generic/provider.py` — implement `classify_ip()` only

### classify_ip() spec
Input `{"type": token_type, "raw": raw}` → first-match against this table:

| token_type | IP | confidence | subsystem |
|---|---|---|---|
| `gpu_event` | `GPU` | 0.40 | gpu |
| `firmware_event` | `FIRMWARE` | 0.40 | firmware |
| `memory_event` | `MEMORY` | 0.40 | memory |
| `pcie_error` | `PCIE` | 0.40 | interconnect |
| `smmu_fault` | `IOMMU` | 0.40 | interconnect |
| `storage_fail` | `STORAGE` | 0.40 | storage |
| `power_fault` | `POWER` | 0.40 | power |

Returns `[]` for unknown types. Never raises.
`notes` field always `"generic fallback"`.

### Test file: `tests/test_providers/test_generic_provider.py` (15 tests)

```
T2-01  name() returns "Generic"
T2-02  detect() returns 0.1 for Intel log (doesn't raise)
T2-03  detect() returns 0.1 for empty string
T2-04  detect() returns float in [0.0, 1.0]
T2-05  classify_ip([]) returns []
T2-06  classify_ip with unknown type returns []
T2-07  classify_ip(gpu_event) returns [{ip: GPU, conf: 0.40, subsystem: gpu, notes: ...}]
T2-08  classify_ip(firmware_event) → FIRMWARE
T2-09  classify_ip(pcie_error) → PCIE
T2-10  classify_ip(smmu_fault) → IOMMU
T2-11  classify_ip result has all 4 required keys
T2-12  resolve_cascade([]) returns []
T2-13  get_playbook("unknown") returns {} without raising
T2-14  get_known_issues("any_chip", []) returns []
T2-15  GenericProvider is instance of SoCProvider
```

### Fixture: `tests/fixtures/phase5/generic_unknown_soc.log`
Plain kernel log with no vendor-specific strings. Generic provider should detect() → 0.1.

### Verification
```bash
python3 -m pytest tests/test_providers/test_generic_provider.py -v
```
Expected: 15 passed.

---

## T3 — IntelProvider

**Goal**: Populate Intel ip_definitions.py data; implement all 8 methods; write 28 tests; create 3 fixture logs.

### Files to modify
- `soctriage/providers/intel/ip_definitions.py`
- `soctriage/providers/intel/provider.py`

### ip_definitions.py — data to populate

**IP_PATTERNS**: `dict[str, list[tuple[str, float]]]`
Maps token_type → list of `(raw_pattern_substring, confidence)` tuples.
First match wins per entry.

```python
IP_PATTERNS = {
    "firmware_event": [
        ("GuC", 0.95),   # → GUC
        ("HuC", 0.95),   # → HUC
        ("GSC", 0.95),   # → GSC
    ],
    "gpu_event": [
        ("gfx_0", 0.90), ("rcs0", 0.90),  # → RENDER
        ("bcs0", 0.88),                    # → BLITTER
        ("vcs0", 0.88), ("vcs1", 0.88),   # → MEDIA
        ("vecs0", 0.88),                   # → MEDIA
    ],
    "reset_event": [("GPU HANG", 0.85)],  # → RENDER
    "intel_gtt_event": [("GGTT", 0.90), ("GTT", 0.90)],  # → GGTT
    "smmu_fault": [("intel_iommu", 0.85), ("IOMMU", 0.85)],  # → GGTT
    "pcie_error": [("i915", 0.80)],       # → PCIe
    "display_event": [("CRTC", 0.85), ("pipe", 0.80)],  # → DISPLAY
    "intel_pmc_event": [("PMC", 0.88)],   # → PMC
}
```

**CASCADE_GRAPH**: Fault propagation chains.
```python
CASCADE_GRAPH = {
    "GUC":    ["RENDER", "BLITTER", "MEDIA"],
    "HUC":    ["MEDIA"],
    "RENDER": ["GT"],
    "PCIe":   ["GGTT", "RENDER"],
    "GGTT":   ["RENDER", "BLITTER"],
    "PMC":    ["GT"],
}
```

**PLAYBOOK**: Fix steps per IP block (at least GUC, RENDER, PCIe, GGTT).
```python
PLAYBOOK = {
    "GUC": {
        "steps": [
            "Check kernel version >= 6.3 (required for DG2 GuC 70.bin)",
            "Verify /lib/firmware/i915/dg2_guc_70.bin exists",
            "Try: modprobe -r i915 && modprobe i915 enable_guc=3",
            "If persists: disable GuC submission with i915.enable_guc=0",
        ],
        "references": ["https://gitlab.freedesktop.org/drm/intel/issues/7546"],
        "notes": "GuC submission required for DG2+. Kernel < 6.3 does not ship correct firmware.",
    },
    "RENDER": { ... },
    "PCIe": { ... },
    "GGTT": { ... },
}
```

**REGISTER_MAPS**: At least GUC_STATUS, RING_HEAD, RING_TAIL.
```python
REGISTER_MAPS = {
    "GUC_STATUS": {
        0x1: "GUC_READY",
        0x2: "GUC_UKERNEL_ACTIVE",
        0x4: "GUC_RESERVED",
    },
    ...
}
```

**HANG_RULES**: At least 3 entries.
```python
HANG_RULES = [
    HangRule(mode="HANG",      signals=[r"ring timeout", r"GPU HANG"],     confidence=0.90),
    HangRule(mode="STALL",     signals=[r"engine stall", r"CS stall"],     confidence=0.75),
    HangRule(mode="HARD-HANG", signals=[r"GPU HANG.*reset failed"],        confidence=0.95),
]
```

### provider.py — method implementations

**detect()**: Existing keyword counting is fine; add regex bonus (+0.15) for:
`r"i915.*firmware|GuC.*fail|GPU HANG.*DG2"` patterns. Cap at 1.0.

**classify_ip()**: Walk token_stream, for each token try IP_PATTERNS lookup.
Map matched pattern to IP block name using a secondary lookup:
```python
_PATTERN_TO_IP = {
    "firmware_event": {"GuC": "GUC", "HuC": "HUC", "GSC": "GSC"},
    "gpu_event": {"gfx_0": "RENDER", "rcs0": "RENDER", "bcs0": "BLITTER",
                  "vcs0": "MEDIA", "vcs1": "MEDIA", "vecs0": "MEDIA"},
    "reset_event": {"GPU HANG": "RENDER"},
    ...
}
```
Return first match per token. Multiple tokens → multiple entries (deduped by IP).

**resolve_cascade()**: Walk ip_hits, build chain using CASCADE_GRAPH BFS from primary IP.

**get_playbook()**: Return PLAYBOOK.get(ip_block, {}).

**decode_registers()**: For each register in input, look up in REGISTER_MAPS,
decode active bits, return `{reg: {"raw": val, "fields": {name: bool}}}`.

**get_hang_rules()**: Return HANG_RULES.

**get_known_issues()**: 18-entry list, filter by chip_gen + symptom overlap.

### Test file: `tests/test_providers/test_intel_provider.py` (28 tests)

```
T3-01  name() returns "Intel Xe/Gen Graphics"
T3-02  detect() returns float in [0.0, 1.0]
T3-03  detect() returns >= 0.5 on intel_dg2_guc_hang.log content
T3-04  detect() returns 0.0 on amdgpu-only log
T3-05  classify_ip([]) returns []
T3-06  classify_ip(unknown type) returns [] without raising
T3-07  firmware_event+GuC → GUC, conf=0.95, subsystem=firmware
T3-08  firmware_event+HuC → HUC, conf=0.95, subsystem=firmware
T3-09  firmware_event+GSC → GSC, conf=0.95, subsystem=firmware
T3-10  gpu_event+gfx_0 → RENDER, conf=0.90, subsystem=gpu
T3-11  gpu_event+bcs0 → BLITTER, conf=0.88, subsystem=gpu
T3-12  gpu_event+vcs0 → MEDIA, conf=0.88, subsystem=gpu
T3-13  reset_event+GPU HANG → RENDER, conf=0.85, subsystem=gpu
T3-14  intel_gtt_event+GGTT → GGTT, conf=0.90, subsystem=interconnect
T3-15  smmu_fault+intel_iommu → GGTT, conf=0.85, subsystem=interconnect
T3-16  pcie_error+i915 → PCIe, conf=0.80, subsystem=interconnect
T3-17  display_event+CRTC → DISPLAY, conf=0.85, subsystem=display
T3-18  classify_ip result has ip, confidence, subsystem, notes keys
T3-19  resolve_cascade([]) returns []
T3-20  resolve_cascade(GUC hit) starts with GUC
T3-21  resolve_cascade follows CASCADE_GRAPH (GUC → includes RENDER)
T3-22  get_playbook("GUC") returns dict with "steps" key
T3-23  get_playbook("unknown_ip") returns {}
T3-24  get_register_maps() returns dict (non-empty)
T3-25  decode_registers({"GUC_STATUS": 0x3}) returns dict with "fields"
T3-26  decode_registers({"UNKNOWN_REG": 0xFF}) returns gracefully (no raise)
T3-27  get_known_issues("intel_dg2", ["firmware_event"]) returns >= 1 result including INTEL-DG2-001
T3-28  get_hang_rules() returns list of HangRule with len >= 3
```

### Fixtures (3 files)
- `intel_dg2_guc_hang.log` — DG2 GuC load fail → GPU hang (contains `i915`, `GuC`, `firmware`, `GPU HANG`)
- `intel_pvc_sriov_reset.log` — PVC SR-IOV reset storm (contains `i915`, `SR-IOV`, `PCIe`, `reset`)
- `intel_mtl_tbt_smmu.log` — MTL Thunderbolt SMMU fault (contains `i915`, `thunderbolt`, `intel_iommu`)

### Verification
```bash
python3 -m pytest tests/test_providers/test_intel_provider.py -v
```
Expected: 28 passed.

---

## T4 — QualcommProvider

**Goal**: Populate Qualcomm ip_definitions.py; implement all 8 methods; write 30 tests; create 2 fixture logs.

### Files to modify
- `soctriage/providers/qualcomm/ip_definitions.py`
- `soctriage/providers/qualcomm/provider.py`

### ip_definitions.py

**IP_PATTERNS** (token_type → `[(raw_substring, confidence)]`):
```python
IP_PATTERNS = {
    "gpu_event":         [("kgsl", 0.92), ("adreno", 0.92)],          # → ADRENO
    "qcom_adsp_crash":   [("", 0.98)],                                 # → LPASS (always)
    "qcom_cdsp_crash":   [("", 0.98)],                                 # → WCSS
    "smmu_fault":        [("arm-smmu", 0.90), ("qcom_smmu", 0.90)],   # → SMMU
    "ufs_event":         [("ufshcd", 0.92), ("ufs", 0.88)],           # → UFS
    "phy_init_fail":     [("ufs", 0.90)],                              # → QMP
    "phy_calibration_fail": [("pcie", 0.88)],                         # → QMP
    "spmi_event":        [("PM8", 0.90), ("PMI", 0.88), ("spmi", 0.85)],  # → PMIC
    "remoteproc_crash":  [("qcom_q6v5", 0.92)],                       # → LPASS/CPUss
    "pcie_error":        [("", 0.85)],                                 # → PCIe
    "display_event":     [("mdss", 0.90), ("dpu", 0.90)],             # → CAMSS/VENUS
    "power_event":       [("krait", 0.80), ("cpufreq", 0.75)],        # → RPM
    "wdt_event":         [("qcom-wdt", 0.95), ("apps_wdt", 0.95)],    # → CPUss
}
```

**CASCADE_GRAPH**:
```python
CASCADE_GRAPH = {
    "LPASS": ["CPUss", "SMMU"],
    "WCSS":  ["CPUss", "SMMU"],
    "SMMU":  ["ADRENO", "UFS", "PCIe"],
    "QMP":   ["UFS", "PCIe"],
    "PMIC":  ["CPUss", "RPM"],
}
```

**PLAYBOOK**: At least LPASS, SMMU, UFS, ADRENO entries.

**REGISTER_MAPS**: SMMU_FSR, GPU_STATUS, RPM_STATUS (at minimum).

**HANG_RULES**: At least 3 (ADSP crash, GPU hang, WDT fire).

**KNOWN_ISSUES**: 20 entries (QCOM-ADSP-001, QCOM-UFS-001, QCOM-SMMU-001, + 17 more).

### Test file: `tests/test_providers/test_qualcomm_provider.py` (30 tests)

```
T4-01..04  name(), detect() float range, detect >= 0.5 on qcom log, detect 0.0 on intel log
T4-05..06  classify_ip([]) = [], unknown type = []
T4-07      gpu_event+kgsl → ADRENO, conf=0.92, subsystem=gpu
T4-08      gpu_event+adreno → ADRENO
T4-09      qcom_adsp_crash → LPASS, conf=0.98, subsystem=remoteproc
T4-10      qcom_cdsp_crash → WCSS, conf=0.98, subsystem=remoteproc
T4-11      smmu_fault+arm-smmu → SMMU, conf=0.90, subsystem=interconnect
T4-12      ufs_event+ufshcd → UFS, conf=0.92, subsystem=storage
T4-13      spmi_event+PM8 → PMIC, conf=0.90, subsystem=power
T4-14      remoteproc_crash+qcom_q6v5 → LPASS or CPUss
T4-15      pcie_error → PCIe
T4-16      display_event+mdss → CAMSS or VENUS
T4-17      wdt_event → CPUss
T4-18      classify_ip result has all 4 required keys
T4-19..21  resolve_cascade([]) = [], LPASS→chain includes CPUss, follows CASCADE_GRAPH
T4-22..23  get_playbook("SMMU") has steps key; get_playbook("X") = {}
T4-24      get_register_maps() non-empty dict
T4-25..26  decode_registers known reg; decode_registers unknown reg graceful
T4-27      get_known_issues("qcom_sm8550", ["qcom_adsp_crash"]) includes QCOM-ADSP-001
T4-28      get_known_issues("unknown_chip", []) returns []
T4-29      get_hang_rules() returns >= 3 HangRule objects
T4-30      QualcommProvider is instance of SoCProvider
```

### Fixtures (2 files)
- `qcom_sm8550_adsp_suspend.log` — SM8550 ADSP crash on suspend (contains `msm`, `qcom`, `ADSP`, `remoteproc`)
- `qcom_sdm845_ufs_phy.log` — SDM845 UFS PHY calibration fail (contains `qcom`, `ufshcd`, `phy`, `UFS`)

### Verification
```bash
python3 -m pytest tests/test_providers/test_qualcomm_provider.py -v
```
Expected: 30 passed.

---

## T5 — AMDProvider

**Goal**: Populate AMD ip_definitions.py; implement all 8 methods; write 30 tests; create 3 fixture logs.

**Note**: The actual `amd/ip_definitions.py` uses `GFX, SDMA, GMC, VCN, PSP, RLC, MEC, KFD, IH, DCN, MMHUB, GCHUB, JPEG, SMU`. Use these as canonical IP names (not the spec's `GFX_HUB` etc.).

### Files to modify
- `soctriage/providers/amd/ip_definitions.py`
- `soctriage/providers/amd/provider.py`

### ip_definitions.py

**IP_PATTERNS**:
```python
IP_PATTERNS = {
    "gpu_event":         [("gfx", 0.90), ("sdma", 0.90), ("vcn", 0.90)],  # GFX / SDMA / VCN
    "reset_event":       [("GPU reset", 0.85), ("amdgpu", 0.80)],          # GFX
    "memory_event":      [("VRAM", 0.90), ("mmhub", 0.90), ("GMC", 0.88)], # MMHUB / GMC
    "memory_poison":     [("HBM", 0.95), ("ECC", 0.92)],                   # GMC (ECC)
    "ras_event":         [("RAS", 0.95), ("CE", 0.88), ("UE", 0.90)],      # RLC (RAS)
    "amd_psp_fw_fail":   [("", 0.98)],                                     # PSP (always)
    "amd_psp_event":     [("PSP", 0.90)],                                  # PSP
    "amd_sev_event":     [("SEV", 0.95)],                                  # PSP (SEV)
    "power_event":       [("PMFW", 0.88), ("voltage", 0.80)],              # SMU
    "thermal_event":     [("TJ_MAX", 0.90), ("TDP", 0.88), ("temp", 0.80)], # SMU
    "smmu_fault":        [("AMD IOMMU", 0.85), ("amd_iommu", 0.85)],       # IH
    "pcie_error":        [("NBIO", 0.85), ("PCIe", 0.80)],                 # IH
    "display_event":     [("DCN", 0.88), ("CRTC", 0.85)],                  # DCN
}
```

**CASCADE_GRAPH**:
```python
CASCADE_GRAPH = {
    "PSP":   ["GFX", "SDMA", "VCN"],
    "GMC":   ["GFX", "SDMA"],
    "IH":    ["GFX", "SDMA", "VCN"],
    "SMU":   ["GFX"],
    "GFX":   ["KFD"],
}
```

**PLAYBOOK**: At least PSP, GFX, GMC, SMU entries.

**REGISTER_MAPS**: GRBM_STATUS, CP_STALLED_STAT, SDMA0_STATUS (minimum).
```python
REGISTER_MAPS = {
    "GRBM_STATUS": {
        0x80000000: "GUI_ACTIVE",
        0x40000000: "CP_RQ_PENDING",
        0x20000000: "CP_ME_BUSY",
    },
    ...
}
```

**HANG_RULES**: At least 3 (GPU hang, RAS UE, PSP fail).

**KNOWN_ISSUES**: 22 entries (AMD-MI300-001, AMD-MI200-001, AMD-PSP-001, AMD-RDNA2-001, + 18 more).

### Test file: `tests/test_providers/test_amd_provider.py` (30 tests)

```
T5-01..04  name(), detect() float range, detect >= 0.5 on amd log, detect 0.0 on nvidia log
T5-05..06  classify_ip([]) = [], unknown type = []
T5-07      gpu_event+gfx → GFX, conf=0.90, subsystem=gpu
T5-08      gpu_event+sdma → SDMA, conf=0.90, subsystem=gpu
T5-09      gpu_event+vcn → VCN, conf=0.90, subsystem=gpu
T5-10      reset_event+GPU reset → GFX, conf=0.85, subsystem=gpu
T5-11      memory_event+VRAM → MMHUB or GMC, subsystem=memory
T5-12      memory_poison+HBM → GMC (ECC), conf=0.95, subsystem=memory
T5-13      ras_event+UE → RLC (RAS), conf=0.90, subsystem=debug
T5-14      amd_psp_fw_fail → PSP, conf=0.98, subsystem=firmware
T5-15      amd_psp_event+PSP → PSP, subsystem=firmware
T5-16      amd_sev_event+SEV → PSP (SEV), conf=0.95, subsystem=security
T5-17      power_event+PMFW → SMU, conf=0.88, subsystem=power
T5-18      thermal_event+TJ_MAX → SMU, conf=0.90, subsystem=power
T5-19      smmu_fault+AMD IOMMU → IH, conf=0.85
T5-20      display_event+DCN → DCN
T5-21      classify_ip result has all 4 required keys
T5-22..24  resolve_cascade([]) = [], PSP→chain includes GFX, chain is list[str]
T5-25..26  get_playbook("PSP") has steps; get_playbook("X") = {}
T5-27      get_register_maps() returns GRBM_STATUS key
T5-28      decode_registers({"GRBM_STATUS": 0xC0000000}) returns fields dict
T5-29      get_known_issues("amd_cdna3", ["gpu_hang", "memory_event"]) includes AMD-MI300-001
T5-30      get_hang_rules() returns >= 3 HangRule objects
```

### Fixtures (3 files)
- `amd_mi300_mmhub_stall.log` — MI300X MMHUB stall + panic (contains `amdgpu`, `GRBM_STATUS`, `mmhub`, `reset`)
- `amd_navi21_gfx_hang.log` — Navi21 GFX pipe hang (contains `amdgpu`, `gfx`, `CP_STALLED`, `ring`)
- `amd_psp_fw_fail.log` — Navi31 PSP firmware unsigned (contains `amdgpu`, `PSP`, `firmware`, `fail`)

### Verification
```bash
python3 -m pytest tests/test_providers/test_amd_provider.py -v
```
Expected: 30 passed.

---

## T6 — NVIDIAProvider

**Goal**: Populate NVIDIA ip_definitions.py; implement all 8 methods; write 20 tests; create 1 fixture log.

**Canonical IP blocks** (from actual `nvidia/ip_definitions.py`):
`GPC, SM, L2, FBPA, NVLink, PCIe, PMU, SEC2, GSP, DISPLAY`

### Files to modify
- `soctriage/providers/nvidia/ip_definitions.py`
- `soctriage/providers/nvidia/provider.py`

### ip_definitions.py

**IP_PATTERNS**:
```python
IP_PATTERNS = {
    "gpu_event":      [("gr", 0.88), ("GPC", 0.88), ("SM", 0.85)],      # GPC / SM
    "reset_event":    [("GPU reset", 0.85), ("nvidia", 0.80)],           # GPC
    "firmware_event": [("GSP", 0.95)],                                   # GSP
    "timeout_event":  [("channel", 0.80), ("timeout", 0.78)],            # GPC
    "pcie_error":     [("nvidia", 0.85), ("PCIe", 0.80)],               # PCIe
    "memory_event":   [("FB", 0.88), ("ECC", 0.90), ("FBPA", 0.90)],    # FBPA / L2
    "display_event":  [("DISP", 0.85), ("CRTC", 0.82)],                 # DISPLAY
    "power_event":    [("PMU", 0.85), ("TDP", 0.82)],                   # PMU
}
```

**CASCADE_GRAPH**:
```python
CASCADE_GRAPH = {
    "GSP":   ["GPC", "SM"],
    "GPC":   ["SM", "L2"],
    "FBPA":  ["L2", "GPC"],
    "PCIe":  ["GPC"],
    "NVLink":["GPC", "FBPA"],
}
```

**PLAYBOOK**: At least GSP, GPC, PCIe entries.

**REGISTER_MAPS**: XID_STATUS, PGRAPH_STATUS, PFIFO_STATUS (minimum).

**HANG_RULES**: At least 2 (GSP timeout, GPC hang).

**KNOWN_ISSUES**: 12 entries (NV-HOPPER-001, NV-AMPERE-001, + 10 more).

### Test file: `tests/test_providers/test_nvidia_provider.py` (20 tests)

```
T6-01..04  name(), detect() float range, detect >= 0.5 on nvidia log, detect 0.0 on qcom log
T6-05..06  classify_ip([]) = [], unknown type = []
T6-07      gpu_event+gr → GPC, conf=0.88, subsystem=gpu
T6-08      gpu_event+GPC → GPC
T6-09      reset_event+GPU reset → GPC, conf=0.85
T6-10      firmware_event+GSP → GSP, conf=0.95, subsystem=firmware
T6-11      pcie_error+nvidia → PCIe, conf=0.85
T6-12      memory_event+FBPA → FBPA, conf=0.90, subsystem=memory
T6-13      display_event+DISP → DISPLAY
T6-14      power_event+PMU → PMU, subsystem=power
T6-15      classify_ip result has all 4 required keys
T6-16..17  resolve_cascade([]) = [], GSP→chain includes GPC
T6-18      get_playbook("GSP") has steps key; get_playbook("X") = {}
T6-19      get_known_issues("nvidia_hopper", ["firmware_event"]) includes NV-HOPPER-001
T6-20      get_hang_rules() returns >= 2 HangRule objects
```

### Fixture (1 file)
- `nvidia_h100_gsp_timeout.log` — H100 GSP timeout during MIG init (contains `nvidia`, `NVRM`, `GSP`, `timeout`, `XID`)

### Verification
```bash
python3 -m pytest tests/test_providers/test_nvidia_provider.py -v
```
Expected: 20 passed.

---

## T7 — Registry Tests

**Goal**: Verify ProviderRegistry auto-discovery and detect_provider() routing with all 5 real providers.

**Depends on**: T2–T6 all complete.

### File to create
- `tests/test_providers/test_provider_registry.py` (12 tests)

### Test list

```
T7-01  auto_discover() finds exactly 5 providers
T7-02  list_providers() returns all 5 names
T7-03  All registered providers are SoCProvider instances
T7-04  detect_provider(intel_dg2_guc_hang.log content) → IntelProvider
T7-05  detect_provider(qcom_sm8550_adsp_suspend.log content) → QualcommProvider
T7-06  detect_provider(amd_mi300_mmhub_stall.log content) → AMDProvider
T7-07  detect_provider(nvidia_h100_gsp_timeout.log content) → NVIDIAProvider
T7-08  detect_provider(generic_unknown_soc.log content) → GenericProvider
T7-09  GenericProvider is not selected when a vendor-specific provider matches
T7-10  Registry survives a provider that raises during detect() (logs warning, continues)
T7-11  classify_ip() never raises for any of the 10 Phase 5 fixtures (parametrized)
T7-12  Full pipeline: tokenize→assemble→detect_provider→classify_ip on intel fixture without error
```

### Verification
```bash
python3 -m pytest tests/test_providers/test_provider_registry.py -v
```
Expected: 12 passed.

---

## T8 — Final Verification

**Goal**: Full suite passes; mypy clean; locked files unchanged.

### Steps

```bash
# 1. Full test suite
python3 -m pytest -q
# Expected: ~803 passed, 6 xfailed, 1 xpassed, 0 failed

# 2. mypy on providers
python3 -m mypy soctriage/providers/ --ignore-missing-imports
# Expected: 0 errors

# 3. Locked file check
git diff HEAD -- soctriage/core/soc_provider.py \
                 soctriage/core/token_rule.py \
                 soctriage/core/tokenizer.py \
                 soctriage/core/assembler.py \
                 soctriage/core/classifier.py \
                 soctriage/core/cascade.py \
                 soctriage/core/ascii_diagram.py \
                 soctriage/cli.py \
                 soctriage/core/reporter.py
# Expected: empty (no output)

# 4. classify_ip safety check — no provider raises for any fixture
python3 -c "
import pathlib
from soctriage.core.provider_registry import ProviderRegistry
from pathlib import Path
reg = ProviderRegistry()
reg.auto_discover(Path('soctriage/providers'))
for f in Path('tests/fixtures/phase5').iterdir():
    raw = f.read_text()
    p = reg.detect_provider(raw)
    tokens = [{'type': 'gpu_event', 'raw': raw[:200]}]
    try:
        result = p.classify_ip(tokens)
        print(f'OK {f.name}: {p.name()} → {result}')
    except Exception as e:
        print(f'FAIL {f.name}: {e}')
"
```

---

## Summary: 135 Tests Across 6 Files

| Task | File | Tests |
|------|------|-------|
| T2 | test_generic_provider.py | 15 |
| T3 | test_intel_provider.py | 28 |
| T4 | test_qualcomm_provider.py | 30 |
| T5 | test_amd_provider.py | 30 |
| T6 | test_nvidia_provider.py | 20 |
| T7 | test_provider_registry.py | 12 |
| **Total** | | **135** |

---

## Commit Strategy

One atomic commit per task (T2–T7), each passing its own tests before commit.
Message format: `soctriage phase 5: <provider> provider + <N> tests`

Final commit (T8): `soctriage phase 5: verified — 803 passed · 0 failed`
