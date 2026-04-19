"""test_samsung_platform_rules.py — Phase 2d: samsung_platform.yaml (3 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/samsung_platform.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "arm64", "unknown", [], [])

def test_exynos_mif_fail():        assert _r().match("exynos-busmon: MIF error", _ctx()) == "exynos_mif_fail"
def test_exynos_tmu_event():       assert _r().match("exynos_tmu: thermal trip", _ctx()) == "exynos_tmu_event"
def test_samsung_platform_event(): assert _r().match("samsung_iommu: page fault", _ctx()) == "samsung_platform_event"
