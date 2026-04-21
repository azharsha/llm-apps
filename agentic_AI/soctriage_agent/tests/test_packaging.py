"""
test_packaging.py — Phase 8 packaging and distribution smoke tests.

AC-P8-P-01 to AC-P8-P-15
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ── Package metadata (5) ──────────────────────────────────────────────────────


def test_package_importable_after_install() -> None:
    import soctriage  # noqa: F401


def test_version_matches_pyproject_toml() -> None:
    import importlib.metadata
    import tomllib

    installed = importlib.metadata.version("soctriage")
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        toml_ver = tomllib.load(fh)["project"]["version"]
    assert installed == toml_ver


def test_cli_entry_point_registered() -> None:
    import importlib.metadata

    eps = importlib.metadata.entry_points(group="console_scripts")
    names = [ep.name for ep in eps]
    assert "soctriage" in names


def test_all_provider_modules_importable() -> None:
    import soctriage.providers.intel.provider      # noqa: F401
    import soctriage.providers.qualcomm.provider   # noqa: F401
    import soctriage.providers.amd.provider        # noqa: F401
    import soctriage.providers.nvidia.provider     # noqa: F401
    import soctriage.providers.generic.provider    # noqa: F401


def test_all_core_modules_importable() -> None:
    import soctriage.core.input_handler    # noqa: F401
    import soctriage.core.tokenizer        # noqa: F401
    import soctriage.core.token_rule       # noqa: F401
    import soctriage.core.assembler        # noqa: F401
    import soctriage.core.classifier       # noqa: F401
    import soctriage.core.cascade          # noqa: F401
    import soctriage.core.reporter         # noqa: F401
    import soctriage.core.html_renderer    # noqa: F401
    import soctriage.core.agent            # noqa: F401
    import soctriage.core.hardware_decode  # noqa: F401


# ── CLI invocation (5) ────────────────────────────────────────────────────────


def test_cli_help_exits_0() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "soctriage.cli", "--help"],
        capture_output=True,
    )
    assert result.returncode == 0


def test_cli_version_exits_0_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "soctriage.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "soctriage" in (result.stdout + result.stderr)


def test_cli_list_providers_exits_0() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "soctriage.cli", "--list-providers"],
        capture_output=True,
    )
    assert result.returncode == 0


def test_cli_no_args_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "soctriage.cli"],
        capture_output=True,
    )
    assert result.returncode != 0


def test_soctriage_module_has_cli_main() -> None:
    from soctriage.cli import main

    assert callable(main)


# ── Distribution artifacts (5) ────────────────────────────────────────────────


_DIST_EXISTS = (PROJECT_ROOT / "dist").exists() and bool(
    list((PROJECT_ROOT / "dist").glob("*.whl"))
)


@pytest.mark.skipif(not _DIST_EXISTS, reason="dist/*.whl not built — run `python -m build` first")
def test_wheel_contains_all_modules() -> None:
    import zipfile

    wheels = list((PROJECT_ROOT / "dist").glob("*.whl"))
    assert wheels, "No wheel found in dist/"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert any(n.startswith("soctriage/") for n in names)
    assert any("soctriage/core/reporter.py" in n for n in names)


@pytest.mark.skipif(not _DIST_EXISTS, reason="dist/*.whl not built — run `python -m build` first")
def test_wheel_contains_yaml_rule_files() -> None:
    import zipfile

    wheels = list((PROJECT_ROOT / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert any("token_rules" in n and n.endswith(".yaml") for n in names)


@pytest.mark.skipif(not _DIST_EXISTS, reason="dist/ not built — run `python -m build` first")
def test_sdist_buildable() -> None:
    sdists = list((PROJECT_ROOT / "dist").glob("*.tar.gz"))
    assert sdists, "No sdist found in dist/ — run `python -m build --sdist`"


def test_extras_llm_importable_without_anthropic() -> None:
    """Importing core modules works even without the [llm] extra installed."""
    from soctriage.core.agent import run_agent  # noqa: F401


def test_extras_dev_markers_defined() -> None:
    import tomllib

    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    extras = data["project"]["optional-dependencies"]
    assert "llm" in extras
    assert "dev" in extras
    assert any("anthropic" in dep for dep in extras["llm"])
    assert any("pytest-benchmark" in dep for dep in extras["dev"])


# ── Docs completeness (8) ─────────────────────────────────────────────────────

_DOCS = [
    "docs/quickstart.md",
    "docs/architecture.md",
    "docs/provider_guide.md",
    "docs/yaml_guide.md",
    "docs/cli_reference.md",
    "docs/api_reference.md",
]


@pytest.mark.parametrize("doc", _DOCS)
def test_doc_file_exists(doc: str) -> None:
    path = PROJECT_ROOT / doc
    assert path.exists(), f"Missing doc: {doc}"
    assert path.stat().st_size > 100, f"Doc too small (likely stub): {doc}"


def test_quickstart_has_required_sections() -> None:
    content = (PROJECT_ROOT / "docs/quickstart.md").read_text()
    for section in ["Installation", "First run", "LLM", "Docker", "JSON"]:
        assert section in content, f"quickstart.md missing section: {section}"


# ── CI config (5) ────────────────────────────────────────────────────────────


def test_pr_workflow_exists() -> None:
    assert (PROJECT_ROOT / ".github/workflows/pr.yml").exists()


def test_release_workflow_exists() -> None:
    assert (PROJECT_ROOT / ".github/workflows/release.yml").exists()


def test_precommit_config_exists() -> None:
    assert (PROJECT_ROOT / ".pre-commit-config.yaml").exists()


def test_dockerfile_exists() -> None:
    assert (PROJECT_ROOT / "Dockerfile").exists()


def test_devcontainer_exists() -> None:
    assert (PROJECT_ROOT / ".devcontainer/devcontainer.json").exists()
