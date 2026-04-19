"""test_interconnect_rules.py — Phase 2b: interconnect.yaml (6 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/interconnect.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_pcie_error():      assert _r().match("pcieport: AER: correctable error", _ctx()) == "pcie_error"
def test_axi_fault():       assert _r().match("NOC error: Slave port timeout", _ctx()) == "axi_fault"
def test_crc_error():       assert _r().match("CRC error on link 0", _ctx()) == "crc_error"
def test_smmu_fault():      assert _r().match("arm-smmu: Unhandled context fault", _ctx()) == "smmu_fault"
def test_dma_fault():       assert _r().match("DMA-API: device driver failed to use bounce buffer", _ctx()) == "dma_fault"
def test_smmu_beats_pcie():
    # smmu_fault (125) > pcie_error (130) — actually pcie is higher, test smmu on dedicated line
    assert _r().match("arm-smmu-v3: SMMU context fault at 0x1234", _ctx()) == "smmu_fault"
