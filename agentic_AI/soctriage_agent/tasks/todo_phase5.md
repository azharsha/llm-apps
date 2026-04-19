# Phase 5 Todo — Provider Implementations

## T1 — Infrastructure
- [ ] Create `tests/test_providers/__init__.py`
- [ ] Create `tests/fixtures/phase5/` directory
- [ ] Verify: `pytest tests/test_providers/ --collect-only` runs clean

## T2 — GenericProvider (15 tests)
- [ ] Implement `classify_ip()` in `soctriage/providers/generic/provider.py`
- [ ] Add `get_known_issues()` non-ABC method (returns `[]`)
- [ ] Create `tests/fixtures/phase5/generic_unknown_soc.log`
- [ ] Create `tests/test_providers/test_generic_provider.py` (15 tests)
- [ ] Verify: 15 passed

## T3 — IntelProvider (28 tests)
- [ ] Populate `soctriage/providers/intel/ip_definitions.py` (IP_PATTERNS, CASCADE_GRAPH, PLAYBOOK, REGISTER_MAPS, HANG_RULES, 18 KNOWN_ISSUES)
- [ ] Implement all 8 methods + `get_known_issues()` in `soctriage/providers/intel/provider.py`
- [ ] Create `tests/fixtures/phase5/intel_dg2_guc_hang.log`
- [ ] Create `tests/fixtures/phase5/intel_pvc_sriov_reset.log`
- [ ] Create `tests/fixtures/phase5/intel_mtl_tbt_smmu.log`
- [ ] Create `tests/test_providers/test_intel_provider.py` (28 tests)
- [ ] Verify: 28 passed

## T4 — QualcommProvider (30 tests)
- [ ] Populate `soctriage/providers/qualcomm/ip_definitions.py` (IP_PATTERNS, CASCADE_GRAPH, PLAYBOOK, REGISTER_MAPS, HANG_RULES, 20 KNOWN_ISSUES)
- [ ] Implement all 8 methods + `get_known_issues()` in `soctriage/providers/qualcomm/provider.py`
- [ ] Create `tests/fixtures/phase5/qcom_sm8550_adsp_suspend.log`
- [ ] Create `tests/fixtures/phase5/qcom_sdm845_ufs_phy.log`
- [ ] Create `tests/test_providers/test_qualcomm_provider.py` (30 tests)
- [ ] Verify: 30 passed

## T5 — AMDProvider (30 tests)
- [ ] Populate `soctriage/providers/amd/ip_definitions.py` (IP_PATTERNS, CASCADE_GRAPH, PLAYBOOK, REGISTER_MAPS, HANG_RULES, 22 KNOWN_ISSUES)
- [ ] Implement all 8 methods + `get_known_issues()` in `soctriage/providers/amd/provider.py`
- [ ] Create `tests/fixtures/phase5/amd_mi300_mmhub_stall.log`
- [ ] Create `tests/fixtures/phase5/amd_navi21_gfx_hang.log`
- [ ] Create `tests/fixtures/phase5/amd_psp_fw_fail.log`
- [ ] Create `tests/test_providers/test_amd_provider.py` (30 tests)
- [ ] Verify: 30 passed

## T6 — NVIDIAProvider (20 tests)
- [ ] Populate `soctriage/providers/nvidia/ip_definitions.py` (IP_PATTERNS, CASCADE_GRAPH, PLAYBOOK, REGISTER_MAPS, HANG_RULES, 12 KNOWN_ISSUES)
- [ ] Implement all 8 methods + `get_known_issues()` in `soctriage/providers/nvidia/provider.py`
- [ ] Create `tests/fixtures/phase5/nvidia_h100_gsp_timeout.log`
- [ ] Create `tests/test_providers/test_nvidia_provider.py` (20 tests)
- [ ] Verify: 20 passed

## T7 — Registry Tests (12 tests) [needs T2–T6]
- [ ] Create `tests/test_providers/test_provider_registry.py` (12 tests)
- [ ] Verify: 12 passed

## T8 — Final Verification [needs T7]
- [ ] `python3 -m pytest -q` → ~803 passed, 6 xfailed, 0 failed
- [ ] `python3 -m mypy soctriage/providers/ --ignore-missing-imports` → 0 errors
- [ ] `git diff HEAD -- <locked files>` → empty (no changes)
- [ ] classify_ip() safety check on all 10 fixtures → no exceptions
- [ ] Commit: `soctriage phase 5: verified — 803 passed · 0 failed`
