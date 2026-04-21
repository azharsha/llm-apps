# SPEC — Phase 8.0.0: Production Hardening, Packaging & Distribution
## SoCTriage v8.0.0 · Final Phase · PyPI · Docker · CI · Docs · Benchmarks

---

## PRD v1.0.0 vs. Reality: Six Discrepancies

### R-1: Benchmark `_run_pipeline()` calls `report()` with wrong type and wrong kwarg

PRD §7 benchmark code:
```python
return report(cascade, no_llm=True, fmt="json")
```

`report()` in `reporter.py` has signature:
```python
def report(agent_result: AgentResult, *, fmt, output, pretty, include_raw) -> str
```

Two bugs:
- `cascade` is a `CascadeResult` (returned by `analyse()`), but `report()` expects `AgentResult`
- `no_llm=True` is not a parameter of `report()`

**Fix:** Use `render_json(cascade)` (Phase 5 function that takes `CascadeResult` directly), or
construct a minimal `AgentResult`. `render_json` is the correct choice for benchmarking
since it's already imported in `reporter.py` and represents the serialisation cost.

```python
from soctriage.core.reporter import render_json

def _run_pipeline(path, registry):
    line_iter, _ = open_log(str(path))
    tokens  = list(tokenize(line_iter, rule_registry=registry))
    events  = list(classify_all(assemble(iter(tokens))))
    cascade = analyse(events)
    return render_json(cascade)
```

### R-2: Shell completions + man page reference `_build_parser` — function is `build_parser`

PRD §5 completions:
```bash
python -m shtab --shell=bash soctriage.cli._build_parser
```

PRD §6 man page:
```bash
argparse-manpage --function _build_parser
```

`cli.py` exports `build_parser()` (public, no underscore). There is no `_build_parser`.

**Fix:** Use `build_parser` everywhere:
```bash
python -m shtab --shell=bash soctriage.cli.build_parser
argparse-manpage --pyfile soctriage/cli.py --function build_parser ...
```

### R-3: Pre-commit yamllint path uses `tokenrules` — actual directory is `token_rules`

PRD §8 pre-commit:
```yaml
files: soctriage/core/tokenrules/.*\.yaml$
```

Actual directory: `soctriage/core/token_rules/` (with underscore).

**Fix:**
```yaml
files: soctriage/core/token_rules/.*\.yaml$
```

### R-4: `mypy.ini` conflicts with `[tool.mypy]` in `pyproject.toml`

PRD §3 adds `[tool.mypy]` to `pyproject.toml`. However `mypy.ini` already exists at the
project root. mypy's config priority: `mypy.ini` wins over `pyproject.toml`. If both exist
with different settings, the `[tool.mypy]` block in `pyproject.toml` is silently ignored.

Additionally, PRD's `[tool.mypy]` uses a single global `ignore_missing_imports = true`,
but the existing `mypy.ini` uses per-module ignores (`[mypy-anthropic]`, `[mypy-httpx]`).
The existing per-module approach is more precise.

**Fix:** Remove `mypy.ini` and consolidate into `pyproject.toml` `[tool.mypy]` with
per-module overrides preserved:
```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_any_generics = false

[[tool.mypy.overrides]]
module = "tests.*"
ignore_errors = true

[[tool.mypy.overrides]]
module = ["anthropic", "httpx"]
ignore_missing_imports = true
```

### R-5: `pyproject.toml` build-system switch from `setuptools` to `hatchling`

Current `pyproject.toml` uses `setuptools` + `soctriage.egg-info/`. PRD wants `hatchling`.
The switch is safe — `hatchling` is a standard build backend. Existing `soctriage.egg-info/`
directory should be deleted after the switch (it's setuptools-specific).

Also: current `pyproject.toml` has `rich>=13.0` as a top-level dependency and
`anthropic>=0.40` as a top-level dep. PRD drops `rich` (not used in source code —
confirmed by grep) and moves `anthropic` to `[llm]` extras only. `httpx` moves to
top-level (needed for OllamaClient).

**Fix:** Replace build-system, update dependencies as per PRD §3, delete `mypy.ini`
(handled in R-4), delete `soctriage.egg-info/`.

### R-6: `pytest-benchmark` imports `tokenize` from `soctriage.core.tokenizer` —
actual public API uses `rule_registry` kwarg but `TokenRuleRegistry` import path differs

PRD benchmark imports:
```python
from soctriage.core.tokenizer import tokenize, TokenRuleRegistry
```

`TokenRuleRegistry` lives in `soctriage.core.token_rule` (not `tokenizer`):
```python
from soctriage.core.token_rule import TokenRuleRegistry
```

**Fix:** Correct the import in `benchmarks/bench_pipeline.py`:
```python
from soctriage.core.token_rule import TokenRuleRegistry
```

---

## 1. Files Changed

| File | Action | Notes |
|---|---|---|
| `pyproject.toml` | Modified | hatchling, classifiers, extras, tool configs |
| `mypy.ini` | Deleted | Consolidated into `[tool.mypy]` in pyproject.toml |
| `soctriage.egg-info/` | Deleted | setuptools artifact, no longer needed |
| `Dockerfile` | New | Multi-stage builder + runtime |
| `docker-compose.yml` | New | Dev + offline + Ollama profiles |
| `completions/soctriage.bash` | New | Generated via shtab |
| `completions/soctriage.zsh` | New | Generated via shtab |
| `completions/soctriage.fish` | New | Generated via shtab |
| `Makefile` | New | completions + install-completions targets |
| `man/soctriage.1` | New | Generated via argparse-manpage |
| `benchmarks/bench_pipeline.py` | New | pytest-benchmark suite (7 tests) |
| `benchmarks/__init__.py` | New | Empty — makes benchmarks a package |
| `.pre-commit-config.yaml` | New | ruff, mypy, pytest-smoke, yamllint |
| `.devcontainer/devcontainer.json` | New | VS Code / Codespaces dev container |
| `CHANGELOG.md` | New | All 8 phases, dates, test counts |
| `CONTRIBUTING.md` | Modified | Already exists — expand with arch map |
| `docs/quickstart.md` | New | 7-section install + first-run guide |
| `docs/architecture.md` | New | Phase map, data flow, module tree |
| `docs/provider_guide.md` | New | How to add a SoCProvider |
| `docs/yaml_guide.md` | New | How to write YAML token rules |
| `docs/cli_reference.md` | New | CLI flags reference |
| `docs/api_reference.md` | New | Public Python API |
| `.github/workflows/pr.yml` | New | Matrix test 3.11 / 3.12 / 3.13 |
| `.github/workflows/release.yml` | New | PyPI + Docker publish on tag |
| `tests/test_packaging.py` | New | 15 packaging smoke tests |

**Do NOT modify:** `soctriage/core/*.py`, `soctriage/providers/**`, `soctriage/cli.py`,
any `tests/test_*.py`, any `soctriage/core/token_rules/*.yaml`.

---

## 2. `pyproject.toml` — Final State

Full replacement. Key changes vs current:
- Build backend: `setuptools` → `hatchling`
- Version: `0.1.0` → `1.0.0`
- Top-level deps: remove `rich`, remove `anthropic`, add `httpx>=0.27.0`
- Add classifiers (12 entries)
- `[llm]` extras: `anthropic>=0.25.0`
- `[dev]` extras: add `pytest-benchmark>=4.0`, `argparse-manpage>=4.5`, `shtab>=1.7`,
  `pre-commit>=3.7`, `pip-audit`
- Add `[tool.hatch.build.targets.wheel]`
- Add `[tool.pytest.ini_options]` (replaces any setup.cfg pytest config)
- Add `[tool.mypy]` with `[[tool.mypy.overrides]]` (replaces mypy.ini)
- Add `[tool.ruff]` section

---

## 3. Benchmark Fixes (R-1, R-6)

`benchmarks/bench_pipeline.py` — corrected from PRD:

```python
from soctriage.core.input_handler import open_log
from soctriage.core.token_rule    import TokenRuleRegistry   # R-6 fix
from soctriage.core.tokenizer     import tokenize
from soctriage.core.assembler     import assemble, LogToken
from soctriage.core.classifier    import classify_all
from soctriage.core.cascade       import analyse
from soctriage.core.reporter      import render_json          # R-1 fix

def _run_pipeline(path, registry):
    line_iter, _ = open_log(str(path))
    tokens  = list(tokenize(line_iter, rule_registry=registry))
    events  = list(classify_all(assemble(iter(tokens))))
    cascade = analyse(events)
    return render_json(cascade)                               # R-1 fix
```

`LogEvent` fixture in `test_bench_cascade_10k_events` — add missing `tokens` field and
`kernel_ver` as `None` (already present in PRD — just confirm it matches the dataclass):

```python
LogEvent(
    event_id=i, event_type="gpuhang", severity="error",
    subsystem="gpu", ip_block="GFXHUB", tokens=[],          # empty list OK
    start_line=i*10, end_line=i*10+9, arch="x86_64",
    chip_gen="amd_cdna3", kernel_ver="6.8.0-45-generic",
    confidence=0.8, raw_text="gpu hang",
    has_call_trace=False, has_registers=False,
    provider_name="amd"
)
```

LogEvent signature (verified): all 16 fields match. PRD benchmark is correct here.

---

## 4. Shell Completions + Man Page Fixes (R-2)

### Makefile
```makefile
.PHONY: completions install-completions man

completions:
	mkdir -p completions
	python -m shtab --shell=bash soctriage.cli.build_parser > completions/soctriage.bash
	python -m shtab --shell=zsh  soctriage.cli.build_parser > completions/soctriage.zsh
	python -m shtab --shell=fish soctriage.cli.build_parser > completions/soctriage.fish

install-completions: completions
	install -Dm644 completions/soctriage.bash /etc/bash_completion.d/soctriage
	install -Dm644 completions/soctriage.zsh  /usr/share/zsh/site-functions/_soctriage
	install -Dm644 completions/soctriage.fish /usr/share/fish/completions/soctriage.fish

man:
	mkdir -p man
	argparse-manpage \
		--pyfile soctriage/cli.py \
		--function build_parser \
		--author "SD Move" \
		--project-name soctriage \
		--url "https://github.com/sdmove/soctriage" \
		> man/soctriage.1
```

For CI (no `make` required), completions and man page are generated once and committed
as static files. Tests in `test_packaging.py` verify their existence, not generation.

---

## 5. Pre-Commit Fix (R-3)

```yaml
# .pre-commit-config.yaml
      - id: yamllint
        args: [-d, "{extends: relaxed, rules: {line-length: {max: 120}}}"]
        files: soctriage/core/token_rules/.*\.yaml$    # R-3 fix: underscore
```

---

## 6. `test_packaging.py` — Implementation Notes

The 15 tests require careful implementation:

### Import-based tests (no subprocess)
```python
def test_package_importable_after_install():
    import soctriage
    assert soctriage is not None

def test_version_matches_pyproject_toml():
    import importlib.metadata, tomllib
    ver = importlib.metadata.version("soctriage")
    with open("pyproject.toml", "rb") as f:
        toml_ver = tomllib.load(f)["project"]["version"]
    assert ver == toml_ver

def test_all_core_modules_importable():
    import soctriage.core.input_handler, soctriage.core.tokenizer
    import soctriage.core.assembler, soctriage.core.classifier
    import soctriage.core.cascade, soctriage.core.reporter
    import soctriage.core.html_renderer, soctriage.core.agent
```

### subprocess-based tests
```python
def test_cli_help_exits_0():
    result = subprocess.run(["soctriage", "--help"], capture_output=True)
    assert result.returncode == 0

def test_cli_version_exits_0_prints_version():
    result = subprocess.run(["soctriage", "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "soctriage" in result.stdout

def test_cli_list_providers_exits_0():
    result = subprocess.run(["soctriage", "--list-providers"], capture_output=True)
    assert result.returncode == 0

def test_cli_no_args_exits_usage():
    result = subprocess.run(["soctriage"], capture_output=True)
    assert result.returncode in (2, 3)  # argparse or EXITUSAGE

def test_soctriage_command_in_path():
    result = subprocess.run(["which", "soctriage"], capture_output=True)
    assert result.returncode == 0
```

### Distribution artifact tests
These tests require `python -m build` to have been run. In CI this runs first. Locally,
skip with `@pytest.mark.skipif(not Path("dist").exists(), reason="dist/ not built")`:

```python
def test_wheel_contains_all_modules():
    wheels = list(Path("dist").glob("*.whl"))
    # unzip and check soctriage/ tree is present
    ...

def test_wheel_contains_yaml_rule_files():
    # verify token_rules/*.yaml are in the wheel
    ...
```

---

## 7. CHANGELOG.md Structure

All 8 phases, reverse-chronological order:

```markdown
# Changelog

## [1.0.0] — 2026-04-21 (Phase 8)
Production hardening: PyPI packaging, Docker, CI matrix, benchmarks, docs, completions.
Tests: 1083 passed · 0 failed.

## [0.8.0] — 2026-04-20 (Phase 7)
Reporter + CLI hardening: report(), HTML renderer, exit codes.
Tests: 1048 passed · 6 xfailed.

## [0.7.0] — Phase 6
Agentic AI: run_agent(), Anthropic tool-calling loop.
Tests: 968 passed.

...
```

---

## 8. GitHub Actions — Implementation Notes

### PR gate (`pr.yml`)
- `pip-audit` line: `pip-audit --require-hashes -r requirements-locked.txt || true` —
  `requirements-locked.txt` must exist. Either generate it in CI
  (`pip freeze > requirements-locked.txt`) or replace with `pip-audit --desc on`.
  Since no `requirements-locked.txt` exists in the repo, use:
  ```yaml
  - name: pip-audit (security scan)
    run: pip install pip-audit && pip-audit --desc on || true
  ```

### Release workflow (`release.yml`)
- Docker push requires `DOCKER_TOKEN` secret — document in `CONTRIBUTING.md`.
- `pip install soctriage-*.whl[llm]` in Dockerfile: shell glob expansion in RUN requires
  a shell. The PRD combines `pip install` and `rm -f` in one RUN with `&&`. Use:
  ```dockerfile
  RUN pip install --no-cache-dir /tmp/soctriage-*.whl[llm] && rm -f /tmp/*.whl
  ```
  This is already what the PRD shows — it's valid as a shell command.

---

## 9. Acceptance Criteria

| Group | Count | Verification |
|---|---|---|
| `test_packaging.py` | 15 | `pytest tests/test_packaging.py` |
| `benchmarks/bench_pipeline.py` | 7 | `pytest benchmarks/ --benchmark-only` |
| Docs completeness | 8 | Checked in `test_packaging.py` (file existence + section headers) |
| CI config validity | 5 | Checked via `test_packaging.py` (file existence) |
| **Total new** | **35** | |
| **Grand total** | **~1083** | Phase 0–7 (1048) + Phase 8 (35) |

Combined gate: **~1083 passed · 0 failed · mypy 0 errors · ruff 0 violations**
