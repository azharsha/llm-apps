"""
provider_registry.py — Phase 2

Discovers, registers, and selects SoC providers.
auto_discover() walks providers/*/provider.py and instantiates each provider class.
detect_provider() calls .detect() on all registered providers and returns the
highest-confidence match, falling back to GenericProvider if all scores < 0.3.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

from soctriage.core.soc_provider import SoCProvider

__all__ = ["ProviderRegistry", "PROVIDER_PRIORITY"]

logger = logging.getLogger(__name__)

# Discovery order determines tie-breaking when two providers return the same score.
PROVIDER_PRIORITY: list[str] = ["intel", "qualcomm", "amd", "nvidia", "generic"]

# Minimum detect() score to be considered a valid match (non-generic).
_MIN_DETECT_CONFIDENCE: float = 0.3


class ProviderRegistry:

    def __init__(self) -> None:
        self._providers: list[SoCProvider] = []

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, provider: SoCProvider) -> None:
        """Add a provider instance to the registry."""
        self._providers.append(provider)
        logger.debug("Registered provider: %s", provider.name())

    # ── Auto-discovery ────────────────────────────────────────────────────────

    def auto_discover(self, providers_dir: Path) -> None:
        """
        Walk providers/*/provider.py, import each module, find the concrete
        SoCProvider subclass, instantiate it, and register it.

        Providers are registered in PROVIDER_PRIORITY order; subdirectories
        not in PROVIDER_PRIORITY are appended after the known ones.
        """
        # Collect subdirs that contain a provider.py
        found: dict[str, Path] = {}
        for subdir in providers_dir.iterdir():
            if subdir.is_dir() and (subdir / "provider.py").exists():
                found[subdir.name] = subdir / "provider.py"

        # Load in PROVIDER_PRIORITY order, then any remainder
        ordered_names = [n for n in PROVIDER_PRIORITY if n in found]
        remainder = [n for n in sorted(found) if n not in PROVIDER_PRIORITY]

        for name in ordered_names + remainder:
            self._load_provider_module(name, found[name])

    def _load_provider_module(self, name: str, module_path: Path) -> None:
        """Import a single provider module and register its SoCProvider subclass."""
        # Derive dotted module name from path relative to the package root.
        # e.g.  soctriage/providers/intel/provider.py → soctriage.providers.intel.provider
        try:
            parts = module_path.parts
            # Find "soctriage" anchor and build dotted name from there
            anchor = next(
                (i for i, p in enumerate(parts) if p == "soctriage"),
                None,
            )
            if anchor is None:
                # Fallback: use importlib.util for paths outside the package
                module = _load_by_path(name, module_path)
            else:
                dotted = ".".join(parts[anchor:]).removesuffix(".py")
                module = importlib.import_module(dotted)
        except Exception as exc:
            logger.warning("Failed to import provider %r from %s: %r", name, module_path, exc)
            return

        # Find the first concrete SoCProvider subclass in the module
        for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, SoCProvider)
                and obj is not SoCProvider
                and not inspect.isabstract(obj)
            ):
                try:
                    instance = obj()
                    self.register(instance)
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate provider class %s from %s: %r",
                        obj.__name__, module_path, exc,
                    )
                return  # only register the first concrete class per module

        logger.warning("No concrete SoCProvider subclass found in %s", module_path)

    # ── Provider detection ────────────────────────────────────────────────────

    def detect_provider(self, raw_log: str) -> SoCProvider:
        """
        Call .detect() on all registered providers.
        Return the highest-confidence match.
        Falls back to GenericProvider if all non-generic scores < _MIN_DETECT_CONFIDENCE
        or if no providers are registered.
        """
        if not self._providers:
            logger.warning("No providers registered — using GenericProvider fallback")
            from soctriage.providers.generic.provider import GenericProvider
            return GenericProvider()

        best_provider: SoCProvider | None = None
        best_score: float = -1.0
        generic_fallback: SoCProvider | None = None

        for provider in self._providers:
            try:
                score = provider.detect(raw_log)
            except Exception as exc:
                logger.debug("Provider %s raised during detect(): %r", provider.name(), exc)
                score = 0.0

            if provider.name() == "Generic":
                generic_fallback = provider
                continue  # only use generic if no real provider matches

            if score > best_score:
                best_score = score
                best_provider = provider

        if best_provider is not None and best_score >= _MIN_DETECT_CONFIDENCE:
            logger.debug(
                "Selected provider %r (score=%.2f)", best_provider.name(), best_score
            )
            return best_provider

        # No vendor-specific provider matched — use generic fallback
        if generic_fallback is not None:
            logger.debug("No vendor match (best=%.2f) — using GenericProvider", best_score)
            return generic_fallback

        # Absolute fallback: instantiate GenericProvider even if not registered
        from soctriage.providers.generic.provider import GenericProvider
        return GenericProvider()

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_providers(self) -> list[str]:
        """Return list of registered provider names."""
        return [p.name() for p in self._providers]


# ── Helper: load module from file path without package anchoring ──────────────


def _load_by_path(name: str, path: Path):  # type: ignore[return]
    """Load a Python module from an arbitrary file path using importlib.util."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"_soctriage_provider_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module
