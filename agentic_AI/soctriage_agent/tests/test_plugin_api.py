"""
tests/test_plugin_api.py — Phase 2e: 10 plugin API tests.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from soctriage.core import plugin as plugin_module
from soctriage.core.plugin import register_rule, PluginLoader
from soctriage.core.token_rule import TokenRuleRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_plugin(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


_SIMPLE_PLUGIN = """\
from soctriage.core.plugin import register_rule

@register_rule(priority=100)
class SimpleRule:
    token_type = "simple_event"
    patterns   = ["SIMPLE_SIGNAL"]
    arch       = "any"
    providers  = ["any"]
"""

_ARCH_PLUGIN = """\
from soctriage.core.plugin import register_rule

@register_rule(priority=120)
class ArchRule:
    token_type = "arm64_event"
    patterns   = ["ARM64_FATAL"]
    arch       = "arm64"
    providers  = ["any"]
"""

_PROVIDERS_PLUGIN = """\
from soctriage.core.plugin import register_rule

@register_rule(priority=130)
class ProviderRule:
    token_type = "qcom_custom_event"
    patterns   = ["QCOM_SIGNAL"]
    arch       = "any"
    providers  = ["qualcomm"]
"""

_TWO_RULES_PLUGIN = """\
from soctriage.core.plugin import register_rule

@register_rule(priority=80)
class RuleA:
    token_type = "event_a"
    patterns   = ["SIGNAL_A"]

@register_rule(priority=90)
class RuleB:
    token_type = "event_b"
    patterns   = ["SIGNAL_B"]
"""

_NO_TOKEN_TYPE_PLUGIN = """\
from soctriage.core.plugin import register_rule

@register_rule(priority=50)
class BadRule:
    patterns = ["something"]
"""


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_register_rule_decorator_registers() -> None:
    initial = len(plugin_module._PLUGIN_REGISTRY)

    @register_rule(priority=50)
    class _TestRule:
        token_type = "decorator_test_event"
        patterns   = ["DECORATOR_TEST"]

    assert len(plugin_module._PLUGIN_REGISTRY) == initial + 1
    plugin_module._PLUGIN_REGISTRY.clear()


def test_register_rule_sets_priority() -> None:
    @register_rule(priority=155)
    class _PriorityRule:
        token_type = "priority_test_event"
        patterns   = ["PRIORITY_TEST"]

    added = plugin_module._PLUGIN_REGISTRY[-1]
    assert added.priority == 155
    plugin_module._PLUGIN_REGISTRY.clear()


def test_plugin_loader_load_file(tmp_path: Path) -> None:
    plugin_file = _make_plugin(tmp_path, "simple.py", _SIMPLE_PLUGIN)
    registry = TokenRuleRegistry()

    count = PluginLoader.load_file(plugin_file, registry)

    assert count == 1
    assert registry.rule_count() == 1


def test_plugin_loader_clears_registry_after_load(tmp_path: Path) -> None:
    plugin_file = _make_plugin(tmp_path, "simple.py", _SIMPLE_PLUGIN)
    registry = TokenRuleRegistry()
    PluginLoader.load_file(plugin_file, registry)

    assert plugin_module._PLUGIN_REGISTRY == []


def test_multiple_plugins_load_cleanly(tmp_path: Path) -> None:
    f = _make_plugin(tmp_path, "two.py", _TWO_RULES_PLUGIN)
    registry = TokenRuleRegistry()

    count = PluginLoader.load_file(f, registry)

    assert count == 2
    assert registry.rule_count() == 2


def test_plugin_arch_constraint_preserved(tmp_path: Path) -> None:
    f = _make_plugin(tmp_path, "arch.py", _ARCH_PLUGIN)
    registry = TokenRuleRegistry()
    PluginLoader.load_file(f, registry)

    rules = registry._rules
    assert len(rules) == 1
    assert rules[0].rule.arch == "arm64"


def test_plugin_providers_constraint_preserved(tmp_path: Path) -> None:
    f = _make_plugin(tmp_path, "providers.py", _PROVIDERS_PLUGIN)
    registry = TokenRuleRegistry()
    PluginLoader.load_file(f, registry)

    rules = registry._rules
    assert len(rules) == 1
    assert rules[0].rule.providers == ["qualcomm"]


def test_plugin_loader_load_directory(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "a_rules.py", _SIMPLE_PLUGIN)
    _make_plugin(tmp_path, "b_rules.py", _ARCH_PLUGIN)
    # This file starts with _ and must be skipped
    _make_plugin(tmp_path, "_ignored.py", _PROVIDERS_PLUGIN)

    registry = TokenRuleRegistry()
    count = PluginLoader.load_directory(tmp_path, registry)

    assert count == 2
    assert registry.rule_count() == 2


def test_plugin_invalid_missing_token_type_raises(tmp_path: Path) -> None:
    f = _make_plugin(tmp_path, "bad.py", _NO_TOKEN_TYPE_PLUGIN)
    registry = TokenRuleRegistry()

    with pytest.raises(ValueError, match="must define a non-empty 'token_type'"):
        PluginLoader.load_file(f, registry)
    plugin_module._PLUGIN_REGISTRY.clear()


def test_plugin_rule_count_increases(tmp_path: Path) -> None:
    registry = TokenRuleRegistry()
    assert registry.rule_count() == 0

    f = _make_plugin(tmp_path, "two.py", _TWO_RULES_PLUGIN)
    PluginLoader.load_file(f, registry)

    assert registry.rule_count() == 2
