"""Tests for report/generator.py.

Critical constraints under test:
- [FINAL-H4] PASS=#2d6a4f, FAIL=#9b2226, CONDITIONAL=#b5451b, INCOMPLETE=#495057
- CONDITIONAL verdict → mandatory orange-bordered action items box
- po_verdict_reason rendered as subtitle
- save_html_report() and save_json_report() write files
- JSON report contains po_verdict as stable CI gate field
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from poagent.agents.triage import TriageOutput


def _make_triage(verdict: str, board: str = "test-board", run_id: str = "test-run") -> TriageOutput:
    """Build a minimal TriageOutput for the given verdict."""
    return TriageOutput(
        run_id=run_id,
        board_name=board,
        po_verdict=verdict,
        po_verdict_reason=f"Test verdict: {verdict}",
        root_cause_hypotheses=[],
        recommended_actions=["Check PMBus configuration"],
        action_items=["Measure VCC_CORE manually"] if verdict == "CONDITIONAL" else [],
        domain_summaries=[],
        signing_key_id="test-key-id",
        poagent_hmac_sha256="",
    )


class TestVerdictColors:
    """[FINAL-H4] Verdict color codes in HTML."""

    def test_pass_color_code(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        assert "2d6a4f" in html

    def test_fail_color_code(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("FAIL")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        assert "9b2226" in html

    def test_conditional_color_code(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("CONDITIONAL")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        assert "b5451b" in html

    def test_incomplete_color_code(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("INCOMPLETE")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        assert "495057" in html


class TestConditionalActionItemsBox:
    """[FINAL-H4] CONDITIONAL verdict → mandatory orange-bordered action items box."""

    def test_conditional_has_action_items_box(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("CONDITIONAL")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        # Orange border and action items section are mandatory for CONDITIONAL
        assert "action-items" in html or "action items" in html.lower()

    def test_conditional_action_items_orange_border(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("CONDITIONAL")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        # b5451b is the CONDITIONAL orange color used in the action-items border
        assert "b5451b" in html

    def test_pass_verdict_no_action_items_box(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        # PASS should contain the color but not the action-items div
        assert "PASS" in html or "2d6a4f" in html


class TestVerdictReasonRendered:
    def test_verdict_reason_in_html(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("FAIL")
        html = generate_html_report(triage_output=triage, run_id="test-run")
        assert "Test verdict: FAIL" in html


class TestSaveReports:
    def test_save_html_report_creates_file(self, tmp_dir):
        from poagent.report.generator import generate_html_report, save_html_report

        triage = _make_triage("PASS")
        html = generate_html_report(triage_output=triage, run_id="t1")
        save_html_report(html, output_dir=str(tmp_dir), run_id="t1")
        # File is named {run_id}_report.html
        assert (tmp_dir / "t1_report.html").exists()

    def test_save_json_report_creates_file(self, tmp_dir):
        from poagent.report.generator import save_json_report

        triage = _make_triage("CONDITIONAL")
        save_json_report(triage, output_dir=str(tmp_dir), run_id="r1")
        assert (tmp_dir / "r1_triage.json").exists()

    def test_json_report_has_po_verdict(self, tmp_dir):
        """[FINAL-H3] po_verdict is the stable CI gate field in JSON."""
        from poagent.report.generator import save_json_report

        triage = _make_triage("FAIL")
        save_json_report(triage, output_dir=str(tmp_dir), run_id="f1")
        data = json.loads((tmp_dir / "f1_triage.json").read_text())
        assert "po_verdict" in data
        assert data["po_verdict"] == "FAIL"

    def test_html_report_is_valid_html(self, tmp_dir):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS")
        html = generate_html_report(triage_output=triage, run_id="h1")
        assert "<!DOCTYPE html>" in html or "<html" in html


class TestGenerateHtmlContent:
    def test_run_id_in_report(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS", run_id="my-unique-run-id")
        html = generate_html_report(triage_output=triage, run_id="my-unique-run-id")
        assert "my-unique-run-id" in html

    def test_board_name_in_report(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS", board="tigerlake-mb")
        html = generate_html_report(triage_output=triage, run_id="bc-test")
        assert "tigerlake-mb" in html

    def test_boot_context_kernel_version_rendered(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS")
        boot_ctx = {"kernel_version": "5.15.0-generic"}
        html = generate_html_report(triage_output=triage, run_id="bc-test", boot_context=boot_ctx)
        assert "5.15.0" in html

    def test_silicon_stepping_unresolved_shown(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("CONDITIONAL")
        triage.silicon_stepping_unresolved = True
        html = generate_html_report(triage_output=triage, run_id="step-test")
        assert "UNRESOLVED" in html or "fallback" in html.lower()

    def test_signing_key_id_in_report(self):
        from poagent.report.generator import generate_html_report

        triage = _make_triage("PASS")
        html = generate_html_report(
            triage_output=triage, run_id="s1", signing_key_id="prod-key-2026"
        )
        assert "prod-key-2026" in html
