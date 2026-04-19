"""test_dma_engine_rules.py — Phase 2b: dma_engine.yaml (4 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/dma_engine.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx():
    return TokenContext(1, "any", "unknown", [], [])

def test_dma_timeout():        assert _r().match("DMA transfer timeout on channel 0", _ctx()) == "dma_timeout"
def test_dma_channel_fail():   assert _r().match("DMA channel request failed for audio", _ctx()) == "dma_channel_fail"
def test_dma_engine_event():   assert _r().match("dmaengine: allocating channel", _ctx()) == "dma_engine_event"
def test_bam_dma_timeout():    assert _r().match("bam_dma: timeout on descriptor", _ctx()) == "dma_timeout"
