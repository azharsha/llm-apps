"""test_soc_platform_rules.py — Phase 2b: soc_platform.yaml (7 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/soc_platform.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(arch="any"):
    return TokenContext(1, arch, "unknown", [], [])

def test_wdt_event():       assert _r().match("QCOM watchdog: bark received", _ctx()) == "wdt_event"
def test_mce_error():       assert _r().match("mce: [Hardware Error]: Machine check", _ctx(arch="x86_64")) == "mce_error"
def test_mce_not_arm64():   assert _r().match("MCE event", _ctx(arch="arm64")) != "mce_error"
def test_nmi_event():       assert _r().match("Uhhuh. NMI received for unknown reason", _ctx()) == "nmi_event"
def test_irq_error():       assert _r().match("nobody cared about IRQ 42", _ctx()) == "irq_error"
def test_gic_event():       assert _r().match("GIC: Sending SGI to all CPUs", _ctx()) == "gic_event"
def test_acpi_event():      assert _r().match("ACPI Error: Method execution failed", _ctx()) == "acpi_event"
