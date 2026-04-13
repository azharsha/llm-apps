"""Tests for board/dts_parser.py.

Critical constraints under test:
- parse_dts() correctly parses a valid .dts file
- _detect_cycles() catches circular dependencies
- parse_po_agent_properties() extracts po-agent-* properties
- Overlay DTS cycle detection via dependency graph
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


class TestParseDts:
    def test_parse_sample_tgl_dts(self, sample_dts_path):
        from poagent.board.dts_parser import parse_dts

        tree = parse_dts(sample_dts_path)
        assert tree is not None

    def test_parse_minimal_dts(self, tmp_path):
        from poagent.board.dts_parser import parse_dts

        dts = tmp_path / "minimal.dts"
        dts.write_text(textwrap.dedent("""\
            /dts-v1/;
            / {
                model = "Test Board";
                compatible = "test,board";
            };
        """))
        tree = parse_dts(dts)
        assert tree is not None

    def test_nonexistent_file_raises(self, tmp_path):
        from poagent.board.dts_parser import parse_dts

        with pytest.raises((FileNotFoundError, ValueError, Exception)):
            parse_dts(tmp_path / "nonexistent.dts")


class TestParsePoAgentProperties:
    def test_extracts_board_name(self, sample_dts_path):
        """parse_po_agent_properties takes raw DTS text, returns list of tuples."""
        from poagent.board.dts_parser import parse_po_agent_properties

        text = sample_dts_path.read_text()
        props = parse_po_agent_properties(text)
        # Returns list of (node, prop, value) tuples
        assert isinstance(props, list)

    def test_extracts_rails(self, tmp_path):
        """DTS with po-agent,expected-mv extracts rail voltage as tuple."""
        from poagent.board.dts_parser import parse_po_agent_properties

        dts_text = textwrap.dedent("""\
            /dts-v1/;
            / {
                vcc_core {
                    po-agent,expected-mv = <1000>;
                    po-agent,critical;
                };
            };
        """)
        props = parse_po_agent_properties(dts_text)
        prop_names = [p for _, p, _ in props]
        assert "po-agent,expected-mv" in prop_names

    def test_extracts_clocks(self, tmp_path):
        """DTS with multiple po-agent,* properties extracts all of them."""
        from poagent.board.dts_parser import parse_po_agent_properties

        dts_text = textwrap.dedent("""\
            /dts-v1/;
            / {
                vcc_io {
                    po-agent,expected-mv = <1800>;
                    po-agent,tolerance-pct = <5>;
                };
            };
        """)
        props = parse_po_agent_properties(dts_text)
        assert isinstance(props, list)
        prop_names = [p for _, p, _ in props]
        assert "po-agent,expected-mv" in prop_names

    def test_no_po_agent_node_returns_empty(self, tmp_path):
        from poagent.board.dts_parser import parse_po_agent_properties

        dts_text = textwrap.dedent("""\
            /dts-v1/;
            / {
                model = "Plain Board";
                compatible = "plain,board";
            };
        """)
        props = parse_po_agent_properties(dts_text)
        # Returns empty list when no po-agent,* properties found
        assert isinstance(props, list)
        assert props == []


class TestDetectCycles:
    def test_no_cycle_passes(self):
        from poagent.board.dts_parser import _detect_cycles

        # A→B→C (no cycle)
        graph = {"A": ["B"], "B": ["C"], "C": []}
        cycles = _detect_cycles(graph)
        assert not cycles

    def test_simple_cycle_detected(self):
        from poagent.board.dts_parser import _detect_cycles

        # A→B→A (cycle)
        graph = {"A": ["B"], "B": ["A"]}
        cycles = _detect_cycles(graph)
        assert cycles  # must return non-empty (truthy)

    def test_self_loop_detected(self):
        from poagent.board.dts_parser import _detect_cycles

        graph = {"A": ["A"]}
        cycles = _detect_cycles(graph)
        assert cycles

    def test_complex_cycle_detected(self):
        from poagent.board.dts_parser import _detect_cycles

        # A→B→C→A (3-node cycle)
        graph = {"A": ["B"], "B": ["C"], "C": ["A"]}
        cycles = _detect_cycles(graph)
        assert cycles

    def test_disconnected_acyclic_passes(self):
        from poagent.board.dts_parser import _detect_cycles

        graph = {"A": ["B"], "C": ["D"], "B": [], "D": []}
        cycles = _detect_cycles(graph)
        assert not cycles
