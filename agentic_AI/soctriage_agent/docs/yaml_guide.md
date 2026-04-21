# SoCTriage — YAML Token Rule Guide

YAML token rules are the primary way to teach SoCTriage about new kernel error patterns.
Each `.yaml` file under `soctriage/core/token_rules/` maps to a kernel subsystem.

## Rule Schema

```yaml
- token_type: my_event           # Required. snake_case. Vendor-prefix only if vendor-specific.
  priority: 95                   # Required. Integer 1–200. Higher = matched first.
  match_mode: any                # Required. See match modes below.
  patterns:                      # Required. List of strings or {regex: "..."} dicts.
    - "exact string to match"
    - regex: "^anchored_regex$"
  arch: any                      # Optional. any | x86_64 | arm64. Default: any.
  providers: any                 # Optional. any | [intel, amd, qualcomm, nvidia, generic].
  notes: "Why this rule exists"  # Optional. For documentation.
```

## Match Modes

| Mode | Behaviour |
|---|---|
| `any` | Match if ANY pattern fires on the current line |
| `all` | Match if ALL patterns fire (across a context window) |
| `context` | Match if pattern fires AND at least one recent token matches context |
| `negative` | Match if ANY pattern fires AND no negative_patterns fire |

## Priority Guide

| Range | Use For |
|---|---|
| 180–200 | pstore / ramoops / bootloader — must win over everything |
| 150–179 | Vendor-specific platform crashes (ADSP, PSP, TEE) |
| 130–149 | RAS, CXL, PCIe AER, security violations |
| 100–129 | Core kernel, GPU hang, SoC bring-up signals |
| 70–99 | Device drivers, storage, network |
| 40–69 | Informational, warnings, generic events |
| 1–39 | Fallback / unknown — **never use in custom rules** |

## Example: GPU hang rule

```yaml
- token_type: gpu_hang
  priority: 115
  match_mode: any
  patterns:
    - "GPU HANG"
    - "gpu hang detected"
    - regex: "GPU-[0-9a-f]+ hang"
  arch: any
  providers: any
  notes: "Generic GPU hang — covers AMD, NVIDIA, Intel"
```

## Example: Vendor-specific rule

```yaml
- token_type: qcom_adsp_crash
  priority: 160
  match_mode: any
  patterns:
    - "ADSP: crash"
    - "adsp_err: fatal"
    - regex: "subsys-restart: Resetting the adsp"
  arch: arm64
  providers: [qualcomm]
  notes: "Qualcomm ADSP subsystem crash — triggers SSR"
```

## Naming Conventions

- Generic (any vendor): `pcie_error`, `gpu_hang`, `memory_ecc_error`
- Vendor-specific: `qcom_adsp_crash`, `amd_psp_event`, `intel_pmc_event`
- Never: `amdgpu_token`, `i915_event` (driver name as prefix — too narrow)

## What NOT to add to YAML

- Rules that need multi-line state across many lines → use Python plugin API
- Rules that need chip_gen-specific branching → use Python plugin API
- Rules that call external APIs or read files
- Rules matching > 50% of all kernel log lines (too broad)

## Testing your rule

```bash
# Run the token rule test suite
pytest tests/test_token_rules/ -v

# Quick check against a real log
soctriage --token-rule "my_event:exact string" crash.log --no-llm
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full workflow.
