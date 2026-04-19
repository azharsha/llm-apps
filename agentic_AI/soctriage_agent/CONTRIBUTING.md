# Contributing to SoCTriage

## Adding a New Token Type via YAML

SoCTriage uses YAML rule files that map 1:1 to Linux kernel subsystem directories.
Adding a new token type takes under 5 minutes and requires zero Python changes.

### Step 1: Find or create the right YAML file

Find the kernel source directory where the error originates:

| Kernel path | YAML file |
|---|---|
| `drivers/gpu/drm/` | `core/token_rules/gpu.yaml` |
| `drivers/soc/qcom/` | `core/token_rules/qualcomm_platform.yaml` |
| `drivers/soc/amd/` | `core/token_rules/amd_platform.yaml` |
| New subsystem | `core/token_rules/<subsystem>.yaml` (create it) |

### Step 2: Add your rule

```yaml
- token_type: my_new_event        # snake_case; vendor-prefix only if vendor-specific
  priority: 95                    # see priority guide below
  match_mode: any                 # any | all | context | negative
  patterns:
    - "exact string to match"
    - regex: "^anchored_regex_here"
  arch: any                       # any | x86_64 | arm64
  providers: any                  # any | [intel, amd, qualcomm, nvidia, generic]
  notes: "What this catches and why"
```

### Step 3: Write a test

Create or update `tests/test_token_rules/test_<subsystem>_rules.py`:

```python
from pathlib import Path
from soctriage.core.token_rule import TokenRuleRegistry, TokenContext

def test_my_new_event_detected():
    registry = TokenRuleRegistry()
    registry.load_yaml(Path("soctriage/core/token_rules/<subsystem>.yaml"))
    ctx = TokenContext(line_no=1, arch="any", chip_gen="unknown",
                      provider="unknown", recent_tokens=[], recent_types=[])
    assert registry.match("exact string to match", ctx) == "my_new_event"
```

### Step 4: Run tests

```bash
pytest tests/test_token_rules/ -v
```

### Step 5: Open a PR

Title format: `yaml: add <token_type> to <yaml_file>`
Example: `yaml: add cxl_gen3_fatal to cxl.yaml`

---

## Adding a New Token Type via Python Plugin

Use a Python plugin when your rule needs:
- Multi-line state
- chip_gen-specific logic
- Context from preceding tokens

### Plugin file format

```python
# plugins/my_soc_rules.py
from soctriage.core.plugin import register_rule

@register_rule(priority=145)
class CxlGen3FatalRule:
    """CXL 3.0 fatal errors not yet in cxl.yaml"""
    token_type = "cxl_gen3_fatal"
    patterns   = ["CXL 3.0: fatal", "cxl_gen3: unrecoverable"]
    arch       = "any"
    providers  = ["any"]
```

### Load at runtime

```bash
soctriage --input crash.log --plugin plugins/my_soc_rules.py
```

### Inline rule injection (one-off)

```bash
# Single pattern
soctriage --input crash.log --token-rule "cxl_event:cxl_mem:"

# Multiple patterns for the same token type
soctriage --input crash.log \
  --token-rule "cxl_event:cxl_mem:" \
  --token-rule "cxl_event:CXL: error"
```

---

## Priority Guide

| Range | Use For |
|---|---|
| 180–200 | pstore / ramoops / bootloader (must beat everything) |
| 150–179 | Vendor-specific platform crashes (ADSP, PSP, TEE) |
| 130–149 | RAS, CXL, security violations |
| 100–129 | Core kernel, GPU, SoC bring-up signals |
| 70–99 | Device drivers, storage, network |
| 40–69 | Info, warning, generic |
| 1–39 | Fallback / unknown — **never use in custom rules** |

---

## Token Naming Conventions

- Generic: `pcie_error`, `gpu_event`, `timeout_event`
- Vendor-specific: `qcom_adsp_crash`, `amd_psp_event`, `intel_pmc_event`
- Never: `amdgpu_token`, `i915_pcie_event` (driver name as prefix)

**Vendor-specific vs generic:**
- Pattern only fires on one vendor's hardware → add `providers: [vendor]`
- Pattern could fire on any vendor → `providers: any`
- Pattern only fires on arm64 → add `arch: arm64`

---

## What NOT to add to YAML

- Rules that need multi-line state → use Python plugin API instead
- Rules that need chip_gen-specific logic → use Python plugin API
- Rules that call external APIs or read files

---

## PR Checklist

- [ ] Rule added to the correct YAML file (or new YAML created)
- [ ] `token_type` follows naming conventions (snake_case, no driver-name prefix)
- [ ] `priority` set in the correct range per the priority guide
- [ ] Test added in `tests/test_token_rules/test_<subsystem>_rules.py`
- [ ] `pytest tests/test_token_rules/ -v` passes locally
- [ ] PR title follows `yaml: add <token_type> to <yaml_file>` format
