"""
plugin.py — Phase 2e: Python plugin API for custom token rules.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from soctriage.core.token_rule import TokenRule, TokenRuleRegistry

__all__ = ["register_rule", "PluginLoader"]

_PLUGIN_REGISTRY: list[TokenRule] = []


def register_rule(priority: int = 50) -> Callable[[type], type]:
    """
    Decorator that registers a class's token rule attributes into the plugin registry.

    Usage:
        @register_rule(priority=140)
        class MyRule:
            token_type = "my_event"
            patterns   = ["MY_HW_FATAL"]
            arch       = "arm64"
            providers  = ["qualcomm"]
    """
    def decorator(cls: type) -> type:
        token_type = getattr(cls, "token_type", None)
        if not token_type:
            raise ValueError(
                f"Plugin class {cls.__name__!r} must define a non-empty 'token_type'"
            )
        rule = TokenRule(
            token_type       = str(token_type),
            priority         = priority,
            match_mode       = str(getattr(cls, "match_mode", "any")),
            patterns         = list(getattr(cls, "patterns", [])),
            exclude_patterns = list(getattr(cls, "exclude_patterns", [])),
            arch             = str(getattr(cls, "arch", "any")),
            providers        = list(getattr(cls, "providers", ["any"])),
            notes            = str(getattr(cls, "notes", "")),
        )
        _PLUGIN_REGISTRY.append(rule)
        return cls
    return decorator


class PluginLoader:
    """Executes Python plugin files and injects @register_rule rules into a registry."""

    @staticmethod
    def load_file(path: Path, registry: TokenRuleRegistry) -> int:
        """
        Execute a plugin file and inject all @register_rule rules into registry.
        Clears _PLUGIN_REGISTRY after loading to prevent cross-load pollution.
        Returns the count of rules loaded.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location("soctriage_plugin", path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load plugin file: {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        count = 0
        for rule in _PLUGIN_REGISTRY:
            registry.register(rule)
            count += 1
        _PLUGIN_REGISTRY.clear()
        return count

    @staticmethod
    def load_directory(plugins_dir: Path, registry: TokenRuleRegistry) -> int:
        """Load all *.py files from plugins_dir, skipping files starting with _."""
        count = 0
        for py_file in sorted(plugins_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            count += PluginLoader.load_file(py_file, registry)
        return count
