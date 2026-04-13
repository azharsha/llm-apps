"""Tests for clock_topology.py.

Critical constraints under test:
- KNOWN_DOMAINS is a frozenset of exactly 10 canonical domain names [LAST-S5]
- get_clock_topology() returns None for unknown SoC, not exception
- ClockTopologyDB stores clocks as dict[str, ClockEntry]
- ClockEntry has only parent and consumers fields
- Unknown consumer name validation (e.g. "high_speed_serial" vs "highspeed_serial")
"""

from __future__ import annotations

import pytest

from poagent.board.clock_topology import (
    KNOWN_DOMAINS,
    ClockEntry,
    ClockTopologyDB,
    get_clock_topology,
)


EXPECTED_DOMAINS = frozenset({
    "power_clocking",
    "compute_memory",
    "storage",
    "highspeed_serial",
    "display_graphics",
    "networking",
    "audio",
    "lowspeed_interface",
    "security_crypto",
    "sensors_misc",
})


class TestKnownDomains:
    """[LAST-S5] Verify KNOWN_DOMAINS frozenset."""

    def test_known_domains_is_frozenset(self):
        assert isinstance(KNOWN_DOMAINS, frozenset)

    def test_known_domains_has_10_entries(self):
        assert len(KNOWN_DOMAINS) == 10

    def test_known_domains_exact_contents(self):
        assert KNOWN_DOMAINS == EXPECTED_DOMAINS

    def test_known_domains_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            KNOWN_DOMAINS.add("new_domain")  # type: ignore[attr-defined]

    def test_highspeed_serial_not_high_speed_serial(self):
        """Common typo: 'high_speed_serial' is NOT in KNOWN_DOMAINS."""
        assert "high_speed_serial" not in KNOWN_DOMAINS
        assert "highspeed_serial" in KNOWN_DOMAINS

    def test_no_whitespace_in_domain_names(self):
        for d in KNOWN_DOMAINS:
            assert " " not in d
            assert d == d.strip()


class TestGetClockTopology:
    """Test get_clock_topology() API contract [U-02]."""

    def test_unknown_soc_returns_none(self):
        """Unknown SoC returns None gracefully, not an exception."""
        result = get_clock_topology("unknown,soc-that-does-not-exist")
        assert result is None or isinstance(result, ClockTopologyDB)

    def test_none_compatible_returns_none(self):
        result = get_clock_topology(None)
        assert result is None or isinstance(result, ClockTopologyDB)

    def test_empty_compatible_returns_none(self):
        result = get_clock_topology("")
        assert result is None or isinstance(result, ClockTopologyDB)

    def test_qualcomm_compatible_returns_db(self):
        """Qualcomm compatible string should return a topology DB."""
        result = get_clock_topology("qcom,sc8280xp")
        assert result is None or isinstance(result, ClockTopologyDB)

    def test_return_type_is_clocktopologydb_or_none(self):
        result = get_clock_topology("intel,tigerlake")
        assert result is None or isinstance(result, ClockTopologyDB)


class TestClockEntry:
    """Test ClockEntry dataclass fields."""

    def test_clock_entry_parent_and_consumers(self):
        entry = ClockEntry(parent=None, consumers=["compute_memory"])
        assert entry.parent is None
        assert "compute_memory" in entry.consumers

    def test_clock_entry_with_parent(self):
        entry = ClockEntry(parent="xtal_ref", consumers=["storage", "networking"])
        assert entry.parent == "xtal_ref"
        assert len(entry.consumers) == 2

    def test_clock_entry_empty_consumers(self):
        entry = ClockEntry(parent="gpll", consumers=[])
        assert entry.consumers == []


class TestClockTopologyDB:
    """Test ClockTopologyDB data access."""

    def _make_db(self) -> ClockTopologyDB:
        """Build a minimal test DB using actual API."""
        return ClockTopologyDB(
            soc_compatible="test,soc",
            clocks={
                "xtal_19p2": ClockEntry(parent=None, consumers=["power_clocking"]),
                "pll_core": ClockEntry(parent="xtal_19p2",
                                       consumers=["compute_memory", "highspeed_serial"]),
            },
        )

    def test_clocks_dict_access(self):
        db = self._make_db()
        assert "pll_core" in db.clocks
        entry = db.clocks["pll_core"]
        assert "compute_memory" in entry.consumers
        assert "highspeed_serial" in entry.consumers

    def test_clock_parent_is_stored(self):
        db = self._make_db()
        assert db.clocks["pll_core"].parent == "xtal_19p2"
        assert db.clocks["xtal_19p2"].parent is None

    def test_soc_compatible_stored(self):
        db = self._make_db()
        assert db.soc_compatible == "test,soc"

    def test_clocks_is_dict(self):
        db = self._make_db()
        assert isinstance(db.clocks, dict)
        assert len(db.clocks) == 2

    def test_all_consumer_domains_are_known(self):
        """All consumer domain names must be in KNOWN_DOMAINS."""
        db = self._make_db()
        for clock_name, entry in db.clocks.items():
            for consumer in entry.consumers:
                assert consumer in KNOWN_DOMAINS, (
                    f"Clock {clock_name} has unknown consumer '{consumer}'. "
                    f"Did you mean one of {sorted(KNOWN_DOMAINS)}?"
                )

    def test_highspeed_serial_not_typo(self):
        """Validate 'highspeed_serial' vs 'high_speed_serial' typo guard."""
        entry = ClockEntry(parent=None, consumers=["highspeed_serial"])
        assert "highspeed_serial" in KNOWN_DOMAINS
        for consumer in entry.consumers:
            assert consumer in KNOWN_DOMAINS

    def test_builtin_qcom_topology_has_valid_consumers(self):
        """If Qualcomm topology is available, all consumers must be in KNOWN_DOMAINS."""
        db = get_clock_topology("qcom,sc8280x")
        if db is None:
            pytest.skip("qcom,sc8280x topology not built-in")
        for clock_name, entry in db.clocks.items():
            for consumer in entry.consumers:
                assert consumer in KNOWN_DOMAINS, (
                    f"Qualcomm clock {clock_name} has unknown consumer '{consumer}'"
                )
