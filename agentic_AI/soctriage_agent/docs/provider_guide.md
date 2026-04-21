# SoCTriage — Adding a New SoC Provider

This guide walks through adding full support for a new SoC vendor (e.g., MediaTek, Samsung).

## Step 1: Create the provider directory

```bash
mkdir -p soctriage/providers/mediatek
touch soctriage/providers/mediatek/__init__.py
touch soctriage/providers/mediatek/provider.py
```

## Step 2: Implement `SoCProvider`

```python
# soctriage/providers/mediatek/provider.py
from soctriage.core.soc_provider import SoCProvider

class MediaTekProvider(SoCProvider):
    @classmethod
    def name(cls) -> str:
        return "mediatek"

    def detect(self, raw_log: str) -> float:
        """Return confidence score 0.0–1.0 that this log is from a MediaTek SoC."""
        score = 0.0
        if "mediatek" in raw_log.lower() or "mtk" in raw_log.lower():
            score += 0.5
        if "mt8" in raw_log.lower():  # MT8xxx chip family
            score += 0.3
        if "APU" in raw_log or "TINYSYS" in raw_log:
            score += 0.2
        return min(score, 1.0)

    def chip_gen(self, raw_log: str) -> str:
        if "mt8195" in raw_log.lower():
            return "mt8195"
        if "mt8192" in raw_log.lower():
            return "mt8192"
        return "mediatek_unknown"

    def arch(self, raw_log: str) -> str:
        return "arm64"  # MediaTek SoCs are ARM64
```

## Step 3: Register the provider

The `ProviderRegistry.auto_discover()` call in `cli.py` and `providers/__init__.py`
automatically discovers any `provider.py` file under `soctriage/providers/`. No
registration code is needed.

Verify auto-discovery works:

```bash
soctriage --list-providers
# Should include: mediatek
```

## Step 4: Add YAML token rules

Create `soctriage/core/token_rules/mediatek.yaml`:

```yaml
- token_type: mtk_apu_crash
  priority: 145
  match_mode: any
  patterns:
    - "APU: fatal error"
    - "TINYSYS: crash"
  arch: arm64
  providers: [mediatek]
  notes: "MediaTek APU (AI processor) crash events"

- token_type: mtk_scp_timeout
  priority: 120
  match_mode: any
  patterns:
    - "SCP: IPI timeout"
    - "scp_ipi: timeout"
  arch: any
  providers: [mediatek]
  notes: "MediaTek SCP (System Control Processor) IPI timeout"
```

See [yaml_guide.md](yaml_guide.md) for the full rule schema.

## Step 5: Write tests

Create `tests/test_providers/test_mediatek_provider.py`:

```python
from soctriage.providers.mediatek.provider import MediaTekProvider

def test_detect_mediatek_log():
    p = MediaTekProvider()
    assert p.detect("mediatek: init complete, mt8195 detected") > 0.5

def test_detect_rejects_intel_log():
    p = MediaTekProvider()
    assert p.detect("i915 0000:00:02.0: GuC firmware") < 0.1

def test_chip_gen_mt8195():
    p = MediaTekProvider()
    assert p.chip_gen("Booting mt8195 board") == "mt8195"

def test_arch_is_arm64():
    p = MediaTekProvider()
    assert p.arch("") == "arm64"
```

## Step 6: Run tests

```bash
pytest tests/test_providers/test_mediatek_provider.py -v
pytest tests/ -q  # full suite — must stay green
```

## Provider API Reference

```python
class SoCProvider:
    @classmethod
    def name(cls) -> str: ...          # lowercase vendor name, e.g. "mediatek"
    def detect(self, raw_log: str) -> float: ...  # confidence 0.0–1.0
    def chip_gen(self, raw_log: str) -> str: ...  # chip generation string
    def arch(self, raw_log: str) -> str: ...      # "x86_64" | "arm64" | "unknown"
```

The provider with the highest `detect()` score is selected. `GenericProvider` always
returns `0.1` as a fallback.
