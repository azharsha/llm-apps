"""test_pm_domains_rules.py — Phase 2d: pm_domains.yaml (2 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/pm_domains.yaml")
def _r(): r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(): return TokenContext(1, "any", "unknown", [], [])

def test_pm_domain_fail():   assert _r().match("genpd: power on failed", _ctx()) == "pm_domain_fail"
def test_pm_domain_event():  assert _r().match("pd_provider: domain registered", _ctx()) == "pm_domain_event"
