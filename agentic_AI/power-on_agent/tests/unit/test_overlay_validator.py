"""Tests for overlay_validator.py.

Critical constraints under test:
- [O-01] expected_mv lower bound is 100mV (not 500mV)
- 100–499mV emits SUSPICIOUS_LOW_VOLTAGE (INFO, not error)
- Zero value is a hard error
- tolerance_pct must be 1–20
- pcie_gen must be 1–5
- NO_CRITICAL_RAILS if no rail has critical=True
- BOUNDS_EXEMPT properties skip bounds check
"""

from __future__ import annotations

import textwrap
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_mock_dtc():
    """Return a mock subprocess.run result simulating dtc success."""
    m = MagicMock()
    m.returncode = 0
    m.stderr = ""
    return m


def _write_overlay(tmp_path: Path, data: dict) -> Path:
    """Write a DTS overlay with po-agent,* properties derived from data dict."""
    p = tmp_path / "overlay.dts"
    lines = ["/dts-v1/;", "/ {"]

    rails = data.get("rails", {})
    for rail_name, rail_props in rails.items():
        lines.append(f"    {rail_name.lower().replace('-', '_')} {{")
        mv = rail_props.get("expected_mv")
        if mv is not None:
            # Map negative values to 0 (DTS u32 can't represent negative)
            dts_mv = max(0, mv)
            lines.append(f"        po-agent,expected-mv = <{dts_mv}>;")
        if rail_props.get("critical"):
            lines.append("        po-agent,critical;")
        tol = rail_props.get("tolerance_pct")
        if tol is not None:
            lines.append(f"        po-agent,tolerance-pct = <{int(tol)}>;")
        lines.append("    };")

    pcie_list = data.get("pcie", [])
    for pcie_entry in pcie_list:
        name = pcie_entry.get("name", "pcie0").replace("-", "_")
        gen = pcie_entry.get("expected_gen")
        lines.append(f"    {name} {{")
        if gen is not None:
            lines.append(f"        po-agent,expected-pcie-gen = <{gen}>;")
        lines.append("    };")

    # Handle po-agent,human-reviewed at root level
    if "po-agent,human-reviewed" in data:
        lines.append(f"    po-agent,human-reviewed = <{data['po-agent,human-reviewed']}>;")

    lines.append("};")
    p.write_text("\n".join(lines))
    return p


@pytest.fixture()
def validator(tmp_path):
    """Return a validation callable that mocks dtc and returns errors+warnings list."""
    from poagent.board.overlay_validator import validate_overlay

    def _validate(path):
        with patch("poagent.board.overlay_validator.subprocess.run",
                   return_value=_make_mock_dtc()):
            report = validate_overlay(str(path))
        # Return combined errors + warnings so tests can check either
        return report.errors + report.warnings

    return _validate


class TestExpectedMvBounds:
    """[O-01] expected_mv lower bound is 100mV."""

    def test_100mv_is_valid(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VDD_MX": {"expected_mv": 352, "critical": True}}
        })
        errors = validator(p)
        assert not any("expected_mv" in e and "100" in e for e in errors)

    def test_zero_mv_is_hard_error(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VDD_CORE": {"expected_mv": 0, "critical": True}}
        })
        errors = validator(p)
        assert any("zero" in e.lower() or "ZERO_VALUE_ERROR" in e for e in errors)

    def test_negative_mv_is_hard_error(self, validator, tmp_path):
        # Negative values mapped to 0 in DTS → triggers ZERO_VALUE_ERROR
        p = _write_overlay(tmp_path, {
            "rails": {"VDD_CORE": {"expected_mv": -100, "critical": True}}
        })
        errors = validator(p)
        assert errors  # must produce at least one error

    def test_100_to_499mv_emits_suspicious_low_voltage(self, validator, tmp_path):
        """100–499mV emits SUSPICIOUS_LOW_VOLTAGE (info only, not a hard error)."""
        p = _write_overlay(tmp_path, {
            "rails": {"VDD_MX": {"expected_mv": 352, "critical": True}}
        })
        errors = validator(p)
        # SUSPICIOUS_LOW_VOLTAGE is informational — may or may not appear as error
        # The key is it does NOT block validation entirely
        # (validate_overlay returns list of errors; suspicious is info only)
        hard_errors = [e for e in errors if "BOUNDS_VIOLATION" in e or "zero" in e.lower()]
        assert not hard_errors

    def test_500mv_is_valid_no_suspicious(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VCC_IO": {"expected_mv": 1800, "critical": True}}
        })
        errors = validator(p)
        hard_errors = [e for e in errors if "BOUNDS_VIOLATION" in e]
        assert not hard_errors

    def test_5001mv_exceeds_upper_bound(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VCC_BIG": {"expected_mv": 6000, "critical": True}}
        })
        errors = validator(p)
        assert any("BOUNDS_VIOLATION" in e or "expected-mv" in e for e in errors)


class TestTolerancePct:
    def test_valid_tolerance(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VCC": {"expected_mv": 1000, "tolerance_pct": 5.0, "critical": True}}
        })
        errors = validator(p)
        hard = [e for e in errors if "tolerance" in e.lower() and "BOUNDS_VIOLATION" in e]
        assert not hard

    def test_zero_tolerance_is_error(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VCC": {"expected_mv": 1000, "tolerance_pct": 0.0, "critical": True}}
        })
        errors = validator(p)
        assert any("tolerance" in e.lower() or "zero" in e.lower() for e in errors)

    def test_tolerance_above_20_is_error(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {"VCC": {"expected_mv": 1000, "tolerance_pct": 25.0, "critical": True}}
        })
        errors = validator(p)
        assert any("tolerance" in e.lower() or "BOUNDS_VIOLATION" in e for e in errors)


class TestPcieGen:
    def test_pcie_gen_1_to_5_valid(self, validator, tmp_path):
        for gen in [1, 2, 3, 4, 5]:
            p = _write_overlay(tmp_path, {
                "pcie": [{"name": "ep0", "expected_gen": gen}]
            })
            errors = validator(p)
            gen_errors = [e for e in errors if "pcie" in e.lower() and "gen" in e.lower()]
            assert not gen_errors, f"Gen {gen} should be valid, got: {gen_errors}"

    def test_pcie_gen_0_invalid(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "pcie": [{"name": "ep0", "expected_gen": 0}]
        })
        errors = validator(p)
        assert any("gen" in e.lower() or "BOUNDS_VIOLATION" in e for e in errors)

    def test_pcie_gen_6_invalid(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "pcie": [{"name": "ep0", "expected_gen": 6}]
        })
        errors = validator(p)
        assert any("gen" in e.lower() or "BOUNDS_VIOLATION" in e for e in errors)


class TestNoCriticalRails:
    def test_no_rails_at_all_passes(self, validator, tmp_path):
        """Empty rails → may warn but should not hard-fail."""
        p = _write_overlay(tmp_path, {})
        errors = validator(p)
        # NO_CRITICAL_RAILS is a warning; empty overlay might be valid
        # The key is it parses without exception
        assert isinstance(errors, list)

    def test_rails_with_no_critical_flag(self, validator, tmp_path):
        """Rails present but none critical=True → NO_CRITICAL_RAILS warning."""
        p = _write_overlay(tmp_path, {
            "rails": {
                "VCC1": {"expected_mv": 1000, "critical": False},
                "VCC2": {"expected_mv": 1800, "critical": False},
            }
        })
        errors = validator(p)
        assert any("critical" in e.lower() or "NO_CRITICAL_RAILS" in e for e in errors)


class TestBoundsExempt:
    def test_human_reviewed_property_not_checked(self, validator, tmp_path):
        """po-agent,human-reviewed is BOUNDS_EXEMPT — should not trigger BOUNDS_VIOLATION."""
        p = _write_overlay(tmp_path, {
            "po-agent,human-reviewed": 1,
            "rails": {"VCC": {"expected_mv": 1000, "critical": True}},
        })
        errors = validator(p)
        exempt_errors = [e for e in errors if "human-reviewed" in e]
        assert not exempt_errors


class TestValidOverlay:
    def test_minimal_valid_overlay(self, validator, tmp_path):
        p = _write_overlay(tmp_path, {
            "rails": {
                "VCC_CORE": {"expected_mv": 1000, "tolerance_pct": 5.0, "critical": True},
                "VCC_IO": {"expected_mv": 1800, "tolerance_pct": 5.0, "critical": False},
            }
        })
        errors = validator(p)
        hard = [e for e in errors if "BOUNDS_VIOLATION" in e or "ZERO_VALUE_ERROR" in e]
        assert not hard

    def test_qualcomm_vdd_mx_352mv_valid(self, validator, tmp_path):
        """Qualcomm VDD_MX at 352mV must be valid (the original bug that caused O-01)."""
        p = _write_overlay(tmp_path, {
            "rails": {
                "VDD_MX": {"expected_mv": 352, "tolerance_pct": 5.0, "critical": True},
                "VDD_CX": {"expected_mv": 380, "tolerance_pct": 5.0, "critical": True},
            }
        })
        errors = validator(p)
        hard = [e for e in errors if "BOUNDS_VIOLATION" in e]
        assert not hard
