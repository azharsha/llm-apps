from __future__ import annotations


def get_all_providers() -> list:
    """Return one instance of every registered provider."""
    from soctriage.core.provider_registry import ProviderRegistry
    from pathlib import Path
    reg = ProviderRegistry()
    reg.auto_discover(Path(__file__).parent)
    return reg._providers
