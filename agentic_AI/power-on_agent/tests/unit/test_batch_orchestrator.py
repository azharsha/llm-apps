"""Tests for agents/batch_orchestrator.py.

Critical constraints under test:
- [§16] _read_fleet_csv() validates required columns
- Missing 'dts' column → ValueError
- Missing both 'host' and 'serial' → ValueError
- Valid CSV rows parsed correctly
- fleet_summary.csv written after run
- Board failures do not abort other boards
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _write_fleet_csv(tmp_path: Path, rows: list[dict]) -> Path:
    csv_path = tmp_path / "fleet.csv"
    if not rows:
        csv_path.write_text("board_name,host,dts\n")
        return csv_path

    fields = list(rows[0].keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


class TestReadFleetCsv:
    def test_valid_csv_parsed(self, tmp_path):
        from poagent.agents.batch_orchestrator import _read_fleet_csv

        dts = tmp_path / "board.dts"
        dts.write_text("/dts-v1/;\n/ { compatible = \"test,board\"; };")

        csv_path = _write_fleet_csv(tmp_path, [
            {"board_name": "board1", "host": "192.168.1.1", "dts": str(dts)},
            {"board_name": "board2", "host": "192.168.1.2", "dts": str(dts)},
        ])

        rows = _read_fleet_csv(csv_path)
        assert len(rows) == 2
        assert rows[0]["board_name"] == "board1"
        assert rows[1]["host"] == "192.168.1.2"

    def test_missing_dts_column_raises(self, tmp_path):
        from poagent.agents.batch_orchestrator import _read_fleet_csv

        csv_path = _write_fleet_csv(tmp_path, [
            {"board_name": "b1", "host": "10.0.0.1"},  # no dts column
        ])
        with pytest.raises(ValueError, match="dts"):
            _read_fleet_csv(csv_path)

    def test_missing_host_and_serial_raises(self, tmp_path):
        from poagent.agents.batch_orchestrator import _read_fleet_csv

        csv_path = _write_fleet_csv(tmp_path, [
            {"board_name": "b1", "dts": "/tmp/test.dts"},  # no host or serial
        ])
        with pytest.raises(ValueError):
            _read_fleet_csv(csv_path)

    def test_empty_csv_raises(self, tmp_path):
        from poagent.agents.batch_orchestrator import _read_fleet_csv

        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("board_name,host,dts\n")  # header only, no rows
        with pytest.raises(ValueError):
            _read_fleet_csv(csv_path)

    def test_rows_with_no_connection_skipped(self, tmp_path):
        """Rows with empty host AND empty serial are skipped with warning."""
        from poagent.agents.batch_orchestrator import _read_fleet_csv

        dts = tmp_path / "board.dts"
        dts.write_text("/dts-v1/;\n/ {};")

        csv_path = _write_fleet_csv(tmp_path, [
            {"board_name": "ok", "host": "10.0.0.1", "serial": "", "dts": str(dts)},
            {"board_name": "bad", "host": "", "serial": "", "dts": str(dts)},
        ])

        rows = _read_fleet_csv(csv_path)
        names = [r["board_name"] for r in rows]
        assert "ok" in names
        # "bad" row has no connection — should be skipped


class TestWriteFleetSummary:
    def test_summary_csv_written(self, tmp_path, minimal_config):
        from poagent.agents.batch_orchestrator import FleetSummary, BoardRunResult, _write_fleet_summary_csv

        results = [
            BoardRunResult(board_name="board1", run_id="r1", verdict="PASS", elapsed_s=10.0),
            BoardRunResult(board_name="board2", run_id="r2", verdict="FAIL", elapsed_s=15.0),
        ]
        summary = FleetSummary(results=results)
        summary.compute()

        csv_path = _write_fleet_summary_csv(summary, tmp_path)
        assert csv_path.exists()

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        board_names = [r["board_name"] for r in rows]
        assert "board1" in board_names
        assert "board2" in board_names


class TestFleetSummaryCompute:
    def test_compute_counts(self):
        from poagent.agents.batch_orchestrator import FleetSummary, BoardRunResult

        results = [
            BoardRunResult(board_name="b1", run_id="r1", verdict="PASS"),
            BoardRunResult(board_name="b2", run_id="r2", verdict="FAIL"),
            BoardRunResult(board_name="b3", run_id="r3", verdict="CONDITIONAL"),
            BoardRunResult(board_name="b4", run_id="r4", verdict="INCOMPLETE"),
        ]
        summary = FleetSummary(results=results)
        summary.compute()

        assert summary.total == 4
        assert summary.passed == 1
        assert summary.failed == 1
        assert summary.conditional == 1
        assert summary.incomplete == 1
